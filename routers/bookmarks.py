"""
Bookmark CRUD endpoints:
  POST   /api/bookmarks
  GET    /api/bookmarks
  GET    /api/bookmarks/{bookmark_id}
  DELETE /api/bookmarks/{bookmark_id}
  PATCH  /api/bookmarks/{bookmark_id}/topic
  POST   /api/bookmarks/bulk-delete
  POST   /api/bookmarks/bulk-move
"""

import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .deps import load_bookmarks, save_bookmarks, review_sessions, review_sessions_lock

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


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/bookmarks")
async def create_bookmark(request: BookmarkCreateRequest):
    """Save a deep research result as a bookmark."""
    bookmark_id = f"bm_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    workspace_path = ""
    with review_sessions_lock:
        if request.session_id in review_sessions:
            workspace_path = review_sessions[request.session_id].get("workspace_path", "")

    bookmark = {
        "id": bookmark_id,
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
async def list_bookmarks():
    """List all bookmarks (summary only, without report content)."""
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
            }
            for bm in data["bookmarks"]
        ]
    }


@router.get("/bookmarks/{bookmark_id}")
async def get_bookmark(bookmark_id: str):
    """Get full bookmark detail including report."""
    data = load_bookmarks()
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id:
            return bm
    raise HTTPException(status_code=404, detail="Bookmark not found")


@router.delete("/bookmarks/{bookmark_id}")
async def delete_bookmark(bookmark_id: str):
    """Delete a bookmark."""
    data = load_bookmarks()
    original_len = len(data["bookmarks"])
    data["bookmarks"] = [bm for bm in data["bookmarks"] if bm["id"] != bookmark_id]

    if len(data["bookmarks"]) == original_len:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    save_bookmarks(data)
    return {"success": True, "message": "Bookmark deleted"}


@router.patch("/bookmarks/{bookmark_id}/topic")
async def update_bookmark_topic(bookmark_id: str, request: BookmarkTopicUpdateRequest):
    """Update a bookmark's topic."""
    data = load_bookmarks()
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id:
            bm["topic"] = request.topic
            save_bookmarks(data)
            return {"success": True, "topic": request.topic}
    raise HTTPException(status_code=404, detail="Bookmark not found")


@router.post("/bookmarks/bulk-delete")
async def bulk_delete_bookmarks(request: BulkDeleteBookmarksRequest):
    """Delete multiple bookmarks at once."""
    data = load_bookmarks()
    ids_set = set(request.bookmark_ids)
    original = len(data["bookmarks"])
    data["bookmarks"] = [bm for bm in data["bookmarks"] if bm["id"] not in ids_set]
    deleted = original - len(data["bookmarks"])
    if deleted == 0:
        raise HTTPException(status_code=404, detail="No bookmarks found to delete")
    save_bookmarks(data)
    return {"success": True, "deleted_count": deleted}


@router.post("/bookmarks/bulk-move")
async def bulk_move_bookmarks(request: BulkMoveBookmarksRequest):
    """Move multiple bookmarks to a new topic."""
    data = load_bookmarks()
    ids_set = set(request.bookmark_ids)
    updated = 0
    for bm in data["bookmarks"]:
        if bm["id"] in ids_set:
            bm["topic"] = request.topic
            updated += 1
    if updated == 0:
        raise HTTPException(status_code=404, detail="No bookmarks found to update")
    save_bookmarks(data)
    return {"success": True, "updated_count": updated, "topic": request.topic}
