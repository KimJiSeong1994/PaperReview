"""Offline QueryAnalyzer policy pilot for SkillOpt search experiments.

This module is deliberately dev/eval-only. It does not import the production
QueryAnalyzer or call the search router. It evaluates the PR1 benchmark fixture
against the documented baseline skill so PR2 can prove the offline gate shape
before any SkillOpt adapter or production flag exists.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .skillopt_contract import (
    V1_ALLOWED_SCOPE,
    ValidationError,
    load_json,
    validate_dataset_contract,
    validate_execution_control,
)


@dataclass(frozen=True)
class OfflineQueryAnalysis:
    """Deterministic offline analysis record for one benchmark query."""

    query_id: str
    original_query: str
    improved_query: str
    confidence: float
    gate_decision: str
    split: str


def load_baseline_skill(path: str | Path) -> str:
    """Load the doc-only baseline search skill used by the offline pilot."""
    text = Path(path).read_text(encoding="utf-8")
    required_phrases = (
        "QueryAnalyzer standard search path",
        "Do not include `use_llm_search`",
        "production behavior unchanged",
    )
    missing = [phrase for phrase in required_phrases if phrase not in text]
    if missing:
        raise ValidationError(f"baseline skill missing required phrases: {missing}")
    return text


def run_offline_query_analyzer_pilot(
    *,
    dataset_path: str | Path,
    control_path: str | Path,
    baseline_skill_path: str | Path,
) -> dict[str, Any]:
    """Evaluate the baseline QueryAnalyzer policy over the offline fixture.

    The pilot intentionally returns a metadata envelope, not search results. Its
    purpose is to prove that later SkillOpt candidates must carry the same v1
    execution controls and rollout metadata before they can be compared.
    """
    dataset = load_json(dataset_path)
    control = load_json(control_path)
    skill_text = load_baseline_skill(baseline_skill_path)
    baseline_skill_hash = _file_hash(baseline_skill_path)
    validate_dataset_contract(dataset)
    validate_execution_control(control)

    analyses = [_analyze_fixture_query(query) for query in dataset["queries"]]
    accepted = [analysis for analysis in analyses if analysis.gate_decision == "use_original_query"]
    split_counts: dict[str, int] = {"train": 0, "selection": 0, "test": 0}
    for analysis in analyses:
        split_counts[analysis.split] += 1

    return {
        "version": "query-analyzer-offline-pilot-v0",
        "scope": V1_ALLOWED_SCOPE,
        "dataset_hash": dataset["dataset_hash"],
        "execution_control_hash": control["control_hash"],
        "baseline_skill_chars": len(skill_text),
        "query_count": len(analyses),
        "accepted_query_count": len(accepted),
        "split_counts": split_counts,
        "rollout_metadata": {
            "skill_hash": baseline_skill_hash,
            "dataset_hash": dataset["dataset_hash"],
            "execution_control_hash": control["control_hash"],
            "stage_modes": ["offline_query_analyzer_pilot"],
            "stage_timings": {"offline_query_analyzer_pilot_ms": 0},
            "query_analysis_confidence": min(analysis.confidence for analysis in analyses),
            "improved_query_gate_decision": "use_original_query",
            "cache_status": control["cache_policy"],
            "hyde_enabled": control["hyde_policy"]["enabled"],
            "relevance_scorer_path": control["relevance_filter_policy"]["local_cross_encoder"],
            "budget_branch": control["budget_policy"]["mode"],
        },
        "analyses": [analysis.__dict__ for analysis in analyses],
    }


def _analyze_fixture_query(query: Mapping[str, Any]) -> OfflineQueryAnalysis:
    """Produce a conservative offline stand-in for standard QueryAnalyzer policy."""
    original = str(query["query_text"])
    return OfflineQueryAnalysis(
        query_id=str(query["query_id"]),
        original_query=original,
        improved_query=original,
        confidence=1.0,
        gate_decision="use_original_query",
        split=str(query["split"]),
    )


def _file_hash(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()
