"""JWT authentication + password auth + Azure AD SSO."""
import time
from datetime import datetime, timedelta
from typing import Optional

import requests
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import bcrypt as _bcrypt
from jose import JWTError, jwt

from .config import get_config
from .database import _verify_pw, get_user_by_id, get_user_by_username

_security = HTTPBearer(auto_error=False)

_ALG = "HS256"
_EXPIRY_HOURS = 8

# Cache Azure AD signing keys (JWKS) so we don't refetch on every SSO login.
_JWKS_CACHE: dict = {"keys": None, "fetched_at": 0.0, "tenant": None}
_JWKS_TTL = 3600  # 1 hour


def _get_azure_jwks(tenant_id: str) -> list:
    now = time.time()
    if (
        _JWKS_CACHE["keys"] is not None
        and _JWKS_CACHE["tenant"] == tenant_id
        and now - _JWKS_CACHE["fetched_at"] < _JWKS_TTL
    ):
        return _JWKS_CACHE["keys"]
    url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    keys = resp.json().get("keys", [])
    _JWKS_CACHE.update({"keys": keys, "fetched_at": now, "tenant": tenant_id})
    return keys


def verify_sso_token(id_token: str) -> dict:
    """Cryptographically verify an Azure AD ID token and return its claims.

    Validates the RS256 signature against Azure's published JWKS, plus the
    audience (client_id) and issuer/expiry. Raises HTTPException(401) on any
    failure — NEVER trust an unverified token.
    """
    cfg = get_config()
    tenant_id = cfg.sso.tenant_id
    client_id = cfg.sso.client_id
    try:
        unverified_header = jwt.get_unverified_header(id_token)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Malformed SSO token: {exc}")

    kid = unverified_header.get("kid")
    keys = _get_azure_jwks(tenant_id)
    signing_key = next((k for k in keys if k.get("kid") == kid), None)
    if signing_key is None:
        raise HTTPException(status_code=401, detail="SSO token signing key not found")

    # Azure v2 issuer. Accept both the tenant-specific v2.0 issuer forms.
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    try:
        claims = jwt.decode(
            id_token,
            signing_key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=issuer,
            options={"verify_at_hash": False},
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"SSO token verification failed: {exc}")
    return claims


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_token(user_id: str, username: str, display_name: str, auth_method: str) -> str:
    cfg = get_config()
    payload = {
        "sub": username,
        "user_id": user_id,
        "display_name": display_name,
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


# ── Password auth ─────────────────────────────────────────────────────────────

async def authenticate_password(username: str, password: str) -> Optional[dict]:
    user = await get_user_by_username(username)
    if not user or not user.get("password_hash"):
        return None
    if not _verify_pw(password, user["password_hash"]):
        return None
    if not user.get("is_active", 1):
        return None  # Account disabled
    return user


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> dict:
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(creds.credentials)
    user = await get_user_by_id(payload["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.get("is_active", 1):
        raise HTTPException(status_code=403, detail="Account disabled")
    return user


async def ws_auth(token: str) -> dict:
    """Validate JWT passed as ?token= in WebSocket URL."""
    payload = decode_token(token)
    user = await get_user_by_id(payload["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.get("is_active", 1):
        raise HTTPException(status_code=403, detail="Account disabled")
    return user


async def get_admin_user(user=Depends(get_current_user)) -> dict:
    """FastAPI dependency that restricts access to admin users only."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
