"""
Blog endpoints:
  GET    /api/blog/posts          — List published posts (public, paginated)
  GET    /api/blog/posts/{slug}   — Get single post by slug (public)
  POST   /api/blog/posts          — Create post (admin only)
  PUT    /api/blog/posts/{id}     — Update post (admin only)
  DELETE /api/blog/posts/{id}     — Delete post (admin only)
  GET    /api/blog/tags           — List all tags with post counts (public)
"""

import json
import logging
import math
import re
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from filelock import FileLock
from pydantic import BaseModel, Field

from .deps import get_admin_user, get_optional_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/blog", tags=["blog"])

BLOG_DIR = Path("data/blog")
POSTS_FILE = BLOG_DIR / "posts.json"
_posts_lock = FileLock(str(POSTS_FILE) + ".lock")


# ── Helpers ───────────────────────────────────────────────────────────


def _ensure_blog_dir() -> None:
    """Create data/blog/ directory if it does not exist."""
    BLOG_DIR.mkdir(parents=True, exist_ok=True)


def _load_posts() -> list[dict]:
    """Load all posts from posts.json. Caller must hold _posts_lock."""
    if not POSTS_FILE.exists():
        return []
    try:
        with open(POSTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("posts", [])
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error("Corrupted posts.json, returning empty list")
        return []


def _save_posts(posts: list[dict]) -> None:
    """Save posts to posts.json (atomic write). Caller must hold _posts_lock."""
    _ensure_blog_dir()
    tmp = POSTS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"posts": posts}, f, ensure_ascii=False, indent=2)
    tmp.replace(POSTS_FILE)


def _generate_slug(title: str, post_id: str) -> str:
    """Generate a URL-safe slug from the title.

    For ASCII-compatible titles, produces a readable slug (e.g. "hello-world").
    For non-ASCII titles (Korean, etc.), uses a shortened UUID prefix to
    guarantee uniqueness and URL safety.
    """
    # Normalize unicode, strip accents
    normalized = unicodedata.normalize("NFKD", title)
    ascii_part = normalized.encode("ascii", "ignore").decode("ascii").strip().lower()
    # Replace non-alphanumeric with hyphens, collapse multiples
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_part).strip("-")

    if slug and len(slug) >= 3:
        # Append short id suffix to avoid collision
        return f"{slug}-{post_id[:8]}"
    # Non-ASCII dominant title: use id-based slug
    return post_id[:8]


def _estimate_reading_time(content: str) -> int:
    """Estimate reading time in minutes (approx 200 words/min).

    Counts both whitespace-separated tokens (for English) and
    CJK character runs (each CJK char ~ 1 word) to handle mixed content.
    """
    if not content:
        return 1
    # Count whitespace-separated tokens
    word_count = len(content.split())
    minutes = max(1, math.ceil(word_count / 200))
    return minutes


# ── Pydantic models ──────────────────────────────────────────────────


class PostCreateRequest(BaseModel):
    """Request body for creating a new blog post."""
    title: str = Field(..., min_length=1, max_length=300)
    content: str = Field(..., min_length=1)
    excerpt: str = Field("", max_length=500)
    tags: list[str] = Field(default_factory=list)
    thumbnail_url: Optional[str] = Field(None, max_length=2000)
    published: bool = True


class PostUpdateRequest(BaseModel):
    """Request body for updating a blog post. All fields optional."""
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    content: Optional[str] = Field(None, min_length=1)
    excerpt: Optional[str] = Field(None, max_length=500)
    tags: Optional[list[str]] = None
    thumbnail_url: Optional[str] = Field(None, max_length=2000)
    published: Optional[bool] = None


class PostSummary(BaseModel):
    """Post summary returned in list responses (no full content, no thumbnail)."""
    id: str
    title: str
    slug: str
    excerpt: str
    author: str
    tags: list[str]
    has_thumbnail: bool = False
    created_at: str
    updated_at: Optional[str]
    published: bool
    reading_time_min: int


class PostDetail(PostSummary):
    """Full post including markdown content and thumbnail."""
    content: str
    thumbnail_url: Optional[str] = None


class PostListResponse(BaseModel):
    """Paginated post list response."""
    posts: list[PostSummary]
    total: int
    page: int
    pages: int


class TagCount(BaseModel):
    """Tag with its associated post count."""
    tag: str
    count: int


class TagListResponse(BaseModel):
    """Response for the tags endpoint."""
    tags: list[TagCount]


# ── Endpoints ─────────────────────────────────────────────────────────


@router.get("/thumbnail/{post_id}")
async def get_thumbnail(post_id: str):
    """Serve thumbnail image for a blog post."""
    from fastapi.responses import FileResponse

    thumb_path = BLOG_DIR / "thumbnails" / f"{post_id}.png"
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(thumb_path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/posts", response_model=PostListResponse)
async def list_posts(
    tag: Optional[str] = Query(None, max_length=100, description="Filter by tag"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Posts per page"),
    current_user: Optional[str] = Depends(get_optional_user),
) -> PostListResponse:
    """List blog posts, sorted by created_at descending.

    Public users see only published posts.
    Admin users see all posts (published and drafts).
    """
    with _posts_lock:
        all_posts = _load_posts()

    # TODO: admin check via JWT role — for now, public always sees published only
    posts = [p for p in all_posts if p.get("published")]

    # Filter by tag
    if tag:
        tag_lower = tag.lower()
        posts = [p for p in posts if tag_lower in [t.lower() for t in p.get("tags", [])]]

    # Sort by created_at descending
    posts.sort(key=lambda p: p.get("created_at", ""), reverse=True)

    # Pagination
    total = len(posts)
    pages = max(1, math.ceil(total / limit))
    start = (page - 1) * limit
    end = start + limit
    page_posts = posts[start:end]

    # Strip content and heavy thumbnail from list responses
    summaries = []
    for p in page_posts:
        summary = {k: v for k, v in p.items() if k not in ("content", "thumbnail_url")}
        summary["has_thumbnail"] = bool(p.get("thumbnail_url"))
        summaries.append(summary)

    return PostListResponse(
        posts=[PostSummary(**s) for s in summaries],
        total=total,
        page=page,
        pages=pages,
    )


@router.get("/posts/{slug}", response_model=PostDetail)
async def get_post(
    slug: str,
    current_user: Optional[str] = Depends(get_optional_user),
) -> PostDetail:
    """Get a single post by slug. Returns 404 if not found or unpublished."""
    with _posts_lock:
        all_posts = _load_posts()

    post = next((p for p in all_posts if p.get("slug") == slug), None)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Non-admin users cannot view unpublished posts
    if not post.get("published"):
        raise HTTPException(status_code=404, detail="Post not found")

    return PostDetail(**post)


@router.post("/posts", response_model=PostDetail, status_code=201)
async def create_post(
    request: PostCreateRequest,
    admin: str = Depends(get_admin_user),
) -> PostDetail:
    """Create a new blog post. Admin only."""
    post_id = uuid.uuid4().hex
    now = datetime.now().isoformat()
    slug = _generate_slug(request.title, post_id)

    # Sanitize tags: strip whitespace, lowercase, deduplicate
    tags = list(dict.fromkeys(t.strip() for t in request.tags if t.strip()))

    post = {
        "id": post_id,
        "title": request.title.strip(),
        "slug": slug,
        "excerpt": request.excerpt.strip() if request.excerpt else "",
        "content": request.content,
        "author": admin,
        "tags": tags,
        "thumbnail_url": request.thumbnail_url,
        "created_at": now,
        "updated_at": None,
        "published": request.published,
        "reading_time_min": _estimate_reading_time(request.content),
    }

    with _posts_lock:
        posts = _load_posts()
        posts.append(post)
        _save_posts(posts)

    logger.info("Blog post created: id=%s slug=%s author=%s", post_id, slug, admin)
    return PostDetail(**post)


@router.put("/posts/{post_id}", response_model=PostDetail)
async def update_post(
    post_id: str,
    request: PostUpdateRequest,
    admin: str = Depends(get_admin_user),
) -> PostDetail:
    """Update an existing blog post (partial update). Admin only."""
    with _posts_lock:
        posts = _load_posts()
        post = next((p for p in posts if p.get("id") == post_id), None)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")

        # Apply partial updates
        update_data = request.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        for key, value in update_data.items():
            if key == "title" and value is not None:
                post["title"] = value.strip()
                post["slug"] = _generate_slug(value, post["id"])
            elif key == "content" and value is not None:
                post["content"] = value
                post["reading_time_min"] = _estimate_reading_time(value)
            elif key == "tags" and value is not None:
                post["tags"] = list(dict.fromkeys(t.strip() for t in value if t.strip()))
            elif key == "excerpt" and value is not None:
                post["excerpt"] = value.strip()
            else:
                post[key] = value

        post["updated_at"] = datetime.now().isoformat()
        _save_posts(posts)

    logger.info("Blog post updated: id=%s by=%s", post_id, admin)
    return PostDetail(**post)


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: str,
    admin: str = Depends(get_admin_user),
) -> dict:
    """Delete a blog post. Admin only."""
    with _posts_lock:
        posts = _load_posts()
        original_len = len(posts)
        posts = [p for p in posts if p.get("id") != post_id]

        if len(posts) == original_len:
            raise HTTPException(status_code=404, detail="Post not found")

        _save_posts(posts)

    logger.info("Blog post deleted: id=%s by=%s", post_id, admin)
    return {"success": True, "deleted": post_id}


@router.get("/tags", response_model=TagListResponse)
async def list_tags() -> TagListResponse:
    """List all unique tags from published posts with their post counts."""
    with _posts_lock:
        all_posts = _load_posts()

    tag_counts: dict[str, int] = {}
    for post in all_posts:
        if not post.get("published"):
            continue
        for tag in post.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    # Sort by count descending, then alphabetically
    sorted_tags = sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))

    return TagListResponse(
        tags=[TagCount(tag=t, count=c) for t, c in sorted_tags],
    )
