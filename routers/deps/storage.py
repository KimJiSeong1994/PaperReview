"""
Storage helpers: bookmarks, users, papers.

Provides load/save/modify functions backed by SQLite (BookmarkDB / UserDB).
The public function signatures are unchanged so all routers continue to work
without modification.

Migration: on first call the legacy JSON files are automatically imported
into SQLite and renamed to *.migrated.
"""

import json
import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

logger = logging.getLogger(__name__)

# ── Review session storage (shared between reviews & bookmarks) ────────
review_sessions: Dict[str, Dict[str, Any]] = {}
review_sessions_lock = threading.Lock()

# ── Workspace 기반 세션 복원 (서버 재시작 시 인메모리 세션 유실 방지) ──
WORKSPACE_DIR = DATA_DIR / "workspace"

# F-02: metadata.json 에 username 이 없는 legacy 세션은 이 sentinel 로
# 복원되어 어떤 실제 사용자도 일치시키지 못하게 한다 (= 자동 봉인).
# 재실행/삭제되기 전까지 모든 호출에서 404 를 반환한다.
_LEGACY_SESSION_OWNER_SENTINEL = "__legacy_unknown__"


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

        # 세션 복원.  username 이 없거나 None 이면 legacy sentinel 로 봉인 — F-02.
        restored_username = metadata.get("username") or _LEGACY_SESSION_OWNER_SENTINEL
        review_sessions[session_id] = {
            "status": "completed",
            "workspace_path": str(session_dir),
            "created_at": metadata.get("created_at", ""),
            "num_papers": metadata.get("num_papers", 0),
            "paper_ids": metadata.get("paper_ids", []),
            "papers_data": metadata.get("papers_data"),
            "progress": "Restored from workspace",
            "username": restored_username,
        }
        restored += 1

    if restored > 0:
        logger.info("Restored %d review sessions from workspace", restored)

    return restored


# 모듈 로드 시 자동 복원
_restore_sessions_from_workspace()

# ── Legacy file paths (kept for test-patch compatibility) ─────────────
BOOKMARKS_FILE = DATA_DIR / "bookmarks.json"
# _bookmarks_lock is kept as a module-level name so tests can patch it.
# The SQLite layer handles its own thread-safety; this lock is a no-op stub.
_bookmarks_lock = threading.Lock()

USERS_FILE = DATA_DIR / "users.json"
_users_lock = threading.Lock()

# ── Papers file helpers (unchanged — still JSON-based) ────────────────
PAPERS_FILE = DATA_DIR / "raw" / "papers.json"
_papers_lock = threading.Lock()

# ── SQLite DB singletons (keyed by resolved db_path for test isolation) ──
_bookmark_dbs: Dict[str, Any] = {}
_bookmark_dbs_lock = threading.Lock()

_user_dbs: Dict[str, Any] = {}
_user_dbs_lock = threading.Lock()


def _get_bookmark_db():
    """Return a BookmarkDB instance whose path is derived from BOOKMARKS_FILE.

    Using BOOKMARKS_FILE at call-time (not import-time) ensures that test
    patches on BOOKMARKS_FILE are respected: the DB will be created in the
    same directory as the (possibly patched) JSON file.
    """
    from src.storage.bookmark_db import BookmarkDB

    db_path = Path(str(BOOKMARKS_FILE)).with_suffix(".db")
    key = str(db_path.resolve())

    with _bookmark_dbs_lock:
        if key not in _bookmark_dbs:
            db = BookmarkDB(db_path=db_path)
            # Auto-migrate JSON → SQLite on first use
            db.migrate_from_json(str(BOOKMARKS_FILE))
            _bookmark_dbs[key] = db
        return _bookmark_dbs[key]


def _get_user_db():
    """Return a UserDB instance whose path is derived from USERS_FILE."""
    from src.storage.user_db import UserDB

    db_path = Path(str(USERS_FILE)).with_suffix(".db")
    key = str(db_path.resolve())

    with _user_dbs_lock:
        if key not in _user_dbs:
            db = UserDB(db_path=db_path)
            # Auto-migrate JSON → SQLite on first use
            db.migrate_from_json(str(USERS_FILE))
            _user_dbs[key] = db
        return _user_dbs[key]


# ── Bookmarks public API ──────────────────────────────────────────────

def load_bookmarks() -> dict:
    """Load bookmarks from SQLite (thread-safe).

    Returns the same ``{"bookmarks": [...]}`` structure as the former
    JSON-based implementation so all callers remain unchanged.
    """
    db = _get_bookmark_db()
    bookmarks = db.get_all()
    return {"bookmarks": bookmarks}


def load_bookmarks_for_user(username: str) -> list:
    """Return all bookmarks for *username* using the indexed SQLite query.

    Replaces the O(N) ``load_bookmarks()`` full-scan + Python-filter
    pattern used in list and detail endpoints.  The return value is a
    plain ``list[dict]`` — identical in shape to the entries inside
    ``load_bookmarks()["bookmarks"]`` — so callers can iterate directly.

    Parameters
    ----------
    username:
        Authenticated user whose bookmarks are requested.  Validated by
        ``BookmarkDB.get_by_username`` via
        :func:`~src.events.contracts.assert_valid_username`.

    Returns
    -------
    list[dict]
        Zero or more bookmark dicts ordered by ``created_at DESC``.
        Returns an empty list if *username* fails format validation
        (legacy / external-IdP / forged JWT subs) — preserves the old
        comparison-filter behaviour of returning 0 results rather than
        raising a 500.
    """
    import hashlib

    from src.events.contracts import assert_valid_username

    try:
        assert_valid_username(username)
    except ValueError:
        user_hash_prefix = hashlib.sha256(username.encode("utf-8")).hexdigest()[:12]
        logger.warning(
            "load_bookmarks_for_user: invalid username (hash_prefix=%s) — returning empty list",
            user_hash_prefix,
        )
        return []
    return _get_bookmark_db().get_by_username(username)


def save_bookmarks(data: dict) -> None:
    """Persist a full bookmarks payload to SQLite.

    Accepts the same ``{"bookmarks": [...]}`` structure as before.
    Each bookmark is upserted; bookmarks absent from *data* are NOT deleted
    (use :func:`modify_bookmarks` for read-modify-write with deletions).
    """
    db = _get_bookmark_db()
    for bm in data.get("bookmarks", []):
        db.upsert(bm)


def _save_bookmarks_replace(data: dict) -> None:
    """Replace-all helper used inside modify_bookmarks context manager.

    Deletes all bookmarks owned by users represented in *data*, then
    re-upserts the supplied list.  This faithfully replicates the old
    atomic-overwrite semantics while keeping deletions scoped.
    """
    db = _get_bookmark_db()
    new_ids = {bm["id"] for bm in data.get("bookmarks", []) if bm.get("id")}

    # Delete rows whose id is no longer present in the new list
    existing = db.get_all()
    for bm in existing:
        if bm.get("id") and bm["id"] not in new_ids:
            db.delete(bm["id"])

    # Upsert remaining
    for bm in data.get("bookmarks", []):
        db.upsert(bm)


@contextmanager
def modify_bookmarks():
    """Atomically read-modify-write bookmarks backed by SQLite.

    Preserves the original context-manager contract:

        with modify_bookmarks() as data:
            data["bookmarks"].append(new_bm)
            # auto-saved on exit

    The in-memory *data* dict is built from the current DB state.  On clean
    exit the full list is reconciled back into SQLite (upserts + deletes).
    Exceptions abort the write.
    """
    db = _get_bookmark_db()
    bookmarks = db.get_all()
    data: dict = {"bookmarks": bookmarks}
    try:
        yield data
    except Exception:
        raise
    else:
        _save_bookmarks_replace(data)


# ── Users public API ─────────────────────────────────────────────────

def load_users() -> dict:
    """Load users from SQLite (thread-safe).

    Returns the same ``{username: {...}}`` dict as the former JSON
    implementation so all callers remain unchanged.
    """
    db = _get_user_db()
    return db.get_all()


def save_users(users: dict) -> None:
    """Persist a users dict to SQLite.

    Accepts the same ``{username: {...}}`` structure as before.
    Each user is upserted; users absent from *users* are NOT deleted
    (use :func:`modify_users` for replace-all semantics).
    """
    db = _get_user_db()
    for username, data in users.items():
        db.upsert(username, data)


def _save_users_replace(users: dict) -> None:
    """Replace-all helper used inside modify_users context manager."""
    db = _get_user_db()
    new_usernames = set(users.keys())

    existing = db.get_all()
    for username in existing:
        if username not in new_usernames:
            db.delete(username)

    for username, data in users.items():
        db.upsert(username, data)


@contextmanager
def modify_users():
    """Atomically read-modify-write users backed by SQLite."""
    db = _get_user_db()
    users = db.get_all()
    try:
        yield users
    except Exception:
        raise
    else:
        _save_users_replace(users)
