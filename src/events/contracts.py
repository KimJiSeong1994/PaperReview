"""
Shared contract helpers: input validation and safety assertions.

Functions
---------
assert_valid_username  — rejects usernames that don't match the safe pattern
safe_user_path         — path-traversal-safe user directory resolution
assert_embedding_dim   — dimension consistency guard
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Username safety
# ---------------------------------------------------------------------------

# Intentionally excludes dots to prevent directory traversal via ".."-like
# segments and to avoid ambiguity with file extensions.
_SAFE_USERNAME: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def assert_valid_username(username: str) -> None:
    """
    Assert that *username* is safe for use in file-system operations.

    Raises
    ------
    ValueError
        If *username* does not match ``^[A-Za-z0-9_\\-]{1,64}$``.
    """
    if not _SAFE_USERNAME.match(username):
        raise ValueError(
            f"Invalid username {username!r}: must match ^[A-Za-z0-9_\\-]{{1,64}}$"
        )


# ---------------------------------------------------------------------------
# Path traversal guard
# ---------------------------------------------------------------------------


def safe_user_path(base: Path, username: str) -> Path:
    """
    Return ``base / username`` as a resolved, traversal-safe :class:`~pathlib.Path`.

    The function:

    1. Validates *username* via :func:`assert_valid_username`.
    2. Resolves both *base* and the candidate path with :meth:`~pathlib.Path.resolve`.
    3. Asserts the resolved target starts with ``str(resolved_base) + os.sep``
       (or equals ``resolved_base``), preventing escape via symlinks or
       ``..`` segments.

    Parameters
    ----------
    base:
        The root directory that the returned path must reside under.
    username:
        A validated username; used as a single path component.

    Returns
    -------
    Path
        The resolved absolute path ``base / username``.

    Raises
    ------
    ValueError
        If *username* is invalid **or** the resolved path escapes *base*.
    """
    assert_valid_username(username)

    resolved_base = base.resolve()
    target = (base / username).resolve()

    # Guard: target must be directly inside base (not equal to base itself,
    # and not escape via symlinks).
    target_str = str(target)
    base_str = str(resolved_base)

    if target_str != base_str and not target_str.startswith(base_str + os.sep):
        raise ValueError(
            f"Path traversal detected: {target_str!r} is outside base {base_str!r}"
        )

    return target


# ---------------------------------------------------------------------------
# Embedding dimension assertion
# ---------------------------------------------------------------------------


def assert_embedding_dim(value: int, expected: int = 384) -> None:
    """
    Assert that *value* matches the expected embedding dimensionality.

    Parameters
    ----------
    value:
        The actual dimension to check.
    expected:
        The required dimension (default ``384`` for MiniLM-style models).

    Raises
    ------
    AssertionError
        If ``value != expected``.
    """
    assert value == expected, (
        f"Embedding dimension mismatch: got {value}, expected {expected}"
    )
