"""
Event types for the event-driven lock-in infrastructure.

This module defines the canonical EventType enum and the UserEvent Pydantic model
used to record user interactions with the PaperReviewAgent system. All events are
immutable (frozen=True) to prevent accidental mutation after creation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# EventType enum
# ---------------------------------------------------------------------------

_PAYLOAD_MAX_BYTES = 8192


class EventType(str, Enum):
    """Canonical set of user interaction events tracked by the system."""

    BOOKMARK_ADD = "bookmark_add"
    BOOKMARK_REMOVE = "bookmark_remove"
    HIGHLIGHT_CREATE = "highlight_create"
    HIGHLIGHT_UPDATE = "highlight_update"
    HIGHLIGHT_DELETE = "highlight_delete"
    REVIEW_CREATE = "review_create"
    REVIEW_UPDATE = "review_update"
    SCORE_OVERRIDE = "score_override"
    SEARCH_CLICK = "search_click"
    PAPER_OPEN = "paper_open"
    QUERY_SUBMIT = "query_submit"


# ---------------------------------------------------------------------------
# UserEvent model
# ---------------------------------------------------------------------------


class UserEvent(BaseModel):
    """
    Immutable record of a single user interaction event.

    Parameters
    ----------
    user_id:
        Identifier of the user performing the action (1–64 characters).
    event_type:
        One of the canonical :class:`EventType` values.
    payload:
        Arbitrary JSON-serializable metadata for the event.
        Serialized size must not exceed 8 192 bytes.
    paper_id:
        Optional identifier of the paper involved in the event.
    created_at:
        UTC timestamp of when the event occurred; defaults to now.
    source:
        Origin of the event — ``"app"`` for real-time UI events,
        ``"backfill"`` for historical imports, ``"import"`` for bulk loads.
    """

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=64)
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    paper_id: str | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source: Literal["app", "backfill", "import"] = "app"

    @field_validator("payload")
    @classmethod
    def _validate_payload_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Reject payloads whose JSON representation exceeds 8 192 bytes."""
        size = len(json.dumps(v, ensure_ascii=False).encode("utf-8"))
        if size > _PAYLOAD_MAX_BYTES:
            raise ValueError(
                f"payload exceeds maximum size of {_PAYLOAD_MAX_BYTES} bytes "
                f"(got {size} bytes)"
            )
        return v
