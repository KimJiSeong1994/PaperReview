"""Paper recommendation notification endpoints."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.recommendations_artifacts import load_recommendation_artifact

from .deps.auth import get_current_user

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


class RecommendationVariantEvidence(BaseModel):
    variant: str
    reason: str = ""
    score: float | None = None
    display_score: str | None = None
    confidence_label: str
    rank: int | None = None


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
    variants: list[RecommendationVariantEvidence] = Field(default_factory=list)


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
