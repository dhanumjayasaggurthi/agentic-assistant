"""Configuration loader — reads config.ini for all 9 marketplace cards."""
import os
import secrets
import configparser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

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
class DatabaseConfig:
    dsn: str    # asyncpg connection string (read from config.ini [database] or RDI_DATABASE_URL env var)
    schema: str = "rdi_ai"  # PostgreSQL schema name — auto-created on startup if missing


@dataclass
class ExecutionConfig:
    mode: str = "local"  # local for development; docker for production isolation
    docker_image: str = "python:3.12-slim"
    network_enabled: bool = False
    memory_mb: int = 1024
    cpus: float = 1.0
    pids_limit: int = 128
    timeout_seconds: int = 60


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
    database: Optional[DatabaseConfig]
    execution: ExecutionConfig
    jwt_secret: str
    workspace_dir: Path
    db_path: Path
    admin_username: str = "admin"
    admin_password: str = ""  # read from config.ini [app] admin_password — no default in code


def _get(cfg: configparser.ConfigParser, section: str, key: str, fallback: str = "") -> str:
    if not cfg.has_section(section):
        return fallback
    return cfg.get(section, key, fallback=fallback)


def _load_jwt_secret(cfg: configparser.ConfigParser, root: Path) -> str:
    """Resolve a STABLE JWT secret.

    Priority: JWT_SECRET env var → config.ini [app] jwt_secret → a persisted
    file (.jwt_secret). A random per-process secret would invalidate every
    session on restart and break multi-worker prod (each worker gets a different
    key), so we generate once and persist it.
    """
    env = os.environ.get("JWT_SECRET")
    if env:
        return env
    cfg_secret = _get(cfg, "app", "jwt_secret", "")
    if cfg_secret and not _is_placeholder(cfg_secret):
        return cfg_secret
    secret_file = root / ".jwt_secret"
    try:
        if secret_file.exists():
            existing = secret_file.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        new_secret = secrets.token_hex(32)
        secret_file.write_text(new_secret, encoding="utf-8")
        return new_secret
    except Exception:
        # Filesystem unavailable — fall back to a process-local secret.
        return secrets.token_hex(32)


def load_config() -> AppConfig:
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)

    def azure_chat() -> Optional[AzureChatConfig]:
        k = _get(cfg, "azure_chat", "api_key")
        e = _get(cfg, "azure_chat", "endpoint", "https://genaiapimna.jnj.com/openai-chat")
        v = _get(cfg, "azure_chat", "api_version", "2024-12-01-preview")
        return None if _is_placeholder(k) or _is_placeholder(e) else AzureChatConfig(k, e, v)

    def azure_gpt5() -> Optional[AzureGPT5Config]:
        k = _get(cfg, "azure_gpt5", "api_key")
        e = _get(cfg, "azure_gpt5", "endpoint", "https://genaiapimna.jnj.com/openai-gpt-5")
        v = _get(cfg, "azure_gpt5", "api_version", "2024-10-21")
        return None if _is_placeholder(k) or _is_placeholder(e) else AzureGPT5Config(k, e, v)

    def azure_embedding() -> Optional[AzureEmbeddingConfig]:
        k = _get(cfg, "azure_embedding", "api_key")
        e = _get(cfg, "azure_embedding", "endpoint", "https://genaiapimna.jnj.com/openai-embeddings")
        v = _get(cfg, "azure_embedding", "api_version", "2022-12-01")
        return None if _is_placeholder(k) or _is_placeholder(e) else AzureEmbeddingConfig(k, e, v)

    def azure_image() -> Optional[AzureImageConfig]:
        k = _get(cfg, "azure_image", "api_key")
        e = _get(cfg, "azure_image", "endpoint", "https://genaiapimna.jnj.com/openai-image")
        v = _get(cfg, "azure_image", "api_version", "2024-10-21")
        return None if _is_placeholder(k) or _is_placeholder(e) else AzureImageConfig(k, e, v)

    def azure_audio() -> Optional[AzureAudioConfig]:
        k = _get(cfg, "azure_audio", "api_key")
        e = _get(cfg, "azure_audio", "endpoint", "https://genaiapimna.jnj.com/openai-audio")
        v = _get(cfg, "azure_audio", "api_version", "2025-03-01-preview")
        return None if _is_placeholder(k) or _is_placeholder(e) else AzureAudioConfig(k, e, v)

    def bedrock() -> Optional[BedrockConfig]:
        k = _get(cfg, "bedrock", "api_key")
        e = _get(cfg, "bedrock", "endpoint", "https://genaiapigwna.jnj.com")
        return None if _is_placeholder(k) or _is_placeholder(e) else BedrockConfig(k, e)

    def vertex() -> Optional[VertexConfig]:
        k = _get(cfg, "vertex", "api_key")
        e = _get(cfg, "vertex", "endpoint", "https://genaiapigcpna.jnj.com")
        return None if _is_placeholder(k) or _is_placeholder(e) else VertexConfig(k, e)

    def vertex_image() -> Optional[VertexImageConfig]:
        k = _get(cfg, "vertex_image", "api_key")
        e = _get(cfg, "vertex_image", "endpoint", "https://genaiapigcpna.jnj.com")
        return None if _is_placeholder(k) or _is_placeholder(e) else VertexImageConfig(k, e)

    def database() -> Optional[DatabaseConfig]:
        schema = _get(cfg, "database", "schema", "rdi_ai")
        dsn = os.environ.get("RDI_DATABASE_URL") or _get(cfg, "database", "dsn", "")
        if dsn:
            return DatabaseConfig(dsn=dsn, schema=schema)
        host = _get(cfg, "database", "host", "")
        if host and not _is_placeholder(host):
            port = _get(cfg, "database", "port", "5432")
            name = _get(cfg, "database", "name", "rdi_ai")
            user = _get(cfg, "database", "user", "postgres")
            pw = _get(cfg, "database", "password", "")
            return DatabaseConfig(
                dsn=f"postgresql://{quote_plus(user)}:{quote_plus(pw)}@{host}:{port}/{name}",
                schema=schema,
            )
        return None

    execution = ExecutionConfig(
        mode=(os.environ.get("RDI_EXECUTION_MODE") or _get(cfg, "execution", "mode", "local")).strip().lower(),
        docker_image=os.environ.get("RDI_EXECUTION_IMAGE") or _get(cfg, "execution", "docker_image", "python:3.12-slim"),
        network_enabled=(os.environ.get("RDI_EXECUTION_NETWORK") or _get(cfg, "execution", "network_enabled", "false")).lower() in ("1", "true", "yes"),
        memory_mb=int(os.environ.get("RDI_EXECUTION_MEMORY_MB") or _get(cfg, "execution", "memory_mb", "1024")),
        cpus=float(os.environ.get("RDI_EXECUTION_CPUS") or _get(cfg, "execution", "cpus", "1.0")),
        pids_limit=int(os.environ.get("RDI_EXECUTION_PIDS") or _get(cfg, "execution", "pids_limit", "128")),
        timeout_seconds=int(os.environ.get("RDI_EXECUTION_TIMEOUT") or _get(cfg, "execution", "timeout_seconds", "60")),
    )
    if execution.mode not in ("local", "docker"):
        raise RuntimeError("RDI_EXECUTION_MODE must be 'local' or 'docker'")

    tenant_id = _get(cfg, "sso", "tenant_id", "YOUR_TENANT_ID")
    sso = SSOConfig(
        tenant_id=tenant_id,
        client_id=_get(cfg, "sso", "client_id", ""),
        redirect_uri=_get(cfg, "sso", "redirect_uri", "http://localhost:8000"),
        scopes=_get(cfg, "sso", "scopes", "openid profile email User.Read").split(),
        enabled=not _is_placeholder(tenant_id),
    )

    root = Path(__file__).parent.parent

    # Workspace: prefer config.ini [app] workspace_dir, then env var, then home dir
    # IMPORTANT: must be OUTSIDE the project directory to avoid uvicorn --reload restarts
    ws_override = (
        os.environ.get("RDI_WORKSPACE_DIR")
        or _get(cfg, "app", "workspace_dir", "")
    )
    if ws_override:
        workspace_dir = Path(ws_override).expanduser().resolve()
    else:
        workspace_dir = Path.home() / "rdi-ai-workspace"

    db_override = (
        os.environ.get("RDI_DB_PATH")
        or _get(cfg, "app", "db_path", "")
    )
    db_path = Path(db_override).expanduser().resolve() if db_override else root / "rdi_ai.db"

    return AppConfig(
        jwt_secret=_load_jwt_secret(cfg, root),
        azure_chat=azure_chat(),
        azure_gpt5=azure_gpt5(),
        azure_embedding=azure_embedding(),
        azure_image=azure_image(),
        azure_audio=azure_audio(),
        bedrock=bedrock(),
        vertex=vertex(),
        vertex_image=vertex_image(),
        sso=sso,
        database=database(),
        execution=execution,
        workspace_dir=workspace_dir,
        db_path=db_path,
        admin_username=_get(cfg, "app", "admin_username", "admin"),
        admin_password=_get(cfg, "app", "admin_password", ""),
    )


_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config
