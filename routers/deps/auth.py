"""
JWT authentication helpers: decode, get_current_user, get_admin_user, get_optional_user.
"""

import logging
import os
import secrets
from typing import Optional

import jwt as _pyjwt
from fastapi import HTTPException
from starlette.requests import Request

from .config import ENVIRONMENT

logger = logging.getLogger(__name__)

# ── JWT configuration ─────────────────────────────────────────────────
_JWT_SECRET = os.getenv("JWT_SECRET")
if not _JWT_SECRET:
    if ENVIRONMENT == "production":
        raise RuntimeError(
            "FATAL: JWT_SECRET environment variable is required in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    _JWT_SECRET = secrets.token_hex(32)
    logger.warning("JWT_SECRET not set — using random secret (development mode).")
_JWT_ALGORITHM = "HS256"


def _decode_jwt(request: Request) -> dict:
    """Extract and decode JWT from Authorization header. Returns full payload."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[len("Bearer "):]
    try:
        payload = _pyjwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except _pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except _pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return payload


async def get_current_user(request: Request) -> str:
    """Extract and validate JWT from Authorization header. Returns username."""
    payload = _decode_jwt(request)
    return payload["sub"]


async def get_admin_user(request: Request) -> str:
    """Like get_current_user but requires admin role. Returns username."""
    payload = _decode_jwt(request)
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload["sub"]


async def get_optional_user(request: Request) -> Optional[str]:
    """Extract username from JWT if present, return None otherwise (no auth required)."""
    try:
        payload = _decode_jwt(request)
        return payload.get("sub")
    except HTTPException:
        return None
