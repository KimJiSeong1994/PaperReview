"""Authentication router – JWT-based login, registration & token verification."""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

from .deps import limiter, load_users, save_users, modify_users, _JWT_SECRET

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── Config ────────────────────────────────────────────────────────────
JWT_SECRET = _JWT_SECRET
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24


# ── Password helpers (bcrypt with legacy SHA-256 migration) ──────────

def _hash_password(password: str) -> str:
    """Hash password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify password. Supports bcrypt and legacy SHA-256 hashes."""
    if stored_hash.startswith(("$2b$", "$2a$")):
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    # Legacy SHA-256: fixed salt from JWT_SECRET[:16]
    salt = JWT_SECRET[:16]
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == stored_hash


def _is_legacy_hash(stored_hash: str) -> bool:
    """Check if the hash is legacy SHA-256 format (64 hex chars)."""
    return len(stored_hash) == 64 and not stored_hash.startswith("$")


# ── User store helpers (using shared deps) ────────────────────────────

def _load_users() -> dict:
    """Load users, seeding default admin if users.json doesn't exist."""
    users = load_users()
    if users:
        # Migrate: ensure every user has a role field
        needs_save = False
        for uname, data in users.items():
            if "role" not in data:
                data["role"] = "admin" if uname == os.getenv("APP_USERNAME", "admin") else "user"
                needs_save = True
        if needs_save:
            save_users(users)
        return users

    # First run: create default admin
    default_user = os.getenv("APP_USERNAME", "admin")
    default_pass = os.getenv("APP_PASSWORD")
    if not default_pass:
        default_pass = secrets.token_urlsafe(16)
        logger.warning("No APP_PASSWORD set. Generated admin password: %s", default_pass)
        logger.warning("Set APP_PASSWORD env var to use a fixed password.")
    users = {
        default_user: {
            "password_hash": _hash_password(default_pass),
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    }
    save_users(users)
    return users


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

def _create_token(username: str, role: str = "user") -> str:
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/register", response_model=MessageResponse)
@limiter.limit("3/minute")
async def register(request: Request, reg_request: RegisterRequest):
    """Register a new user account."""
    with modify_users() as users:
        if reg_request.username in users:
            raise HTTPException(status_code=409, detail="Username already exists")

        users[reg_request.username] = {
            "password_hash": _hash_password(reg_request.password),
            "role": "user",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    return MessageResponse(message="Account created successfully", username=reg_request.username)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, login_request: LoginRequest):
    """Authenticate with username/password and receive a JWT token."""
    users = _load_users()
    user = users.get(login_request.username)

    if not user or not _verify_password(login_request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Migrate legacy SHA-256 hash to bcrypt on successful login
    if _is_legacy_hash(user["password_hash"]):
        with modify_users() as all_users:
            if login_request.username in all_users:
                all_users[login_request.username]["password_hash"] = _hash_password(login_request.password)

    role = user.get("role", "user")
    token = _create_token(login_request.username, role=role)
    return TokenResponse(access_token=token, username=login_request.username, role=role)


@router.get("/verify", response_model=VerifyResponse)
@limiter.limit("30/minute")
async def verify_token(request: Request, token: str):
    """Verify that a JWT token is still valid."""
    payload = _decode_token(token)
    return VerifyResponse(valid=True, username=payload["sub"], role=payload.get("role", "user"))
