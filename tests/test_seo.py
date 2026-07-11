"""Tests for the server-side SEO/GEO rendering endpoints (routers/seo.py).

Hermetic: posts are injected by patching ``routers.seo._load_posts``; no
network access and no real data files are read or written.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api_server import app
from routers.seo import _normalize_latex_delimiters

PUBLISHED_SLUG = "hello-world-abc12345"
UNPUBLISHED_SLUG = "draft-post-def67890"
KOREAN_SLUG = "korean-post-aaaa1111"

_FIXED_POSTS = [
    {
        "id": "abc12345aaaa",
        "title": "Hello World Research Note",
        "slug": PUBLISHED_SLUG,
        "excerpt": "An introductory writeup about paper review.",
        "content": "# Heading\n\nThis is the **rendered** body text of the post with math \\(\\tilde A\\) and display:\n\n\\[\\mathcal{L}=x\\]\n\n$$\\mathcal{Q}=y_0+\\lambda\\mathcal{R}_{reg},\\quad\n\\mathcal{R}_{reg}=\\sum_{i,j}A_{ij}\\|f(X_i)-f(X_j)\\|^2$$",
        "author": "test-admin",
        "tags": ["rag", "llm"],
        "thumbnail_url": "/api/blog/figures/hello-world.png",
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


def test_post_image_metadata_uses_absolute_urls(client: TestClient) -> None:
    """Crawler-facing image metadata should not expose root-relative /api paths."""
    body = client.get(f"/blog/{PUBLISHED_SLUG}").text

    assert 'property="og:image" content="https://jiphyeonjeon.kr/api/blog/figures/hello-world.png"' in body
    assert 'name="twitter:image" content="https://jiphyeonjeon.kr/api/blog/figures/hello-world.png"' in body
    assert '"image": "https://jiphyeonjeon.kr/api/blog/figures/hello-world.png"' in body
    assert 'content="/api/blog/figures/hello-world.png"' not in body


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
    assert "/llms-full.txt" in body


def test_llms_full_txt_contains_all_published_post_bodies(client: TestClient) -> None:
    resp = client.get("/llms-full.txt")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text

    assert f"Canonical: https://jiphyeonjeon.kr/blog/{PUBLISHED_SLUG}" in body
    assert f"Canonical: https://jiphyeonjeon.kr/blog/{KOREAN_SLUG}" in body
    assert "rendered** body text" in body
    assert "본문 내용은 한국어로 렌더링됩니다." in body
    assert "$\\tilde A$" in body
    assert "$$\n\\mathcal{L}=x\n$$" in body

    assert UNPUBLISHED_SLUG not in body
    assert "Draft content that bots must not see." not in body


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
    assert "linkedin.com/in/jiseong-kim-868218193" in html
    assert "disambiguatingDescription" in html


def test_ssr_pages_render_site_footer_with_profile_links(client: TestClient) -> None:
    """Every SSR page carries the maintainer-profile footer for credibility."""
    for path in ("/blog", f"/blog/{PUBLISHED_SLUG}", "/blog/category/engineering"):
        html = client.get(path).text
        assert '<footer class="site-footer">' in html, path
        assert 'href="https://github.com/KimJiSeong1994"' in html, path
        assert 'href="https://www.linkedin.com/in/jiseong-kim-868218193/"' in html, path


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


def test_latex_note_delimiters_are_normalized_before_markdown() -> None:
    r"""PaperWiki-style \( ... \) and \[ ... \] delimiters do not get markdown-escaped."""
    text = "Inline \\(\\tilde A\\) and block:\n\\[\n\\mathcal{L}=x\n\\]"

    normalized = _normalize_latex_delimiters(text)

    assert "$\\tilde A$" in normalized
    assert "$$\\mathcal{L}=x$$" in normalized
    assert "\\(" not in normalized
    assert "\\[" not in normalized


def test_ssr_post_keeps_latex_backslashes_after_normalization(client: TestClient) -> None:
    r"""SSR should render math fallback instead of exposing raw or escaped delimiters."""
    html = client.get(f"/blog/{PUBLISHED_SLUG}").text

    assert "blog-math-inline" in html
    assert "blog-math-display" in html
    assert "\\tilde A" in html
    assert "$\\tilde A$" not in html
    assert "(\\tilde A)" not in html
    assert "$$\\mathcal{L}=x$$" not in html


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


def test_blog_index_renders_every_nonempty_category(monkeypatch) -> None:
    """The /blog index links every category hub and its posts, not just one.

    Non-JS crawlers discover posts by following anchors from /blog, so the
    paper-review section must not be orphaned behind client-side navigation.
    """
    review_post = {
        "id": "ffff2222dddd",
        "title": "DeepWalk Review",
        "slug": "deepwalk-review-ffff2222",
        "excerpt": "A deep review of DeepWalk.",
        "content": "Review body.",
        "author": "test-admin",
        "tags": ["PaperReview"],
        "thumbnail_url": None,
        "created_at": "2026-04-01T09:00:00",
        "updated_at": None,
        "published": True,
        "reading_time_min": 1,
        "category": "paper-review",
    }
    monkeypatch.setattr("routers.seo._load_posts", lambda: [*_FIXED_POSTS, review_post])
    monkeypatch.setattr("routers.seo._load_deleted", lambda: set())
    html = TestClient(app).get("/blog").text
    assert "/blog/category/paper-review" in html
    assert ">Paper Reviews</a>" in html
    assert f'/blog/{review_post["slug"]}' in html
    assert "/blog/category/engineering" in html
    assert ">Engineering</a>" in html
    assert f"/blog/{PUBLISHED_SLUG}" in html


def test_paper_review_post_links_reviewed_paper_in_json_ld(monkeypatch) -> None:
    """A review citing '**Paper:** …' emits ScholarlyArticle + about/citation."""
    review_post = {
        "id": "eeee3333aaaa",
        "title": "DeepWalk Review",
        "slug": "deepwalk-review-eeee3333",
        "excerpt": "A deep review of DeepWalk.",
        "content": (
            "# DeepWalk Review\n\n"
            '**Paper:** Perozzi, Bryan; Al-Rfou, Rami; Skiena, Steven. (2014). '
            '"DeepWalk: Online Learning of Social Representations." '
            "*KDD 2014*, arXiv:1403.6652. https://doi.org/10.1145/2623330.2623732\n\n"
            "## Review\n\nBody text."
        ),
        "author": "test-admin",
        "tags": ["PaperReview"],
        "thumbnail_url": None,
        "created_at": "2026-04-01T09:00:00",
        "updated_at": None,
        "published": True,
        "reading_time_min": 1,
        "category": "paper-review",
    }
    monkeypatch.setattr("routers.seo._load_posts", lambda: [*_FIXED_POSTS, review_post])
    monkeypatch.setattr("routers.seo._load_deleted", lambda: set())
    html = TestClient(app).get(f"/blog/{review_post['slug']}").text

    arxiv_url = "https://arxiv.org/abs/1403.6652"
    assert '"@type": "ScholarlyArticle"' in html
    assert f'"@id": "{arxiv_url}"' in html
    assert '"name": "DeepWalk: Online Learning of Social Representations"' in html
    assert f'"about": {{"@id": "{arxiv_url}"}}' in html
    assert f'"citation": {{"@id": "{arxiv_url}"}}' in html
    assert '"propertyID": "arXiv", "value": "1403.6652"' in html
    assert '"propertyID": "DOI", "value": "10.1145/2623330.2623732"' in html
    assert '"name": "Perozzi, Bryan"' in html


def test_non_review_post_has_no_scholarly_article(client: TestClient) -> None:
    """Posts without a paper citation keep their JSON-LD unchanged."""
    html = client.get(f"/blog/{PUBLISHED_SLUG}").text
    assert "ScholarlyArticle" not in html
    assert '"citation"' not in html


def test_blog_index_omits_empty_category(client: TestClient) -> None:
    """A category with no published posts renders no section on /blog."""
    html = client.get("/blog").text
    assert "/blog/category/paper-review" not in html


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
    assert "https://jiphyeonjeon.kr/llms-full.txt" in body
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
