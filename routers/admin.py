"""
Admin-only endpoints:
  GET    /api/admin/dashboard
  GET    /api/admin/users
  PATCH  /api/admin/users/{username}/role
  DELETE /api/admin/users/{username}
  GET    /api/admin/papers
  DELETE /api/admin/papers
  GET    /api/admin/bookmarks
  DELETE /api/admin/bookmarks/{bookmark_id}
"""

import json
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .deps import get_admin_user, load_bookmarks, save_bookmarks, review_sessions, review_sessions_lock

router = APIRouter(prefix="/api/admin", tags=["admin"])

USERS_FILE = Path(__file__).resolve().parent.parent / "data" / "users.json"
PAPERS_FILE = Path(__file__).resolve().parent.parent / "data" / "raw" / "papers.json"


# ── Helpers ──────────────────────────────────────────────────────────

def _load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_users(users: dict) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)


def _load_papers() -> dict:
    if not PAPERS_FILE.exists():
        return {"metadata": {}, "papers": []}
    with open(PAPERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_papers(data: dict) -> None:
    PAPERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PAPERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Pydantic models ─────────────────────────────────────────────────

class RoleUpdateRequest(BaseModel):
    role: str  # "admin" or "user"


class PaperDeleteRequest(BaseModel):
    indices: List[int]  # paper indices to delete


# ── Dashboard ────────────────────────────────────────────────────────

@router.get("/dashboard")
async def admin_dashboard(admin: str = Depends(get_admin_user)):
    """Return aggregate statistics for the admin dashboard."""
    users = _load_users()
    papers_data = _load_papers()
    bookmarks_data = load_bookmarks()

    with review_sessions_lock:
        session_count = len(review_sessions)

    return {
        "total_users": len(users),
        "total_papers": len(papers_data.get("papers", [])),
        "total_bookmarks": len(bookmarks_data.get("bookmarks", [])),
        "total_sessions": session_count,
    }


# ── Users ────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(admin: str = Depends(get_admin_user)):
    """List all registered users with their bookmark counts."""
    users = _load_users()
    bookmarks_data = load_bookmarks()

    # Count bookmarks per user
    bm_counts: dict[str, int] = {}
    for bm in bookmarks_data.get("bookmarks", []):
        owner = bm.get("username", "")
        bm_counts[owner] = bm_counts.get(owner, 0) + 1

    user_list = []
    for username, data in users.items():
        user_list.append({
            "username": username,
            "role": data.get("role", "user"),
            "created_at": data.get("created_at", ""),
            "bookmark_count": bm_counts.get(username, 0),
        })

    return {"users": user_list}


@router.patch("/users/{username}/role")
async def update_user_role(username: str, request: RoleUpdateRequest, admin: str = Depends(get_admin_user)):
    """Change a user's role (admin or user)."""
    if request.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'user'")

    if username == admin:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    users = _load_users()
    if username not in users:
        raise HTTPException(status_code=404, detail="User not found")

    users[username]["role"] = request.role
    _save_users(users)
    return {"success": True, "username": username, "role": request.role}


@router.delete("/users/{username}")
async def delete_user(username: str, admin: str = Depends(get_admin_user)):
    """Delete a user and all their bookmarks."""
    if username == admin:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    users = _load_users()
    if username not in users:
        raise HTTPException(status_code=404, detail="User not found")

    del users[username]
    _save_users(users)

    # Also delete their bookmarks
    data = load_bookmarks()
    data["bookmarks"] = [bm for bm in data["bookmarks"] if bm.get("username") != username]
    save_bookmarks(data)

    return {"success": True, "message": f"User '{username}' and their bookmarks deleted"}


# ── Papers ───────────────────────────────────────────────────────────

@router.get("/papers")
async def list_papers(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    admin: str = Depends(get_admin_user),
):
    """List papers with pagination."""
    papers_data = _load_papers()
    papers = papers_data.get("papers", [])
    total = len(papers)

    start = (page - 1) * page_size
    end = start + page_size
    page_papers = []
    for idx, p in enumerate(papers[start:end], start=start):
        page_papers.append({
            "index": idx,
            "title": p.get("title", "Untitled"),
            "authors": p.get("authors", [])[:3],
            "source": p.get("source", ""),
            "published_date": p.get("published_date", ""),
            "search_query": p.get("search_query", ""),
        })

    return {
        "papers": page_papers,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.delete("/papers")
async def delete_papers(request: PaperDeleteRequest, admin: str = Depends(get_admin_user)):
    """Delete papers by their indices."""
    papers_data = _load_papers()
    papers = papers_data.get("papers", [])

    indices_set = set(request.indices)
    papers_data["papers"] = [p for i, p in enumerate(papers) if i not in indices_set]

    deleted = len(papers) - len(papers_data["papers"])
    if deleted == 0:
        raise HTTPException(status_code=404, detail="No papers found at given indices")

    # Update metadata
    papers_data.setdefault("metadata", {})["total_papers"] = len(papers_data["papers"])
    _save_papers(papers_data)

    return {"success": True, "deleted_count": deleted}


# ── Bookmarks ────────────────────────────────────────────────────────

@router.get("/bookmarks")
async def list_all_bookmarks(
    username: Optional[str] = Query(None),
    admin: str = Depends(get_admin_user),
):
    """List all bookmarks. Optionally filter by username."""
    data = load_bookmarks()
    all_bm = data.get("bookmarks", [])
    if username:
        all_bm = [bm for bm in all_bm if bm.get("username") == username]
    return {
        "bookmarks": [
            {
                "id": bm["id"],
                "title": bm.get("title", "Untitled"),
                "username": bm.get("username", ""),
                "query": bm.get("query", ""),
                "topic": bm.get("topic", "General"),
                "num_papers": bm.get("num_papers", 0),
                "papers": [
                    {"title": p.get("title", ""), "authors": p.get("authors", [])}
                    for p in bm.get("papers", [])
                ],
                "created_at": bm.get("created_at", ""),
            }
            for bm in all_bm
        ]
    }


@router.delete("/bookmarks/{bookmark_id}")
async def admin_delete_bookmark(bookmark_id: str, admin: str = Depends(get_admin_user)):
    """Admin: delete any bookmark regardless of owner."""
    data = load_bookmarks()
    original = len(data["bookmarks"])
    data["bookmarks"] = [bm for bm in data["bookmarks"] if bm["id"] != bookmark_id]

    if len(data["bookmarks"]) == original:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    save_bookmarks(data)
    return {"success": True, "message": "Bookmark deleted"}
