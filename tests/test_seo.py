"""Tests for the server-side SEO/GEO rendering endpoints (routers/seo.py).

Hermetic: posts are injected by patching ``routers.seo._load_posts``; no
network access and no real data files are read or written.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api_server import app
from routers.seo import (
    _blog_posting_graph,
    _blog_seo_meta,
    _normalize_blog_markdown,
    _normalize_latex_delimiters,
)

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


def test_blog_seo_meta_enriches_paper_reviews_with_arxiv() -> None:
    title, desc = _blog_seo_meta(
        {
            "category": "paper-review",
            "title": "DeepWalk: Online Learning of Social Representations",
            "excerpt": "랜덤워크 임베딩 리뷰.",
            "content": '**Paper:** Perozzi et al. "DeepWalk: Online Learning of Social '
            'Representations" (KDD 2014). arXiv:1403.6652\n\n**Abstract:** ...',
        }
    )
    assert title == (
        "DeepWalk: Online Learning of Social Representations — arXiv:1403.6652 논문 리뷰 · 집현전"
    )
    assert desc == "arXiv:1403.6652 · 랜덤워크 임베딩 리뷰."


def test_blog_post_renders_excerpt_as_lead(client: TestClient) -> None:
    """The excerpt is surfaced as a visible lead paragraph under the title
    (on-page Korean/summary text for search), not only in the meta tag."""
    body = client.get(f"/blog/{PUBLISHED_SLUG}").text
    assert (
        '<p class="blog-detail-lead">An introductory writeup about paper review.</p>'
        in body
    )


def test_blog_post_renders_korean_dek_from_leading_h1(client: TestClient) -> None:
    """The stripped leading markdown H1 is surfaced as an <h2> dek (a Korean
    heading), not discarded — while the body keeps a single title <h1>."""
    body = client.get(f"/blog/{PUBLISHED_SLUG}").text
    assert '<h2 class="blog-detail-dek">Heading</h2>' in body
    # Still exactly one title H1.
    assert body.count('class="blog-detail-title"') == 1


def test_faq_section_emits_faqpage_jsonld() -> None:
    post = {
        "title": "GIN Review",
        "slug": "gin-review",
        "excerpt": "요약",
        "author": "test",
        "content": (
            "본문.\n\n## 자주 묻는 질문\n\n"
            "### GIN 논문이란?\nGIN은 그래프 신경망의 표현력을 다룬 논문입니다.\n\n"
            "### GIN의 핵심 기여는?\nWL 테스트만큼 강력한 GNN을 증명했습니다.\n"
        ),
        "tags": [],
    }
    graph = _blog_posting_graph(post)["@graph"]
    faq = next((n for n in graph if n.get("@type") == "FAQPage"), None)
    assert faq is not None
    questions = [q["name"] for q in faq["mainEntity"]]
    assert questions == ["GIN 논문이란?", "GIN의 핵심 기여는?"]
    assert faq["mainEntity"][0]["acceptedAnswer"]["text"].startswith("GIN은 그래프 신경망")


def test_no_faq_section_emits_no_faqpage() -> None:
    post = {"title": "T", "slug": "s", "excerpt": "e", "author": "a", "content": "# T\n\n본문만.", "tags": []}
    graph = _blog_posting_graph(post)["@graph"]
    assert not any(n.get("@type") == "FAQPage" for n in graph)


def test_blog_seo_meta_leaves_non_paper_posts_unchanged() -> None:
    title, desc = _blog_seo_meta(
        {"title": "Hello World Research Note", "excerpt": "An intro.", "content": "# Heading\n\nbody"}
    )
    assert title == "Hello World Research Note | Jiphyeonjeon Blog"
    assert desc == "An intro."


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
    assert "<loc>https://jiphyeonjeon.kr/introduce/</loc>" in resp.text
    assert "<loc>https://jiphyeonjeon.kr/ko/introduce/</loc>" in resp.text
    # Tag hub must be announced, or the indexable page stays undiscovered.
    assert "<loc>https://jiphyeonjeon.kr/blog/tags</loc>" in resp.text
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
    # Korean content -> ko feed language (was mislabeled en); + self atom link.
    assert "<language>ko</language>" in resp.text
    assert 'rel="self"' in resp.text and "/feed.xml" in resp.text
    assert "<lastBuildDate>" in resp.text


def test_sitemap_has_image_namespace_and_thumbnail(client: TestClient) -> None:
    body = client.get("/sitemap.xml").text
    assert "http://www.google.com/schemas/sitemap-image/1.1" in body
    # The published fixture post has a thumbnail_url -> surfaced as an image loc.
    assert "<image:image>" in body
    assert "https://jiphyeonjeon.kr/api/blog/figures/hello-world.png" in body


def test_blog_post_author_is_grounded_person(client: TestClient) -> None:
    body = client.get(f"/blog/{PUBLISHED_SLUG}").text
    assert "https://github.com/KimJiSeong1994" in body
    assert "https://www.linkedin.com/in/jiseong-kim-868218193/" in body
    assert 'property="article:published_time"' in body
    assert 'property="og:image:alt"' in body


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


def test_llms_full_txt_keeps_post_boundaries_unambiguous(monkeypatch) -> None:
    """Post titles are the only ``#`` headings and ``---`` the only separator.

    A naive chunker must be able to split the corpus at post boundaries so
    every retrieved chunk stays attributable to its canonical URL.
    """
    tricky = {
        "id": "tricky1234",
        "title": "Tricky Markdown Post",
        "slug": "tricky-markdown-post",
        "excerpt": "Post with body headings and rules.",
        "content": (
            "# Duplicate H1\n\n## Section A\n\ntext\n\n---\n\n"
            "### Sub B\n\n```python\n# code comment, not a heading\n---\n```\n"
        ),
        "author": "test-admin",
        "tags": [],
        "thumbnail_url": None,
        "created_at": "2026-04-02T09:00:00",
        "updated_at": None,
        "published": True,
        "reading_time_min": 1,
    }
    monkeypatch.setattr("routers.seo._load_posts", lambda: [*_FIXED_POSTS, tricky])
    monkeypatch.setattr("routers.seo._load_deleted", lambda: set())
    body = TestClient(app).get("/llms-full.txt").text

    published_count = 3  # two published fixtures + tricky

    def _outside_fences(text: str) -> list[str]:
        lines, fenced = [], False
        for line in text.split("\n"):
            if line.lstrip().startswith(("```", "~~~")):
                fenced = not fenced
                continue
            if not fenced:
                lines.append(line)
        return lines

    visible = _outside_fences(body)
    hash_headings = [line for line in visible if line.startswith("# ")]
    # Corpus header + one per post; body headings were all demoted.
    assert len(hash_headings) == published_count + 1
    separators = [line for line in visible if line.strip() == "---"]
    assert len(separators) == published_count
    # Body headings demoted one level; thematic break rewritten.
    assert "### Section A" in body
    assert "#### Sub B" in body
    assert "\n***\n" in body
    # Fenced code content untouched.
    assert "# code comment, not a heading" in body


def test_llms_txt_has_geo_sections(client: TestClient) -> None:
    """llms.txt exposes entity/capabilities/optional sections and dated posts."""
    body = client.get("/llms.txt").text
    for section in (
        "## About",
        "## Capabilities",
        "## Review methodology",
        "## Claude access",
        "## Key pages",
        "## Blog",
        "## Optional",
    ):
        assert section in body, f"missing {section}"
    # Entity grounding + machine-readable resources for AI engines.
    assert "github.com/KimJiSeong1994/PaperReview" in body
    assert "/feed.xml" in body and "/sitemap.xml" in body
    assert "[About Jiphyeonjeon — English](https://jiphyeonjeon.kr/introduce/)" in body
    assert "[집현전 소개 — 한국어](https://jiphyeonjeon.kr/ko/introduce/)" in body
    assert "[한국어](https://jiphyeonjeon.kr/ko/introduce/)" in body
    assert "[Claude extension overview](https://jiphyeonjeon.kr/introduce/#claude)" in body
    assert "github.com/KimJiSeong1994/jiphyeonjeon-agent" in body
    assert "quotation, paraphrase, inference, and unverified claims" in body
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


def test_spa_shell_follows_saved_choice_then_os_then_dark() -> None:
    """A saved choice wins; with none, follow the OS; if that fails, dark."""
    html = Path("web-ui/index.html").read_text(encoding="utf-8")
    assert "localStorage.getItem('theme')" in html
    assert "prefers-color-scheme: light" in html
    assert "t = 'dark'" in html, "dark must remain the fallback when matchMedia is unavailable"
    # The saved value has to be consulted before the media query, or an explicit
    # choice would be overridden by the OS on every load.
    assert html.index("localStorage.getItem('theme')") < html.index("prefers-color-scheme")


def test_ssr_and_spa_theme_scripts_agree() -> None:
    """The two pre-paint theme scripts are a documented mirror pair.

    routers/seo.py ships its own copy for SSR pages. If they drift, a reader
    moving between a blog page and the SPA sees the theme change under them —
    which is exactly what happened while only one of them read the OS
    preference. Compare behaviour, not bytes: one is minified.
    """
    spa = Path("web-ui/index.html").read_text(encoding="utf-8")
    ssr = Path("routers/seo.py").read_text(encoding="utf-8")
    ssr_script = ssr[ssr.index("theme_script = ("):]
    ssr_script = ssr_script[: ssr_script.index("\n    )")]

    for needle in ("localStorage.getItem('theme')", "prefers-color-scheme: light", "'dark'"):
        assert needle in spa, f"SPA shell lost {needle}"
        assert needle in ssr_script, f"SSR theme script lost {needle}"

    for source, name in ((spa, "SPA shell"), (ssr_script, "SSR theme script")):
        assert source.index("localStorage.getItem('theme')") < source.index(
            "prefers-color-scheme"
        ), f"{name} consults the OS before the saved choice"


def test_spa_shell_has_korean_search_metadata_and_feed_discovery() -> None:
    """Non-JS search crawlers receive metadata matching the Korean-first home page."""
    html = Path("web-ui/index.html").read_text(encoding="utf-8")
    assert '<html lang="ko">' in html
    assert "<title>AI 논문 검색·리뷰 도구 | 집현전</title>" in html
    assert 'name="description"' in html and "원문 근거" in html
    assert 'name="robots" content="index, follow, max-image-preview:large' in html
    assert 'property="og:locale" content="ko_KR"' in html
    assert 'rel="alternate" type="application/rss+xml" href="/feed.xml"' in html
    assert '"@type": "WebSite"' in html and '"alternateName": "집현전"' in html


def test_ssr_sets_theme_before_paint(client: TestClient) -> None:
    """SSR blog pages set data-theme early so it isn't lost pre-hydration."""
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


def test_indented_display_math_fences_are_aligned_at_column_zero() -> None:
    r"""PaperWiki list indentation must not shift only one display-math fence."""
    text = "- formula:\n  \\[\n  \\mathcal{U}(s)=x\n  \\]\n  explanation\n\n\\[y=z\\]"

    normalized = _normalize_blog_markdown(text)

    assert "\n  $$" not in normalized
    assert normalized.count("\n$$\n") == 3
    assert "$$\n\\mathcal{U}(s)=x\n$$" in normalized
    assert "$$\ny=z\n$$" in normalized
    assert "explanation" in normalized


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


def test_paper_review_hub_uses_append_order_for_same_time_publications(monkeypatch) -> None:
    """Paper Reviews shows the later-published item first when dates tie."""
    shared = {
        "excerpt": "Review excerpt.",
        "content": "Review body.",
        "author": "test-admin",
        "tags": ["PaperReview"],
        "thumbnail_url": None,
        "created_at": "2026-08-08T00:00:00+09:00",
        "updated_at": None,
        "published": True,
        "reading_time_min": 1,
        "category": "paper-review",
    }
    first = {**shared, "id": "first", "title": "First review", "slug": "first-review"}
    second = {**shared, "id": "second", "title": "Second review", "slug": "second-review"}
    monkeypatch.setattr("routers.seo._load_posts", lambda: [first, second])

    html = TestClient(app).get("/blog/category/paper-review").text

    assert html.index("Second review") < html.index("First review")


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


def _series_fixture_posts() -> list[dict]:
    """Two published members of the gnn series plus the base fixtures."""
    from routers.seo import BLOG_SERIES

    slugs = BLOG_SERIES["gnn"]["slugs"]
    members = [
        {
            "id": f"series{i}",
            "title": f"Series Post {i}",
            "slug": slug,
            "excerpt": f"Excerpt {i}.",
            "content": "Body text.",
            "author": "test-admin",
            "tags": ["PaperReview"],
            "thumbnail_url": None,
            "created_at": f"2026-05-0{i + 1}T09:00:00",
            "updated_at": None,
            "published": True,
            "reading_time_min": 1,
            "category": "paper-review",
        }
        for i, slug in enumerate(slugs[:2])
    ]
    return [*_FIXED_POSTS, *members]


def test_dwe_series_ends_with_systematic_contextualized_embedding_comparison() -> None:
    from routers.seo import BLOG_SERIES

    slug = "a-systematic-comparison-contextualized-word-embeddings-lexical-semantic-change"
    assert len(BLOG_SERIES["dwe"]["slugs"]) == 12
    assert BLOG_SERIES["dwe"]["slugs"][-1] == slug
    assert "핵심 논문 12편" in BLOG_SERIES["dwe"]["description"]


def test_graphrag_series_follows_foundational_publication_order() -> None:
    from routers.seo import BLOG_SERIES

    slugs = BLOG_SERIES["graphrag"]["slugs"]
    assert slugs == [
        "knowledge-graph-prompting-multi-document-qa",
        "ms-graphrag-global-query-focused-summarization",
        "hipporag-neurobiologically-inspired-long-term-memory",
        "lightrag-dual-level-graph-rag",
        "hipporag2-from-rag-to-memory",
        "causalrag-causal-graph-retrieval",
        "leanrag-semantic-aggregation-hierarchical-retrieval",
        "linearrag-linear-graph-retrieval-augmented-generation",
        "deep-graphrag",
        "causalrag2-hugrag-hierarchical-causal-gating",
        "ragu",
    ]
    assert "핵심 논문 11편" in BLOG_SERIES["graphrag"]["description"]
    assert "기초 연구부터 최초 공개 순서" in BLOG_SERIES["graphrag"]["description"]


def test_graph_causality_series_follows_foundational_order() -> None:
    from routers.seo import BLOG_SERIES

    series = BLOG_SERIES["graph-causality"]
    assert series["title"] == "Graph causality 논문 리뷰 시리즈"
    assert series["slugs"] == [
        "pcm-partial-cross-mapping-eliminates-indirect-causal-influences",
        "cic-dynamical-causality-under-invisible-confounders",
        "ic2-interventional-dynamical-causality-under-latent-confounders",
    ]
    assert "핵심 논문 3편" in series["description"]
    assert "공개·기초 흐름 순서" in series["description"]


def test_removed_urban_spatial_sociology_series_has_no_membership() -> None:
    from routers.seo import BLOG_SERIES, _series_membership

    assert "urban-spatial-sociology" not in BLOG_SERIES
    assert _series_membership(
        "transferable-human-mobility-network-reconstruction-with-neurogravity"
    ) is None
    assert _series_membership(
        "theory-informed-interpretable-graph-learning-urban-commuting-flows"
    ) is None
    assert TestClient(app).get("/blog/series/urban-spatial-sociology").status_code == 404


def test_series_hub_renders_ordered_list_and_item_list_schema(monkeypatch) -> None:
    monkeypatch.setattr("routers.seo._load_posts", _series_fixture_posts)
    monkeypatch.setattr("routers.seo._load_deleted", lambda: set())
    resp = TestClient(app).get("/blog/series/gnn")
    assert resp.status_code == 200
    html = resp.text
    assert '<link rel="canonical" href="https://jiphyeonjeon.kr/blog/series/gnn">' in html
    assert "GNN 논문 리뷰 시리즈" in html
    assert '"@type": "CollectionPage"' in html
    assert '"@type": "ItemList"' in html
    assert '"numberOfItems": 2' in html
    # Ordered: position 1 is the first series slug.
    assert html.index("Series Post 0") < html.index("Series Post 1")
    assert "noindex" not in html


def test_series_member_post_has_banner_and_is_part_of(monkeypatch) -> None:
    from routers.seo import BLOG_SERIES

    monkeypatch.setattr("routers.seo._load_posts", _series_fixture_posts)
    monkeypatch.setattr("routers.seo._load_deleted", lambda: set())
    first, second = BLOG_SERIES["gnn"]["slugs"][:2]
    html = TestClient(app).get(f"/blog/{first}").text
    assert '<nav class="blog-series"' in html
    assert 'href="/blog/series/gnn"' in html
    # Only 2 of the series slugs are published -> next link targets the 2nd,
    # and position is computed over published members only (1/2편).
    assert "1/2편" in html
    assert f'href="/blog/{second}">시리즈 다음 글' in html
    assert '"isPartOf": {"@id": "https://jiphyeonjeon.kr/blog/series/gnn#collection"}' in html


def test_empty_series_hub_is_noindex(client: TestClient) -> None:
    """Base fixtures publish no series members -> hub served noindex."""
    resp = client.get("/blog/series/gnn")
    assert resp.status_code == 200
    assert '<meta name="robots" content="noindex,nofollow">' in resp.text


def test_unknown_series_returns_404(client: TestClient) -> None:
    resp = client.get("/blog/series/zzz-unknown")
    assert resp.status_code == 404


def test_sitemap_lists_nonempty_series_hub_only(monkeypatch, client: TestClient) -> None:
    # Base fixtures: no members published -> series hub omitted.
    assert "/blog/series/gnn" not in client.get("/sitemap.xml").text
    monkeypatch.setattr("routers.seo._load_posts", _series_fixture_posts)
    monkeypatch.setattr("routers.seo._load_deleted", lambda: set())
    assert "/blog/series/gnn" in TestClient(app).get("/sitemap.xml").text


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
    # llms.txt is discovered at its well-known root path, not via the sitemap,
    # and is not an indexable page — listing it only spent crawl budget.
    assert "https://jiphyeonjeon.kr/llms.txt" not in body
    assert "https://jiphyeonjeon.kr/llms-full.txt" not in body
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

def test_tags_hub_is_ssr_200_and_indexable(client: TestClient) -> None:
    """/blog/tags must not fall through to the /blog/{slug} handler (prod 404)."""
    resp = client.get("/blog/tags")
    assert resp.status_code == 200
    html = resp.text
    assert '<link rel="canonical" href="https://jiphyeonjeon.kr/blog/tags">' in html
    assert "noindex" not in html
    # Published tags are linked to the filtered list; unpublished ones are not.
    assert 'href="/blog?tag=rag"' in html
    assert 'href="/blog?tag=리뷰"' in html
    assert "draft" not in html


def test_tags_hub_merges_case_variants(monkeypatch) -> None:
    posts = [
        {"slug": "a", "title": "A", "excerpt": "", "content": "", "tags": ["GraphRAG"],
         "published": True, "created_at": "2026-01-01T00:00:00+00:00"},
        {"slug": "b", "title": "B", "excerpt": "", "content": "", "tags": ["graphrag"],
         "published": True, "created_at": "2026-01-02T00:00:00+00:00"},
    ]
    monkeypatch.setattr("routers.seo._load_posts", lambda: posts)
    monkeypatch.setattr("routers.seo._load_deleted", lambda: set())
    html = TestClient(app).get("/blog/tags").text
    assert html.count("?tag=") == 1, "case variants must collapse to one link"


def test_tags_hub_head_request(client: TestClient) -> None:
    assert client.head("/blog/tags").status_code == 200
