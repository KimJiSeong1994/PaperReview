import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTRO_SOURCE = ROOT / "web-ui" / "src" / "components" / "IntroducePage.tsx"
LANDING_SOURCE = ROOT / "web-ui" / "src" / "components" / "LandingSections.tsx"
FAQ_SOURCE = ROOT / "web-ui" / "src" / "seo" / "introduceFaq.ts"
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


def test_introduce_maintains_english_and_korean_copy() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (INTRO_SOURCE, LANDING_SOURCE, FAQ_SOURCE)
    )
    assert "Find the papers." in source
    assert "논문을 찾은 뒤," in source
    assert "What kind of AI paper search tool is Jiphyeonjeon?" in source
    assert "집현전은 어떤 AI 논문 검색 도구인가요?" in source


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
    assert 'data-static-route="introduce-ko"' in source
    assert "What happens in one conversation" in source
    assert "대화 한 번에 일어나는 일" in source
    assert "How are claims in an AI paper review verified?" in source
    assert "FAQPage" in source
    assert "AboutPage" in source
    assert "BreadcrumbList" in source
    assert 'https://jiphyeonjeon.kr/ko/introduce/' in source
    assert 'hreflang="en"' in source
    assert 'hreflang="ko"' in source


def test_introduce_static_route_explains_optional_claude_access() -> None:
    """Claude crawlers can distinguish the public web app from its extension."""
    source = STATIC_ROUTE_SOURCE.read_text(encoding="utf-8")

    assert "Use Jiphyeonjeon with Claude" in source
    assert "optional open-source extension installed separately" in source
    assert "https://github.com/KimJiSeong1994/jiphyeonjeon-agent" in source


def test_introduce_does_not_claim_signed_out_search_or_unconditional_verification() -> None:
    """Search needs sign-in, and claim verification happens only in a full review."""
    sources = [
        path.read_text(encoding="utf-8")
        for path in (INTRO_SOURCE, LANDING_SOURCE, FAQ_SOURCE, STATIC_ROUTE_SOURCE)
    ]
    for source in sources:
        assert "검색은 바로 시작할 수 있습니다" not in source
        assert "Search immediately" not in source
        assert "국내 논문 검색" not in source
    faq = FAQ_SOURCE.read_text(encoding="utf-8")
    assert "정밀 리뷰에서 검증합니다" in faq
    assert "In a full review." in faq


def test_introduce_drops_hard_coded_extension_counts() -> None:
    source = LANDING_SOURCE.read_text(encoding="utf-8")
    assert "RESEARCH_SKILL_COUNT" not in source
    assert "MCP_TOOL_COUNT" not in source
    assert re.search(r"\d+\s*개\s*(?:MCP|연구 스킬)", source) is None
    assert re.search(r"\b\d+\s+(?:MCP tools|research skills)\b", source) is None


def test_introduce_static_route_keeps_claude_anchor_and_avoids_sample_links() -> None:
    """llms.txt links /introduce/#claude; /samples full loads need the nginx route first."""
    source = STATIC_ROUTE_SOURCE.read_text(encoding="utf-8")
    assert source.count('<section id="claude">') == 2
    assert 'href="/samples' not in source
