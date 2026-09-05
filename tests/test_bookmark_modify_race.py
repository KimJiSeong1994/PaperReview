"""Concurrent read-modify-write on bookmarks must not lose a write.

`modify_bookmarks()` reads the whole list, hands it to the caller, and writes
it back — deleting anything the caller dropped. Before the read and the write
shared one transaction, two of these could interleave and the second commit
would silently undo the first: a new bookmark vanishing, or a deleted one
coming back. Two open tabs is the ordinary case, and production runs two
uvicorn workers, so the writers need not even share a process.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from routers.deps import storage


def _bm(bid: str, title: str) -> dict:
    return {
        "id": bid,
        "username": "alice",
        "topic": "General",
        "title": title,
        "papers": [],
        "created_at": "2026-01-01T00:00:00",
    }


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Point the storage layer at a throwaway database."""
    monkeypatch.setattr(storage, "BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    storage._bookmark_dbs.clear()
    yield
    storage._bookmark_dbs.clear()


def _ids() -> set[str]:
    return {b["id"] for b in storage.load_bookmarks()["bookmarks"]}


def _run_both(first, second, head_start=0.2):
    """Start *first*, let it get inside its block, then run *second*."""
    errors: list[BaseException] = []

    def guard(fn):
        def inner():
            try:
                fn()
            except BaseException as exc:  # surfaced after join
                errors.append(exc)
        return inner

    t1 = threading.Thread(target=guard(first))
    t1.start()
    time.sleep(head_start / 2)
    t2 = threading.Thread(target=guard(second))
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)
    assert not errors, errors


def test_two_appends_both_survive(store):
    with storage.modify_bookmarks() as data:
        data["bookmarks"].append(_bm("a", "first"))

    def slow_append():
        with storage.modify_bookmarks() as data:
            time.sleep(0.2)          # hold the window open
            data["bookmarks"].append(_bm("b", "slow"))

    def quick_append():
        with storage.modify_bookmarks() as data:
            data["bookmarks"].append(_bm("c", "quick"))

    _run_both(slow_append, quick_append)
    assert _ids() == {"a", "b", "c"}


def test_a_delete_is_not_undone_by_a_concurrent_edit(store):
    with storage.modify_bookmarks() as data:
        data["bookmarks"] += [_bm("a", "keep"), _bm("doomed", "delete me")]

    def slow_edit():
        with storage.modify_bookmarks() as data:
            time.sleep(0.2)
            for bm in data["bookmarks"]:
                if bm["id"] == "a":
                    bm["title"] = "edited"

    def delete_one():
        with storage.modify_bookmarks() as data:
            data["bookmarks"] = [b for b in data["bookmarks"] if b["id"] != "doomed"]

    _run_both(slow_edit, delete_one)
    assert "doomed" not in _ids(), "a deleted bookmark came back"
    assert _ids() == {"a"}


def test_raising_inside_the_block_writes_nothing(store):
    with storage.modify_bookmarks() as data:
        data["bookmarks"].append(_bm("a", "kept"))

    with pytest.raises(RuntimeError):
        with storage.modify_bookmarks() as data:
            data["bookmarks"].append(_bm("never", "rolled back"))
            raise RuntimeError("abort")

    assert _ids() == {"a"}


def test_returning_from_inside_the_block_still_commits(store):
    """`share.py` returns its response from inside the block."""
    def add_and_return():
        with storage.modify_bookmarks() as data:
            data["bookmarks"].append(_bm("a", "committed on return"))
            return "done"

    assert add_and_return() == "done"
    assert _ids() == {"a"}
