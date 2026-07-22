"""Admin visits-report endpoint (first-party analytics + crawler stats).

Serves the admin "방문 리포트" dashboard tab. All aggregation happens in
``src.analytics.visits_report`` / ``src.analytics.crawler_logs`` against the
host-local analytics.db and nginx access logs; this router only handles auth,
parameter validation, and shaping the two sources into one response.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from routers.deps.auth import get_admin_user
from src.analytics.activity_report import build_activity_report
from src.analytics.crawler_logs import build_crawler_report
from src.analytics.review_store import REVIEWS_DB_PATH
from src.analytics.visits_report import build_visits_report

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/analytics", tags=["admin"])

_ALLOWED_WINDOWS = (7, 28, 90)


def _analytics_db_path() -> Path:
    return Path(os.getenv("ANALYTICS_DB_PATH", "data/analytics.db"))


def _data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data"))


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


@router.get("/activity")
async def admin_activity_report(
    days: int = Query(28, description="Window size in KST days: 7, 28, or 90"),
    admin: str = Depends(get_admin_user),
) -> dict:
    """Return authenticated product-usage metrics for the requested window.

    Covers signups, active users, search, bookmarks and deep-review pipeline
    health from the durable user-attributed stores (events.db / users.db /
    bookmarks.db / reviews.db).
    """
    if days not in _ALLOWED_WINDOWS:
        raise HTTPException(status_code=400, detail="days must be one of 7, 28, 90")

    data_dir = _data_dir()
    return build_activity_report(
        events_db=Path(os.getenv("EVENTS_DB_PATH", str(data_dir / "events.db"))),
        users_db=data_dir / "users.db",
        bookmarks_db=data_dir / "bookmarks.db",
        reviews_db=REVIEWS_DB_PATH,
        days=days,
    )
