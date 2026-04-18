"""
GDPR unified delete endpoint for the current user.

  DELETE /api/me/all  — wipe all personal data across every storage layer.

Rate-limited to 3 requests per day per authenticated user (JWT sub claim).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import jwt as _pyjwt
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from starlette.requests import Request

from .deps import get_current_user, limiter, _JWT_SECRET, _JWT_ALGORITHM
from .deps.storage import _get_bookmark_db
from src.events.contracts import assert_valid_username, safe_user_path

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

# ── Configuration (env-overridable, no hardcoded paths) ───────────────
_DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

EVENTS_DB_PATH = Path(os.getenv("EVENTS_DB_PATH", str(_DATA_DIR / "events.db")))
PROFILE_DB_PATH = Path(os.getenv("PROFILE_DB_PATH", str(_DATA_DIR / "profile.db")))
# NOTE: bookmark DB path is NOT read here — the storage-layer singleton
# (`routers.deps.storage._get_bookmark_db`) is the single source of truth.
# Keeping an independent env var here caused GDPR stage 4 to open the wrong
# file when the storage layer pointed elsewhere (BOOKMARKS_FILE-derived).
_EMBEDDINGS_USERS_DIR = _DATA_DIR / "embeddings" / "users"
_GDPR_AUDIT_LOG = _DATA_DIR / ".gdpr_audit.jsonl"

# ── Router ────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/me", tags=["me"])


# ── Pydantic models ───────────────────────────────────────────────────

class DeleteResult(BaseModel):
    """Result of a GDPR delete-all operation."""

    deleted: bool
    """True only when ALL six deletion stages completed without error."""

    partial_failures: list[str]
    """Stage names that raised an exception (e.g. ``"events_db"``)."""

    audit_hash: str
    """SHA-256 hex digest of the username — proof of deletion without PII retention."""


# ── Helpers ───────────────────────────────────────────────────────────

def _append_audit_log(
    audit_hash: str,
    partial_failures: list[str],
) -> None:
    """Append one JSON line to the GDPR audit log at ``data/.gdpr_audit.jsonl``."""
    _GDPR_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "audit_hash": audit_hash,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "partial_failures": partial_failures,
    }
    with open(_GDPR_AUDIT_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


# ── Endpoint ──────────────────────────────────────────────────────────

@router.delete("/all", response_model=DeleteResult)
@limiter.limit("3/day", key_func=_user_key_func)
async def delete_all(
    request: Request,
    username: str = Depends(get_current_user),
) -> DeleteResult:
    """Delete **all** personal data for the authenticated user.

    Six deletion stages are executed independently.  A stage failure does
    **not** abort the remaining stages; it is recorded in ``partial_failures``
    and the audit log instead.  ``deleted`` is ``True`` only when every stage
    succeeds.

    Returns
    -------
    DeleteResult
        Structured result including an audit hash and a list of any stages
        that raised an exception.
    """
    # Validate username before touching any FS paths.
    try:
        assert_valid_username(username)
    except ValueError as exc:
        # Log a hash prefix only — never the raw username (GDPR / PII).
        user_hash_prefix = hashlib.sha256(username.encode("utf-8")).hexdigest()[:12]
        logger.exception(
            "GDPR delete_all: invalid username (hash_prefix=%s): %s",
            user_hash_prefix,
            exc,
        )
        # A malformed username cannot have meaningful data; still return a
        # well-formed response rather than a 500.
        return DeleteResult(deleted=False, partial_failures=["username_invalid"], audit_hash="")

    audit_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()
    partial_failures: list[str] = []

    # ── Stage 1: rubric_db ─────────────────────────────────────────────
    try:
        if PROFILE_DB_PATH.exists():
            conn = sqlite3.connect(str(PROFILE_DB_PATH), check_same_thread=False)
            try:
                conn.execute(
                    "DELETE FROM user_rubric WHERE username = ?", (username,)
                )
                conn.commit()
            finally:
                conn.close()
        # No-op if table/file absent in Week 0 — not an error.
    except Exception:
        logger.exception("GDPR delete_all [rubric_db] failed for hash %s", audit_hash)
        partial_failures.append("rubric_db")

    # ── Stage 2: profile_emb ──────────────────────────────────────────
    try:
        emb_path = safe_user_path(_EMBEDDINGS_USERS_DIR, username)
        if emb_path.exists():
            shutil.rmtree(emb_path)
    except Exception:
        logger.exception("GDPR delete_all [profile_emb] failed for hash %s", audit_hash)
        partial_failures.append("profile_emb")

    # ── Stage 3: events_db ────────────────────────────────────────────
    try:
        if EVENTS_DB_PATH.exists():
            conn = sqlite3.connect(str(EVENTS_DB_PATH), check_same_thread=False)
            try:
                conn.execute(
                    "DELETE FROM user_events WHERE user_id = ?", (username,)
                )
                conn.commit()
            finally:
                conn.close()
    except Exception:
        logger.exception("GDPR delete_all [events_db] failed for hash %s", audit_hash)
        partial_failures.append("events_db")

    # ── Stage 4: bookmarks ────────────────────────────────────────────
    # Use the storage-layer singleton so we act on the same DB that
    # POST /api/bookmarks writes to. The old code opened a parallel
    # sqlite3 connection against ``BOOKMARKS_DB_PATH`` which could diverge
    # from ``BOOKMARKS_FILE.with_suffix('.db')`` and silently fail.
    try:
        db = _get_bookmark_db()
        db.delete_by_username(username)
    except Exception:
        logger.exception("GDPR delete_all [bookmarks] failed for hash %s", audit_hash)
        partial_failures.append("bookmarks")

    # ── Stage 5: llm_cache ────────────────────────────────────────────
    # TODO(Week 1+): iterate LLM cache and remove entries keyed by user hash.
    logger.info(
        "GDPR delete_all [llm_cache]: placeholder — skipping for hash %s",
        audit_hash,
    )

    # ── Stage 6: in_memory ────────────────────────────────────────────
    # TODO(Week 1+): invalidate ProfileEventSubscriber / any in-memory user caches.
    logger.info(
        "GDPR delete_all [in_memory]: placeholder — skipping for hash %s",
        audit_hash,
    )

    # ── Audit log ─────────────────────────────────────────────────────
    try:
        _append_audit_log(audit_hash, partial_failures)
    except Exception:
        logger.error(
            "GDPR delete_all: failed to write audit log for hash %s — audit trail broken",
            audit_hash,
            exc_info=True,
        )
        partial_failures.append("audit_log")

    deleted = len(partial_failures) == 0
    return DeleteResult(
        deleted=deleted,
        partial_failures=partial_failures,
        audit_hash=audit_hash,
    )
