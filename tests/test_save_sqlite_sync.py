"""Tests for the /save -> SQLite sync (routers/papers.py, P2-3).

The ``POST /api/save`` handler historically wrote only to ``data/papers.json``
(which deep-review reads), so papers ingested via ``/api/save`` were invisible
to ``get_paper`` and the SQLite-backed paper lookup/search. The P2-3 patch also
upserts saved papers into ``_paper_db`` so they become findable.

These tests validate the patch's core chain in isolation (temp DB, no real-data
pollution, no app-server dependencies): flatten the per-source ``results`` dict
-> ensure a canonical ``doc_id`` via :func:`generate_doc_id` -> ``PaperDB.save_papers``
(upsert) -> ``get_paper(doc_id)`` resolves.

``tests/conftest.py`` puts the project root on ``sys.path`` so ``src.*`` imports work.
"""

import tempfile
from pathlib import Path

from src.storage.paper_db import PaperDB
from src.utils.paper_utils import generate_doc_id


def _sync_flatten(results):
    """Mirror of the sync logic inserted into ``routers.papers.save_papers``."""
    flat = []
    for paper_list in results.values():
        for paper in paper_list:
            if not paper.get("doc_id"):
                paper["doc_id"] = generate_doc_id(paper.get("title", ""))
            flat.append(paper)
    return flat


def _fresh_db():
    return PaperDB(db_path=Path(tempfile.mkdtemp()) / "papers.db")


def test_ingested_paper_becomes_findable_by_get_paper():
    db = _fresh_db()
    results = {
        "arxiv": [
            {
                "title": "Deep Binding of Language Model Virtual Personas",
                "abstract": "abc",
                "arxiv_id": "2504.11673",
                "source": "arxiv",
                "pdf_url": "https://arxiv.org/pdf/2504.11673",
                "year": "2025",
            }
        ]
    }
    flat = _sync_flatten(results)
    assert db.save_papers(flat) == 1

    doc_id = generate_doc_id("Deep Binding of Language Model Virtual Personas")
    got = db.get_paper(doc_id)
    assert got is not None, "get_paper must resolve the synced paper by canonical doc_id"
    assert got["title"].startswith("Deep Binding")


def test_explicit_doc_id_is_preserved():
    db = _fresh_db()
    flat = _sync_flatten({"arxiv": [{"title": "T", "doc_id": "explicit-123", "source": "arxiv"}]})
    assert flat[0]["doc_id"] == "explicit-123"
    db.save_papers(flat)
    assert db.get_paper("explicit-123") is not None


def test_upsert_is_idempotent_and_updates():
    db = _fresh_db()
    db.save_papers(_sync_flatten({"arxiv": [{"title": "Anthology paper", "abstract": "v1", "source": "arxiv"}]}))
    db.save_papers(_sync_flatten({"arxiv": [{"title": "Anthology paper", "abstract": "v2", "source": "arxiv"}]}))

    got = db.get_paper(generate_doc_id("Anthology paper"))
    assert got is not None
    assert got["abstract"] == "v2", "ON CONFLICT upsert should update the abstract"


def test_multi_source_results_all_flattened_and_saved():
    db = _fresh_db()
    results = {
        "arxiv": [{"title": "PaperA", "source": "arxiv"}],
        "openalex": [{"title": "PaperB", "source": "openalex"}],
        "dblp": [],
    }
    flat = _sync_flatten(results)
    assert len(flat) == 2
    db.save_papers(flat)
    assert db.get_paper(generate_doc_id("PaperA")) is not None
    assert db.get_paper(generate_doc_id("PaperB")) is not None


def test_empty_results_no_crash():
    db = _fresh_db()
    flat = _sync_flatten({"arxiv": [], "openalex": []})
    assert flat == []
    # The patch guards the upsert with `if flat:`; emulate that no-op path.
    assert db.save_papers(flat) == 0
