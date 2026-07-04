from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.search_eval.approved_policy import export_approved_skillopt_policy
from src.search_eval.continuous_optimizer import (
    append_reward_memory_entry,
    build_live_canary_handoff,
    build_next_iteration_seed,
    build_optimizer_decision_record,
    run_continuous_optimization_iteration,
    validate_continuous_iteration_manifest,
    validate_evaluator_contract_v1,
    validate_live_canary_handoff,
    validate_optimizer_decision_record,
)
from src.search_eval.retrieval_eval import build_fixture_retrieval_results, score_retrieval_results
from src.search_eval.skillopt_adapter import canonical_file_hash
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


def _candidate_best_skill(tmp_path: Path) -> Path:
    baseline = Path(BASELINE_SKILL).read_text(encoding="utf-8")
    text = baseline + """

## SkillOpt accepted edit — continuous RL memory candidate
- QueryAnalyzer standard search path should preserve exact paper-title and author intent first.
- Do not enable `use_llm_search` for this policy.
- Do not enable HyDE prompt optimization for this policy.
- Do not promote RelevanceFilter prompt optimization for this policy.
- Prefer source_queries that place must-include title phrases before broad acceptable synonyms.
"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "best_skill.md"
    path.write_text(text, encoding="utf-8")
    return path


def _evals(best_skill: Path | None = None) -> tuple[dict, dict]:
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(dataset_path=DATASET, quality="baseline"),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(dataset_path=DATASET, quality="candidate"),
    )
    if best_skill is not None:
        candidate_eval = {**candidate_eval, "evaluated_skill_hash": canonical_file_hash(best_skill)}
    return baseline_eval, candidate_eval


def _approved_policy(tmp_path: Path) -> tuple[dict, dict, dict, Path, Path]:
    best_skill = _candidate_best_skill(tmp_path)
    baseline_eval, candidate_eval = _evals(best_skill)
    manifest_path = _materialization_manifest_path(tmp_path)
    artifact = export_approved_skillopt_policy(
        best_skill_path=best_skill,
        output_dir=tmp_path / "approved",
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        baseline_eval=baseline_eval,
        candidate_eval=candidate_eval,
        materialization_manifest_path=manifest_path,
        minimum_ndcg_delta=0.01,
    )
    return artifact, baseline_eval, candidate_eval, manifest_path, Path(artifact["artifact_path"])


def _decision(tmp_path: Path, **overrides):
    artifact, baseline_eval, candidate_eval, manifest_path, _artifact_path = _approved_policy(tmp_path)
    return build_optimizer_decision_record(
        run_id="run-20260704-accepted",
        approved_policy_artifact=artifact,
        baseline_eval=baseline_eval,
        candidate_eval=candidate_eval,
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        materialization_manifest_path=manifest_path,
        **overrides,
    )


def test_evaluator_contract_requires_minimum_ndcg_delta():
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(dataset_path=DATASET, quality="candidate"),
    )
    candidate_eval = dict(baseline_eval)

    with pytest.raises(ValidationError, match="candidate nDCG@10"):
        validate_evaluator_contract_v1(baseline_eval=baseline_eval, candidate_eval=candidate_eval)


def test_optimizer_decision_updates_reward_memory_only_after_approval(tmp_path: Path):
    artifact, baseline_eval, candidate_eval, manifest_path, _artifact_path = _approved_policy(tmp_path)
    decision = build_optimizer_decision_record(
        run_id="run-20260704-accepted",
        approved_policy_artifact=artifact,
        baseline_eval=baseline_eval,
        candidate_eval=candidate_eval,
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        materialization_manifest_path=manifest_path,
    )
    validate_optimizer_decision_record(decision)

    memory_path = tmp_path / "reward-memory.jsonl"
    entry = append_reward_memory_entry(memory_path, decision, approved_policy_artifact_path=_artifact_path)

    assert entry["skill_hash"] == decision["candidate_skill_hash"]
    assert entry["reward"] >= 0.01
    lines = memory_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["run_id"] == "run-20260704-accepted"


def test_reward_memory_rejects_rolled_back_or_quarantined_runs(tmp_path: Path):
    with pytest.raises(ValidationError, match="rolled back or quarantined"):
        append_reward_memory_entry(
            tmp_path / "memory.jsonl",
            _decision(tmp_path / "rolled", status="accepted", rolled_back=True),
            approved_policy_artifact_path=_approved_policy(tmp_path / "rolled")[4],
        )

    with pytest.raises(ValidationError, match="rolled back or quarantined"):
        append_reward_memory_entry(
            tmp_path / "memory.jsonl",
            _decision(tmp_path / "quarantined", status="accepted", quarantined=True),
            approved_policy_artifact_path=_approved_policy(tmp_path / "quarantined")[4],
        )


def test_optimizer_rejects_eval_payload_hash_drift_after_approval(tmp_path: Path):
    artifact, baseline_eval, candidate_eval, manifest_path, _artifact_path = _approved_policy(tmp_path)
    baseline_drifts = [
        {**baseline_eval, "scoring_elapsed_ms": baseline_eval["scoring_elapsed_ms"] + 0.001},
        {**baseline_eval, "artifact_path": "hidden-extra-field"},
    ]
    for drifted_baseline in baseline_drifts:
        with pytest.raises(ValidationError, match="baseline_eval hash"):
            build_optimizer_decision_record(
                run_id="run-baseline-eval-drift",
                approved_policy_artifact=artifact,
                baseline_eval=drifted_baseline,
                candidate_eval=candidate_eval,
                dataset_path=DATASET,
                control_path=CONTROL,
                baseline_skill_path=BASELINE_SKILL,
                materialization_manifest_path=manifest_path,
            )

    candidate_drifts = [
        {**candidate_eval, "scoring_elapsed_ms": candidate_eval["scoring_elapsed_ms"] + 0.001},
        {**candidate_eval, "runtime_env_path": "hidden-extra-field"},
    ]
    for drifted_candidate in candidate_drifts:
        with pytest.raises(ValidationError, match="candidate_eval hash"):
            build_optimizer_decision_record(
                run_id="run-candidate-eval-drift",
                approved_policy_artifact=artifact,
                baseline_eval=baseline_eval,
                candidate_eval=drifted_candidate,
                dataset_path=DATASET,
                control_path=CONTROL,
                baseline_skill_path=BASELINE_SKILL,
                materialization_manifest_path=manifest_path,
            )


def test_reward_memory_rejects_duplicate_artifact_even_with_new_run_id(tmp_path: Path):
    artifact, baseline_eval, candidate_eval, manifest_path, artifact_path = _approved_policy(tmp_path)
    decision = build_optimizer_decision_record(
        run_id="run-duplicate-a",
        approved_policy_artifact=artifact,
        baseline_eval=baseline_eval,
        candidate_eval=candidate_eval,
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        materialization_manifest_path=manifest_path,
    )
    memory_path = tmp_path / "reward-memory.jsonl"
    append_reward_memory_entry(memory_path, decision, approved_policy_artifact_path=artifact_path)
    duplicate_decision = {**decision, "run_id": "run-duplicate-b"}

    with pytest.raises(ValidationError, match="duplicate approved artifact"):
        append_reward_memory_entry(memory_path, duplicate_decision, approved_policy_artifact_path=artifact_path)


def test_reward_memory_rejects_forged_approved_artifact_hash(tmp_path: Path):
    artifact, baseline_eval, candidate_eval, manifest_path, _artifact_path = _approved_policy(tmp_path)
    decision = build_optimizer_decision_record(
        run_id="run-20260704-accepted",
        approved_policy_artifact=artifact,
        baseline_eval=baseline_eval,
        candidate_eval=candidate_eval,
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        materialization_manifest_path=manifest_path,
    )
    forged_path = tmp_path / "forged-approved.json"
    forged_path.write_text(json.dumps({**artifact, "dataset_hash": "forged-dataset"}), encoding="utf-8")

    with pytest.raises(ValidationError, match="file hash mismatch|dataset hash"):
        append_reward_memory_entry(
            tmp_path / "memory.jsonl",
            decision,
            approved_policy_artifact_path=forged_path,
        )


def test_optimizer_blocks_holdout_leakage_and_eval_hash_mismatch(tmp_path: Path):
    with pytest.raises(ValidationError, match="holdout leakage"):
        _decision(tmp_path / "leakage", holdout_leakage_detected=True)

    artifact, baseline_eval, candidate_eval, manifest_path, _artifact_path = _approved_policy(tmp_path / "hash")
    bad_eval = {**candidate_eval, "evaluated_skill_hash": "sha256:" + "0" * 64}
    with pytest.raises(ValidationError, match="evaluated_skill_hash"):
        build_optimizer_decision_record(
            run_id="run-hash-mismatch",
            approved_policy_artifact=artifact,
            baseline_eval=baseline_eval,
            candidate_eval=bad_eval,
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            materialization_manifest_path=manifest_path,
        )


def test_optimizer_rejects_baseline_and_materialization_lineage_drift(tmp_path: Path):
    artifact, baseline_eval, candidate_eval, manifest_path, _artifact_path = _approved_policy(tmp_path)
    wrong_baseline = tmp_path / "wrong-baseline.md"
    wrong_baseline.write_text(Path(BASELINE_SKILL).read_text(encoding="utf-8") + "\nextra drift\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="baseline_skill_path"):
        build_optimizer_decision_record(
            run_id="run-baseline-drift",
            approved_policy_artifact=artifact,
            baseline_eval=baseline_eval,
            candidate_eval=candidate_eval,
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=wrong_baseline,
            materialization_manifest_path=manifest_path,
        )

    tampered_manifest = tmp_path / "tampered-manifest.json"
    tampered_manifest.write_text(manifest_path.read_text(encoding="utf-8").replace("skillopt-search-benchmark-materialization-v0", "skillopt-search-benchmark-materialization-v0"), encoding="utf-8")
    # Same JSON content copied to a different file still has the same content hash; mutate a source hash to prove drift rejection.
    import json as _json

    manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_hashes"]["dataset_file"] = "sha256:" + "0" * 64
    tampered_manifest.write_text(_json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValidationError, match="materialization manifest hash|source_hashes"):
        build_optimizer_decision_record(
            run_id="run-manifest-drift",
            approved_policy_artifact=artifact,
            baseline_eval=baseline_eval,
            candidate_eval=candidate_eval,
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            materialization_manifest_path=tampered_manifest,
        )


def test_next_iteration_seed_uses_only_previous_approved_policy_as_baseline(tmp_path: Path):
    decision = _decision(tmp_path)

    seed = build_next_iteration_seed(decision, next_holdout_generation_id="holdout:generation-2:test")

    assert seed["baseline_hash"] == decision["candidate_skill_hash"]
    assert seed["baseline_source"] == "approved_policy_export"
    assert seed["reward_memory_file_anchor"] == decision["approved_policy_artifact_file_hash"]
    assert seed["previous_holdout_generation_id"] != seed["next_holdout_generation_id"]
    assert seed["holdout_reuse_policy"] == "rotate_holdout_generation_keep_test_split_read_only_no_training"


def test_next_iteration_seed_rejects_non_accepted_decision(tmp_path: Path):
    decision = _decision(tmp_path)
    rejected = {**decision, "status": "rejected", "reward": 0.0}

    with pytest.raises(ValidationError, match="accepted optimizer decision"):
        build_next_iteration_seed(rejected, next_holdout_generation_id="holdout:generation-2:test")

    with pytest.raises(ValidationError, match="rotated holdout generation"):
        build_next_iteration_seed(
            decision,
            next_holdout_generation_id=decision["holdout_lineage"]["generation_id"],
        )


def test_next_iteration_seed_rejects_tampered_operating_contract(tmp_path: Path):
    decision = _decision(tmp_path)
    seed = build_next_iteration_seed(decision, next_holdout_generation_id="holdout:generation-2:test")

    from src.search_eval.continuous_optimizer import validate_next_iteration_seed

    with pytest.raises(ValidationError, match="baseline_source"):
        validate_next_iteration_seed({**seed, "baseline_source": "manual_override"})
    with pytest.raises(ValidationError, match="reward_memory_file_anchor"):
        validate_next_iteration_seed({**seed, "reward_memory_file_anchor": "not-a-digest"})
    with pytest.raises(ValidationError, match="scope"):
        validate_next_iteration_seed({**seed, "scope": "hyde_prompt_promotion"})
    with pytest.raises(ValidationError, match="holdout"):
        validate_next_iteration_seed({**seed, "holdout_reuse_policy": "reuse_test_for_training"})

    tampered_decision = {
        **decision,
        "holdout_lineage": {**decision["holdout_lineage"], "reuse_as_training": True},
    }
    with pytest.raises(ValidationError, match="training reward"):
        build_next_iteration_seed(tampered_decision, next_holdout_generation_id="holdout:generation-2:test")


def test_run_continuous_optimization_iteration_writes_operating_artifacts(tmp_path: Path):
    artifact, baseline_eval, candidate_eval, manifest_path, artifact_path = _approved_policy(tmp_path)
    approval = {
        "approved_by": "search-quality-owner",
        "approved_at": artifact["created_at"],
        "expires_at": "2999-01-01T00:00:00Z",
        "artifact_hash": canonical_file_hash(artifact_path),
    }

    result = run_continuous_optimization_iteration(
        run_id="run-iteration-001",
        output_dir=tmp_path / "iteration",
        approved_policy_artifact_path=artifact_path,
        baseline_eval=baseline_eval,
        candidate_eval=candidate_eval,
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        materialization_manifest_path=manifest_path,
        reward_memory_path=tmp_path / "reward-memory.jsonl",
        next_holdout_generation_id="holdout:generation-2:test",
        manual_approval=approval,
        rollback_sla_minutes=15,
    )

    validate_continuous_iteration_manifest(result["manifest"])
    assert Path(result["manifest_path"]).exists()
    assert Path(result["manifest"]["decision_record_path"]).exists()
    assert Path(result["manifest"]["reward_memory_entry_path"]).exists()
    assert Path(result["manifest"]["next_iteration_seed_path"]).exists()
    assert Path(result["manifest"]["live_canary_handoff_path"]).exists()
    assert result["decision"]["run_id"] == "run-iteration-001"
    assert result["reward_entry"]["skill_hash"] == result["decision"]["candidate_skill_hash"]
    assert result["next_iteration_seed"]["baseline_hash"] == result["decision"]["candidate_skill_hash"]
    assert result["live_canary_handoff"]["rollout_fraction"] == 0.0
    assert (tmp_path / "reward-memory.jsonl").read_text(encoding="utf-8").count("run-iteration-001") == 1

    tampered_manifest = {**result["manifest"], "decision_record_hash": "sha256:" + "0" * 64}
    with pytest.raises(ValidationError, match="decision_record hash mismatch"):
        validate_continuous_iteration_manifest(tampered_manifest)

    with pytest.raises(ValidationError, match="duplicate run_id"):
        run_continuous_optimization_iteration(
            run_id="run-iteration-001",
            output_dir=tmp_path / "iteration-duplicate",
            approved_policy_artifact_path=artifact_path,
            baseline_eval=baseline_eval,
            candidate_eval=candidate_eval,
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            materialization_manifest_path=manifest_path,
            reward_memory_path=tmp_path / "reward-memory.jsonl",
            next_holdout_generation_id="holdout:generation-3:test",
        )


def test_run_continuous_optimization_iteration_requires_complete_canary_inputs(tmp_path: Path):
    _artifact, baseline_eval, candidate_eval, manifest_path, artifact_path = _approved_policy(tmp_path)

    with pytest.raises(ValidationError, match="manual_approval"):
        run_continuous_optimization_iteration(
            run_id="run-iteration-no-approval",
            output_dir=tmp_path / "iteration",
            approved_policy_artifact_path=artifact_path,
            baseline_eval=baseline_eval,
            candidate_eval=candidate_eval,
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            materialization_manifest_path=manifest_path,
            reward_memory_path=tmp_path / "reward-memory.jsonl",
            next_holdout_generation_id="holdout:generation-2:test",
            rollback_sla_minutes=15,
        )


def test_run_continuous_optimization_iteration_does_not_append_on_downstream_failure(tmp_path: Path):
    _artifact, baseline_eval, candidate_eval, manifest_path, artifact_path = _approved_policy(tmp_path)
    reward_memory = tmp_path / "reward-memory.jsonl"

    with pytest.raises(ValidationError, match="manual_approval"):
        run_continuous_optimization_iteration(
            run_id="bad-canary",
            output_dir=tmp_path / "bad-iteration",
            approved_policy_artifact_path=artifact_path,
            baseline_eval=baseline_eval,
            candidate_eval=candidate_eval,
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            materialization_manifest_path=manifest_path,
            reward_memory_path=reward_memory,
            next_holdout_generation_id="holdout:generation-2:test",
            rollback_sla_minutes=15,
        )

    assert not reward_memory.exists()


def test_reward_memory_rejects_forged_reward_value(tmp_path: Path):
    artifact, baseline_eval, candidate_eval, manifest_path, artifact_path = _approved_policy(tmp_path)
    decision = build_optimizer_decision_record(
        run_id="run-forged-reward",
        approved_policy_artifact=artifact,
        baseline_eval=baseline_eval,
        candidate_eval=candidate_eval,
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        materialization_manifest_path=manifest_path,
    )
    forged = {**decision, "reward": 999.0}

    with pytest.raises(ValidationError, match="reward"):
        append_reward_memory_entry(tmp_path / "memory.jsonl", forged, approved_policy_artifact_path=artifact_path)


def test_live_canary_handoff_requires_manual_approval_and_stale_hash_check(tmp_path: Path):
    _artifact, _baseline_eval, _candidate_eval, _manifest_path, artifact_path = _approved_policy(tmp_path)
    approval = {
        "approved_by": "search-quality-owner",
        "approved_at": _artifact["created_at"],
        "expires_at": "2999-01-01T00:00:00Z",
        "artifact_hash": canonical_file_hash(artifact_path),
    }

    handoff = build_live_canary_handoff(
        approved_policy_artifact_path=artifact_path,
        manual_approval=approval,
        rollback_sla_minutes=15,
    )
    validate_live_canary_handoff(handoff)
    assert handoff["rollout_fraction"] == 0.0
    assert handoff["state"] == "manual_approval_required_before_enablement"

    tampered_sla = {**handoff, "rollback_sla_minutes": 999}
    with pytest.raises(ValidationError, match="rollback_sla"):
        validate_live_canary_handoff(tampered_sla)

    expired_handoff = {
        **handoff,
        "created_at": "2026-07-04T13:00:00Z",
        "manual_approval": {
            **handoff["manual_approval"],
            "approved_at": "1999-01-01T00:00:00Z",
            "expires_at": "2000-01-01T00:00:00Z",
        },
    }
    with pytest.raises(ValidationError, match="stale|expiry"):
        validate_live_canary_handoff(expired_handoff)

    stale_time = {**approval, "approved_at": "1999-01-01T00:00:00Z"}
    with pytest.raises(ValidationError, match="stale"):
        build_live_canary_handoff(
            approved_policy_artifact_path=artifact_path,
            manual_approval=stale_time,
            rollback_sla_minutes=15,
        )

    stale = {**approval, "artifact_hash": "sha256:" + "0" * 64}
    with pytest.raises(ValidationError, match="stale"):
        build_live_canary_handoff(
            approved_policy_artifact_path=artifact_path,
            manual_approval=stale,
            rollback_sla_minutes=15,
        )

    with pytest.raises(ValidationError, match="rollback_sla"):
        build_live_canary_handoff(
            approved_policy_artifact_path=artifact_path,
            manual_approval=approval,
            rollback_sla_minutes=120,
        )
