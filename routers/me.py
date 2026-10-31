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
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from starlette.requests import Request

from .deps import limiter, _JWT_SECRET, _JWT_ALGORITHM
from .deps import user_deletion
from .deps.storage import _get_user_db, review_sessions
from .deps.user_deletion import DeleteResult, delete_user_cascade
from .deps.auth import AuthenticatedPrincipal, get_authenticated_principal
from src.storage.bookmark_db import bookmark_belongs_to_account
from src.storage.user_db import AccountLifecycleError

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
        token = auth_header[len("Bearer ") :]
        try:
            payload = _pyjwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
            sub = payload.get("sub")
            if sub:
                # Return an opaque SHA-256 prefix so the raw username never
                # appears in slowapi's "ratelimit … exceeded" log line.
                # The hash is stable per user, so rate-limit semantics are
                # identical to keying on the raw sub.
                return "u:" + hashlib.sha256(sub.encode("utf-8")).hexdigest()[:16]
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
    response: Response,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
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
    result = delete_user_cascade(
        principal.username,
        account_incarnation=principal.account_incarnation,
    )
    if not result.deleted:
        response.status_code = 503 if result.retryable else 409
    return result


# ── My deep-review sessions (home "이어서 하기") ───────────────────────


class ReviewSessionSummary(BaseModel):
    """PII-free view of one deep-review session for the owner's home screen."""

    session_id: str
    status: str
    progress: str | None = None
    num_papers: int = 0
    created_at: str = ""
    title: str | None = None


class ReviewSessionListResponse(BaseModel):
    sessions: list[ReviewSessionSummary]
    total: int


def _summarize_session(session_id: str, session: dict) -> ReviewSessionSummary:
    papers = session.get("papers_data")
    first = papers[0] if isinstance(papers, list) and papers else None
    title = first.get("title") if isinstance(first, dict) else None
    paper_ids = session.get("paper_ids")
    num_papers = session.get("num_papers") or (
        len(paper_ids) if isinstance(paper_ids, list) else 0
    )
    return ReviewSessionSummary(
        session_id=session_id,
        status=str(session.get("status") or "unknown"),
        progress=session.get("progress") or None,
        num_papers=int(num_papers),
        created_at=str(session.get("created_at") or ""),
        title=str(title) if title else None,
    )


@router.get("/review-sessions", response_model=ReviewSessionListResponse)
async def list_my_review_sessions(
    limit: int = Query(5, ge=1, le=20),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
) -> ReviewSessionListResponse:
    """List the caller's deep-review sessions, newest first.

    Ownership uses the same predicate as bookmark attachment
    (:func:`bookmark_belongs_to_account`), so sessions of other accounts,
    re-registered usernames, and legacy sentinel sessions never leak.
    ``total`` counts every owned session; ``sessions`` is capped by ``limit``.
    """
    try:
        with _get_user_db().account_guard(
            principal.username, principal.account_incarnation
        ) as account:
            legacy_event_cutoff = account["legacy_event_cutoff"]
    except AccountLifecycleError:
        raise HTTPException(status_code=401, detail="Account deleted or disabled")

    owned = [
        (session_id, session)
        for session_id, session in list(review_sessions.items())
        if bookmark_belongs_to_account(
            session,
            username=principal.username,
            account_incarnation=principal.account_incarnation,
            legacy_event_cutoff=legacy_event_cutoff,
        )
    ]
    owned.sort(key=lambda item: str(item[1].get("created_at") or ""), reverse=True)
    return ReviewSessionListResponse(
        sessions=[_summarize_session(sid, session) for sid, session in owned[:limit]],
        total=len(owned),
    )


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
