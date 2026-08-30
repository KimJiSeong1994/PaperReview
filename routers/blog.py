"""
Blog endpoints:
  GET    /api/blog/posts          — List published posts (public, paginated, ?q= search)
  GET    /api/blog/posts/{slug}   — Get single post by slug (public)
  POST   /api/blog/posts          — Create post (admin only)
  PUT    /api/blog/posts/{id}     — Update post (admin only)
  DELETE /api/blog/posts/{id}     — Delete post (admin only)
  GET    /api/blog/tags           — List tags with post counts (public, paginated, ?sort=name|count)
"""

import json
import logging
import math
import re
import unicodedata
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

# Post categories. "engineering" is the default so legacy posts and
# admin-authored product/dev writeups fall here; paper reviews are opt-in.
BlogCategory = Literal["paper-review", "engineering"]
DEFAULT_CATEGORY: str = "engineering"
VALID_CATEGORIES: frozenset[str] = frozenset({"paper-review", "engineering"})

from fastapi import APIRouter, Depends, HTTPException, Query
from filelock import FileLock
from pydantic import BaseModel, Field, model_validator

from .deps import get_admin_user, get_optional_user
from .indexnow import post_url as _indexnow_post_url, submit_async as _indexnow_submit_async

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/blog", tags=["blog"])

# Hangul, Kana, and CJK ideographs — scripts written without spaces.
_CJK_RE = re.compile(r"[가-힣぀-ヿ一-鿿]")

BLOG_DIR = Path("data/blog")
POSTS_FILE = BLOG_DIR / "posts.json"
DELETED_FILE = BLOG_DIR / "deleted.json"
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


def _sort_posts_by_publication(posts: list[dict]) -> list[dict]:
    """Return newest publications first with deterministic same-time ordering.

    ``posts.json`` is append-oriented, so a later list position represents a
    later publication when two posts share the same ``created_at`` value. This
    tie-break keeps category/index views aligned with actual publishing order
    without affecting the explicit chapter order defined by blog series.
    """

    def _key(indexed_post: tuple[int, dict]) -> tuple[float, int]:
        index, post = indexed_post
        raw = str(post.get("created_at") or "")
        try:
            published_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            timestamp = published_at.timestamp()
        except (TypeError, ValueError, OverflowError):
            timestamp = float("-inf")
        return timestamp, index

    return [post for _, post in sorted(enumerate(posts), key=_key, reverse=True)]


def _save_posts(posts: list[dict]) -> None:
    """Save posts to posts.json (atomic write). Caller must hold _posts_lock."""
    _ensure_blog_dir()
    tmp = POSTS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"posts": posts}, f, ensure_ascii=False, indent=2)
    tmp.replace(POSTS_FILE)


def _load_deleted() -> set[str]:
    """Load the set of deleted (tombstoned) slugs. Caller must hold _posts_lock.

    Returns an empty set when the tombstone file is missing or corrupt.
    """
    if not DELETED_FILE.exists():
        return set()
    try:
        with open(DELETED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("slugs", []))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error("Corrupted deleted.json, returning empty set")
        return set()


def _record_deleted(slug: str) -> None:
    """Add a slug to the deleted tombstone (atomic write).

    Caller must hold _posts_lock. Deduplicates and persists the slug set.
    """
    _ensure_blog_dir()
    slugs = _load_deleted()
    slugs.add(slug)
    tmp = DELETED_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"slugs": sorted(slugs)}, f, ensure_ascii=False, indent=2)
    tmp.replace(DELETED_FILE)


def _generate_slug(title: str, post_id: str) -> str:
    """Generate a readable URL-safe slug without a UUID suffix.

    ASCII-compatible titles become stable human-readable slugs, e.g.
    ``"SkillOpt Search Policy Training 2026"`` ->
    ``"skillopt-search-policy-training"``. A trailing 4-digit year is
    removed so evergreen paper-review URLs stay clean. Non-ASCII dominant
    titles still fall back to a short id because this backend does not
    transliterate Korean.
    Uniqueness is handled separately by :func:`_unique_slug`, which appends
    ``-2``, ``-3`` only when a collision actually exists.
    """
    # Normalize unicode, strip accents
    normalized = unicodedata.normalize("NFKD", title)
    ascii_part = normalized.encode("ascii", "ignore").decode("ascii").strip().lower()
    # Replace non-alphanumeric with hyphens, collapse multiples
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_part).strip("-")
    slug = re.sub(r"-+", "-", slug)
    # Drop trailing year suffixes such as ``-2026`` from generated canonical URLs.
    slug = re.sub(r"-(?:19|20)\d{2}$", "", slug)
    slug = slug[:80].strip("-")

    if slug and len(slug) >= 3:
        return slug
    # Non-ASCII dominant title: use id-based fallback
    return post_id[:8]


def _unique_slug(base_slug: str, posts: list[dict], *, current_post_id: str | None = None) -> str:
    """Return ``base_slug`` unless another post already owns it.

    Keeps SEO-friendly URLs clean by avoiding random suffixes. If a title is
    reused, suffixes are deterministic and readable: ``slug``, ``slug-2``,
    ``slug-3``. ``current_post_id`` lets updates keep their existing slug.
    """
    taken = {
        p.get("slug")
        for p in posts
        if p.get("slug") and (current_post_id is None or p.get("id") != current_post_id)
    }
    if base_slug not in taken:
        return base_slug

    i = 2
    while f"{base_slug}-{i}" in taken:
        i += 1
    return f"{base_slug}-{i}"


def _estimate_reading_time(content: str) -> int:
    """Estimate reading time in minutes (approx 200 words/min).

    Counts whitespace-separated tokens (for English) plus CJK characters at
    2.5 chars per word-equivalent (~500 CJK chars/min), so mixed Korean and
    English content is estimated on one scale. CJK characters are removed
    before the whitespace pass so a mixed run is not counted twice.
    """
    if not content:
        return 1
    # CJK runs carry no spaces, so content.split() alone undercounts Korean
    # posts several-fold. Count CJK characters separately and drop them from
    # the whitespace pass so mixed Korean/English text is not counted twice.
    cjk_count = len(_CJK_RE.findall(content))
    word_count = len(_CJK_RE.sub(" ", content).split())
    minutes = max(1, math.ceil((word_count + cjk_count / 2.5) / 200))
    return minutes


# Search is a linear scan over every post: ``str.find`` first, then a
# left-boundary regex only where the substring already hit (ASCII tokens only).
# The prefilter matters — a bare lookbehind regex defeats CPython's literal
# fast path and costs 3-5x more on the body scan. Over 66 posts / 1.3M chars
# matching costs ~4ms for a rare token and ~16ms for one in nearly every post;
# end-to-end is 13-33ms including the 2.1MB posts.json load.
# ponytail: linear scan, add an index if the corpus outgrows ~10MB.
_MAX_SEARCH_TOKENS = 8
_SNIPPET_WIDTH = 160


def _snippet_around(content: str, match_pos: int) -> str:
    """Return ~160 chars of body text centred on the first match.

    Whitespace and newlines are collapsed so markdown blocks read as one line;
    no markdown parsing beyond that, since the frontend renders it as plain text.
    """
    start = max(0, match_pos - _SNIPPET_WIDTH // 2)
    end = min(len(content), start + _SNIPPET_WIDTH)
    body = " ".join(content[start:end].split())
    return f"{'…' if start > 0 else ''}{body}{'…' if end < len(content) else ''}"


def _compile_tokens(tokens: list[str]) -> list[tuple[str, Optional[re.Pattern]]]:
    """Pair each token with its matcher, once per request rather than per post.

    ASCII tokens need a left word boundary, or "gat" matches "aggregation" and
    "ai" matches "training" — on an AI-research blog those are the first
    queries typed. It is a left boundary and not ``\b`` on both sides so
    prefix search still works: "embed" must find "embedding".
    Korean tokens stay plain substrings: Hangul are word characters, so a
    boundary assertion would stop "검색" matching "검색을" or "논문검색", and
    that agglutinative matching is the whole reason body search works here.
    """
    return [
        (token, re.compile(r"(?<![A-Za-z0-9])" + re.escape(token)) if token.isascii() else None)
        for token in tokens
    ]


def _find(token: str, pattern: Optional[re.Pattern], haystack: str) -> int:
    """Index of the first boundary-respecting hit, or ``-1``.

    ``str.find`` runs first as a prefilter: the plain substring is a strict
    superset of the boundary match, so a miss here is a miss for the regex too,
    and it is several times cheaper. Korean tokens carry no pattern — for them
    the substring test is already the answer.
    """
    pos = haystack.find(token)
    if pos < 0 or pattern is None:
        return pos
    # The substring hit may be mid-word, so take the position from the regex.
    hit = pattern.search(haystack)
    return hit.start() if hit is not None else -1


def _match_post(
    post: dict, patterns: list[tuple[str, Optional[re.Pattern]]]
) -> Optional[tuple[int, Optional[str]]]:
    """Return ``(score, snippet)`` when every token matches, else ``None``.

    Tokens are ANDed, each matching anywhere in title/tags/excerpt/content.
    A token scores by the strongest field it hits (title 3 / tag 2 / excerpt 1
    / body 0) so a title match outranks a body-only match. The snippet is built
    only for body matches — otherwise the stored excerpt already shows why the
    post matched.
    """
    title = (post.get("title") or "").lower()
    tags = " ".join(post.get("tags") or []).lower()
    excerpt = (post.get("excerpt") or "").lower()
    content = (post.get("content") or "").lower()

    score = 0
    body_pos = -1
    for token, pattern in patterns:
        if _find(token, pattern, title) >= 0:
            score += 3
        elif _find(token, pattern, tags) >= 0:
            score += 2
        elif _find(token, pattern, excerpt) >= 0:
            score += 1
        elif (pos := _find(token, pattern, content)) >= 0:
            if body_pos < 0:
                body_pos = pos
        else:
            return None

    snippet = _snippet_around(post.get("content") or "", body_pos) if body_pos >= 0 else None
    return score, snippet


# ── Pydantic models ──────────────────────────────────────────────────


class PostCreateRequest(BaseModel):
    """Request body for creating a new blog post."""
    title: str = Field(..., min_length=1, max_length=300)
    content: str = Field(..., min_length=1)
    excerpt: str = Field("", max_length=500)
    tags: list[str] = Field(default_factory=list)
    thumbnail_url: Optional[str] = Field(None, max_length=2000)
    slug: Optional[str] = Field(
        None,
        min_length=3,
        max_length=120,
        description="Optional URL slug. If omitted, generated from title without a random suffix.",
    )
    published: bool = True
    category: BlogCategory = Field(
        DEFAULT_CATEGORY,
        description="Content type: 'paper-review' (deep review of a paper) "
        "or 'engineering' (product / dev writeup).",
    )


class PostUpdateRequest(BaseModel):
    """Request body for updating a blog post. All fields optional."""
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    content: Optional[str] = Field(None, min_length=1)
    excerpt: Optional[str] = Field(None, max_length=500)
    tags: Optional[list[str]] = None
    thumbnail_url: Optional[str] = Field(None, max_length=2000)
    slug: Optional[str] = Field(None, min_length=3, max_length=120)
    published: Optional[bool] = None
    category: Optional[BlogCategory] = None


class PostSummary(BaseModel):
    """Post summary returned in list responses (no full content, no thumbnail)."""
    id: str
    title: str
    slug: str
    excerpt: str
    author: str
    tags: list[str]
    category: str = DEFAULT_CATEGORY
    has_thumbnail: bool = False
    created_at: str
    updated_at: Optional[str]
    published: bool
    reading_time_min: int
    # Body excerpt around a search hit; None unless ?q= matched the body.
    snippet: Optional[str] = None


class PostDetail(PostSummary):
    """Full post including markdown content and thumbnail."""
    content: str
    thumbnail_url: Optional[str] = None

    @model_validator(mode="after")
    def _derive_has_thumbnail(self) -> "PostDetail":
        """Keep ``has_thumbnail`` in step with ``thumbnail_url``.

        Detail responses are built straight from the stored post dict, which
        has no ``has_thumbnail`` key, so the field fell back to its ``False``
        default and contradicted the list endpoint (which computes it). Derive
        it here so every construction site agrees.
        """
        self.has_thumbnail = bool(self.thumbnail_url)
        return self


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
    """Paginated tag list response."""
    tags: list[TagCount]
    total: int
    page: int
    pages: int


# ── Endpoints ─────────────────────────────────────────────────────────


@router.get("/thumbnail/{post_id}")
async def get_thumbnail(post_id: str):
    """Serve thumbnail image for a blog post."""
    from fastapi.responses import FileResponse

    # Path traversal 방지: post_id에서 경로 구분자 차단
    if "/" in post_id or "\\" in post_id or ".." in post_id:
        raise HTTPException(status_code=400, detail="Invalid post_id")
    thumb_path = (BLOG_DIR / "thumbnails" / f"{post_id}.png").resolve()
    allowed_dir = (BLOG_DIR / "thumbnails").resolve()
    if not str(thumb_path).startswith(str(allowed_dir)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(thumb_path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/figures/{filename}")
async def get_figure(filename: str):
    """Serve blog figure images."""
    from fastapi.responses import FileResponse

    # Path traversal 방지: filename에서 경로 구분자 차단
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    fig_path = (BLOG_DIR / "figures" / filename).resolve()
    allowed_dir = (BLOG_DIR / "figures").resolve()
    if not str(fig_path).startswith(str(allowed_dir)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not fig_path.exists():
        raise HTTPException(status_code=404, detail="Figure not found")
    import mimetypes
    media_type = mimetypes.guess_type(str(fig_path))[0] or "application/octet-stream"
    # .png 확장자지만 실제 JPEG인 경우 처리
    try:
        with open(fig_path, "rb") as f:
            header = f.read(3)
        if header[:2] == b'\xff\xd8':
            media_type = "image/jpeg"
        elif header[:3] == b'\x89PN':
            media_type = "image/png"
    except Exception:
        pass
    return FileResponse(fig_path, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/posts", response_model=PostListResponse)
async def list_posts(
    tag: Optional[str] = Query(None, max_length=100, description="Filter by tag"),
    category: Optional[str] = Query(
        None, max_length=32, description="Filter by category: 'paper-review' or 'engineering'"
    ),
    q: Optional[str] = Query(
        None, max_length=100, description="Full-text search over title, tags, excerpt and body"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Posts per page"),
    current_user: Optional[str] = Depends(get_optional_user),
) -> PostListResponse:
    """List blog posts, sorted by created_at descending.

    Public users see only published posts.
    Admin users see all posts (published and drafts).
    With ``q``, results are restricted to posts matching every token and sorted
    by match relevance first, falling back to the same recency order for ties.
    """
    with _posts_lock:
        all_posts = _load_posts()

    # TODO: admin check via JWT role — for now, public always sees published only
    posts = [p for p in all_posts if p.get("published")]

    # Filter by tag
    if tag:
        tag_lower = tag.lower()
        posts = [p for p in posts if tag_lower in [t.lower() for t in p.get("tags", [])]]

    # Filter by category (posts missing the field fall back to the default)
    if category:
        posts = [p for p in posts if p.get("category", DEFAULT_CATEGORY) == category]

    # Full-text search: filter after the cheap metadata filters, before sorting.
    tokens = (q or "").lower().split()[:_MAX_SEARCH_TOKENS]
    scores: dict[str, int] = {}
    snippets: dict[str, str] = {}
    if tokens:
        patterns = _compile_tokens(tokens)
        matched = []
        for p in posts:
            hit = _match_post(p, patterns)
            if hit is None:
                continue
            score, snippet = hit
            matched.append(p)
            scores[p.get("id")] = score
            if snippet:
                snippets[p.get("id")] = snippet
        posts = matched

    posts = _sort_posts_by_publication(posts)
    if tokens:
        # Stable sort keeps the recency order above as the tie-break for
        # equally-scored posts, so date parsing is not reimplemented here.
        posts.sort(key=lambda p: scores.get(p.get("id"), 0), reverse=True)

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
        summary["snippet"] = snippets.get(p.get("id"))
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
    now = datetime.now(timezone.utc).isoformat()
    base_slug = _generate_slug(request.slug or request.title, post_id)

    # Sanitize tags: strip whitespace, lowercase, deduplicate
    tags = list(dict.fromkeys(t.strip() for t in request.tags if t.strip()))

    post = {
        "id": post_id,
        "title": request.title.strip(),
        "slug": base_slug,
        "excerpt": request.excerpt.strip() if request.excerpt else "",
        "content": request.content,
        "author": admin,
        "tags": tags,
        "category": request.category,
        "thumbnail_url": request.thumbnail_url,
        "created_at": now,
        "updated_at": None,
        "published": request.published,
        "reading_time_min": _estimate_reading_time(request.content),
    }

    with _posts_lock:
        posts = _load_posts()
        post["slug"] = _unique_slug(base_slug, posts)
        posts.append(post)
        _save_posts(posts)

    logger.info("Blog post created: id=%s slug=%s author=%s", post_id, post["slug"], admin)
    if post["published"]:
        _indexnow_submit_async([_indexnow_post_url(post["slug"])])
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
                if "slug" not in update_data:
                    base_slug = _generate_slug(value, post["id"])
                    post["slug"] = _unique_slug(base_slug, posts, current_post_id=post["id"])
            elif key == "slug" and value is not None:
                base_slug = _generate_slug(value, post["id"])
                post["slug"] = _unique_slug(base_slug, posts, current_post_id=post["id"])
            elif key == "content" and value is not None:
                post["content"] = value
                post["reading_time_min"] = _estimate_reading_time(value)
            elif key == "tags" and value is not None:
                post["tags"] = list(dict.fromkeys(t.strip() for t in value if t.strip()))
            elif key == "excerpt" and value is not None:
                post["excerpt"] = value.strip()
            else:
                post[key] = value

        post["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_posts(posts)

    logger.info("Blog post updated: id=%s by=%s", post_id, admin)
    if post.get("published"):
        _indexnow_submit_async([_indexnow_post_url(post["slug"])])
    return PostDetail(**post)


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: str,
    admin: str = Depends(get_admin_user),
) -> dict:
    """Delete a blog post. Admin only.

    Records the deleted slug in the tombstone so the SSR layer can serve a
    410 Gone for its URL afterwards.
    """
    with _posts_lock:
        posts = _load_posts()
        target = next((p for p in posts if p.get("id") == post_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="Post not found")

        target_slug = target.get("slug")
        posts = [p for p in posts if p.get("id") != post_id]
        _save_posts(posts)

        if target_slug:
            _record_deleted(target_slug)

    logger.info("Blog post deleted: id=%s by=%s", post_id, admin)
    return {"success": True, "deleted": post_id}


def _merged_tag_counts(posts: list[dict]) -> list[tuple[str, int]]:
    """Return ``(tag, count)`` for published posts, merged across casing.

    Tags differing only by case collapse into one entry (counts summed,
    displayed with the casing used most often). Takes ``posts`` rather than
    loading them so the SEO tag hub — which patches its own ``_load_posts``
    in tests — can share it without a second loader.
    """
    # Group by lowercase tag, tracking how often each original casing appears.
    variants: dict[str, Counter[str]] = {}
    for post in posts:
        if not post.get("published"):
            continue
        for tag in post.get("tags", []):
            variants.setdefault(tag.lower(), Counter())[tag] += 1
    return [
        # Most-used casing wins; ties broken by the lexicographically first.
        (min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0], sum(counts.values()))
        for counts in variants.values()
    ]


@router.get("/tags", response_model=TagListResponse)
async def list_tags(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(60, ge=1, le=300, description="Tags per page"),
    sort: Literal["name", "count"] = Query(
        "name", description="'name' = alphabetical, 'count' = most-used first"
    ),
) -> TagListResponse:
    """List unique tags from published posts with their post counts.

    Tags differing only by case are merged into one entry (counts summed,
    displayed with the casing used most often) so the tag index never shows
    two chips for the same tag. ``?tag=`` on /posts is case-insensitive, so
    the merged casing still links correctly.
    """
    with _posts_lock:
        all_posts = _load_posts()

    merged = _merged_tag_counts(all_posts)

    if sort == "count":
        merged.sort(key=lambda tc: (-tc[1], tc[0].casefold()))
    else:
        merged.sort(key=lambda tc: tc[0].casefold())

    total = len(merged)
    start = (page - 1) * limit
    return TagListResponse(
        tags=[TagCount(tag=t, count=c) for t, c in merged[start : start + limit]],
        total=total,
        page=page,
        pages=max(1, math.ceil(total / limit)),
    )
