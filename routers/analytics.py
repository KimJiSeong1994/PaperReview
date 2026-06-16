"""First-party analytics ingestion endpoints."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

from routers.deps import get_optional_user, limiter
from src.analytics.first_party import (
    ALLOWED_FIRST_PARTY_EVENTS,
    AppAnalyticsEvent,
    record_app_analytics_event,
    sanitize_page_path,
    sanitize_payload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _analytics_db_path() -> Path:
    return Path(os.getenv("ANALYTICS_DB_PATH", "data/analytics.db"))


class AnalyticsEventIn(BaseModel):
    client_id: str = Field(..., min_length=8, max_length=96)
    session_id: str = Field(..., min_length=8, max_length=96)
    event_name: str = Field(..., min_length=1, max_length=64)
    page_path: str = Field(default="/", max_length=512)
    payload: dict[str, Any] = Field(default_factory=dict)


class AnalyticsEventAccepted(BaseModel):
    accepted: bool = True


@router.post("/events", response_model=AnalyticsEventAccepted, status_code=202)
@limiter.limit("120/minute")
async def ingest_analytics_event(
    request: Request,
    event: AnalyticsEventIn,
    user_id: str | None = Depends(get_optional_user),
) -> AnalyticsEventAccepted:
    """Persist a sanitized first-party analytics event in analytics.db.

    The authenticated username is inferred from the JWT server-side when
    present. Clients cannot provide or spoof ``user_id`` in the payload.
    """
    if event.event_name not in ALLOWED_FIRST_PARTY_EVENTS:
        raise HTTPException(status_code=400, detail="Unsupported analytics event")

    try:
        record_app_analytics_event(
            _analytics_db_path(),
            AppAnalyticsEvent(
                user_id=user_id,
                client_id=event.client_id,
                session_id=event.session_id,
                event_name=event.event_name,
                page_path=sanitize_page_path(event.page_path),
                payload=sanitize_payload(event.payload),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("failed to persist first-party analytics event")
        raise HTTPException(status_code=503, detail="Analytics unavailable")

    return AnalyticsEventAccepted()
