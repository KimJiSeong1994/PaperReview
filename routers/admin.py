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
from collections import Counter
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .deps import get_admin_user, load_bookmarks, save_bookmarks, review_sessions, review_sessions_lock

router = APIRouter(prefix="/api/admin", tags=["admin"])

USERS_FILE = Path(__file__).resolve().parent.parent / "data" / "users.json"
PAPERS_FILE = Path(__file__).resolve().parent.parent / "data" / "raw" / "papers.json"
GRAPH_META_FILE = Path(__file__).resolve().parent.parent / "data" / "graph" / "paper_graph_metadata.json"


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
    papers = papers_data.get("papers", [])
    bookmarks_data = load_bookmarks()

    with review_sessions_lock:
        session_count = len(review_sessions)

    # Knowledge graph metadata
    kg_nodes, kg_edges = 0, 0
    if GRAPH_META_FILE.exists():
        try:
            with open(GRAPH_META_FILE, "r", encoding="utf-8") as f:
                gm = json.load(f)
            kg_nodes = gm.get("nodes", 0)
            kg_edges = gm.get("edges", 0)
        except Exception:
            pass

    # Papers by source
    source_counter = Counter(p.get("source", "Unknown") for p in papers)
    papers_by_source = [{"source": s, "count": c} for s, c in source_counter.most_common()]

    # Papers by year
    year_counter: Counter = Counter()
    for p in papers:
        d = p.get("published_date", "")
        y = d[:4] if d and len(d) >= 4 else None
        if y and y.isdigit():
            year_counter[y] += 1
    papers_by_year = [{"year": y, "count": c} for y, c in sorted(year_counter.items())]

    # Top search queries
    query_counter = Counter(p.get("search_query", "") for p in papers if p.get("search_query"))
    top_queries = [{"query": q, "count": c} for q, c in query_counter.most_common(7)]

    # Top categories
    cat_counter: Counter = Counter()
    for p in papers:
        for cat in p.get("categories", []):
            cat_counter[cat] += 1
    top_categories = [{"category": cat, "count": c} for cat, c in cat_counter.most_common(7)]

    # Recent papers (by collected_at)
    sorted_papers = sorted(papers, key=lambda p: p.get("collected_at", ""), reverse=True)
    recent_papers = [
        {
            "title": p.get("title", "Untitled"),
            "source": p.get("source", ""),
            "collected_at": p.get("collected_at", ""),
        }
        for p in sorted_papers[:5]
    ]

    return {
        "total_users": len(users),
        "total_papers": len(papers),
        "total_bookmarks": len(bookmarks_data.get("bookmarks", [])),
        "total_sessions": session_count,
        "kg_nodes": kg_nodes,
        "kg_edges": kg_edges,
        "papers_by_source": papers_by_source,
        "papers_by_year": papers_by_year,
        "top_queries": top_queries,
        "top_categories": top_categories,
        "recent_papers": recent_papers,
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

@router.get("/papers/stats")
async def papers_stats(admin: str = Depends(get_admin_user)):
    """Get paper counts grouped by user for tree view."""
    papers_data = _load_papers()
    papers = papers_data.get("papers", [])
    counts: dict[str, int] = {}
    for p in papers:
        user = p.get("searched_by", "")
        counts[user] = counts.get(user, 0) + 1

    return {
        "total": len(papers),
        "users": sorted(
            [{"username": u or "(unknown)", "paper_count": c} for u, c in counts.items()],
            key=lambda x: x["username"],
        ),
    }


@router.get("/papers")
async def list_papers(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    username: Optional[str] = Query(None),
    admin: str = Depends(get_admin_user),
):
    """List papers with pagination. Optionally filter by searched_by username."""
    papers_data = _load_papers()
    papers = papers_data.get("papers", [])

    # Filter by username if provided
    if username:
        papers = [p for p in papers if p.get("searched_by") == username]

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
            "searched_by": p.get("searched_by", ""),
        })

    # Collect unique usernames for filter dropdown
    all_papers = papers_data.get("papers", [])
    usernames = sorted(set(p.get("searched_by", "") for p in all_papers if p.get("searched_by")))

    return {
        "papers": page_papers,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max((total + page_size - 1) // page_size, 1),
        "usernames": usernames,
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
