from __future__ import annotations

from pathlib import Path

import pytest

from src.search_eval.skillopt_candidate_generation import (
    record_candidate_generation_manifest,
    validate_candidate_generation_manifest,
)
from src.search_eval.skillopt_contract import ValidationError
from src.search_eval.skillopt_materializer import materialize_skillopt_search_benchmark

DATASET = "data/search_eval/skillopt_paper_search_v0.json"
CONTROL = "data/search_eval/skillopt_execution_control_v0.json"
BASELINE_SKILL = "docs/skillopt_search/baseline_skill.md"


def _materialization_manifest_path(tmp_path: Path) -> Path:
    manifest = materialize_skillopt_search_benchmark(
        output_dir=tmp_path / "materialized",
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
    )
    return Path(manifest["output_dir"]) / "skillopt_materialization_manifest.json"


def _best_skill(tmp_path: Path) -> Path:
    text = Path(BASELINE_SKILL).read_text(encoding="utf-8") + """

## SkillOpt generated candidate
- QueryAnalyzer standard search path should preserve exact paper-title and author intent first.
- Do not enable `use_llm_search` for this policy.
- Do not enable HyDE prompt optimization for this policy.
- Do not promote RelevanceFilter prompt optimization for this policy.
"""
    path = tmp_path / "best_skill.md"
    path.write_text(text, encoding="utf-8")
    return path


def _external_run() -> dict:
    return {
        "runner": "external-skillopt-checkout",
        "command": "python scripts/train.py --config configs/jiphyeonjeon_search/default.yaml",
        "run_id": "skillopt-run-001",
        "completed_at": "2026-07-04T14:00:00Z",
        "raw_user_logs_included": False,
        "pii_included": False,
    }


def test_candidate_generation_manifest_binds_external_skillopt_output(tmp_path: Path):
    materialization_path = _materialization_manifest_path(tmp_path)
    best_skill = _best_skill(tmp_path)

    manifest = record_candidate_generation_manifest(
        output_dir=tmp_path / "candidate-generation",
        materialization_manifest_path=materialization_path,
        best_skill_path=best_skill,
        external_run=_external_run(),
    )

    validate_candidate_generation_manifest(manifest)
    assert Path(manifest["manifest_path"]).exists()
    assert manifest["status"] == "candidate_generated_requires_offline_approval"
    assert manifest["requires_approved_export"] is True
    assert manifest["external_run"]["raw_user_logs_included"] is False
    assert manifest["external_run_hash"].startswith("sha256:")


def test_candidate_generation_manifest_rejects_best_skill_and_materialization_drift(tmp_path: Path):
    materialization_path = _materialization_manifest_path(tmp_path)
    best_skill = _best_skill(tmp_path)
    manifest = record_candidate_generation_manifest(
        output_dir=tmp_path / "candidate-generation",
        materialization_manifest_path=materialization_path,
        best_skill_path=best_skill,
        external_run=_external_run(),
    )

    best_skill.write_text(best_skill.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="best_skill hash"):
        validate_candidate_generation_manifest(manifest)

    best_skill.write_text(Path(BASELINE_SKILL).read_text(encoding="utf-8") + "\nQueryAnalyzer standard search path\nDo not enable `use_llm_search`\nDo not enable HyDE\nDo not promote RelevanceFilter\n", encoding="utf-8")
    tampered = {**manifest, "materialization_manifest_hash": "sha256:" + "0" * 64}
    with pytest.raises(ValidationError, match="materialization manifest hash"):
        validate_candidate_generation_manifest(tampered)


def test_candidate_generation_manifest_rejects_external_run_extra_fields_and_hash_drift(tmp_path: Path):
    materialization_path = _materialization_manifest_path(tmp_path)
    best_skill = _best_skill(tmp_path)

    with pytest.raises(ValidationError, match="unsupported keys"):
        record_candidate_generation_manifest(
            output_dir=tmp_path / "candidate-generation-extra",
            materialization_manifest_path=materialization_path,
            best_skill_path=best_skill,
            external_run={**_external_run(), "raw_logs": "USER_EMAIL=alice@example.com"},
        )

    manifest = record_candidate_generation_manifest(
        output_dir=tmp_path / "candidate-generation",
        materialization_manifest_path=materialization_path,
        best_skill_path=best_skill,
        external_run=_external_run(),
    )
    tampered = {**manifest, "external_run_hash": "sha256:" + "0" * 64}
    with pytest.raises(ValidationError, match="external_run hash"):
        validate_candidate_generation_manifest(tampered)


def test_candidate_generation_rejects_secret_or_raw_log_external_run(tmp_path: Path):
    with pytest.raises(ValidationError, match="secret|raw-user-log|raw user logs"):
        record_candidate_generation_manifest(
            output_dir=tmp_path / "candidate-generation",
            materialization_manifest_path=_materialization_manifest_path(tmp_path),
            best_skill_path=_best_skill(tmp_path),
            external_run={**_external_run(), "command": "python train.py --api_key secret"},
        )
    with pytest.raises(ValidationError, match="raw user logs"):
        record_candidate_generation_manifest(
            output_dir=tmp_path / "candidate-generation-raw",
            materialization_manifest_path=_materialization_manifest_path(tmp_path / "raw"),
            best_skill_path=_best_skill(tmp_path / "raw"),
            external_run={**_external_run(), "raw_user_logs_included": True},
        )
