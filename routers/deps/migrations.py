"""
One-time data migrations that run on import.

- _migrate_bookmarks_add_username: assigns default user to bookmarks without one
- _migrate_papers_add_searched_by: assigns default user to papers without one
"""

import json
import logging
import os

from .storage import (
    BOOKMARKS_FILE,
    _bookmarks_lock,
    PAPERS_FILE,
    _papers_lock,
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
