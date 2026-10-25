"""
Async database layer — PostgreSQL + pgvector ONLY.

SQLite has been removed by design decision (2026-07-12): conversations, chats,
messages, usage and embeddings all live in PostgreSQL. `init_db()` raises a
clear error when no [database] section / RDI_DATABASE_URL is configured.

New in this version:
  • runs table       — checkpointed agent runs (plan → steps → status), so a
                        disconnected/killed run can be shown and resumed.
  • artifacts table  — registry of everything produced in a conversation
                        (images, PDFs, decks, sheets…) enabling cross-step
                        reuse ("build a PPT with those images").
  • embeddings API   — pgvector-backed store/search (cosine), 1536-dim.
"""
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import bcrypt as _bcrypt

from .config import get_config

# ── Connection pool ───────────────────────────────────────────────────────────

_pg_pool = None            # asyncpg.Pool, set in init_db()
_vector_ok: bool = False   # pgvector extension available


def _pool():
    if _pg_pool is None:
        raise RuntimeError(
            "Database not initialised — PostgreSQL is required. "
            "Configure [database] in config.ini or set RDI_DATABASE_URL."
        )
    return _pg_pool


def vector_available() -> bool:
    return _vector_ok


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_pw(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def _verify_pw(password: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


def _now() -> str:
    return datetime.utcnow().isoformat()


def _row(r) -> Optional[Dict]:
    return None if r is None else dict(r)


def _rows(rs) -> List[Dict]:
    return [dict(r) for r in rs]


# ── Model pricing table ($/1K tokens) ────────────────────────────────────────

_PRICING: Dict[str, tuple] = {
    "gpt-4o-mini":            (0.00015, 0.0006),
    "gpt-4o":                 (0.0025, 0.010),
    "gpt-4.1-nano":           (0.0001, 0.0004),
    "gpt-4.1-mini":           (0.0004, 0.0016),
    "gpt-4.1":                (0.002, 0.008),
    "gpt-5-nano":             (0.00005, 0.0004),
    "gpt-5-mini":             (0.00025, 0.002),
    "gpt-5-pro":              (0.075, 0.30),
    "gpt-5":                  (0.00125, 0.010),
    "o4-mini":                (0.0011, 0.0044),
    "o3-mini":                (0.0011, 0.0044),
    "o3-pro":                 (0.020, 0.080),
    "o3":                     (0.010, 0.040),
    "claude-opus-4":          (0.015, 0.075),
    "claude-sonnet-4":        (0.003, 0.015),
    "claude-haiku-4":         (0.0008, 0.004),
    "claude-3-5-sonnet":      (0.003, 0.015),
    "claude-3-7-sonnet":      (0.003, 0.015),
    "llama3-3-70b":           (0.00072, 0.00072),
    "llama3-2-90b":           (0.002, 0.002),
    "gemini-2.5-pro":         (0.00125, 0.010),
    "gemini-2.5-flash-lite":  (0.0000375, 0.00015),
    "gemini-2.5-flash":       (0.000075, 0.0003),
}
_PRICING_ORDERED = sorted(_PRICING.items(), key=lambda kv: len(kv[0]), reverse=True)


def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    for key, (inp, out) in _PRICING_ORDERED:
        if key in model:
            return round(inp * input_tokens / 1000 + out * output_tokens / 1000, 6)
    return 0.0


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                    TEXT PRIMARY KEY,
    username              TEXT UNIQUE NOT NULL,
    password_hash         TEXT,
    display_name          TEXT,
    email                 TEXT,
    auth_method           TEXT DEFAULT 'password',
    is_admin              INTEGER DEFAULT 0,
    is_active             INTEGER DEFAULT 1,
    workspace_mode        TEXT DEFAULT 'cloud',
    workspace_custom_path TEXT,
    created_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id                   TEXT PRIMARY KEY,
    user_id              TEXT NOT NULL,
    title                TEXT DEFAULT 'New Conversation',
    model                TEXT NOT NULL,
    cross_chat_reference BOOLEAN DEFAULT FALSE,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    tool_calls      TEXT,
    attachments     TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages (conversation_id, created_at);

CREATE TABLE IF NOT EXISTS attachments (
    id              TEXT PRIMARY KEY,
    user_id         TEXT,
    conversation_id TEXT,
    message_id      TEXT,
    filename        TEXT NOT NULL,
    content_type    TEXT NOT NULL,
    content         TEXT NOT NULL,
    storage_path    TEXT,
    size_bytes      BIGINT DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_events (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    conversation_id TEXT,
    model           TEXT NOT NULL,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    cost_usd        REAL DEFAULT 0.0,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_events (user_id, created_at);

-- Agent runs: checkpointed so the timeline survives disconnects/restarts and a
-- broken run is visibly resumable instead of silently lost.
CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    model           TEXT NOT NULL,
    fallback_model  TEXT,
    status          TEXT NOT NULL DEFAULT 'running',  -- running|waiting_permission|done|error|cancelled
    steps           JSONB NOT NULL DEFAULT '[]',
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    cost_usd        REAL DEFAULT 0.0,
    error           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_conv ON runs (conversation_id, created_at DESC);

-- Artifact registry: everything a conversation produces, so later steps can
-- reuse earlier outputs ("make a PPT with those images").
CREATE TABLE IF NOT EXISTS artifacts (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    run_id          TEXT,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,      -- image|pdf|pptx|docx|xlsx|code|file
    path            TEXT NOT NULL,      -- workspace-relative path
    size_bytes      BIGINT DEFAULT 0,
    meta            JSONB DEFAULT '{}',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_conv ON artifacts (conversation_id, created_at DESC);
"""

_MIGRATIONS = [
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS attachments TEXT",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS fallback_model TEXT",
    "ALTER TABLE attachments ADD COLUMN IF NOT EXISTS user_id TEXT",
    "ALTER TABLE attachments ADD COLUMN IF NOT EXISTS storage_path TEXT",
    "ALTER TABLE attachments ADD COLUMN IF NOT EXISTS size_bytes BIGINT DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS idx_attachments_user ON attachments (user_id, created_at DESC)",
]

_VECTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS embeddings (
    id              TEXT PRIMARY KEY,
    user_id         TEXT,
    conversation_id TEXT,
    content_hash    TEXT UNIQUE NOT NULL,
    content         TEXT NOT NULL,
    embedding       vector(1536),
    metadata        JSONB DEFAULT '{}',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_embeddings_conv ON embeddings (conversation_id);
"""

_VECTOR_ANN_INDEX = """
CREATE INDEX IF NOT EXISTS idx_embeddings_ann ON embeddings
USING hnsw (embedding vector_cosine_ops);
"""


# ── init_db ───────────────────────────────────────────────────────────────────

async def init_db() -> None:
    global _pg_pool, _vector_ok
    cfg = get_config()

    if not cfg.database:
        raise RuntimeError(
            "PostgreSQL is required (SQLite support was removed). "
            "Add a [database] section to config.ini or set RDI_DATABASE_URL, e.g.\n"
            "  RDI_DATABASE_URL=postgresql://rdi:rdi_dev_password@localhost:5432/rdi_ai\n"
            "Quick start: docker compose -f docker-compose.postgres.yml up -d"
        )

    import asyncpg
    schema = cfg.database.schema  # e.g. "rdi_ai" — auto-created below

    # Step 1: ensure the schema exists using a temporary plain connection
    # (we cannot set search_path to a schema that doesn't exist yet)
    _tmp = await asyncpg.connect(cfg.database.dsn)
    try:
        await _tmp.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    finally:
        await _tmp.close()

    # Step 2: create pool with search_path locked to our schema so every
    # unqualified table reference (users, messages, …) lands in the right place
    _pg_pool = await asyncpg.create_pool(
        cfg.database.dsn, min_size=2, max_size=10, command_timeout=60,
        server_settings={"search_path": schema},
    )
    async with _pg_pool.acquire() as conn:
        await conn.execute(_SCHEMA)
        for sql in _MIGRATIONS:
            await conn.execute(sql)
        # pgvector is expected. Degrade visibly (vector_available()) if absent.
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(_VECTOR_SCHEMA)
            try:
                await conn.execute(_VECTOR_ANN_INDEX)
            except Exception:
                pass  # hnsw needs pgvector >=0.5; exact scan still works
            _vector_ok = True
        except Exception as exc:
            _vector_ok = False
            print(f"[db] WARNING: pgvector unavailable ({exc}); embeddings disabled")
        await _seed_admin(conn, cfg.admin_username, cfg.admin_password)


async def _seed_admin(conn, username: str, password: str) -> None:
    if not username or not password:
        return  # no admin credentials in config.ini — skip seeding
    row = await conn.fetchrow("SELECT id FROM users WHERE username=$1", username)
    if not row:
        await conn.execute(
            "INSERT INTO users (id,username,password_hash,display_name,auth_method,"
            "is_admin,is_active,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            str(uuid.uuid4()), username, _hash_pw(password),
            "Admin", "password", 1, 1, _now(),
        )
    else:
        await conn.execute("UPDATE users SET is_admin=1 WHERE username=$1", username)


async def db_health() -> Dict[str, Any]:
    """Cheap health probe for /health."""
    try:
        async with _pool().acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"postgres": True, "pgvector": _vector_ok}
    except Exception as exc:
        return {"postgres": False, "pgvector": False, "error": str(exc)}


# ── Users ─────────────────────────────────────────────────────────────────────

async def get_user_by_username(username: str) -> Optional[Dict]:
    async with _pool().acquire() as conn:
        return _row(await conn.fetchrow("SELECT * FROM users WHERE username=$1", username))


async def get_user_by_id(user_id: str) -> Optional[Dict]:
    async with _pool().acquire() as conn:
        return _row(await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id))


async def upsert_sso_user(sub: str, email: str, display_name: str) -> Dict:
    async with _pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE username=$1", sub)
        if row:
            await conn.execute(
                "UPDATE users SET display_name=$1, email=$2 WHERE username=$3",
                display_name, email, sub,
            )
            return _row(await conn.fetchrow("SELECT * FROM users WHERE username=$1", sub))
        uid = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO users (id,username,display_name,email,auth_method,created_at)"
            " VALUES ($1,$2,$3,$4,$5,$6)",
            uid, sub, display_name, email, "sso", _now(),
        )
        return _row(await conn.fetchrow("SELECT * FROM users WHERE id=$1", uid))


# ── Conversations ─────────────────────────────────────────────────────────────

async def create_conversation(user_id: str, model: str, title: str = "New Conversation") -> Dict:
    cid, now = str(uuid.uuid4()), _now()
    async with _pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations (id,user_id,title,model,created_at,updated_at)"
            " VALUES ($1,$2,$3,$4,$5,$6)",
            cid, user_id, title, model, now, now,
        )
    return {"id": cid, "user_id": user_id, "title": title, "model": model,
            "created_at": now, "updated_at": now, "cross_chat_reference": False}


async def list_conversations(user_id: str) -> List[Dict]:
    async with _pool().acquire() as conn:
        return _rows(await conn.fetch(
            "SELECT * FROM conversations WHERE user_id=$1 ORDER BY updated_at DESC", user_id
        ))


async def get_conversation(conv_id: str, user_id: str) -> Optional[Dict]:
    async with _pool().acquire() as conn:
        return _row(await conn.fetchrow(
            "SELECT * FROM conversations WHERE id=$1 AND user_id=$2", conv_id, user_id
        ))


async def update_conversation_meta(conv_id: str, title: str = None, model: str = None,
                                   cross_chat_reference: bool = None) -> None:
    now = _now()
    async with _pool().acquire() as conn:
        if title is not None:
            await conn.execute("UPDATE conversations SET title=$1 WHERE id=$2", title, conv_id)
        if model is not None:
            await conn.execute("UPDATE conversations SET model=$1 WHERE id=$2", model, conv_id)
        if cross_chat_reference is not None:
            await conn.execute(
                "UPDATE conversations SET cross_chat_reference=$1 WHERE id=$2",
                cross_chat_reference, conv_id,
            )
        await conn.execute("UPDATE conversations SET updated_at=$1 WHERE id=$2", now, conv_id)


async def delete_conversation(conv_id: str, user_id: str) -> bool:
    """Delete a conversation and all children — only if owned by user_id."""
    async with _pool().acquire() as conn:
        owner = await conn.fetchrow(
            "SELECT id FROM conversations WHERE id=$1 AND user_id=$2", conv_id, user_id
        )
        if not owner:
            return False
        await conn.execute("DELETE FROM messages WHERE conversation_id=$1", conv_id)
        await conn.execute("DELETE FROM attachments WHERE conversation_id=$1", conv_id)
        await conn.execute("DELETE FROM usage_events WHERE conversation_id=$1", conv_id)
        await conn.execute("DELETE FROM runs WHERE conversation_id=$1", conv_id)
        await conn.execute("DELETE FROM artifacts WHERE conversation_id=$1", conv_id)
        try:
            await conn.execute("DELETE FROM embeddings WHERE conversation_id=$1", conv_id)
        except Exception:
            pass
        await conn.execute("DELETE FROM conversations WHERE id=$1 AND user_id=$2", conv_id, user_id)
    return True


# ── Messages ──────────────────────────────────────────────────────────────────

async def add_message(conv_id: str, role: str, content: str, tool_calls=None,
                      attachments=None) -> str:
    mid, now = str(uuid.uuid4()), _now()
    tc = json.dumps(tool_calls) if tool_calls else None
    att = json.dumps(attachments) if attachments else None
    async with _pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO messages (id,conversation_id,role,content,tool_calls,attachments,created_at)"
            " VALUES ($1,$2,$3,$4,$5,$6,$7)",
            mid, conv_id, role, content, tc, att, now,
        )
        await conn.execute("UPDATE conversations SET updated_at=$1 WHERE id=$2", now, conv_id)
    return mid


def _decode_attachments(row: Dict) -> Dict:
    raw = row.get("attachments")
    if isinstance(raw, str) and raw:
        try:
            row["attachments"] = json.loads(raw)
        except Exception:
            row["attachments"] = []
    elif not isinstance(raw, list):
        row["attachments"] = []
    return row


async def get_messages(conv_id: str) -> List[Dict]:
    async with _pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM messages WHERE conversation_id=$1 ORDER BY created_at ASC", conv_id
        )
        return [_decode_attachments(r) for r in _rows(rows)]


async def auto_title(conv_id: str, first_user_message: str) -> None:
    title = first_user_message[:60].strip()
    if len(first_user_message) > 60:
        title += "…"
    await update_conversation_meta(conv_id, title=title)


# ── Cross-chat context ────────────────────────────────────────────────────────

async def get_other_conversation_summaries(user_id: str, exclude_conv_id: str) -> List[Dict]:
    async with _pool().acquire() as conn:
        return _rows(await conn.fetch("""
            SELECT c.id, c.title, c.model,
                   (SELECT content FROM messages
                    WHERE conversation_id=c.id AND role='assistant'
                    ORDER BY created_at DESC LIMIT 1) AS last_response
            FROM conversations c
            WHERE c.user_id=$1 AND c.id != $2
            ORDER BY c.updated_at DESC
            LIMIT 10
        """, user_id, exclude_conv_id))


# ── Attachments ───────────────────────────────────────────────────────────────

async def save_attachment(conv_id: str, filename: str, content_type: str,
                          content: str, msg_id: str = None, user_id: str = None,
                          storage_path: str = None, size_bytes: int = 0,
                          attachment_id: str = None) -> str:
    aid, now = attachment_id or str(uuid.uuid4()), _now()
    # PostgreSQL TEXT cannot contain NUL (U+0000). The binary original is
    # stored separately; legacy callers may supply actual extracted text.
    if not isinstance(content, str):
        raise TypeError("Attachment content must be Unicode text; store binary on disk")
    content = content.replace("\x00", "\ufffd")
    async with _pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO attachments (id,user_id,conversation_id,message_id,filename,"
            "content_type,content,storage_path,size_bytes,created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
            aid, user_id, conv_id, msg_id, filename, content_type, content,
            storage_path, int(size_bytes or 0), now,
        )
    return aid


async def get_attachment(attachment_id: str, user_id: str) -> Optional[Dict]:
    """Return an attachment only when it belongs to the requesting user.

    Legacy rows without user_id are accepted only when their conversation is
    owned by the user.
    """
    async with _pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT a.*
            FROM attachments a
            LEFT JOIN conversations c ON c.id=a.conversation_id
            WHERE a.id=$1 AND (a.user_id=$2 OR (a.user_id IS NULL AND c.user_id=$2))
            LIMIT 1
            """,
            attachment_id, user_id,
        )
        return _row(row)


async def bind_attachments_to_conversation(attachment_ids: List[str], conv_id: str,
                                           user_id: str) -> None:
    if not attachment_ids:
        return
    async with _pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE attachments
            SET conversation_id=$1
            WHERE id = ANY($2::text[]) AND user_id=$3
              AND (conversation_id IS NULL OR conversation_id='' OR conversation_id=$1)
            """,
            conv_id, attachment_ids, user_id,
        )


async def get_attachments(conv_id: str) -> List[Dict]:
    async with _pool().acquire() as conn:
        return _rows(await conn.fetch(
            "SELECT * FROM attachments WHERE conversation_id=$1 ORDER BY created_at ASC", conv_id
        ))


# ── Runs (checkpointed agent runs) ────────────────────────────────────────────

async def create_run(conv_id: str, user_id: str, model: str,
                     fallback_model: str = None) -> str:
    rid, now = str(uuid.uuid4()), _now()
    async with _pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO runs (id,conversation_id,user_id,model,fallback_model,"
            "status,steps,created_at,updated_at) VALUES ($1,$2,$3,$4,$5,'running','[]',$6,$7)",
            rid, conv_id, user_id, model, fallback_model, now, now,
        )
    return rid


async def checkpoint_run(run_id: str, steps: List[Dict], status: str = "running") -> None:
    """Persist the full step list after every state change — cheap and idempotent,
    so a crashed process never loses the timeline."""
    async with _pool().acquire() as conn:
        await conn.execute(
            "UPDATE runs SET steps=$1::jsonb, status=$2, updated_at=$3 WHERE id=$4",
            json.dumps(steps), status, _now(), run_id,
        )


async def finish_run(run_id: str, status: str, input_tokens: int = 0,
                     output_tokens: int = 0, cost_usd: float = 0.0,
                     error: str = None) -> None:
    async with _pool().acquire() as conn:
        await conn.execute(
            "UPDATE runs SET status=$1, input_tokens=$2, output_tokens=$3, "
            "cost_usd=$4, error=$5, updated_at=$6 WHERE id=$7",
            status, input_tokens, output_tokens, cost_usd, error, _now(), run_id,
        )


async def get_latest_run(conv_id: str) -> Optional[Dict]:
    async with _pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM runs WHERE conversation_id=$1 ORDER BY created_at DESC LIMIT 1",
            conv_id,
        )
        r = _row(row)
        if r and isinstance(r.get("steps"), str):
            try:
                r["steps"] = json.loads(r["steps"])
            except Exception:
                r["steps"] = []
        return r


# ── Artifacts registry ────────────────────────────────────────────────────────

_ARTIFACT_KINDS = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image",
    ".pdf": "pdf", ".pptx": "pptx", ".docx": "docx", ".xlsx": "xlsx",
    ".py": "code", ".js": "code", ".sh": "code",
}


def artifact_kind(filename: str) -> str:
    from pathlib import Path as _P
    return _ARTIFACT_KINDS.get(_P(filename).suffix.lower(), "file")


async def register_artifact(conv_id: str, name: str, path: str, run_id: str = None,
                            kind: str = None, size_bytes: int = 0,
                            meta: Dict = None) -> str:
    aid, now = str(uuid.uuid4()), _now()
    async with _pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO artifacts (id,conversation_id,run_id,name,kind,path,"
            "size_bytes,meta,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9)",
            aid, conv_id, run_id, name, kind or artifact_kind(name), path,
            size_bytes, json.dumps(meta or {}), now,
        )
    return aid


async def list_artifacts(conv_id: str) -> List[Dict]:
    async with _pool().acquire() as conn:
        rows = _rows(await conn.fetch(
            "SELECT * FROM artifacts WHERE conversation_id=$1 ORDER BY created_at DESC", conv_id
        ))
        for r in rows:
            if isinstance(r.get("meta"), str):
                try:
                    r["meta"] = json.loads(r["meta"])
                except Exception:
                    r["meta"] = {}
        return rows


# ── Embeddings (pgvector) ─────────────────────────────────────────────────────

def _vec_literal(vec: List[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in vec) + "]"


async def upsert_embedding(content_hash: str, content: str, vector: List[float],
                           user_id: str = None, conversation_id: str = None,
                           metadata: Dict = None) -> None:
    if not _vector_ok:
        return
    async with _pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO embeddings (id,user_id,conversation_id,content_hash,content,
                                    embedding,metadata,created_at)
            VALUES ($1,$2,$3,$4,$5,$6::vector,$7::jsonb,$8)
            ON CONFLICT (content_hash) DO UPDATE
              SET content=EXCLUDED.content, embedding=EXCLUDED.embedding,
                  metadata=EXCLUDED.metadata
            """,
            str(uuid.uuid4()), user_id, conversation_id, content_hash, content,
            _vec_literal(vector), json.dumps(metadata or {}), _now(),
        )


async def search_embeddings(vector: List[float], top_k: int = 5,
                            user_id: str = None,
                            conversation_id: str = None) -> List[Dict]:
    """Cosine-distance ANN search. Optional scoping to a user or conversation."""
    if not _vector_ok:
        return []
    where, params = [], [_vec_literal(vector)]
    if user_id:
        params.append(user_id)
        where.append(f"user_id=${len(params)}")
    if conversation_id:
        params.append(conversation_id)
        where.append(f"conversation_id=${len(params)}")
    params.append(top_k)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    async with _pool().acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT id, content, metadata, conversation_id,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM embeddings
            {where_sql}
            ORDER BY embedding <=> $1::vector
            LIMIT ${len(params)}
        """, *params)
        return _rows(rows)


# ── Usage tracking ────────────────────────────────────────────────────────────

async def record_usage(user_id: str, conv_id: Optional[str], model: str,
                       input_tokens: int, output_tokens: int) -> None:
    cost = _calc_cost(model, input_tokens, output_tokens)
    async with _pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO usage_events (id,user_id,conversation_id,model,"
            "input_tokens,output_tokens,cost_usd,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            str(uuid.uuid4()), user_id, conv_id, model, input_tokens, output_tokens,
            cost, _now(),
        )


async def get_cost_stats(days: int = 30, user_id: Optional[str] = None) -> List[Dict]:
    async with _pool().acquire() as conn:
        where = "WHERE e.created_at::timestamptz > NOW() - MAKE_INTERVAL(days => $1)"
        params: list = [days]
        if user_id:
            where += " AND e.user_id=$2"
            params.append(user_id)
        rows = await conn.fetch(f"""
            SELECT u.username, u.display_name, e.model,
                   COUNT(*) AS calls,
                   SUM(e.input_tokens) AS input_tokens,
                   SUM(e.output_tokens) AS output_tokens,
                   SUM(e.cost_usd) AS cost_usd
            FROM usage_events e
            JOIN users u ON u.id = e.user_id
            {where}
            GROUP BY u.username, u.display_name, e.model
            ORDER BY cost_usd DESC
        """, *params)
        return _rows(rows)


# ── Admin ─────────────────────────────────────────────────────────────────────

async def list_all_users() -> List[Dict]:
    async with _pool().acquire() as conn:
        return _rows(await conn.fetch("""
            SELECT u.id, u.username, u.display_name, u.email, u.auth_method,
                   COALESCE(u.is_admin, 0) AS is_admin,
                   COALESCE(u.is_active, 1) AS is_active,
                   u.workspace_mode, u.created_at,
                   COUNT(DISTINCT c.id) AS conv_count,
                   COUNT(DISTINCT m.id) AS msg_count
            FROM users u
            LEFT JOIN conversations c ON c.user_id = u.id
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY u.id, u.username, u.display_name, u.email, u.auth_method,
                     u.is_admin, u.is_active, u.workspace_mode, u.created_at
            ORDER BY u.created_at ASC
        """))


def _public_user(row: Optional[Dict]) -> Optional[Dict]:
    if not row:
        return row
    row = dict(row)
    row.pop("password_hash", None)
    return row


async def admin_create_user(username: str, password: str, display_name: str,
                            is_admin: int = 0) -> Dict:
    uid, now = str(uuid.uuid4()), _now()
    async with _pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO users (id,username,password_hash,display_name,auth_method,"
            "is_admin,is_active,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            uid, username, _hash_pw(password), display_name or username,
            "password", is_admin, 1, now,
        )
        return _public_user(_row(await conn.fetchrow("SELECT * FROM users WHERE id=$1", uid)))


async def reset_user_password(user_id: str, new_password: str) -> None:
    async with _pool().acquire() as conn:
        await conn.execute(
            "UPDATE users SET password_hash=$1 WHERE id=$2", _hash_pw(new_password), user_id
        )


async def set_user_active(user_id: str, is_active: int) -> None:
    async with _pool().acquire() as conn:
        await conn.execute("UPDATE users SET is_active=$1 WHERE id=$2", is_active, user_id)


async def set_user_workspace(user_id: str, mode: str, custom_path: str = None) -> None:
    async with _pool().acquire() as conn:
        await conn.execute(
            "UPDATE users SET workspace_mode=$1, workspace_custom_path=$2 WHERE id=$3",
            mode, custom_path, user_id,
        )


async def get_usage_stats() -> Dict:
    async with _pool().acquire() as conn:
        totals: Dict[str, Any] = {}
        for key, sql in [
            ("total_users", "SELECT COUNT(*) AS n FROM users"),
            ("total_conversations", "SELECT COUNT(*) AS n FROM conversations"),
            ("total_messages", "SELECT COUNT(*) AS n FROM messages"),
        ]:
            row = await conn.fetchrow(sql)
            totals[key] = row["n"]
        rows = await conn.fetch("""
            SELECT u.username, u.display_name,
                   COUNT(DISTINCT c.id) AS convs,
                   COUNT(DISTINCT m.id) AS msgs
            FROM users u
            LEFT JOIN conversations c ON c.user_id = u.id
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY u.id, u.username, u.display_name
            ORDER BY msgs DESC
        """)
        totals["by_user"] = _rows(rows)
        return totals
