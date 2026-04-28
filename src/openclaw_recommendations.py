"""Import helpers for OpenClaw paper-recommender artifacts.

OpenClaw/AutoResearchClaw writes ``raw.json`` recommendation artifacts whose
shape is already consumed by :mod:`src.recommendations_artifacts`. This module
validates that an artifact is safe to publish, derives the PaperReviewAgent
user/date destination, and writes it atomically under the existing notification
artifact layout.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.recommendations_artifacts import safe_str


_SAFE_USER_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class OpenClawArtifactError(ValueError):
    """Raised when an OpenClaw artifact cannot be safely imported."""


@dataclass(frozen=True)
class ImportedOpenClawArtifact:
    """Result metadata for an imported OpenClaw artifact."""

    user_id: str
    date: str
    source_path: Path
    destination_path: Path
    variant_count: int
    item_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "imported": True,
            "user_id": self.user_id,
            "date": self.date,
            "source_path": str(self.source_path),
            "destination_path": str(self.destination_path),
            "variant_count": self.variant_count,
            "item_count": self.item_count,
        }


def safe_user_id(value: Any) -> str:
    """Return a path-safe OpenClaw/PaperReview user id or raise."""

    user_id = safe_str(value)
    if not _SAFE_USER_ID_RE.fullmatch(user_id):
        raise OpenClawArtifactError("raw.json user_id is missing or not path-safe")
    return user_id


def _valid_date(value: Any) -> str | None:
    candidate = safe_str(value)
    if not _DATE_RE.fullmatch(candidate):
        return None
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def _variant_items(raw: dict[str, Any]) -> tuple[int, int]:
    variants = raw.get("variants")
    if not isinstance(variants, dict) or not variants:
        raise OpenClawArtifactError("raw.json variants must be a non-empty object")

    variant_count = 0
    item_count = 0
    for name, items in variants.items():
        if not safe_str(name):
            raise OpenClawArtifactError("raw.json contains an empty variant name")
        if not isinstance(items, list):
            raise OpenClawArtifactError(f"raw.json variant {name!r} must be a list")
        valid_items = [item for item in items if isinstance(item, dict) and safe_str(item.get("title"))]
        if valid_items:
            variant_count += 1
            item_count += len(valid_items)

    if item_count <= 0:
        raise OpenClawArtifactError("raw.json variants contain no titled paper items")
    return variant_count, item_count


def _date_from_run_at(value: Any) -> str | None:
    run_at = safe_str(value)
    if not run_at:
        return None
    prefix_date = _valid_date(run_at[:10])
    if prefix_date:
        return prefix_date
    try:
        return datetime.fromisoformat(run_at.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _date_from_source_path(source_path: Path) -> str | None:
    for part in reversed(source_path.parts):
        artifact_date = _valid_date(part)
        if artifact_date:
            return artifact_date
    return None


def derive_artifact_date(raw: dict[str, Any], source_path: Path, *, date_override: str | None = None) -> str:
    """Derive the PaperReviewAgent artifact date for an OpenClaw raw artifact."""

    if date_override is not None:
        artifact_date = _valid_date(date_override)
        if artifact_date is None:
            raise OpenClawArtifactError("--date must be a valid YYYY-MM-DD date")
        return artifact_date

    for candidate in (_date_from_run_at(raw.get("run_at")), _date_from_source_path(source_path)):
        if candidate:
            return candidate
    return datetime.now(timezone.utc).date().isoformat()


def load_and_validate_openclaw_raw(source_path: Path) -> tuple[dict[str, Any], str, int, int]:
    """Load an OpenClaw ``raw.json`` and return validated metadata."""

    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OpenClawArtifactError(f"raw.json not found: {source_path}") from exc
    except OSError as exc:
        raise OpenClawArtifactError(f"could not read raw.json: {source_path}") from exc
    except json.JSONDecodeError as exc:
        raise OpenClawArtifactError("raw.json is not valid JSON") from exc

    if not isinstance(raw, dict):
        raise OpenClawArtifactError("raw.json must contain a JSON object")

    user_id = safe_user_id(raw.get("user_id"))
    variant_count, item_count = _variant_items(raw)
    return raw, user_id, variant_count, item_count


def destination_path(artifacts_dir: Path, user_id: str, artifact_date: str) -> Path:
    """Return a normalized destination that cannot escape ``artifacts_dir``."""

    safe_user = safe_user_id(user_id)
    valid_date = _valid_date(artifact_date)
    if valid_date is None:
        raise OpenClawArtifactError("destination date must be a valid YYYY-MM-DD date")

    root = artifacts_dir.resolve()
    destination = (root / safe_user / valid_date / "raw.json").resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:  # defensive; safe_user/date validation should already prevent this.
        raise OpenClawArtifactError("destination escaped artifacts directory") from exc
    return destination


def import_openclaw_artifact(
    source_path: Path,
    artifacts_dir: Path,
    *,
    date_override: str | None = None,
) -> ImportedOpenClawArtifact:
    """Validate and atomically import an OpenClaw raw artifact.

    The artifact is written to
    ``{artifacts_dir}/{user_id}/{YYYY-MM-DD}/raw.json`` so the existing
    recommendation notification reader can consume it without schema changes.
    """

    source_path = source_path.expanduser()
    raw, user_id, variant_count, item_count = load_and_validate_openclaw_raw(source_path)
    artifact_date = derive_artifact_date(raw, source_path, date_override=date_override)
    destination = destination_path(artifacts_dir, user_id, artifact_date)
    destination.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = destination.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(destination)

    return ImportedOpenClawArtifact(
        user_id=user_id,
        date=artifact_date,
        source_path=source_path,
        destination_path=destination,
        variant_count=variant_count,
        item_count=item_count,
    )
