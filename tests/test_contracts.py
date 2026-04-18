"""
Tests for src/events/contracts.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.events.contracts import (
    assert_embedding_dim,
    assert_valid_username,
    safe_user_path,
)


# ---------------------------------------------------------------------------
# assert_valid_username
# ---------------------------------------------------------------------------


def test_valid_username_passes():
    """Alphanumeric names, hyphens and underscores up to 64 chars are accepted."""
    for name in ("alice", "Bob_123", "user-42", "A" * 64):
        assert_valid_username(name)  # must not raise


def test_dot_username_rejected():
    """Usernames containing dots are rejected (prevents traversal via '..'-like paths)."""
    with pytest.raises(ValueError, match="Invalid username"):
        assert_valid_username("alice.admin")


def test_traversal_rejected(tmp_path):
    """A username like '../etc' must be rejected by assert_valid_username before reaching safe_user_path."""
    with pytest.raises(ValueError, match="Invalid username"):
        assert_valid_username("../etc")


def test_long_username_rejected():
    """Usernames longer than 64 characters are rejected."""
    with pytest.raises(ValueError, match="Invalid username"):
        assert_valid_username("a" * 65)


# ---------------------------------------------------------------------------
# assert_embedding_dim
# ---------------------------------------------------------------------------


def test_embedding_dim_mismatch_raises():
    """Mismatched dimension raises AssertionError."""
    with pytest.raises(AssertionError):
        assert_embedding_dim(512, expected=384)


def test_embedding_dim_match_passes():
    """Matching dimension does not raise."""
    assert_embedding_dim(384)          # default expected
    assert_embedding_dim(768, expected=768)


# ---------------------------------------------------------------------------
# safe_user_path
# ---------------------------------------------------------------------------


def test_safe_user_path_returns_resolved_path(tmp_path):
    """safe_user_path returns the resolved absolute path for a valid username."""
    result = safe_user_path(tmp_path, "alice")
    assert result == (tmp_path / "alice").resolve()
    assert result.is_absolute()


def test_safe_user_path_rejects_dot_traversal(tmp_path):
    """Usernames with dots are rejected before path resolution."""
    with pytest.raises(ValueError):
        safe_user_path(tmp_path, "..malicious")


def test_safe_user_path_rejects_symlink_escape(tmp_path):
    """
    A symlink pointing outside base is detected and rejected.

    We create a symlink inside tmp_path that points to /tmp (outside base)
    and confirm safe_user_path raises ValueError.
    """
    import os

    outside = tmp_path.parent / "outside_dir"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "escape_link"
    # Only create the symlink if the OS supports it
    try:
        os.symlink(str(outside), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform")

    with pytest.raises(ValueError, match="traversal"):
        safe_user_path(tmp_path, "escape_link")
