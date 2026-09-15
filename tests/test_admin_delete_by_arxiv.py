"""
Admin paper deletion — both endpoints.

``DELETE /api/admin/papers/by-arxiv`` matches a record by its own ``arxiv_id``
(version suffix / ``arxiv:`` prefix ignored), so concurrent writes that shift
list positions cannot remove the wrong paper.  These tests pin:
* identity match + normalization (bare id, ``vN`` suffix, ``arxiv:`` prefix);
* metadata.total_papers is updated and only matching records are removed;
* no match -> 404; empty request -> 400.

``DELETE /api/admin/papers`` addresses by index, which a third of the corpus
needs (38 of 115 live records have no ``arxiv_id``).  Its tests live at the
bottom of this file and pin that an index means a position in the *unfiltered*
corpus and that it is verified against the record's fingerprint before deleting.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# Env must be primed before importing the app.
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-testing-only")
os.environ.setdefault("APP_PASSWORD", "test-admin-password")
os.environ.setdefault("APP_USERNAME", "test-admin")

from api_server import app  # noqa: E402
import routers.admin as admin  # noqa: E402
from routers.deps import get_admin_user  # noqa: E402


@pytest.fixture
def client():
    # Bypass get_admin_user's DB re-check; auth is covered elsewhere.
    app.dependency_overrides[get_admin_user] = lambda: "test-admin"
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_admin_user, None)


def _corpus():
    return {
        "papers": [
            {"title": "Keep A", "arxiv_id": "1111.00001"},
            {"title": "Del 1", "arxiv_id": "2305.17493"},          # bare
            {"title": "Keep B", "arxiv_id": "2222.00002v2"},
            {"title": "Del 2", "arxiv_id": "2305.03514v3"},        # version suffix
            {"title": "Del 3", "arxiv_id": "arXiv:2312.15524"},    # prefix form
        ],
        "metadata": {"total_papers": 5},
    }


def test_delete_by_arxiv_identity_and_normalization(client, monkeypatch):
    corpus = _corpus()
    saved = {}
    monkeypatch.setattr(admin, "_load_papers", lambda: corpus)
    monkeypatch.setattr(admin, "_save_papers", lambda data: saved.update(data=data))

    resp = client.request(
        "DELETE",
        "/api/admin/papers/by-arxiv",
        json={"arxiv_ids": ["2305.17493", "2305.03514", "2312.15524"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted_count"] == 3
    assert set(body["deleted_titles"]) == {"Del 1", "Del 2", "Del 3"}

    remaining = [p["title"] for p in saved["data"]["papers"]]
    assert remaining == ["Keep A", "Keep B"]  # positional neighbours untouched
    assert saved["data"]["metadata"]["total_papers"] == 2


def test_delete_by_arxiv_no_match_returns_404(client, monkeypatch):
    monkeypatch.setattr(admin, "_load_papers", _corpus)
    monkeypatch.setattr(admin, "_save_papers", lambda data: None)

    resp = client.request(
        "DELETE", "/api/admin/papers/by-arxiv", json={"arxiv_ids": ["9999.99999"]}
    )
    assert resp.status_code == 404


def test_delete_by_arxiv_empty_returns_400(client, monkeypatch):
    monkeypatch.setattr(admin, "_load_papers", _corpus)
    monkeypatch.setattr(admin, "_save_papers", lambda data: None)

    resp = client.request(
        "DELETE", "/api/admin/papers/by-arxiv", json={"arxiv_ids": []}
    )
    assert resp.status_code == 400


# ── Index path: DELETE /api/admin/papers ─────────────────────────────────────
#
# The index path stays because a third of the corpus has no arxiv_id (38 of 115
# live records), so by-arxiv cannot address every paper.  Its indices are
# positions in the *unfiltered* corpus and are verified against each record's
# fingerprint before anything is removed — a position alone is not an identity.


@pytest.fixture
def corpus(monkeypatch):
    """Mutable in-memory corpus shared by GET and DELETE within one test."""
    state = {"papers": [], "metadata": {"total_papers": 0}}

    def install(papers):
        state["papers"] = list(papers)
        state["metadata"] = {"total_papers": len(papers)}
        return state

    monkeypatch.setattr(admin, "_load_papers", lambda: state)
    monkeypatch.setattr(admin, "_save_papers", lambda data: state.update(data))
    install.titles = lambda: [p["title"] for p in state["papers"]]
    return install


def _mixed_corpus():
    return [
        {"title": "ALICE-0", "searched_by": "alice"},
        {"title": "BOB-0", "searched_by": "bob"},
        {"title": "BOB-1", "searched_by": "bob"},
        {"title": "ALICE-1", "searched_by": "alice"},
        {"title": "BOB-2", "searched_by": "bob"},
    ]


def _delete(client, rows):
    return client.request(
        "DELETE",
        "/api/admin/papers",
        json={"papers": [{"index": r["index"], "fingerprint": r["fingerprint"]} for r in rows]},
    )


def test_filtered_listing_reports_global_indices(client, corpus):
    """A username filter must not renumber rows: DELETE addresses the corpus."""
    corpus(_mixed_corpus())

    rows = client.get("/api/admin/papers?username=bob").json()["papers"]

    assert [(r["index"], r["title"]) for r in rows] == [
        (1, "BOB-0"),
        (2, "BOB-1"),
        (4, "BOB-2"),
    ]


def test_delete_from_member_folder_removes_the_paper_the_admin_picked(client, corpus):
    """Regression: filtered index 0 used to delete global index 0 (ALICE-0)."""
    corpus(_mixed_corpus())

    rows = client.get("/api/admin/papers?username=bob").json()["papers"]
    resp = _delete(client, rows[:1])

    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted_count"] == 1
    assert corpus.titles() == ["ALICE-0", "BOB-1", "ALICE-1", "BOB-2"]


def test_delete_from_a_later_page_of_a_filtered_folder(client, corpus):
    """Pagination variant: page offsets were counted within the filtered list."""
    corpus(_mixed_corpus() + [{"title": "BOB-3", "searched_by": "bob"}])

    body = client.get("/api/admin/papers?username=bob&page=2&page_size=2").json()
    rows = body["papers"]
    assert [(r["index"], r["title"]) for r in rows] == [(4, "BOB-2"), (5, "BOB-3")]
    assert body["total"] == 4

    resp = _delete(client, rows)

    assert resp.status_code == 200, resp.text
    assert corpus.titles() == ["ALICE-0", "BOB-0", "BOB-1", "ALICE-1"]


def test_retrying_a_delete_refuses_instead_of_eating_the_neighbour(client, corpus):
    """Regression: the same index sent twice used to delete two papers."""
    corpus([{"title": f"P{i}", "searched_by": "bob"} for i in range(5)])

    rows = client.get("/api/admin/papers").json()["papers"]
    assert _delete(client, rows[1:2]).status_code == 200
    assert corpus.titles() == ["P0", "P2", "P3", "P4"]

    retry = _delete(client, rows[1:2])  # same index + same stale fingerprint

    assert retry.status_code == 409
    assert corpus.titles() == ["P0", "P2", "P3", "P4"]


def test_one_stale_fingerprint_rejects_the_whole_request(client, corpus):
    """All-or-nothing: a single mismatch must delete nothing."""
    corpus([{"title": f"P{i}", "searched_by": "bob"} for i in range(5)])

    rows = client.get("/api/admin/papers").json()["papers"]
    tampered = [rows[0], {**rows[2], "fingerprint": "deadbeefdeadbeef"}]

    resp = _delete(client, tampered)

    assert resp.status_code == 409
    assert "nothing was deleted" in resp.json()["detail"]
    assert corpus.titles() == ["P0", "P1", "P2", "P3", "P4"]


def test_delete_out_of_range_index_returns_400(client, corpus):
    corpus(_mixed_corpus())

    resp = client.request(
        "DELETE", "/api/admin/papers", json={"papers": [{"index": 99, "fingerprint": "x"}]}
    )

    assert resp.status_code == 400
    assert corpus.titles() == ["ALICE-0", "BOB-0", "BOB-1", "ALICE-1", "BOB-2"]


def test_fingerprint_distinguishes_records_that_share_a_position(client, corpus):
    """Same title, different owner -> different fingerprint."""
    corpus([
        {"title": "Attention Is All You Need", "searched_by": "alice"},
        {"title": "Attention Is All You Need", "searched_by": "bob"},
    ])

    rows = client.get("/api/admin/papers").json()["papers"]

    assert rows[0]["fingerprint"] != rows[1]["fingerprint"]
