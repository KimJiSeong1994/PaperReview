"""Blog slug generation should produce clean SEO-friendly URLs."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_server import app
import routers.blog as blog
from routers.deps import get_admin_user


def test_generate_slug_drops_random_id_suffix() -> None:
    assert (
        blog._generate_slug("SkillOpt Search Policy Training", "90c0bb4ee568")
        == "skillopt-search-policy-training"
    )


def test_generate_slug_drops_trailing_year_suffix() -> None:
    assert (
        blog._generate_slug(
            "GraphSAGE Inductive Representation Learning Large Graphs Review 2026",
            "graphsage-170602216-2026-review",
        )
        == "graphsage-inductive-representation-learning-large-graphs-review"
    )
    assert (
        blog._generate_slug("Best Papers from 2026 Survey", "abc12345")
        == "best-papers-from-2026-survey"
    )


def test_unique_slug_adds_counter_only_on_collision() -> None:
    posts = [
        {"id": "a", "slug": "skillopt-search-policy-training"},
        {"id": "b", "slug": "skillopt-search-policy-training-2"},
    ]

    assert blog._unique_slug("new-post", posts) == "new-post"
    assert blog._unique_slug("skillopt-search-policy-training", posts) == (
        "skillopt-search-policy-training-3"
    )
    assert (
        blog._unique_slug(
            "skillopt-search-policy-training",
            posts,
            current_post_id="a",
        )
        == "skillopt-search-policy-training"
    )


def test_create_post_uses_clean_slug_and_resolves_collision(monkeypatch) -> None:
    existing = [
        {
            "id": "existing",
            "title": "SkillOpt Search Policy Training",
            "slug": "skillopt-search-policy-training",
            "excerpt": "old",
            "content": "old content",
            "author": "test-admin",
            "tags": [],
            "category": "engineering",
            "thumbnail_url": None,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": None,
            "published": True,
            "reading_time_min": 1,
        }
    ]
    saved: dict[str, list[dict]] = {}

    monkeypatch.setattr(blog, "_load_posts", lambda: list(existing))
    monkeypatch.setattr(blog, "_save_posts", lambda posts: saved.update(posts=posts))
    monkeypatch.setattr(blog, "_indexnow_submit_async", lambda urls: None)
    app.dependency_overrides[get_admin_user] = lambda: "test-admin"
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/blog/posts",
            json={
                "title": "SkillOpt Search Policy Training",
                "content": "new content body",
                "published": False,
            },
        )
    finally:
        app.dependency_overrides.pop(get_admin_user, None)

    assert resp.status_code == 201, resp.text
    assert resp.json()["slug"] == "skillopt-search-policy-training-2"
    assert saved["posts"][-1]["slug"] == "skillopt-search-policy-training-2"
