"""
Tests for src/events/feature_flags.py

Each test gets an isolated SQLite DB via the FEATURE_FLAGS_DB_PATH env var
and the tmp_path pytest fixture.
"""

from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_module(monkeypatch, db_path: str):
    """
    Return a freshly-imported feature_flags module pointed at *db_path*.

    Reloading ensures module-level state (cached connections, etc.) is reset.
    """
    import importlib

    monkeypatch.setenv("FEATURE_FLAGS_DB_PATH", db_path)

    import src.events.feature_flags as ff_module
    importlib.reload(ff_module)
    return ff_module


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_env_var_default_false(monkeypatch, tmp_path):
    """With no DB row and no env var, is_enabled returns False."""
    ff = _fresh_module(monkeypatch, str(tmp_path / "ff.db"))
    # Ensure the env var for the flag is absent
    monkeypatch.delenv(ff.RUBRIC_MEMORY_ENABLED, raising=False)

    assert ff.is_enabled(ff.RUBRIC_MEMORY_ENABLED) is False


def test_env_var_true_enables(monkeypatch, tmp_path):
    """Setting the env var to 'true' enables the flag when no DB row exists."""
    ff = _fresh_module(monkeypatch, str(tmp_path / "ff.db"))
    monkeypatch.setenv(ff.ATLAS_ENABLED, "true")

    assert ff.is_enabled(ff.ATLAS_ENABLED) is True


def test_global_db_override(monkeypatch, tmp_path):
    """A global DB override (username=None) takes precedence over env var."""
    ff = _fresh_module(monkeypatch, str(tmp_path / "ff.db"))
    # Env var says False (absent), DB says True
    monkeypatch.delenv(ff.PROFILE_RANKER_ENABLED, raising=False)

    ff.set_override(ff.PROFILE_RANKER_ENABLED, enabled=True)

    assert ff.is_enabled(ff.PROFILE_RANKER_ENABLED) is True


def test_per_user_db_override_takes_priority(monkeypatch, tmp_path):
    """Per-user DB row overrides the global DB row."""
    ff = _fresh_module(monkeypatch, str(tmp_path / "ff.db"))

    # Global says disabled, per-user says enabled
    ff.set_override(ff.RUBRIC_MEMORY_ENABLED, enabled=False)
    ff.set_override(ff.RUBRIC_MEMORY_ENABLED, enabled=True, username="alice")

    # alice sees True
    assert ff.is_enabled(ff.RUBRIC_MEMORY_ENABLED, username="alice") is True
    # anonymous / other user sees global False
    assert ff.is_enabled(ff.RUBRIC_MEMORY_ENABLED) is False
    assert ff.is_enabled(ff.RUBRIC_MEMORY_ENABLED, username="bob") is False


def test_is_enabled_handles_missing_flag(monkeypatch, tmp_path):
    """An unknown flag name with no env var and no DB row returns False."""
    ff = _fresh_module(monkeypatch, str(tmp_path / "ff.db"))
    monkeypatch.delenv("TOTALLY_UNKNOWN_FLAG", raising=False)

    assert ff.is_enabled("TOTALLY_UNKNOWN_FLAG") is False
