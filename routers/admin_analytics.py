"""Admin visits-report endpoint (first-party analytics + crawler stats).

Serves the admin "방문 리포트" dashboard tab. All aggregation happens in
``src.analytics.visits_report`` / ``src.analytics.crawler_logs`` against the
host-local analytics.db and nginx access logs; this router only handles auth,
parameter validation, and shaping the two sources into one response.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from routers.deps.auth import get_admin_user
from src.analytics.crawler_logs import build_crawler_report
from src.analytics.visits_report import build_visits_report
from src.analytics.dashboard import build_dashboard
from src.analytics.mcp_usage import build_mcp_usage_report, mcp_analytics_db_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/analytics", tags=["admin"])

_ALLOWED_WINDOWS = (7, 28, 90)


def _analytics_db_path() -> Path:
    return Path(os.getenv("ANALYTICS_DB_PATH", "data/analytics.db"))


def _dashboard_report(db_path: Path, days: int) -> dict:
    report = build_dashboard(db_path, days=days)
    # Public titles make ranked pages readable without fetching article bodies in the browser.
    from routers.blog import _load_posts, _posts_lock
    try:
        with _posts_lock:
            titles = {f"/blog/{p['slug']}": p.get('title') for p in _load_posts()
                      if p.get('published') and p.get('slug')}
        for page in report['top_pages']:
            page['title'] = titles.get(page['path'])
    except (OSError, ValueError):
        logger.warning('dashboard page titles unavailable', exc_info=True)
    return report


@router.get('/overview')
async def admin_overview(
    days: int = Query(7), admin: str = Depends(get_admin_user),
) -> dict:
    if days not in _ALLOWED_WINDOWS:
        raise HTTPException(status_code=400, detail='days must be one of 7, 28, 90')
    db_path = _analytics_db_path()
    if not db_path.exists():
        raise HTTPException(status_code=503, detail='방문 분석 데이터가 아직 준비되지 않았습니다.')
    return await asyncio.to_thread(_dashboard_report, db_path, days)


@router.get("/visits")
async def admin_visits_report(
    days: int = Query(28, description="Window size in KST days: 7, 28, or 90"),
    admin: str = Depends(get_admin_user),
) -> dict:
    """Return the visits dashboard payload for the requested window."""
    if days not in _ALLOWED_WINDOWS:
        raise HTTPException(status_code=400, detail="days must be one of 7, 28, 90")

    db_path = _analytics_db_path()
    if not db_path.exists():
        raise HTTPException(status_code=503, detail="analytics.db not available")

    report = build_visits_report(db_path, days=days)
    try:
        report["ai"] = build_crawler_report(days=days)
    except Exception:  # pragma: no cover — crawler stats must never break the page
        logger.exception("crawler report failed")
        report["ai"] = {"available": False, "reason": "internal error"}
    return report


@router.get("/mcp")
async def admin_mcp_usage_report(
    days: int = Query(28, description="Window size in KST days: 7, 28, or 90"),
    include_internal: bool = Query(False, description="Include admin/internal actors"),
    admin: str = Depends(get_admin_user),
) -> dict:
    """Return independent MCP request, tool, and job operational usage."""
    if days not in _ALLOWED_WINDOWS:
        raise HTTPException(status_code=400, detail="days must be one of 7, 28, 90")
    return await asyncio.to_thread(
        build_mcp_usage_report,
        mcp_analytics_db_path(),
        days=days,
        include_internal=include_internal,
    )
