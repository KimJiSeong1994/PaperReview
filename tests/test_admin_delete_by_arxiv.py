"""
Admin paper deletion by arXiv id (DELETE /api/admin/papers/by-arxiv).

Identity-based deletion is safer than the positional ``DELETE /api/admin/papers``
(by index) against the shared corpus: a record is matched by its own
``arxiv_id`` (version suffix / ``arxiv:`` prefix ignored), so concurrent writes
that shift list positions cannot remove the wrong paper.

These tests pin:
* identity match + normalization (bare id, ``vN`` suffix, ``arxiv:`` prefix);
* metadata.total_papers is updated and only matching records are removed;
* no match -> 404; empty request -> 400.
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
