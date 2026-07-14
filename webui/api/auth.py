"""JWT and password authentication utilities."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

import bcrypt
import jwt

_SECRET_KEY_PATH = Path.home() / ".nanobot" / "webui_secret.key"
_ALGORITHM = "HS256"
_TOKEN_EXPIRE_DAYS = 7
_AUTHLESS_USER = {
    "id": "local-admin",
    "username": "皖电智尊保",
    "role": "admin",
    "created_at": datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat(),
}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_authless_mode() -> bool:
    """Whether WebUI login should be bypassed for internal deployments."""
    return _env_flag("WEBUI_AUTH_DISABLED", False)


def get_authless_user() -> dict[str, str]:
    """Return the synthesized local admin user used in authless mode."""
    return dict(_AUTHLESS_USER)


def _get_secret_key() -> str:
    """Load or generate the JWT signing secret."""
    if not _SECRET_KEY_PATH.exists():
        _SECRET_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_hex(32)
        _SECRET_KEY_PATH.write_text(key, encoding="utf-8")
        _SECRET_KEY_PATH.chmod(0o600)
    return _SECRET_KEY_PATH.read_text(encoding="utf-8").strip()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: str, username: str, role: str) -> str:
    """Create a JWT access token valid for 7 days."""
    expire = datetime.now(timezone.utc) + timedelta(days=_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, _get_secret_key(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT token. Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, _get_secret_key(), algorithms=[_ALGORITHM])
