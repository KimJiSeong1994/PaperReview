"""Deprecated v0 fixture provenance for external SkillOpt characterization.

This module does not run SkillOpt training. It records the boundary between this
repo's materialized benchmark and an external SkillOpt checkout/output so later
approval can prove which benchmark, command, and best_skill.md produced a
candidate.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .policy_validation import validate_runtime_policy_text
from .skillopt_adapter import canonical_file_hash
from .skillopt_contract import V1_ALLOWED_SCOPE, ValidationError, load_json
from .skillopt_materializer import ENV_NAME, validate_skillopt_materialization_manifest

CANDIDATE_GENERATION_VERSION = "skillopt-candidate-generation-manifest-v0"


def record_candidate_generation_manifest(
    *,
    output_dir: str | Path,
    materialization_manifest_path: str | Path,
    best_skill_path: str | Path,
    external_run: Mapping[str, Any],
) -> dict[str, Any]:
    """Write a non-authoritative v0 fixture/dev characterization manifest."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    materialization_manifest = load_json(materialization_manifest_path)
    validate_skillopt_materialization_manifest(materialization_manifest)
    skill_path = Path(best_skill_path)
    try:
        skill_text = skill_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(
            f"candidate best_skill path is unreadable: {skill_path}"
        ) from exc
    validate_runtime_policy_text(skill_text)
    _validate_external_run(external_run)
    manifest = {
        "version": CANDIDATE_GENERATION_VERSION,
        "created_at": _utc_now_iso(),
        "env_name": ENV_NAME,
        "scope": V1_ALLOWED_SCOPE,
        "status": "fixture_only_not_exportable",
        "deprecated": True,
        "authority": "none",
        "evidence_class": "fixture",
        "authorization_status": "not_authorized",
        "authoritative_use": False,
        "materialization_manifest_path": str(Path(materialization_manifest_path)),
        "materialization_manifest_hash": canonical_file_hash(
            materialization_manifest_path
        ),
        "materialization_source_hashes": dict(
            materialization_manifest["source_hashes"]
        ),
        "dataset_hash": materialization_manifest["dataset_hash"],
        "execution_control_hash": materialization_manifest["execution_control_hash"],
        "best_skill_path": str(skill_path),
        "best_skill_hash": canonical_file_hash(skill_path),
        "external_run": dict(external_run),
        "external_run_hash": _mapping_hash(external_run),
        "requires_approved_export": False,
    }
    validate_candidate_generation_manifest(manifest)
    manifest_path = output / "candidate_generation_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {**manifest, "manifest_path": str(manifest_path)}


def validate_candidate_generation_manifest(manifest: Mapping[str, Any]) -> None:
    required = {
        "version",
        "created_at",
        "env_name",
        "scope",
        "status",
        "deprecated",
        "authority",
        "evidence_class",
        "authorization_status",
        "authoritative_use",
        "materialization_manifest_path",
        "materialization_manifest_hash",
        "materialization_source_hashes",
        "dataset_hash",
        "execution_control_hash",
        "best_skill_path",
        "best_skill_hash",
        "external_run",
        "external_run_hash",
        "requires_approved_export",
    }
    missing = required - set(manifest)
    if missing:
        raise ValidationError(
            f"candidate generation manifest missing required keys: {sorted(missing)}"
        )
    if manifest.get("version") != CANDIDATE_GENERATION_VERSION:
        raise ValidationError("candidate generation manifest version is invalid")
    if manifest.get("env_name") != ENV_NAME:
        raise ValidationError("candidate generation env_name is invalid")
    if manifest.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("candidate generation scope is invalid")
    if manifest.get("status") != "fixture_only_not_exportable":
        raise ValidationError("candidate generation v0 must remain fixture-only")
    if manifest.get("deprecated") is not True:
        raise ValidationError(
            "candidate generation v0 must remain explicitly deprecated"
        )
    if manifest.get("authority") != "none":
        raise ValidationError("candidate generation v0 authority must be none")
    if manifest.get("evidence_class") != "fixture":
        raise ValidationError("candidate generation v0 evidence_class must be fixture")
    if manifest.get("authorization_status") != "not_authorized":
        raise ValidationError("candidate generation v0 must remain not_authorized")
    if manifest.get("authoritative_use") is not False:
        raise ValidationError("candidate generation v0 cannot be used authoritatively")
    if manifest.get("requires_approved_export") is not False:
        raise ValidationError("candidate generation v0 cannot enter approved export")
    _require_iso_datetime(manifest.get("created_at"), "candidate_generation.created_at")
    materialization_path = _require_existing_file(
        manifest.get("materialization_manifest_path"), "materialization_manifest_path"
    )
    if canonical_file_hash(materialization_path) != manifest.get(
        "materialization_manifest_hash"
    ):
        raise ValidationError(
            "candidate generation materialization manifest hash mismatch"
        )
    materialization_manifest = load_json(materialization_path)
    validate_skillopt_materialization_manifest(materialization_manifest)
    if dict(manifest.get("materialization_source_hashes", {})) != dict(
        materialization_manifest["source_hashes"]
    ):
        raise ValidationError(
            "candidate generation materialization source hashes mismatch"
        )
    if manifest.get("dataset_hash") != materialization_manifest.get("dataset_hash"):
        raise ValidationError("candidate generation dataset_hash mismatch")
    if manifest.get("execution_control_hash") != materialization_manifest.get(
        "execution_control_hash"
    ):
        raise ValidationError("candidate generation execution_control_hash mismatch")
    best_skill_path = _require_existing_file(
        manifest.get("best_skill_path"), "best_skill_path"
    )
    if canonical_file_hash(best_skill_path) != manifest.get("best_skill_hash"):
        raise ValidationError("candidate generation best_skill hash mismatch")
    validate_runtime_policy_text(best_skill_path.read_text(encoding="utf-8"))
    external_run = manifest.get("external_run")
    _validate_external_run(external_run)
    if _mapping_hash(external_run) != manifest.get("external_run_hash"):
        raise ValidationError("candidate generation external_run hash mismatch")


def _validate_external_run(external_run: Any) -> None:
    if not isinstance(external_run, Mapping):
        raise ValidationError("candidate generation external_run must be an object")
    allowed = {
        "runner",
        "command",
        "run_id",
        "completed_at",
        "raw_user_logs_included",
        "pii_included",
    }
    if set(external_run) != allowed:
        raise ValidationError(
            "candidate generation external_run contains unsupported keys"
        )
    for key in ("runner", "command", "run_id"):
        value = external_run.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(
                f"candidate generation external_run.{key} is required"
            )
        _reject_secret_like_text(value, f"candidate_generation.external_run.{key}")
    _require_iso_datetime(
        external_run.get("completed_at"),
        "candidate_generation.external_run.completed_at",
    )
    if external_run.get("raw_user_logs_included") is not False:
        raise ValidationError(
            "candidate generation external run must exclude raw user logs"
        )
    if external_run.get("pii_included") is not False:
        raise ValidationError("candidate generation external run must exclude PII")


def _reject_secret_like_text(value: str, field: str) -> None:
    lowered = value.lower()
    for marker in (
        "api_key",
        "secret",
        "password",
        "raw user log",
        "raw_logs",
        "user_id",
        "session_id",
        "@",
    ):
        if marker in lowered:
            raise ValidationError(
                f"{field} must not include secret, PII, or raw-user-log markers"
            )


def _mapping_hash(value: Mapping[str, Any]) -> str:
    import hashlib

    payload = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_existing_file(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"candidate generation {field} is required")
    path = Path(value)
    if not path.is_file():
        raise ValidationError(f"candidate generation {field} is missing")
    return path


def _require_iso_datetime(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be an ISO timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO timestamp") from exc


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
