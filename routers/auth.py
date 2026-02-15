"""Authentication router – JWT-based login, registration & token verification."""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

from .deps import limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── Config ────────────────────────────────────────────────────────────
JWT_SECRET = os.getenv("JWT_SECRET", "paper-review-agent-secret-key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

USERS_FILE = Path(__file__).resolve().parent.parent / "data" / "users.json"


# ── User store helpers ────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    """Hash password with SHA-256 + salt."""
    salt = JWT_SECRET[:16]
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def _load_users() -> dict:
    """Load users from JSON file."""
    if not USERS_FILE.exists():
        # Seed with default admin account from env
        default_user = os.getenv("APP_USERNAME", "Jipyheonjeon")
        default_pass = os.getenv("APP_PASSWORD", "KGs951159**")
        users = {
            default_user: {
                "password_hash": _hash_password(default_pass),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        }
        _save_users(users)
        return users

    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_users(users: dict) -> None:
    """Persist users to JSON file."""
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)


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


class MessageResponse(BaseModel):
    message: str
    username: str


class VerifyResponse(BaseModel):
    valid: bool
    username: str


# ── JWT helpers ───────────────────────────────────────────────────────

def _create_token(username: str) -> str:
    payload = {
        "sub": username,
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
    users = _load_users()

    if reg_request.username in users:
        raise HTTPException(status_code=409, detail="Username already exists")

    users[reg_request.username] = {
        "password_hash": _hash_password(reg_request.password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_users(users)

    return MessageResponse(message="Account created successfully", username=reg_request.username)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, login_request: LoginRequest):
    """Authenticate with username/password and receive a JWT token."""
    users = _load_users()
    user = users.get(login_request.username)

    if not user or user["password_hash"] != _hash_password(login_request.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = _create_token(login_request.username)
    return TokenResponse(access_token=token, username=login_request.username)


@router.get("/verify", response_model=VerifyResponse)
@limiter.limit("30/minute")
async def verify_token(request: Request, token: str):
    """Verify that a JWT token is still valid."""
    payload = _decode_token(token)
    return VerifyResponse(valid=True, username=payload["sub"])
