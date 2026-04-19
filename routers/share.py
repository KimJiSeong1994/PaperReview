"""
Share endpoints for public read-only access to bookmark highlights:
  POST   /api/bookmarks/{bookmark_id}/share   (auth required)
  DELETE /api/bookmarks/{bookmark_id}/share   (auth required)
  GET    /api/shared/{share_token}            (public, rate-limited)
"""

import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from .deps import load_bookmarks, modify_bookmarks, get_current_user, limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["share"])

# ── Pydantic models ───────────────────────────────────────────────────

class CreateShareRequest(BaseModel):
    expires_in_days: Optional[int] = 30


class CreateShareResponse(BaseModel):
    token: str
    share_url: str
    created_at: str
    expires_at: str


# ── Sensitive fields to strip from public response ────────────────────

_STRIP_FIELDS = {"workspace_path", "session_id", "username"}


# ── Endpoints ─────────────────────────────────────────────────────────

@router.post("/bookmarks/{bookmark_id}/share")
async def create_share_link(
    bookmark_id: str,
    request: CreateShareRequest = CreateShareRequest(),
    username: str = Depends(get_current_user),
):
    """Generate a public share token for a bookmark."""
    token = f"sh_{secrets.token_urlsafe(16)}"
    now = datetime.now()
    expires_days = request.expires_in_days or 30
    expires_at = now + timedelta(days=expires_days)

    with modify_bookmarks() as data:
        for bm in data["bookmarks"]:
            if bm["id"] == bookmark_id:
                if bm.get("username") != username:
                    raise HTTPException(status_code=404, detail="Bookmark not found")
                bm["share"] = {
                    "token": token,
                    "created_at": now.isoformat(),
                    "expires_at": expires_at.isoformat(),
                }
                return CreateShareResponse(
                    token=token,
                    share_url=f"/share/{token}",
                    created_at=now.isoformat(),
                    expires_at=expires_at.isoformat(),
                )
        raise HTTPException(status_code=404, detail="Bookmark not found")


@router.delete("/bookmarks/{bookmark_id}/share")
async def revoke_share_link(
    bookmark_id: str,
    username: str = Depends(get_current_user),
):
    """Revoke the public share link for a bookmark."""
    with modify_bookmarks() as data:
        for bm in data["bookmarks"]:
            if bm["id"] == bookmark_id:
                if bm.get("username") != username:
                    raise HTTPException(status_code=404, detail="Bookmark not found")
                if "share" not in bm:
                    raise HTTPException(status_code=404, detail="No share link exists")
                del bm["share"]
                return {"success": True, "message": "Share link revoked"}
        raise HTTPException(status_code=404, detail="Bookmark not found")


@router.get("/shared/{share_token}")
@limiter.limit("30/minute")
async def get_shared_bookmark(share_token: str, request: Request):
    """Public endpoint: retrieve a shared bookmark by token (no auth required)."""
    data = load_bookmarks()
    for bm in data["bookmarks"]:
        share = bm.get("share")
        if not share or share.get("token") != share_token:
            continue

        # Check expiration
        expires_at = share.get("expires_at")
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) < datetime.now():
                    raise HTTPException(status_code=410, detail="Share link has expired")
            except ValueError:
                pass

        # Build safe response: strip sensitive fields
        safe = {k: v for k, v in bm.items() if k not in _STRIP_FIELDS}
        # Remove the share metadata itself from the response
        safe.pop("share", None)
        return safe

    raise HTTPException(status_code=404, detail="Shared bookmark not found")
