from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.search_eval.approved_policy import (
    ValidatedApprovedSkillOptPolicy,
    export_approved_skillopt_policy,
)
from src.search_eval.cron_runner import main
from src.search_eval.release_holdout import RELEASE_HOLDOUT_AUTHORITY_CONTEXT_ENV
from src.search_eval.skillopt_contract import ValidationError
from tests.skillopt_acceptance_fixtures import publish_accepted_candidate
from tests.test_skillopt_continuous_optimizer import (
    BASELINE_SKILL,
    CONTROL,
    DATASET,
    _candidate_best_skill,
    _evals,
    _two_stage_eval_inputs,
)


@pytest.fixture(autouse=True)
def _scope_release_holdout_authority_env(monkeypatch: pytest.MonkeyPatch):
    """Prevent imported optimizer fixtures from leaking authority configuration."""
    monkeypatch.delenv(RELEASE_HOLDOUT_AUTHORITY_CONTEXT_ENV, raising=False)
    yield


def _approved_policy_for_cron(
    tmp_path: Path,
) -> tuple[ValidatedApprovedSkillOptPolicy, dict, dict, Path]:
    best_skill = _candidate_best_skill(tmp_path)
    baseline_eval, candidate_eval = _evals(best_skill)
    accepted = publish_accepted_candidate(
        parent=tmp_path,
        best_skill_path=best_skill,
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
    )
    artifact = export_approved_skillopt_policy(
        **accepted,
        output_dir=tmp_path / "approved",
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        **_two_stage_eval_inputs(
            baseline_eval, candidate_eval, tmp_path=tmp_path, best_skill=best_skill
        ),
        minimum_ndcg_delta=0.01,
    )
    return artifact, baseline_eval, candidate_eval, artifact.artifact_path


def test_skillopt_cron_runner_skips_when_artifacts_are_not_configured(
    capsys, monkeypatch
):
    for env_name in (
        "SKILLOPT_APPROVED_POLICY_ARTIFACT",
        "SKILLOPT_BASELINE_EVAL",
        "SKILLOPT_CANDIDATE_EVAL",
    ):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("SKILLOPT_MATERIALIZATION_MANIFEST", "obsolete-v0.json")

    assert main([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "SKIPPED"
    assert payload["missing_env"] == [
        "SKILLOPT_APPROVED_POLICY_ARTIFACT",
        "SKILLOPT_BASELINE_EVAL",
        "SKILLOPT_CANDIDATE_EVAL",
    ]
    assert "SKILLOPT_MATERIALIZATION_MANIFEST" not in payload["missing_env"]


def test_skillopt_cron_runner_strict_missing_config_fails(capsys, monkeypatch):
    for env_name in (
        "SKILLOPT_APPROVED_POLICY_ARTIFACT",
        "SKILLOPT_BASELINE_EVAL",
        "SKILLOPT_CANDIDATE_EVAL",
    ):
        monkeypatch.delenv(env_name, raising=False)

    assert main(["--strict"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "SKIPPED"


def test_skillopt_cron_runner_rejects_removed_materialization_manifest_flag():
    with pytest.raises(SystemExit) as exc_info:
        main(["--materialization-manifest", "obsolete-v0.json"])

    assert exc_info.value.code == 2


def test_skillopt_cron_runner_executes_configured_iteration(tmp_path: Path, capsys):
    artifact, baseline_eval, candidate_eval, artifact_path = _approved_policy_for_cron(
        tmp_path
    )
    assert artifact["version"] == "approved-skillopt-policy-v3"
    baseline_eval_path = tmp_path / "baseline_eval.json"
    candidate_eval_path = tmp_path / "candidate_eval.json"
    baseline_eval_path.write_text(json.dumps(baseline_eval), encoding="utf-8")
    candidate_eval_path.write_text(json.dumps(candidate_eval), encoding="utf-8")
    reward_memory_path = tmp_path / "reward-memory.jsonl"

    status = main(
        [
            "--approved-policy-artifact",
            str(artifact_path),
            "--baseline-eval",
            str(baseline_eval_path),
            "--candidate-eval",
            str(candidate_eval_path),
            "--output-dir",
            str(tmp_path / "runs"),
            "--reward-memory",
            str(reward_memory_path),
            "--run-id",
            "skillopt-cron-test",
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "complete"
    assert payload["run_id"] == "skillopt-cron-test"
    assert "materialization_manifest_path" not in payload
    assert Path(payload["manifest_path"]).exists()
    assert Path(payload["summary_path"]).exists()
    assert reward_memory_path.exists()


def test_skillopt_cron_runner_rejects_removed_holdout_generation_flag():
    with pytest.raises(SystemExit) as exc_info:
        main(["--next-holdout-generation-id", "forbidden"])

    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "run_id", ["../escape", "/absolute", "a/b", r"a\b", ".", "..", "실행"]
)
def test_skillopt_cron_runner_rejects_unsafe_run_id_before_path_join(run_id: str):
    with pytest.raises(ValidationError, match="run_id"):
        main(
            [
                "--approved-policy-artifact",
                "unused.json",
                "--baseline-eval",
                "unused.json",
                "--candidate-eval",
                "unused.json",
                "--run-id",
                run_id,
            ]
        )
