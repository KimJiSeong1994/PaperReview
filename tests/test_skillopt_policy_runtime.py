"""Runtime SkillOpt policy gate tests for QueryAnalyzer search."""
from __future__ import annotations

import hashlib
import importlib
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.QueryAgent import query_analyzer as query_analyzer_module
from app.QueryAgent.query_analyzer import QueryAnalyzer
from app.QueryAgent.skillopt_policy import (
    SKILLOPT_POLICY_ENABLED_ENV,
    SKILLOPT_POLICY_HASH_ENV,
    SKILLOPT_POLICY_PATH_ENV,
    SKILLOPT_POLICY_SCOPE,
    SKILLOPT_POLICY_SCOPE_ENV,
    SkillOptPolicyError,
    build_skillopt_policy_prompt_block,
    load_skillopt_policy_from_env,
)


SKILLOPT_ENV_VARS = (
    SKILLOPT_POLICY_ENABLED_ENV,
    SKILLOPT_POLICY_PATH_ENV,
    SKILLOPT_POLICY_HASH_ENV,
    SKILLOPT_POLICY_SCOPE_ENV,
)


def _clear_skillopt_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SKILLOPT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _clear_query_cache() -> None:
    with query_analyzer_module._analysis_cache_lock:
        query_analyzer_module._analysis_cache.clear()


def _policy_text() -> str:
    return Path("docs/skillopt_search/baseline_skill.md").read_text(encoding="utf-8")


def _write_policy(tmp_path: Path, text: str | None = None) -> tuple[Path, str]:
    content = text if text is not None else _policy_text()
    path = tmp_path / "skillopt_policy.md"
    path.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return path, digest


def _llm_response(query: str, *, marker: str = "baseline") -> MagicMock:
    payload = {
        "is_academic": True,
        "intent": "paper_search",
        "keywords": [marker, "graph", "rag"],
        "core_concepts": ["graph retrieval augmented generation"],
        "research_area": "Information Retrieval",
        "improved_query": f"{query} {marker}",
        "search_strategy": "keyword search",
        "search_filters": {"year_start": None, "year_end": None, "category": None},
        "confidence": 0.86,
        "source_queries": {
            "arxiv": "ti:graph OR abs:rag",
            "dblp": "graph rag",
            "google_scholar": [
                "graph rag survey",
                "graph retrieval augmented generation",
            ],
        },
    }
    choice = SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))
    return SimpleNamespace(choices=[choice])


@pytest.fixture(autouse=True)
def _isolated_env_and_cache(monkeypatch: pytest.MonkeyPatch):
    _clear_skillopt_env(monkeypatch)
    _clear_query_cache()
    yield
    _clear_query_cache()


class TestSkillOptPolicyLoader:
    def test_policy_loader_returns_disabled_when_env_absent(self) -> None:
        policy = load_skillopt_policy_from_env({})

        assert policy.enabled is False
        assert build_skillopt_policy_prompt_block(policy) == ""

    def test_policy_loader_accepts_sha256_prefix_and_plain_hex(self, tmp_path: Path) -> None:
        path, digest = _write_policy(tmp_path)

        with_prefix = load_skillopt_policy_from_env(
            {
                SKILLOPT_POLICY_ENABLED_ENV: "true",
                SKILLOPT_POLICY_PATH_ENV: str(path),
                SKILLOPT_POLICY_HASH_ENV: f"sha256:{digest}",
            }
        )
        plain = load_skillopt_policy_from_env(
            {
                SKILLOPT_POLICY_ENABLED_ENV: "1",
                SKILLOPT_POLICY_PATH_ENV: str(path),
                SKILLOPT_POLICY_HASH_ENV: digest,
            }
        )

        assert with_prefix.enabled is True
        assert plain.content_hash == f"sha256:{digest}"
        assert SKILLOPT_POLICY_SCOPE in build_skillopt_policy_prompt_block(plain)

    def test_policy_loader_rejects_missing_path_hash_and_mismatch(self, tmp_path: Path) -> None:
        path, digest = _write_policy(tmp_path)

        with pytest.raises(SkillOptPolicyError, match=SKILLOPT_POLICY_PATH_ENV):
            load_skillopt_policy_from_env(
                {
                    SKILLOPT_POLICY_ENABLED_ENV: "true",
                    SKILLOPT_POLICY_HASH_ENV: f"sha256:{digest}",
                }
            )
        with pytest.raises(SkillOptPolicyError, match=SKILLOPT_POLICY_HASH_ENV):
            load_skillopt_policy_from_env(
                {
                    SKILLOPT_POLICY_ENABLED_ENV: "true",
                    SKILLOPT_POLICY_PATH_ENV: str(path),
                }
            )
        with pytest.raises(SkillOptPolicyError, match="hash mismatch"):
            load_skillopt_policy_from_env(
                {
                    SKILLOPT_POLICY_ENABLED_ENV: "true",
                    SKILLOPT_POLICY_PATH_ENV: str(path),
                    SKILLOPT_POLICY_HASH_ENV: "sha256:" + "0" * 64,
                }
            )

    def test_policy_loader_rejects_relative_path(self, tmp_path: Path) -> None:
        _path, digest = _write_policy(tmp_path)

        with pytest.raises(SkillOptPolicyError, match="absolute path"):
            load_skillopt_policy_from_env(
                {
                    SKILLOPT_POLICY_ENABLED_ENV: "true",
                    SKILLOPT_POLICY_PATH_ENV: "relative_policy.md",
                    SKILLOPT_POLICY_HASH_ENV: f"sha256:{digest}",
                }
            )

    def test_policy_loader_rejects_wrong_scope_and_unsafe_content(self, tmp_path: Path) -> None:
        path, digest = _write_policy(tmp_path)
        with pytest.raises(SkillOptPolicyError, match=SKILLOPT_POLICY_SCOPE_ENV):
            load_skillopt_policy_from_env(
                {
                    SKILLOPT_POLICY_ENABLED_ENV: "true",
                    SKILLOPT_POLICY_PATH_ENV: str(path),
                    SKILLOPT_POLICY_HASH_ENV: f"sha256:{digest}",
                    SKILLOPT_POLICY_SCOPE_ENV: "hyde_prompt_promotion",
                }
            )

        bad_path, bad_digest = _write_policy(tmp_path, "unsafe prompt without gates")
        with pytest.raises(SkillOptPolicyError, match="required v1 safety phrases"):
            load_skillopt_policy_from_env(
                {
                    SKILLOPT_POLICY_ENABLED_ENV: "true",
                    SKILLOPT_POLICY_PATH_ENV: str(bad_path),
                    SKILLOPT_POLICY_HASH_ENV: f"sha256:{bad_digest}",
                }
            )


class TestQueryAnalyzerSkillOptRuntimeGate:
    def _run_analyze(
        self,
        query: str,
        response: MagicMock,
        *,
        apply_skillopt_policy: bool = False,
    ) -> tuple[dict, str]:
        analyzer = QueryAnalyzer(api_key="fake-key")
        analyzer.client = object()
        captured: dict[str, object] = {}

        def fake_completion(*args, **kwargs):
            captured.update(kwargs)
            return response

        with patch.object(query_analyzer_module, "create_chat_completion", side_effect=fake_completion):
            result = analyzer.analyze_and_prepare(
                query, apply_skillopt_policy=apply_skillopt_policy
            )

        messages = captured["messages"]
        assert isinstance(messages, list)
        return result, messages[0]["content"]

    def test_default_behavior_is_unchanged_when_skillopt_env_absent(self) -> None:
        result, system_prompt = self._run_analyze(
            "graph rag", _llm_response("graph rag", marker="baseline")
        )

        assert result["keywords"][0] == "baseline"
        assert "SkillOpt optimized policy" not in system_prompt
        assert "Policy provenance" not in system_prompt

    def test_policy_not_injected_when_flag_false_even_with_path_and_hash(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path, digest = _write_policy(tmp_path)
        monkeypatch.setenv(SKILLOPT_POLICY_ENABLED_ENV, "false")
        monkeypatch.setenv(SKILLOPT_POLICY_PATH_ENV, str(path))
        monkeypatch.setenv(SKILLOPT_POLICY_HASH_ENV, f"sha256:{digest}")

        result, system_prompt = self._run_analyze(
            "graph rag",
            _llm_response("graph rag", marker="baseline"),
            apply_skillopt_policy=True,
        )

        assert result["keywords"][0] == "baseline"
        assert "SkillOpt optimized policy" not in system_prompt

    def test_policy_not_injected_for_generic_call_even_when_env_valid(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path, digest = _write_policy(tmp_path)
        monkeypatch.setenv(SKILLOPT_POLICY_ENABLED_ENV, "true")
        monkeypatch.setenv(SKILLOPT_POLICY_PATH_ENV, str(path))
        monkeypatch.setenv(SKILLOPT_POLICY_HASH_ENV, f"sha256:{digest}")

        result, system_prompt = self._run_analyze(
            "graph rag", _llm_response("graph rag", marker="baseline")
        )

        assert result["keywords"][0] == "baseline"
        assert "SkillOpt optimized policy" not in system_prompt

    def test_policy_injected_only_with_explicit_flag_path_and_hash(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path, digest = _write_policy(tmp_path)
        monkeypatch.setenv(SKILLOPT_POLICY_ENABLED_ENV, "true")
        monkeypatch.setenv(SKILLOPT_POLICY_PATH_ENV, str(path))
        monkeypatch.setenv(SKILLOPT_POLICY_HASH_ENV, f"sha256:{digest}")

        result, system_prompt = self._run_analyze(
            "graph rag",
            _llm_response("graph rag", marker="skillopt"),
            apply_skillopt_policy=True,
        )

        assert result["keywords"][0] == "skillopt"
        assert system_prompt.count("SkillOpt optimized policy") == 1
        assert f"sha256:{digest}" in system_prompt
        assert "QueryAnalyzer standard search path" in system_prompt
        assert "Do not enable `use_llm_search`" in system_prompt

    def test_invalid_enabled_policy_fails_closed_with_visible_warning(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path, _digest = _write_policy(tmp_path)
        monkeypatch.setenv(SKILLOPT_POLICY_ENABLED_ENV, "true")
        monkeypatch.setenv(SKILLOPT_POLICY_PATH_ENV, str(path))
        monkeypatch.setenv(SKILLOPT_POLICY_HASH_ENV, "sha256:" + "0" * 64)

        with caplog.at_level(logging.WARNING, logger="app.QueryAgent.query_analyzer"):
            result, system_prompt = self._run_analyze(
                "graph rag",
                _llm_response("graph rag", marker="baseline"),
                apply_skillopt_policy=True,
            )

        assert result["keywords"][0] == "baseline"
        assert "SkillOpt optimized policy" not in system_prompt
        assert any("SkillOpt search policy disabled" in rec.message for rec in caplog.records)

    def test_policy_application_does_not_poison_default_cache(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path, digest = _write_policy(tmp_path)
        monkeypatch.setenv(SKILLOPT_POLICY_ENABLED_ENV, "true")
        monkeypatch.setenv(SKILLOPT_POLICY_PATH_ENV, str(path))
        monkeypatch.setenv(SKILLOPT_POLICY_HASH_ENV, f"sha256:{digest}")

        analyzer = QueryAnalyzer(api_key="fake-key")
        analyzer.client = object()
        completion = MagicMock(
            side_effect=[
                _llm_response("graph rag", marker="skillopt"),
                _llm_response("graph rag", marker="baseline"),
            ]
        )
        with patch.object(query_analyzer_module, "create_chat_completion", completion):
            enabled_result = analyzer.analyze_and_prepare(
                "graph rag", apply_skillopt_policy=True
            )
            monkeypatch.setenv(SKILLOPT_POLICY_ENABLED_ENV, "false")
            disabled_result = analyzer.analyze_and_prepare(
                "graph rag", apply_skillopt_policy=True
            )

        assert enabled_result["keywords"][0] == "skillopt"
        assert disabled_result["keywords"][0] == "baseline"
        assert completion.call_count == 2

    def test_policy_path_does_not_import_search_eval(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path, digest = _write_policy(tmp_path)
        monkeypatch.setenv(SKILLOPT_POLICY_ENABLED_ENV, "true")
        monkeypatch.setenv(SKILLOPT_POLICY_PATH_ENV, str(path))
        monkeypatch.setenv(SKILLOPT_POLICY_HASH_ENV, f"sha256:{digest}")

        class SearchEvalImportBlocker:
            def find_spec(self, fullname, path=None, target=None):
                if fullname.startswith("src.search_eval") or fullname.startswith("search_eval"):
                    raise AssertionError(f"production policy imported {fullname}")
                return None

        blocker = SearchEvalImportBlocker()
        sys.meta_path.insert(0, blocker)
        try:
            importlib.reload(query_analyzer_module)
            analyzer = query_analyzer_module.QueryAnalyzer(api_key="fake-key")
            analyzer.client = object()
            with patch.object(
                query_analyzer_module,
                "create_chat_completion",
                return_value=_llm_response("graph rag", marker="skillopt"),
            ):
                result = analyzer.analyze_and_prepare(
                    "graph rag", apply_skillopt_policy=True
                )
        finally:
            sys.meta_path.remove(blocker)
            importlib.reload(query_analyzer_module)

        assert result["keywords"][0] == "skillopt"
