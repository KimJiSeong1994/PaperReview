"""
One-time data migrations that run on import.

- _migrate_bookmarks_add_username: assigns default user to bookmarks without one
- _migrate_papers_add_searched_by: assigns default user to papers without one
- _fix_username_typo: fixes Jiphyeonjeon → Jipyheonjeon in SQLite DBs
"""

import json
import logging
import os
import sqlite3

from .storage import (
    BOOKMARKS_FILE,
    _bookmarks_lock,
    PAPERS_FILE,
    _papers_lock,
    DATA_DIR,
)

logger = logging.getLogger(__name__)


def _migrate_bookmarks_add_username():
    """One-time: assign existing bookmarks without username to the default admin."""
    default_user = os.getenv("APP_USERNAME", "Jipyheonjeon")
    with _bookmarks_lock:
        if not BOOKMARKS_FILE.exists():
            return
        with open(BOOKMARKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        needs_save = False
        for bm in data.get("bookmarks", []):
            if "username" not in bm:
                bm["username"] = default_user
                needs_save = True

        if needs_save:
            tmp_file = BOOKMARKS_FILE.with_suffix(".json.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp_file.replace(BOOKMARKS_FILE)
            logger.info("Assigned existing bookmarks to user '%s'", default_user)


def _migrate_papers_add_searched_by():
    """One-time: assign existing papers without searched_by to the default admin."""
    default_user = os.getenv("APP_USERNAME", "Jipyheonjeon")
    if not PAPERS_FILE.exists():
        return
    try:
        with _papers_lock:
            with open(PAPERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            needs_save = False
            for paper in data.get("papers", []):
                if "searched_by" not in paper:
                    paper["searched_by"] = default_user
                    needs_save = True

            if needs_save:
                tmp_file = PAPERS_FILE.with_suffix(".json.tmp")
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                tmp_file.replace(PAPERS_FILE)
                logger.info("Assigned existing papers to user '%s'", default_user)
    except Exception as e:
        logger.warning("Paper migration warning: %s", e)


def _fix_username_typo():
    """Fix Jiphyeonjeon → Jipyheonjeon typo in SQLite databases.

    Commit a523dbd introduced 'Jiphyeonjeon' as the migration default,
    but the registered user account is 'Jipyheonjeon'. This one-time fix
    updates all affected records.
    """
    wrong = "Jiphyeonjeon"
    correct = os.getenv("APP_USERNAME", "Jipyheonjeon")

    if wrong == correct:
        return

    for db_name, table, column in [
        ("bookmarks.db", "bookmarks", "username"),
    ]:
        db_path = DATA_DIR / db_name
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute(
                f"UPDATE {table} SET {column} = ? WHERE {column} = ?",  # noqa: S608
                (correct, wrong),
            )
            if cursor.rowcount > 0:
                logger.info(
                    "[Migration] Fixed username typo in %s: %d rows ('%s' → '%s')",
                    db_name, cursor.rowcount, wrong, correct,
                )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("[Migration] Failed to fix username in %s: %s", db_name, e)
