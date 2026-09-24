"""Public SSR data must survive React mounting without exposing private fields."""

import json
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from api_server import app
from routers import seo


class BootstrapParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root_depth = 0
        self.in_bootstrap = False
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div" and (self.root_depth or attrs.get("id") == "root"):
            self.root_depth += 1
        if tag == "script" and attrs.get("id") == "blog-bootstrap":
            assert self.root_depth == 0, "Bootstrap would be destroyed by createRoot"
            assert attrs.get("type") == "application/json"
            self.in_bootstrap = True
            self.blocks.append("")

    def handle_endtag(self, tag):
        if tag == "div" and self.root_depth:
            self.root_depth -= 1
        if tag == "script":
            self.in_bootstrap = False

    def handle_data(self, text):
        if self.in_bootstrap:
            self.blocks[-1] += text


@pytest.fixture
def article(monkeypatch):
    post = dict(
        id="bootstrap-id",
        slug="bootstrap-paper",
        title="한국어 paper",
        excerpt="Public excerpt",
        content="## Easy\n\nEASY-BODY",
        deep_content="## Deep\n\nDEEP-BODY " + "analysis " * 500,
        author="Reviewer",
        tags=["paper-review"],
        category="paper-review",
        thumbnail_url="/api/blog/figures/example.png",
        published=True,
        created_at="2026-09-24T00:00:00+00:00",
        updated_at=None,
        reading_time_min=1,
        index_deep_view=True,
        private_editor_note="DO-NOT-EXPOSE",
        workflow_token="SECRET-INTERNAL",
    )
    draft = dict(post, slug="draft", published=False, content="PRIVATE-DRAFT")
    monkeypatch.setattr(seo, "_load_posts", lambda: [post, draft])
    monkeypatch.setattr(seo, "_load_deleted", lambda: {"deleted"})
    monkeypatch.setattr(
        seo,
        "_get_assets",
        lambda: ("", '<script type="module" src="/assets/app.js"></script>'),
    )
    return post


@pytest.mark.parametrize("suffix", ["", "?view=deep"])
def test_public_bootstrap_is_outside_root_before_modules_with_both_views(
    article, suffix
):
    response = TestClient(app).get("/blog/bootstrap-paper" + suffix)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.text.count('id="seo-json-ld"') == 1
    parser = BootstrapParser()
    parser.feed(response.text)
    assert len(parser.blocks) == 1
    bootstrap = json.loads(parser.blocks[0])
    assert bootstrap["version"] == 1
    assert bootstrap["route"] == {"slug": article["slug"]}
    post = bootstrap["post"]
    assert post["slug"] == article["slug"]
    assert post["content"] == article["content"]
    assert post["deep_content"] == article["deep_content"]
    assert post["reading_time_min"] == 1
    assert post["deep_reading_time_min"] == seo._estimate_reading_time(
        article["deep_content"]
    )
    assert post["index_deep_view"] is True
    assert (
        "DO-NOT-EXPOSE" not in response.text and "SECRET-INTERNAL" not in response.text
    )
    assert response.text.index('id="blog-bootstrap"') < response.text.index(
        'src="/assets/app.js"'
    )


def test_bootstrap_roundtrips_script_breakouts_and_unicode(article):
    attack = '</ScRiPt><script id="pwned">alert(1)</script><&>\u2028\u2029'
    article.update(content=attack, deep_content=attack, title=attack, excerpt=attack)
    # Isolate JSON embedding from the existing trusted-author raw-Markdown
    # renderer: a safe rendered body must not gain executable payload markup.
    html = seo._build_document(
        title=attack,
        description=attack,
        canonical="https://example.com/blog/test",
        og_type="article",
        image="",
        json_ld=None,
        article_html="<p>Already rendered public article</p>",
        blog_post=article,
    )
    parser = BootstrapParser()
    parser.feed(html)
    assert len(parser.blocks) == 1
    raw = parser.blocks[0]
    assert not any(char in raw for char in "<>&\u2028\u2029")
    assert '<script id="pwned">' not in html
    assert json.loads(raw)["post"]["content"] == attack
    assert json.loads(raw)["post"]["deep_content"] == attack


@pytest.mark.parametrize(
    "slug,status", [("draft", 404), ("unknown", 404), ("deleted", 410)]
)
def test_nonpublic_pages_never_expose_bootstrap(article, slug, status):
    response = TestClient(app).get(f"/blog/{slug}?view=deep")
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert 'id="blog-bootstrap"' not in response.text
    assert "PRIVATE-DRAFT" not in response.text
    assert 'content="noindex,nofollow"' in response.text
