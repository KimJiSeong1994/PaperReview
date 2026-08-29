"""Blog list search (``GET /api/blog/posts?q=``) should find body-only matches."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api_server import app
import routers.blog as blog


_SHARED = {
    "author": "test-admin",
    "thumbnail_url": None,
    "updated_at": None,
    "published": True,
    "reading_time_min": 1,
}

POSTS = [
    {
        **_SHARED,
        "id": "body",
        "title": "임베딩 파이프라인 정리",
        "slug": "embedding-pipeline",
        "excerpt": "임베딩 모델을 통일한 이야기.",
        "tags": ["embedding"],
        "category": "engineering",
        # Newest post, so a relevance regression cannot hide behind recency:
        # the title match below must still outrank this body-only match.
        "created_at": "2026-01-04T00:00:00+09:00",
        # "랭킹" and "검색을" only exist in the body — metadata search would miss both.
        "content": "앞부분 " * 40 + "랭킹 가중치를 측정으로 고르고 검색을 개선했다. " + "뒷부분 " * 40,
    },
    {
        **_SHARED,
        "id": "title",
        "title": "랭킹 실험 노트",
        "slug": "ranking-notes",
        "excerpt": "실험 요약.",
        "tags": ["eval"],
        "category": "paper-review",
        "created_at": "2026-01-02T00:00:00+09:00",
        "content": "본문에는 관련 단어가 없다.",
    },
    {
        **_SHARED,
        "id": "other",
        # "aggregation"/"training" contain "gat"/"ai" mid-word — must NOT match.
        "title": "GraphSAGE Review",
        "slug": "graphsage-review",
        "excerpt": "Inductive representation learning.",
        "tags": ["graph"],
        "category": "paper-review",
        "created_at": "2026-01-03T00:00:00+09:00",
        "content": "Neighborhood sampling, aggregation and training embeddings.",
    },
    {
        **_SHARED,
        "id": "gat",
        "title": "Graph Attention Networks (GAT)",
        "slug": "gat-paper",
        "excerpt": "Masked self-attention layers.",
        "tags": ["attention"],
        "category": "paper-review",
        # Oldest, so only relevance can put it above the mid-word candidates.
        "created_at": "2025-12-01T00:00:00+09:00",
        "content": "Attention over neighborhoods.",
    },
]


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(blog, "_load_posts", lambda: [dict(p) for p in POSTS])
    return TestClient(app)


def _slugs(response) -> list[str]:
    return [p["slug"] for p in response.json()["posts"]]


def test_body_only_match_is_found(client: TestClient) -> None:
    """"랭킹" hits one post via its body and another via its title."""
    response = client.get("/api/blog/posts", params={"q": "랭킹"})

    assert response.status_code == 200
    assert set(_slugs(response)) == {"embedding-pipeline", "ranking-notes"}


def test_all_tokens_must_match(client: TestClient) -> None:
    response = client.get("/api/blog/posts", params={"q": "랭킹 가중치"})
    assert _slugs(response) == ["embedding-pipeline"]

    response = client.get("/api/blog/posts", params={"q": "랭킹 존재하지않는단어"})
    assert _slugs(response) == []


def test_match_is_case_insensitive(client: TestClient) -> None:
    assert _slugs(client.get("/api/blog/posts", params={"q": "graphsage"})) == [
        "graphsage-review"
    ]
    assert _slugs(client.get("/api/blog/posts", params={"q": "GRAPHSAGE"})) == [
        "graphsage-review"
    ]


def test_korean_substring_matches_inflected_word(client: TestClient) -> None:
    """"검색" must match "검색을" — Korean is agglutinative."""
    assert _slugs(client.get("/api/blog/posts", params={"q": "검색"})) == [
        "embedding-pipeline"
    ]


def test_title_match_ranks_above_body_match(client: TestClient) -> None:
    assert _slugs(client.get("/api/blog/posts", params={"q": "랭킹"})) == [
        "ranking-notes",
        "embedding-pipeline",
    ]


def test_snippet_only_for_body_matches(client: TestClient) -> None:
    posts = {p["slug"]: p for p in client.get("/api/blog/posts", params={"q": "랭킹"}).json()["posts"]}

    assert posts["ranking-notes"]["snippet"] is None
    snippet = posts["embedding-pipeline"]["snippet"]
    assert snippet is not None
    assert "랭킹" in snippet
    assert snippet.startswith("…") and snippet.endswith("…")
    assert "\n" not in snippet


def test_content_never_leaks_into_list_response(client: TestClient) -> None:
    for params in ({}, {"q": "랭킹"}):
        body = client.get("/api/blog/posts", params=params).json()
        assert all("content" not in p for p in body["posts"])


def test_blank_q_behaves_like_absent_q(client: TestClient) -> None:
    absent = client.get("/api/blog/posts").json()
    for blank in ("", "   "):
        assert client.get("/api/blog/posts", params={"q": blank}).json() == absent


def test_q_combines_with_category_filter(client: TestClient) -> None:
    response = client.get(
        "/api/blog/posts", params={"q": "랭킹", "category": "paper-review"}
    )
    assert _slugs(response) == ["ranking-notes"]
    assert response.json()["total"] == 1


def test_pagination_reflects_filtered_count(client: TestClient) -> None:
    body = client.get("/api/blog/posts", params={"q": "랭킹", "limit": 1}).json()

    assert body["total"] == 2
    assert body["pages"] == 2
    assert [p["slug"] for p in body["posts"]] == ["ranking-notes"]

    page2 = client.get("/api/blog/posts", params={"q": "랭킹", "limit": 1, "page": 2}).json()
    assert [p["slug"] for p in page2["posts"]] == ["embedding-pipeline"]


def test_ascii_token_does_not_match_mid_word(client: TestClient) -> None:
    """"gat"/"ai" must not fire inside "aggregation"/"training"."""
    assert "graphsage-review" not in _slugs(client.get("/api/blog/posts", params={"q": "gat"}))
    assert _slugs(client.get("/api/blog/posts", params={"q": "ai"})) == []


def test_ascii_token_still_prefix_matches(client: TestClient) -> None:
    """The boundary is left-only, so "embed" still finds "embeddings"."""
    # graphsage-review only carries "embeddings" in its body — a full-word
    # boundary rule would drop it. embedding-pipeline matches on its tag.
    assert _slugs(client.get("/api/blog/posts", params={"q": "embed"})) == [
        "embedding-pipeline",
        "graphsage-review",
    ]


def test_exact_ascii_match_outranks_mid_word_candidates(client: TestClient) -> None:
    assert _slugs(client.get("/api/blog/posts", params={"q": "gat"})) == ["gat-paper"]
