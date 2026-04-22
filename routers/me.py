"""
GDPR unified delete endpoint for the current user.

  DELETE /api/me/all  — wipe all personal data across every storage layer.

Rate-limited to 3 requests per day per authenticated user (JWT sub claim).

Implementation note
-------------------
The actual deletion cascade lives in
:mod:`routers.deps.user_deletion` so the same logic can be reused by
admin-initiated deletes (``DELETE /api/admin/users/{username}``).  This
module is a thin HTTP/auth wrapper that keeps the public endpoint shape
unchanged.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import jwt as _pyjwt
from fastapi import APIRouter, Depends
from starlette.requests import Request

from .deps import get_current_user, limiter, _JWT_SECRET, _JWT_ALGORITHM
from .deps import user_deletion
from .deps.user_deletion import DeleteResult, delete_user_cascade

logger = logging.getLogger(__name__)


# ── Rate-limit key: JWT sub (not IP) ──────────────────────────────────

def _user_key_func(request: Request) -> str:
    """Return the JWT ``sub`` claim for rate-limiting.

    Keying by user identity (instead of IP) prevents:
    - Shared-NAT users from exhausting each other's GDPR delete quota.
    - IP-rotation attacks that would allow the same user to bypass the 3/day limit.

    Falls back to client IP if the token is absent or invalid so that
    unauthenticated requests are still counted (they will be rejected by
    ``get_current_user`` anyway, but we never open a bypass path).
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        try:
            payload = _pyjwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
            sub = payload.get("sub")
            if sub:
                # Return an opaque SHA-256 prefix so the raw username never
                # appears in slowapi's "ratelimit … exceeded" log line.
                # The hash is stable per user, so rate-limit semantics are
                # identical to keying on the raw sub.
                return "u:" + hashlib.sha256(
                    sub.encode("utf-8")
                ).hexdigest()[:16]
        except _pyjwt.InvalidTokenError:
            pass
    # Fallback: IP address (unauthenticated or malformed token)
    return request.client.host if request.client else "127.0.0.1"


# ── Router ────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/me", tags=["me"])


# ── Endpoint ──────────────────────────────────────────────────────────

@router.delete("/all", response_model=DeleteResult)
@limiter.limit("3/day", key_func=_user_key_func)
async def delete_all(
    request: Request,
    username: str = Depends(get_current_user),
) -> DeleteResult:
    """Delete **all** personal data for the authenticated user.

    Delegates to :func:`routers.deps.user_deletion.delete_user_cascade`
    with ``actor=None`` (self-delete semantics).  See that function for
    the stage-by-stage contract and failure-handling policy.

    Returns
    -------
    DeleteResult
        Structured result including an audit hash and a list of any stages
        that raised an exception.
    """
    return delete_user_cascade(username, actor=None)


# ── Legacy re-exports (kept for backward compatibility with fixtures) ──
#
# Older tests imported these symbols directly from ``routers.me``.  They
# are now owned by :mod:`routers.deps.user_deletion`; we re-export
# read-only aliases so that ``from routers.me import EVENTS_DB_PATH`` does
# not break.  Tests that need to patch these paths should target
# ``routers.deps.user_deletion`` instead.
EVENTS_DB_PATH: Path = user_deletion.EVENTS_DB_PATH
PROFILE_DB_PATH: Path = user_deletion.PROFILE_DB_PATH
_EMBEDDINGS_USERS_DIR: Path = user_deletion.EMBEDDINGS_USERS_DIR
_GDPR_AUDIT_LOG: Path = user_deletion.GDPR_AUDIT_LOG
