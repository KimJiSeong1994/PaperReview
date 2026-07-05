from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.deep_review_eval import cron_runner

_DEEP_REVIEW_CRON_ENV = (
    "SKILLOPT_DEEP_REVIEW_DATASET",
    "SKILLOPT_DEEP_REVIEW_CONTROL",
    "SKILLOPT_DEEP_REVIEW_CANDIDATE_ARTIFACT",
    "SKILLOPT_DEEP_REVIEW_ROLLBACK_RECORD",
    "SKILLOPT_DEEP_REVIEW_OPTIMIZER_STRICT",
    "SKILLOPT_DEEP_REVIEW_POLICY_ENABLED",
    "SKILLOPT_DEEP_REVIEW_POLICY_PATH",
    "SKILLOPT_DEEP_REVIEW_POLICY_HASH",
    "SKILLOPT_DEEP_REVIEW_POLICY_SCOPE",
)


def _clear_env(monkeypatch) -> None:
    for name in _DEEP_REVIEW_CRON_ENV:
        monkeypatch.delenv(name, raising=False)


def _policy_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_default_deep_review_skillopt_cron_guard_completes(monkeypatch, capsys):
    _clear_env(monkeypatch)

    assert cron_runner.main([]) == 0

    message = json.loads(capsys.readouterr().out)
    assert message["status"] == "complete"
    assert message["scope"] == "deep_review_analysis_prompt"
    assert message["runtime_policy_enabled"] is False
    assert message["runtime_policy_hash"] == ""


def test_deep_review_skillopt_cron_guard_validates_enabled_policy(monkeypatch, capsys):
    _clear_env(monkeypatch)
    policy = Path("docs/skillopt_deep_review/baseline_skill.md").resolve()
    digest = _policy_hash(policy)
    monkeypatch.setenv("SKILLOPT_DEEP_REVIEW_POLICY_ENABLED", "true")
    monkeypatch.setenv("SKILLOPT_DEEP_REVIEW_POLICY_PATH", str(policy))
    monkeypatch.setenv("SKILLOPT_DEEP_REVIEW_POLICY_HASH", digest)
    monkeypatch.setenv("SKILLOPT_DEEP_REVIEW_POLICY_SCOPE", "deep_review_analysis_prompt")

    assert cron_runner.main([]) == 0

    message = json.loads(capsys.readouterr().out)
    assert message["status"] == "complete"
    assert message["runtime_policy_enabled"] is True
    assert message["runtime_policy_hash"] == digest


def test_deep_review_skillopt_cron_guard_strict_fails_on_missing_artifact(monkeypatch, capsys):
    _clear_env(monkeypatch)

    result = cron_runner.main([
        "--candidate-artifact",
        "data/deep_review_eval/missing-candidate.json",
        "--strict",
    ])

    assert result == 2
    message = json.loads(capsys.readouterr().out)
    assert message["status"] == "failed"
    assert "missing-candidate.json" in message["reason"]
