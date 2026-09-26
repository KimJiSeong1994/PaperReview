"""
JWT authentication helpers: decode, get_current_user, get_admin_user, get_optional_user.

All three dependency functions verify that the authenticated principal
still exists in the user DB.  A valid JWT alone is not sufficient — if
the account has been deleted (self-delete or admin-initiated cascade)
the token becomes unusable immediately, preventing zombie access until
the JWT's natural expiry.
"""

import logging
import os
import secrets
import sqlite3
from dataclasses import dataclass
from typing import Optional

import jwt as _pyjwt
from fastapi import HTTPException
from starlette.requests import Request

from src.analytics.mcp_context import identify_actor, is_mcp_request
from src.storage.user_db import AccountLifecycleError

from .config import ENVIRONMENT

logger = logging.getLogger(__name__)

# ── JWT configuration ─────────────────────────────────────────────────
_JWT_SECRET = os.getenv("JWT_SECRET")
if not _JWT_SECRET:
    if ENVIRONMENT == "production":
        raise RuntimeError(
            "FATAL: JWT_SECRET environment variable is required in production. "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    _JWT_SECRET = secrets.token_hex(32)
    logger.warning("JWT_SECRET not set — using random secret (development mode).")
_JWT_ALGORITHM = "HS256"


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    username: str
    account_incarnation: str


def _decode_jwt(request: Request) -> dict:
    """Extract and decode JWT from Authorization header. Returns full payload."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )

    token = auth_header[len("Bearer ") :]
    try:
        payload = _pyjwt.decode(
            token,
            _JWT_SECRET,
            algorithms=[_JWT_ALGORITHM],
            options={"require": ["sub", "exp", "account_incarnation"]},
        )
    except _pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except _pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    from .storage import _get_user_db

    try:
        user = _get_user_db().validate_principal(
            payload["sub"], payload["account_incarnation"]
        )
    except AccountLifecycleError:
        raise HTTPException(status_code=401, detail="Account deleted or disabled")
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail="Account authority unavailable")
    payload["role"] = user.get("role")
    request.state.authenticated_principal = AuthenticatedPrincipal(
        payload["sub"], payload["account_incarnation"]
    )
    return payload


async def get_authenticated_principal(request: Request) -> AuthenticatedPrincipal:
    """Return the identity validated at the authoritative auth boundary."""
    payload = _decode_jwt(request)
    identify_actor(payload["sub"], payload.get("role"))
    return AuthenticatedPrincipal(payload["sub"], payload["account_incarnation"])


async def get_current_user(request: Request) -> str:
    """Extract and validate JWT, then confirm the account still exists.

    A deleted or disabled account returns HTTP 401 with detail
    ``"Account deleted or disabled"`` so the client can force re-login.
    """
    return (await get_authenticated_principal(request)).username


async def get_admin_user(request: Request) -> str:
    """Like :func:`get_current_user` but requires the *current* admin role.

    The role is re-checked against the DB so that a role demotion takes
    effect immediately — the JWT's ``role`` claim is only a hint, never
    authoritative.
    """
    payload = _decode_jwt(request)
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    username = payload["sub"]
    identify_actor(username, payload.get("role"))
    return username


async def get_optional_user(request: Request) -> Optional[str]:
    """Extract username from JWT if present and the account still exists.

    Returns ``None`` for:
    - Missing / malformed / expired tokens (no auth).
    - Tokens for deleted accounts (treated as anonymous).
    """
    # The configured MCP token must not silently become an anonymous review
    # owner: subsequent status/report endpoints require that same account.
    if is_mcp_request(request.headers):
        return await get_current_user(request)
    try:
        return await get_current_user(request)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        return None
