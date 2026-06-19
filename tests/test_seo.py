"""Tests for the server-side SEO/GEO rendering endpoints (routers/seo.py).

Hermetic: posts are injected by patching ``routers.seo._load_posts``; no
network access and no real data files are read or written.
"""

import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from api_server import app

PUBLISHED_SLUG = "hello-world-abc12345"
UNPUBLISHED_SLUG = "draft-post-def67890"
KOREAN_SLUG = "korean-post-aaaa1111"

_FIXED_POSTS = [
    {
        "id": "abc12345aaaa",
        "title": "Hello World Research Note",
        "slug": PUBLISHED_SLUG,
        "excerpt": "An introductory writeup about paper review.",
        "content": "# Heading\n\nThis is the **rendered** body text of the post.",
        "author": "test-admin",
        "tags": ["rag", "llm"],
        "thumbnail_url": None,
        "created_at": "2026-01-15T10:00:00",
        "updated_at": None,
        "published": True,
        "reading_time_min": 2,
    },
    {
        "id": "def67890bbbb",
        "title": "Secret Draft",
        "slug": UNPUBLISHED_SLUG,
        "excerpt": "Should never be served.",
        "content": "Draft content that bots must not see.",
        "author": "test-admin",
        "tags": ["draft"],
        "thumbnail_url": None,
        "created_at": "2026-02-01T12:00:00",
        "updated_at": None,
        "published": False,
        "reading_time_min": 1,
    },
    {
        "id": "aaaa1111cccc",
        "title": "한국어 논문 리뷰 노트",
        "slug": KOREAN_SLUG,
        "excerpt": "한국어로 작성된 리뷰 요약입니다.",
        "content": "# 제목\n\n본문 내용은 한국어로 렌더링됩니다.",
        "author": "test-admin",
        "tags": ["리뷰"],
        "thumbnail_url": None,
        "created_at": "2026-03-01T09:00:00",
        "updated_at": None,
        "published": True,
        "reading_time_min": 1,
    },
]


@pytest.fixture
def client(monkeypatch) -> TestClient:
    """TestClient with ``_load_posts`` patched to a fixed in-memory list."""
    monkeypatch.setattr("routers.seo._load_posts", lambda: list(_FIXED_POSTS))
    monkeypatch.setattr("routers.seo._load_deleted", lambda: set())
    return TestClient(app)


def test_published_post_renders_full_html(client: TestClient) -> None:
    resp = client.get(f"/blog/{PUBLISHED_SLUG}")
    assert resp.status_code == 200
    body = resp.text
    assert "<title>" in body
    assert "Hello World Research Note" in body
    assert "rendered" in body  # markdown-rendered content text
    assert '"@type": "BlogPosting"' in body or '"@type":"BlogPosting"' in body
    assert "application/ld+json" in body


def test_unpublished_post_is_404_noindex(client: TestClient) -> None:
    resp = client.get(f"/blog/{UNPUBLISHED_SLUG}")
    assert resp.status_code == 404
    assert "noindex" in resp.text
    # Draft content must not leak into the 404 page.
    assert "Draft content that bots must not see." not in resp.text


def test_missing_post_is_404_noindex(client: TestClient) -> None:
    resp = client.get("/blog/this-slug-does-not-exist-99999")
    assert resp.status_code == 404
    assert "noindex" in resp.text


def test_blog_index_lists_published_only(client: TestClient) -> None:
    resp = client.get("/blog")
    assert resp.status_code == 200
    body = resp.text
    assert f'href="/blog/{PUBLISHED_SLUG}"' in body
    assert UNPUBLISHED_SLUG not in body


def test_sitemap_valid_xml_published_only(client: TestClient) -> None:
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    # Parses as valid XML.
    root = ET.fromstring(resp.text)
    assert root.tag.endswith("urlset")
    assert PUBLISHED_SLUG in resp.text
    assert UNPUBLISHED_SLUG not in resp.text


def test_feed_valid_rss_with_published_link(client: TestClient) -> None:
    resp = client.get("/feed.xml")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/rss+xml")
    root = ET.fromstring(resp.text)
    assert root.tag == "rss"
    assert f"/blog/{PUBLISHED_SLUG}" in resp.text
    assert UNPUBLISHED_SLUG not in resp.text


def test_korean_post_uses_ko_locale(client: TestClient) -> None:
    resp = client.get(f"/blog/{KOREAN_SLUG}")
    assert resp.status_code == 200
    body = resp.text
    assert '"inLanguage": "ko"' in body or '"inLanguage":"ko"' in body
    assert 'content="ko_KR"' in body
    assert '<html lang="ko"' in body


def test_english_post_uses_en_locale(client: TestClient) -> None:
    resp = client.get(f"/blog/{PUBLISHED_SLUG}")
    assert resp.status_code == 200
    body = resp.text
    assert '"inLanguage": "en"' in body or '"inLanguage":"en"' in body
    assert 'content="en_US"' in body
    assert '<html lang="en"' in body


def test_llms_txt_lists_published_posts(client: TestClient) -> None:
    resp = client.get("/llms.txt")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert "# 집현전" in body
    assert PUBLISHED_SLUG in body
    assert UNPUBLISHED_SLUG not in body


def test_deleted_slug_returns_410_noindex(client: TestClient, monkeypatch) -> None:
    deleted_slug = "deleted-post-zzzz9999"
    monkeypatch.setattr("routers.seo._load_deleted", lambda: {deleted_slug})
    resp = client.get(f"/blog/{deleted_slug}")
    assert resp.status_code == 410
    assert "noindex" in resp.text


def test_unknown_slug_still_returns_404(client: TestClient) -> None:
    resp = client.get("/blog/totally-unknown-slug-00000")
    assert resp.status_code == 404
    assert "noindex" in resp.text
