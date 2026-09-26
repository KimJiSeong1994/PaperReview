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
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

logger = logging.getLogger(__name__)

from .deps import (
    load_bookmarks_for_user,
    modify_bookmarks,
    review_sessions,
    review_sessions_lock,
    get_openai_client,
    limiter,
)
from .highlight_service import (
    CATEGORY_CONFIG,
    generate_highlights,
    _find_verbatim_or_fuzzy,
)
from src.events.emit import emit_or_warn
from src.events.event_types import EventType, UserEvent
from src.storage.bookmark_db import bookmark_belongs_to_account
from src.storage.user_db import AccountLifecycleError
from src.recommendation_attribution import attribute_recommendation_outcome
from .deps.auth import AuthenticatedPrincipal, get_authenticated_principal
from .deps.storage import _get_user_db, _get_bookmark_db

router = APIRouter(prefix="/api", tags=["bookmarks"])


@contextmanager
def _account_guard(principal):
    try:
        with _get_user_db().account_guard(
            principal.username, principal.account_incarnation
        ) as account:
            yield account
    except AccountLifecycleError:
        raise HTTPException(status_code=401, detail="Account deleted or disabled")
    except (sqlite3.Error, OSError):
        raise HTTPException(status_code=503, detail="Account authority unavailable")


def _belongs(record, principal, account):
    return bookmark_belongs_to_account(
        record,
        username=principal.username,
        account_incarnation=principal.account_incarnation,
        legacy_event_cutoff=account["legacy_event_cutoff"],
    )


@contextmanager
def _modify_owned(principal):
    with _account_guard(principal) as account:
        with modify_bookmarks() as all_data:
            owned = [
                bm for bm in all_data["bookmarks"] if _belongs(bm, principal, account)
            ]
            other = [
                bm
                for bm in all_data["bookmarks"]
                if not _belongs(bm, principal, account)
            ]
            data = {"bookmarks": owned}
            yield data
            for bm in data["bookmarks"]:
                bm["account_incarnation"] = principal.account_incarnation
            all_data["bookmarks"] = other + data["bookmarks"]


def _get_owned(bookmark_id, principal):
    with _account_guard(principal) as account:
        bm = _get_bookmark_db().get_by_id(bookmark_id)
        if bm is None or not _belongs(bm, principal, account):
            raise HTTPException(status_code=404, detail="Bookmark not found")
        return bm


def _emit_bound(principal, event):
    event.payload["account_incarnation"] = principal.account_incarnation
    emit_or_warn(event)


def _attribute_saved_papers(bookmark, principal):
    """Secondary attribution must never turn a committed save into an error."""
    if not bookmark["papers"]:
        return [{"status": "not_attributed", "reason": "missing_paper_metadata"}]
    try:
        authority = _get_user_db()
        events_db = Path(
            os.getenv(
                "EVENTS_DB_PATH", str(Path(os.getenv("DATA_DIR", "data")) / "events.db")
            )
        )
        return [
            attribute_recommendation_outcome(
                authority=authority,
                events_db=events_db,
                username=principal.username,
                account_incarnation=principal.account_incarnation,
                paper=paper,
                kind="save",
                outcome_id=bookmark["id"],
            )
            for paper in bookmark["papers"]
        ]
    except Exception:
        logger.warning("Recommendation save attribution unavailable")
        return [{"status": "unavailable", "reason": "attribution_unavailable"}]


# ── Pydantic models ───────────────────────────────────────────────────
#
# Body-size caps (RT4): every string is bounded and every list is capped.
# The limits are intentionally generous for legitimate payloads (512 KB
# markdown report, 500 papers, 50 tags) but firmly reject the kind of
# 10 MB blob that a live penetration test accepted.

# Reasonable upper bound on a review report — 512 KB of markdown.
# Typical reports are a few KB; this cap is ~1000x bigger than average.
_MAX_REPORT_BYTES = 524288


class BookmarkCreateRequest(BaseModel):
    session_id: str = Field(..., max_length=200)
    title: str = Field(..., max_length=500)
    query: str = Field("", max_length=2000)
    papers: List[dict] = Field(default_factory=list, max_length=500)
    report_markdown: str = Field(..., max_length=_MAX_REPORT_BYTES)
    tags: List[str] = Field(default_factory=list, max_length=50)
    topic: str = Field("General", max_length=100)


class BookmarkTitleUpdateRequest(BaseModel):
    title: str = Field(..., max_length=500)


class BookmarkTopicUpdateRequest(BaseModel):
    topic: str = Field(..., max_length=100)


class BookmarkResponse(BaseModel):
    id: str
    title: str
    session_id: str
    query: str
    num_papers: int
    created_at: str
    tags: List[str]
    topic: str = "General"
    recommendation_attribution: List[dict] = Field(default_factory=list)


class BookmarkFromPaperRequest(BaseModel):
    title: str = Field(..., max_length=500)
    authors: List[str] = Field(default_factory=list, max_length=200)
    year: Optional[int] = None
    venue: Optional[str] = Field(None, max_length=500)
    doi: Optional[str] = Field(None, max_length=200)
    arxiv_id: Optional[str] = Field(None, max_length=100)
    openalex_id: Optional[str] = Field(None, max_length=256)
    semantic_scholar_id: Optional[str] = Field(None, max_length=256)
    pmid: Optional[str] = Field(None, max_length=256)
    url: Optional[str] = Field(None, max_length=2048)
    pdf_url: Optional[str] = Field(None, max_length=2048)
    context: Optional[str] = Field(None, max_length=_MAX_REPORT_BYTES)
    source_curriculum: Optional[str] = Field(None, max_length=500)
    topic: str = Field("Curriculum Papers", max_length=100)
    tags: List[str] = Field(default_factory=list, max_length=50)


class BulkDeleteBookmarksRequest(BaseModel):
    bookmark_ids: List[str] = Field(..., max_length=500)


class BulkMoveBookmarksRequest(BaseModel):
    bookmark_ids: List[str] = Field(..., max_length=500)
    topic: str = Field(..., max_length=100)


class BookmarkNotesUpdateRequest(BaseModel):
    notes: Optional[str] = Field(None, max_length=_MAX_REPORT_BYTES)
    highlights: Optional[List[dict]] = Field(None, max_length=500)


# ── Endpoints ──────────────────────────────────────────────────────────


@router.post("/bookmarks")
@limiter.limit("30/minute")
async def create_bookmark(
    request: Request,
    payload: BookmarkCreateRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    username = principal.username
    """Save a deep research result as a bookmark."""
    bookmark_id = (
        f"bm_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    )

    workspace_path = ""
    with _account_guard(principal) as account, review_sessions_lock:
        if payload.session_id in review_sessions:
            session = review_sessions[payload.session_id]
            if not _belongs(session, principal, account):
                raise HTTPException(status_code=404, detail="Review session not found")
            workspace_path = session.get("workspace_path", "")

    bookmark = {
        "id": bookmark_id,
        "username": username,
        "title": payload.title,
        "session_id": payload.session_id,
        "workspace_path": workspace_path,
        "query": payload.query,
        "papers": payload.papers,
        "num_papers": len(payload.papers),
        "report_markdown": payload.report_markdown,
        "created_at": datetime.now().isoformat(),
        "tags": payload.tags,
        "topic": payload.topic,
    }

    with _modify_owned(principal) as data:
        data["bookmarks"].append(bookmark)

    attribution = _attribute_saved_papers(bookmark, principal)
    _emit_bound(
        principal,
        UserEvent(
            user_id=username,
            event_type=EventType.BOOKMARK_ADD,
            paper_id=bookmark_id,
            payload={
                "topic": payload.topic[:200],
                "title": payload.title[:200],
            },
        ),
    )

    return BookmarkResponse(
        id=bookmark_id,
        title=payload.title,
        session_id=payload.session_id,
        query=payload.query,
        num_papers=len(payload.papers),
        created_at=bookmark["created_at"],
        tags=payload.tags,
        topic=payload.topic,
        recommendation_attribution=attribution,
    )


@router.post("/bookmarks/from-paper")
@limiter.limit("30/minute")
async def create_bookmark_from_paper(
    request: Request,
    payload: BookmarkFromPaperRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    username = principal.username
    """Create a lightweight bookmark from a paper's metadata (e.g., from curriculum).

    F-34: IP rate-limited to 30/min — matches the primary create_bookmark
    endpoint and caps write-amplification from the curriculum/explore UI.
    """
    bookmark_id = (
        f"bm_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    )

    report_lines = [f"# {payload.title}\n"]
    if payload.authors:
        report_lines.append(f"**Authors**: {', '.join(payload.authors)}\n")
    if payload.year:
        report_lines.append(f"**Year**: {payload.year}\n")
    if payload.venue:
        report_lines.append(f"**Venue**: {payload.venue}\n")
    if payload.context:
        report_lines.append(f"\n## Context\n{payload.context}\n")

    paper_entry = {
        "title": payload.title,
        "authors": payload.authors,
        "year": payload.year,
        "venue": payload.venue or "",
        "doi": payload.doi or "",
        "arxiv_id": payload.arxiv_id or "",
        "openalex_id": payload.openalex_id or "",
        "semantic_scholar_id": payload.semantic_scholar_id or "",
        "pmid": payload.pmid or "",
        "url": payload.url or "",
        "pdf_url": payload.pdf_url or "",
    }

    bookmark = {
        "id": bookmark_id,
        "username": username,
        "title": payload.title,
        "session_id": "",
        "workspace_path": "",
        "query": "",
        "papers": [paper_entry],
        "num_papers": 1,
        "report_markdown": "\n".join(report_lines),
        "created_at": datetime.now().isoformat(),
        "tags": payload.tags or (["curriculum"] if payload.source_curriculum else []),
        "topic": payload.topic,
    }

    with _modify_owned(principal) as data:
        data["bookmarks"].append(bookmark)

    attribution = _attribute_saved_papers(bookmark, principal)
    _emit_bound(
        principal,
        UserEvent(
            user_id=username,
            event_type=EventType.BOOKMARK_ADD,
            paper_id=bookmark_id,
            payload={
                "topic": payload.topic[:200],
                "title": payload.title[:200],
            },
        ),
    )

    return BookmarkResponse(
        id=bookmark_id,
        title=payload.title,
        session_id="",
        query="",
        num_papers=1,
        created_at=bookmark["created_at"],
        tags=bookmark["tags"],
        topic=payload.topic,
        recommendation_attribution=attribution,
    )


@router.get("/bookmarks")
async def list_bookmarks(
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    """List bookmarks for the current user (summary only)."""
    with _account_guard(principal) as account:
        user_bookmarks = [
            bm
            for bm in load_bookmarks_for_user(principal.username, include_reports=False)
            if _belongs(bm, principal, account)
        ]
    return {
        "bookmarks": [
            {
                "id": bm.get("id", ""),
                "title": bm.get("title", ""),
                "session_id": bm.get("session_id", ""),
                "query": bm.get("query", ""),
                "num_papers": bm.get("num_papers", 0),
                "created_at": bm.get("created_at", ""),
                "tags": bm.get("tags", []),
                "topic": bm.get("topic", "General"),
                "has_notes": bool((bm.get("notes") or "").strip())
                or bool(bm.get("highlights", [])),
                "has_citation_tree": bool(bm.get("citation_tree")),
                "has_share": bool(bm.get("share")),
            }
            for bm in user_bookmarks
        ]
    }


@router.get("/bookmarks/{bookmark_id}")
async def get_bookmark(
    bookmark_id: str,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    """Get full bookmark detail including report."""
    return _get_owned(bookmark_id, principal)


@router.delete("/bookmarks/{bookmark_id}")
@limiter.limit("30/minute")
async def delete_bookmark(
    request: Request,
    bookmark_id: str,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    username = principal.username
    """Delete a bookmark owned by the current user."""
    with _modify_owned(principal) as data:
        original_len = len(data["bookmarks"])
        data["bookmarks"] = [
            bm
            for bm in data["bookmarks"]
            if not (bm["id"] == bookmark_id and bm.get("username") == username)
        ]
        if len(data["bookmarks"]) == original_len:
            raise HTTPException(status_code=404, detail="Bookmark not found")

    _emit_bound(
        principal,
        UserEvent(
            user_id=username,
            event_type=EventType.BOOKMARK_REMOVE,
            paper_id=bookmark_id,
            payload={"bookmark_id": bookmark_id},
        ),
    )
    return {"success": True, "message": "Bookmark deleted"}


@router.patch("/bookmarks/{bookmark_id}/topic")
@limiter.limit("30/minute")
async def update_bookmark_topic(
    request: Request,
    bookmark_id: str,
    payload: BookmarkTopicUpdateRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    username = principal.username
    """Update a bookmark's topic."""
    with _modify_owned(principal) as data:
        for bm in data["bookmarks"]:
            if bm["id"] == bookmark_id:
                if bm.get("username") != username:
                    raise HTTPException(status_code=404, detail="Bookmark not found")
                bm["topic"] = payload.topic
                return {"success": True, "topic": payload.topic}
        raise HTTPException(status_code=404, detail="Bookmark not found")


@router.patch("/bookmarks/{bookmark_id}/title")
@limiter.limit("30/minute")
async def update_bookmark_title(
    request: Request,
    bookmark_id: str,
    payload: BookmarkTitleUpdateRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    username = principal.username
    """Update a bookmark's title.

    F-34: IP rate-limited to 30/min to bound write volume on this PATCH.
    """
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    with _modify_owned(principal) as data:
        for bm in data["bookmarks"]:
            if bm["id"] == bookmark_id:
                if bm.get("username") != username:
                    raise HTTPException(status_code=404, detail="Bookmark not found")
                bm["title"] = title
                return {"success": True, "title": title}
        raise HTTPException(status_code=404, detail="Bookmark not found")


@router.patch("/bookmarks/{bookmark_id}/notes")
@limiter.limit("60/minute")
async def update_bookmark_notes(
    request: Request,
    bookmark_id: str,
    payload: BookmarkNotesUpdateRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    username = principal.username
    """Update a bookmark's personal notes and/or highlights."""
    result: dict | None = None
    highlight_event_type: EventType | None = None
    prev_highlight_count: int = 0

    with _modify_owned(principal) as data:
        for bm in data["bookmarks"]:
            if bm["id"] == bookmark_id:
                if bm.get("username") != username:
                    raise HTTPException(status_code=404, detail="Bookmark not found")
                if payload.notes is not None:
                    bm["notes"] = payload.notes
                if payload.highlights is not None:
                    prev_highlight_count = len(bm.get("highlights") or [])
                    bm["highlights"] = payload.highlights
                    new_count = len(payload.highlights)
                    if new_count == 0:
                        highlight_event_type = EventType.HIGHLIGHT_DELETE
                    elif prev_highlight_count == 0:
                        highlight_event_type = EventType.HIGHLIGHT_CREATE
                    else:
                        highlight_event_type = EventType.HIGHLIGHT_UPDATE
                result = {
                    "success": True,
                    "notes": bm.get("notes", ""),
                    "highlights": bm.get("highlights", []),
                }
                break
        if result is None:
            raise HTTPException(status_code=404, detail="Bookmark not found")

    if highlight_event_type is not None:
        _emit_bound(
            principal,
            UserEvent(
                user_id=username,
                event_type=highlight_event_type,
                paper_id=bookmark_id,
                payload={
                    "bookmark_id": bookmark_id,
                    "highlight_count": len(payload.highlights),
                },
            ),
        )

    return result


@router.post("/bookmarks/{bookmark_id}/auto-highlight")
@limiter.limit("5/minute")
async def auto_highlight_bookmark(
    request: Request,
    bookmark_id: str,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    username = principal.username
    """Use LLM to automatically extract key highlights from the bookmark report.

    Async so the long-running LLM call is offloaded via
    ``run_in_threadpool`` rather than holding a FastAPI threadpool worker
    for the entire request lifetime. Prevents starvation of other sync
    endpoints during bursts of auto-highlight traffic.
    """
    from openai import APITimeoutError, RateLimitError, APIError

    # Phase 1: Read bookmark and report (before LLM call)
    bookmark = _get_owned(bookmark_id, principal)

    report = bookmark.get("report_markdown", "")
    if not report.strip():
        raise HTTPException(status_code=400, detail="No report content to analyze")

    query = bookmark.get("query", "")
    title = bookmark.get("title", "")

    # Phase 2: LLM call (potentially long-running, no lock held) — offloaded
    # to threadpool so the event loop stays free for other requests.
    client = get_openai_client()
    try:
        llm_highlights = await run_in_threadpool(
            generate_highlights, report, query, title, client
        )
    except APITimeoutError:
        raise HTTPException(
            status_code=504, detail="LLM analysis timed out. Please retry."
        )
    except RateLimitError:
        raise HTTPException(
            status_code=429, detail="Rate limited. Please wait and retry."
        )
    except APIError as e:
        raise HTTPException(status_code=502, detail=f"LLM service error: {e.message}")
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Phase 3: Atomic read-modify-write under single lock
    with _modify_owned(principal) as data:
        bookmark = None
        for bm in data["bookmarks"]:
            if bm["id"] == bookmark_id and bm.get("username") == username:
                bookmark = bm
                break
        if not bookmark:
            raise HTTPException(status_code=404, detail="Bookmark not found")

        existing_by_text = {
            h["text"]: i for i, h in enumerate(bookmark.get("highlights", []))
        }
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
                confidence_level = max(
                    1, min(5, int(float(item.get("confidence_level", 3))))
                )
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
            memo = (
                f"{cfg['label']} {reviewer_comment}"
                if reviewer_comment
                else cfg["label"]
            )

            # Enrich existing highlight if it lacks deep comment fields
            existing_idx = (
                existing_by_text.get(text)
                if text in existing_by_text
                else existing_by_text.get(matched_text)
            )
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
                if reviewer_comment and (
                    not existing_hl.get("memo")
                    or existing_hl["memo"] == existing_hl.get("category", "")
                ):
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

            new_highlights.append(
                {
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
                }
            )
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
@limiter.limit("10/minute")
async def bulk_delete_bookmarks(
    request: Request,
    payload: BulkDeleteBookmarksRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    username = principal.username
    """Delete multiple bookmarks owned by the current user."""
    with _modify_owned(principal) as data:
        ids_set = set(payload.bookmark_ids)
        deleted_ids = {bm["id"] for bm in data["bookmarks"] if bm["id"] in ids_set}
        original = len(data["bookmarks"])
        data["bookmarks"] = [
            bm
            for bm in data["bookmarks"]
            if not (bm["id"] in ids_set and bm.get("username") == username)
        ]
        deleted = original - len(data["bookmarks"])
        if deleted == 0:
            raise HTTPException(status_code=404, detail="No bookmarks found to delete")

    for bm_id in sorted(deleted_ids):
        _emit_bound(
            principal,
            UserEvent(
                user_id=username,
                event_type=EventType.BOOKMARK_REMOVE,
                paper_id=bm_id,
                payload={"bookmark_id": bm_id, "bulk": True},
            ),
        )
    return {"success": True, "deleted_count": deleted}


@router.post("/bookmarks/bulk-move")
@limiter.limit("10/minute")
async def bulk_move_bookmarks(
    request: Request,
    payload: BulkMoveBookmarksRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    username = principal.username
    """Move multiple bookmarks to a new topic (current user only).

    F-34: IP rate-limited to 10/min — this endpoint updates up to 500
    bookmarks in one shot, so looser caps would invite burst abuse.
    """
    with _modify_owned(principal) as data:
        ids_set = set(payload.bookmark_ids)
        updated = 0
        for bm in data["bookmarks"]:
            if bm["id"] in ids_set and bm.get("username") == username:
                bm["topic"] = payload.topic
                updated += 1
        if updated == 0:
            raise HTTPException(status_code=404, detail="No bookmarks found to update")
    return {"success": True, "updated_count": updated, "topic": payload.topic}
