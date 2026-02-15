"""Authentication router – JWT-based login & token verification."""

import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

from .deps import limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── Credentials from environment ─────────────────────────────────────
APP_USERNAME = os.getenv("APP_USERNAME", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD", "admin123")
JWT_SECRET = os.getenv("JWT_SECRET", "paper-review-agent-secret-key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24


# ── Request / Response models ────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class VerifyResponse(BaseModel):
    valid: bool
    username: str


# ── Helpers ──────────────────────────────────────────────────────────

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

@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, login_request: LoginRequest):
    """Authenticate with username/password and receive a JWT token."""
    if login_request.username != APP_USERNAME or login_request.password != APP_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = _create_token(login_request.username)
    return TokenResponse(access_token=token, username=login_request.username)


@router.get("/verify", response_model=VerifyResponse)
@limiter.limit("30/minute")
async def verify_token(request: Request, token: str):
    """Verify that a JWT token is still valid."""
    payload = _decode_token(token)
    return VerifyResponse(valid=True, username=payload["sub"])
