"""
Bookmark CRUD endpoints (per-user isolated):
  POST   /api/bookmarks
  GET    /api/bookmarks
  GET    /api/bookmarks/{bookmark_id}
  DELETE /api/bookmarks/{bookmark_id}
  PATCH  /api/bookmarks/{bookmark_id}/topic
  PATCH  /api/bookmarks/{bookmark_id}/notes
  POST   /api/bookmarks/{bookmark_id}/auto-highlight
  POST   /api/bookmarks/bulk-delete
  POST   /api/bookmarks/bulk-move
"""

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from .deps import load_bookmarks, save_bookmarks, modify_bookmarks, review_sessions, review_sessions_lock, get_current_user, get_openai_client
from .highlight_service import CATEGORY_CONFIG, generate_highlights, _find_verbatim_or_fuzzy

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

    with modify_bookmarks() as data:
        data["bookmarks"].append(bookmark)

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
                "has_citation_tree": bool(bm.get("citation_tree")),
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
    with modify_bookmarks() as data:
        original_len = len(data["bookmarks"])
        data["bookmarks"] = [
            bm for bm in data["bookmarks"]
            if not (bm["id"] == bookmark_id and bm.get("username") == username)
        ]
        if len(data["bookmarks"]) == original_len:
            raise HTTPException(status_code=404, detail="Bookmark not found")
    return {"success": True, "message": "Bookmark deleted"}


@router.patch("/bookmarks/{bookmark_id}/topic")
async def update_bookmark_topic(
    bookmark_id: str, request: BookmarkTopicUpdateRequest,
    username: str = Depends(get_current_user),
):
    """Update a bookmark's topic."""
    with modify_bookmarks() as data:
        for bm in data["bookmarks"]:
            if bm["id"] == bookmark_id:
                if bm.get("username") != username:
                    raise HTTPException(status_code=403, detail="Access denied")
                bm["topic"] = request.topic
                return {"success": True, "topic": request.topic}
        raise HTTPException(status_code=404, detail="Bookmark not found")


@router.patch("/bookmarks/{bookmark_id}/notes")
async def update_bookmark_notes(
    bookmark_id: str, request: BookmarkNotesUpdateRequest,
    username: str = Depends(get_current_user),
):
    """Update a bookmark's personal notes and/or highlights."""
    with modify_bookmarks() as data:
        for bm in data["bookmarks"]:
            if bm["id"] == bookmark_id:
                if bm.get("username") != username:
                    raise HTTPException(status_code=403, detail="Access denied")
                if request.notes is not None:
                    bm["notes"] = request.notes
                if request.highlights is not None:
                    bm["highlights"] = request.highlights
                return {
                    "success": True,
                    "notes": bm.get("notes", ""),
                    "highlights": bm.get("highlights", []),
                }
        raise HTTPException(status_code=404, detail="Bookmark not found")


@router.post("/bookmarks/{bookmark_id}/auto-highlight")
def auto_highlight_bookmark(bookmark_id: str, username: str = Depends(get_current_user)):
    """Use LLM to automatically extract key highlights from the bookmark report."""
    from openai import APITimeoutError, RateLimitError, APIError

    # Phase 1: Read bookmark and report (before LLM call)
    data = load_bookmarks()
    bookmark = None
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id:
            if bm.get("username") != username:
                raise HTTPException(status_code=403, detail="Access denied")
            bookmark = bm
            break
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    report = bookmark.get("report_markdown", "")
    if not report.strip():
        raise HTTPException(status_code=400, detail="No report content to analyze")

    query = bookmark.get("query", "")
    title = bookmark.get("title", "")

    # Phase 2: LLM call (potentially long-running, no lock held)
    client = get_openai_client()
    try:
        llm_highlights = generate_highlights(report, query, title, client)
    except APITimeoutError:
        raise HTTPException(status_code=504, detail="LLM analysis timed out. Please retry.")
    except RateLimitError:
        raise HTTPException(status_code=429, detail="Rate limited. Please wait and retry.")
    except APIError as e:
        raise HTTPException(status_code=502, detail=f"LLM service error: {e.message}")
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Phase 3: Atomic read-modify-write under single lock
    with modify_bookmarks() as data:
        bookmark = None
        for bm in data["bookmarks"]:
            if bm["id"] == bookmark_id and bm.get("username") == username:
                bookmark = bm
                break
        if not bookmark:
            raise HTTPException(status_code=404, detail="Bookmark not found")

        existing_by_text = {h["text"]: i for i, h in enumerate(bookmark.get("highlights", []))}
        new_highlights = list(bookmark.get("highlights", []))
        added_count = 0
        enriched_count = 0
        valid_categories = set(CATEGORY_CONFIG.keys())

        for item in llm_highlights:
            text = item.get("text", "").strip()
            category = item.get("category", "finding")
            if category not in valid_categories:
                category = "finding"
            reviewer_comment = item.get("reviewer_comment", "").strip()
            implication = item.get("implication", "").strip()
            # Backward compat: fall back to legacy "reason" if reviewer_comment absent
            if not reviewer_comment:
                reviewer_comment = item.get("reason", "").strip()
            strength_or_weakness = item.get("strength_or_weakness", "").strip().lower()
            if strength_or_weakness not in ("strength", "weakness"):
                strength_or_weakness = ""
            question_for_authors = item.get("question_for_authors", "").strip()
            try:
                confidence_level = max(1, min(5, int(float(item.get("confidence_level", 3)))))
            except (ValueError, TypeError):
                confidence_level = 3
            try:
                significance = max(1, min(5, int(float(item.get("significance", 3)))))
            except (ValueError, TypeError):
                significance = 3
            section = item.get("section", "")
            if not text or len(text) < 5:
                continue

            # Verbatim match with fuzzy fallback
            matched_text = _find_verbatim_or_fuzzy(text, report)
            if not matched_text:
                continue

            cfg = CATEGORY_CONFIG[category]
            memo = f"{cfg['label']} {reviewer_comment}" if reviewer_comment else cfg["label"]

            # Enrich existing highlight if it lacks deep comment fields
            existing_idx = existing_by_text.get(text) if text in existing_by_text else existing_by_text.get(matched_text)
            if existing_idx is not None:
                existing_hl = new_highlights[existing_idx]
                enriched = False
                if implication and not existing_hl.get("implication"):
                    existing_hl["implication"] = implication
                    enriched = True
                if section and not existing_hl.get("section"):
                    existing_hl["section"] = section
                    enriched = True
                if significance and not existing_hl.get("significance"):
                    existing_hl["significance"] = significance
                    enriched = True
                if not existing_hl.get("category"):
                    existing_hl["category"] = category
                    existing_hl["color"] = cfg["color"]
                    enriched = True
                if reviewer_comment and (not existing_hl.get("memo") or existing_hl["memo"] == existing_hl.get("category", "")):
                    existing_hl["memo"] = memo
                    enriched = True
                if strength_or_weakness and not existing_hl.get("strength_or_weakness"):
                    existing_hl["strength_or_weakness"] = strength_or_weakness
                    enriched = True
                if question_for_authors and not existing_hl.get("question_for_authors"):
                    existing_hl["question_for_authors"] = question_for_authors
                    enriched = True
                if confidence_level and not existing_hl.get("confidence_level"):
                    existing_hl["confidence_level"] = confidence_level
                    enriched = True
                if enriched:
                    enriched_count += 1
                continue

            new_highlights.append({
                "id": f"hl_{uuid.uuid4().hex[:12]}",
                "text": matched_text,
                "color": cfg["color"],
                "memo": memo,
                "category": category,
                "significance": significance,
                "section": section,
                "implication": implication,
                "strength_or_weakness": strength_or_weakness,
                "question_for_authors": question_for_authors,
                "confidence_level": confidence_level,
                "created_at": datetime.now().isoformat(),
            })
            existing_by_text[matched_text] = len(new_highlights) - 1
            added_count += 1

        bookmark["highlights"] = new_highlights

    return {
        "success": True,
        "highlights": new_highlights,
        "added_count": added_count,
        "enriched_count": enriched_count,
    }


@router.post("/bookmarks/bulk-delete")
async def bulk_delete_bookmarks(request: BulkDeleteBookmarksRequest, username: str = Depends(get_current_user)):
    """Delete multiple bookmarks owned by the current user."""
    with modify_bookmarks() as data:
        ids_set = set(request.bookmark_ids)
        original = len(data["bookmarks"])
        data["bookmarks"] = [
            bm for bm in data["bookmarks"]
            if not (bm["id"] in ids_set and bm.get("username") == username)
        ]
        deleted = original - len(data["bookmarks"])
        if deleted == 0:
            raise HTTPException(status_code=404, detail="No bookmarks found to delete")
    return {"success": True, "deleted_count": deleted}


@router.post("/bookmarks/bulk-move")
async def bulk_move_bookmarks(request: BulkMoveBookmarksRequest, username: str = Depends(get_current_user)):
    """Move multiple bookmarks to a new topic (current user only)."""
    with modify_bookmarks() as data:
        ids_set = set(request.bookmark_ids)
        updated = 0
        for bm in data["bookmarks"]:
            if bm["id"] in ids_set and bm.get("username") == username:
                bm["topic"] = request.topic
                updated += 1
        if updated == 0:
            raise HTTPException(status_code=404, detail="No bookmarks found to update")
    return {"success": True, "updated_count": updated, "topic": request.topic}
