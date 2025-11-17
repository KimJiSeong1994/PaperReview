"""
Lightweight fallback implementation of python-dotenv's load_dotenv.

Provides a minimal subset of the original library's functionality so that
the project can run in environments where third-party dependencies cannot
be installed (e.g., offline sandboxes). The implementation supports the
simple "KEY=VALUE" syntax commonly used in .env files.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union


def load_dotenv(dotenv_path: Union[str, os.PathLike[str], None] = None, override: bool = False) -> bool:
    """
    Parse environment variables from a .env file into ``os.environ``.

    Args:
        dotenv_path: Optional custom path to the .env file. Defaults to ".env"
            in the current working directory if not provided.
        override: If True, overwrite existing environment variables. Matches
            python-dotenv's ``override`` parameter.

    Returns:
        bool: True if a .env file was successfully processed, False otherwise.
    """

    path = Path(dotenv_path) if dotenv_path else Path(".env")
    if not path.exists():
        return False

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        key, sep, value = stripped.partition("=")
        if not sep:
            continue

        key = key.strip()
        value = value.strip().strip("\"'")  # remove common quotes

        if key and (override or key not in os.environ):
            os.environ[key] = value

    return True


__all__ = ["load_dotenv"]

