"""Authentication router – JWT-based login, registration & token verification."""

import hashlib
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

from src.storage.user_db import AccountLifecycleError

from .deps import limiter, load_users, _JWT_SECRET
from .deps.auth import _decode_jwt
from .deps.storage import _get_user_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── Config ────────────────────────────────────────────────────────────
JWT_SECRET = _JWT_SECRET
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

# Legacy password salt — decoupled from JWT_SECRET for safe key rotation.
# Set LEGACY_PASSWORD_SALT to JWT_SECRET[:16] used when legacy hashes were created.
_LEGACY_PASSWORD_SALT = os.getenv("LEGACY_PASSWORD_SALT", "")
if not _LEGACY_PASSWORD_SALT:
    logger.warning(
        "LEGACY_PASSWORD_SALT not set. Legacy SHA-256 password verification disabled. "
        "Users with legacy hashes must reset their passwords."
    )


# ── Password helpers (bcrypt with legacy SHA-256 migration) ──────────


def _hash_password(password: str) -> str:
    """Hash password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify password. Supports bcrypt and legacy SHA-256 hashes."""
    if stored_hash.startswith(("$2b$", "$2a$")):
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    # Legacy SHA-256: requires dedicated salt (decoupled from JWT_SECRET)
    if not _LEGACY_PASSWORD_SALT:
        return False
    return (
        hashlib.sha256(f"{_LEGACY_PASSWORD_SALT}{password}".encode()).hexdigest()
        == stored_hash
    )


def _is_legacy_hash(stored_hash: str) -> bool:
    """Check if the hash is legacy SHA-256 format (64 hex chars)."""
    return len(stored_hash) == 64 and not stored_hash.startswith("$")


# ── User store helpers (using shared deps) ────────────────────────────


def _load_users() -> dict:
    """Seed the default admin only in a never-used account store."""
    users = load_users()
    if users:
        return users
    default_user = os.getenv("APP_USERNAME", "admin")
    default_pass = os.getenv("APP_PASSWORD")
    generated = not default_pass
    if generated:
        default_pass = secrets.token_urlsafe(16)
    try:
        _get_user_db().create_account(
            default_user,
            {
                "password_hash": _hash_password(default_pass),
                "role": "admin",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            only_if_pristine=True,
        )
    except AccountLifecycleError as exc:
        if exc.reason not in {"store_not_pristine", "username_reserved"}:
            raise
        return load_users()
    if generated:
        from .deps.storage import USERS_FILE

        password_file = Path(USERS_FILE).parent / ".admin_password"
        fd = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(default_pass)
        logger.warning("Generated admin password saved to %s", password_file)
    return load_users()


# ── Request / Response models ────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(..., min_length=4, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str = "user"


class MessageResponse(BaseModel):
    message: str
    username: str


class VerifyResponse(BaseModel):
    valid: bool
    username: str
    role: str = "user"


# ── JWT helpers ───────────────────────────────────────────────────────


def _create_token(username: str, *, account_incarnation: str) -> str:
    """Issue only for the exact account whose credentials were checked."""
    try:
        with _get_user_db().account_guard(username, account_incarnation) as user:
            payload = {
                "sub": username,
                "account_incarnation": account_incarnation,
                "role": user.get("role", "user"),
                "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
                "iat": datetime.now(timezone.utc),
            }
            return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    except AccountLifecycleError:
        raise HTTPException(status_code=401, detail="Account deleted or disabled")
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail="Account authority unavailable")


def _decode_token(token: str) -> dict:
    """Decode a raw JWT string. Delegates to shared _decode_jwt logic."""
    # Build a minimal request-like object for the shared decoder
    from starlette.requests import Request as _Req

    scope = {
        "type": "http",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    }
    req = _Req(scope)
    return _decode_jwt(req)


# ── Endpoints ────────────────────────────────────────────────────────


@router.post("/register", response_model=MessageResponse)
@limiter.limit("3/minute")
async def register(request: Request, reg_request: RegisterRequest):
    """Register a new user account."""
    try:
        _get_user_db().create_account(
            reg_request.username,
            {
                "password_hash": _hash_password(reg_request.password),
                "role": "user",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except AccountLifecycleError as exc:
        raise HTTPException(status_code=409, detail=exc.reason)
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail="Account authority unavailable")

    return MessageResponse(
        message="Account created successfully", username=reg_request.username
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, login_request: LoginRequest):
    """Authenticate with username/password and receive a JWT token."""
    try:
        users = _load_users()
    except (sqlite3.Error, AccountLifecycleError):
        raise HTTPException(status_code=503, detail="Account authority unavailable")
    user = users.get(login_request.username)

    if not user or not _verify_password(login_request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Migrate legacy SHA-256 hash to bcrypt on successful login
    if _is_legacy_hash(user["password_hash"]):
        try:
            _get_user_db().upsert(
                login_request.username,
                {"password_hash": _hash_password(login_request.password)},
                expected_incarnation=user["account_incarnation"],
            )
        except AccountLifecycleError:
            raise HTTPException(status_code=401, detail="Account deleted or disabled")
        except sqlite3.Error:
            raise HTTPException(status_code=503, detail="Account authority unavailable")

    token = _create_token(
        login_request.username, account_incarnation=user["account_incarnation"]
    )
    role = _decode_token(token).get("role", "user")
    return TokenResponse(access_token=token, username=login_request.username, role=role)


@router.get("/verify", response_model=VerifyResponse)
@limiter.limit("30/minute")
async def verify_token(request: Request):
    """Verify that a JWT token from the Authorization header is still valid."""
    payload = _decode_jwt(request)
    return VerifyResponse(
        valid=True, username=payload["sub"], role=payload.get("role", "user")
    )
