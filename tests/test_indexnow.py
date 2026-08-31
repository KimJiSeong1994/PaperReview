"""Tests for IndexNow instant-indexing (routers/indexnow.py).

Hermetic: no network (submission is guarded off under PYTEST_CURRENT_TEST),
no real data files (posts are injected via a temp POSTS_FILE).
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from api_server import app
from routers import indexnow
from routers.indexnow import INDEXNOW_KEY, submit_indexnow


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_key_file_is_served(client: TestClient) -> None:
    resp = client.get(f"/api/indexnow/{INDEXNOW_KEY}.txt")
    assert resp.status_code == 200
    assert resp.text == INDEXNOW_KEY
    assert "text/plain" in resp.headers["content-type"]


def test_wrong_key_file_is_404(client: TestClient) -> None:
    assert client.get("/api/indexnow/deadbeef.txt").status_code == 404


def test_published_urls_lists_only_published_with_slug(monkeypatch, tmp_path) -> None:
    posts = {
        "posts": [
            {"slug": "live-1", "published": True},
            {"slug": "draft-1", "published": False},
            {"slug": "live-2", "published": True},
            {"published": True},  # no slug -> skipped
        ]
    }
    pf = tmp_path / "posts.json"
    pf.write_text(json.dumps(posts), encoding="utf-8")
    monkeypatch.setattr(indexnow, "POSTS_FILE", pf)

    urls = indexnow.published_urls()
    assert urls[0] == f"{indexnow.SITE_URL}/"
    assert f"{indexnow.SITE_URL}/blog" in urls
    assert f"{indexnow.SITE_URL}/blog/tags" in urls
    assert f"{indexnow.SITE_URL}/blog/live-1" in urls
    assert f"{indexnow.SITE_URL}/blog/live-2" in urls
    assert f"{indexnow.SITE_URL}/blog/draft-1" not in urls


def test_submit_is_noop_and_never_networks_in_tests() -> None:
    # PYTEST_CURRENT_TEST guard keeps this offline even with a non-empty list.
    assert asyncio.run(submit_indexnow(["https://jiphyeonjeon.kr/blog/x"])) is False
    assert asyncio.run(submit_indexnow([])) is False


def test_submit_noop_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(indexnow, "INDEXNOW_ENABLED", False)
    assert asyncio.run(submit_indexnow(["https://jiphyeonjeon.kr/"])) is False


def test_keylocation_is_root_scoped(monkeypatch) -> None:
    # Must be at the host root so /blog/* URLs pass IndexNow's directory-scope
    # verification (a /api/indexnow/ key would only cover /api/indexnow/*).
    assert indexnow.KEY_LOCATION == f"{indexnow.SITE_URL}/{INDEXNOW_KEY}.txt"
