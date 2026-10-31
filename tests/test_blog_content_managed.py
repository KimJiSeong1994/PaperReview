"""Admin blog writes are refused while BLOG_CONTENT_DIR points at the content-repo checkout."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api_server import app
import routers.blog as blog
from routers.deps import get_admin_user


@pytest.fixture
def admin_client(monkeypatch: pytest.MonkeyPatch):
    saved: list[list[dict]] = []
    stored = [{"id": "p1", "slug": "one", "title": "One", "content": "x", "published": True, "tags": []}]
    monkeypatch.setattr(blog, "_load_posts", lambda: stored)
    monkeypatch.setattr(blog, "_save_posts", lambda posts: saved.append(posts))
    monkeypatch.setattr(blog, "_record_deleted", lambda slug: None)
    monkeypatch.setattr(blog, "_indexnow_submit_async", lambda urls: None)
    app.dependency_overrides[get_admin_user] = lambda: "test-admin"
    try:
        yield TestClient(app), saved
    finally:
        app.dependency_overrides.pop(get_admin_user, None)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/api/blog/posts", {"title": "T", "content": "c"}),
        ("PUT", "/api/blog/posts/p1", {"title": "T2"}),
        ("DELETE", "/api/blog/posts/p1", None),
    ],
)
def test_writes_refused_when_content_repo_is_the_source(
    monkeypatch: pytest.MonkeyPatch, admin_client, method: str, path: str, body
) -> None:
    client, saved = admin_client
    monkeypatch.setenv("BLOG_CONTENT_DIR", "/srv/jiphyeonjeon-content")
    response = client.request(method, path, json=body)
    assert response.status_code == 409, response.text
    assert "jiphyeonjeon-content" in response.json()["detail"]
    assert saved == []


def test_writes_allowed_against_the_in_repo_copy(monkeypatch: pytest.MonkeyPatch, admin_client) -> None:
    client, saved = admin_client
    monkeypatch.delenv("BLOG_CONTENT_DIR", raising=False)
    response = client.post("/api/blog/posts", json={"title": "T", "content": "c"})
    assert response.status_code == 201, response.text
    assert len(saved) == 1
