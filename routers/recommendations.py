"""Incarnation-bound common recommendations and durable user controls."""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from src.events.emit import emit_or_warn
from src.events.event_types import EventType, UserEvent
from src.recommendation_state import (
    RecommendationState,
    RecommendationStateError,
    utc_now,
)
from src.recommendations_artifacts import (
    DeliveryValidationError,
    load_recommendation_artifact,
    parse_delivery_time,
    read_delivery,
)
from src.storage.user_db import AccountLifecycleError
from .deps.auth import AuthenticatedPrincipal, get_authenticated_principal
from .deps.storage import _get_user_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])

Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
]
CanonicalKey = Annotated[
    str, Field(min_length=1, max_length=512, pattern=r"^[^\x00-\x1f]+$")
]
Action = Literal["hide", "already_seen", "topic_less", "interested", "seen"]


class RecommendationNotification(BaseModel):
    canonical_key: str
    final_rank: int
    display_position: int
    seen: bool
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    publication_date: str | None = None
    venue: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    openalex_id: str | None = Field(None, max_length=256)
    semantic_scholar_id: str | None = Field(None, max_length=256)
    pmid: str | None = Field(None, max_length=256)
    score: float
    reason: str
    candidate_sources: list[str] = Field(default_factory=list)
    score_breakdown: dict[str, float] = Field(default_factory=dict)


class RecommendationNotificationResponse(BaseModel):
    items: list[RecommendationNotification]
    unread_count: int
    total_count: int
    latest_run_at: str | None
    run_id: str | None
    scoring_mode: str | None
    state: str
    freshness: str
    source_statuses: dict[str, str]
    degraded_reasons: list[str]


class ItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: Identifier
    canonical_key: CanonicalKey


class RecommendationFeedbackRequest(ItemRequest):
    request_id: Identifier
    action: Literal["hide", "already_seen", "topic_less", "interested", "undo"]
    undo_action: Action | None = None


class RecommendationReadStateRequest(ItemRequest):
    request_id: Identifier
    action: Literal["seen"] = "seen"


class RecommendationExposureRequest(ItemRequest):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    visible_fraction: float = Field(ge=0.5, le=1, strict=True)
    visible_ms: int = Field(ge=1000, le=60000, strict=True)


def _artifact_root() -> Path:
    return Path(
        os.getenv(
            "RECOMMENDATIONS_ARTIFACTS_DIR",
            str(Path(os.getenv("DATA_DIR", "data")) / "recommendations"),
        )
    )


def _state() -> RecommendationState:
    return RecommendationState(
        Path(
            os.getenv(
                "EVENTS_DB_PATH", str(Path(os.getenv("DATA_DIR", "data")) / "events.db")
            )
        ),
        authority=_get_user_db(),
    )


def _unavailable(code: str) -> HTTPException:
    return HTTPException(status_code=503, detail={"code": code})


@router.get("/notifications", response_model=RecommendationNotificationResponse)
async def list_recommendation_notifications(
    limit: Annotated[int, Query(ge=1, le=5)] = 5,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
) -> RecommendationNotificationResponse:
    """Read the exact current account, policy and ordered reserve together."""
    try:
        user_db = _get_user_db()
        with user_db.account_guard(principal.username, principal.account_incarnation):
            now = utc_now()
            policy = _state().policy(principal.account_incarnation, now=now)
            result = load_recommendation_artifact(
                _artifact_root(),
                principal.account_incarnation,
                limit,
                policy=policy,
                now=now,
            )
        return RecommendationNotificationResponse(**result)
    except AccountLifecycleError:
        raise HTTPException(
            status_code=401, detail="Account deleted or disabled"
        ) from None
    except (sqlite3.Error, RecommendationStateError):
        raise _unavailable("policy_unavailable") from None
    except (OSError, DeliveryValidationError):
        raise _unavailable("invalid_artifact") from None


def _require_member(
    principal: AuthenticatedPrincipal, body: ItemRequest, *, now
) -> dict:
    raw = read_delivery(
        _artifact_root(), principal.account_incarnation, now=now, run_id=body.run_id
    )
    if raw is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_delivery"})
    if now - parse_delivery_time(raw["run_at"]) >= timedelta(hours=72):
        raise HTTPException(status_code=409, detail={"code": "expired_delivery"})
    if not any(row["canonical_key"] == body.canonical_key for row in raw["items"]):
        raise HTTPException(status_code=404, detail={"code": "unknown_recommendation"})
    return raw


def _record_action(
    principal: AuthenticatedPrincipal,
    body: RecommendationFeedbackRequest | RecommendationReadStateRequest,
) -> dict:
    try:
        user_db = _get_user_db()
        with user_db.account_guard(principal.username, principal.account_incarnation):
            now, state = utc_now(), _state()
            undo_action = getattr(body, "undo_action", None)
            acknowledged = state.receipt(
                principal.account_incarnation,
                request_id=body.request_id,
                run_id=body.run_id,
                canonical_key=body.canonical_key,
                action=body.action,
                undo_action=undo_action,
            )
            if acknowledged is not None:
                return acknowledged
            if body.action == "undo":
                if undo_action is None:
                    raise HTTPException(
                        status_code=422, detail={"code": "invalid_undo_action"}
                    )
                if not state.has_action(
                    principal.account_incarnation,
                    run_id=body.run_id,
                    canonical_key=body.canonical_key,
                    action=undo_action,
                    now=now,
                ):
                    _require_member(principal, body, now=now)
            else:
                _require_member(principal, body, now=now)
            receipt = state.apply_action(
                principal.account_incarnation,
                run_id=body.run_id,
                canonical_key=body.canonical_key,
                action=body.action,
                request_id=body.request_id,
                undo_action=undo_action,
                now=now,
            )
        # Analytics is supplementary: failed or dropped emission cannot change
        # the transaction result or undo a user's durable privacy control.
        try:
            event_type = (
                EventType.RECOMMENDATION_READ
                if body.action == "seen"
                else EventType.RECOMMENDATION_FEEDBACK
            )
            emit_or_warn(
                UserEvent(
                    user_id=principal.username,
                    event_type=event_type,
                    paper_id=body.canonical_key,
                    payload={
                        "account_incarnation": principal.account_incarnation,
                        "run_id": body.run_id,
                        "paper_id": body.canonical_key,
                        "feedback_type": body.action,
                        "action": body.action,
                        "request_id": body.request_id,
                    },
                )
            )
        except Exception:
            logger.warning("recommendation_analytics_emit_failed")
        return receipt
    except AccountLifecycleError:
        raise HTTPException(
            status_code=401, detail="Account deleted or disabled"
        ) from None
    except RecommendationStateError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from None
    except sqlite3.Error:
        raise _unavailable("policy_unavailable") from None
    except (OSError, DeliveryValidationError):
        raise _unavailable("invalid_artifact") from None


@router.post("/feedback")
async def record_recommendation_feedback(
    body: RecommendationFeedbackRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
) -> dict:
    return _record_action(principal, body)


@router.post("/read-state")
async def record_recommendation_read_state(
    body: RecommendationReadStateRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
) -> dict:
    return _record_action(principal, body)


@router.post("/exposure")
async def record_recommendation_exposure(
    body: RecommendationExposureRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
) -> dict:
    try:
        user_db = _get_user_db()
        with user_db.account_guard(principal.username, principal.account_incarnation):
            now, state = utc_now(), _state()
            raw = _require_member(principal, body, now=now)
            visible = state.policy(principal.account_incarnation, now=now).project(
                raw["items"], limit=5
            )
            if not any(row["canonical_key"] == body.canonical_key for row in visible):
                raise HTTPException(
                    status_code=409, detail={"code": "not_visible_recommendation"}
                )
            recorded = state.record_exposure(
                principal.account_incarnation,
                run_id=body.run_id,
                canonical_key=body.canonical_key,
                visible_fraction=body.visible_fraction,
                visible_ms=body.visible_ms,
                now=now,
            )
        return {"tracked": True, "recorded": recorded}
    except AccountLifecycleError:
        raise HTTPException(
            status_code=401, detail="Account deleted or disabled"
        ) from None
    except RecommendationStateError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from None
    except sqlite3.Error:
        raise _unavailable("policy_unavailable") from None
    except (OSError, DeliveryValidationError):
        raise _unavailable("invalid_artifact") from None
