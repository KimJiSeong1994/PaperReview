"""Validation helpers for SkillOpt paper-search evaluation artifacts.

These helpers intentionally do not call the production search path. They guard
PR1 scaffolding artifacts so later SkillOpt experiments cannot silently promote
an unversioned skill, leak split groups, or compare baseline/candidate runs under
incompatible execution controls.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class ValidationError(ValueError):
    """Raised when a SkillOpt search-eval artifact violates the contract."""


REQUIRED_DATASET_FIELDS = {
    "version",
    "dataset_hash",
    "provenance",
    "splits",
    "queries",
    "primary_metric",
    "guardrail_metrics",
}

REQUIRED_QUERY_FIELDS = {
    "query_id",
    "query_text",
    "group_id",
    "split",
    "locale",
    "intent",
    "difficulty",
    "downstream",
    "labels",
}

REQUIRED_PROVENANCE_FIELDS = {
    "type",
    "raw_user_logs_included",
    "privacy_review",
}

REQUIRED_SPLIT_FIELDS = {"train", "selection", "test"}

REQUIRED_LABEL_FIELDS = {"must_include", "acceptable", "must_exclude"}

REQUIRED_ARTIFACT_FIELDS = {
    "version",
    "skill_hash",
    "baseline_hash",
    "dataset_hash",
    "execution_control_hash",
    "created_at",
    "metric_snapshot",
    "rollback_to",
    "rollout_metadata",
    "scope",
}

REQUIRED_ROLLBACK_FIELDS = {
    "rollback_id",
    "from_candidate_hash",
    "rollback_to_skill_hash",
    "reason",
    "triggered_by",
    "feature_flag_after",
    "quarantined_candidate",
    "api_contract_unchanged",
}

REQUIRED_CONTROL_FIELDS = {
    "version",
    "control_hash",
    "scope",
    "fast_mode",
    "use_llm_search",
    "cache_policy",
    "query_analyzer_confidence_gate",
    "improved_query_overlap_gate",
    "hyde_policy",
    "relevance_filter_policy",
    "budget_policy",
    "controlled_rollout_gate",
    "required_rollout_metadata",
}

V1_ALLOWED_SCOPE = "query_analyzer_standard_search"
CANDIDATE_ARTIFACT_VERSION = "candidate-example-v0"
PRIMARY_METRIC = "nDCG@10"
REQUIRED_GUARDRAILS = {
    "MRR@10",
    "Recall@5",
    "Recall@10",
    "wrong_paper_handoff_rate",
    "p95_latency_ms",
    "token_estimate",
    "cost_estimate",
}
_ALLOWED_HYDE_POLICY = {
    "enabled": False,
    "promotion_in_scope": False,
    "reason": "v1 isolates QueryAnalyzer standard search policy",
}
_ALLOWED_RELEVANCE_FILTER = {
    "local_cross_encoder": "production_equivalent",
    "llm_fallback": "production_equivalent_logged",
    "promotion_in_scope": False,
    "reason": "v1 excludes RelevanceFilter prompt optimization",
}
_GUARDRAIL_LIMITS = {
    "wrong_paper_handoff_rate": 0.05,
    "p95_latency_ms": 3000.0,
}
_MINIMUM_QUERY_ANALYSIS_CONFIDENCE = 0.8
_REQUIRED_ROLLOUT_METADATA = {
    "skill_hash",
    "dataset_hash",
    "execution_control_hash",
    "stage_modes",
    "stage_timings",
    "query_analysis_confidence",
    "improved_query_gate_decision",
    "cache_status",
    "hyde_enabled",
    "relevance_scorer_path",
    "budget_branch",
}
_ALLOWED_CONFIDENCE_GATE = {
    "mode": "production_equivalent",
    "minimum_confidence": _MINIMUM_QUERY_ANALYSIS_CONFIDENCE,
}
_ALLOWED_OVERLAP_GATE = {
    "mode": "production_equivalent",
    "minimum_overlap": 0.5,
    "max_length_ratio": 2.0,
}
_ALLOWED_BUDGET_POLICY = {
    "mode": "generous_fixed_offline_budget",
    "low_budget_slice": "separate_guardrail_eval",
}
_ALLOWED_CONTROLLED_ROLLOUT_GATE = {
    "state": "shadow_only",
    "max_rollout_fraction": 0.0,
    "requires_manual_approval": True,
}
_ALLOWED_QUERY_ENUMS = {
    "locale": {"en", "ko", "mixed"},
    "difficulty": {"easy", "medium", "hard"},
    "downstream": {"search_only", "search_to_review", "search_to_explore"},
}
_PII_PATTERNS = (
    re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
    re.compile(
        r"\b(?:raw user logs?|raw logs|raw user identifiers?|private rejected query|private quer(?:y|ies)|user_id|session_id)\b",
        re.IGNORECASE,
    ),
)


def load_json(path: str | Path) -> dict[str, Any]:
    """Load a JSON object from ``path``."""
    data = json.loads(
        Path(path).read_text(encoding="utf-8"),
        parse_constant=lambda constant: (_ for _ in ()).throw(
            ValidationError(f"non-finite JSON value {constant}")
        ),
    )
    if not isinstance(data, dict):
        raise ValidationError(f"{path} must contain a JSON object")
    return data


def canonical_self_hash(value: Mapping[str, Any], hash_field: str) -> str:
    """Return a canonical sha256 over an artifact excluding its hash field."""
    payload = dict(value)
    payload.pop(hash_field, None)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_dataset_contract(dataset: Mapping[str, Any]) -> None:
    """Validate the v0 benchmark dataset contract."""
    _require_exact_keys(dataset, REQUIRED_DATASET_FIELDS, "dataset")
    _reject_private_strings(dataset, "dataset")
    dataset_hash = _require_sha256_digest(
        dataset.get("dataset_hash"), "dataset.dataset_hash"
    )
    if dataset.get("primary_metric") != PRIMARY_METRIC:
        raise ValidationError("dataset primary_metric must be nDCG@10")
    guardrail_metrics = dataset.get("guardrail_metrics")
    if not isinstance(guardrail_metrics, Sequence) or isinstance(
        guardrail_metrics, (str, bytes)
    ):
        raise ValidationError("dataset.guardrail_metrics must be a list")
    if any(
        not isinstance(metric, str) or not metric.strip()
        for metric in guardrail_metrics
    ):
        raise ValidationError(
            "dataset.guardrail_metrics must contain non-empty strings"
        )
    if len(set(guardrail_metrics)) != len(guardrail_metrics):
        raise ValidationError("dataset.guardrail_metrics must not contain duplicates")
    required_guardrail_metrics = REQUIRED_GUARDRAILS | {
        "Recall@10",
        "token_estimate",
        "cost_estimate",
    }
    missing_guardrail_metrics = required_guardrail_metrics - set(guardrail_metrics)
    if missing_guardrail_metrics:
        raise ValidationError(
            f"dataset.guardrail_metrics missing {sorted(missing_guardrail_metrics)}"
        )

    provenance = dataset.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValidationError("dataset.provenance must be an object")
    _require_exact_keys(provenance, REQUIRED_PROVENANCE_FIELDS, "dataset.provenance")
    if provenance.get("raw_user_logs_included") is not False:
        raise ValidationError("dataset provenance must exclude raw user logs")
    if provenance.get("type") != "synthetic_and_public_seed":
        raise ValidationError(
            "dataset provenance.type must be synthetic_and_public_seed"
        )
    splits = dataset.get("splits")
    if not isinstance(splits, Mapping):
        raise ValidationError("dataset.splits must be an object")
    _require_exact_keys(splits, REQUIRED_SPLIT_FIELDS, "dataset.splits")
    expected = {"train": 0.6, "selection": 0.2, "test": 0.2}
    if {key: splits.get(key) for key in expected} != expected:
        raise ValidationError("dataset.splits must be train=.6 selection=.2 test=.2")

    queries = dataset.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValidationError("dataset.queries must be a non-empty list")

    seen_query_ids: set[str] = set()
    seen_groups: dict[str, str] = {}
    split_counts = {"train": 0, "selection": 0, "test": 0}
    intents_by_split: dict[str, set[str]] = {
        "train": set(),
        "selection": set(),
        "test": set(),
    }
    for index, query in enumerate(queries):
        if not isinstance(query, Mapping):
            raise ValidationError(f"queries[{index}] must be an object")
        _require_exact_keys(query, REQUIRED_QUERY_FIELDS, f"queries[{index}]")
        query_id = _require_non_empty_string(
            query["query_id"], f"queries[{index}].query_id"
        )
        _reject_private_text(query_id, f"queries[{index}].query_id")
        _reject_private_text(
            _require_non_empty_string(
                query["query_text"], f"queries[{index}].query_text"
            ),
            f"queries[{index}].query_text",
        )
        if query_id in seen_query_ids:
            raise ValidationError(f"queries[{index}].query_id must be unique")
        seen_query_ids.add(query_id)

        split = query["split"]
        if split not in split_counts:
            raise ValidationError(
                f"queries[{index}].split must be train/selection/test"
            )
        split_counts[split] += 1

        group_id = _require_non_empty_string(
            query["group_id"], f"queries[{index}].group_id"
        )
        _reject_private_text(group_id, f"queries[{index}].group_id")
        intent = _require_non_empty_string(query["intent"], f"queries[{index}].intent")
        _reject_private_text(intent, f"queries[{index}].intent")
        intents_by_split[split].add(intent)
        for enum_key, allowed_values in _ALLOWED_QUERY_ENUMS.items():
            value = _require_non_empty_string(
                query[enum_key], f"queries[{index}].{enum_key}"
            )
            _reject_private_text(value, f"queries[{index}].{enum_key}")
            if value not in allowed_values:
                raise ValidationError(
                    f"queries[{index}].{enum_key} must be one of {sorted(allowed_values)}"
                )

        previous = seen_groups.setdefault(group_id, split)
        if previous != split:
            raise ValidationError(f"group_id {group_id!r} leaks across splits")

        labels = query["labels"]
        if not isinstance(labels, Mapping):
            raise ValidationError(f"queries[{index}].labels must be an object")
        _require_exact_keys(labels, REQUIRED_LABEL_FIELDS, f"queries[{index}].labels")
        must_include = labels.get("must_include")
        if not must_include:
            raise ValidationError(
                f"queries[{index}].labels.must_include must be non-empty"
            )
        for label_key in REQUIRED_LABEL_FIELDS:
            label_value = labels[label_key]
            if not isinstance(label_value, list):
                raise ValidationError(
                    f"queries[{index}].labels.{label_key} must be a list"
                )
            if any(
                not isinstance(label, str) or not label.strip() for label in label_value
            ):
                raise ValidationError(
                    f"queries[{index}].labels.{label_key} must contain non-empty strings"
                )

    if any(count == 0 for count in split_counts.values()):
        raise ValidationError(
            f"all splits must have at least one query: {split_counts}"
        )
    if split_counts["selection"] < 2:
        raise ValidationError(
            "selection split must include at least two queries for live SkillOpt gate stability"
        )
    required_selection_intents = {"author_search", "method_search"}
    missing_selection_intents = (
        required_selection_intents - intents_by_split["selection"]
    )
    if missing_selection_intents:
        raise ValidationError(
            f"selection split missing required intents: {sorted(missing_selection_intents)}"
        )
    if dataset_hash != canonical_self_hash(dataset, "dataset_hash"):
        raise ValidationError(
            "dataset.dataset_hash does not match canonical dataset content"
        )


def validate_execution_control(control: Mapping[str, Any]) -> None:
    """Validate the execution-control matrix for comparable rollouts."""
    _require_exact_keys(control, REQUIRED_CONTROL_FIELDS, "execution_control")
    _reject_private_strings(control, "execution_control")
    control_hash = _require_sha256_digest(
        control.get("control_hash"), "execution_control.control_hash"
    )
    if control.get("cache_policy") != "disabled_or_cold_per_rollout":
        raise ValidationError(
            "execution_control.cache_policy must be disabled_or_cold_per_rollout"
        )
    if control.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError(f"execution_control.scope must be {V1_ALLOWED_SCOPE}")
    if control.get("fast_mode") is not False:
        raise ValidationError("v1 execution control requires fast_mode=false")
    if control.get("use_llm_search") is not False:
        raise ValidationError("v1 execution control requires use_llm_search=false")

    confidence_gate = control.get("query_analyzer_confidence_gate")
    if not isinstance(confidence_gate, Mapping):
        raise ValidationError("query_analyzer_confidence_gate must be an object")
    _require_exact_policy(
        confidence_gate, _ALLOWED_CONFIDENCE_GATE, "query_analyzer_confidence_gate"
    )

    overlap_gate = control.get("improved_query_overlap_gate")
    if not isinstance(overlap_gate, Mapping):
        raise ValidationError("improved_query_overlap_gate must be an object")
    _require_exact_policy(
        overlap_gate, _ALLOWED_OVERLAP_GATE, "improved_query_overlap_gate"
    )

    budget = control.get("budget_policy")
    if not isinstance(budget, Mapping):
        raise ValidationError("budget_policy must be an object")
    _require_exact_policy(budget, _ALLOWED_BUDGET_POLICY, "budget_policy")

    rollout_gate = control.get("controlled_rollout_gate")
    if not isinstance(rollout_gate, Mapping):
        raise ValidationError("controlled_rollout_gate must be an object")
    _require_exact_policy(
        rollout_gate, _ALLOWED_CONTROLLED_ROLLOUT_GATE, "controlled_rollout_gate"
    )

    hyde = control.get("hyde_policy")
    if not isinstance(hyde, Mapping):
        raise ValidationError("hyde_policy must be an object")
    _require_exact_policy(hyde, _ALLOWED_HYDE_POLICY, "hyde_policy")

    relevance = control.get("relevance_filter_policy")
    if not isinstance(relevance, Mapping):
        raise ValidationError("relevance_filter_policy must be an object")
    _require_exact_policy(
        relevance, _ALLOWED_RELEVANCE_FILTER, "relevance_filter_policy"
    )

    metadata = control.get("required_rollout_metadata")
    if not isinstance(metadata, Sequence) or isinstance(metadata, (str, bytes)):
        raise ValidationError("required_rollout_metadata must be a list")
    if any(not isinstance(item, str) or not item.strip() for item in metadata):
        raise ValidationError(
            "required_rollout_metadata must contain non-empty strings"
        )
    if len(set(metadata)) != len(metadata):
        raise ValidationError("required_rollout_metadata must not contain duplicates")
    missing = _REQUIRED_ROLLOUT_METADATA - set(metadata)
    if missing:
        raise ValidationError(f"required_rollout_metadata missing {sorted(missing)}")
    extra = set(metadata) - _REQUIRED_ROLLOUT_METADATA
    if extra:
        raise ValidationError(
            f"required_rollout_metadata contains forbidden entries: {sorted(extra)}"
        )
    if control_hash != canonical_self_hash(control, "control_hash"):
        raise ValidationError(
            "execution_control.control_hash does not match canonical control content"
        )


def validate_candidate_artifact(
    artifact: Mapping[str, Any],
    *,
    dataset: Mapping[str, Any] | None = None,
    execution_control: Mapping[str, Any] | None = None,
) -> None:
    """Validate a SkillOpt candidate artifact and optional cross-artifact hashes."""
    _require_keys(artifact, REQUIRED_ARTIFACT_FIELDS, "candidate_artifact")
    if artifact.get("version") != CANDIDATE_ARTIFACT_VERSION:
        raise ValidationError(
            "candidate_artifact.version is invalid; legacy bytes cannot be relabelled as higher evidence"
        )
    skill_hash = _require_sha256_digest(
        artifact.get("skill_hash"), "candidate_artifact.skill_hash"
    )
    baseline_hash = _require_sha256_digest(
        artifact.get("baseline_hash"), "candidate_artifact.baseline_hash"
    )
    _require_non_empty_string(
        artifact.get("dataset_hash"), "candidate_artifact.dataset_hash"
    )
    _require_non_empty_string(
        artifact.get("execution_control_hash"),
        "candidate_artifact.execution_control_hash",
    )
    _require_iso_datetime(artifact.get("created_at"), "candidate_artifact.created_at")
    if skill_hash == baseline_hash:
        raise ValidationError(
            "candidate_artifact.skill_hash must differ from baseline_hash"
        )
    if artifact.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError(f"candidate_artifact.scope must be {V1_ALLOWED_SCOPE}")

    snapshot = artifact.get("metric_snapshot")
    if not isinstance(snapshot, Mapping):
        raise ValidationError("candidate_artifact.metric_snapshot must be an object")
    if snapshot.get("primary_metric") != PRIMARY_METRIC:
        raise ValidationError(
            "candidate_artifact.metric_snapshot.primary_metric must be nDCG@10"
        )
    baseline = snapshot.get("baseline")
    candidate = snapshot.get("candidate")
    baseline = _require_finite_number(
        baseline, "candidate_artifact.metric_snapshot.baseline"
    )
    candidate = _require_finite_number(
        candidate, "candidate_artifact.metric_snapshot.candidate"
    )
    _require_metric_range(baseline, "candidate_artifact.metric_snapshot.baseline")
    _require_metric_range(candidate, "candidate_artifact.metric_snapshot.candidate")
    if candidate < baseline:
        raise ValidationError(
            "candidate_artifact candidate metric must not regress below baseline"
        )

    guardrails = snapshot.get("guardrails")
    if not isinstance(guardrails, Mapping):
        raise ValidationError(
            "candidate_artifact.metric_snapshot.guardrails is required"
        )
    required_guardrails = (
        set(dataset["guardrail_metrics"])
        if dataset is not None
        else REQUIRED_GUARDRAILS
    )
    missing_guardrails = required_guardrails - set(guardrails)
    if missing_guardrails:
        raise ValidationError(
            f"candidate_artifact guardrails missing {sorted(missing_guardrails)}"
        )
    for name in required_guardrails:
        value = _require_finite_number(
            guardrails[name], f"candidate_artifact guardrail {name}"
        )
        if name == "p95_latency_ms":
            if value < 0:
                raise ValidationError(
                    f"candidate_artifact guardrail {name} must be non-negative"
                )
            if value > _GUARDRAIL_LIMITS["p95_latency_ms"]:
                raise ValidationError(
                    f"candidate_artifact guardrail {name} exceeds v1 threshold"
                )
        elif name.endswith("_estimate"):
            if value < 0:
                raise ValidationError(
                    f"candidate_artifact guardrail {name} must be non-negative"
                )
        else:
            _require_metric_range(value, f"candidate_artifact guardrail {name}")
            if name in _GUARDRAIL_LIMITS and value > _GUARDRAIL_LIMITS[name]:
                raise ValidationError(
                    f"candidate_artifact guardrail {name} exceeds v1 threshold"
                )

    rollout_metadata = artifact.get("rollout_metadata")
    if not isinstance(rollout_metadata, Mapping):
        raise ValidationError("candidate_artifact.rollout_metadata must be an object")
    missing_rollout_metadata = _REQUIRED_ROLLOUT_METADATA - set(rollout_metadata)
    if missing_rollout_metadata:
        raise ValidationError(
            f"candidate_artifact.rollout_metadata missing {sorted(missing_rollout_metadata)}"
        )
    if rollout_metadata.get("skill_hash") != artifact.get("skill_hash"):
        raise ValidationError(
            "candidate_artifact.rollout_metadata.skill_hash must match skill_hash"
        )
    if rollout_metadata.get("dataset_hash") != artifact.get("dataset_hash"):
        raise ValidationError(
            "candidate_artifact.rollout_metadata.dataset_hash must match dataset_hash"
        )
    if rollout_metadata.get("execution_control_hash") != artifact.get(
        "execution_control_hash"
    ):
        raise ValidationError(
            "candidate_artifact.rollout_metadata.execution_control_hash must match execution_control_hash"
        )
    if rollout_metadata.get("hyde_enabled") is not False:
        raise ValidationError(
            "candidate_artifact.rollout_metadata.hyde_enabled must be false"
        )
    if rollout_metadata.get("cache_status") != "disabled_or_cold_per_rollout":
        raise ValidationError(
            "candidate_artifact.rollout_metadata.cache_status must match execution control"
        )
    if rollout_metadata.get("relevance_scorer_path") != "production_equivalent":
        raise ValidationError(
            "candidate_artifact.rollout_metadata.relevance_scorer_path must be production_equivalent"
        )
    if rollout_metadata.get("budget_branch") != "generous_fixed_offline_budget":
        raise ValidationError(
            "candidate_artifact.rollout_metadata.budget_branch must match execution control"
        )
    if not isinstance(
        rollout_metadata.get("query_analysis_confidence"), int | float
    ) or isinstance(rollout_metadata.get("query_analysis_confidence"), bool):
        raise ValidationError(
            "candidate_artifact.rollout_metadata.query_analysis_confidence must be numeric"
        )
    query_analysis_confidence = float(rollout_metadata["query_analysis_confidence"])
    _require_metric_range(
        query_analysis_confidence,
        "candidate_artifact.rollout_metadata.query_analysis_confidence",
    )
    if query_analysis_confidence < _MINIMUM_QUERY_ANALYSIS_CONFIDENCE:
        raise ValidationError(
            "candidate_artifact.rollout_metadata.query_analysis_confidence below execution-control minimum"
        )

    rollback_to = artifact.get("rollback_to")
    if not isinstance(rollback_to, Mapping) or not rollback_to.get("skill_hash"):
        raise ValidationError("candidate_artifact.rollback_to.skill_hash is required")
    if rollback_to.get("skill_hash") != artifact.get("baseline_hash"):
        raise ValidationError(
            "candidate_artifact.rollback_to.skill_hash must match baseline_hash"
        )

    if dataset is not None and artifact.get("dataset_hash") != dataset.get(
        "dataset_hash"
    ):
        raise ValidationError("candidate_artifact.dataset_hash does not match dataset")
    if execution_control is not None and artifact.get(
        "execution_control_hash"
    ) != execution_control.get("control_hash"):
        raise ValidationError(
            "candidate_artifact.execution_control_hash does not match control"
        )


def validate_rollback_record(
    record: Mapping[str, Any],
    *,
    artifact: Mapping[str, Any] | None = None,
) -> None:
    """Validate rollback metadata for a rejected SkillOpt candidate."""
    _require_keys(record, REQUIRED_ROLLBACK_FIELDS, "rollback_record")
    _require_non_empty_string(record.get("rollback_id"), "rollback_record.rollback_id")
    _require_sha256_digest(
        record.get("from_candidate_hash"), "rollback_record.from_candidate_hash"
    )
    _require_sha256_digest(
        record.get("rollback_to_skill_hash"), "rollback_record.rollback_to_skill_hash"
    )
    reason = _require_non_empty_string(record.get("reason"), "rollback_record.reason")
    triggered_by = _require_non_empty_string(
        record.get("triggered_by"), "rollback_record.triggered_by"
    )
    if reason not in {
        "guardrail_regression",
        "metric_regression",
        "scope_violation",
        "manual_rejection",
    }:
        raise ValidationError("rollback_record.reason must be a known rollback reason")
    if triggered_by not in {"offline_eval_gate", "shadow_eval_gate", "operator"}:
        raise ValidationError(
            "rollback_record.triggered_by must be a known rollback trigger"
        )
    if artifact is not None:
        if record.get("from_candidate_hash") != artifact.get("skill_hash"):
            raise ValidationError(
                "rollback_record.from_candidate_hash does not match candidate"
            )
        if record.get("rollback_to_skill_hash") != artifact.get("baseline_hash"):
            raise ValidationError(
                "rollback_record.rollback_to_skill_hash does not match baseline"
            )
    if record.get("feature_flag_after") is not False:
        raise ValidationError("rollback_record.feature_flag_after must be false")
    if record.get("quarantined_candidate") is not True:
        raise ValidationError("rollback_record.quarantined_candidate must be true")
    if record.get("api_contract_unchanged") is not True:
        raise ValidationError("rollback_record.api_contract_unchanged must be true")


def _require_keys(obj: Mapping[str, Any], required: set[str], label: str) -> None:
    missing = required - set(obj)
    if missing:
        raise ValidationError(f"{label} missing required keys: {sorted(missing)}")


def _require_exact_keys(obj: Mapping[str, Any], required: set[str], label: str) -> None:
    _require_keys(obj, required, label)
    extra = set(obj) - required
    if extra:
        raise ValidationError(f"{label} contains forbidden keys: {sorted(extra)}")


def _require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a non-empty string")
    return value


def _require_iso_datetime(value: Any, label: str) -> None:
    text = _require_non_empty_string(value, label)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{label} must be an ISO-8601 timestamp") from exc


def _require_finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError(f"{label} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValidationError(f"{label} must be finite")
    return numeric


def _require_metric_range(value: float, label: str) -> None:
    if not 0 <= value <= 1:
        raise ValidationError(f"{label} must be between 0 and 1")


def _reject_private_text(value: str, label: str) -> None:
    if any(pattern.search(value) for pattern in _PII_PATTERNS):
        raise ValidationError(f"{label} contains private or raw-log text")


def _reject_private_strings(value: Any, label: str) -> None:
    if isinstance(value, str):
        _reject_private_text(value, label)
    elif isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_private_strings(nested, f"{label}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, nested in enumerate(value):
            _reject_private_strings(nested, f"{label}[{index}]")


def _require_exact_policy(
    policy: Mapping[str, Any], expected: Mapping[str, Any], label: str
) -> None:
    extra = set(policy) - set(expected)
    missing = set(expected) - set(policy)
    if missing:
        raise ValidationError(f"{label} missing required keys: {sorted(missing)}")
    if extra:
        raise ValidationError(f"{label} contains v1-forbidden keys: {sorted(extra)}")
    for key, expected_value in expected.items():
        if policy.get(key) != expected_value:
            raise ValidationError(f"{label}.{key} must remain {expected_value}")


def _require_sha256_digest(value: Any, label: str) -> str:
    text = _require_non_empty_string(value, label)
    prefix = "sha256:"
    digest = text[len(prefix) :] if text.startswith(prefix) else ""
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValidationError(f"{label} must be a sha256 content digest")
    return text
