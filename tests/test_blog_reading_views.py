"""Regression tests for easy/default and optional detailed blog reading."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from api_server import app
import routers.blog as blog
import routers.seo as seo
from routers.deps import get_admin_user
from scripts import submit_indexnow


EASY_BODY = "# Easy heading\n\nEASY-BODY-MARKER short explanation."
DEEP_BODY = "# Detailed heading\n\nDEEP-BODY-MARKER " + "analysis " * 500


def _post(
    *, published: bool = True, deep_content: str | None = DEEP_BODY,
    index_deep_view: bool = False,
) -> dict:
    return {
        "id": "reading-post-id",
        "title": "Two Reading Levels",
        "slug": "two-reading-levels",
        "excerpt": "A shared summary.",
        "content": EASY_BODY,
        "deep_content": deep_content,
        "index_deep_view": index_deep_view,
        "author": "test-admin",
        "tags": ["reading"],
        "category": "engineering",
        "thumbnail_url": None,
        "created_at": "2026-09-20T00:00:00+00:00",
        "updated_at": None,
        "published": published,
        "reading_time_min": blog._estimate_reading_time(EASY_BODY),
    }


@pytest.fixture
def posts_client(monkeypatch) -> TestClient:
    posts = [_post(), _post(published=False) | {"id": "draft", "slug": "draft"}]
    monkeypatch.setattr(blog, "_load_posts", lambda: posts)
    monkeypatch.setattr(seo, "_load_posts", lambda: posts)
    monkeypatch.setattr(seo, "_load_deleted", lambda: set())
    return TestClient(app)


def _json_ld_graph(document: str) -> list[dict]:
    match = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', document, re.S
    )
    assert match is not None
    return json.loads(match.group(1))["@graph"]


def _posting_json_ld(document: str) -> dict:
    return next(
        node for node in _json_ld_graph(document) if node.get("@type") == "BlogPosting"
    )


def test_source_collection_has_no_primary_paper_in_either_view(monkeypatch) -> None:
    post = _post() | {
        "category": "paper-review",
        "content": "**Sources:** [Program](https://example.com/program)\n\nEasy collection.",
        "deep_content": '**Paper:** A. Author (2024). "A selected paper". arXiv:2404.19737\n\nDetailed collection.',
    }
    monkeypatch.setattr(seo, "_load_posts", lambda: [post])
    client = TestClient(app)
    for suffix in ("", "?view=deep"):
        response = client.get("/blog/two-reading-levels" + suffix)
        assert response.status_code == 200
        assert "blog-detail-reading-link" in response.text
        assert 'class="blog-detail-pdf-link"' not in response.text
        graph = _json_ld_graph(response.text)
        assert not any(node.get("@type") == "ScholarlyArticle" for node in graph)
        assert "citation" not in _posting_json_ld(response.text)


def test_detail_returns_both_bodies_and_list_search_never_leaks_them(
    posts_client: TestClient,
) -> None:
    detail = posts_client.get("/api/blog/posts/two-reading-levels")
    assert detail.status_code == 200
    assert detail.json()["content"] == EASY_BODY
    assert detail.json()["deep_content"] == DEEP_BODY
    assert detail.json()["deep_reading_time_min"] == blog._estimate_reading_time(
        DEEP_BODY
    )

    results = posts_client.get("/api/blog/posts", params={"q": "DEEP-BODY-MARKER"})
    assert results.status_code == 200
    payload = results.json()
    assert [post["slug"] for post in payload["posts"]] == ["two-reading-levels"]
    assert "content" not in payload["posts"][0]
    assert "deep_content" not in payload["posts"][0]
    assert "deep_reading_time_min" not in payload["posts"][0]
    assert posts_client.get("/api/blog/posts/draft").status_code == 404


def test_create_update_preserves_and_clears_deep_content(monkeypatch) -> None:
    stored: list[dict] = []

    monkeypatch.setattr(blog, "_load_posts", lambda: stored)
    monkeypatch.setattr(
        blog, "_save_posts", lambda posts: stored.__setitem__(slice(None), posts)
    )
    monkeypatch.setattr(blog, "_indexnow_submit_async", lambda urls: None)
    app.dependency_overrides[get_admin_user] = lambda: "test-admin"
    try:
        client = TestClient(app)
        created = client.post(
            "/api/blog/posts",
            json={
                "title": "Created reading post",
                "content": EASY_BODY,
                "deep_content": DEEP_BODY,
                "published": False,
            },
        )
        assert created.status_code == 201, created.text
        post_id = created.json()["id"]
        assert created.json()["deep_content"] == DEEP_BODY
        assert created.json()["deep_reading_time_min"] == blog._estimate_reading_time(
            DEEP_BODY
        )

        partial = client.put(f"/api/blog/posts/{post_id}", json={"excerpt": "Updated"})
        assert partial.status_code == 200
        assert partial.json()["deep_content"] == DEEP_BODY

        cleared = client.put(f"/api/blog/posts/{post_id}", json={"deep_content": None})
        assert cleared.status_code == 200
        assert cleared.json()["deep_content"] is None
        assert cleared.json()["deep_reading_time_min"] is None

        blank = client.put(f"/api/blog/posts/{post_id}", json={"deep_content": "  \n"})
        assert blank.status_code == 200
        assert blank.json()["deep_content"] is None
    finally:
        app.dependency_overrides.pop(get_admin_user, None)


def test_ssr_selects_view_with_stable_canonical_and_per_view_metadata(
    posts_client: TestClient,
) -> None:
    default = posts_client.get("/blog/two-reading-levels")
    assert default.status_code == 200
    assert "EASY-BODY-MARKER" in default.text
    assert "DEEP-BODY-MARKER" not in default.text
    assert 'class="blog-detail-reading-mode">쉬운 읽기</span>' in default.text
    assert 'class="blog-detail-pdf-link blog-detail-reading-link"' in default.text
    assert 'href="/blog/two-reading-levels?view=deep"' in default.text
    assert f"{blog._estimate_reading_time(EASY_BODY)} min read" in default.text
    assert _posting_json_ld(default.text)["articleBody"] == EASY_BODY

    deep = posts_client.get("/blog/two-reading-levels", params={"view": "deep"})
    assert deep.status_code == 200
    assert "DEEP-BODY-MARKER" in deep.text
    assert "EASY-BODY-MARKER" not in deep.text
    assert 'class="blog-detail-reading-mode">상세 읽기</span>' in deep.text
    assert 'class="blog-detail-pdf-link blog-detail-reading-link"' in deep.text
    assert 'href="/blog/two-reading-levels"' in deep.text
    assert f"{blog._estimate_reading_time(DEEP_BODY)} min read" in deep.text
    assert _posting_json_ld(deep.text)["articleBody"] == DEEP_BODY

    canonical = (
        '<link rel="canonical" href="https://jiphyeonjeon.kr/blog/two-reading-levels">'
    )
    assert canonical in default.text
    assert canonical in deep.text


def test_unknown_view_and_missing_detail_fall_back_to_default(monkeypatch) -> None:
    posts = [
        _post(deep_content="  \n"),
        _post(published=False) | {"id": "draft", "slug": "draft"},
    ]
    monkeypatch.setattr(seo, "_load_posts", lambda: posts)
    monkeypatch.setattr(seo, "_load_deleted", lambda: set())
    client = TestClient(app)

    unknown = client.get("/blog/two-reading-levels", params={"view": "anything" * 20})
    missing_deep = client.get("/blog/two-reading-levels", params={"view": "deep"})
    assert unknown.status_code == missing_deep.status_code == 200
    assert "EASY-BODY-MARKER" in unknown.text
    assert "EASY-BODY-MARKER" in missing_deep.text
    assert "상세 읽기" not in missing_deep.text
    assert "articleBody" not in _posting_json_ld(missing_deep.text)
    assert client.get("/blog/draft", params={"view": "deep"}).status_code == 404


def test_deep_view_keeps_default_body_paper_identity(monkeypatch) -> None:
    easy_body = (
        "# Canonical review\n\n"
        '**Paper:** Author, Alice. (2024). "Canonical Paper." '
        "arXiv:2401.12345. https://doi.org/10.1000/canonical\n\n"
        "## Review\n\nEasy explanation."
    )
    deep_body = (
        "# Detailed analysis\n\n"
        "A comparison mentions arXiv:2502.54321 and doi:10.1000/distractor, "
        "but has no Paper header."
    )
    post = _post() | {
        "category": "paper-review",
        "content": easy_body,
        "deep_content": deep_body,
        "reading_time_min": blog._estimate_reading_time(easy_body),
    }
    monkeypatch.setattr(seo, "_load_posts", lambda: [post])
    monkeypatch.setattr(seo, "_load_deleted", lambda: set())
    client = TestClient(app)

    easy = client.get("/blog/two-reading-levels").text
    deep = client.get("/blog/two-reading-levels", params={"view": "deep"}).text
    easy_graph = _json_ld_graph(easy)
    deep_graph = _json_ld_graph(deep)
    easy_posting = next(n for n in easy_graph if n.get("@type") == "BlogPosting")
    deep_posting = next(n for n in deep_graph if n.get("@type") == "BlogPosting")

    canonical_id = "https://arxiv.org/abs/2401.12345"
    assert easy_posting["about"] == deep_posting["about"] == {"@id": canonical_id}
    assert easy_posting["citation"] == deep_posting["citation"] == {
        "@id": canonical_id
    }
    assert easy_posting["articleBody"] == easy_body
    assert deep_posting["articleBody"] == deep_body
    assert easy_posting["wordCount"] == len(easy_body.split())
    assert deep_posting["wordCount"] == len(deep_body.split())

    for graph in (easy_graph, deep_graph):
        paper = next(n for n in graph if n.get("@type") == "ScholarlyArticle")
        identifiers = {(item["propertyID"], item["value"]) for item in paper["identifier"]}
        assert identifiers == {
            ("arXiv", "2401.12345"),
            ("DOI", "10.1000/canonical"),
        }


def test_opted_in_views_have_distinct_index_identity(monkeypatch) -> None:
    post = _post(index_deep_view=True) | {
        "content": EASY_BODY + "\n\n## FAQ\n### What is it?\nAn easy answer.",
        "deep_content": DEEP_BODY + "\n\n## FAQ\n### What is it?\nA detailed answer.",
    }
    monkeypatch.setattr(seo, "_load_posts", lambda: [post])
    monkeypatch.setattr(seo, "_load_deleted", lambda: set())
    client = TestClient(app)
    easy = client.get("/blog/two-reading-levels")
    deep = client.get("/blog/two-reading-levels?view=deep")
    base = "https://jiphyeonjeon.kr/blog/two-reading-levels"
    for response, url, suffix, body in (
        (easy, base, "쉬운 읽기", post["content"]),
        (deep, base + "?view=deep", "상세 읽기", post["deep_content"]),
    ):
        assert response.status_code == 200
        assert f'<link rel="canonical" href="{url.replace("&", "&amp;")}">' in response.text
        assert f" · {suffix}</title>" in response.text
        assert 'content="index, follow' in response.text
        graph = _json_ld_graph(response.text)
        posting = next(n for n in graph if n.get("@type") == "BlogPosting")
        faq = next(n for n in graph if n.get("@type") == "FAQPage")
        assert posting["url"] == url
        assert posting["mainEntityOfPage"]["@id"] == url
        assert posting["articleBody"] == body
        assert faq["@id"] == url + "#faq"
    unknown = client.get("/blog/two-reading-levels?view=unknown")
    assert f'<link rel="canonical" href="{base}">' in unknown.text
    assert " · 쉬운 읽기</title>" in unknown.text

    sitemap = client.get("/sitemap.xml")
    locs = [node.text for node in ET.fromstring(sitemap.text).iter() if node.tag.endswith("}loc")]
    assert base in locs
    assert base + "?view=deep" in locs
    assert sitemap.text.count(base + "?view=deep") == 1


def test_deep_indexing_requires_published_nonblank_opt_in(monkeypatch) -> None:
    posts = [
        _post(index_deep_view=False),
        _post(index_deep_view=True, deep_content="  ") | {"slug": "blank"},
        _post(index_deep_view=True, published=False) | {"slug": "draft"},
    ]
    monkeypatch.setattr(seo, "_load_posts", lambda: posts)
    monkeypatch.setattr(seo, "_load_deleted", lambda: set())
    client = TestClient(app)
    locs = [node.text for node in ET.fromstring(client.get("/sitemap.xml").text).iter()
            if node.tag.endswith("}loc")]
    assert not any("?view=deep" in loc for loc in locs)
    assert not any("/draft" in loc for loc in locs)
    default_deep = client.get("/blog/two-reading-levels?view=deep")
    assert '<link rel="canonical" href="https://jiphyeonjeon.kr/blog/two-reading-levels">' in default_deep.text
    blank = client.get("/blog/blank?view=deep")
    assert '<link rel="canonical" href="https://jiphyeonjeon.kr/blog/blank">' in blank.text
    assert client.get("/blog/draft?view=deep").status_code == 404


def test_indexnow_sitemap_parser_keeps_query_without_image_loc(monkeypatch) -> None:
    xml = b'''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
        <url><loc>https://jiphyeonjeon.kr/blog/evo-ontology?view=deep&amp;ref=x</loc>
        <image:image><image:loc>https://jiphyeonjeon.kr/image.png</image:loc></image:image></url>
        <url><loc>https://jiphyeonjeon.kr.evil.example/blog/other</loc></url>
        </urlset>'''
    monkeypatch.setattr(submit_indexnow, "_get", lambda url: xml)
    assert submit_indexnow.build_url_list() == [
        "https://jiphyeonjeon.kr/blog/evo-ontology?view=deep&ref=x"
    ]


def test_indexnow_notifies_both_views_and_removed_deep(monkeypatch) -> None:
    stored: list[dict] = []
    notified: list[list[str]] = []
    monkeypatch.setattr(blog, "_load_posts", lambda: stored)
    monkeypatch.setattr(blog, "_save_posts", lambda posts: stored.__setitem__(slice(None), posts))
    monkeypatch.setattr(blog, "_indexnow_submit_async", lambda urls: notified.append(urls))
    monkeypatch.setattr(blog, "_record_deleted", lambda slug: None)
    app.dependency_overrides[get_admin_user] = lambda: "test-admin"
    try:
        client = TestClient(app)
        created = client.post("/api/blog/posts", json={
            "title": "Index both views", "slug": "index-both-views",
            "content": EASY_BODY, "deep_content": DEEP_BODY,
            "index_deep_view": True,
        })
        assert created.status_code == 201
        assert created.json()["index_deep_view"] is True
        post_id = created.json()["id"]
        base = blog._indexnow_post_url("index-both-views")
        assert notified[-1] == [base, base + "?view=deep"]
        updated = client.put(f"/api/blog/posts/{post_id}", json={"excerpt": "New excerpt"})
        assert updated.status_code == 200
        assert notified[-1] == [base, base + "?view=deep"]
        cleared = client.put(f"/api/blog/posts/{post_id}", json={"deep_content": None})
        assert cleared.status_code == 200
        assert notified[-1] == [base, base + "?view=deep"]
        assert cleared.json()["index_deep_view"] is True
        restored = client.put(f"/api/blog/posts/{post_id}", json={"deep_content": DEEP_BODY})
        assert restored.status_code == 200
        assert notified[-1] == [base, base + "?view=deep"]
        unpublished = client.put(f"/api/blog/posts/{post_id}", json={"published": False})
        assert unpublished.status_code == 200
        assert notified[-1] == [base, base + "?view=deep"]
        republished = client.put(f"/api/blog/posts/{post_id}", json={"published": True})
        assert republished.status_code == 200
        assert notified[-1] == [base, base + "?view=deep"]
        renamed = client.put(f"/api/blog/posts/{post_id}", json={"slug": "renamed-views"})
        assert renamed.status_code == 200
        renamed_base = blog._indexnow_post_url("renamed-views")
        assert notified[-1] == [
            renamed_base, renamed_base + "?view=deep", base, base + "?view=deep"
        ]
        deleted = client.delete(f"/api/blog/posts/{post_id}")
        assert deleted.status_code == 200
        assert notified[-1] == [renamed_base, renamed_base + "?view=deep"]
    finally:
        app.dependency_overrides.pop(get_admin_user, None)
