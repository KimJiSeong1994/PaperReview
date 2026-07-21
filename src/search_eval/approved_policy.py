"""Export an approved SkillOpt best_skill.md for runtime policy gating."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator

from .accepted_candidate import (
    AcceptedSkillOptCandidate,
    load_accepted_skillopt_candidate,
)
from .policy_validation import validate_runtime_policy_text
from .retrieval_eval import (
    assert_candidate_beats_baseline,
    validate_retrieval_evaluation_record,
)
from .skillopt_adapter import canonical_file_hash
from .skillopt_contract import (
    V1_ALLOWED_SCOPE,
    ValidationError,
    load_json,
    validate_dataset_contract,
    validate_execution_control,
)
from .query_analyzer_pilot import load_baseline_skill
from .skillopt_run_contract import (
    INPUT_ARTIFACT_NAMES,
    AuthorityContext,
    canonical_json_bytes,
    read_stable_file,
    resolve_authority_context,
    verify_authority_context_current,
)

APPROVED_POLICY_VERSION = "approved-skillopt-policy-v2"
MINIMUM_APPROVAL_NDCG_DELTA = 0.01


@dataclass(frozen=True)
class ValidatedApprovedSkillOptPolicy(Mapping[str, Any]):
    """Immutable consumer capability for one fully revalidated v2 approval.

    The mapping view is retained for read compatibility with reporting code, but
    authoritative consumers must require this concrete type. Nested values are
    copied on access so callers cannot mutate the validated snapshot in place.
    """

    _artifact: Mapping[str, Any]
    artifact_path: Path
    artifact_hash: str
    artifact_size_bytes: int
    runtime_env_path: Path
    accepted_candidate: AcceptedSkillOptCandidate

    def __getitem__(self, key: str) -> Any:
        if key == "artifact_path":
            return str(self.artifact_path)
        if key == "runtime_env_path":
            return str(self.runtime_env_path)
        return deepcopy(self._artifact[key])

    def __iter__(self) -> Iterator[str]:
        return iter((*self._artifact, "artifact_path", "runtime_env_path"))

    def __len__(self) -> int:
        return len(self._artifact) + 2

    def persisted_artifact(self) -> dict[str, Any]:
        return deepcopy(dict(self._artifact))


def export_approved_skillopt_policy(
    *,
    acceptance_manifest_path: str | Path,
    run_root: str | Path,
    output_dir: str | Path,
    dataset_path: str | Path,
    control_path: str | Path,
    baseline_skill_path: str | Path,
    selection_baseline_eval: Mapping[str, Any],
    selection_candidate_eval: Mapping[str, Any],
    holdout_eval_loader: Callable[[], tuple[Mapping[str, Any], Mapping[str, Any]]],
    minimum_ndcg_delta: float = MINIMUM_APPROVAL_NDCG_DELTA,
) -> ValidatedApprovedSkillOptPolicy:
    """Validate and export a SkillOpt best skill as a runtime-loadable policy."""
    if (
        isinstance(minimum_ndcg_delta, bool)
        or not isinstance(minimum_ndcg_delta, (int, float))
        or not math.isfinite(float(minimum_ndcg_delta))
        or float(minimum_ndcg_delta) < MINIMUM_APPROVAL_NDCG_DELTA
    ):
        raise ValidationError(
            f"approved policy minimum nDCG@10 delta must be at least {MINIMUM_APPROVAL_NDCG_DELTA}"
        )
    accepted = load_accepted_skillopt_candidate(
        acceptance_manifest_path=acceptance_manifest_path,
        run_root=run_root,
    )
    if canonical_file_hash(accepted.best_skill_path) != accepted.best_skill_hash:
        raise ValidationError("accepted best_skill changed after acceptance validation")
    accepted_provenance = _build_accepted_candidate_provenance(accepted)
    try:
        best_skill_text = accepted.best_skill_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("accepted best_skill must be UTF-8 text") from exc
    dataset = load_json(dataset_path)
    control = load_json(control_path)
    validate_dataset_contract(dataset)
    validate_execution_control(control)
    if control.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("approved policy export requires v1 QueryAnalyzer scope")
    load_baseline_skill(baseline_skill_path)
    validate_runtime_policy_text(best_skill_text)
    best_skill_hash = accepted.best_skill_hash
    selection_ids = [
        str(query["query_id"])
        for query in dataset["queries"]
        if query["split"] == "selection"
    ]
    validate_retrieval_evaluation_record(selection_baseline_eval)
    validate_retrieval_evaluation_record(selection_candidate_eval)
    _validate_eval_record_matches_query_ids(
        selection_baseline_eval, dataset, selection_ids
    )
    _validate_eval_record_matches_query_ids(
        selection_candidate_eval, dataset, selection_ids
    )
    baseline_skill_hash = canonical_file_hash(baseline_skill_path)
    _validate_eval_matches_skill(
        selection_baseline_eval,
        baseline_skill_hash,
        label="baseline",
    )
    _validate_eval_matches_skill(
        selection_candidate_eval,
        best_skill_hash,
        label="candidate",
    )
    _validate_accepted_candidate_matches_inputs(
        accepted_input_hashes=accepted.input_artifact_hashes,
        dataset_path=dataset_path,
        control_path=control_path,
        baseline_skill_path=baseline_skill_path,
    )
    assert_candidate_beats_baseline(
        baseline_record=selection_baseline_eval,
        candidate_record=selection_candidate_eval,
        minimum_delta=minimum_ndcg_delta,
    )
    selection_gate = _build_selection_gate_evidence(
        dataset=dataset,
        candidate_eval=selection_candidate_eval,
        baseline_eval_hash=_mapping_hash(selection_baseline_eval),
        candidate_eval_hash=_mapping_hash(selection_candidate_eval),
    )
    holdout_baseline_eval, holdout_candidate_eval = holdout_eval_loader()
    test_ids = [
        str(query["query_id"])
        for query in dataset["queries"]
        if query["split"] == "test"
    ]
    validate_retrieval_evaluation_record(holdout_baseline_eval)
    validate_retrieval_evaluation_record(holdout_candidate_eval)
    _validate_eval_record_matches_query_ids(holdout_baseline_eval, dataset, test_ids)
    _validate_eval_record_matches_query_ids(holdout_candidate_eval, dataset, test_ids)
    _validate_eval_matches_skill(
        holdout_baseline_eval,
        baseline_skill_hash,
        label="baseline",
    )
    _validate_eval_matches_skill(
        holdout_candidate_eval,
        best_skill_hash,
        label="candidate",
    )
    assert_candidate_beats_baseline(
        baseline_record=holdout_baseline_eval,
        candidate_record=holdout_candidate_eval,
    )
    holdout_gate = _build_holdout_gate_evidence(
        dataset=dataset,
        baseline_eval=holdout_baseline_eval,
        candidate_eval=holdout_candidate_eval,
        baseline_eval_hash=_mapping_hash(holdout_baseline_eval),
        candidate_eval_hash=_mapping_hash(holdout_candidate_eval),
    )

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    exported_skill = output / "best_skill.md"
    exported_skill.write_bytes(accepted.best_skill_bytes)
    exported_skill_hash = canonical_file_hash(exported_skill)
    if exported_skill_hash != best_skill_hash:
        raise ValidationError("approved policy export skill hash changed during copy")

    artifact = {
        "version": APPROVED_POLICY_VERSION,
        "created_at": accepted_provenance["accepted_at"],
        "scope": V1_ALLOWED_SCOPE,
        "skill_hash": exported_skill_hash,
        "baseline_hash": baseline_skill_hash,
        "dataset_hash": dataset["dataset_hash"],
        "execution_control_hash": control["control_hash"],
        "runtime_policy_path": str(exported_skill.resolve()),
        "evaluation_status": "qualified",
        "authorization_status": "not_authorized",
        "evaluation_evidence": _build_evaluation_evidence(
            selection_baseline_eval=selection_baseline_eval,
            selection_candidate_eval=selection_candidate_eval,
            holdout_baseline_eval=holdout_baseline_eval,
            holdout_candidate_eval=holdout_candidate_eval,
        ),
        "accepted_candidate": accepted_provenance,
        "runtime_env": {
            "SKILLOPT_SEARCH_POLICY_ENABLED": "false",
            "SKILLOPT_SEARCH_POLICY_PATH": str(exported_skill.resolve()),
            "SKILLOPT_SEARCH_POLICY_HASH": exported_skill_hash,
            "SKILLOPT_SEARCH_POLICY_SCOPE": V1_ALLOWED_SCOPE,
        },
        "metric_snapshot": {
            "primary_metric": "nDCG@10",
            "split": "selection",
            "evaluated_skill_hash": best_skill_hash,
            "baseline": float(selection_baseline_eval["nDCG@10"]),
            "candidate": float(selection_candidate_eval["nDCG@10"]),
            "baseline_eval_hash": _mapping_hash(selection_baseline_eval),
            "candidate_eval_hash": _mapping_hash(selection_candidate_eval),
            "guardrails": {
                "baseline": _guardrail_snapshot(selection_baseline_eval),
                "candidate": _guardrail_snapshot(selection_candidate_eval),
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
    artifact_path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    env_path = output / "runtime_env.sh"
    env_path.write_text(_runtime_env_shell(artifact["runtime_env"]), encoding="utf-8")
    return load_validated_approved_skillopt_policy(artifact_path)


def _validate_eval_record_matches_query_ids(
    record: Mapping[str, Any],
    dataset: Mapping[str, Any],
    expected_ids: list[str],
) -> None:
    if record.get("dataset_hash") != dataset.get("dataset_hash"):
        raise ValidationError(
            "retrieval evaluation dataset_hash does not match dataset"
        )
    per_query = record.get("per_query")
    if not isinstance(per_query, list):
        raise ValidationError("retrieval evaluation per_query must be a list")
    actual_ids = [
        str(item.get("query_id")) for item in per_query if isinstance(item, Mapping)
    ]
    if actual_ids != expected_ids:
        raise ValidationError(
            "retrieval evaluation per_query ids must match dataset query order"
        )
    if int(record.get("query_count", -1)) != len(expected_ids):
        raise ValidationError("retrieval evaluation query_count must match dataset")


def _validate_eval_matches_skill(
    evaluation: Mapping[str, Any],
    expected_skill_hash: str,
    *,
    label: str,
) -> None:
    evaluated_skill_hash = evaluation.get("evaluated_skill_hash")
    if evaluated_skill_hash != expected_skill_hash:
        raise ValidationError(
            f"{label} evaluation evaluated_skill_hash must match its skill file hash"
        )


def _validate_accepted_candidate_matches_inputs(
    *,
    accepted_input_hashes: Mapping[str, str],
    dataset_path: str | Path,
    control_path: str | Path,
    baseline_skill_path: str | Path,
) -> None:
    expected = {
        "dataset": _canonical_json_file_hash(dataset_path),
        "execution_control": _canonical_json_file_hash(control_path),
        "baseline_skill": canonical_file_hash(baseline_skill_path),
    }
    mismatches = [
        name
        for name, digest in expected.items()
        if accepted_input_hashes.get(name) != digest
    ]
    if mismatches:
        raise ValidationError(
            "accepted candidate inputs do not match approval inputs: "
            + ", ".join(sorted(mismatches))
        )


def _canonical_json_file_hash(path: str | Path) -> str:
    payload = canonical_json_bytes(load_json(path))
    return "sha256:" + hashlib.sha256(payload).hexdigest()


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


def _build_evaluation_evidence(
    *,
    selection_baseline_eval: Mapping[str, Any],
    selection_candidate_eval: Mapping[str, Any],
    holdout_baseline_eval: Mapping[str, Any],
    holdout_candidate_eval: Mapping[str, Any],
) -> dict[str, Any]:
    records = {
        "selection_baseline": selection_baseline_eval,
        "selection_candidate": selection_candidate_eval,
        "test_baseline": holdout_baseline_eval,
        "test_candidate": holdout_candidate_eval,
    }
    lineage: dict[str, Any] = {}
    modes = set()
    for name, record in records.items():
        evidence = record.get("evidence")
        if not isinstance(evidence, Mapping):
            raise ValidationError(f"{name} evaluation evidence is missing")
        descriptor = dict(evidence)
        lineage[name] = descriptor
        modes.add(descriptor.get("mode"))
    if len(modes) != 1:
        raise ValidationError("approval evaluation evidence modes must match")
    return {"mode": modes.pop(), "records": lineage}


def _build_selection_gate_evidence(
    *,
    dataset: Mapping[str, Any],
    candidate_eval: Mapping[str, Any],
    baseline_eval_hash: str,
    candidate_eval_hash: str,
) -> dict[str, Any]:
    required_intents = {"author_search", "method_search"}
    selection_queries = [
        query
        for query in dataset["queries"]
        if query["split"] == "selection" and query["intent"] in required_intents
    ]
    intents = {str(query["intent"]) for query in selection_queries}
    missing = required_intents - intents
    if missing:
        raise ValidationError(
            f"selection gate missing required intents: {sorted(missing)}"
        )
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
            raise ValidationError(
                f"selection gate missing candidate eval for {query_id}"
            )
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
        failed_summary = ", ".join(
            f"{row['query_id']}({row['intent']})" for row in failed
        )
        raise ValidationError(
            f"selection gate failed canonical anchor recall for: {failed_summary}"
        )
    evidence = {
        "status": "passed",
        "baseline_eval_hash": baseline_eval_hash,
        "candidate_eval_hash": candidate_eval_hash,
        "required_intents": sorted(required_intents),
        "passed_query_ids": passed_query_ids,
        "per_query": per_query,
    }
    evidence["evidence_hash"] = _mapping_hash(evidence)
    return evidence


def _build_holdout_gate_evidence(
    *,
    dataset: Mapping[str, Any],
    baseline_eval: Mapping[str, Any],
    candidate_eval: Mapping[str, Any],
    baseline_eval_hash: str,
    candidate_eval_hash: str,
) -> dict[str, Any]:
    test_queries = [query for query in dataset["queries"] if query["split"] == "test"]
    if not test_queries:
        raise ValidationError("holdout gate requires at least one test query")
    rows_by_id = {
        str(row["query_id"]): row
        for row in candidate_eval["per_query"]
        if isinstance(row, Mapping) and isinstance(row.get("query_id"), str)
    }
    baseline_rows_by_id = {
        str(row["query_id"]): row
        for row in baseline_eval["per_query"]
        if isinstance(row, Mapping) and isinstance(row.get("query_id"), str)
    }
    per_query = []
    passed_query_ids = []
    for query in test_queries:
        query_id = str(query["query_id"])
        row = rows_by_id.get(query_id)
        if not isinstance(row, Mapping):
            raise ValidationError(f"holdout gate missing candidate eval for {query_id}")
        baseline_row = baseline_rows_by_id.get(query_id)
        if not isinstance(baseline_row, Mapping):
            raise ValidationError(f"holdout gate missing baseline eval for {query_id}")
        ndcg = float(row["ndcg_at_10"])
        recall = float(row["recall_at_10"])
        passed = (
            ndcg > 0.0
            and recall > 0.0
            and ndcg >= float(baseline_row["ndcg_at_10"])
            and recall >= float(baseline_row["recall_at_10"])
        )
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
        failed_summary = ", ".join(
            f"{row['query_id']}({row['intent']})" for row in failed
        )
        raise ValidationError(
            f"holdout gate failed canonical anchor recall for: {failed_summary}"
        )
    evidence = {
        "status": "passed",
        "split": "test",
        "baseline_eval_hash": baseline_eval_hash,
        "candidate_eval_hash": candidate_eval_hash,
        "passed_query_ids": passed_query_ids,
        "per_query": per_query,
    }
    evidence["evidence_hash"] = _mapping_hash(evidence)
    return evidence


def split_retrieval_evaluation_record(
    record: Mapping[str, Any], query_ids: list[str]
) -> dict[str, Any]:
    wanted = set(query_ids)
    rows = [dict(row) for row in record["per_query"] if row.get("query_id") in wanted]
    if len(rows) != len(wanted):
        raise ValidationError("retrieval evaluation is missing required split rows")
    count = len(rows)
    subset = dict(record)
    subset["per_query"] = rows
    subset["query_count"] = count
    for target, source in (
        ("nDCG@10", "ndcg_at_10"),
        ("MRR@10", "mrr_at_10"),
        ("Recall@5", "recall_at_5"),
        ("Recall@10", "recall_at_10"),
        ("wrong_paper_handoff_rate", "wrong_paper_handoff"),
    ):
        subset[target] = round(sum(float(row[source]) for row in rows) / count, 6)
    return subset


def load_validated_approved_skillopt_policy(
    path: str | Path,
) -> ValidatedApprovedSkillOptPolicy:
    """Load a persisted approval only after replaying its accepted-v2 trust chain."""
    authority_context: AuthorityContext = resolve_authority_context()
    held = read_stable_file(path)
    if held.path.name != "approved_policy_artifact.json":
        raise ValidationError(
            "approved policy must use canonical approved_policy_artifact.json path"
        )
    artifact = _decode_json_object(held.payload, "approved policy artifact")
    validate_approved_policy_artifact(artifact)
    provenance = artifact["accepted_candidate"]
    accepted = load_accepted_skillopt_candidate(
        acceptance_manifest_path=provenance["acceptance_manifest_path"],
        run_root=provenance["run_root"],
        authority_context=authority_context,
    )
    expected_provenance = _build_accepted_candidate_provenance(accepted)
    if provenance != expected_provenance:
        raise ValidationError(
            "approved policy accepted provenance does not match fully revalidated v2 acceptance"
        )
    _validate_approval_inputs_against_acceptance(artifact, accepted)
    runtime_policy = read_stable_file(artifact["runtime_policy_path"])
    expected_policy_path = (held.path.parent / "best_skill.md").resolve()
    if runtime_policy.path != expected_policy_path:
        raise ValidationError(
            "approved runtime policy path is not the canonical sibling best_skill.md"
        )
    if (
        runtime_policy.sha256 != artifact["skill_hash"]
        or runtime_policy.sha256 != accepted.best_skill_hash
        or runtime_policy.payload != accepted.best_skill_bytes
    ):
        raise ValidationError(
            "approved runtime policy bytes do not match accepted best_skill snapshot"
        )
    runtime_env_path = held.path.parent / "runtime_env.sh"
    runtime_env = read_stable_file(runtime_env_path)
    expected_env = _runtime_env_shell(artifact["runtime_env"]).encode("utf-8")
    if runtime_env.payload != expected_env:
        raise ValidationError(
            "approved runtime environment template does not match artifact"
        )
    verify_authority_context_current(authority_context)
    return ValidatedApprovedSkillOptPolicy(
        _artifact=deepcopy(artifact),
        artifact_path=held.path,
        artifact_hash=held.sha256,
        artifact_size_bytes=held.size_bytes,
        runtime_env_path=runtime_env.path,
        accepted_candidate=accepted,
    )


def _build_accepted_candidate_provenance(
    accepted: AcceptedSkillOptCandidate,
) -> dict[str, Any]:
    manifest = _read_canonical_accepted_json(
        accepted.manifest_path,
        expected_hash=accepted.manifest_hash,
        expected_size=accepted.manifest_size_bytes,
        label="acceptance manifest",
    )
    request = _read_canonical_accepted_json(
        accepted.run_root / "artifacts" / "run_request.json",
        expected_hash=accepted.sealed_request_hash,
        expected_size=accepted.sealed_request_size_bytes,
        label="sealed request",
    )
    result = _read_canonical_accepted_json(
        accepted.run_root / "artifacts" / "run_result.json",
        expected_hash=accepted.sealed_result_hash,
        expected_size=accepted.sealed_result_size_bytes,
        label="sealed result",
    )
    compatibility = {
        "profile_identity": request["upstream"]["profile_identity"],
        "report_identity": request["upstream"]["compatibility_report_identity"],
        "pristine_source_identity": request["upstream"]["pristine_source_identity"],
        "overlay_identity": request["upstream"]["overlay_identity"],
        "staging_identity": request["upstream"]["staging_identity"],
        "runner_identity": request["upstream"]["runner_identity"],
        "custody_identity": request["upstream"]["custody_identity"],
    }
    authority = {
        "policy_identity": request["authority"]["policy_identity"],
        "store_receipt_identity": result["attestation"]["store_receipt_identity"],
        "coordinator_id": request["authority"]["coordinator_id"],
        "coordinator_namespace": request["authority"]["coordinator_namespace"],
    }
    receipts = {
        "usage_identity": accepted.usage_receipt_identity,
        "privacy_identity": accepted.privacy_receipt_identity,
    }
    expected_flat = {
        "profile_identity": accepted.profile_identity,
        "overlay_identity": accepted.overlay_identity,
        "staging_identity": accepted.staging_identity,
        "runner_identity": accepted.runner_identity,
        "custody_identity": accepted.custody_identity,
        "policy_identity": accepted.policy_identity,
        "coordinator_id": accepted.coordinator_id,
        "coordinator_namespace": accepted.coordinator_namespace,
    }
    observed_flat = {**compatibility, **authority}
    for name, expected in expected_flat.items():
        if observed_flat.get(name) != expected:
            raise ValidationError(f"accepted request/result provenance {name} mismatch")
    return {
        "version": "accepted-skillopt-provenance-v2",
        "run_root": str(accepted.run_root),
        "acceptance_manifest_path": str(accepted.manifest_path),
        "acceptance_manifest_hash": accepted.manifest_hash,
        "acceptance_manifest_size_bytes": accepted.manifest_size_bytes,
        "accepted_at": manifest["accepted_at"],
        "request_id": accepted.request_id,
        "result_id": accepted.result_id,
        "sealed_request_hash": accepted.sealed_request_hash,
        "sealed_request_size_bytes": accepted.sealed_request_size_bytes,
        "sealed_result_hash": accepted.sealed_result_hash,
        "sealed_result_size_bytes": accepted.sealed_result_size_bytes,
        "input_artifact_hashes": dict(sorted(accepted.input_artifact_hashes.items())),
        "evidence_snapshot_hashes": {
            name: entry["sha256"]
            for name, entry in sorted(manifest["evidence_snapshots"].items())
        },
        "accepted_output_hashes": {
            name: entry["sha256"]
            for name, entry in sorted(manifest["accepted_outputs"].items())
        },
        "accepted_receipt_hashes": {
            name: entry["sha256"]
            for name, entry in sorted(manifest["accepted_receipts"].items())
        },
        "compatibility": compatibility,
        "authority": authority,
        "receipts": receipts,
    }


def _validate_approval_inputs_against_acceptance(
    artifact: Mapping[str, Any], accepted: AcceptedSkillOptCandidate
) -> None:
    hashes = accepted.input_artifact_hashes
    expected_direct = {
        "baseline_hash": hashes["baseline_skill"],
    }
    for field, expected in expected_direct.items():
        if artifact.get(field) != expected:
            raise ValidationError(
                f"approved policy {field} does not match accepted input bytes"
            )
    manifest = _read_canonical_accepted_json(
        accepted.manifest_path,
        expected_hash=accepted.manifest_hash,
        expected_size=accepted.manifest_size_bytes,
        label="acceptance manifest",
    )
    for name, artifact_field, payload_field in (
        ("dataset", "dataset_hash", "dataset_hash"),
        ("execution_control", "execution_control_hash", "control_hash"),
    ):
        entry = manifest["evidence_snapshots"][name]
        held = read_stable_file(accepted.run_root / entry["path"])
        if held.sha256 != hashes[name] or held.size_bytes != entry["size_bytes"]:
            raise ValidationError(
                f"accepted {name} snapshot changed before approval consumption"
            )
        value = _decode_json_object(held.payload, f"accepted {name} snapshot")
        if artifact.get(artifact_field) != value.get(payload_field):
            raise ValidationError(
                f"approved policy {artifact_field} does not match accepted {name} content"
            )


def _read_canonical_accepted_json(
    path: Path,
    *,
    expected_hash: str,
    expected_size: int,
    label: str,
) -> dict[str, Any]:
    held = read_stable_file(path)
    if held.sha256 != expected_hash or held.size_bytes != expected_size:
        raise ValidationError(f"{label} changed after acceptance validation")
    value = _decode_json_object(held.payload, label)
    if canonical_json_bytes(value) != held.payload:
        raise ValidationError(f"{label} is not canonical accepted JSON")
    return value


def _decode_json_object(payload: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValidationError(f"{label} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ValidationError(f"{label} contains non-finite JSON value {constant}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value


def validate_approved_policy_artifact(artifact: Mapping[str, Any]) -> None:
    artifact = (
        artifact.persisted_artifact()
        if isinstance(artifact, ValidatedApprovedSkillOptPolicy)
        else dict(artifact)
    )
    artifact.pop("artifact_path", None)
    artifact.pop("runtime_env_path", None)
    required = {
        "version",
        "created_at",
        "scope",
        "skill_hash",
        "baseline_hash",
        "dataset_hash",
        "execution_control_hash",
        "runtime_policy_path",
        "evaluation_status",
        "authorization_status",
        "evaluation_evidence",
        "accepted_candidate",
        "runtime_env",
        "metric_snapshot",
        "selection_gate",
        "holdout_gate",
        "rollback_to",
    }
    if set(artifact) != required:
        raise ValidationError(
            "approved_policy_artifact keys mismatch: "
            f"missing={sorted(required - set(artifact))}, "
            f"extra={sorted(set(artifact) - required)}"
        )
    if artifact.get("version") != APPROVED_POLICY_VERSION:
        raise ValidationError("approved_policy_artifact.version is invalid")
    if artifact.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("approved_policy_artifact.scope is invalid")
    if artifact.get("evaluation_status") != "qualified":
        raise ValidationError("approved_policy_artifact evaluation_status is invalid")
    if artifact.get("authorization_status") != "not_authorized":
        raise ValidationError("approved_policy_artifact must remain not_authorized")
    _validate_evaluation_evidence_artifact(artifact.get("evaluation_evidence"))
    _require_iso_datetime(
        artifact.get("created_at"), "approved_policy_artifact.created_at"
    )
    if artifact.get("skill_hash") == artifact.get("baseline_hash"):
        raise ValidationError(
            "approved_policy_artifact.skill_hash must differ from baseline_hash"
        )
    env = artifact.get("runtime_env")
    if not isinstance(env, Mapping):
        raise ValidationError("approved_policy_artifact.runtime_env must be an object")
    _validate_runtime_env(
        env,
        runtime_policy_path=artifact.get("runtime_policy_path"),
        skill_hash=artifact.get("skill_hash"),
    )
    metrics = artifact.get("metric_snapshot")
    if not isinstance(metrics, Mapping):
        raise ValidationError(
            "approved_policy_artifact.metric_snapshot must be an object"
        )
    if metrics.get("primary_metric") != "nDCG@10":
        raise ValidationError("approved_policy_artifact primary_metric must be nDCG@10")
    if metrics.get("split") != "selection":
        raise ValidationError(
            "approved_policy_artifact metric_snapshot must be selection-only"
        )
    if metrics.get("evaluated_skill_hash") != artifact.get("skill_hash"):
        raise ValidationError(
            "approved_policy_artifact evaluated_skill_hash must match skill_hash"
        )
    _require_sha256_text(
        metrics.get("baseline_eval_hash"),
        "approved_policy_artifact.metric_snapshot.baseline_eval_hash",
    )
    _require_sha256_text(
        metrics.get("candidate_eval_hash"),
        "approved_policy_artifact.metric_snapshot.candidate_eval_hash",
    )
    baseline_metric = _artifact_metric(
        metrics.get("baseline"), "metric_snapshot.baseline", maximum=1.0
    )
    candidate_metric = _artifact_metric(
        metrics.get("candidate"), "metric_snapshot.candidate", maximum=1.0
    )
    # Match the export gate's additive comparison. Subtracting two binary
    # floats can turn an exact 0.01 improvement into 0.009999999999999953.
    if Decimal(str(candidate_metric)) < (
        Decimal(str(baseline_metric)) + Decimal(str(MINIMUM_APPROVAL_NDCG_DELTA))
    ):
        raise ValidationError(
            "approved_policy_artifact candidate metric must improve by at least 0.01"
        )
    _validate_accepted_candidate_artifact(artifact.get("accepted_candidate"))
    accepted_provenance = artifact["accepted_candidate"]
    if accepted_provenance["accepted_output_hashes"].get("best_skill") != artifact.get(
        "skill_hash"
    ):
        raise ValidationError(
            "approved skill_hash must match accepted best_skill identity"
        )
    _validate_artifact_guardrails(metrics.get("guardrails"))
    _validate_selection_gate_artifact(artifact.get("selection_gate"))
    _validate_holdout_gate_artifact(artifact.get("holdout_gate"))
    rollback = artifact.get("rollback_to")
    if not isinstance(rollback, Mapping) or rollback.get("skill_hash") != artifact.get(
        "baseline_hash"
    ):
        raise ValidationError(
            "approved_policy_artifact rollback hash must match baseline_hash"
        )


def _validate_accepted_candidate_artifact(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise ValidationError(
            "approved_policy_artifact.accepted_candidate must be an object"
        )
    required = {
        "version",
        "run_root",
        "acceptance_manifest_path",
        "acceptance_manifest_hash",
        "acceptance_manifest_size_bytes",
        "accepted_at",
        "request_id",
        "result_id",
        "sealed_request_hash",
        "sealed_request_size_bytes",
        "sealed_result_hash",
        "sealed_result_size_bytes",
        "input_artifact_hashes",
        "evidence_snapshot_hashes",
        "accepted_output_hashes",
        "accepted_receipt_hashes",
        "compatibility",
        "authority",
        "receipts",
    }
    if set(value) != required:
        raise ValidationError(
            "approved_policy_artifact.accepted_candidate keys mismatch"
        )
    if value.get("version") != "accepted-skillopt-provenance-v2":
        raise ValidationError(
            "approved accepted-candidate provenance version is invalid"
        )
    run_root = value.get("run_root")
    manifest_path = value.get("acceptance_manifest_path")
    if not isinstance(run_root, str) or not Path(run_root).is_absolute():
        raise ValidationError("approved accepted-candidate run_root must be absolute")
    if not isinstance(manifest_path, str) or not Path(manifest_path).is_absolute():
        raise ValidationError("approved acceptance manifest path must be absolute")
    _require_iso_datetime(
        value.get("accepted_at"), "approved accepted-candidate accepted_at"
    )
    for field in (
        "acceptance_manifest_hash",
        "request_id",
        "result_id",
        "sealed_request_hash",
        "sealed_result_hash",
    ):
        _require_sha256_text(
            value.get(field), f"approved_policy_artifact.accepted_candidate.{field}"
        )
    for field in (
        "acceptance_manifest_size_bytes",
        "sealed_request_size_bytes",
        "sealed_result_size_bytes",
    ):
        if (
            isinstance(value.get(field), bool)
            or not isinstance(value.get(field), int)
            or value[field] <= 0
        ):
            raise ValidationError(
                f"approved accepted-candidate {field} must be positive"
            )
    for field in (
        "input_artifact_hashes",
        "evidence_snapshot_hashes",
        "accepted_output_hashes",
        "accepted_receipt_hashes",
    ):
        hashes = value.get(field)
        if not isinstance(hashes, Mapping) or not hashes:
            raise ValidationError(
                f"approved accepted-candidate {field} must be non-empty"
            )
        for name, digest in hashes.items():
            if not isinstance(name, str) or not name:
                raise ValidationError(
                    f"approved accepted-candidate {field} key is invalid"
                )
            _require_sha256_text(digest, f"approved accepted-candidate {field}.{name}")
    if set(value["input_artifact_hashes"]) != set(INPUT_ARTIFACT_NAMES):
        raise ValidationError("approved accepted-candidate input identities mismatch")
    if set(value["evidence_snapshot_hashes"]) != set(INPUT_ARTIFACT_NAMES):
        raise ValidationError(
            "approved accepted-candidate evidence snapshot identities mismatch"
        )
    if value["input_artifact_hashes"] != value["evidence_snapshot_hashes"]:
        raise ValidationError(
            "approved accepted-candidate input/evidence identities differ"
        )
    if set(value["accepted_output_hashes"]) != {
        "best_skill",
        "evaluation",
        "sanitized_summary",
    }:
        raise ValidationError("approved accepted-candidate output identities mismatch")
    if set(value["accepted_receipt_hashes"]) != {"usage", "privacy"}:
        raise ValidationError(
            "approved accepted-candidate receipt snapshot identities mismatch"
        )
    compatibility = value.get("compatibility")
    expected_compatibility = {
        "profile_identity",
        "report_identity",
        "pristine_source_identity",
        "overlay_identity",
        "staging_identity",
        "runner_identity",
        "custody_identity",
    }
    if (
        not isinstance(compatibility, Mapping)
        or set(compatibility) != expected_compatibility
    ):
        raise ValidationError(
            "approved accepted-candidate compatibility identities mismatch"
        )
    authority = value.get("authority")
    expected_authority = {
        "policy_identity",
        "store_receipt_identity",
        "coordinator_id",
        "coordinator_namespace",
    }
    if not isinstance(authority, Mapping) or set(authority) != expected_authority:
        raise ValidationError(
            "approved accepted-candidate authority identities mismatch"
        )
    receipts = value.get("receipts")
    if not isinstance(receipts, Mapping) or set(receipts) != {
        "usage_identity",
        "privacy_identity",
    }:
        raise ValidationError("approved accepted-candidate receipt identities mismatch")
    for group, fields in (
        (compatibility, expected_compatibility),
        (authority, {"policy_identity", "store_receipt_identity"}),
        (receipts, {"usage_identity", "privacy_identity"}),
    ):
        for field in fields:
            _require_sha256_text(
                group.get(field), f"approved accepted-candidate {field}"
            )
    for field in ("coordinator_id", "coordinator_namespace"):
        if not isinstance(authority.get(field), str) or not authority[field].strip():
            raise ValidationError(f"approved accepted-candidate {field} is required")


def _validate_evaluation_evidence_artifact(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {"mode", "records"}:
        raise ValidationError(
            "approved_policy_artifact evaluation_evidence keys mismatch"
        )
    mode = value.get("mode")
    if mode not in {"fixture", "measured"}:
        raise ValidationError(
            "approved_policy_artifact evaluation_evidence mode is invalid"
        )
    records = value.get("records")
    expected_records = {
        "selection_baseline",
        "selection_candidate",
        "test_baseline",
        "test_candidate",
    }
    if not isinstance(records, Mapping) or set(records) != expected_records:
        raise ValidationError(
            "approved_policy_artifact evaluation_evidence records mismatch"
        )
    for name, descriptor in records.items():
        if not isinstance(descriptor, Mapping) or set(descriptor) != {
            "mode",
            "capture_id",
            "capture_hash",
        }:
            raise ValidationError(
                f"approved_policy_artifact {name} evidence keys mismatch"
            )
        if descriptor.get("mode") != mode:
            raise ValidationError(
                "approved_policy_artifact evaluation evidence modes must match"
            )
        if mode == "fixture":
            if (
                descriptor.get("capture_id") is not None
                or descriptor.get("capture_hash") is not None
            ):
                raise ValidationError(
                    "fixture approval evidence must not claim a capture"
                )
        else:
            capture_id = descriptor.get("capture_id")
            if not isinstance(capture_id, str) or not capture_id.strip():
                raise ValidationError("measured approval evidence requires capture_id")
            _require_sha256_text(
                descriptor.get("capture_hash"),
                f"approved_policy_artifact.evaluation_evidence.{name}.capture_hash",
            )


def _validate_runtime_env(
    env: Mapping[str, Any], *, runtime_policy_path: Any, skill_hash: Any
) -> None:
    required = {
        "SKILLOPT_SEARCH_POLICY_ENABLED",
        "SKILLOPT_SEARCH_POLICY_PATH",
        "SKILLOPT_SEARCH_POLICY_HASH",
        "SKILLOPT_SEARCH_POLICY_SCOPE",
    }
    if set(env) != required:
        raise ValidationError(
            "approved_policy_artifact runtime_env must contain exactly the four rollout keys"
        )
    if env.get("SKILLOPT_SEARCH_POLICY_ENABLED") != "false":
        raise ValidationError(
            "approved_policy_artifact runtime_env must remain disabled"
        )
    policy_path = env.get("SKILLOPT_SEARCH_POLICY_PATH")
    if not isinstance(policy_path, str) or not Path(policy_path).is_absolute():
        raise ValidationError(
            "approved_policy_artifact runtime_env path must be absolute"
        )
    if policy_path != runtime_policy_path:
        raise ValidationError(
            "approved_policy_artifact runtime_env path must match runtime_policy_path"
        )
    if env.get("SKILLOPT_SEARCH_POLICY_HASH") != skill_hash:
        raise ValidationError(
            "approved_policy_artifact runtime hash must match skill_hash"
        )
    if env.get("SKILLOPT_SEARCH_POLICY_SCOPE") != V1_ALLOWED_SCOPE:
        raise ValidationError("approved_policy_artifact runtime_env scope is invalid")


def _validate_selection_gate_artifact(selection_gate: Any) -> None:
    if not isinstance(selection_gate, Mapping):
        raise ValidationError(
            "approved_policy_artifact.selection_gate must be an object"
        )
    if selection_gate.get("status") != "passed":
        raise ValidationError("approved_policy_artifact.selection_gate must be passed")
    _validate_gate_evidence_hash(selection_gate, "selection_gate")
    _require_sha256_text(
        selection_gate.get("baseline_eval_hash"),
        "approved_policy_artifact.selection_gate.baseline_eval_hash",
    )
    _require_sha256_text(
        selection_gate.get("candidate_eval_hash"),
        "approved_policy_artifact.selection_gate.candidate_eval_hash",
    )
    required_intents = selection_gate.get("required_intents")
    if set(required_intents or []) != {"author_search", "method_search"}:
        raise ValidationError(
            "approved_policy_artifact.selection_gate required_intents is invalid"
        )
    passed_query_ids = selection_gate.get("passed_query_ids")
    if not isinstance(passed_query_ids, list) or any(
        not isinstance(query_id, str) or not query_id for query_id in passed_query_ids
    ):
        raise ValidationError(
            "approved_policy_artifact.selection_gate passed_query_ids is invalid"
        )
    per_query = selection_gate.get("per_query")
    if not isinstance(per_query, list) or len(per_query) < 2:
        raise ValidationError(
            "approved_policy_artifact.selection_gate per_query is incomplete"
        )
    intents = set()
    seen_query_ids = set()
    actual_passed_query_ids = []
    for row in per_query:
        if not isinstance(row, Mapping):
            raise ValidationError(
                "approved_policy_artifact.selection_gate per_query entries must be objects"
            )
        query_id = row.get("query_id")
        if not isinstance(query_id, str) or not query_id:
            raise ValidationError(
                "approved_policy_artifact.selection_gate query_id is required"
            )
        if query_id in seen_query_ids:
            raise ValidationError(
                "approved_policy_artifact.selection_gate duplicate query_id"
            )
        seen_query_ids.add(query_id)
        intent = str(row.get("intent") or "")
        intents.add(intent)
        must_include = row.get("must_include")
        if (
            not isinstance(must_include, list)
            or not must_include
            or any(
                not isinstance(value, str) or not value.strip()
                for value in must_include
            )
        ):
            raise ValidationError(
                "approved_policy_artifact.selection_gate must_include is required"
            )
        if row.get("passed") is not True:
            raise ValidationError(
                "approved_policy_artifact.selection_gate per_query must be passed"
            )
        ndcg = _artifact_metric(
            row.get("ndcg_at_10"), f"selection_gate.{query_id}.ndcg_at_10", maximum=1.0
        )
        if ndcg <= 0.0:
            raise ValidationError(
                "approved_policy_artifact.selection_gate ndcg_at_10 must be greater than zero"
            )
        recall = _artifact_metric(
            row.get("recall_at_10"),
            f"selection_gate.{query_id}.recall_at_10",
            maximum=1.0,
        )
        if recall <= 0.0:
            raise ValidationError(
                "approved_policy_artifact.selection_gate recall_at_10 must be greater than zero"
            )
        actual_passed_query_ids.append(query_id)
    if not {"author_search", "method_search"} <= intents:
        raise ValidationError(
            "approved_policy_artifact.selection_gate missing required intent evidence"
        )
    if passed_query_ids != actual_passed_query_ids:
        raise ValidationError(
            "approved_policy_artifact.selection_gate passed_query_ids must match passed per_query ids"
        )


def _validate_holdout_gate_artifact(holdout_gate: Any) -> None:
    if not isinstance(holdout_gate, Mapping):
        raise ValidationError("approved_policy_artifact.holdout_gate must be an object")
    if holdout_gate.get("status") != "passed" or holdout_gate.get("split") != "test":
        raise ValidationError(
            "approved_policy_artifact.holdout_gate must be passed test evidence"
        )
    _validate_gate_evidence_hash(holdout_gate, "holdout_gate")
    _require_sha256_text(
        holdout_gate.get("baseline_eval_hash"),
        "approved_policy_artifact.holdout_gate.baseline_eval_hash",
    )
    _require_sha256_text(
        holdout_gate.get("candidate_eval_hash"),
        "approved_policy_artifact.holdout_gate.candidate_eval_hash",
    )
    passed_query_ids = holdout_gate.get("passed_query_ids")
    if not isinstance(passed_query_ids, list) or any(
        not isinstance(query_id, str) or not query_id for query_id in passed_query_ids
    ):
        raise ValidationError(
            "approved_policy_artifact.holdout_gate passed_query_ids is invalid"
        )
    per_query = holdout_gate.get("per_query")
    if not isinstance(per_query, list) or not per_query:
        raise ValidationError(
            "approved_policy_artifact.holdout_gate per_query is incomplete"
        )
    seen_query_ids = set()
    actual_passed_query_ids = []
    for row in per_query:
        if not isinstance(row, Mapping):
            raise ValidationError(
                "approved_policy_artifact.holdout_gate per_query entries must be objects"
            )
        query_id = row.get("query_id")
        if not isinstance(query_id, str) or not query_id:
            raise ValidationError(
                "approved_policy_artifact.holdout_gate query_id is required"
            )
        if query_id in seen_query_ids:
            raise ValidationError(
                "approved_policy_artifact.holdout_gate duplicate query_id"
            )
        seen_query_ids.add(query_id)
        must_include = row.get("must_include")
        if (
            not isinstance(must_include, list)
            or not must_include
            or any(
                not isinstance(value, str) or not value.strip()
                for value in must_include
            )
        ):
            raise ValidationError(
                "approved_policy_artifact.holdout_gate must_include is required"
            )
        if row.get("passed") is not True:
            raise ValidationError(
                "approved_policy_artifact.holdout_gate per_query must be passed"
            )
        ndcg = _artifact_metric(
            row.get("ndcg_at_10"), f"holdout_gate.{query_id}.ndcg_at_10", maximum=1.0
        )
        recall = _artifact_metric(
            row.get("recall_at_10"),
            f"holdout_gate.{query_id}.recall_at_10",
            maximum=1.0,
        )
        if ndcg <= 0.0 or recall <= 0.0:
            raise ValidationError(
                "approved_policy_artifact.holdout_gate metrics must be greater than zero"
            )
        actual_passed_query_ids.append(query_id)
    if passed_query_ids != actual_passed_query_ids:
        raise ValidationError(
            "approved_policy_artifact.holdout_gate passed_query_ids must match passed per_query ids"
        )


def _validate_gate_evidence_hash(gate: Mapping[str, Any], field: str) -> None:
    expected = gate.get("evidence_hash")
    _require_sha256_text(expected, f"approved_policy_artifact.{field}.evidence_hash")
    payload = dict(gate)
    payload.pop("evidence_hash", None)
    if _mapping_hash(payload) != expected:
        raise ValidationError(
            f"approved_policy_artifact.{field} evidence_hash mismatch"
        )


def _validate_artifact_guardrails(guardrails: Any) -> None:
    if not isinstance(guardrails, Mapping):
        raise ValidationError("approved_policy_artifact.guardrails must be an object")
    baseline = guardrails.get("baseline")
    candidate = guardrails.get("candidate")
    if not isinstance(baseline, Mapping) or not isinstance(candidate, Mapping):
        raise ValidationError(
            "approved_policy_artifact.guardrails must include baseline and candidate"
        )
    for metric in ("MRR@10", "Recall@5", "Recall@10", "wrong_paper_handoff_rate"):
        _artifact_metric(
            baseline.get(metric), f"guardrails.baseline.{metric}", maximum=1.0
        )
        _artifact_metric(
            candidate.get(metric), f"guardrails.candidate.{metric}", maximum=1.0
        )
    for metric in ("p95_latency_ms", "token_estimate", "cost_estimate"):
        _artifact_metric(baseline.get(metric), f"guardrails.baseline.{metric}")
        _artifact_metric(candidate.get(metric), f"guardrails.candidate.{metric}")
    for metric in ("MRR@10", "Recall@5", "Recall@10"):
        if float(candidate[metric]) < float(baseline[metric]):
            raise ValidationError(
                f"approved_policy_artifact candidate {metric} must not regress"
            )
    if float(candidate["Recall@10"]) <= 0.0:
        raise ValidationError(
            "approved_policy_artifact candidate Recall@10 must be greater than zero"
        )
    if float(candidate["wrong_paper_handoff_rate"]) > float(
        baseline["wrong_paper_handoff_rate"]
    ):
        raise ValidationError(
            "approved_policy_artifact candidate wrong_paper_handoff_rate must not regress"
        )
    for metric in ("p95_latency_ms", "token_estimate", "cost_estimate"):
        if float(candidate[metric]) > float(baseline[metric]):
            raise ValidationError(
                f"approved_policy_artifact candidate {metric} must not regress"
            )


def _artifact_metric(value: Any, field: str, *, maximum: float | None = None) -> float:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(
            f"approved_policy_artifact.{field} must be a finite number"
        )
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValidationError(
            f"approved_policy_artifact.{field} must be finite and non-negative"
        )
    if maximum is not None and number > maximum:
        raise ValidationError(f"approved_policy_artifact.{field} must be <= {maximum}")
    return number


def _mapping_hash(value: Mapping[str, Any]) -> str:
    import hashlib

    payload = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_iso_datetime(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be an ISO timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO timestamp") from exc


def _require_sha256_text(value: Any, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
    ):
        raise ValidationError(f"{field} must be a sha256 digest")
    if any(ch not in "0123456789abcdef" for ch in value[len("sha256:") :]):
        raise ValidationError(f"{field} must be a sha256 digest")


def _runtime_env_shell(env: Mapping[str, str]) -> str:
    lines = ["#!/usr/bin/env bash", "set -euo pipefail"]
    for key in sorted(env):
        value = str(env[key]).replace("'", "'\\''")
        lines.append(f"export {key}='{value}'")
    return "\n".join(lines) + "\n"
