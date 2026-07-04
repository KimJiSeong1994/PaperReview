"""Export an approved SkillOpt best_skill.md for runtime policy gating."""
from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .retrieval_eval import assert_candidate_beats_baseline, validate_retrieval_evaluation_record
from .skillopt_adapter import canonical_file_hash
from .skillopt_materializer import validate_skillopt_materialization_manifest
from .skillopt_contract import V1_ALLOWED_SCOPE, ValidationError, load_json, validate_dataset_contract, validate_execution_control
from .query_analyzer_pilot import load_baseline_skill


def export_approved_skillopt_policy(
    *,
    best_skill_path: str | Path,
    output_dir: str | Path,
    dataset_path: str | Path,
    control_path: str | Path,
    baseline_skill_path: str | Path,
    baseline_eval: Mapping[str, Any],
    candidate_eval: Mapping[str, Any],
    materialization_manifest_path: str | Path,
    minimum_ndcg_delta: float = 0.0,
) -> dict[str, Any]:
    """Validate and export a SkillOpt best skill as a runtime-loadable policy."""
    dataset = load_json(dataset_path)
    control = load_json(control_path)
    validate_dataset_contract(dataset)
    validate_execution_control(control)
    if control.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("approved policy export requires v1 QueryAnalyzer scope")
    load_baseline_skill(baseline_skill_path)
    validate_runtime_policy_text(Path(best_skill_path).read_text(encoding="utf-8"))
    best_skill_hash = canonical_file_hash(best_skill_path)
    validate_retrieval_evaluation_record(baseline_eval)
    validate_retrieval_evaluation_record(candidate_eval)
    _validate_eval_record_matches_dataset(baseline_eval, dataset)
    _validate_eval_record_matches_dataset(candidate_eval, dataset)
    _validate_candidate_eval_matches_skill(candidate_eval, best_skill_hash)
    manifest = load_json(materialization_manifest_path)
    validate_skillopt_materialization_manifest(manifest)
    _validate_manifest_matches_inputs(
        manifest,
        dataset=dataset,
        control=control,
        dataset_path=dataset_path,
        control_path=control_path,
        baseline_skill_path=baseline_skill_path,
    )
    assert_candidate_beats_baseline(
        baseline_record=baseline_eval,
        candidate_record=candidate_eval,
        minimum_delta=minimum_ndcg_delta,
    )
    selection_gate = _build_selection_gate_evidence(dataset=dataset, candidate_eval=candidate_eval)
    holdout_gate = _build_holdout_gate_evidence(dataset=dataset, candidate_eval=candidate_eval)

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    exported_skill = output / "best_skill.md"
    shutil.copyfile(best_skill_path, exported_skill)
    exported_skill_hash = canonical_file_hash(exported_skill)
    if exported_skill_hash != best_skill_hash:
        raise ValidationError("approved policy export skill hash changed during copy")

    artifact = {
        "version": "approved-skillopt-policy-v0",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "scope": V1_ALLOWED_SCOPE,
        "skill_hash": exported_skill_hash,
        "baseline_hash": canonical_file_hash(baseline_skill_path),
        "dataset_hash": dataset["dataset_hash"],
        "execution_control_hash": control["control_hash"],
        "runtime_policy_path": str(exported_skill.resolve()),
        "materialization_manifest_hash": canonical_file_hash(materialization_manifest_path),
        "runtime_env": {
            "SKILLOPT_SEARCH_POLICY_ENABLED": "true",
            "SKILLOPT_SEARCH_POLICY_PATH": str(exported_skill.resolve()),
            "SKILLOPT_SEARCH_POLICY_HASH": exported_skill_hash,
            "SKILLOPT_SEARCH_POLICY_SCOPE": V1_ALLOWED_SCOPE,
        },
        "metric_snapshot": {
            "primary_metric": "nDCG@10",
            "evaluated_skill_hash": best_skill_hash,
            "baseline": float(baseline_eval["nDCG@10"]),
            "candidate": float(candidate_eval["nDCG@10"]),
            "baseline_eval_hash": _mapping_hash(baseline_eval),
            "candidate_eval_hash": _mapping_hash(candidate_eval),
            "guardrails": {
                "baseline": _guardrail_snapshot(baseline_eval),
                "candidate": _guardrail_snapshot(candidate_eval),
            },
        },
        "selection_gate": selection_gate,
        "holdout_gate": holdout_gate,
        "rollback_to": {
            "version": "baseline-v0",
            "skill_hash": canonical_file_hash(baseline_skill_path),
        },
    }
    validate_approved_policy_artifact(artifact)
    artifact_path = output / "approved_policy_artifact.json"
    artifact_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    env_path = output / "runtime_env.sh"
    env_path.write_text(_runtime_env_shell(artifact["runtime_env"]), encoding="utf-8")
    return {**artifact, "artifact_path": str(artifact_path), "runtime_env_path": str(env_path)}


def _validate_eval_record_matches_dataset(record: Mapping[str, Any], dataset: Mapping[str, Any]) -> None:
    if record.get("dataset_hash") != dataset.get("dataset_hash"):
        raise ValidationError("retrieval evaluation dataset_hash does not match dataset")
    expected_ids = [str(query["query_id"]) for query in dataset["queries"]]
    per_query = record.get("per_query")
    if not isinstance(per_query, list):
        raise ValidationError("retrieval evaluation per_query must be a list")
    actual_ids = [str(item.get("query_id")) for item in per_query if isinstance(item, Mapping)]
    if actual_ids != expected_ids:
        raise ValidationError("retrieval evaluation per_query ids must match dataset query order")
    if int(record.get("query_count", -1)) != len(expected_ids):
        raise ValidationError("retrieval evaluation query_count must match dataset")


def _validate_candidate_eval_matches_skill(candidate_eval: Mapping[str, Any], best_skill_hash: str) -> None:
    evaluated_skill_hash = candidate_eval.get("evaluated_skill_hash")
    if evaluated_skill_hash != best_skill_hash:
        raise ValidationError("candidate evaluation evaluated_skill_hash must match best_skill.md hash")


def _validate_manifest_matches_inputs(
    manifest: Mapping[str, Any],
    *,
    dataset: Mapping[str, Any],
    control: Mapping[str, Any],
    dataset_path: str | Path,
    control_path: str | Path,
    baseline_skill_path: str | Path,
) -> None:
    if manifest.get("dataset_hash") != dataset.get("dataset_hash"):
        raise ValidationError("materialization manifest dataset_hash does not match dataset")
    if manifest.get("execution_control_hash") != control.get("control_hash"):
        raise ValidationError("materialization manifest execution_control_hash does not match control")
    expected_hashes = {
        "dataset_file": canonical_file_hash(dataset_path),
        "control_file": canonical_file_hash(control_path),
        "baseline_skill_file": canonical_file_hash(baseline_skill_path),
    }
    if dict(manifest.get("source_hashes", {})) != expected_hashes:
        raise ValidationError("materialization manifest source_hashes do not match export inputs")


def _guardrail_snapshot(record: Mapping[str, Any]) -> dict[str, float]:
    return {
        "MRR@10": float(record["MRR@10"]),
        "Recall@5": float(record["Recall@5"]),
        "Recall@10": float(record["Recall@10"]),
        "wrong_paper_handoff_rate": float(record["wrong_paper_handoff_rate"]),
        "p95_latency_ms": float(record["p95_latency_ms"]),
        "token_estimate": float(record["token_estimate"]),
        "cost_estimate": float(record["cost_estimate"]),
    }


def _build_selection_gate_evidence(*, dataset: Mapping[str, Any], candidate_eval: Mapping[str, Any]) -> dict[str, Any]:
    required_intents = {"author_search", "method_search"}
    selection_queries = [
        query
        for query in dataset["queries"]
        if query["split"] == "selection" and query["intent"] in required_intents
    ]
    intents = {str(query["intent"]) for query in selection_queries}
    missing = required_intents - intents
    if missing:
        raise ValidationError(f"selection gate missing required intents: {sorted(missing)}")
    rows_by_id = {
        str(row["query_id"]): row
        for row in candidate_eval["per_query"]
        if isinstance(row, Mapping) and isinstance(row.get("query_id"), str)
    }
    per_query = []
    passed_query_ids = []
    for query in selection_queries:
        query_id = str(query["query_id"])
        row = rows_by_id.get(query_id)
        if not isinstance(row, Mapping):
            raise ValidationError(f"selection gate missing candidate eval for {query_id}")
        ndcg = float(row["ndcg_at_10"])
        recall = float(row["recall_at_10"])
        passed = ndcg > 0.0 and recall > 0.0
        per_query.append(
            {
                "query_id": query_id,
                "intent": str(query["intent"]),
                "must_include": list(query["labels"]["must_include"]),
                "ndcg_at_10": ndcg,
                "recall_at_10": recall,
                "passed": passed,
            }
        )
        if passed:
            passed_query_ids.append(query_id)
    failed = [row for row in per_query if not row["passed"]]
    if failed:
        failed_summary = ", ".join(f"{row['query_id']}({row['intent']})" for row in failed)
        raise ValidationError(f"selection gate failed canonical anchor recall for: {failed_summary}")
    return {
        "status": "passed",
        "required_intents": sorted(required_intents),
        "passed_query_ids": passed_query_ids,
        "per_query": per_query,
    }


def _build_holdout_gate_evidence(*, dataset: Mapping[str, Any], candidate_eval: Mapping[str, Any]) -> dict[str, Any]:
    test_queries = [query for query in dataset["queries"] if query["split"] == "test"]
    if not test_queries:
        raise ValidationError("holdout gate requires at least one test query")
    rows_by_id = {
        str(row["query_id"]): row
        for row in candidate_eval["per_query"]
        if isinstance(row, Mapping) and isinstance(row.get("query_id"), str)
    }
    per_query = []
    passed_query_ids = []
    for query in test_queries:
        query_id = str(query["query_id"])
        row = rows_by_id.get(query_id)
        if not isinstance(row, Mapping):
            raise ValidationError(f"holdout gate missing candidate eval for {query_id}")
        ndcg = float(row["ndcg_at_10"])
        recall = float(row["recall_at_10"])
        passed = ndcg > 0.0 and recall > 0.0
        per_query.append(
            {
                "query_id": query_id,
                "intent": str(query["intent"]),
                "must_include": list(query["labels"]["must_include"]),
                "ndcg_at_10": ndcg,
                "recall_at_10": recall,
                "passed": passed,
            }
        )
        if passed:
            passed_query_ids.append(query_id)
    failed = [row for row in per_query if not row["passed"]]
    if failed:
        failed_summary = ", ".join(f"{row['query_id']}({row['intent']})" for row in failed)
        raise ValidationError(f"holdout gate failed canonical anchor recall for: {failed_summary}")
    return {
        "status": "passed",
        "split": "test",
        "passed_query_ids": passed_query_ids,
        "per_query": per_query,
    }


def validate_runtime_policy_text(text: str) -> None:
    """Validate that a best_skill.md can pass runtime SkillOpt policy gates."""
    required = (
        "QueryAnalyzer standard search path",
        "Do not enable `use_llm_search`",
        "Do not enable HyDE",
        "Do not promote RelevanceFilter",
    )
    missing = [phrase for phrase in required if phrase not in text]
    if missing:
        raise ValidationError(f"approved SkillOpt policy missing runtime safety phrases: {missing}")
    if len(text.encode("utf-8")) > 16_384:
        raise ValidationError("approved SkillOpt policy exceeds runtime policy size limit")


def validate_approved_policy_artifact(artifact: Mapping[str, Any]) -> None:
    required = {
        "version",
        "created_at",
        "scope",
        "skill_hash",
        "baseline_hash",
        "dataset_hash",
        "execution_control_hash",
        "runtime_policy_path",
        "materialization_manifest_hash",
        "runtime_env",
        "metric_snapshot",
        "selection_gate",
        "holdout_gate",
        "rollback_to",
    }
    missing = required - set(artifact)
    if missing:
        raise ValidationError(f"approved_policy_artifact missing required keys: {sorted(missing)}")
    if artifact.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("approved_policy_artifact.scope is invalid")
    _require_iso_datetime(artifact.get("created_at"), "approved_policy_artifact.created_at")
    if artifact.get("skill_hash") == artifact.get("baseline_hash"):
        raise ValidationError("approved_policy_artifact.skill_hash must differ from baseline_hash")
    env = artifact.get("runtime_env")
    if not isinstance(env, Mapping):
        raise ValidationError("approved_policy_artifact.runtime_env must be an object")
    if env.get("SKILLOPT_SEARCH_POLICY_HASH") != artifact.get("skill_hash"):
        raise ValidationError("approved_policy_artifact runtime hash must match skill_hash")
    metrics = artifact.get("metric_snapshot")
    if not isinstance(metrics, Mapping):
        raise ValidationError("approved_policy_artifact.metric_snapshot must be an object")
    if metrics.get("primary_metric") != "nDCG@10":
        raise ValidationError("approved_policy_artifact primary_metric must be nDCG@10")
    if metrics.get("evaluated_skill_hash") != artifact.get("skill_hash"):
        raise ValidationError("approved_policy_artifact evaluated_skill_hash must match skill_hash")
    _require_sha256_text(metrics.get("baseline_eval_hash"), "approved_policy_artifact.metric_snapshot.baseline_eval_hash")
    _require_sha256_text(metrics.get("candidate_eval_hash"), "approved_policy_artifact.metric_snapshot.candidate_eval_hash")
    baseline_metric = _artifact_metric(metrics.get("baseline"), "metric_snapshot.baseline", maximum=1.0)
    candidate_metric = _artifact_metric(metrics.get("candidate"), "metric_snapshot.candidate", maximum=1.0)
    if candidate_metric < baseline_metric:
        raise ValidationError("approved_policy_artifact candidate metric must not regress")
    _validate_artifact_guardrails(metrics.get("guardrails"))
    _validate_selection_gate_artifact(artifact.get("selection_gate"))
    _validate_holdout_gate_artifact(artifact.get("holdout_gate"))
    rollback = artifact.get("rollback_to")
    if not isinstance(rollback, Mapping) or rollback.get("skill_hash") != artifact.get("baseline_hash"):
        raise ValidationError("approved_policy_artifact rollback hash must match baseline_hash")


def _validate_selection_gate_artifact(selection_gate: Any) -> None:
    if not isinstance(selection_gate, Mapping):
        raise ValidationError("approved_policy_artifact.selection_gate must be an object")
    if selection_gate.get("status") != "passed":
        raise ValidationError("approved_policy_artifact.selection_gate must be passed")
    required_intents = selection_gate.get("required_intents")
    if set(required_intents or []) != {"author_search", "method_search"}:
        raise ValidationError("approved_policy_artifact.selection_gate required_intents is invalid")
    passed_query_ids = selection_gate.get("passed_query_ids")
    if not isinstance(passed_query_ids, list) or any(not isinstance(query_id, str) or not query_id for query_id in passed_query_ids):
        raise ValidationError("approved_policy_artifact.selection_gate passed_query_ids is invalid")
    per_query = selection_gate.get("per_query")
    if not isinstance(per_query, list) or len(per_query) < 2:
        raise ValidationError("approved_policy_artifact.selection_gate per_query is incomplete")
    intents = set()
    seen_query_ids = set()
    actual_passed_query_ids = []
    for row in per_query:
        if not isinstance(row, Mapping):
            raise ValidationError("approved_policy_artifact.selection_gate per_query entries must be objects")
        query_id = row.get("query_id")
        if not isinstance(query_id, str) or not query_id:
            raise ValidationError("approved_policy_artifact.selection_gate query_id is required")
        if query_id in seen_query_ids:
            raise ValidationError("approved_policy_artifact.selection_gate duplicate query_id")
        seen_query_ids.add(query_id)
        intent = str(row.get("intent") or "")
        intents.add(intent)
        must_include = row.get("must_include")
        if not isinstance(must_include, list) or not must_include or any(not isinstance(value, str) or not value.strip() for value in must_include):
            raise ValidationError("approved_policy_artifact.selection_gate must_include is required")
        if row.get("passed") is not True:
            raise ValidationError("approved_policy_artifact.selection_gate per_query must be passed")
        ndcg = _artifact_metric(row.get("ndcg_at_10"), f"selection_gate.{query_id}.ndcg_at_10", maximum=1.0)
        if ndcg <= 0.0:
            raise ValidationError("approved_policy_artifact.selection_gate ndcg_at_10 must be greater than zero")
        recall = _artifact_metric(row.get("recall_at_10"), f"selection_gate.{query_id}.recall_at_10", maximum=1.0)
        if recall <= 0.0:
            raise ValidationError("approved_policy_artifact.selection_gate recall_at_10 must be greater than zero")
        actual_passed_query_ids.append(query_id)
    if not {"author_search", "method_search"} <= intents:
        raise ValidationError("approved_policy_artifact.selection_gate missing required intent evidence")
    if passed_query_ids != actual_passed_query_ids:
        raise ValidationError("approved_policy_artifact.selection_gate passed_query_ids must match passed per_query ids")


def _validate_holdout_gate_artifact(holdout_gate: Any) -> None:
    if not isinstance(holdout_gate, Mapping):
        raise ValidationError("approved_policy_artifact.holdout_gate must be an object")
    if holdout_gate.get("status") != "passed" or holdout_gate.get("split") != "test":
        raise ValidationError("approved_policy_artifact.holdout_gate must be passed test evidence")
    passed_query_ids = holdout_gate.get("passed_query_ids")
    if not isinstance(passed_query_ids, list) or any(not isinstance(query_id, str) or not query_id for query_id in passed_query_ids):
        raise ValidationError("approved_policy_artifact.holdout_gate passed_query_ids is invalid")
    per_query = holdout_gate.get("per_query")
    if not isinstance(per_query, list) or not per_query:
        raise ValidationError("approved_policy_artifact.holdout_gate per_query is incomplete")
    seen_query_ids = set()
    actual_passed_query_ids = []
    for row in per_query:
        if not isinstance(row, Mapping):
            raise ValidationError("approved_policy_artifact.holdout_gate per_query entries must be objects")
        query_id = row.get("query_id")
        if not isinstance(query_id, str) or not query_id:
            raise ValidationError("approved_policy_artifact.holdout_gate query_id is required")
        if query_id in seen_query_ids:
            raise ValidationError("approved_policy_artifact.holdout_gate duplicate query_id")
        seen_query_ids.add(query_id)
        must_include = row.get("must_include")
        if not isinstance(must_include, list) or not must_include or any(not isinstance(value, str) or not value.strip() for value in must_include):
            raise ValidationError("approved_policy_artifact.holdout_gate must_include is required")
        if row.get("passed") is not True:
            raise ValidationError("approved_policy_artifact.holdout_gate per_query must be passed")
        ndcg = _artifact_metric(row.get("ndcg_at_10"), f"holdout_gate.{query_id}.ndcg_at_10", maximum=1.0)
        recall = _artifact_metric(row.get("recall_at_10"), f"holdout_gate.{query_id}.recall_at_10", maximum=1.0)
        if ndcg <= 0.0 or recall <= 0.0:
            raise ValidationError("approved_policy_artifact.holdout_gate metrics must be greater than zero")
        actual_passed_query_ids.append(query_id)
    if passed_query_ids != actual_passed_query_ids:
        raise ValidationError("approved_policy_artifact.holdout_gate passed_query_ids must match passed per_query ids")


def _validate_artifact_guardrails(guardrails: Any) -> None:
    if not isinstance(guardrails, Mapping):
        raise ValidationError("approved_policy_artifact.guardrails must be an object")
    baseline = guardrails.get("baseline")
    candidate = guardrails.get("candidate")
    if not isinstance(baseline, Mapping) or not isinstance(candidate, Mapping):
        raise ValidationError("approved_policy_artifact.guardrails must include baseline and candidate")
    for metric in ("MRR@10", "Recall@5", "Recall@10", "wrong_paper_handoff_rate"):
        _artifact_metric(baseline.get(metric), f"guardrails.baseline.{metric}", maximum=1.0)
        _artifact_metric(candidate.get(metric), f"guardrails.candidate.{metric}", maximum=1.0)
    for metric in ("p95_latency_ms", "token_estimate", "cost_estimate"):
        _artifact_metric(baseline.get(metric), f"guardrails.baseline.{metric}")
        _artifact_metric(candidate.get(metric), f"guardrails.candidate.{metric}")
    for metric in ("MRR@10", "Recall@5", "Recall@10"):
        if float(candidate[metric]) < float(baseline[metric]):
            raise ValidationError(f"approved_policy_artifact candidate {metric} must not regress")
    if float(candidate["Recall@10"]) <= 0.0:
        raise ValidationError("approved_policy_artifact candidate Recall@10 must be greater than zero")
    if float(candidate["wrong_paper_handoff_rate"]) > float(baseline["wrong_paper_handoff_rate"]):
        raise ValidationError("approved_policy_artifact candidate wrong_paper_handoff_rate must not regress")
    for metric in ("p95_latency_ms", "token_estimate", "cost_estimate"):
        if float(candidate[metric]) > float(baseline[metric]):
            raise ValidationError(f"approved_policy_artifact candidate {metric} must not regress")


def _artifact_metric(value: Any, field: str, *, maximum: float | None = None) -> float:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"approved_policy_artifact.{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValidationError(f"approved_policy_artifact.{field} must be finite and non-negative")
    if maximum is not None and number > maximum:
        raise ValidationError(f"approved_policy_artifact.{field} must be <= {maximum}")
    return number


def _mapping_hash(value: Mapping[str, Any]) -> str:
    import hashlib

    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_iso_datetime(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be an ISO timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO timestamp") from exc


def _require_sha256_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise ValidationError(f"{field} must be a sha256 digest")
    if any(ch not in "0123456789abcdef" for ch in value[len("sha256:"):]):
        raise ValidationError(f"{field} must be a sha256 digest")


def _runtime_env_shell(env: Mapping[str, str]) -> str:
    lines = ["#!/usr/bin/env bash", "set -euo pipefail"]
    for key in sorted(env):
        value = str(env[key]).replace("'", "'\\''")
        lines.append(f"export {key}='{value}'")
    return "\n".join(lines) + "\n"
