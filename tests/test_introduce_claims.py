import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTRO_SOURCE = ROOT / "web-ui" / "src" / "components" / "IntroducePage.tsx"
LANDING_SOURCE = ROOT / "web-ui" / "src" / "components" / "LandingSections.tsx"
STATIC_ROUTE_SOURCE = ROOT / "web-ui" / "scripts" / "create-static-routes.mjs"
POSTS_SOURCE = ROOT / "data" / "blog" / "posts.json"


def test_introduce_does_not_display_a_volatile_public_review_count() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (INTRO_SOURCE, LANDING_SOURCE)
    )
    assert "PUBLISHED_REVIEWS" not in source
    assert re.search(r"공개(?:된)? 리뷰[^\n]{0,30}\d+편", source) is None
    assert re.search(r"\b\d+\s+(?:public\s+)?(?:paper\s+)?reviews?\b", source, re.I) is None


def test_introduce_avoids_unmeasured_review_duration_claims() -> None:
    source = LANDING_SOURCE.read_text(encoding="utf-8")
    assert "4~5분" not in source
    assert "4-5분" not in source
    assert "4–5 minutes" not in source
    assert "4-5 minutes" not in source


def test_introduce_visible_copy_is_english() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (INTRO_SOURCE, LANDING_SOURCE)
    )
    assert re.search(r"[가-힣]", source) is None


def test_introduce_blog_links_resolve_to_published_posts() -> None:
    source = LANDING_SOURCE.read_text(encoding="utf-8")
    paths = set(re.findall(r'(?:to:\s*\'|to=")(/blog/[^\'"]+)', source))
    post_paths = {path for path in paths if not path.startswith("/blog/category/")}

    posts = json.loads(POSTS_SOURCE.read_text(encoding="utf-8"))["posts"]
    published_slugs = {
        post["slug"]
        for post in posts
        if post.get("published") is True and post.get("slug")
    }

    assert post_paths
    assert {path.removeprefix("/blog/") for path in post_paths} <= published_slugs


def test_introduce_static_route_exposes_search_content_without_javascript() -> None:
    source = STATIC_ROUTE_SOURCE.read_text(encoding="utf-8")
    assert 'data-static-route="introduce"' in source
    assert "From paper search to source verification" in source
    assert "How are claims in an AI paper review verified?" in source
    assert "AboutPage" in source
    assert "BreadcrumbList" in source


def test_introduce_static_route_explains_optional_claude_access() -> None:
    """Claude crawlers can distinguish the public web app from its extension."""
    source = STATIC_ROUTE_SOURCE.read_text(encoding="utf-8")

    assert "Use Jiphyeonjeon with Claude" in source
    assert "optional open-source extension installed separately" in source
    assert "https://github.com/KimJiSeong1994/jiphyeonjeon-agent" in source
