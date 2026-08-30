"""The tag index merges case-collided tags and paginates them."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_server import app
import routers.blog as blog


def _post(tags: list[str], published: bool = True) -> dict:
    return {
        "id": "post",
        "title": "Post",
        "slug": "post",
        "excerpt": "",
        "content": "body",
        "author": "test-admin",
        "tags": tags,
        "category": "paper-review",
        "thumbnail_url": None,
        "created_at": "2026-08-08T00:00:00+09:00",
        "updated_at": None,
        "published": published,
        "reading_time_min": 1,
    }


def _get(monkeypatch, posts: list[dict], query: str = "") -> dict:
    monkeypatch.setattr(blog, "_load_posts", lambda: posts)
    response = TestClient(app).get(f"/api/blog/tags{query}")
    assert response.status_code == 200, response.text
    return response.json()


def test_case_collided_tags_merge_into_most_used_casing(monkeypatch) -> None:
    posts = [_post(["GraphRAG"])] + [_post(["graphrag"]) for _ in range(3)]

    body = _get(monkeypatch, posts)

    assert body["tags"] == [{"tag": "graphrag", "count": 4}]
    assert body["total"] == 1


def test_casing_tie_falls_back_to_lexicographically_first(monkeypatch) -> None:
    body = _get(monkeypatch, [_post(["LLM"]), _post(["llm"])])

    assert body["tags"] == [{"tag": "LLM", "count": 2}]


def test_sort_name_is_case_insensitive_alphabetical(monkeypatch) -> None:
    posts = [_post(["zebra"]), _post(["Apple"]), _post(["banana"]), _post(["그래프"])]

    body = _get(monkeypatch, posts, "?sort=name")

    assert [t["tag"] for t in body["tags"]] == ["Apple", "banana", "zebra", "그래프"]


def test_sort_count_orders_by_count_then_name(monkeypatch) -> None:
    posts = [_post(["rare"]), _post(["Beta"]), _post(["alpha"]), _post(["alpha"])]

    body = _get(monkeypatch, posts, "?sort=count")

    assert [(t["tag"], t["count"]) for t in body["tags"]] == [
        ("alpha", 2),
        ("Beta", 1),
        ("rare", 1),
    ]


def test_pagination_splits_merged_tags_without_overlap_or_gap(monkeypatch) -> None:
    # 5 distinct tags after merging "TAG3" into the more common "tag3".
    posts = [_post([f"tag{i}"]) for i in range(5)] + [_post(["TAG3"]), _post(["tag3"])]

    first = _get(monkeypatch, posts, "?limit=3&page=1")
    second = _get(monkeypatch, posts, "?limit=3&page=2")

    assert first["total"] == second["total"] == 5
    assert first["pages"] == second["pages"] == 2
    assert (first["page"], second["page"]) == (1, 2)
    names = [t["tag"] for t in first["tags"]] + [t["tag"] for t in second["tags"]]
    assert names == ["tag0", "tag1", "tag2", "tag3", "tag4"]
    assert [t["count"] for t in second["tags"]] == [3, 1]


def test_page_past_the_end_returns_empty_list(monkeypatch) -> None:
    body = _get(monkeypatch, [_post(["solo"])], "?page=9&limit=60")

    assert body["tags"] == []
    assert body["total"] == 1
    assert body["pages"] == 1


def test_unpublished_post_tags_are_excluded(monkeypatch) -> None:
    posts = [_post(["shipped"]), _post(["draft-only"], published=False)]

    body = _get(monkeypatch, posts)

    assert [t["tag"] for t in body["tags"]] == ["shipped"]
    assert body["total"] == 1


def test_no_params_returns_valid_paginated_response(monkeypatch) -> None:
    body = _get(monkeypatch, [_post(["one"]), _post(["two"])])

    assert body == {
        "tags": [{"tag": "one", "count": 1}, {"tag": "two", "count": 1}],
        "total": 2,
        "page": 1,
        "pages": 1,
    }


def test_empty_tag_set_still_reports_one_page(monkeypatch) -> None:
    body = _get(monkeypatch, [_post([])])

    assert body == {"tags": [], "total": 0, "page": 1, "pages": 1}
