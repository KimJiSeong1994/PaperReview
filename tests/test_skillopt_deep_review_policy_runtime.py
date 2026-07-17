"""Runtime SkillOpt policy gate tests for DeepReview."""
from __future__ import annotations

import hashlib
import importlib
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.DeepAgent import deep_review_agent as deep_review_module
from app.DeepAgent.skillopt_policy import (
    SKILLOPT_DEEP_REVIEW_POLICY_ENABLED_ENV,
    SKILLOPT_DEEP_REVIEW_POLICY_HASH_ENV,
    SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV,
    SKILLOPT_DEEP_REVIEW_POLICY_SCOPE,
    SKILLOPT_DEEP_REVIEW_POLICY_SCOPE_ENV,
    SkillOptDeepReviewPolicyError,
    build_skillopt_deep_review_policy_prompt_block,
    load_skillopt_deep_review_policy_from_env,
)

ENV_VARS = (
    SKILLOPT_DEEP_REVIEW_POLICY_ENABLED_ENV,
    SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV,
    SKILLOPT_DEEP_REVIEW_POLICY_HASH_ENV,
    SKILLOPT_DEEP_REVIEW_POLICY_SCOPE_ENV,
)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch):
    _clear_env(monkeypatch)
    yield
    _clear_env(monkeypatch)


def _policy_text() -> str:
    return Path("docs/skillopt_deep_review/baseline_skill.md").read_text(encoding="utf-8")


def _write_policy(tmp_path: Path, text: str | None = None) -> tuple[Path, str]:
    content = text if text is not None else _policy_text()
    path = tmp_path / "deep_review_skillopt_policy.md"
    path.write_text(content, encoding="utf-8")
    return path, hashlib.sha256(content.encode("utf-8")).hexdigest()


class _FakeLLM:
    def __init__(self):
        self.prompts: list[str] = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(content="analysis body")


def _paper() -> dict:
    return {
        "id": "paper-1",
        "title": "Graph RAG for Reviews",
        "authors": ["A. Author"],
        "year": 2026,
        "abstract": "We propose graph retrieval augmented generation with ablations.",
    }


def test_loader_returns_disabled_when_env_absent() -> None:
    policy = load_skillopt_deep_review_policy_from_env({})

    assert policy.enabled is False
    assert build_skillopt_deep_review_policy_prompt_block(policy) == ""


def test_loader_accepts_hash_pinned_absolute_policy(tmp_path: Path) -> None:
    path, digest = _write_policy(tmp_path)

    policy = load_skillopt_deep_review_policy_from_env(
        {
            SKILLOPT_DEEP_REVIEW_POLICY_ENABLED_ENV: "true",
            SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV: str(path),
            SKILLOPT_DEEP_REVIEW_POLICY_HASH_ENV: f"sha256:{digest}",
        }
    )

    assert policy.enabled is True
    assert policy.scope == SKILLOPT_DEEP_REVIEW_POLICY_SCOPE
    block = build_skillopt_deep_review_policy_prompt_block(policy)
    assert f"sha256:{digest}" in block
    assert "DeepReview analysis prompt path" in block


def test_loader_rejects_symlink_policy_path(tmp_path: Path) -> None:
    path, digest = _write_policy(tmp_path)
    symlink = tmp_path / "deep-review-policy-link.md"
    symlink.symlink_to(path)

    with pytest.raises(SkillOptDeepReviewPolicyError, match="Failed to open|must not be a symlink"):
        load_skillopt_deep_review_policy_from_env(
            {
                SKILLOPT_DEEP_REVIEW_POLICY_ENABLED_ENV: "true",
                SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV: str(symlink),
                SKILLOPT_DEEP_REVIEW_POLICY_HASH_ENV: digest,
            }
        )


def test_loader_rejects_missing_hash_wrong_scope_relative_path_and_unsafe_content(tmp_path: Path) -> None:
    path, digest = _write_policy(tmp_path)
    with pytest.raises(SkillOptDeepReviewPolicyError, match=SKILLOPT_DEEP_REVIEW_POLICY_HASH_ENV):
        load_skillopt_deep_review_policy_from_env(
            {
                SKILLOPT_DEEP_REVIEW_POLICY_ENABLED_ENV: "true",
                SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV: str(path),
            }
        )
    with pytest.raises(SkillOptDeepReviewPolicyError, match="absolute path"):
        load_skillopt_deep_review_policy_from_env(
            {
                SKILLOPT_DEEP_REVIEW_POLICY_ENABLED_ENV: "true",
                SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV: "relative.md",
                SKILLOPT_DEEP_REVIEW_POLICY_HASH_ENV: f"sha256:{digest}",
            }
        )
    with pytest.raises(SkillOptDeepReviewPolicyError, match=SKILLOPT_DEEP_REVIEW_POLICY_SCOPE_ENV):
        load_skillopt_deep_review_policy_from_env(
            {
                SKILLOPT_DEEP_REVIEW_POLICY_ENABLED_ENV: "true",
                SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV: str(path),
                SKILLOPT_DEEP_REVIEW_POLICY_HASH_ENV: f"sha256:{digest}",
                SKILLOPT_DEEP_REVIEW_POLICY_SCOPE_ENV: "query_analyzer_standard_search",
            }
        )
    unsafe, unsafe_digest = _write_policy(tmp_path, "unsafe policy")
    with pytest.raises(SkillOptDeepReviewPolicyError, match="required v1 safety phrases"):
        load_skillopt_deep_review_policy_from_env(
            {
                SKILLOPT_DEEP_REVIEW_POLICY_ENABLED_ENV: "true",
                SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV: str(unsafe),
                SKILLOPT_DEEP_REVIEW_POLICY_HASH_ENV: f"sha256:{unsafe_digest}",
            }
        )


def test_deep_review_prompt_is_unchanged_when_policy_disabled() -> None:
    llm = _FakeLLM()
    with patch.object(deep_review_module, "get_llm", return_value=llm):
        raw = deep_review_module.analyze_paper_deep.invoke({"paper_json": json.dumps(_paper())})

    payload = json.loads(raw)
    assert payload["analysis"] == "analysis body"
    assert len(llm.prompts) == 1
    assert "SkillOpt optimized policy" not in llm.prompts[0]


def test_deep_review_policy_is_injected_only_with_valid_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path, digest = _write_policy(tmp_path)
    monkeypatch.setenv(SKILLOPT_DEEP_REVIEW_POLICY_ENABLED_ENV, "true")
    monkeypatch.setenv(SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV, str(path))
    monkeypatch.setenv(SKILLOPT_DEEP_REVIEW_POLICY_HASH_ENV, f"sha256:{digest}")
    llm = _FakeLLM()

    with patch.object(deep_review_module, "get_llm", return_value=llm):
        raw = deep_review_module.analyze_paper_deep.invoke({"paper_json": json.dumps(_paper())})

    payload = json.loads(raw)
    assert payload["success"] is True
    assert "SkillOpt optimized policy" in llm.prompts[0]
    assert f"sha256:{digest}" in llm.prompts[0]
    assert "Do not bypass fact verification" in llm.prompts[0]


def test_invalid_enabled_policy_fails_closed_with_warning(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path, _digest = _write_policy(tmp_path)
    monkeypatch.setenv(SKILLOPT_DEEP_REVIEW_POLICY_ENABLED_ENV, "true")
    monkeypatch.setenv(SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV, str(path))
    monkeypatch.setenv(SKILLOPT_DEEP_REVIEW_POLICY_HASH_ENV, "sha256:" + "0" * 64)
    llm = _FakeLLM()

    with caplog.at_level(logging.WARNING, logger="app.DeepAgent.deep_review_agent"):
        with patch.object(deep_review_module, "get_llm", return_value=llm):
            raw = deep_review_module.analyze_paper_deep.invoke({"paper_json": json.dumps(_paper())})

    payload = json.loads(raw)
    assert payload["success"] is True
    assert "SkillOpt optimized policy" not in llm.prompts[0]
    assert any("SkillOpt DeepReview policy disabled" in rec.message for rec in caplog.records)


def test_deep_review_policy_path_does_not_import_dev_eval(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path, digest = _write_policy(tmp_path)
    monkeypatch.setenv(SKILLOPT_DEEP_REVIEW_POLICY_ENABLED_ENV, "true")
    monkeypatch.setenv(SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV, str(path))
    monkeypatch.setenv(SKILLOPT_DEEP_REVIEW_POLICY_HASH_ENV, f"sha256:{digest}")

    class DeepReviewEvalImportBlocker:
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith("src.deep_review_eval") or fullname.startswith("deep_review_eval"):
                raise AssertionError(f"production policy imported {fullname}")
            return None

    blocker = DeepReviewEvalImportBlocker()
    sys.meta_path.insert(0, blocker)
    try:
        importlib.reload(deep_review_module)
        llm = _FakeLLM()
        with patch.object(deep_review_module, "get_llm", return_value=llm):
            raw = deep_review_module.analyze_paper_deep.invoke({"paper_json": json.dumps(_paper())})
    finally:
        sys.meta_path.remove(blocker)
        importlib.reload(deep_review_module)

    assert json.loads(raw)["success"] is True
    assert "SkillOpt optimized policy" in llm.prompts[0]
