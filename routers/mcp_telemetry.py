"""Authenticated, bounded ingestion for adapter-reported MCP tool telemetry."""

from __future__ import annotations

import logging
import math
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from starlette.requests import Request

from routers.deps import get_current_user, limiter
from routers.deps.storage import _get_user_db
from src.analytics.mcp_usage import TOOL_NAMES, record_event_async

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class MCPToolTelemetryIn(BaseModel):
    invocation_id: UUID
    tool_name: str
    status: Literal["started", "succeeded", "failed", "cancelled"]
    duration_ms: float | None = Field(default=None, ge=0, le=86_400_000)
    client_name: str | None = Field(default=None, min_length=1, max_length=64)
    client_version: str | None = Field(default=None, min_length=1, max_length=32)
    adapter_version: str | None = Field(default=None, min_length=1, max_length=32)

    model_config = {"extra": "forbid"}

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        if value not in TOOL_NAMES:
            raise ValueError("unsupported tool name")
        return value

    @field_validator("duration_ms")
    @classmethod
    def validate_finite_duration(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("duration_ms must be finite")
        return value


class MCPToolTelemetryAccepted(BaseModel):
    accepted: bool = True


@router.post("/telemetry", response_model=MCPToolTelemetryAccepted, status_code=202)
@limiter.limit("120/minute")
async def ingest_mcp_tool_telemetry(
    request: Request,
    event: MCPToolTelemetryIn,
    actor_id: str = Depends(get_current_user),
) -> MCPToolTelemetryAccepted:
    """Record one adapter invocation phase without accepting identity or payload data."""
    user = _get_user_db().get(actor_id) or {}
    actor_role = user.get("role") if user.get("role") in {"user", "admin"} else "user"
    accepted = await record_event_async(
        kind="tool",
        name=event.tool_name,
        status=event.status,
        actor_id=actor_id,
        actor_role=actor_role,
        invocation_id=str(event.invocation_id),
        duration_ms=event.duration_ms,
        client_name=event.client_name,
        client_version=event.client_version,
        adapter_version=event.adapter_version,
        source="adapter_report",
    )
    if not accepted:
        logger.warning("MCP telemetry event was not persisted")
        raise HTTPException(status_code=503, detail="MCP telemetry unavailable")
    return MCPToolTelemetryAccepted()


__all__ = ["MCPToolTelemetryIn", "router"]
