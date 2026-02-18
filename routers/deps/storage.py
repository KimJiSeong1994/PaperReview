"""
File-based storage helpers: bookmarks, users, papers.

Provides load/save/modify functions with thread-safe file locking,
plus in-memory session storage for reviews.
"""

import json
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict

from filelock import FileLock

from .config import PROJECT_ROOT

logger = logging.getLogger(__name__)

# ── Review session storage (shared between reviews & bookmarks) ────────
review_sessions: Dict[str, Dict[str, Any]] = {}
review_sessions_lock = threading.Lock()

# ── Bookmarks file & helpers ──────────────────────────────────────────
BOOKMARKS_FILE = Path("data/bookmarks.json")
_bookmarks_lock = FileLock(str(BOOKMARKS_FILE) + ".lock")


def load_bookmarks() -> dict:
    """Load bookmarks from JSON file (thread-safe)."""
    with _bookmarks_lock:
        if not BOOKMARKS_FILE.exists():
            return {"bookmarks": []}
        try:
            with open(BOOKMARKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            backup = BOOKMARKS_FILE.with_suffix(".json.corrupt")
            BOOKMARKS_FILE.rename(backup)
            logger.error("Corrupt bookmarks file backed up to %s: %s", backup, e)
            return {"bookmarks": []}


def save_bookmarks(data: dict):
    """Save bookmarks to JSON file (thread-safe, atomic write)."""
    with _bookmarks_lock:
        BOOKMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = BOOKMARKS_FILE.with_suffix(".json.tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_file.replace(BOOKMARKS_FILE)


@contextmanager
def modify_bookmarks():
    """Atomically read-modify-write bookmarks under a single lock.

    Only saves if the block completes without exception.
    Usage:
        with modify_bookmarks() as data:
            data["bookmarks"].append(new_bm)
            # auto-saved on exit
    """
    with _bookmarks_lock:
        if BOOKMARKS_FILE.exists():
            with open(BOOKMARKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {"bookmarks": []}
        try:
            yield data
        except Exception:
            raise
        else:
            BOOKMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = BOOKMARKS_FILE.with_suffix(".json.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp_file.replace(BOOKMARKS_FILE)


# ── Users file & helpers (shared by auth + admin) ────────────────────
USERS_FILE = PROJECT_ROOT / "data" / "users.json"
_users_lock = FileLock(str(USERS_FILE) + ".lock")


def load_users() -> dict:
    """Load users from JSON file (thread-safe)."""
    with _users_lock:
        if not USERS_FILE.exists():
            return {}
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            backup = USERS_FILE.with_suffix(".json.corrupt")
            USERS_FILE.rename(backup)
            logger.error("Corrupt users file backed up to %s: %s", backup, e)
            return {}


def save_users(users: dict) -> None:
    """Save users to JSON file (thread-safe, atomic write)."""
    with _users_lock:
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = USERS_FILE.with_suffix(".json.tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
        tmp_file.replace(USERS_FILE)


@contextmanager
def modify_users():
    """Atomically read-modify-write users under a single lock."""
    with _users_lock:
        if USERS_FILE.exists():
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                users = json.load(f)
        else:
            users = {}
        try:
            yield users
        except Exception:
            raise
        else:
            USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = USERS_FILE.with_suffix(".json.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(users, f, indent=2, ensure_ascii=False)
            tmp_file.replace(USERS_FILE)


# ── Papers file helpers ──────────────────────────────────────────────
PAPERS_FILE = Path("data/raw/papers.json")
_papers_lock = FileLock(str(PAPERS_FILE) + ".lock")
