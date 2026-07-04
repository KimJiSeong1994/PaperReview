from __future__ import annotations

import json
from pathlib import Path

from src.search_eval.cron_runner import main
from tests.test_skillopt_continuous_optimizer import _approved_policy


def test_skillopt_cron_runner_skips_when_artifacts_are_not_configured(capsys):
    assert main([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "SKIPPED"
    assert "SKILLOPT_APPROVED_POLICY_ARTIFACT" in payload["missing_env"]


def test_skillopt_cron_runner_strict_missing_config_fails(capsys):
    assert main(["--strict"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "SKIPPED"


def test_skillopt_cron_runner_executes_configured_iteration(tmp_path: Path, capsys):
    _artifact, baseline_eval, candidate_eval, manifest_path, artifact_path = _approved_policy(tmp_path)
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
            "--materialization-manifest",
            str(manifest_path),
            "--output-dir",
            str(tmp_path / "runs"),
            "--reward-memory",
            str(reward_memory_path),
            "--run-id",
            "skillopt-cron-test",
            "--next-holdout-generation-id",
            "holdout:skillopt-cron-test:next",
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "complete"
    assert payload["run_id"] == "skillopt-cron-test"
    assert Path(payload["manifest_path"]).exists()
    assert Path(payload["summary_path"]).exists()
    assert reward_memory_path.exists()
