"""Validation and fail-safe loading for generated GEO comparisons."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO_ROOT / "data/blog/geo-comparisons.json"
GENERATED_PATH = REPO_ROOT / "routers/geo_comparisons_generated.py"

AXES = (
    "retrieval_or_representation_unit",
    "graph_construction",
    "evaluation_context",
    "traceability",
    "cost",
    "failure_conditions",
)
HUBS = ("graphrag", "gnn")
CELL_STATES = {"known", "unknown", "not_applicable"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class GeoComparisonError(ValueError):
    """The comparison source does not satisfy the public data contract."""


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a JSON value deterministically for source and field hashes."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GeoComparisonError(f"{path} must be a non-empty string")
    return value


def _https_url(value: Any, path: str) -> str:
    text = _nonempty_string(value, path)
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise GeoComparisonError(f"{path} must be an HTTPS URL without credentials")
    return text


def validate_comparisons(
    document: Any,
    *,
    series_members: Mapping[str, Sequence[str]] | None = None,
    published_slugs: set[str] | None = None,
) -> dict[str, Any]:
    """Validate and return a detached comparison mapping.

    ``series_members`` and ``published_slugs`` are supplied by build tooling so
    this module remains importable without the web application or its data.
    """
    if not isinstance(document, Mapping):
        raise GeoComparisonError("comparison document must be an object")
    if set(document) != {"schema_version", "comparisons"}:
        raise GeoComparisonError("comparison document has unknown or missing fields")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise GeoComparisonError("schema_version must be 1")
    comparisons = document["comparisons"]
    if not isinstance(comparisons, Mapping) or tuple(comparisons) != HUBS:
        raise GeoComparisonError("comparisons must contain graphrag then gnn")

    all_entry_slugs: set[str] = set()
    for hub_id, hub in comparisons.items():
        path = f"comparisons.{hub_id}"
        if not isinstance(hub, Mapping):
            raise GeoComparisonError(f"{path} must be an object")
        required = {"question", "reading_guide", "axes", "entries", "limits", "source_note"}
        if set(hub) != required:
            raise GeoComparisonError(f"{path} has unknown or missing fields")
        _nonempty_string(hub["question"], f"{path}.question")
        _nonempty_string(hub["limits"], f"{path}.limits")
        _nonempty_string(hub["source_note"], f"{path}.source_note")
        reading_guide = hub["reading_guide"]
        if not isinstance(reading_guide, list) or not 1 <= len(reading_guide) <= 6:
            raise GeoComparisonError(f"{path}.reading_guide must contain one to six steps")
        guide_slugs: list[str] = []
        for step_index, step in enumerate(reading_guide):
            step_path = f"{path}.reading_guide[{step_index}]"
            if not isinstance(step, Mapping) or set(step) != {"title", "description", "slugs"}:
                raise GeoComparisonError(f"{step_path} has unknown or missing fields")
            _nonempty_string(step["title"], f"{step_path}.title")
            _nonempty_string(step["description"], f"{step_path}.description")
            if not isinstance(step["slugs"], list) or not step["slugs"]:
                raise GeoComparisonError(f"{step_path}.slugs must be a non-empty array")
            for slug in step["slugs"]:
                guide_slugs.append(_nonempty_string(slug, f"{step_path}.slugs"))
        if len(guide_slugs) != len(set(guide_slugs)):
            raise GeoComparisonError(f"{path}.reading_guide has duplicated slugs")
        if series_members is not None and guide_slugs != list(series_members.get(hub_id, ())):
            raise GeoComparisonError(f"{path}.reading_guide must preserve complete series order")
        axes = hub["axes"]
        if not isinstance(axes, list) or tuple(axes) != AXES:
            raise GeoComparisonError(f"{path}.axes must contain the six axes in canonical order")
        entries = hub["entries"]
        if not isinstance(entries, list) or not entries:
            raise GeoComparisonError(f"{path}.entries must be a non-empty array")
        seen_slugs: set[str] = set()
        for entry_index, entry in enumerate(entries):
            entry_path = f"{path}.entries[{entry_index}]"
            if not isinstance(entry, Mapping) or set(entry) != {"slug", "label", "summary", "values"}:
                raise GeoComparisonError(f"{entry_path} has unknown or missing fields")
            slug = _nonempty_string(entry["slug"], f"{entry_path}.slug")
            _nonempty_string(entry["label"], f"{entry_path}.label")
            summary = entry["summary"]
            if not isinstance(summary, Mapping) or set(summary) != {"role", "fit", "caution"}:
                raise GeoComparisonError(f"{entry_path}.summary has unknown or missing fields")
            for key, value in summary.items():
                text = _nonempty_string(value, f"{entry_path}.summary.{key}")
                if len(text) > 100:
                    raise GeoComparisonError(f"{entry_path}.summary.{key} exceeds 100 characters")
            if slug in seen_slugs:
                raise GeoComparisonError(f"{entry_path}.slug is duplicated")
            seen_slugs.add(slug)
            if slug in all_entry_slugs:
                raise GeoComparisonError(f"{entry_path}.slug belongs to more than one series")
            all_entry_slugs.add(slug)
            if series_members is not None and slug not in series_members.get(hub_id, ()):
                raise GeoComparisonError(f"{entry_path}.slug is not a {hub_id} member")
            if published_slugs is not None and slug not in published_slugs:
                raise GeoComparisonError(f"{entry_path}.slug is not published")
            values = entry["values"]
            if not isinstance(values, Mapping) or tuple(values) != AXES:
                raise GeoComparisonError(f"{entry_path}.values must contain every axis in order")
            for axis, cell in values.items():
                cell_path = f"{entry_path}.values.{axis}"
                if not isinstance(cell, Mapping) or set(cell) != {
                    "state", "value", "reason", "sources"
                }:
                    raise GeoComparisonError(f"{cell_path} has unknown or missing fields")
                state = cell["state"]
                if state not in CELL_STATES:
                    raise GeoComparisonError(f"{cell_path}.state is invalid")
                sources = cell["sources"]
                if not isinstance(sources, list) or any(
                    not isinstance(source, str) for source in sources
                ):
                    raise GeoComparisonError(f"{cell_path}.sources must be a unique array")
                if len(sources) != len(set(sources)):
                    raise GeoComparisonError(f"{cell_path}.sources must be a unique array")
                for source_index, source in enumerate(sources):
                    _https_url(source, f"{cell_path}.sources[{source_index}]")
                if state == "known":
                    _nonempty_string(cell["value"], f"{cell_path}.value")
                    if cell["reason"] is not None:
                        raise GeoComparisonError(f"{cell_path}.reason must be null when known")
                    if not sources:
                        raise GeoComparisonError(f"{cell_path}.sources requires primary provenance")
                else:
                    if cell["value"] is not None:
                        raise GeoComparisonError(f"{cell_path}.value must be null for {state}")
                    _nonempty_string(cell["reason"], f"{cell_path}.reason")
    return copy.deepcopy(dict(comparisons))


def _literal_generated(path: Path) -> tuple[Any, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if (
            not isinstance(node, ast.Assign)
            or len(node.targets) != 1
            or not isinstance(node.targets[0], ast.Name)
            or node.targets[0].id
            not in {"GEO_COMPARISONS", "GEO_COMPARISONS_SOURCE_SHA256"}
        ):
            raise GeoComparisonError("generated projection contains executable or unknown statements")
        name = node.targets[0].id
        if name in values:
            raise GeoComparisonError("generated projection has duplicate exports")
        values[name] = ast.literal_eval(node.value)
    if set(values) != {"GEO_COMPARISONS", "GEO_COMPARISONS_SOURCE_SHA256"}:
        raise GeoComparisonError("generated projection has missing exports")
    return values["GEO_COMPARISONS"], values["GEO_COMPARISONS_SOURCE_SHA256"]


def load_geo_comparisons(
    *, generated_path: Path = GENERATED_PATH, source_path: Path = SOURCE_PATH
) -> dict[str, Any]:
    """Return source-matched literal projections, or an empty mapping on corruption."""
    try:
        source_document = json.loads(
            source_path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                GeoComparisonError(f"non-finite JSON constant is forbidden: {token}")
            ),
        )
        source_comparisons = validate_comparisons(source_document)
        generated_comparisons, embedded_digest = _literal_generated(generated_path)
        checked_generated = validate_comparisons(
            {"schema_version": 1, "comparisons": generated_comparisons}
        )
        if not isinstance(embedded_digest, str) or not _SHA256_RE.fullmatch(embedded_digest):
            raise GeoComparisonError("generated source hash is malformed")
        expected_digest = canonical_sha256(
            {"schema_version": 1, "comparisons": source_comparisons}
        )
        generated_digest = canonical_sha256(
            {"schema_version": 1, "comparisons": checked_generated}
        )
        if embedded_digest != expected_digest or generated_digest != expected_digest:
            raise GeoComparisonError("generated projection digest does not match canonical source")
        return checked_generated
    except (
        AttributeError,
        GeoComparisonError,
        json.JSONDecodeError,
        OSError,
        SyntaxError,
        TypeError,
        ValueError,
    ) as exc:
        logger.warning("GEO comparisons unavailable; preserving the original series hub: %s", exc)
        return {}
