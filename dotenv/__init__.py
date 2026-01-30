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
from typing import Union, Optional


def find_dotenv(filename: str = '.env', raise_error_if_not_found: bool = False, usecwd: bool = False) -> str:
    """
    Search for .env file in current directory and parent directories.
    
    Args:
        filename: Name of the file to find (default: '.env')
        raise_error_if_not_found: Raise IOError if file not found
        usecwd: Start search from current working directory
        
    Returns:
        Path to .env file as string, or empty string if not found
    """
    if usecwd:
        start_path = Path.cwd()
    else:
        # Start from current working directory by default
        start_path = Path.cwd()
    
    # Search upwards for the file
    current = start_path
    for _ in range(10):  # Limit search depth
        env_file = current / filename
        if env_file.exists():
            return str(env_file)
        
        parent = current.parent
        if parent == current:  # Reached root
            break
        current = parent
    
    # Not found
    if raise_error_if_not_found:
        raise IOError(f"File {filename} not found")
    
    return ''


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


__all__ = ["load_dotenv", "find_dotenv"]

