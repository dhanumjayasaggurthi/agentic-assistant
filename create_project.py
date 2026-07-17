"""
RDI AI — Project Bootstrap Script
Run this once to create the complete project structure.

Usage:
    python create_project.py                    # creates in current directory
    python create_project.py --dir /path/to/dir # creates in specified directory
"""
import argparse
import os
import sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=".", help="Target directory")
    args = parser.parse_args()

    root = Path(args.dir).resolve()
    root.mkdir(parents=True, exist_ok=True)

    def w(rel, content):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        print(f"  created  {rel}")

    print(f"\nCreating RDI AI project in: {root}\n")

    # ── requirements.txt ──────────────────────────────────────────────────────
    w("requirements.txt", """\
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
bcrypt>=3.1.7,<4.0.0
python-multipart>=0.0.9
aiofiles>=23.2.0
openai>=1.61.0
boto3>=1.34.0
google-genai>=1.0.0
requests>=2.31.0
msal>=1.28.0
aiosqlite>=0.20.0
PyPDF2>=3.0.0
python-docx>=1.1.0
Pillow>=10.0.0
python-dotenv>=1.0.0
websockets>=13.0
fpdf2>=2.7.0
python-pptx>=0.6.21
openpyxl>=3.1.0
beautifulsoup4>=4.12.0
httpx>=0.27.0
""")

    # ── config.ini (template — user fills in keys) ────────────────────────────
    w("config.ini", """\
# ──────────────────────────────────────────────────────────────────────────────
# GenAI API Marketplace — API Keys & Endpoints
# Replace YOUR_* placeholders with real keys from each marketplace card.
# Leave as YOUR_* to skip that provider at runtime.
# ──────────────────────────────────────────────────────────────────────────────

[azure_chat]
api_key     = YOUR_AZURE_CHAT_API_KEY
endpoint    = https://genaiapimna.jnj.com/openai-chat
api_version = 2024-12-01-preview

[azure_gpt5]
api_key     = YOUR_AZURE_GPT5_API_KEY
endpoint    = https://genaiapimna.jnj.com/openai-gpt-5
api_version = 2024-10-21

[azure_embedding]
api_key     = YOUR_AZURE_EMBEDDING_API_KEY
endpoint    = https://genaiapimna.jnj.com/openai-embeddings
api_version = 2022-12-01

[azure_image]
api_key     = YOUR_AZURE_IMAGE_API_KEY
endpoint    = https://genaiapimna.jnj.com/openai-image
api_version = 2024-10-21

[azure_audio]
api_key     = YOUR_AZURE_AUDIO_API_KEY
endpoint    = https://genaiapimna.jnj.com/openai-audio
api_version = 2025-03-01-preview

[azure_completion]
api_key     = YOUR_AZURE_COMPLETION_API_KEY
endpoint    = https://genaiapimna.jnj.com/openai-completion
api_version = 2023-03-15-preview

[bedrock]
api_key  = YOUR_BEDROCK_API_KEY
endpoint = https://genaiapigwna.jnj.com

[vertex]
api_key  = YOUR_VERTEX_API_KEY
endpoint = https://genaiapigcpna.jnj.com

[vertex_image]
api_key  = YOUR_VERTEX_IMAGE_API_KEY
endpoint = https://genaiapigcpna.jnj.com

[sso]
tenant_id    = YOUR_TENANT_ID
client_id    = YOUR_CLIENT_ID
redirect_uri = http://localhost:8000
scopes       = openid profile email User.Read
""")

    # ── workspace placeholder ─────────────────────────────────────────────────
    w("workspace/.gitkeep", "")

    # ── backend/__init__.py ───────────────────────────────────────────────────
    w("backend/__init__.py", "")
    w("backend/providers/__init__.py", "")
    w("backend/agents/__init__.py", "")

    # ── backend/config.py ─────────────────────────────────────────────────────
    w("backend/config.py", '''\
"""Configuration loader — reads config.ini for all 9 marketplace cards."""
import os
import secrets
import configparser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path(__file__).parent.parent / "config.ini"


def _is_placeholder(val: str) -> bool:
    return not val or val.upper().startswith("YOUR_")


@dataclass
class AzureChatConfig:
    api_key: str
    endpoint: str
    api_version: str = "2024-12-01-preview"


@dataclass
class AzureGPT5Config:
    api_key: str
    endpoint: str
    api_version: str = "2024-10-21"


@dataclass
class AzureEmbeddingConfig:
    api_key: str
    endpoint: str
    api_version: str = "2022-12-01"


@dataclass
class AzureImageConfig:
    api_key: str
    endpoint: str
    api_version: str = "2024-10-21"


@dataclass
class AzureAudioConfig:
    api_key: str
    endpoint: str
    api_version: str = "2025-03-01-preview"


@dataclass
class BedrockConfig:
    api_key: str
    endpoint: str


@dataclass
class VertexConfig:
    api_key: str
    endpoint: str


@dataclass
class VertexImageConfig:
    api_key: str
    endpoint: str


@dataclass
class SSOConfig:
    tenant_id: str
    client_id: str
    redirect_uri: str
    scopes: list
    enabled: bool


@dataclass
class AppConfig:
    azure_chat: Optional[AzureChatConfig]
    azure_gpt5: Optional[AzureGPT5Config]
    azure_embedding: Optional[AzureEmbeddingConfig]
    azure_image: Optional[AzureImageConfig]
    azure_audio: Optional[AzureAudioConfig]
    bedrock: Optional[BedrockConfig]
    vertex: Optional[VertexConfig]
    vertex_image: Optional[VertexImageConfig]
    sso: SSOConfig
    jwt_secret: str
    workspace_dir: Path
    db_path: Path


def _get(cfg, section, key, fallback=""):
    if not cfg.has_section(section):
        return fallback
    return cfg.get(section, key, fallback=fallback)


def load_config() -> AppConfig:
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)

    def azure_chat():
        k = _get(cfg, "azure_chat", "api_key")
        e = _get(cfg, "azure_chat", "endpoint", "https://genaiapimna.jnj.com/openai-chat")
        v = _get(cfg, "azure_chat", "api_version", "2024-12-01-preview")
        return None if _is_placeholder(k) or _is_placeholder(e) else AzureChatConfig(k, e, v)

    def azure_gpt5():
        k = _get(cfg, "azure_gpt5", "api_key")
        e = _get(cfg, "azure_gpt5", "endpoint", "https://genaiapimna.jnj.com/openai-gpt-5")
        v = _get(cfg, "azure_gpt5", "api_version", "2024-10-21")
        return None if _is_placeholder(k) or _is_placeholder(e) else AzureGPT5Config(k, e, v)

    def azure_embedding():
        k = _get(cfg, "azure_embedding", "api_key")
        e = _get(cfg, "azure_embedding", "endpoint", "https://genaiapimna.jnj.com/openai-embeddings")
        v = _get(cfg, "azure_embedding", "api_version", "2022-12-01")
        return None if _is_placeholder(k) or _is_placeholder(e) else AzureEmbeddingConfig(k, e, v)

    def azure_image():
        k = _get(cfg, "azure_image", "api_key")
        e = _get(cfg, "azure_image", "endpoint", "https://genaiapimna.jnj.com/openai-image")
        v = _get(cfg, "azure_image", "api_version", "2024-10-21")
        return None if _is_placeholder(k) or _is_placeholder(e) else AzureImageConfig(k, e, v)

    def azure_audio():
        k = _get(cfg, "azure_audio", "api_key")
        e = _get(cfg, "azure_audio", "endpoint", "https://genaiapimna.jnj.com/openai-audio")
        v = _get(cfg, "azure_audio", "api_version", "2025-03-01-preview")
        return None if _is_placeholder(k) or _is_placeholder(e) else AzureAudioConfig(k, e, v)

    def bedrock():
        k = _get(cfg, "bedrock", "api_key")
        e = _get(cfg, "bedrock", "endpoint", "https://genaiapigwna.jnj.com")
        return None if _is_placeholder(k) or _is_placeholder(e) else BedrockConfig(k, e)

    def vertex():
        k = _get(cfg, "vertex", "api_key")
        e = _get(cfg, "vertex", "endpoint", "https://genaiapigcpna.jnj.com")
        return None if _is_placeholder(k) or _is_placeholder(e) else VertexConfig(k, e)

    def vertex_image():
        k = _get(cfg, "vertex_image", "api_key")
        e = _get(cfg, "vertex_image", "endpoint", "https://genaiapigcpna.jnj.com")
        return None if _is_placeholder(k) or _is_placeholder(e) else VertexImageConfig(k, e)

    tenant_id = _get(cfg, "sso", "tenant_id", "YOUR_TENANT_ID")
    sso = SSOConfig(
        tenant_id=tenant_id,
        client_id=_get(cfg, "sso", "client_id", ""),
        redirect_uri=_get(cfg, "sso", "redirect_uri", "http://localhost:8000"),
        scopes=_get(cfg, "sso", "scopes", "openid profile email User.Read").split(),
        enabled=not _is_placeholder(tenant_id),
    )

    root = Path(__file__).parent.parent
    return AppConfig(
        azure_chat=azure_chat(),
        azure_gpt5=azure_gpt5(),
        azure_embedding=azure_embedding(),
        azure_image=azure_image(),
        azure_audio=azure_audio(),
        bedrock=bedrock(),
        vertex=vertex(),
        vertex_image=vertex_image(),
        sso=sso,
        jwt_secret=os.environ.get("JWT_SECRET", secrets.token_hex(32)),
        workspace_dir=root / "workspace",
        db_path=root / "rdi_ai.db",
    )


_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config
''')

    # ── backend/database.py ───────────────────────────────────────────────────
    w("backend/database.py", '''\
"""Async SQLite database — conversations, messages, users."""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import aiosqlite
from passlib.context import CryptContext

from .config import get_config

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _now() -> str:
    return datetime.utcnow().isoformat()


def _db_path() -> Path:
    return get_config().db_path


async def init_db() -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id           TEXT PRIMARY KEY,
                username     TEXT UNIQUE NOT NULL,
                password_hash TEXT,
                display_name TEXT,
                email        TEXT,
                auth_method  TEXT DEFAULT \'password\',
                created_at   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id         TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                title      TEXT DEFAULT \'New Conversation\',
                model      TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id              TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role            TEXT NOT NULL,
                content         TEXT NOT NULL,
                tool_calls      TEXT,
                created_at      TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS attachments (
                id              TEXT PRIMARY KEY,
                conversation_id TEXT,
                message_id      TEXT,
                filename        TEXT NOT NULL,
                content_type    TEXT NOT NULL,
                content         TEXT NOT NULL,
                created_at      TEXT NOT NULL
            );
        """)
        await db.commit()
        cur = await db.execute("SELECT id FROM users WHERE username=\'admin\'")
        if not await cur.fetchone():
            await db.execute(
                "INSERT INTO users (id,username,password_hash,display_name,auth_method,created_at)"
                " VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), "admin", _pwd_ctx.hash("Welcome@2026"),
                 "Admin", "password", _now()),
            )
            await db.commit()


async def get_user_by_username(username: str) -> Optional[Dict]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE username=?", (username,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_user_by_id(user_id: str) -> Optional[Dict]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE id=?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def upsert_sso_user(sub: str, email: str, display_name: str) -> Dict:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE username=?", (sub,))
        row = await cur.fetchone()
        if row:
            await db.execute(
                "UPDATE users SET display_name=?, email=? WHERE username=?",
                (display_name, email, sub),
            )
            await db.commit()
            cur = await db.execute("SELECT * FROM users WHERE username=?", (sub,))
            row = await cur.fetchone()
            return dict(row)
        uid = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO users (id,username,display_name,email,auth_method,created_at)"
            " VALUES (?,?,?,?,?,?)",
            (uid, sub, display_name, email, "sso", _now()),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE id=?", (uid,))
        row = await cur.fetchone()
        return dict(row)


async def create_conversation(user_id: str, model: str, title: str = "New Conversation") -> Dict:
    async with aiosqlite.connect(_db_path()) as db:
        cid, now = str(uuid.uuid4()), _now()
        await db.execute(
            "INSERT INTO conversations (id,user_id,title,model,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (cid, user_id, title, model, now, now),
        )
        await db.commit()
        return {"id": cid, "user_id": user_id, "title": title, "model": model,
                "created_at": now, "updated_at": now}


async def list_conversations(user_id: str) -> List[Dict]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM conversations WHERE user_id=? ORDER BY updated_at DESC", (user_id,)
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_conversation(conv_id: str, user_id: str) -> Optional[Dict]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM conversations WHERE id=? AND user_id=?", (conv_id, user_id)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def update_conversation_meta(conv_id: str, title: str = None, model: str = None) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        now = _now()
        if title is not None:
            await db.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (title, now, conv_id))
        if model is not None:
            await db.execute("UPDATE conversations SET model=?, updated_at=? WHERE id=?", (model, now, conv_id))
        await db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conv_id))
        await db.commit()


async def delete_conversation(conv_id: str, user_id: str) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute("DELETE FROM conversations WHERE id=? AND user_id=?", (conv_id, user_id))
        await db.commit()


async def add_message(conv_id: str, role: str, content: str, tool_calls=None) -> str:
    async with aiosqlite.connect(_db_path()) as db:
        mid, now = str(uuid.uuid4()), _now()
        await db.execute(
            "INSERT INTO messages (id,conversation_id,role,content,tool_calls,created_at) VALUES (?,?,?,?,?,?)",
            (mid, conv_id, role, content,
             json.dumps(tool_calls) if tool_calls else None, now),
        )
        await db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conv_id))
        await db.commit()
        return mid


async def get_messages(conv_id: str) -> List[Dict]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC", (conv_id,)
        )
        return [dict(r) for r in await cur.fetchall()]


async def auto_title(conv_id: str, first_user_message: str) -> None:
    title = first_user_message[:60].strip()
    if len(first_user_message) > 60:
        title += "\\u2026"
    await update_conversation_meta(conv_id, title=title)


async def save_attachment(conv_id: str, filename: str, content_type: str,
                          content: str, msg_id: str = None) -> str:
    async with aiosqlite.connect(_db_path()) as db:
        aid = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO attachments (id,conversation_id,message_id,filename,content_type,content,created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (aid, conv_id, msg_id, filename, content_type, content, _now()),
        )
        await db.commit()
        return aid
''')

    # ── backend/auth.py ───────────────────────────────────────────────────────
    w("backend/auth.py", '''\
"""JWT authentication + password auth + Azure AD SSO."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import get_config
from .database import get_user_by_id, get_user_by_username

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_security = HTTPBearer(auto_error=False)
_ALG = "HS256"
_EXPIRY_HOURS = 8


def create_token(user_id: str, username: str, display_name: str, auth_method: str) -> str:
    cfg = get_config()
    payload = {
        "sub": username, "user_id": user_id, "display_name": display_name,
        "auth_method": auth_method,
        "exp": datetime.utcnow() + timedelta(hours=_EXPIRY_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, cfg.jwt_secret, algorithm=_ALG)


def decode_token(token: str) -> dict:
    cfg = get_config()
    try:
        return jwt.decode(token, cfg.jwt_secret, algorithms=[_ALG])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


async def authenticate_password(username: str, password: str) -> Optional[dict]:
    user = await get_user_by_username(username)
    if not user or not user.get("password_hash"):
        return None
    if not _pwd_ctx.verify(password, user["password_hash"]):
        return None
    return user


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> dict:
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(creds.credentials)
    user = await get_user_by_id(payload["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def ws_auth(token: str) -> dict:
    payload = decode_token(token)
    user = await get_user_by_id(payload["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
''')

    # ── backend/providers/azure_chat.py ───────────────────────────────────────
    w("backend/providers/azure_chat.py", '''\
"""Azure OpenAI Chat — GPT-3.5/4/4o/4.1 + o-series + o3-pro (Responses API)."""
import asyncio
from typing import AsyncGenerator, List, Optional

import requests
from openai import AsyncAzureOpenAI

from ..config import get_config

_O_SERIES = {
    "o1", "o1-mini-global", "o1-global",
    "o3", "o3-global", "o3-mini", "o3-mini-global", "o3-pro-global",
    "o4-mini", "o4-mini-global",
}
_RESPONSES_MODELS = {"o3-pro-global"}


def _is_o_series(model: str) -> bool:
    return model in _O_SERIES or any(model.startswith(p) for p in ("o1", "o3", "o4"))


def _client() -> AsyncAzureOpenAI:
    cfg = get_config().azure_chat
    if not cfg:
        raise RuntimeError("Azure Chat not configured — add [azure_chat] to config.ini")
    return AsyncAzureOpenAI(api_key=cfg.api_key, azure_endpoint=cfg.endpoint,
                            api_version=cfg.api_version)


def _messages_to_text(messages: List[dict]) -> str:
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        if role != "system":
            parts.append(f"{role}: {content}")
    return "\\n".join(parts)


async def stream_chat(messages: List[dict], model: str, max_tokens: int = 4096,
                      temperature: Optional[float] = None) -> AsyncGenerator[str, None]:
    if model in _RESPONSES_MODELS:
        text = await responses_api(model, _messages_to_text(messages))
        for ch in text:
            yield ch
        return

    c = _client()
    if _is_o_series(model):
        filtered = [m for m in messages if m.get("role") != "system"]
        kw = {"model": model, "messages": filtered,
              "max_completion_tokens": max_tokens, "stream": True}
    else:
        kw = {"model": model, "messages": messages, "max_tokens": max_tokens, "stream": True}
        if temperature is not None:
            kw["temperature"] = temperature

    async with await c.chat.completions.create(**kw) as stream:
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


async def complete_with_tools(messages: List[dict], model: str,
                               tools: List[dict], max_tokens: int = 4096) -> dict:
    c = _client()
    kw: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if not _is_o_series(model):
        kw["tools"] = tools
        kw["tool_choice"] = "auto"
    else:
        kw.pop("max_tokens")
        kw["max_completion_tokens"] = max_tokens
        kw["messages"] = [m for m in messages if m.get("role") != "system"]

    resp = await c.chat.completions.create(**kw)
    choice = resp.choices[0]
    return {"content": choice.message.content or "",
            "tool_calls": choice.message.tool_calls,
            "finish_reason": choice.finish_reason}


async def responses_api(model: str, prompt: str, max_output_tokens: int = 4096) -> str:
    cfg = get_config().azure_chat
    if not cfg:
        raise RuntimeError("Azure Chat not configured")
    url = f"{cfg.endpoint.rstrip(\'/\')}/openai/v1/responses"
    loop = asyncio.get_event_loop()

    def _call():
        r = requests.post(url,
            headers={"api-key": cfg.api_key, "Content-Type": "application/json"},
            json={"model": model, "input": prompt, "max_output_tokens": max_output_tokens},
            timeout=300)
        r.raise_for_status()
        data = r.json()
        return "".join(part.get("text", "")
            for item in data.get("output", [])
            for part in item.get("content", [])
            if part.get("type") == "output_text")

    return await loop.run_in_executor(None, _call)
''')

    # ── backend/providers/azure_gpt5.py ──────────────────────────────────────
    w("backend/providers/azure_gpt5.py", '''\
"""Azure GPT-5 — chat models (max_completion_tokens) + Codex (Responses API)."""
import asyncio
from typing import AsyncGenerator, List

import requests
from openai import AsyncAzureOpenAI

from ..config import get_config

_CODEX_MODELS = {
    "gpt-5-pro-global", "gpt-5-codex-global", "gpt-5.1-codex-global",
    "gpt-5.1-codex-mini-global", "gpt-5.1-codex-max-global",
    "gpt-5.2-codex-global", "gpt-5.3-codex-global",
}


def _client() -> AsyncAzureOpenAI:
    cfg = get_config().azure_gpt5
    if not cfg:
        raise RuntimeError("Azure GPT-5 not configured — add [azure_gpt5] to config.ini")
    return AsyncAzureOpenAI(api_key=cfg.api_key, azure_endpoint=cfg.endpoint,
                            api_version=cfg.api_version)


def is_codex(model: str) -> bool:
    return model in _CODEX_MODELS


async def stream_gpt5(messages: List[dict], model: str,
                       max_tokens: int = 4096) -> AsyncGenerator[str, None]:
    if model in _CODEX_MODELS:
        prompt = "\\n".join(
            f"{m[\'role\']}: {m[\'content\']}" for m in messages
            if isinstance(m.get("content"), str)
        )
        text = await codex_responses_api(model, prompt, max_tokens)
        for ch in text:
            yield ch
        return

    c = _client()
    resp = await c.chat.completions.create(
        model=model, messages=messages,
        max_completion_tokens=max_tokens, stream=True)
    async with resp as stream:
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


async def codex_responses_api(model: str, prompt: str,
                               max_output_tokens: int = 4096) -> str:
    cfg = get_config().azure_gpt5
    if not cfg:
        raise RuntimeError("Azure GPT-5 not configured")
    url = f"{cfg.endpoint.rstrip(\'/\')}/openai/v1/responses"
    loop = asyncio.get_event_loop()

    def _call():
        r = requests.post(url,
            headers={"api-key": cfg.api_key, "Content-Type": "application/json"},
            json={"model": model, "input": prompt, "max_output_tokens": max_output_tokens},
            timeout=120)
        r.raise_for_status()
        data = r.json()
        return "".join(part.get("text", "")
            for item in data.get("output", [])
            for part in item.get("content", [])
            if part.get("type") == "output_text")

    return await loop.run_in_executor(None, _call)
''')

    # ── backend/providers/azure_audio.py ─────────────────────────────────────
    w("backend/providers/azure_audio.py", '''\
"""Azure Audio — TTS + Transcription + Diarization."""
import base64
import io

from openai import AsyncAzureOpenAI

from ..config import get_config

_TTS_VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")
_TTS_MODEL  = "gpt-4o-mini-tts-global"
_STT_MODEL  = "gpt-4o-transcribe-global"
_STT_DIAR   = "gpt-4o-transcribe-diarize-global"


def _client() -> AsyncAzureOpenAI:
    cfg = get_config().azure_audio
    if not cfg:
        raise RuntimeError("Azure Audio not configured — add [azure_audio] to config.ini")
    return AsyncAzureOpenAI(api_key=cfg.api_key, azure_endpoint=cfg.endpoint,
                            api_version=cfg.api_version)


async def text_to_speech(text: str, voice: str = "nova",
                          model: str = _TTS_MODEL) -> bytes:
    if voice not in _TTS_VOICES:
        voice = "nova"
    c = _client()
    resp = await c.audio.speech.create(model=model, voice=voice, input=text)
    return resp.content


async def text_to_speech_b64(text: str, voice: str = "nova") -> str:
    audio = await text_to_speech(text, voice)
    return base64.b64encode(audio).decode()


async def transcribe(audio_bytes: bytes, filename: str = "audio.wav",
                     diarize: bool = False) -> str:
    model = _STT_DIAR if diarize else _STT_MODEL
    c = _client()
    buf = io.BytesIO(audio_bytes)
    buf.name = filename
    resp = await c.audio.transcriptions.create(
        model=model, file=(filename, buf, "audio/wav"))
    return resp.text or ""
''')

    # ── backend/providers/azure_image.py ─────────────────────────────────────
    w("backend/providers/azure_image.py", '''\
"""Azure Image Generation — gpt-image-1/1.5/2."""
import io
from typing import Literal, Optional

from openai import AsyncAzureOpenAI

from ..config import get_config

_DEFAULT_MODEL = "gpt-image-2-global"
ImageSize = Literal["1024x1024", "1792x1024", "1024x1792"]


def _client() -> AsyncAzureOpenAI:
    cfg = get_config().azure_image
    if not cfg:
        raise RuntimeError("Azure Image not configured — add [azure_image] to config.ini")
    return AsyncAzureOpenAI(api_key=cfg.api_key, azure_endpoint=cfg.endpoint,
                            api_version=cfg.api_version)


async def generate_image(prompt: str, model: str = _DEFAULT_MODEL,
                          size: ImageSize = "1024x1024", n: int = 1) -> dict:
    c = _client()
    resp = await c.images.generate(model=model, prompt=prompt, n=n, size=size)
    item = resp.data[0]
    return {"prompt": prompt, "url": getattr(item, "url", None),
            "b64": getattr(item, "b64_json", None), "model": model, "size": size}


async def edit_image(image_bytes: bytes, mask_bytes: Optional[bytes],
                     prompt: str, model: str = "gpt-image-1-global",
                     size: ImageSize = "1024x1024") -> dict:
    c = _client()
    img_buf = io.BytesIO(image_bytes); img_buf.name = "image.png"
    kwargs = {"model": model, "image": img_buf, "prompt": prompt, "n": 1, "size": size}
    if mask_bytes:
        mask_buf = io.BytesIO(mask_bytes); mask_buf.name = "mask.png"
        kwargs["mask"] = mask_buf
    resp = await c.images.edit(**kwargs)
    item = resp.data[0]
    return {"prompt": prompt, "url": getattr(item, "url", None),
            "b64": getattr(item, "b64_json", None)}
''')

    # ── backend/providers/azure_embedding.py ─────────────────────────────────
    w("backend/providers/azure_embedding.py", '''\
"""Azure Embeddings — text-embedding-3-large/small/ada-002."""
from typing import List

from openai import AsyncAzureOpenAI

from ..config import get_config

_DEFAULT_MODEL = "text-embedding-3-large"


def _client() -> AsyncAzureOpenAI:
    cfg = get_config().azure_embedding
    if not cfg:
        raise RuntimeError("Azure Embedding not configured — add [azure_embedding] to config.ini")
    return AsyncAzureOpenAI(api_key=cfg.api_key, azure_endpoint=cfg.endpoint,
                            api_version=cfg.api_version)


async def embed(text: str, model: str = _DEFAULT_MODEL) -> List[float]:
    c = _client()
    resp = await c.embeddings.create(model=model, input=text)
    return resp.data[0].embedding


async def embed_batch(texts: List[str], model: str = _DEFAULT_MODEL) -> List[List[float]]:
    c = _client()
    resp = await c.embeddings.create(model=model, input=texts)
    resp.data.sort(key=lambda x: x.index)
    return [d.embedding for d in resp.data]
''')

    # ── backend/providers/bedrock.py ──────────────────────────────────────────
    w("backend/providers/bedrock.py", '''\
"""AWS Bedrock — Claude/Llama/Cohere via Converse API + x-api-key event hook."""
import asyncio
import json
from typing import AsyncGenerator, List, Optional

from ..config import get_config

_CLAUDE_PREFIXES = ("anthropic.", "us.anthropic.", "global.anthropic.")


def _is_claude(model: str) -> bool:
    return any(model.startswith(p) for p in _CLAUDE_PREFIXES)


def _make_client():
    import boto3
    cfg = get_config().bedrock
    if not cfg:
        raise RuntimeError("Bedrock not configured — add [bedrock] to config.ini")
    session = boto3.Session(aws_access_key_id="dummy", aws_secret_access_key="dummy")
    client = session.client("bedrock-runtime", endpoint_url=cfg.endpoint, region_name="dummy")
    api_key = cfg.api_key

    def _inject(model, params, request_signer, **kwargs):
        params["headers"]["x-api-key"] = api_key

    client.meta.events.register("before-call.bedrock-runtime.Converse", _inject)
    client.meta.events.register("before-call.bedrock-runtime.ConverseStream", _inject)
    client.meta.events.register("before-call.bedrock-runtime.InvokeModel", _inject)
    return client


def _convert_messages(messages: List[dict]) -> List[dict]:
    result = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        content = m.get("content", "")
        if isinstance(content, str):
            blocks = [{"text": content}]
        elif isinstance(content, list):
            blocks = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        blocks.append({"text": part["text"]})
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            mime, b64 = url.split(",", 1)
                            fmt = mime.split("/")[1].split(";")[0]
                            blocks.append({"image": {"format": fmt,
                                "source": {"bytes": b64.encode()}}})
        else:
            blocks = [{"text": str(content)}]
        if role == "tool":
            result.append({"role": "user", "content": [{"toolResult": {
                "toolUseId": m.get("tool_call_id", ""),
                "content": [{"text": content}]}}]})
            continue
        result.append({"role": role, "content": blocks})
    return result


async def stream_bedrock(messages: List[dict], model: str,
                          system_prompt: Optional[str] = None,
                          max_tokens: int = 4096) -> AsyncGenerator[str, None]:
    loop = asyncio.get_event_loop()
    client = _make_client()
    kwargs: dict = {"modelId": model, "messages": _convert_messages(messages),
                    "inferenceConfig": {"maxTokens": max_tokens}}
    if system_prompt and _is_claude(model):
        kwargs["system"] = [{"text": system_prompt}]

    def _call():
        return client.converse_stream(**kwargs)

    response = await loop.run_in_executor(None, _call)
    stream = response.get("stream")
    if not stream:
        return

    def _iter():
        for event in stream:
            delta = event.get("contentBlockDelta", {}).get("delta", {})
            text = delta.get("text", "")
            if text:
                yield text

    for token in await loop.run_in_executor(None, lambda: list(_iter())):
        yield token


async def complete_bedrock(messages: List[dict], model: str,
                            system_prompt: Optional[str] = None,
                            max_tokens: int = 4096,
                            tools: Optional[List] = None) -> dict:
    loop = asyncio.get_event_loop()
    client = _make_client()
    kwargs: dict = {"modelId": model, "messages": _convert_messages(messages),
                    "inferenceConfig": {"maxTokens": max_tokens}}
    if system_prompt and _is_claude(model):
        kwargs["system"] = [{"text": system_prompt}]
    if tools:
        kwargs["toolConfig"] = {"tools": [
            {"toolSpec": {"name": t["function"]["name"],
                          "description": t["function"].get("description", ""),
                          "inputSchema": {"json": t["function"].get("parameters", {})}}}
            for t in tools]}

    def _call():
        return client.converse(**kwargs)

    resp = await loop.run_in_executor(None, _call)
    msg = resp["output"]["message"]
    content_text, tool_calls = "", []
    for block in msg.get("content", []):
        if "text" in block:
            content_text += block["text"]
        elif "toolUse" in block:
            tool_calls.append(block["toolUse"])
    return {"content": content_text, "tool_calls": tool_calls or None,
            "finish_reason": resp.get("stopReason", "stop")}
''')

    # ── backend/providers/vertex.py ───────────────────────────────────────────
    w("backend/providers/vertex.py", '''\
"""Google Vertex AI — Gemini chat + image generation via RDI gateway."""
import asyncio
from typing import AsyncGenerator, List

import requests

from ..config import get_config


def _make_vertex_client():
    from google import genai
    from google.auth.credentials import Credentials
    from google.genai.types import HttpOptions

    class _Creds(Credentials):
        def refresh(self, request):
            self.token = "dummy-token"
            self.expiry = None

    cfg = get_config().vertex
    if not cfg:
        raise RuntimeError("Vertex AI not configured — add [vertex] to config.ini")

    return genai.Client(
        vertexai=True, project="dummy", location="dummy",
        http_options=HttpOptions(api_version="v1", base_url=cfg.endpoint,
                                 headers={"x-api-key": cfg.api_key}),
        credentials=_Creds(),
    )


def _convert_messages(messages: List[dict]) -> List[dict]:
    contents = []
    for m in messages:
        role = m.get("role", "user")
        if role == "system":
            contents.insert(0, {"role": "user", "parts": [{"text": m.get("content", "")}]})
            continue
        content = m.get("content", "")
        if isinstance(content, str):
            parts = [{"text": content}]
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append({"text": block["text"]})
        else:
            parts = [{"text": str(content)}]
        vertex_role = "model" if role == "assistant" else "user"
        contents.append({"role": vertex_role, "parts": parts})
    return contents


async def stream_vertex(messages: List[dict], model: str) -> AsyncGenerator[str, None]:
    loop = asyncio.get_event_loop()
    client = _make_vertex_client()
    contents = _convert_messages(messages)

    def _call():
        return [chunk.text for chunk in
                client.models.generate_content_stream(model=model, contents=contents)
                if chunk.text]

    for t in await loop.run_in_executor(None, _call):
        yield t


async def complete_vertex(messages: List[dict], model: str) -> dict:
    loop = asyncio.get_event_loop()
    client = _make_vertex_client()
    contents = _convert_messages(messages)

    def _call():
        return client.models.generate_content(model=model, contents=contents)

    resp = await loop.run_in_executor(None, _call)
    return {"content": resp.text or "", "tool_calls": None, "finish_reason": "stop"}


async def generate_vertex_image(prompt: str, model: str = "gemini-2.5-flash-image") -> dict:
    cfg = get_config().vertex_image
    if not cfg:
        raise RuntimeError("Vertex Image not configured — add [vertex_image] to config.ini")
    url = (f"{cfg.endpoint.rstrip(\'/\')}/v1/projects/GenAI"
           f"/locations/us-east1/publishers/google/models/{model}:generateContent")
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
    headers = {"content-type": "application/json", "accept": "application/json",
               "x-api-key": cfg.api_key}
    loop = asyncio.get_event_loop()

    def _call():
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        r.raise_for_status()
        return r.json()

    data = await loop.run_in_executor(None, _call)
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    result: dict = {"prompt": prompt, "b64": None, "text": ""}
    for p in parts:
        if "inlineData" in p:
            result["b64"] = p["inlineData"].get("data", "")
        elif "text" in p:
            result["text"] += p["text"]
    return result
''')

    # ── backend/agents/tools.py ───────────────────────────────────────────────
    w("backend/agents/tools.py", '''\
"""Tool definitions and sandboxed executors for the coding agent."""
import asyncio
import difflib
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

from ..config import get_config


def _safe_path(rel: str) -> Path:
    workspace = get_config().workspace_dir
    target = (workspace / rel).resolve()
    if not str(target).startswith(str(workspace.resolve())):
        raise ValueError(f"Path traversal blocked: {rel!r}")
    return target


TOOL_DEFINITIONS: List[Dict] = [
    {"type": "function", "function": {"name": "read_file",
        "description": "Read a file from the workspace directory.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Relative path within workspace/"}},
        "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file",
        "description": "Write or overwrite a file. Shows diff preview first.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "create_file",
        "description": "Create a new file (fails if already exists).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "delete_file",
        "description": "Delete a file from the workspace.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "list_files",
        "description": "List all files in the workspace or a subdirectory.",
        "parameters": {"type": "object", "properties": {
            "directory": {"type": "string", "default": ""}}}}},
    {"type": "function", "function": {"name": "run_bash",
        "description": "Execute a shell command in the workspace directory.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "default": 30}},
        "required": ["command"]}}},
    {"type": "function", "function": {"name": "run_python",
        "description": "Execute Python code and return stdout+stderr.",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string"},
            "timeout": {"type": "integer", "default": 30}},
        "required": ["code"]}}},
    {"type": "function", "function": {"name": "search_files",
        "description": "Search for a text pattern across workspace files.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "file_pattern": {"type": "string", "default": "*"}},
        "required": ["pattern"]}}},
]


def compute_diff(old: str, new: str, filename: str) -> str:
    diff = difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm="")
    return "".join(diff) or "(no changes)"


def build_preview(tool: str, args: Dict) -> str:
    if tool == "run_bash":
        return f"$ {args.get(\'command\', \'\')}"
    if tool == "run_python":
        code = args.get("code", "")
        return f"```python\\n{code[:300]}{'...' if len(code)>300 else ''}\\n```"
    if tool in ("write_file", "create_file"):
        path = args.get("path", ""); content = args.get("content", "")
        target = _safe_path(path)
        if tool == "write_file" and target.exists():
            return compute_diff(target.read_text(encoding="utf-8", errors="replace"),
                                content, path)
        return f"Create {path}:\\n{content[:500]}{'...' if len(content)>500 else ''}"
    if tool == "delete_file":
        return f"Delete workspace/{args.get(\'path\', \'\')}"
    if tool == "list_files":
        return f"List workspace/{args.get(\'directory\', \'\')}"
    if tool == "read_file":
        return f"Read workspace/{args.get(\'path\', \'\')}"
    if tool == "search_files":
        return f"Search \'{args.get(\'pattern\', \'\')}\' in {args.get(\'file_pattern\', \'*\')}"
    return str(args)[:200]


async def execute_tool(tool: str, args: Dict) -> str:
    try:
        if tool == "read_file":
            p = _safe_path(args["path"])
            return p.read_text(encoding="utf-8", errors="replace") if p.exists() else f"Not found: {args[\'path\']}"
        if tool == "write_file":
            p = _safe_path(args["path"]); p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"], encoding="utf-8")
            return f"Written {len(args[\'content\'])} chars to {args[\'path\']}"
        if tool == "create_file":
            p = _safe_path(args["path"])
            if p.exists():
                return f"Already exists: {args[\'path\']} — use write_file to overwrite"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"], encoding="utf-8")
            return f"Created {args[\'path\']}"
        if tool == "delete_file":
            p = _safe_path(args["path"])
            if not p.exists():
                return f"Not found: {args[\'path\']}"
            p.unlink(); return f"Deleted {args[\'path\']}"
        if tool == "list_files":
            directory = args.get("directory", "")
            base = _safe_path(directory) if directory else get_config().workspace_dir
            files = [str(p.relative_to(get_config().workspace_dir))
                     for p in sorted(base.rglob("*")) if p.is_file()]
            return "\\n".join(files) if files else "(empty)"
        if tool == "run_bash":
            cmd = args["command"]; timeout = min(int(args.get("timeout", 30)), 60)
            loop = asyncio.get_event_loop()
            def _run():
                r = subprocess.run(cmd, shell=True, cwd=str(get_config().workspace_dir),
                                   capture_output=True, text=True, timeout=timeout)
                out = r.stdout + r.stderr
                return out[:4000] + ("\\u2026[truncated]" if len(out)>4000 else "")
            try:
                return await loop.run_in_executor(None, _run)
            except subprocess.TimeoutExpired:
                return f"Timed out after {timeout}s"
        if tool == "run_python":
            code = args["code"]; timeout = min(int(args.get("timeout", 30)), 60)
            loop = asyncio.get_event_loop()
            def _run():
                r = subprocess.run([sys.executable, "-c", code],
                                   cwd=str(get_config().workspace_dir),
                                   capture_output=True, text=True, timeout=timeout)
                out = r.stdout + r.stderr
                return out[:4000] + ("\\u2026[truncated]" if len(out)>4000 else "")
            try:
                return await loop.run_in_executor(None, _run)
            except subprocess.TimeoutExpired:
                return f"Python timed out after {timeout}s"
        if tool == "search_files":
            pattern = args["pattern"]; file_glob = args.get("file_pattern", "*")
            results = []
            for path in get_config().workspace_dir.rglob(file_glob):
                if path.is_file():
                    try:
                        for i, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                            if pattern.lower() in line.lower():
                                results.append(f"{path.relative_to(get_config().workspace_dir)}:{i}: {line.rstrip()}")
                    except Exception:
                        pass
            return "\\n".join(results[:100]) if results else f"No matches for \'{pattern}\'"
        return f"Unknown tool: {tool}"
    except Exception as exc:
        return f"Error: {exc}"


def get_file_tree() -> List[Dict]:
    workspace = get_config().workspace_dir
    return [{"path": str(p.relative_to(workspace)).replace("\\\\", "/"),
             "name": p.name, "size": p.stat().st_size}
            for p in sorted(workspace.rglob("*"))
            if p.is_file() and ".gitkeep" not in p.name]
''')

    # ── backend/agents/chat_agent.py ──────────────────────────────────────────
    w("backend/agents/chat_agent.py", '''\
"""Multi-turn chat agent — routes to correct provider based on model ID."""
from typing import AsyncGenerator, Dict, List, Optional

_GPT5_PREFIXES  = ("gpt-5", "gpt-5.", "gpt-5-")
_BEDROCK_PREFIXES = ("anthropic.", "us.anthropic.", "global.anthropic.",
                     "us.meta.", "global.meta.", "cohere.", "us.cohere.",
                     "global.cohere.", "amazon.titan", "meta.llama")
_VERTEX_MODELS  = {"gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"}

_SYSTEM = ("You are RDI AI, an advanced enterprise AI assistant. "
           "Be helpful, accurate, and concise. Format responses in Markdown.")


def _route(model: str) -> str:
    if any(model.startswith(p) for p in _BEDROCK_PREFIXES):
        return "bedrock"
    if model in _VERTEX_MODELS:
        return "vertex"
    if any(model.startswith(p) for p in _GPT5_PREFIXES):
        return "gpt5"
    return "azure_chat"


def build_messages(history: List[Dict], user_message: str,
                   attachments: Optional[List[Dict]] = None,
                   system_prompt: str = _SYSTEM) -> List[Dict]:
    messages = [{"role": "system", "content": system_prompt}]
    for m in history:
        if m.get("role") in ("user", "assistant"):
            messages.append({"role": m["role"], "content": m["content"]})

    if attachments:
        parts: List[Dict] = [{"type": "text", "text": user_message}]
        for att in attachments:
            att_type = att.get("type", "")
            content = att.get("content", "")
            name = att.get("name", "file")
            if att_type.startswith("image/"):
                parts.append({"type": "image_url",
                              "image_url": {"url": f"data:{att_type};base64,{content}"}})
            else:
                parts.append({"type": "text",
                              "text": f"\\n--- {name} ---\\n{content}\\n---"})
        messages.append({"role": "user", "content": parts})
    else:
        messages.append({"role": "user", "content": user_message})
    return messages


async def stream_response(messages: List[Dict], model: str) -> AsyncGenerator[str, None]:
    provider = _route(model)
    if provider == "azure_chat":
        from ..providers.azure_chat import stream_chat
        async for token in stream_chat(messages, model):
            yield token
    elif provider == "gpt5":
        from ..providers.azure_gpt5 import stream_gpt5
        async for token in stream_gpt5(messages, model):
            yield token
    elif provider == "bedrock":
        from ..providers.bedrock import stream_bedrock
        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), None)
        user_msgs = [m for m in messages if m.get("role") != "system"]
        async for token in stream_bedrock(user_msgs, model, system_prompt=sys_msg):
            yield token
    elif provider == "vertex":
        from ..providers.vertex import stream_vertex
        async for token in stream_vertex(messages, model):
            yield token
    else:
        yield f"Unknown provider for model: {model}"


def trim_history(history: List[Dict], max_chars: int = 400_000) -> List[Dict]:
    total = sum(len(str(m.get("content", ""))) for m in history)
    while total > max_chars and len(history) > 2:
        removed = history.pop(1)
        total -= len(str(removed.get("content", "")))
    return history
''')

    # ── backend/agents/coding_agent.py ────────────────────────────────────────
    w("backend/agents/coding_agent.py", '''\
"""Coding agent — agentic loop with permission pause/resume via asyncio.Event."""
import asyncio
import json
import uuid
from typing import Callable, Dict, List

from .tools import TOOL_DEFINITIONS, build_preview, execute_tool

_CODING_SYSTEM = """You are RDI Coding Agent with full access to a sandboxed workspace.
Rules:
1. Explain what you will do before calling each tool.
2. Read existing files before modifying them.
3. Use Markdown fences for code.
4. Summarize what was done when finished.
5. Never access paths outside workspace/.
"""
MAX_TURNS = 20


async def run_coding_agent(
    user_message: str, history: List[Dict], model: str,
    permission_fn: Callable, token_callback: Callable, tool_result_callback: Callable,
) -> str:
    from .chat_agent import _route
    from ..providers.azure_gpt5 import is_codex

    if is_codex(model):
        from ..providers.azure_gpt5 import codex_responses_api
        messages = [{"role": "system", "content": _CODING_SYSTEM}]
        for m in history[-20:]:
            if m.get("role") in ("user", "assistant"):
                messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": user_message})
        prompt = "\\n".join(f"{m[\'role\']}: {m.get(\'content\',\'\')}" for m in messages)
        result = await codex_responses_api(model, prompt)
        await token_callback(result)
        return result

    provider = _route(model)
    messages = [{"role": "system", "content": _CODING_SYSTEM}]
    for m in history[-20:]:
        if m.get("role") in ("user", "assistant"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_message})

    final_answer = ""
    for turn in range(MAX_TURNS):
        resp = await _complete_with_tools(messages, model, provider)
        content = resp.get("content", "")
        tool_calls = resp.get("tool_calls") or []
        finish = resp.get("finish_reason", "stop")

        if content:
            for ch in content:
                await token_callback(ch)
                await asyncio.sleep(0)
            final_answer = content

        if finish == "stop" or not tool_calls:
            break

        messages.append({
            "role": "assistant", "content": content,
            "tool_calls": [{"id": tc.id, "type": "function",
                "function": {"name": tc.function.name,
                             "arguments": tc.function.arguments}}
                for tc in tool_calls]})

        for tc in tool_calls:
            tool_name = tc.function.name
            try:
                tool_args = json.loads(tc.function.arguments)
            except Exception:
                tool_args = {}

            preview = build_preview(tool_name, tool_args)
            request_id = str(uuid.uuid4())
            allowed = await permission_fn(request_id, tool_name, tool_args, preview)
            result = await execute_tool(tool_name, tool_args) if allowed else f"Tool \'{tool_name}\' denied."
            await tool_result_callback(request_id, tool_name, result, allowed)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    return final_answer


async def _complete_with_tools(messages: List[Dict], model: str, provider: str) -> dict:
    if provider == "azure_chat":
        from ..providers.azure_chat import complete_with_tools
        return await complete_with_tools(messages, model, TOOL_DEFINITIONS)
    elif provider == "gpt5":
        from openai import AsyncAzureOpenAI
        from ..config import get_config
        cfg = get_config().azure_gpt5
        if not cfg:
            raise RuntimeError("Azure GPT-5 not configured")
        c = AsyncAzureOpenAI(api_key=cfg.api_key, azure_endpoint=cfg.endpoint,
                             api_version=cfg.api_version)
        resp = await c.chat.completions.create(
            model=model, messages=messages, tools=TOOL_DEFINITIONS,
            tool_choice="auto", max_completion_tokens=4096)
        choice = resp.choices[0]
        return {"content": choice.message.content or "",
                "tool_calls": choice.message.tool_calls,
                "finish_reason": choice.finish_reason}
    elif provider == "bedrock":
        from ..providers.bedrock import complete_bedrock
        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), None)
        user_msgs = [m for m in messages if m.get("role") != "system"]
        return await complete_bedrock(user_msgs, model, system_prompt=sys_msg,
                                      tools=TOOL_DEFINITIONS)
    else:
        from ..providers.vertex import complete_vertex
        return await complete_vertex(messages, model)
''')

    # ── backend/ws_handler.py ─────────────────────────────────────────────────
    w("backend/ws_handler.py", '''\
"""WebSocket session handler — bidirectional streaming + permission pause/resume."""
import asyncio
import base64
import json
import time
from typing import Dict, List, Optional

from fastapi import WebSocket, WebSocketDisconnect

from .agents.chat_agent import build_messages, stream_response, trim_history
from .agents.coding_agent import run_coding_agent
from .agents.tools import get_file_tree
from .database import (add_message, auto_title, create_conversation,
                       delete_conversation, get_conversation, get_messages,
                       list_conversations, update_conversation_meta)
from .providers.azure_audio import text_to_speech_b64, transcribe
from .providers.azure_image import generate_image
from .providers.vertex import generate_vertex_image

_CODING_MODELS = {
    "gpt-5-pro-global", "gpt-5-codex-global", "gpt-5.1-codex-global",
    "gpt-5.1-codex-mini-global", "gpt-5.1-codex-max-global",
    "gpt-5.2-codex-global", "gpt-5.3-codex-global",
}


class WSSession:
    def __init__(self, ws: WebSocket, user: dict):
        self.ws = ws
        self.user = user
        self.conversation_id: Optional[str] = None
        self.model: str = "gpt-4o-global"
        self.history: List[Dict] = []
        self._perm_events: Dict[str, asyncio.Event] = {}
        self._perm_decisions: Dict[str, str] = {}

    async def send(self, data: dict) -> None:
        await self.ws.send_json(data)

    async def send_error(self, msg: str) -> None:
        await self.send({"type": "error", "message": msg})

    async def handle(self, data: dict) -> None:
        t = data.get("type", "")
        dispatch = {
            "chat":                 lambda: asyncio.create_task(self._handle_chat(data)),
            "permission":           lambda: asyncio.ensure_future(self._handle_permission(data)),
            "new_conversation":     lambda: asyncio.ensure_future(self._handle_new_conv(data)),
            "load_conversation":    lambda: asyncio.ensure_future(self._handle_load_conv(data)),
            "list_conversations":   lambda: asyncio.ensure_future(self._handle_list_convs()),
            "set_model":            lambda: setattr(self, "model", data.get("model", self.model)),
            "generate_image":       lambda: asyncio.create_task(self._handle_image(data)),
            "tts":                  lambda: asyncio.create_task(self._handle_tts(data)),
            "transcribe":           lambda: asyncio.create_task(self._handle_transcribe(data)),
            "delete_conversation":  lambda: asyncio.ensure_future(self._handle_del_conv(data)),
            "rename_conversation":  lambda: asyncio.ensure_future(self._handle_rename(data)),
            "get_workspace":        lambda: asyncio.ensure_future(self.send({"type": "workspace", "files": get_file_tree()})),
        }
        fn = dispatch.get(t)
        if fn:
            fn()
        else:
            await self.send_error(f"Unknown type: {t}")

    async def _handle_new_conv(self, data):
        model = data.get("model", self.model)
        self.model = model; self.history = []
        conv = await create_conversation(self.user["id"], model)
        self.conversation_id = conv["id"]
        await self.send({"type": "conversation_created", "id": conv["id"], "conversation": conv})

    async def _handle_load_conv(self, data):
        cid = data.get("conversation_id")
        conv = await get_conversation(cid, self.user["id"])
        if not conv:
            await self.send_error("Conversation not found"); return
        self.conversation_id = cid; self.model = conv["model"]
        msgs = await get_messages(cid)
        self.history = [{"role": m["role"], "content": m["content"]} for m in msgs]
        await self.send({"type": "conversation_loaded", "conversation": conv, "messages": msgs})

    async def _handle_list_convs(self):
        convs = await list_conversations(self.user["id"])
        await self.send({"type": "conversations", "conversations": convs})

    async def _handle_del_conv(self, data):
        cid = data.get("conversation_id")
        await delete_conversation(cid, self.user["id"])
        await self.send({"type": "conversation_deleted", "id": cid})

    async def _handle_rename(self, data):
        cid = data.get("conversation_id"); title = data.get("title", "")
        await update_conversation_meta(cid, title=title)
        await self.send({"type": "conversation_renamed", "id": cid, "title": title})

    async def _handle_chat(self, data):
        user_msg = data.get("message", "").strip()
        model = data.get("model", self.model)
        cid = data.get("conversation_id") or self.conversation_id
        attachments = data.get("attachments", [])
        if not user_msg and not attachments:
            await self.send_error("Empty message"); return
        self.model = model
        if not cid:
            conv = await create_conversation(self.user["id"], model)
            cid = conv["id"]; self.conversation_id = cid
            await self.send({"type": "conversation_created", "id": cid, "conversation": conv})
        else:
            await update_conversation_meta(cid, model=model)
        await add_message(cid, "user", user_msg)
        if len(self.history) == 0:
            await auto_title(cid, user_msg)
        self.history.append({"role": "user", "content": user_msg})
        self.history = trim_history(self.history)
        t0 = time.time()
        if model in _CODING_MODELS:
            await self._run_coding(user_msg, model, cid); return
        messages = build_messages(self.history[:-1], user_msg, attachments or None)
        full_response = ""
        try:
            async for token in stream_response(messages, model):
                full_response += token
                await self.send({"type": "token", "text": token})
        except Exception as exc:
            await self.send_error(f"Model error: {exc}"); return
        await self.send({"type": "done", "latency_ms": int((time.time()-t0)*1000)})
        await add_message(cid, "assistant", full_response)
        self.history.append({"role": "assistant", "content": full_response})

    async def _run_coding(self, user_msg, model, cid):
        t0 = time.time(); full_response = ""
        async def _tok(text):
            nonlocal full_response
            full_response += text
            await self.send({"type": "token", "text": text})
        async def _perm(rid, tool, args, preview):
            await self.send({"type": "permission", "request_id": rid,
                             "tool": tool, "args": args, "preview": preview})
            event = asyncio.Event(); self._perm_events[rid] = event
            await event.wait()
            return self._perm_decisions.pop(rid, "deny") == "allow"
        async def _result(rid, tool, result, allowed):
            await self.send({"type": "tool_result", "request_id": rid,
                             "tool": tool, "result": result[:2000], "allowed": allowed})
            if tool in ("write_file", "create_file", "delete_file"):
                await self.send({"type": "workspace", "files": get_file_tree()})
        try:
            await run_coding_agent(user_msg, self.history[:-1], model,
                                   _perm, _tok, _result)
        except Exception as exc:
            await self.send_error(f"Coding agent error: {exc}"); return
        await self.send({"type": "done", "latency_ms": int((time.time()-t0)*1000)})
        await add_message(cid, "assistant", full_response)
        self.history.append({"role": "assistant", "content": full_response})

    async def _handle_permission(self, data):
        rid = data.get("request_id", ""); decision = data.get("decision", "deny")
        self._perm_decisions[rid] = decision
        event = self._perm_events.pop(rid, None)
        if event: event.set()

    async def _handle_image(self, data):
        prompt = data.get("prompt", ""); model = data.get("model", "gpt-image-2-global")
        size = data.get("size", "1024x1024")
        if not prompt:
            await self.send_error("Image prompt required"); return
        try:
            if model == "gemini-2.5-flash-image":
                result = await generate_vertex_image(prompt, model)
                await self.send({"type": "image_result", "base64": result.get("b64"),
                                 "prompt": prompt, "model": model})
            else:
                result = await generate_image(prompt, model, size)
                await self.send({"type": "image_result", "url": result.get("url"),
                                 "base64": result.get("b64"), "prompt": prompt, "model": model})
        except Exception as exc:
            await self.send_error(f"Image error: {exc}")

    async def _handle_tts(self, data):
        text = data.get("text", ""); voice = data.get("voice", "nova")
        if not text:
            await self.send_error("TTS text required"); return
        try:
            b64 = await text_to_speech_b64(text, voice)
            await self.send({"type": "audio_result", "base64": b64, "voice": voice})
        except Exception as exc:
            await self.send_error(f"TTS error: {exc}")

    async def _handle_transcribe(self, data):
        b64 = data.get("audio_base64", ""); diarize = data.get("diarize", False)
        if not b64:
            await self.send_error("Audio data required"); return
        try:
            text = await transcribe(base64.b64decode(b64), diarize=diarize)
            await self.send({"type": "transcription", "text": text})
        except Exception as exc:
            await self.send_error(f"Transcription error: {exc}")


async def run_session(ws: WebSocket, user: dict) -> None:
    session = WSSession(ws, user)
    convs = await list_conversations(user["id"])
    await session.send({"type": "init", "user": {
        "id": user["id"],
        "display_name": user.get("display_name", user["username"]),
        "auth_method": user.get("auth_method", "password"),
    }, "conversations": convs})
    try:
        while True:
            raw = await ws.receive_text()
            await session.handle(json.loads(raw))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
''')

    # ── backend/main.py ───────────────────────────────────────────────────────
    w("backend/main.py", '''\
"""RDI AI — FastAPI entry point.
Run: uvicorn backend.main:app --reload --port 8000
"""
import base64
import io
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import authenticate_password, create_token, get_current_user, ws_auth
from .config import get_config
from .database import (delete_conversation, get_conversation, init_db,
                       list_conversations, save_attachment, update_conversation_meta)
from .ws_handler import run_session

_ROOT     = Path(__file__).parent.parent
_FRONTEND = _ROOT / "frontend"

app = FastAPI(title="RDI AI", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    await init_db()
    get_config().workspace_dir.mkdir(exist_ok=True)


app.mount("/static", StaticFiles(directory=str(_FRONTEND)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(_FRONTEND / "index.html"))


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
async def login(req: LoginRequest):
    user = await authenticate_password(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user["id"], user["username"],
                         user.get("display_name", user["username"]), "password")
    return {"access_token": token, "token_type": "bearer",
            "user": {"id": user["id"], "display_name": user.get("display_name"),
                     "username": user["username"]}}


class SSORequest(BaseModel):
    id_token: str


@app.post("/auth/sso")
async def sso_login(req: SSORequest):
    cfg = get_config()
    if not cfg.sso.enabled:
        raise HTTPException(status_code=400, detail="SSO not configured")
    try:
        from jose import jwt as jose_jwt
        claims = jose_jwt.get_unverified_claims(req.id_token)
        sub = claims.get("sub", claims.get("oid", ""))
        email = claims.get("email", claims.get("preferred_username", ""))
        name = claims.get("name", email)
        from .database import upsert_sso_user
        user = await upsert_sso_user(sub, email, name)
        token = create_token(user["id"], user["username"], name, "sso")
        return {"access_token": token, "token_type": "bearer",
                "user": {"id": user["id"], "display_name": name, "username": user["username"]}}
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"SSO error: {exc}")


@app.get("/auth/me")
async def me(user=Depends(get_current_user)):
    return {"id": user["id"], "username": user["username"],
            "display_name": user.get("display_name", user["username"]),
            "email": user.get("email", ""), "auth_method": user.get("auth_method", "password")}


@app.get("/auth/sso-config")
async def sso_config():
    cfg = get_config()
    return {"enabled": cfg.sso.enabled,
            "tenant_id": cfg.sso.tenant_id if cfg.sso.enabled else "",
            "client_id": cfg.sso.client_id if cfg.sso.enabled else "",
            "redirect_uri": cfg.sso.redirect_uri, "scopes": cfg.sso.scopes}


@app.get("/conversations")
async def get_conversations(user=Depends(get_current_user)):
    return await list_conversations(user["id"])


@app.delete("/conversations/{conv_id}")
async def del_conversation(conv_id: str, user=Depends(get_current_user)):
    await delete_conversation(conv_id, user["id"])
    return {"ok": True}


class RenameRequest(BaseModel):
    title: str


@app.patch("/conversations/{conv_id}")
async def rename_conversation(conv_id: str, req: RenameRequest,
                               user=Depends(get_current_user)):
    conv = await get_conversation(conv_id, user["id"])
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    await update_conversation_meta(conv_id, title=req.title)
    return {"ok": True, "title": req.title}


@app.post("/files/upload")
async def upload_file(file: UploadFile = File(...),
                      conversation_id: str = Form(None),
                      user=Depends(get_current_user)):
    content_type = file.content_type or "application/octet-stream"
    raw = await file.read()
    filename = file.filename or "upload"
    if content_type.startswith("image/"):
        content = base64.b64encode(raw).decode(); file_type = "image"
    elif content_type == "application/pdf":
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(raw))
            content = "\\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception:
            content = raw.decode("utf-8", errors="replace")
        file_type = "text"
    elif "word" in content_type or filename.endswith(".docx"):
        try:
            from docx import Document
            content = "\\n".join(p.text for p in Document(io.BytesIO(raw)).paragraphs)
        except Exception:
            content = raw.decode("utf-8", errors="replace")
        file_type = "text"
    else:
        content = raw.decode("utf-8", errors="replace"); file_type = "text"
    aid = await save_attachment(conversation_id or "", filename, content_type, content)
    return {"id": aid, "filename": filename, "type": file_type,
            "content_type": content_type, "content": content, "size": len(raw)}


@app.get("/workspace/files")
async def list_workspace(user=Depends(get_current_user)):
    from .agents.tools import get_file_tree
    return get_file_tree()


@app.get("/workspace/files/{path:path}")
async def read_workspace_file(path: str, user=Depends(get_current_user)):
    from .agents.tools import _safe_path
    try:
        p = _safe_path(path)
        if not p.exists():
            raise HTTPException(status_code=404, detail="Not found")
        return {"path": path, "content": p.read_text(encoding="utf-8", errors="replace")}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/workspace/files/{path:path}")
async def delete_workspace_file(path: str, user=Depends(get_current_user)):
    from .agents.tools import _safe_path
    try:
        p = _safe_path(path)
        if not p.exists():
            raise HTTPException(status_code=404, detail="Not found")
        p.unlink(); return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/providers/status")
async def provider_status(user=Depends(get_current_user)):
    cfg = get_config()
    return {k: getattr(cfg, k) is not None for k in
            ("azure_chat","azure_gpt5","azure_embedding","azure_image",
             "azure_audio","bedrock","vertex","vertex_image")}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query(...)):
    await ws.accept()
    try:
        user = await ws_auth(token)
    except Exception:
        await ws.close(code=1008, reason="Unauthorized"); return
    await run_session(ws, user)
''')

    # ── frontend/index.html ───────────────────────────────────────────────────
    w("frontend/index.html", """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>RDI AI</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text y='26' font-size='28'>🔬</text></svg>" />
  <link rel="stylesheet" href="/static/css/app.css" />
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/prismjs@1.29.0/themes/prism-tomorrow.min.css" />
  <script src="https://cdn.jsdelivr.net/npm/prismjs@1.29.0/prism.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/prismjs@1.29.0/plugins/autoloader/prism-autoloader.min.js"></script>
  <script src="https://alcdn.msauth.net/browser/2.38.3/js/msal-browser.min.js"></script>
</head>
<body>
  <div id="root"></div>
  <script src="/static/js/auth.js"></script>
  <script src="/static/js/ws.js"></script>
  <script type="text/babel" src="/static/js/app.js"></script>
</body>
</html>
""")

    # ── frontend/js/auth.js ───────────────────────────────────────────────────
    w("frontend/js/auth.js", """\
/* Auth utilities — JWT storage, SSO MSAL flow */
const Auth = (() => {
  const TOKEN_KEY = 'rdi_jwt', USER_KEY = 'rdi_user';
  const save  = (t, u) => { localStorage.setItem(TOKEN_KEY, t); localStorage.setItem(USER_KEY, JSON.stringify(u)); };
  const clear = ()     => { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); };
  const getToken = ()  => localStorage.getItem(TOKEN_KEY) || '';
  const getUser  = ()  => { try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null'); } catch { return null; } };
  const isLoggedIn = () => {
    const t = getToken(); if (!t) return false;
    try { const p = JSON.parse(atob(t.split('.')[1])); return p.exp > Date.now() / 1000; } catch { return false; }
  };
  const loginPassword = async (username, password) => {
    const res = await fetch('/auth/login', { method: 'POST',
      headers: {'Content-Type':'application/json'}, body: JSON.stringify({username, password}) });
    if (!res.ok) { const e = await res.json().catch(()=>({})); throw new Error(e.detail || 'Login failed'); }
    const data = await res.json(); save(data.access_token, data.user); return data.user;
  };
  const getSSOConfig = async () => { try { return await (await fetch('/auth/sso-config')).json(); } catch { return {enabled:false}; } };
  const loginSSO = async () => {
    const cfg = await getSSOConfig();
    if (!cfg.enabled) throw new Error('SSO not configured');
    const msalApp = new msal.PublicClientApplication({
      auth: { clientId: cfg.client_id, authority: `https://login.microsoftonline.com/${cfg.tenant_id}`, redirectUri: cfg.redirect_uri }
    });
    await msalApp.initialize();
    const result = await msalApp.loginPopup({ scopes: cfg.scopes });
    const res = await fetch('/auth/sso', { method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ id_token: result.idToken }) });
    if (!res.ok) { const e = await res.json().catch(()=>({})); throw new Error(e.detail || 'SSO failed'); }
    const data = await res.json(); save(data.access_token, data.user); return data.user;
  };
  const authHeaders = () => { const t = getToken(); return t ? {Authorization:`Bearer ${t}`} : {}; };
  const fetchJSON = async (url, opts = {}) => {
    const res = await fetch(url, { ...opts, headers: { ...authHeaders(), ...(opts.headers||{}) } });
    if (res.status === 401) { clear(); window.location.reload(); return null; }
    return res.json();
  };
  return { save, clear, getToken, getUser, isLoggedIn, loginPassword, loginSSO, getSSOConfig, authHeaders, fetchJSON };
})();
""")

    # ── frontend/js/ws.js ─────────────────────────────────────────────────────
    w("frontend/js/ws.js", """\
/* WebSocket client — manages connection, reconnect, message dispatch */
const RdiWS = (() => {
  let _ws=null, _handlers={}, _reconnectTimer=null, _connected=false, _onStatus=null;
  const on = (type, fn) => { _handlers[type] = fn; };
  const dispatch = data => { const fn = _handlers[data.type] || _handlers['*']; if (fn) fn(data); };
  const connect = onStatus => {
    _onStatus = onStatus || (() => {});
    const token = Auth.getToken(); if (!token) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    _ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`);
    _ws.onopen = () => { _connected=true; _onStatus('connected'); if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer=null; } };
    _ws.onmessage = e => { try { dispatch(JSON.parse(e.data)); } catch {} };
    _ws.onclose = e => { _connected=false; _onStatus('disconnected'); if (e.code !== 1008) _reconnectTimer = setTimeout(() => connect(onStatus), 3000); };
    _ws.onerror = () => { _connected=false; _onStatus('error'); };
  };
  const send = data => { if (_ws && _ws.readyState === WebSocket.OPEN) { _ws.send(JSON.stringify(data)); return true; } return false; };
  const disconnect = () => { if (_reconnectTimer) clearTimeout(_reconnectTimer); if (_ws) { _ws.close(); _ws=null; } _connected=false; };
  const isConnected = () => _connected;
  return { on, connect, send, disconnect, isConnected };
})();
""")

    # ── frontend/css/app.css ──────────────────────────────────────────────────
    # (read the actual file content from the project)
    css_src = Path(__file__).parent / "frontend" / "css" / "app.css"
    if css_src.exists():
        w("frontend/css/app.css", css_src.read_text(encoding="utf-8"))
    else:
        w("frontend/css/app.css", "/* RDI AI styles — run create_project.py from inside the project directory */")

    # ── frontend/js/app.js ────────────────────────────────────────────────────
    app_src = Path(__file__).parent / "frontend" / "js" / "app.js"
    if app_src.exists():
        w("frontend/js/app.js", app_src.read_text(encoding="utf-8"))
    else:
        w("frontend/js/app.js", "// RDI AI React app — run create_project.py from inside the project directory")

    # ── README.md ─────────────────────────────────────────────────────────────
    w("README.md", """\
# RDI AI — Enterprise Intelligence Platform

## Quick Start

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

Open http://localhost:8000 — login: `admin` / `Welcome@2026`

Fill in `config.ini` with your marketplace API keys to activate each provider.
See the full README in the source project for complete documentation.
""")

    # ── Done ──────────────────────────────────────────────────────────────────
    total = sum(1 for _ in root.rglob("*") if _.is_file())
    print(f"\nDone! {total} files created in {root}")
    print("\nNext steps:")
    print(f"  cd {root}")
    print("  pip install -r requirements.txt")
    print("  # Edit config.ini — add your API keys")
    print("  uvicorn backend.main:app --reload --port 8000")
    print("  # Open http://localhost:8000  (login: admin / Welcome@2026)")


if __name__ == "__main__":
    main()
