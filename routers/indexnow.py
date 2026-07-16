"""IndexNow instant-indexing integration.

Notifies IndexNow-participating engines (Bing, Yandex, Seznam, Naver, …) the
moment a blog post is published or updated, so new/changed URLs are crawled
without waiting for a scheduled crawl.

Note: Google does NOT support IndexNow — Google discovery still relies on the
sitemap + Search Console. This complements, not replaces, that path.

Ownership is proven by serving the verification key at
``/api/indexnow/{key}.txt`` (nginx proxies ``/api`` to the backend, so no nginx
change is needed) and passing it as ``keyLocation`` in every submission.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response

from .deps import get_admin_user

logger = logging.getLogger(__name__)

SITE_URL = os.getenv("SITE_URL", "https://jiphyeonjeon.kr").rstrip("/")
SITE_HOST = SITE_URL.split("://", 1)[-1].split("/", 1)[0]

# Public verification token — not a secret (it is served publicly). Override per
# deploy via INDEXNOW_KEY; the default is fixed so the served key file and the
# submitted key always match.
INDEXNOW_KEY = os.getenv("INDEXNOW_KEY", "8f3a1c07b94e2d65a0f8c3b12e6d47a9")
INDEXNOW_ENABLED = os.getenv("INDEXNOW_ENABLED", "true").lower() == "true"
KEY_LOCATION = f"{SITE_URL}/api/indexnow/{INDEXNOW_KEY}.txt"
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"

BLOG_DIR = Path("data/blog")
POSTS_FILE = BLOG_DIR / "posts.json"

router = APIRouter(prefix="/api/indexnow", tags=["indexnow"])

# Hold references to fire-and-forget tasks so they are not garbage-collected.
_bg_tasks: set[asyncio.Task] = set()


def post_url(slug: str) -> str:
    """Public URL of a blog post."""
    return f"{SITE_URL}/blog/{slug}"


def published_urls() -> list[str]:
    """Home, blog index, category/series hubs, and every published post URL
    (dedup, ordered) — so hub pages get (re)indexed instantly too, not only
    posts."""
    urls = [f"{SITE_URL}/", f"{SITE_URL}/blog"]
    try:
        with open(POSTS_FILE, encoding="utf-8") as f:
            posts = json.load(f).get("posts", [])
    except (OSError, json.JSONDecodeError):
        posts = []

    published = [p for p in posts if p.get("published") and p.get("slug")]

    # Lazy import to avoid a circular import at module load.
    try:
        from routers.seo import BLOG_CATEGORIES, BLOG_SERIES, _category_of

        cats_present = {_category_of(p) for p in published}
        for cat in BLOG_CATEGORIES:
            if cat in cats_present:
                urls.append(f"{SITE_URL}/blog/category/{cat}")
        published_slugs = {p["slug"] for p in published}
        for sid, series in BLOG_SERIES.items():
            if any(s in published_slugs for s in series["slugs"]):
                urls.append(f"{SITE_URL}/blog/series/{sid}")
    except Exception:  # noqa: BLE001 - hub URLs are a bonus; never break posting
        logger.warning("Could not add hub URLs to IndexNow batch", exc_info=True)

    for p in published:
        urls.append(post_url(p["slug"]))
    return list(dict.fromkeys(urls))


async def submit_indexnow(urls: list[str]) -> bool:
    """Submit URLs to IndexNow. Best-effort: logs and swallows all errors."""
    if not INDEXNOW_ENABLED:
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False  # never touch the network during test runs
    urls = [u for u in dict.fromkeys(urls) if u]
    if not urls:
        return False
    payload = {
        "host": SITE_HOST,
        "key": INDEXNOW_KEY,
        "keyLocation": KEY_LOCATION,
        "urlList": urls[:10000],
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                INDEXNOW_ENDPOINT,
                json=payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        ok = resp.status_code in (200, 202)
        logger.info("IndexNow: submitted %d url(s), HTTP %s", len(urls), resp.status_code)
        return ok
    except Exception:  # noqa: BLE001 - submission must never break a request
        logger.warning("IndexNow submission failed", exc_info=True)
        return False


def submit_async(urls: list[str]) -> None:
    """Fire-and-forget submission from within a running event loop."""
    if not INDEXNOW_ENABLED or not urls:
        return
    try:
        task = asyncio.create_task(submit_indexnow(list(urls)))
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)
    except RuntimeError:
        logger.debug("submit_async called without a running loop; skipping")


@router.get("/{key_file}", include_in_schema=False)
async def indexnow_key(key_file: str) -> Response:
    """Serve the IndexNow verification key file (domain-ownership proof)."""
    if key_file != f"{INDEXNOW_KEY}.txt":
        raise HTTPException(status_code=404, detail="Not found")
    return Response(
        content=INDEXNOW_KEY,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/submit", include_in_schema=False)
async def indexnow_resubmit(_admin: str = Depends(get_admin_user)) -> dict:
    """Admin: resubmit home + blog index + all published posts to IndexNow."""
    urls = published_urls()
    ok = await submit_indexnow(urls)
    return {"enabled": INDEXNOW_ENABLED, "submitted": len(urls), "ok": ok}
