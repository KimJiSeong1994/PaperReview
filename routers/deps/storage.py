"""
File-based storage helpers: bookmarks, users, papers.

Provides load/save/modify functions with thread-safe file locking,
plus in-memory session storage for reviews.
"""

import json
import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict

from filelock import FileLock

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

logger = logging.getLogger(__name__)

# ── Review session storage (shared between reviews & bookmarks) ────────
review_sessions: Dict[str, Dict[str, Any]] = {}
review_sessions_lock = threading.Lock()

# ── Workspace 기반 세션 복원 (서버 재시작 시 인메모리 세션 유실 방지) ──
WORKSPACE_DIR = DATA_DIR / "workspace"


def _restore_sessions_from_workspace() -> int:
    """서버 시작 시 workspace 디렉토리에서 완료된 세션을 복원한다.

    각 workspace 폴더의 metadata.json과 reports/*.md를 확인하여
    review_sessions에 재등록한다. 리포트 파일이 있으면 status=completed로 복원.

    Returns:
        복원된 세션 수
    """
    if not WORKSPACE_DIR.exists():
        return 0

    restored = 0
    for session_dir in WORKSPACE_DIR.iterdir():
        if not session_dir.is_dir() or not session_dir.name.startswith("review_"):
            continue

        session_id = session_dir.name
        if session_id in review_sessions:
            continue

        # metadata.json 로드
        metadata_file = session_dir / "metadata.json"
        metadata: Dict[str, Any] = {}
        if metadata_file.exists():
            try:
                with open(metadata_file, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        # 리포트 파일 존재 여부로 완료 상태 판단
        reports_dir = session_dir / "reports"
        has_report = False
        if reports_dir.exists():
            md_files = list(reports_dir.glob("*.md"))
            has_report = len(md_files) > 0

        if not has_report:
            continue  # 리포트 없는 세션은 복원하지 않음

        # 세션 복원
        review_sessions[session_id] = {
            "status": "completed",
            "workspace_path": str(session_dir),
            "created_at": metadata.get("created_at", ""),
            "num_papers": metadata.get("num_papers", 0),
            "paper_ids": metadata.get("paper_ids", []),
            "papers_data": metadata.get("papers_data"),
            "progress": "Restored from workspace",
            "username": metadata.get("username"),
        }
        restored += 1

    if restored > 0:
        logger.info("Restored %d review sessions from workspace", restored)

    return restored


# 모듈 로드 시 자동 복원
_restore_sessions_from_workspace()

# ── Bookmarks file & helpers ──────────────────────────────────────────
BOOKMARKS_FILE = DATA_DIR / "bookmarks.json"
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
USERS_FILE = DATA_DIR / "users.json"
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
PAPERS_FILE = DATA_DIR / "raw" / "papers.json"
_papers_lock = FileLock(str(PAPERS_FILE) + ".lock")
