"""Model default policy tests for OpenAI model upgrades."""

from __future__ import annotations

import importlib


def _reload_defaults(monkeypatch, **env):
    for key in (
        "RESEARCH_MODEL",
        "TOOL_MODEL",
        "EVAL_MODEL",
        "EMBEDDING_MODEL",
        "KOREAN_EMBEDDING_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import src.utils.model_defaults as model_defaults

    return importlib.reload(model_defaults)


def test_literal_openai_model_defaults(monkeypatch):
    defaults = _reload_defaults(monkeypatch)

    assert defaults.DEFAULT_RESEARCH_MODEL == "gpt-5.5"
    assert defaults.DEFAULT_TOOL_MODEL == "gpt-5.4-mini"
    assert defaults.DEFAULT_EVAL_MODEL == "gpt-5.4-mini"
    assert defaults.DEFAULT_EMBEDDING_MODEL == "text-embedding-3-small"
    assert defaults.DEFAULT_KOREAN_EMBEDDING_MODEL == "text-embedding-3-large"


def test_chat_model_env_overrides_do_not_affect_embedding_dimensions(monkeypatch):
    defaults = _reload_defaults(
        monkeypatch,
        RESEARCH_MODEL="gpt-test-research",
        TOOL_MODEL="gpt-test-tool",
        EVAL_MODEL="gpt-test-eval",
        EMBEDDING_MODEL="text-embedding-override",
        KOREAN_EMBEDDING_MODEL="text-embedding-korean-override",
    )

    assert defaults.DEFAULT_RESEARCH_MODEL == "gpt-test-research"
    assert defaults.DEFAULT_TOOL_MODEL == "gpt-test-tool"
    assert defaults.DEFAULT_EVAL_MODEL == "gpt-test-eval"
    assert defaults.DEFAULT_EMBEDDING_MODEL == "text-embedding-3-small"
    assert defaults.DEFAULT_KOREAN_EMBEDDING_MODEL == "text-embedding-3-large"


def test_router_config_uses_non_overriding_dotenv_policy():
    from pathlib import Path

    config_source = Path("routers/deps/config.py").read_text()

    assert "load_dotenv(dotenv_path=env_path, override=False)" in config_source
    assert "load_dotenv(dotenv_path=env_path, override=True)" not in config_source
