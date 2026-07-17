"""One-shot migration: SQLite (rdi_ai.db) → PostgreSQL.

Usage:
  # 1. Start Postgres (docker-compose.postgres.yml)
  # 2. Set RDI_DATABASE_URL (or configure [database] in config.ini)
  # 3. Run:
  python -m scripts.migrate_sqlite_to_postgres

Copies tables: users, conversations, messages, attachments, usage_events.
Idempotent: ON CONFLICT (id) DO NOTHING — safe to re-run.
"""
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

# Locate the SQLite DB relative to this script's parent dir
_ROOT = Path(__file__).parent.parent
_SQLITE_PATH = _ROOT / "rdi_ai.db"


async def migrate():
    db_url = os.environ.get("RDI_DATABASE_URL")
    if not db_url:
        # Try loading from config
        sys.path.insert(0, str(_ROOT))
        from backend.config import get_config
        cfg = get_config()
        if cfg.database:
            db_url = cfg.database.dsn
    if not db_url:
        print("ERROR: No database URL. Set RDI_DATABASE_URL or configure [database] in config.ini.")
        sys.exit(1)

    if not _SQLITE_PATH.exists():
        print(f"ERROR: SQLite DB not found at {_SQLITE_PATH}")
        sys.exit(1)

    import asyncpg
    pg = await asyncpg.connect(db_url)

    # Run the schema first (creates tables if not exist)
    from backend.database import _SCHEMA
    await pg.execute(_SCHEMA)

    sqlite_conn = sqlite3.connect(str(_SQLITE_PATH))
    sqlite_conn.row_factory = sqlite3.Row
    cur = sqlite_conn.cursor()

    print("Migrating users…")
    cur.execute("SELECT * FROM users")
    rows = cur.fetchall()
    for r in rows:
        await pg.execute("""
            INSERT INTO users (id, username, password_hash, display_name, email,
                               auth_method, is_admin, is_active, workspace_mode,
                               workspace_custom_path, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT (id) DO NOTHING
        """,
            r["id"], r["username"], r["password_hash"], r["display_name"],
            r.get("email"), r.get("auth_method", "password"),
            int(r.get("is_admin", 0)), int(r.get("is_active", 1)),
            r.get("workspace_mode", "cloud"), r.get("workspace_custom_path"),
            r["created_at"],
        )
    print(f"  {len(rows)} users migrated")

    print("Migrating conversations…")
    cur.execute("SELECT * FROM conversations")
    rows = cur.fetchall()
    for r in rows:
        await pg.execute("""
            INSERT INTO conversations (id, user_id, title, model, cross_chat_reference,
                                       created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (id) DO NOTHING
        """,
            r["id"], r["user_id"], r["title"], r["model"],
            bool(r.get("cross_chat_reference", 0)),
            r["created_at"], r["updated_at"],
        )
    print(f"  {len(rows)} conversations migrated")

    print("Migrating messages…")
    cur.execute("SELECT * FROM messages")
    rows = cur.fetchall()
    for r in rows:
        await pg.execute("""
            INSERT INTO messages (id, conversation_id, role, content, tool_calls,
                                  attachments, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (id) DO NOTHING
        """,
            r["id"], r["conversation_id"], r["role"], r["content"],
            r.get("tool_calls"), r.get("attachments"), r["created_at"],
        )
    print(f"  {len(rows)} messages migrated")

    print("Migrating attachments…")
    try:
        cur.execute("SELECT * FROM attachments")
        rows = cur.fetchall()
        for r in rows:
            await pg.execute("""
                INSERT INTO attachments (id, conversation_id, message_id, filename,
                                         content_type, content, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT (id) DO NOTHING
            """,
                r["id"], r.get("conversation_id"), r.get("message_id"),
                r["filename"], r["content_type"], r["content"], r["created_at"],
            )
        print(f"  {len(rows)} attachments migrated")
    except sqlite3.OperationalError:
        print("  (no attachments table — skipping)")

    print("Migrating usage_events…")
    try:
        cur.execute("SELECT * FROM usage_events")
        rows = cur.fetchall()
        for r in rows:
            await pg.execute("""
                INSERT INTO usage_events (id, user_id, conversation_id, model,
                                          input_tokens, output_tokens, cost_usd, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT (id) DO NOTHING
            """,
                r["id"], r["user_id"], r.get("conversation_id"), r["model"],
                int(r.get("input_tokens", 0)), int(r.get("output_tokens", 0)),
                float(r.get("cost_usd", 0.0)), r["created_at"],
            )
        print(f"  {len(rows)} usage events migrated")
    except sqlite3.OperationalError:
        print("  (no usage_events table — skipping)")

    await pg.close()
    sqlite_conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    asyncio.run(migrate())
