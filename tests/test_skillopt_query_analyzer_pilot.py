"""Offline QueryAnalyzer pilot tests for SkillOpt PR2."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.search_eval.query_analyzer_pilot import load_baseline_skill, run_offline_query_analyzer_pilot
from src.search_eval.skillopt_adapter import canonical_file_hash
from src.search_eval.skillopt_contract import ValidationError

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/search_eval/skillopt_paper_search_v0.json"
CONTROL = ROOT / "data/search_eval/skillopt_execution_control_v0.json"
BASELINE_SKILL = ROOT / "docs/skillopt_search/baseline_skill.md"


def test_offline_query_analyzer_pilot_returns_v1_metadata():
    result = run_offline_query_analyzer_pilot(
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
    )

    assert result["scope"] == "query_analyzer_standard_search"
    assert result["query_count"] == 8
    assert result["split_counts"] == {"train": 4, "selection": 2, "test": 2}
    assert result["rollout_metadata"]["skill_hash"] == canonical_file_hash(BASELINE_SKILL)
    assert result["rollout_metadata"]["hyde_enabled"] is False
    assert result["rollout_metadata"]["query_analysis_confidence"] >= 0.8
    assert all(item["gate_decision"] == "use_original_query" for item in result["analyses"])


def test_offline_query_analyzer_pilot_rejects_scope_drift(tmp_path):
    control = CONTROL.read_text(encoding="utf-8").replace('"use_llm_search": false', '"use_llm_search": true')
    drifted_control = tmp_path / "control.json"
    drifted_control.write_text(control, encoding="utf-8")

    with pytest.raises(ValidationError, match="use_llm_search=false"):
        run_offline_query_analyzer_pilot(
            dataset_path=DATASET,
            control_path=drifted_control,
            baseline_skill_path=BASELINE_SKILL,
        )


def test_baseline_skill_loader_rejects_missing_scope_phrase(tmp_path):
    bad_skill = tmp_path / "bad_skill.md"
    bad_skill.write_text("# Bad Skill\nproduction behavior unchanged", encoding="utf-8")

    with pytest.raises(ValidationError, match="baseline skill missing"):
        load_baseline_skill(bad_skill)
