"""
Tests for EventType enum and UserEvent Pydantic model.

Covers: enum value naming convention, model serialization round-trip,
and payload size enforcement.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.events.event_types import EventType, UserEvent


def test_all_enum_values_snake_case() -> None:
    """Every EventType value must equal its name lowercased."""
    for member in EventType:
        assert member.value == member.name.lower(), (
            f"{member.name!r}: expected value {member.name.lower()!r}, "
            f"got {member.value!r}"
        )


def test_user_event_serialization_roundtrip() -> None:
    """model_dump output must reconstruct an identical UserEvent."""
    original = UserEvent(
        user_id="user123",
        event_type=EventType.PAPER_OPEN,
        payload={"doi": "10.1234/test"},
        paper_id="arxiv:2401.00001",
        source="app",
    )
    dump = original.model_dump()
    reconstructed = UserEvent(**dump)
    assert reconstructed == original


def test_payload_size_limit() -> None:
    """Payload serialized to >8192 bytes must raise ValidationError."""
    # 'x' * 9000 serializes to well over 8192 UTF-8 bytes as a JSON string
    oversized_payload = {"data": "x" * 9000}
    with pytest.raises(ValidationError):
        UserEvent(
            user_id="user42",
            event_type=EventType.QUERY_SUBMIT,
            payload=oversized_payload,
        )


def test_all_eleven_enum_members_present() -> None:
    """Exactly 11 EventType members are defined."""
    expected = {
        "BOOKMARK_ADD",
        "BOOKMARK_REMOVE",
        "HIGHLIGHT_CREATE",
        "HIGHLIGHT_UPDATE",
        "HIGHLIGHT_DELETE",
        "REVIEW_CREATE",
        "REVIEW_UPDATE",
        "SCORE_OVERRIDE",
        "SEARCH_CLICK",
        "PAPER_OPEN",
        "QUERY_SUBMIT",
    }
    actual = {m.name for m in EventType}
    assert actual == expected


def test_user_event_frozen() -> None:
    """UserEvent must be immutable — direct attribute assignment raises an error."""
    event = UserEvent(
        user_id="alice",
        event_type=EventType.BOOKMARK_ADD,
    )
    with pytest.raises((ValidationError, TypeError)):
        event.user_id = "mallory"  # type: ignore[misc]
