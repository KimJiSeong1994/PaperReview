"""
Shared user-deletion cascade utility.

This module centralises the logic for completely removing a user from every
storage layer of the application (SQLite tables, embedding FS, JSON files,
in-memory caches).  It is consumed by two endpoints:

* ``DELETE /api/me/all``  — self-delete (GDPR right-to-erasure).
* ``DELETE /api/admin/users/{username}``  — admin-initiated account removal.

Design
------
Each stage is executed **independently** inside its own ``try/except``.  A
stage failure does *not* abort the remaining stages. The identity is revoked
before cleanup and reserved until every cleanup stage succeeds. A cross-process
lease serializes cleanup retries without holding an authority transaction.

Path configuration is dynamic via module-level globals so that test fixtures
can monkey-patch ``routers.deps.user_deletion.EVENTS_DB_PATH`` (etc.) between
requests.  For backward compatibility with the legacy
``routers.me`` tests, callers may pass an explicit ``paths`` override dict;
when supplied it takes precedence over the module defaults.

PII safety
----------
Raw usernames are never written to the log.  Only the first 12 hex chars of
``sha256(username)`` appear as a stable correlation prefix.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from filelock import FileLock, Timeout
from pydantic import BaseModel

from src.events.contracts import assert_valid_username, safe_user_path
from src.storage.user_db import AccountLifecycleError
from .auth import AuthenticatedPrincipal

from .storage import (
    PAPERS_FILE,
    _get_bookmark_db,
    _get_user_db,
    _papers_lock,
    review_sessions,
    review_sessions_lock,
)

logger = logging.getLogger(__name__)


# ── Path configuration (env-overridable, patchable in tests) ──────────
_DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

EVENTS_DB_PATH: Path = Path(os.getenv("EVENTS_DB_PATH", str(_DATA_DIR / "events.db")))
PROFILE_DB_PATH: Path = Path(
    os.getenv("PROFILE_DB_PATH", str(_DATA_DIR / "profile.db"))
)
EMBEDDINGS_USERS_DIR: Path = _DATA_DIR / "embeddings" / "users"
BLOG_POSTS_FILE: Path = _DATA_DIR / "blog" / "posts.json"
BLOG_POSTS_LOCK: FileLock = FileLock(str(BLOG_POSTS_FILE) + ".lock")
CURRICULA_DIR: Path = _DATA_DIR / "curricula"
GDPR_AUDIT_LOG: Path = _DATA_DIR / ".gdpr_audit.jsonl"
RECOMMENDATIONS_DIR: Path = Path(
    os.getenv("RECOMMENDATIONS_ARTIFACTS_DIR", str(_DATA_DIR / "recommendations"))
)
RECOMMENDATION_CANDIDATES_DIR: Path = Path(
    os.getenv(
        "RECOMMENDATION_CANDIDATES_DIR", str(_DATA_DIR / "recommendation-candidates")
    )
)


# ── Public constants ──────────────────────────────────────────────────
# Contains characters (``[``, ``:``, ``]``) that are rejected by
# ``assert_valid_username`` — guaranteeing the sentinel can never be
# reused as a real username.
ANONYMIZED_SENTINEL_PREFIX: str = "[deleted:"


def make_sentinel(audit_hash: str) -> str:
    """Return the canonical anonymised-user sentinel for ``audit_hash``.

    Parameters
    ----------
    audit_hash:
        Full ``sha256(username)`` hex digest (64 chars).  Only the first 8
        hex chars are embedded in the sentinel — enough to disambiguate
        multiple deleted authors within a single JSON file without exposing
        a reversible identifier.

    Returns
    -------
    str
        For example ``"[deleted:1a2b3c4d]"``.  Safe for any ``author`` /
        ``owner`` / ``searched_by`` string field.
    """
    return f"{ANONYMIZED_SENTINEL_PREFIX}{audit_hash[:8]}]"


# ── Result model ──────────────────────────────────────────────────────


class DeleteResult(BaseModel):
    """Structured result of a cascaded deletion.

    Attributes
    ----------
    deleted:
        ``True`` only when **every** stage (including the users_db write
        and the audit-log append) completed without raising.
    partial_failures:
        Stage names that raised (``"rubric_db"``, ``"profile_emb"``,
        ``"events_db"``, ``"bookmarks"``, ``"papers_anonymize"``,
        ``"blog_anonymize"``, ``"curriculum_anonymize"``,
        ``review_sessions_memory"``, ``"account_authority"``, ``"audit_log"``,
        or ``"username_invalid"``).
    audit_hash:
        ``sha256(username)`` hex digest — provides proof-of-deletion
        without retaining the original identifier.
    """

    deleted: bool
    partial_failures: list[str]
    audit_hash: str
    retryable: bool = False


# ── Helpers ───────────────────────────────────────────────────────────


def _hash_prefix(username: str) -> str:
    """Return first 12 hex chars of ``sha256(username)`` for log correlation."""
    return hashlib.sha256(username.encode("utf-8")).hexdigest()[:12]


def _resolve_paths(override: Optional[Mapping[str, Path]]) -> Dict[str, Any]:
    """Merge module-default paths with an optional per-call override.

    Tests patch the module-level paths directly, so the defaults read from
    the module globals at call time (not import time).  Legacy callers
    (``routers.me``) pass an explicit override so that patches on
    ``routers.me.X`` continue to steer the cascade even though the logic
    lives here.
    """
    import routers.deps.user_deletion as _self  # re-read after patching
    from src.analytics.mcp_usage import mcp_analytics_db_path

    paths: Dict[str, Any] = {
        "events_db": _self.EVENTS_DB_PATH,
        "mcp_analytics_db": mcp_analytics_db_path(),
        "profile_db": _self.PROFILE_DB_PATH,
        "embeddings_users_dir": _self.EMBEDDINGS_USERS_DIR,
        "blog_posts_file": _self.BLOG_POSTS_FILE,
        "blog_posts_lock": _self.BLOG_POSTS_LOCK,
        "curricula_dir": _self.CURRICULA_DIR,
        "audit_log": _self.GDPR_AUDIT_LOG,
        "recommendations_dir": _self.RECOMMENDATIONS_DIR,
        "recommendation_candidates_dir": _self.RECOMMENDATION_CANDIDATES_DIR,
        "papers_file": PAPERS_FILE,
    }
    if override:
        paths.update({k: v for k, v in override.items() if v is not None})
    return paths


def append_audit_log(
    audit_hash: str,
    partial_failures: list[str],
    actor: Optional[str],
    audit_log_path: Optional[Path] = None,
) -> None:
    """Append one JSON line to the GDPR audit log.

    Parameters
    ----------
    audit_hash:
        ``sha256(username)`` hex digest of the **target** user.
    partial_failures:
        Stage names that raised during the cascade.
    actor:
        ``None`` → self-delete (recorded as ``"self"``).  When an admin
        triggered the delete, pass the admin username; it is stored as a
        truncated hash so the raw identifier never reaches disk.
    audit_log_path:
        Optional override; defaults to the module-level
        :data:`GDPR_AUDIT_LOG`.
    """
    path = audit_log_path if audit_log_path is not None else GDPR_AUDIT_LOG
    path.parent.mkdir(parents=True, exist_ok=True)

    if actor is None:
        actor_hash: str = "self"
    else:
        actor_hash = hashlib.sha256(actor.encode("utf-8")).hexdigest()[:16]

    record = {
        "audit_hash": audit_hash,
        "actor_hash": actor_hash,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "partial_failures": partial_failures,
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


# ── Individual stage helpers ──────────────────────────────────────────


def _stage_rubric_db(username: str, db_path: Path) -> None:
    """Stage 1 — delete user_rubric row(s)."""
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        conn.execute("DELETE FROM user_rubric WHERE username = ?", (username,))
        conn.commit()
    finally:
        conn.close()


def _stage_profile_emb(username: str, embeddings_dir: Path) -> None:
    """Stage 2 — remove embeddings/users/<username>/ directory."""
    _remove_owned_tree(embeddings_dir, username)


def _stage_events_db(username: str, db_path: Path) -> None:
    """Stage 3 — delete user_events rows."""
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_events'"
        ).fetchone():
            return
        conn.execute("DELETE FROM user_events WHERE user_id = ?", (username,))
        conn.commit()
    finally:
        conn.close()


def _stage_bookmarks(username: str) -> None:
    """Stage 4 — delete bookmarks via the storage-layer singleton."""
    _get_bookmark_db().delete_by_username(username)


def _stage_papers_anonymize(username: str, sentinel: str, papers_file: Path) -> None:
    """Stage 5 — rewrite ``searched_by`` fields in raw/papers.json.

    Papers are not deleted; the attribution is replaced with the
    non-reclaimable sentinel so analytics/history remain intact while
    the raw username is erased.
    """
    with _papers_lock:
        if not papers_file.exists():
            return
        with open(papers_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        changed = False
        for paper in data.get("papers", []):
            if paper.get("searched_by") == username:
                paper["searched_by"] = sentinel
                changed = True

        if not changed:
            return

        papers_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = papers_file.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        tmp.replace(papers_file)


def _stage_blog_anonymize(
    username: str,
    sentinel: str,
    posts_file: Path,
    posts_lock: FileLock,
) -> None:
    """Stage 6 — rewrite ``author`` fields in blog/posts.json."""
    with posts_lock:
        if not posts_file.exists():
            return
        with open(posts_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        # posts.json is either {"posts": [...]} or a bare list (legacy).
        posts = data.get("posts") if isinstance(data, dict) else data
        if not isinstance(posts, list):
            raise ValueError("invalid_blog_cleanup_input")

        changed = False
        for post in posts:
            if isinstance(post, dict) and post.get("author") == username:
                post["author"] = sentinel
                changed = True

        if not changed:
            return

        posts_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = posts_file.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        tmp.replace(posts_file)


def _anonymize_json_file(
    json_path: Path,
    username: str,
    sentinel: str,
    keys: tuple[str, ...] = ("owner", "author"),
) -> None:
    """Rewrite matching username fields in a single JSON file.

    Handles both ``{"curricula": [...]}`` top-level containers and arbitrary
    nested dicts/lists.  Only the *listed* keys are candidates so unrelated
    string values are untouched.
    """
    if not json_path.exists():
        return

    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Hidden sidecars are excluded by the caller. An unreadable real
        # document may retain owner input; do not claim complete erasure.
        logger.warning("Unreadable curriculum JSON requires cleanup retry")
        raise

    changed = [False]

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in list(node.items()):
                if k in keys and v == username:
                    node[k] = sentinel
                    changed[0] = True
                else:
                    _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(data)

    if not changed[0]:
        return

    tmp = json_path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    tmp.replace(json_path)


def _stage_curriculum_anonymize(
    username: str, sentinel: str, curricula_dir: Path
) -> None:
    """Stage 7 — rewrite ``owner`` / ``author`` fields across curricula JSONs.

    Each file may use a different schema; ``_anonymize_json_file`` walks
    nested structures and only replaces the listed keys when they equal
    the target username.
    """
    if not curricula_dir.exists():
        return
    failed = False
    for json_path in sorted(curricula_dir.glob("*.json")):
        # Hidden files (``._*`` AppleDouble sidecars, ``.DS_Store``-adjacent
        # noise) are never real curricula — skip without even opening them.
        if json_path.name.startswith("."):
            continue
        try:
            _anonymize_json_file(json_path, username, sentinel)
        except OSError as exc:
            # Continue on a per-file error — do not abort the whole stage.
            logger.warning(
                "curriculum_anonymize: failed on %s: %s", json_path.name, exc
            )
            failed = True
    if failed:
        raise OSError("curriculum_cleanup_incomplete")


def _stage_review_sessions_memory(username: str) -> None:
    """Stage 8 — evict in-memory review sessions owned by username."""
    with review_sessions_lock:
        doomed = [
            sid
            for sid, sess in review_sessions.items()
            if sess.get("username") == username
        ]
        for sid in doomed:
            review_sessions.pop(sid, None)


def _remove_owned_tree(
    root: Path, owner: str, *, legacy_username: Optional[str] = None
) -> None:
    """Remove an exact contained tree, refusing symlink traversal."""
    root = Path(root).absolute()
    if any(part.is_symlink() for part in (root, *root.parents)):
        raise ValueError("unsafe_cleanup_path")
    lexical_target = root / owner
    if lexical_target.is_symlink():
        raise ValueError("unsafe_cleanup_path")
    target = safe_user_path(root, owner)
    if not target.exists():
        return
    for directory, dirs, files in os.walk(target, followlinks=False):
        if any((Path(directory) / name).is_symlink() for name in dirs + files):
            raise ValueError("unsafe_cleanup_path")
        if legacy_username is not None:
            for name in files:
                path = Path(directory) / name
                # Generation IDs share the old username directory level.
                # Prove legacy ownership rather than deleting a colliding
                # generation directory belonging to a different account.
                if path.suffix != ".json":
                    raise ValueError("unverified_legacy_owner")
                payload = json.loads(path.read_text(encoding="utf-8"))
                if (
                    not isinstance(payload, dict)
                    or payload.get("user_id") != legacy_username
                ):
                    raise ValueError("unverified_legacy_owner")
    shutil.rmtree(target)


def _stage_recommendations(
    username: str, incarnation: str, paths: Mapping, *, authority
) -> None:
    from src.recommendation_state import RecommendationState

    RecommendationState(paths["events_db"], authority=authority).delete_incarnation(
        incarnation
    )
    _remove_owned_tree(paths["recommendations_dir"], incarnation)
    _remove_owned_tree(paths["recommendations_dir"], username, legacy_username=username)
    _remove_owned_tree(
        Path(paths["recommendation_candidates_dir"]) / "private", incarnation
    )


# ── Public entry point ────────────────────────────────────────────────


def delete_user_cascade(
    username: str,
    *,
    account_incarnation: str,
    actor: Optional[AuthenticatedPrincipal] = None,
    paths: Optional[Mapping[str, Path]] = None,
) -> DeleteResult:
    """Revoke and clean exactly one identity under a cross-process cleanup lease."""
    audit_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()
    try:
        assert_valid_username(username)
    except ValueError:
        return DeleteResult(
            deleted=False, partial_failures=["username_invalid"], audit_hash=""
        )
    try:
        db = _get_user_db()
        with db.cleanup_lock(username):
            with db.transaction() as tx:
                if actor is not None:
                    acting = tx.validate_principal(
                        actor.username, actor.account_incarnation
                    )
                    if acting.get("role") != "admin":
                        raise AccountLifecycleError("admin_required")
                    if actor.username == username:
                        raise AccountLifecycleError("cannot_delete_self_as_admin")
                    target = tx.get(username)
                    if target and target.get("role") == "admin":
                        if (
                            sum(u.get("role") == "admin" for u in tx.get_all().values())
                            <= 1
                        ):
                            raise AccountLifecycleError("last_admin")
                else:
                    tx.validate_principal(username, account_incarnation)
                tx.begin_delete(username, account_incarnation)
            return _delete_reserved_user(
                username,
                account_incarnation,
                db,
                actor.username if actor else None,
                paths,
            )
    except Timeout:
        return DeleteResult(
            deleted=False,
            partial_failures=["cleanup_busy"],
            audit_hash=audit_hash,
            retryable=True,
        )
    except AccountLifecycleError as exc:
        authority_failure = exc.reason in {
            "lifecycle_integrity_error",
            "unsafe_cleanup_lock",
        }
        return DeleteResult(
            deleted=False,
            partial_failures=[exc.reason],
            audit_hash=audit_hash,
            retryable=authority_failure,
        )
    except (sqlite3.Error, OSError):
        return DeleteResult(
            deleted=False,
            partial_failures=["account_authority"],
            audit_hash=audit_hash,
            retryable=True,
        )


def _delete_reserved_user(
    username: str,
    account_incarnation: str,
    db,
    actor: Optional[str],
    paths: Optional[Mapping[str, Path]],
) -> DeleteResult:
    """Run best-effort stages while the caller holds the exact identity lease."""
    audit_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()
    sentinel = make_sentinel(audit_hash)
    hp = _hash_prefix(username)
    partial_failures: list[str] = []

    p = _resolve_paths(paths)

    # ── Stage 1: rubric_db ────────────────────────────────────────────
    try:
        _stage_rubric_db(username, p["profile_db"])
    except Exception:
        logger.exception("cascade[rubric_db] failed for hash_prefix=%s", hp)
        partial_failures.append("rubric_db")

    # ── Stage 2: profile_emb ──────────────────────────────────────────
    try:
        _stage_profile_emb(username, p["embeddings_users_dir"])
    except Exception:
        logger.exception("cascade[profile_emb] failed for hash_prefix=%s", hp)
        partial_failures.append("profile_emb")

    # ── Stage 3: events_db ────────────────────────────────────────────
    try:
        _stage_events_db(username, p["events_db"])
    except Exception:
        logger.exception("cascade[events_db] failed for hash_prefix=%s", hp)
        partial_failures.append("events_db")

    # ── Stage 4: bookmarks ────────────────────────────────────────────
    try:
        _stage_bookmarks(username)
    except Exception:
        logger.exception("cascade[bookmarks] failed for hash_prefix=%s", hp)
        partial_failures.append("bookmarks")

    # ── Stage 5: papers_anonymize ─────────────────────────────────────
    try:
        _stage_papers_anonymize(username, sentinel, p["papers_file"])
    except Exception:
        logger.exception("cascade[papers_anonymize] failed for hash_prefix=%s", hp)
        partial_failures.append("papers_anonymize")

    # ── Stage 6: blog_anonymize ───────────────────────────────────────
    try:
        _stage_blog_anonymize(
            username, sentinel, p["blog_posts_file"], p["blog_posts_lock"]
        )
    except Exception:
        logger.exception("cascade[blog_anonymize] failed for hash_prefix=%s", hp)
        partial_failures.append("blog_anonymize")

    # ── Stage 7: curriculum_anonymize ─────────────────────────────────
    try:
        _stage_curriculum_anonymize(username, sentinel, p["curricula_dir"])
    except Exception:
        logger.exception("cascade[curriculum_anonymize] failed for hash_prefix=%s", hp)
        partial_failures.append("curriculum_anonymize")

    # ── Stage 8: review_sessions_memory ───────────────────────────────
    try:
        _stage_review_sessions_memory(username)
    except Exception:
        logger.exception(
            "cascade[review_sessions_memory] failed for hash_prefix=%s", hp
        )
        partial_failures.append("review_sessions_memory")

    # Dedicated MCP measurements must follow account deletion as well.
    try:
        from src.analytics.mcp_usage import delete_actor_events

        delete_actor_events(username, p["mcp_analytics_db"])
    except Exception:
        logger.exception("cascade[mcp_analytics] failed for hash_prefix=%s", hp)
        partial_failures.append("mcp_analytics")

    # Policy revocation and both private file namespaces are required cleanup.
    try:
        _stage_recommendations(username, account_incarnation, p, authority=db)
    except Exception:
        logger.error("cascade[recommendations] failed for hash_prefix=%s", hp)
        partial_failures.append("recommendations")

    # ── Audit log ─────────────────────────────────────────────────────
    try:
        append_audit_log(
            audit_hash,
            partial_failures,
            actor=actor,
            audit_log_path=p["audit_log"],
        )
    except Exception:
        logger.error(
            "cascade[audit_log] failed for hash_prefix=%s — audit trail broken",
            hp,
            exc_info=True,
        )
        partial_failures.append("audit_log")

    try:
        db.finish_delete(
            username, account_incarnation, cleanup_succeeded=not partial_failures
        )
    except (AccountLifecycleError, sqlite3.Error, OSError):
        partial_failures.append("account_authority")

    return DeleteResult(
        deleted=len(partial_failures) == 0,
        partial_failures=partial_failures,
        audit_hash=audit_hash,
        retryable=bool(partial_failures),
    )
