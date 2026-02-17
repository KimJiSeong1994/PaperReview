"""
Bookmark CRUD endpoints (per-user isolated):
  POST   /api/bookmarks
  GET    /api/bookmarks
  GET    /api/bookmarks/{bookmark_id}
  DELETE /api/bookmarks/{bookmark_id}
  PATCH  /api/bookmarks/{bookmark_id}/topic
  PATCH  /api/bookmarks/{bookmark_id}/notes
  POST   /api/bookmarks/bulk-delete
  POST   /api/bookmarks/bulk-move
"""

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .deps import load_bookmarks, save_bookmarks, review_sessions, review_sessions_lock, get_current_user

router = APIRouter(prefix="/api", tags=["bookmarks"])


# ── Pydantic models ───────────────────────────────────────────────────

class BookmarkCreateRequest(BaseModel):
    session_id: str
    title: str
    query: str = ""
    papers: List[dict] = []
    report_markdown: str
    tags: List[str] = []
    topic: str = "General"


class BookmarkTopicUpdateRequest(BaseModel):
    topic: str


class BookmarkResponse(BaseModel):
    id: str
    title: str
    session_id: str
    query: str
    num_papers: int
    created_at: str
    tags: List[str]
    topic: str = "General"


class BulkDeleteBookmarksRequest(BaseModel):
    bookmark_ids: List[str]


class BulkMoveBookmarksRequest(BaseModel):
    bookmark_ids: List[str]
    topic: str


class BookmarkNotesUpdateRequest(BaseModel):
    notes: Optional[str] = None
    highlights: Optional[List[dict]] = None


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/bookmarks")
async def create_bookmark(request: BookmarkCreateRequest, username: str = Depends(get_current_user)):
    """Save a deep research result as a bookmark."""
    bookmark_id = f"bm_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    workspace_path = ""
    with review_sessions_lock:
        if request.session_id in review_sessions:
            workspace_path = review_sessions[request.session_id].get("workspace_path", "")

    bookmark = {
        "id": bookmark_id,
        "username": username,
        "title": request.title,
        "session_id": request.session_id,
        "workspace_path": workspace_path,
        "query": request.query,
        "papers": request.papers,
        "num_papers": len(request.papers),
        "report_markdown": request.report_markdown,
        "created_at": datetime.now().isoformat(),
        "tags": request.tags,
        "topic": request.topic,
    }

    data = load_bookmarks()
    data["bookmarks"].append(bookmark)
    save_bookmarks(data)

    return BookmarkResponse(
        id=bookmark_id,
        title=request.title,
        session_id=request.session_id,
        query=request.query,
        num_papers=len(request.papers),
        created_at=bookmark["created_at"],
        tags=request.tags,
        topic=request.topic,
    )


@router.get("/bookmarks")
async def list_bookmarks(username: str = Depends(get_current_user)):
    """List bookmarks for the current user (summary only)."""
    data = load_bookmarks()
    return {
        "bookmarks": [
            {
                "id": bm["id"],
                "title": bm["title"],
                "session_id": bm["session_id"],
                "query": bm.get("query", ""),
                "num_papers": bm.get("num_papers", 0),
                "created_at": bm["created_at"],
                "tags": bm.get("tags", []),
                "topic": bm.get("topic", "General"),
                "has_notes": bool(bm.get("notes", "").strip()) or bool(bm.get("highlights", [])),
            }
            for bm in data["bookmarks"]
            if bm.get("username") == username
        ]
    }


@router.get("/bookmarks/{bookmark_id}")
async def get_bookmark(bookmark_id: str, username: str = Depends(get_current_user)):
    """Get full bookmark detail including report."""
    data = load_bookmarks()
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id:
            if bm.get("username") != username:
                raise HTTPException(status_code=403, detail="Access denied")
            return bm
    raise HTTPException(status_code=404, detail="Bookmark not found")


@router.delete("/bookmarks/{bookmark_id}")
async def delete_bookmark(bookmark_id: str, username: str = Depends(get_current_user)):
    """Delete a bookmark owned by the current user."""
    data = load_bookmarks()
    original_len = len(data["bookmarks"])
    data["bookmarks"] = [
        bm for bm in data["bookmarks"]
        if not (bm["id"] == bookmark_id and bm.get("username") == username)
    ]

    if len(data["bookmarks"]) == original_len:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    save_bookmarks(data)
    return {"success": True, "message": "Bookmark deleted"}


@router.patch("/bookmarks/{bookmark_id}/topic")
async def update_bookmark_topic(
    bookmark_id: str, request: BookmarkTopicUpdateRequest,
    username: str = Depends(get_current_user),
):
    """Update a bookmark's topic."""
    data = load_bookmarks()
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id:
            if bm.get("username") != username:
                raise HTTPException(status_code=403, detail="Access denied")
            bm["topic"] = request.topic
            save_bookmarks(data)
            return {"success": True, "topic": request.topic}
    raise HTTPException(status_code=404, detail="Bookmark not found")


@router.patch("/bookmarks/{bookmark_id}/notes")
async def update_bookmark_notes(
    bookmark_id: str, request: BookmarkNotesUpdateRequest,
    username: str = Depends(get_current_user),
):
    """Update a bookmark's personal notes and/or highlights."""
    data = load_bookmarks()
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id:
            if bm.get("username") != username:
                raise HTTPException(status_code=403, detail="Access denied")
            if request.notes is not None:
                bm["notes"] = request.notes
            if request.highlights is not None:
                bm["highlights"] = request.highlights
            save_bookmarks(data)
            return {
                "success": True,
                "notes": bm.get("notes", ""),
                "highlights": bm.get("highlights", []),
            }
    raise HTTPException(status_code=404, detail="Bookmark not found")


@router.post("/bookmarks/bulk-delete")
async def bulk_delete_bookmarks(request: BulkDeleteBookmarksRequest, username: str = Depends(get_current_user)):
    """Delete multiple bookmarks owned by the current user."""
    data = load_bookmarks()
    ids_set = set(request.bookmark_ids)
    original = len(data["bookmarks"])
    data["bookmarks"] = [
        bm for bm in data["bookmarks"]
        if not (bm["id"] in ids_set and bm.get("username") == username)
    ]
    deleted = original - len(data["bookmarks"])
    if deleted == 0:
        raise HTTPException(status_code=404, detail="No bookmarks found to delete")
    save_bookmarks(data)
    return {"success": True, "deleted_count": deleted}


@router.post("/bookmarks/bulk-move")
async def bulk_move_bookmarks(request: BulkMoveBookmarksRequest, username: str = Depends(get_current_user)):
    """Move multiple bookmarks to a new topic (current user only)."""
    data = load_bookmarks()
    ids_set = set(request.bookmark_ids)
    updated = 0
    for bm in data["bookmarks"]:
        if bm["id"] in ids_set and bm.get("username") == username:
            bm["topic"] = request.topic
            updated += 1
    if updated == 0:
        raise HTTPException(status_code=404, detail="No bookmarks found to update")
    save_bookmarks(data)
    return {"success": True, "updated_count": updated, "topic": request.topic}
