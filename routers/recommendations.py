"""Paper recommendation notification endpoints."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.events.emit import emit_or_warn
from src.events.event_types import EventType, UserEvent
from src.recommendations_artifacts import load_recommendation_artifact

from .deps.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


class RecommendationVariantEvidence(BaseModel):
    variant: str
    reason: str = ""
    score: float | None = None
    display_score: str | None = None
    confidence_label: str
    rank: int | None = None
    matched_terms: list[str] = Field(default_factory=list)
    reason_factors: list[str] = Field(default_factory=list)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    evidence_count: int | None = None
    explanation_confidence: str | None = None
    slot_type: str | None = None
    diversity_adjusted: bool = False
    similarity_penalty: float = 0.0


class RecommendationNotification(BaseModel):
    id: str
    paper_id: str | None = None
    title: str
    reason: str = ""
    variant: str
    run_at: str
    score: float | None = None
    display_score: str | None = None
    confidence_label: str = "추천"
    rank: int | None = None
    year: int | str | None = None
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    source: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    matched_terms: list[str] = Field(default_factory=list)
    reason_factors: list[str] = Field(default_factory=list)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    evidence_count: int | None = None
    explanation_confidence: str | None = None
    slot_type: str | None = None
    diversity_adjusted: bool = False
    similarity_penalty: float = 0.0


class RecommendationPaperNotification(BaseModel):
    id: str
    paper_id: str
    title: str
    top_reason: str = ""
    run_at: str
    score: float | None = None
    display_score: str | None = None
    confidence_label: str = "추천"
    rank: int | None = None
    year: int | str | None = None
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    source: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    matched_terms: list[str] = Field(default_factory=list)
    reason_factors: list[str] = Field(default_factory=list)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    evidence_count: int | None = None
    explanation_confidence: str | None = None
    slot_type: str | None = None
    diversity_adjusted: bool = False
    similarity_penalty: float = 0.0
    variants: list[RecommendationVariantEvidence] = Field(default_factory=list)




class RecommendationFeedbackRequest(BaseModel):
    recommendation_id: str
    paper_id: str | None = None
    feedback_type: str
    reason_factor: str | None = None
    run_at: str | None = None


class RecommendationReadStateRequest(BaseModel):
    run_at: str
    recommendation_id: str | None = None
    action: str = "seen"


def _bounded_text(value: str | None, *, max_len: int = 256) -> str:
    return (value or "").strip()[:max_len]


class RecommendationNotificationResponse(BaseModel):
    items: list[RecommendationNotification]
    grouped_items: list[RecommendationPaperNotification] = Field(default_factory=list)
    unread_count: int
    raw_count: int = 0
    latest_run_at: str | None = None
    scoring_mode: str | None = None
    score_stats: dict[str, dict[str, float]] = Field(default_factory=dict)


def _artifact_root() -> Path:
    """Return configured recommendation artifact root."""

    return Path(os.getenv("RECOMMENDATIONS_ARTIFACTS_DIR", "data/recommendations"))


@router.get("/notifications", response_model=RecommendationNotificationResponse)
async def list_recommendation_notifications(
    limit: int = 10,
    username: str = Depends(get_current_user),
) -> RecommendationNotificationResponse:
    """Return latest AutoResearchClaw recommendations for the signed-in user."""

    bounded_limit = max(1, min(limit, 50))
    return RecommendationNotificationResponse(
        **load_recommendation_artifact(_artifact_root(), username, bounded_limit)
    )



@router.post("/feedback")
async def record_recommendation_feedback(
    body: RecommendationFeedbackRequest,
    username: str = Depends(get_current_user),
) -> dict[str, bool]:
    """Record explicit recommendation feedback as a privacy-safe event."""

    feedback_type = _bounded_text(body.feedback_type, max_len=64)
    recommendation_id = _bounded_text(body.recommendation_id, max_len=256)
    if not feedback_type or not recommendation_id:
        return {"tracked": False}
    payload = {
        "recommendation_id": recommendation_id,
        "feedback_type": feedback_type,
        "reason_factor": _bounded_text(body.reason_factor, max_len=128),
        "run_at": _bounded_text(body.run_at, max_len=64),
    }
    paper_id = _bounded_text(body.paper_id, max_len=256) or None
    if paper_id:
        payload["paper_id"] = paper_id
    try:
        emit_or_warn(
            UserEvent(
                user_id=username,
                event_type=EventType.RECOMMENDATION_FEEDBACK,
                payload=payload,
                paper_id=paper_id,
            )
        )
    except Exception:
        logger.debug("failed to emit RECOMMENDATION_FEEDBACK event", exc_info=True)
        return {"tracked": False}
    return {"tracked": True}


@router.post("/read-state")
async def record_recommendation_read_state(
    body: RecommendationReadStateRequest,
    username: str = Depends(get_current_user),
) -> dict[str, bool]:
    """Record recommendation read/dismiss state as an event."""

    action = _bounded_text(body.action, max_len=32)
    if action not in {"seen", "dismissed"}:
        return {"tracked": False}
    payload = {
        "run_at": _bounded_text(body.run_at, max_len=64),
        "recommendation_id": _bounded_text(body.recommendation_id, max_len=256),
        "action": action,
    }
    try:
        emit_or_warn(
            UserEvent(
                user_id=username,
                event_type=EventType.RECOMMENDATION_READ,
                payload=payload,
            )
        )
    except Exception:
        logger.debug("failed to emit RECOMMENDATION_READ event", exc_info=True)
        return {"tracked": False}
    return {"tracked": True}
