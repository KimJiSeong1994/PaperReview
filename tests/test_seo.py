"""Tests for the server-side SEO/GEO rendering endpoints (routers/seo.py).

Hermetic: posts are injected by patching ``routers.seo._load_posts``; no
network access and no real data files are read or written.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

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


def test_llms_txt_has_geo_sections(client: TestClient) -> None:
    """llms.txt exposes entity/capabilities/optional sections and dated posts."""
    body = client.get("/llms.txt").text
    for section in ("## About", "## Capabilities", "## Key pages", "## Blog", "## Optional"):
        assert section in body, f"missing {section}"
    # Entity grounding + machine-readable resources for AI engines.
    assert "github.com/KimJiSeong1994/PaperReview" in body
    assert "/feed.xml" in body and "/sitemap.xml" in body
    # Published posts carry an ISO date (from created_at 2026-01-15).
    assert "(2026-01-15)" in body


def test_blog_ssr_organization_is_grounded(client: TestClient) -> None:
    """The Organization JSON-LD on an SSR blog page carries sameAs + disambiguation."""
    html = client.get(f"/blog/{PUBLISHED_SLUG}").text
    assert "github.com/KimJiSeong1994/PaperReview" in html
    assert "disambiguatingDescription" in html


def test_spa_shell_defaults_to_dark_before_paint() -> None:
    """The Vite SPA shell mirrors SSR: no saved preference falls back to dark."""
    html = Path("web-ui/index.html").read_text(encoding="utf-8")
    assert "localStorage.getItem('theme')" in html
    assert "t = 'dark'" in html
    assert "setAttribute('data-theme', 'dark')" in html


def test_ssr_sets_theme_before_paint(client: TestClient) -> None:
    """SSR blog pages set data-theme early (default dark) so it isn't lost pre-hydration."""
    for path in ("/blog", f"/blog/{PUBLISHED_SLUG}", "/blog/category/engineering"):
        html = client.get(path).text
        assert "data-theme" in html, f"missing theme script on {path}"
        assert "'dark'" in html, f"missing default-dark theme on {path}"


def test_ssr_post_has_single_h1(client: TestClient) -> None:
    """The duplicate leading content H1 is stripped so only the title H1 remains."""
    html = client.get(f"/blog/{PUBLISHED_SLUG}").text
    # Exactly one <h1 — the title. The content's leading "# Heading" is dropped.
    assert html.count("<h1") == 1
    assert 'class="blog-detail-title"' in html
    assert ">Heading</h1>" not in html


def test_ssr_post_has_related_and_prevnext_links(client: TestClient) -> None:
    """A post links to related posts and to its chronological neighbour."""
    html = client.get(f"/blog/{PUBLISHED_SLUG}").text
    assert "blog-related" in html
    assert "blog-prevnext" in html
    # The other published post is reachable from this one (not star-shaped).
    assert f"/blog/{KOREAN_SLUG}" in html


def test_blog_index_grouped_by_category(client: TestClient) -> None:
    """The SSR index groups posts under a category heading linking to the hub."""
    html = client.get("/blog").text
    assert "/blog/category/engineering" in html
    assert ">Engineering</a>" in html


def test_category_hub_renders_and_self_canonicalizes(client: TestClient) -> None:
    resp = client.get("/blog/category/engineering")
    assert resp.status_code == 200
    html = resp.text
    assert '<link rel="canonical" href="https://jiphyeonjeon.kr/blog/category/engineering">' in html
    assert "CollectionPage" in html
    assert f"/blog/{PUBLISHED_SLUG}" in html  # engineering posts listed
    assert "noindex" not in html


def test_empty_category_hub_is_noindex(client: TestClient) -> None:
    """paper-review has no posts in the fixtures, so its hub is served noindex."""
    resp = client.get("/blog/category/paper-review")
    assert resp.status_code == 200
    assert "noindex" in resp.text


def test_unknown_category_returns_404(client: TestClient) -> None:
    resp = client.get("/blog/category/totally-unknown")
    assert resp.status_code == 404
    assert "noindex" in resp.text


def test_sitemap_lists_nonempty_category_hub_only(client: TestClient) -> None:
    body = client.get("/sitemap.xml").text
    assert f"{'https://jiphyeonjeon.kr'}/blog/category/engineering" in body
    # No published paper-review posts in the fixtures -> hub omitted from sitemap.
    assert "/blog/category/paper-review" not in body


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
