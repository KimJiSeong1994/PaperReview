"""
Server-side SEO/GEO rendering endpoints (no API prefix).

These routes are proxied directly by Nginx so non-JS crawlers and AI engines
(ChatGPT / Perplexity / Claude) receive fully-rendered HTML, a sitemap, and an
RSS feed for the blog. Real users still boot the React SPA on top of the
server-rendered markup via the hashed asset tags extracted from the build.

Endpoints:
  GET /blog            — blog index (HTML, JSON-LD Blog graph)
  GET /blog/{slug}     — single post (HTML, JSON-LD BlogPosting graph)
  GET /sitemap.xml     — XML sitemap of public URLs
  GET /feed.xml        — RSS 2.0 feed of published posts
  GET /llms-full.txt   — full-text published blog corpus for AI/search retrieval
"""

import html
import importlib.util
import json
import logging
import re
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response
from markdown_it import MarkdownIt

from .blog import (
    PostDetail,
    _effective_thumbnail,
    _estimate_reading_time,
    _load_deleted,
    _load_posts,
    _merged_tag_counts,
    _posts_lock,
    _sort_posts_by_publication,
)
from .geo_comparisons import load_geo_comparisons

logger = logging.getLogger(__name__)

router = APIRouter(tags=["seo"])

# Hangul detection: syllables (U+AC00–U+D7A3), Jamo (U+1100–U+11FF),
# compatibility Jamo (U+3130–U+318F). Must match the frontend TS rule.
_HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")


def _detect_lang(text: str) -> str:
    """Return ``"ko"`` if the text contains any Hangul char, else ``"en"``."""
    return "ko" if _HANGUL.search(text or "") else "en"


def _locale(lang: str) -> str:
    """Map a language code to its Open Graph locale string."""
    return "ko_KR" if lang == "ko" else "en_US"


def _absolute_url(url: str | None) -> str:
    """Return an absolute public URL for crawler-facing metadata.

    Stored blog media often uses root-relative paths such as
    ``/api/blog/figures/foo.png``. Browsers resolve those fine, but Google
    structured-data and social-card validators are stricter and more reliable
    when ``image``/``og:image`` values are absolute crawlable URLs.
    """
    value = (url or "").strip()
    if not value:
        return ""
    if value.startswith(("https://", "http://")):
        return value
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("/"):
        return f"{SITE_URL}{value}"
    return f"{SITE_URL}/{value}"


# ── Constants ─────────────────────────────────────────────────────────

SITE_URL = "https://jiphyeonjeon.kr"
OG_DEFAULT_IMAGE = f"{SITE_URL}/og-default.jpg"
BLOG_TITLE = "Jiphyeonjeon Blog - Paper Research Notes"
BLOG_DESCRIPTION = "Research writeups, experiments, and product notes from Jiphyeonjeon."
LLMS_DESCRIPTION = (
    "AI-powered academic paper search and multi-agent deep-review tool for "
    "researchers (Korean/English). Search arXiv, Google Scholar, OpenAlex and "
    "more; run deep multi-agent paper reviews; build study curricula; explore "
    "citation graphs."
)
DIST_INDEX = Path("web-ui/dist/index.html")

ORG_ID = "https://jiphyeonjeon.kr/#organization"

_GEO_AXIS_LABELS = {
    "retrieval_or_representation_unit": "다루는 정보·표현 단위",
    "graph_construction": "입력 그래프와 구성",
    "evaluation_context": "평가 조건",
    "traceability": "설명·근거 확인",
    "cost": "비용",
    "failure_conditions": "실패 조건",
}

# Maintainer profile links shown site-wide for service credibility. Keep in
# sync with web-ui/src/components/SiteFooter.tsx and structuredData.ts.
GITHUB_PROFILE_URL = "https://github.com/KimJiSeong1994"
LINKEDIN_PROFILE_URL = "https://www.linkedin.com/in/jiseong-kim-868218193/"

# Pre-hydration footer appended inside #root on SSR pages so non-JS crawlers
# and users see the same links the React SiteFooter renders. Only Korean
# documents are built this way, hence the /ko/introduce/ href. Kept in sync
# with web-ui/src/components/SiteFooter.tsx by tests/test_site_footer_sync.py.
_SITE_FOOTER_HTML = (
    '<footer class="site-footer"><div class="site-footer-columns">'
    '<nav class="site-footer-column" aria-label="집현전">'
    '<p class="site-footer-heading">집현전</p><ul class="site-footer-list">'
    '<li><a href="/">논문 검색</a></li>'
    '<li><a href="/ko/introduce/">서비스 소개</a></li>'
    "</ul></nav>"
    '<nav class="site-footer-column" aria-label="블로그">'
    '<p class="site-footer-heading">블로그</p><ul class="site-footer-list">'
    '<li><a href="/blog">전체 아티클</a></li>'
    '<li><a href="/blog#series-index">아티클 시리즈</a></li>'
    '<li><a href="/blog/tags">태그 전체 보기</a></li>'
    "</ul></nav>"
    '<nav class="site-footer-column" aria-label="만든 사람">'
    '<p class="site-footer-heading">만든 사람</p><ul class="site-footer-list">'
    f'<li><a href="{GITHUB_PROFILE_URL}" target="_blank" rel="me noopener noreferrer">GitHub</a></li>'
    f'<li><a href="{LINKEDIN_PROFILE_URL}" target="_blank" rel="me noopener noreferrer">LinkedIn</a></li>'
    "</ul></nav></div>"
    '<span class="site-footer-brand">© Jiphyeonjeon (집현전)</span>'
    "</footer>"
)

# Ordered blog series hubs (pillar pages). Keys are the /blog/series/{id}
# path segment; ``slugs`` is the recommended reading order. Keep in sync with
# web-ui/src/seo/series.ts (shared contract, like the JSON-LD builders).
BLOG_SERIES: dict[str, dict] = {
    "jiphyeonjeon-build": {
        "title": "집현전 개발 시리즈",
        "description": (
            "집현전을 만들며 남긴 개발 기록 7편을 시간순으로 읽습니다. "
            "검색 에이전트에서 출발해 논문 관계 그래프, 자동 하이라이트, 읽기 커리큘럼으로 "
            "이어집니다. 이어 MCP 도구 확장, 연구자 페르소나 기반 추천, 검색 프롬프트 선택을 "
            "다루며 논문을 찾는 기능이 읽기와 개인화로 넓어지는 흐름을 살펴봅니다."
        ),
        "slugs": [
            "search-agent-beyond-single-query-65bcbe5c30fd",
            "paper-network-graph-hidden-connections-f954b2866fb4",
            "auto-highlight-ai-scholarly-annotation-f6a5ccb4ce6b",
            "curriculum-generator-jiphyeonjeon-9fdf6c688749",
            "jiphyeonjeon-agent-mcp-tool-surface-a7c9e3d4b821",
            "daily-recommendations-research-persona-dailyrec2026",
            "skillopt-search-policy-training-90c0bb4ee568",
        ],
    },
    "gnn": {
        "title": "GNN 논문 리뷰 시리즈",
        "description": (
            "그래프 표현 학습과 그래프 신경망(GNN)을 11편으로 읽는 시리즈입니다. "
            "노드를 벡터로 표현하는 기초에서 이웃 정보 집계와 새 노드로의 일반화, "
            "이종 그래프와 예측 설명, 공정한 기준선 비교로 이어집니다. "
            "성능 순위가 아니라 개념을 연결하는 읽기 순서입니다."
        ),
        "slugs": [
            "deepwalk-online-learning-social-representations-review-2026",
            "structural-deep-network-embedding-sdne-review-2026",
            "semi-supervised-classification-graph-convolutional-networks-review-2026",
            "graphsage-inductive-representation-learning-large-graphs-review-2026",
            "graph-attention-networks-gat-review-2026",
            "how-powerful-are-graph-neural-networks-gin-review-2026",
            "heterogeneous-graph-neural-network-hetgnn-review-2026",
            "heterogeneous-graph-attention-network-han-review-2026",
            "gnnexplainer-gnn-subgraph-feature-mask-review-2026",
            "explaining-temporal-graph-neural-networks-feature-induced-information-flow-review-2026",
            "classic-gnns-strong-baselines-graph-level-tasks-gnnplus-review-2026",
        ],
    },
    "dwe": {
        "title": "DWE 논문 리뷰 시리즈",
        "description": (
            "단어 의미의 시간적 변화를 추적하는 동적 단어 임베딩의 핵심 논문 12편을 읽습니다. "
            "변화의 통계적 탐지에서 출발해 시간 구간 사이의 임베딩 정렬과 동적 모델을 살펴보고, "
            "문맥화 표현과 용법 분석, 체계 비교로 이어집니다. 각 단계에서 무엇을 의미 변화로 "
            "측정하고 서로 다른 시점의 표현을 어떻게 비교하는지에 초점을 맞춥니다."
        ),
        "slugs": [
            "statistically-significant-detection-linguistic-change-review-2026",
            "diachronic-word-embeddings-statistical-laws-semantic-change-review-2026",
            "dynamic-word-embeddings-dsg-review-2026",
            "dynamic-word-embeddings-evolving-semantic-discovery-review-2026",
            "dynamic-bernoulli-embeddings-language-evolution-review-2026",
            "training-temporal-word-embeddings-compass-twec-review-2026",
            "survey-computational-approaches-lexical-semantic-change-review-2026",
            "how-contextual-are-contextualized-word-representations-review-2026",
            "analysing-lexical-semantic-change-contextualised-word-representations-review-2026",
            "dynamic-contextualized-word-embeddings-dcwe-review-2026",
            "contextualised-semantic-shift-detection-survey-review-2026",
            "a-systematic-comparison-contextualized-word-embeddings-lexical-semantic-change",
        ],
    },
    "graphrag": {
        "title": "GraphRAG 논문 리뷰 시리즈",
        "description": (
            "LLM 검색증강생성에 그래프를 결합하는 GraphRAG 계열의 핵심 논문 11편을 "
            "기초 연구부터 최초 공개 순서로 읽습니다. 문서 그래프 탐색과 전역 요약에서 "
            "연상 기억, 이중 검색, 인과·계층 검색과 다단계 파이프라인으로 이어집니다. "
            "문서 간 관계를 어떻게 색인하고 무엇을 검색하며, 답변의 근거를 어디까지 "
            "확인할 수 있는지 비교합니다."
        ),
        "slugs": [
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
        ],
    },
    "graph-causality": {
        "title": "Graph causality 논문 리뷰 시리즈",
        "description": (
            "그래프와 동역학 시계열에서 인과 구조를 복원하려는 핵심 논문 3편을 "
            "공개·기초 흐름 순서로 읽습니다. PCM의 간접 인과 구분에서 CIC의 잠재 교란자 "
            "분해, IC2의 개입 동역학 인과 추정으로 이어집니다. 직접 인과, 간접 인과, "
            "잠재 교란자를 각 방법이 어떻게 구분하려는지 살펴봅니다."
        ),
        "slugs": [
            "pcm-partial-cross-mapping-eliminates-indirect-causal-influences",
            "cic-dynamical-causality-under-invisible-confounders",
            "ic2-interventional-dynamical-causality-under-latent-confounders",
        ],
    },
}


def _series_membership(slug: str) -> tuple[str, int] | None:
    """Return ``(series_id, position)`` (1-based) for a slug, else ``None``."""
    for series_id, series in BLOG_SERIES.items():
        if slug in series["slugs"]:
            return series_id, series["slugs"].index(slug) + 1
    return None


# Indexable blog category hubs: value -> (display label, hub description).
BLOG_CATEGORIES: dict[str, tuple[str, str]] = {
    "paper-review": (
        "Paper Reviews",
        "Deep multi-agent reviews of individual academic papers from Jiphyeonjeon.",
    ),
    "engineering": (
        "Engineering",
        "Product and engineering notes from building Jiphyeonjeon.",
    ),
}

# ``linkify`` requires optional linkify-it-py. Keep SSR crawler output
# available even when the optional package is absent in test/minimal deploys.
_LINKIFY_AVAILABLE = importlib.util.find_spec("linkify_it") is not None
_md = MarkdownIt("default", {"html": True, "linkify": _LINKIFY_AVAILABLE})

# Matches a single leading top-level ATX heading ("# ...") plus trailing blank
# lines, used to drop the duplicate H1 many posts repeat as their first line.
_LEADING_H1_RE = re.compile(r"\A\s*#[ \t]+[^\n]*\n+")


def _strip_leading_h1(content: str) -> str:
    """Remove a leading ``# `` heading so the page keeps a single (title) H1.

    The template already renders the post title as the ``<h1>``; posts that
    repeat it as the first markdown heading produce a duplicate — and sometimes
    conflicting — H1. Only a leading level-1 ATX heading is stripped; deeper
    headings and mid-body H1s are left untouched.
    """
    return _LEADING_H1_RE.sub("", content, count=1)


_LEADING_H1_TEXT_RE = re.compile(r"\A\s*#[ \t]+([^\n]+)")


def _leading_h1_text(content: str) -> str:
    """Return the (usually Korean) leading ``# `` heading text, else ``""``.

    The visible ``<h1>`` is the English ``post['title']`` and the markdown's own
    leading heading is stripped to avoid a duplicate H1 — but that heading is a
    Korean subtitle ("SDNE 심층 분석: … 논문 해설"). We surface it as a Korean
    ``<h2>`` dek so the page carries a Korean heading (the on-page signal Korean
    queries lack), without editing the post body.
    """
    m = _LEADING_H1_TEXT_RE.match(content or "")
    return m.group(1).strip() if m else ""


def _repair_corrupted_latex_escapes(content: str) -> str:
    r"""Repair common JSON escape damage in stored markdown math.

    A markdown fragment containing ``\tilde`` can be accidentally serialized as
    the JSON escape ``\t`` plus ``ilde``, which becomes a tab character and
    renders as ``ilde{A}``. Keep this narrow: only repair the exact tab+ilde
    sequence observed in blog math, without touching ordinary prose tabs.
    """
    return content.replace("\t" + "ilde", r"\tilde")


def _normalize_display_math_fences(content: str) -> str:
    r"""Put display-math dollar fences on their own lines.

    remark-math/KaTeX and other markdown math parsers are more reliable when
    ``$$`` opens/closes a flow block instead of sharing a line with content.
    Strip list indentation from both fences as one unit: retaining indentation
    on only the opening fence makes markdown-math pair its closing fence with a
    later equation and can consume the intervening article as invalid math.
    """
    return re.sub(
        r"^[ \t]*\$\$([\s\S]*?)\$\$[ \t]*$",
        lambda m: f"$$\n{m.group(1).strip()}\n$$",
        content,
        flags=re.MULTILINE,
    )


def _normalize_latex_delimiters(content: str) -> str:
    r"""Normalize LaTeX note delimiters to markdown-math dollar delimiters.

    PaperWiki/Notion-derived reviews often use ``\(...\)`` and ``\[...\]``.
    Plain Markdown treats those backslashes as escapes, producing broken text
    such as ``(\tilde A)`` in the SSR HTML. The React renderer uses
    remark-math/KaTeX, whose portable delimiter is ``$...$`` / ``$$...$$``.
    Keep the transformation narrow so ordinary prose is left untouched.
    """
    content = re.sub(r"\\\[([\s\S]*?)\\\]", lambda m: f"$${m.group(1).strip()}$$", content)
    return re.sub(r"\\\(([^\n]*?)\\\)", lambda m: f"${m.group(1).strip()}$", content)


def _render_ssr_math_fallback(content: str) -> str:
    r"""Render dollar-delimited math as crawlable fallback HTML.

    The browser bundle hydrates the same markdown with remark-math/KaTeX, but
    the server-side markdown-it renderer intentionally has no JS KaTeX pass.
    Without this fallback, SSR HTML exposes raw ``$\tilde A$`` delimiters in
    table cells and paragraphs.  Keep the fallback conservative and readable:
    fenced code blocks are left untouched, display equations become scrollable
    code blocks, and inline equations become compact code-like spans.
    """

    def _inline(line: str) -> str:
        out: list[str] = []
        i = 0
        while i < len(line):
            if line[i] != "$" or (i > 0 and line[i - 1] == "\\"):
                out.append(line[i])
                i += 1
                continue
            # Display math is handled at line level; leave paired $$ here.
            if i + 1 < len(line) and line[i + 1] == "$":
                out.append("$$")
                i += 2
                continue
            j = i + 1
            while True:
                j = line.find("$", j)
                if j == -1:
                    out.append(line[i])
                    i += 1
                    break
                if j > 0 and line[j - 1] == "\\":
                    j += 1
                    continue
                expr = line[i + 1 : j].strip()
                if not expr:
                    out.append(line[i : j + 1])
                else:
                    safe = html.escape(expr, quote=False)
                    out.append(f'<span class="blog-math-inline"><code>{safe}</code></span>')
                i = j + 1
                break
        return "".join(out)

    rendered: list[str] = []
    display: list[str] | None = None
    in_fence = False

    for line in content.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            rendered.append(line)
            continue
        if in_fence:
            rendered.append(line)
            continue

        stripped = line.strip()
        if display is not None:
            if stripped.endswith("$$"):
                before_close = line[: line.rfind("$$")]
                if before_close.strip():
                    display.append(before_close)
                safe = html.escape("\n".join(display).strip(), quote=False)
                rendered.append(f'<div class="blog-math-display"><code>{safe}</code></div>')
                display = None
            else:
                display.append(line)
            continue

        if stripped == "$$":
            display = []
            continue
        if stripped.startswith("$$"):
            after_open = line[line.find("$$") + 2 :]
            if after_open.strip().endswith("$$"):
                safe = html.escape(after_open[: after_open.rfind("$$")].strip(), quote=False)
                rendered.append(f'<div class="blog-math-display"><code>{safe}</code></div>')
            else:
                display = [after_open] if after_open.strip() else []
            continue

        rendered.append(_inline(line))

    if display is not None:
        rendered.append("$$")
        rendered.extend(display)

    return "\n".join(rendered)


def _normalize_blog_markdown(content: str, *, ssr_math_fallback: bool = False) -> str:
    """Apply SSR-safe blog markdown normalizations before rendering."""
    normalized = _normalize_display_math_fences(
        _normalize_latex_delimiters(_strip_leading_h1(_repair_corrupted_latex_escapes(content)))
    )
    if ssr_math_fallback:
        return _render_ssr_math_fallback(normalized)
    return normalized


def _category_of(post: dict) -> str:
    """Return a known category for a post, defaulting to 'engineering'."""
    cat = post.get("category", "engineering")
    return cat if cat in BLOG_CATEGORIES else "engineering"


def _related_posts(post: dict, published: list[dict], limit: int = 4) -> list[dict]:
    """Return up to ``limit`` other published posts related to ``post``.

    Ranked by: same category, then number of shared tags, then recency.
    Excludes the post itself. ``published`` may be in any order.
    """
    slug = post.get("slug")
    cat = _category_of(post)
    tags = set(post.get("tags", []))
    others = [p for p in published if p.get("slug") != slug]

    def _score(p: dict) -> tuple:
        return (
            1 if _category_of(p) == cat else 0,
            len(tags & set(p.get("tags", []))),
            p.get("created_at", ""),
        )

    others.sort(key=_score, reverse=True)
    return others[:limit]

# ── Asset extraction (cached by dist/index.html mtime) ────────────────

_asset_cache: dict[str, object] = {"mtime": None, "css": "", "scripts": ""}
_SERIES_MANIFEST = "series-manifest.json"


def _get_assets() -> tuple[str, str]:
    """Return (css_links, module_scripts) extracted from the built index.html.

    The result is cached and only re-parsed when the file's mtime changes.
    When DIST_INDEX is missing (dev environment), returns empty strings so
    crawlers still receive content without crashing.
    """
    try:
        mtime = DIST_INDEX.stat().st_mtime
    except OSError:
        return "", ""

    if _asset_cache["mtime"] == mtime:
        return _asset_cache["css"], _asset_cache["scripts"]  # type: ignore[return-value]

    try:
        raw = DIST_INDEX.read_text(encoding="utf-8")
    except OSError:
        return "", ""

    css = "".join(re.findall(r'<link[^>]+href="/assets/[^"]+"[^>]*>', raw))
    scripts = "".join(re.findall(r'<script[^>]+src="/assets/[^"]+"[^>]*></script>', raw))

    _asset_cache.update({"mtime": mtime, "css": css, "scripts": scripts})
    return css, scripts


def _series_stylesheets() -> str:
    """Load the lazy series entry's CSS without requiring JavaScript execution."""
    if not DIST_INDEX.is_file():
        return ""
    try:
        manifest = json.loads((DIST_INDEX.parent / _SERIES_MANIFEST).read_text())
    except (OSError, ValueError):
        logger.warning("series_stylesheets_invalid_built_manifest")
        return ""
    if not isinstance(manifest, dict):
        logger.warning("series_stylesheets_invalid_built_manifest")
        return ""
    visited: set[str] = set()
    styles: list[str] = []
    invalid = False

    def collect(key: str) -> None:
        nonlocal invalid
        if key in visited:
            return
        visited.add(key)
        chunk = manifest.get(key)
        if not isinstance(chunk, dict):
            invalid = True
            return
        imports = chunk.get("imports", [])
        if isinstance(imports, list):
            for dependency in imports:
                if isinstance(dependency, str):
                    collect(dependency)
                else:
                    invalid = True
        else:
            invalid = True
        css = chunk.get("css", [])
        if isinstance(css, list):
            for asset in css:
                if (
                    isinstance(asset, str)
                    and re.fullmatch(r"assets/[A-Za-z0-9_./-]+\.css", asset)
                    and ".." not in asset.split("/")
                    and (DIST_INDEX.parent / asset).is_file()
                ):
                    if asset not in styles:
                        styles.append(asset)
                else:
                    invalid = True
        else:
            invalid = True

    collect("src/components/SeriesPage.tsx")
    if invalid or not styles:
        logger.warning("series_stylesheets_invalid_built_manifest")
    return "".join(f'<link rel="stylesheet" href="/{asset}">' for asset in styles)


# ── Date helpers ──────────────────────────────────────────────────────


def _format_date(post: dict) -> str:
    """Return YYYY-MM-DD for ``updated_at or created_at`` with a safe fallback.

    Tries ``updated_at`` first, then ``created_at``; on parse failure falls back
    to ``created_at``'s raw date prefix.
    """
    raw = post.get("updated_at") or post.get("created_at") or ""
    try:
        return datetime.fromisoformat(raw).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        created = post.get("created_at") or ""
        try:
            return datetime.fromisoformat(created).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return created[:10]


def _parse_dt(value: str) -> datetime:
    """Parse an ISO datetime string, falling back to epoch-ish now on failure."""
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return datetime.now()


# ── Primary paper reference extraction ───────────────────────────────
# Shared contract with web-ui/src/utils/blogPaperReference.ts — the same
# "**Paper:**" citation block is parsed on both sides, so keep the regexes
# and fallbacks identical when changing either implementation.

_PAPER_BLOCK_RE = re.compile(
    r"\*\*Paper:\*\*\s*(.*?)(?=\n\s*\*\*Abstract:\*\*|\n\s*---|\n\s*##\s|$)",
    re.IGNORECASE | re.DOTALL,
)
_ARXIV_RE = re.compile(r"arXiv:?\s*([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", re.IGNORECASE)
_DOI_URL_RE = re.compile(r"https://doi\.org/([^\s)]+)", re.IGNORECASE)
_DOI_TEXT_RE = re.compile(r"\b(?:doi|DOI):\s*(10\.\d{4,9}/[^\s)]+)", re.IGNORECASE)
_DIRECT_PDF_LINK_RE = re.compile(
    r"\[PDF\]\((https://[^\s)]+\.pdf(?:\?[^\s)]*)?)\)", re.IGNORECASE
)
_QUOTED_TITLE_RE = re.compile(r'"([^"]+)"')
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")


def _extract_primary_paper_reference(post: dict) -> dict | None:
    """Return the reviewed paper's citation parsed from the post content.

    Mirrors ``extractPrimaryPaperReference`` in the frontend. Returns a dict
    with ``title``, ``authors`` and optional ``year``/``arxiv_id``/``doi``/
    ``url``/``pdf_url``, or ``None`` when no citation can be recovered.
    """
    content = post.get("content", "") or ""
    match = _PAPER_BLOCK_RE.search(content)
    # A conference/program collection has multiple sources, not one paper.
    # Keep legacy paper-review fallback for articles without either header.
    if not match and re.search(r"^\*\*Sources:\*\*", content, re.IGNORECASE | re.MULTILINE):
        return None
    if not match and post.get("category") != "paper-review":
        return None

    block = (match.group(1) if match else content[:1000]).strip()
    if not block:
        return None

    arxiv_match = _ARXIV_RE.search(block)
    arxiv_id = arxiv_match.group(1).strip().rstrip(".,;:") if arxiv_match else None
    doi_match = _DOI_URL_RE.search(block) or _DOI_TEXT_RE.search(block)
    doi = doi_match.group(1).rstrip(".,;:") if doi_match else None
    direct_pdf_match = _DIRECT_PDF_LINK_RE.search(block)
    direct_pdf_url = direct_pdf_match.group(1) if direct_pdf_match else None
    title_match = _QUOTED_TITLE_RE.search(block)
    title = (title_match.group(1).strip() if title_match else "") or post.get("title", "")
    title = re.sub(r"\.$", "", title)
    year_match = _YEAR_RE.search(block)

    before_title = block.split('"')[0].strip()
    without_year = re.sub(r"\([^)]*\d{4}[^)]*\)\.?\s*$", "", before_title).strip()
    authors = [a.strip() for a in without_year.split(";") if a.strip()]

    if not arxiv_id and not doi and not title:
        return None

    ref: dict = {"title": title, "authors": authors}
    if year_match:
        ref["year"] = int(year_match.group(1))
    if arxiv_id:
        arxiv_base_id = re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)
        ref["arxiv_id"] = arxiv_id
        ref["url"] = f"https://arxiv.org/abs/{arxiv_id}"
        ref["pdf_url"] = f"https://arxiv.org/pdf/{arxiv_base_id}.pdf"
    elif doi:
        ref["url"] = f"https://doi.org/{doi}"
        if direct_pdf_url:
            ref["pdf_url"] = direct_pdf_url
    elif direct_pdf_url:
        ref["url"] = direct_pdf_url
        ref["pdf_url"] = direct_pdf_url
    if doi:
        ref["doi"] = doi
    return ref


# ── JSON-LD builders (must byte-match the frontend builder) ───────────


def _organization_node() -> dict:
    """Return the shared Organization node referenced across all graphs."""
    return {
        "@type": "Organization",
        "@id": ORG_ID,
        "name": "Jiphyeonjeon",
        "alternateName": ["집현전", "Jiphyeonjeon Team", "집현전 팀"],
        "url": "https://jiphyeonjeon.kr",
        "description": (
            "AI-powered academic paper search and multi-agent deep-review web app "
            "for researchers, covering arXiv, Google Scholar and OpenAlex."
        ),
        "disambiguatingDescription": (
            "A modern AI research tool; not the 15th-century Joseon-dynasty royal "
            "research institute of the same name (the Hall of Worthies)."
        ),
        "sameAs": [
            "https://github.com/KimJiSeong1994/PaperReview",
        ],
        "logo": {
            "@type": "ImageObject",
            "url": "https://jiphyeonjeon.kr/Jiphyeonjeon_llama.png",
        },
    }


def _breadcrumb(title: str | None = None, slug: str | None = None) -> dict:
    """Return a BreadcrumbList; appends the post crumb when title & slug given."""
    items = [
        {
            "@type": "ListItem",
            "position": 1,
            "name": "Home",
            "item": "https://jiphyeonjeon.kr/",
        },
        {
            "@type": "ListItem",
            "position": 2,
            "name": "Blog",
            "item": "https://jiphyeonjeon.kr/blog",
        },
    ]
    if title and slug:
        items.append(
            {
                "@type": "ListItem",
                "position": 3,
                "name": title,
                "item": f"https://jiphyeonjeon.kr/blog/{slug}",
            }
        )
    return {"@type": "BreadcrumbList", "itemListElement": items}


def _scholarly_article_node(ref: dict) -> dict:
    """Return a ScholarlyArticle node for the paper a review is about."""
    node: dict = {
        "@type": "ScholarlyArticle",
        "@id": ref["url"],
        "name": ref["title"],
    }
    if ref.get("authors"):
        node["author"] = [{"@type": "Person", "name": name} for name in ref["authors"]]
    identifiers = []
    if ref.get("arxiv_id"):
        identifiers.append(
            {"@type": "PropertyValue", "propertyID": "arXiv", "value": ref["arxiv_id"]}
        )
    if ref.get("doi"):
        identifiers.append({"@type": "PropertyValue", "propertyID": "DOI", "value": ref["doi"]})
        if ref.get("arxiv_id"):
            node["sameAs"] = [f"https://doi.org/{ref['doi']}"]
    if identifiers:
        node["identifier"] = identifiers
    return node


def _blog_author_node(byline: str | None) -> dict | None:
    """Map the displayed review byline without inventing an identity."""
    name = (byline or "").strip()
    if not name:
        return None
    if name.casefold() == "jiphyeonjeon team":
        organization = _organization_node()
        return {
            key: organization[key]
            for key in ("@type", "@id", "name", "alternateName", "url")
        }
    return {"@type": "Person", "name": name}


_FAQ_SECTION_RE = re.compile(
    r"^##[ \t]+(?:자주\s*묻는\s*질문|FAQ|Q\s*&\s*A)[^\n]*\n(.*?)(?=\n##[ \t]|\Z)",
    re.S | re.M,
)
_FAQ_QA_RE = re.compile(r"^###[ \t]+([^\n]+)\n(.*?)(?=\n###[ \t]|\Z)", re.S | re.M)


def _extract_faq(content: str) -> list[tuple[str, str]]:
    """Parse a ``## 자주 묻는 질문`` section into (question, answer) pairs.

    Empty until posts add an FAQ section (Tier-2 content); pre-wired so that the
    moment such a section exists it auto-emits FAQPage rich-result markup with
    no further code change.
    """
    section = _FAQ_SECTION_RE.search(content or "")
    if not section:
        return []
    pairs: list[tuple[str, str]] = []
    for qa in _FAQ_QA_RE.finditer(section.group(1)):
        q = qa.group(1).strip()
        a = " ".join(qa.group(2).split()).strip()
        if q and a:
            pairs.append((q, a))
    return pairs


def _faq_node(pairs: list[tuple[str, str]], url: str) -> dict:
    """A schema.org FAQPage node built from question/answer pairs."""
    return {
        "@type": "FAQPage",
        "@id": f"{url}#faq",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in pairs
        ],
    }


def _blog_posting_graph(
    post: dict, identity_post: dict | None = None, *, deep_view: bool = False
) -> dict:
    """Return a BlogPosting graph for the displayed body and canonical paper.

    ``post`` supplies view-specific content fields such as ``articleBody`` and
    ``wordCount``. ``identity_post`` optionally supplies the stored default body
    used to identify the reviewed paper, so switching reading modes cannot
    change the article's ``about``/``citation`` target.
    """
    title = post.get("title", "")
    slug = post.get("slug", "")
    excerpt = post.get("excerpt", "")
    author = post.get("author", "")
    created_at = post.get("created_at", "")
    updated_at = post.get("updated_at") or created_at
    tags = post.get("tags", [])
    content = post.get("content", "")
    url = f"{SITE_URL}/blog/{slug}"
    if deep_view:
        url += "?view=deep"
    section = "Paper Reviews" if post.get("category") == "paper-review" else "Engineering"

    image = _absolute_url(post.get("thumbnail_url")) or OG_DEFAULT_IMAGE

    posting = {
        "@type": "BlogPosting",
        "headline": title,
        "description": excerpt,
        "datePublished": created_at,
        "dateModified": updated_at,
        "keywords": tags,
        "articleSection": section,
        "url": url,
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "publisher": {"@id": ORG_ID},
        "inLanguage": _detect_lang(f"{title} {content or excerpt}"),
        "wordCount": len(content.split()),
        "image": image,
    }
    author_node = _blog_author_node(author)
    if author_node:
        posting["author"] = author_node
    if (post.get("deep_content") or "").strip():
        posting["articleBody"] = content

    membership = _series_membership(slug)
    if membership:
        series_id, _position = membership
        posting["isPartOf"] = {
            "@id": f"https://jiphyeonjeon.kr/blog/series/{series_id}#collection"
        }

    graph = [_organization_node(), posting]
    # Link the review to the paper it discusses so answer engines can connect
    # "what does <paper> propose?" queries to this post as a citable source.
    identity_source = identity_post if identity_post is not None else post
    ref = _extract_primary_paper_reference(identity_source)
    if ref and ref.get("url"):
        posting["about"] = {"@id": ref["url"]}
        posting["citation"] = {"@id": ref["url"]}
        graph.append(_scholarly_article_node(ref))
    graph.append(_breadcrumb(title, slug))
    faq = _extract_faq(content)
    if faq:
        graph.append(_faq_node(faq, url))

    return {"@context": "https://schema.org", "@graph": graph}


def _blog_index_graph(posts: list[dict]) -> dict:
    """Return the @graph for the blog index page."""
    blog_posts = [
        {
            "@type": "BlogPosting",
            "headline": p.get("title", ""),
            "url": f"https://jiphyeonjeon.kr/blog/{p.get('slug', '')}",
        }
        for p in posts[:20]
    ]
    return {
        "@context": "https://schema.org",
        "@graph": [
            _organization_node(),
            {
                "@type": "Blog",
                "@id": "https://jiphyeonjeon.kr/blog#blog",
                "url": "https://jiphyeonjeon.kr/blog",
                "name": "Jiphyeonjeon Blog",
                "description": BLOG_DESCRIPTION,
                "publisher": {"@id": ORG_ID},
                "blogPost": blog_posts,
            },
            _breadcrumb(),
        ],
    }


def _category_graph(category: str, label: str, description: str, posts: list[dict]) -> dict:
    """Return the @graph for a category hub page (CollectionPage + ItemList)."""
    url = f"https://jiphyeonjeon.kr/blog/category/{category}"
    item_list = {
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "name": p.get("title", ""),
                "url": f"https://jiphyeonjeon.kr/blog/{p.get('slug', '')}",
            }
            for i, p in enumerate(posts[:20])
        ],
    }
    breadcrumb = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://jiphyeonjeon.kr/"},
            {"@type": "ListItem", "position": 2, "name": "Blog", "item": "https://jiphyeonjeon.kr/blog"},
            {"@type": "ListItem", "position": 3, "name": label, "item": url},
        ],
    }
    return {
        "@context": "https://schema.org",
        "@graph": [
            _organization_node(),
            {
                "@type": "CollectionPage",
                "@id": f"{url}#collection",
                "url": url,
                "name": f"{label} — Jiphyeonjeon Blog",
                "description": description,
                "isPartOf": {"@id": "https://jiphyeonjeon.kr/blog#blog"},
                "publisher": {"@id": ORG_ID},
                "mainEntity": item_list,
            },
            breadcrumb,
        ],
    }


def _series_graph(series_id: str, title: str, description: str, posts: list[dict]) -> dict:
    """Return the @graph for a series pillar page (CollectionPage + ItemList)."""
    url = f"https://jiphyeonjeon.kr/blog/series/{series_id}"
    items = [
        {
            "@type": "ListItem",
            "position": i + 1,
            "name": p.get("title", ""),
            "url": f"https://jiphyeonjeon.kr/blog/{p.get('slug', '')}",
        }
        for i, p in enumerate(posts)
    ]
    breadcrumb = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://jiphyeonjeon.kr/"},
            {"@type": "ListItem", "position": 2, "name": "Blog", "item": "https://jiphyeonjeon.kr/blog"},
            {"@type": "ListItem", "position": 3, "name": title, "item": url},
        ],
    }
    return {
        "@context": "https://schema.org",
        "@graph": [
            _organization_node(),
            {
                "@type": "CollectionPage",
                "@id": f"{url}#collection",
                "url": url,
                "name": f"{title} — Jiphyeonjeon Blog",
                "description": description,
                "isPartOf": {"@id": "https://jiphyeonjeon.kr/blog#blog"},
                "publisher": {"@id": ORG_ID},
                "mainEntity": {
                    "@type": "ItemList",
                    "itemListOrder": "https://schema.org/ItemListOrderAscending",
                    "numberOfItems": len(items),
                    "itemListElement": items,
                },
            },
            breadcrumb,
        ],
    }


def _series_total_minutes(posts: list[dict]) -> int | None:
    if not posts:
        return None
    total = 0
    for post in posts:
        minutes = post.get("reading_time_min")
        if not isinstance(minutes, (int, float)):
            return None
        total += minutes
    return int(total)


def _first_sentence(text: str) -> str:
    """Opening sentence of an excerpt/description (the claim without its hedge)."""
    trimmed = text.strip()
    cut = trimmed.find(". ")
    return trimmed if cut == -1 else trimmed[: cut + 1]


def _series_shared_sources(entry: dict, axes: list[str]) -> list[str] | None:
    """Return the shared source list when every axis cites the same sources."""
    first = entry["values"][axes[0]]["sources"]
    if not first:
        return None
    if all(entry["values"][axis]["sources"] == first for axis in axes):
        return first
    return None


def _series_source_links_html(sources: list[str]) -> str:
    links = "".join(
        f'<a href="{html.escape(source, quote=True)}" rel="noopener noreferrer">'
        f"출처 {index}</a>"
        for index, source in enumerate(sources, start=1)
    )
    return f'<span class="geo-comparison-sources">{links}</span>'


def _series_comparison_cell_html(cell: dict, *, include_sources: bool = True) -> str:
    content = cell["value"] if cell["state"] == "known" else cell["reason"]
    state_label = {
        "known": "",
        "unknown": '<span class="geo-state">미확인</span>',
        "not_applicable": '<span class="geo-state">해당 없음</span>',
    }[cell["state"]]
    provenance = _series_source_links_html(cell["sources"]) if include_sources and cell["sources"] else ""
    return f"{state_label}{html.escape(content or '')}{provenance}"


def _series_reading_guide_html(comparison: dict, by_slug: dict[str, dict]) -> str:
    if not comparison:
        return ""
    items = []
    for index, step in enumerate(comparison["reading_guide"], start=1):
        members = [slug for slug in step["slugs"] if slug in by_slug]
        minutes = _series_total_minutes([by_slug[slug] for slug in members])
        meta = (
            f'<span class="blog-series-path-meta">{len(members)}편'
            f'{f" · {minutes}분" if minutes is not None else ""}</span>'
            if members else ""
        )
        items.append(
            f'<li><a href="#series-stage-{index}">'
            f'<span class="blog-series-path-title">{html.escape(step["title"])}</span>'
            f"{meta}</a></li>"
        )
    return (
        '<nav class="blog-series-path" aria-labelledby="series-guide-title">'
        '<h2 id="series-guide-title">한눈에 보는 학습 경로</h2>'
        f'<ol data-count="{len(items)}">{"".join(items)}</ol></nav>'
    )


def _series_comparison_html(
    comparison: dict, posts_by_slug: dict[str, dict], *, detailed: bool = False
) -> str:
    """Render a validated comparison as readable, escaped HTML."""
    if not comparison:
        return ""

    entries = comparison["entries"]
    def entry_link(entry: dict) -> str:
        title = posts_by_slug.get(entry["slug"], {}).get("title")
        if not title:
            return html.escape(entry["label"])
        title_attr = f' title="{html.escape(title, quote=True)}"'
        return (
            f'<a href="/blog/{html.escape(entry["slug"], quote=True)}"{title_attr}>'
            f'{html.escape(entry["label"])}</a>'
        )

    cards = []
    for index, entry in enumerate(entries, start=1):
        if not detailed:
            summary = "".join(
                f"<div><dt>{label}</dt><dd>{html.escape(entry['summary'][key])}</dd></div>"
                for key, label in (("role", "역할"), ("fit", "이럴 때"), ("caution", "주의점"))
            )
            cards.append(
                f'<article class="geo-decision"><h3>{entry_link(entry)}</h3><dl>{summary}</dl>'
                f'<a class="blog-series-text-link" href="#series-evidence-{index}">'
                f'{html.escape(entry["label"])} 상세 근거 <span aria-hidden="true">→</span></a></article>'
            )
            continue
        hoisted = _series_shared_sources(entry, comparison["axes"])
        hoisted_html = (
            '<div class="geo-evidence-method-sources">'
            '<span class="geo-evidence-method-sources-label">전 항목 출처</span>'
            f"{_series_source_links_html(hoisted)}</div>"
            if hoisted else ""
        )
        axes = "".join(
            "<div>"
            f'<dt>{html.escape(_GEO_AXIS_LABELS[axis])}</dt>'
            f'<dd data-state="{html.escape(entry["values"][axis]["state"], quote=True)}">'
            f'{_series_comparison_cell_html(entry["values"][axis], include_sources=hoisted is None)}</dd></div>'
            for axis in comparison["axes"]
        )
        cards.append(
            f'<article class="geo-evidence-method" aria-labelledby="series-evidence-{index}">'
            f'<h3 id="series-evidence-{index}">{entry_link(entry)}</h3>{hoisted_html}<dl>{axes}</dl>'
            '<a class="blog-series-text-link" href="#geo-comparison-title">논문 선택 비교로 돌아가기 '
            '<span aria-hidden="true">↑</span></a></article>'
        )

    if detailed:
        return (
            '<section class="geo-evidence" aria-labelledby="series-evidence-title">'
            '<h2 id="series-evidence-title">상세 근거와 출처</h2>'
            f'<p class="geo-comparison-limits"><strong>해석 한계:</strong> {html.escape(comparison["limits"])}</p>'
            f'<p class="geo-comparison-source-note">{html.escape(comparison["source_note"])}</p>'
            f'{"".join(cards)}</section>'
        )
    return (
        '<section class="geo-comparison" aria-labelledby="geo-comparison-title">'
        '<h2 id="geo-comparison-title">논문 선택 비교</h2>'
        f'<p class="geo-comparison-question">{html.escape(comparison["question"])}</p>'
        '<p class="geo-comparison-caveat">성능 순위가 아닌 역할 비교입니다. 평가 조건과 한계는 상세 근거에서 확인하세요.</p>'
        f'<div class="geo-decision-grid" data-count="{len(entries)}">{"".join(cards)}</div>'
        "</section>"
    )


def _series_reading_list_html(ordered: list[dict], comparison: dict) -> str:
    positions = {post["slug"]: index for index, post in enumerate(ordered, start=1)}

    def post_list(members: list[dict]) -> str:
        if not members:
            return ""
        items = []
        for p in members:
            thumb_url = _effective_thumbnail(p)
            thumb = (
                f'<div class="blog-row-thumb"><img src="{html.escape(thumb_url, quote=True)}" '
                'alt="" width="228" height="128" loading="lazy" decoding="async"></div>'
                if thumb_url else ""
            )
            minutes = p.get("reading_time_min")
            time_html = (
                f'<span class="blog-series-time">{minutes}분</span>'
                if isinstance(minutes, (int, float)) else ""
            )
            items.append(
                f'<li><span class="blog-series-pos" aria-hidden="true">{positions[p["slug"]]}</span>'
                f'<a class="blog-row" href="/blog/{html.escape(p["slug"], quote=True)}" '
                f'aria-label="{html.escape(p.get("title", ""), quote=True)}">'
                '<div class="blog-row-text">'
                f'<h4 class="blog-row-title">{html.escape(p.get("title", ""))}</h4>'
                f'<p class="blog-row-excerpt">{html.escape(_first_sentence(p.get("excerpt", "")))}</p>'
                f'{time_html}</div>{thumb}</a></li>'
            )
        return f'<ol class="blog-series-list" start="{positions[members[0]["slug"]]}">{"".join(items)}</ol>'

    if not comparison:
        return post_list(ordered)
    stages = []
    for index, step in enumerate(comparison["reading_guide"], start=1):
        members = [post for post in ordered if post["slug"] in step["slugs"]]
        minutes = _series_total_minutes(members)
        meta = (
            f'<span class="blog-series-stage-meta">{len(members)}편'
            f'{f" · {minutes}분" if minutes is not None else ""}</span>'
            if members else ""
        )
        listing = post_list(members) or "<p>이 단계에는 아직 공개된 글이 없습니다.</p>"
        stages.append(
            f'<section class="blog-series-stage" aria-labelledby="series-stage-{index}">'
            '<div class="blog-series-stage-heading">'
            f'<h3 id="series-stage-{index}">{html.escape(step["title"])}</h3>{meta}</div>'
            f'<p class="blog-series-stage-description">{html.escape(step["description"])}</p>'
            f"{listing}</section>"
        )
    return "".join(stages)
# ── HTML document builder ─────────────────────────────────────────────


def _json_ld_script(obj: dict) -> str:
    """Serialize a JSON-LD object into a safe <script> tag."""
    payload = json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")
    return f'<script type="application/ld+json" id="seo-json-ld">{payload}</script>'


def _build_document(
    *,
    title: str,
    description: str,
    canonical: str,
    og_type: str,
    image: str,
    json_ld: dict | None,
    article_html: str,
    noindex: bool = False,
    lang: str = "en",
    locale: str = "en_US",
    published_time: str | None = None,
    modified_time: str | None = None,
    blog_post: dict | None = None,
    stylesheets: str = "",
) -> str:
    """Assemble a full SSR HTML document with SEO head + SPA boot assets.

    All dynamic text is HTML-escaped. JSON-LD is serialized with the
    ``</script>`` breakout guard. ``lang``/``locale`` drive the
    ``<html lang>`` attribute and the ``og:locale`` meta; the alternate
    locale is set to the other of ko_KR / en_US.
    """
    css, scripts = _get_assets()

    esc_title = html.escape(title, quote=True)
    esc_desc = html.escape(description, quote=True)
    esc_canonical = html.escape(canonical, quote=True)
    esc_type = html.escape(og_type, quote=True)
    esc_image = html.escape(image, quote=True)
    esc_lang = html.escape(lang, quote=True)
    esc_locale = html.escape(locale, quote=True)
    alternate_locale = "en_US" if locale == "ko_KR" else "ko_KR"

    robots_meta = (
        '<meta name="robots" content="noindex,nofollow">\n    '
        if noindex
        else '<meta name="robots" content="index, follow, max-image-preview:large, '
        'max-snippet:-1, max-video-preview:-1">\n    '
    )
    ld_block = f"{_json_ld_script(json_ld)}\n    " if json_ld else ""
    # article:* times parity with the client SEOHead (only for article pages).
    article_meta = ""
    if og_type == "article":
        if published_time:
            article_meta += (
                f'<meta property="article:published_time" '
                f'content="{html.escape(published_time, quote=True)}">\n    '
            )
        if modified_time:
            article_meta += (
                f'<meta property="article:modified_time" '
                f'content="{html.escape(modified_time, quote=True)}">\n    '
            )

    head = (
        f'<title>{esc_title}</title>\n    '
        f'<meta name="description" content="{esc_desc}">\n    '
        f'{robots_meta}'
        f'<link rel="canonical" href="{esc_canonical}">\n    '
        f'<meta property="og:title" content="{esc_title}">\n    '
        f'<meta property="og:description" content="{esc_desc}">\n    '
        f'<meta property="og:type" content="{esc_type}">\n    '
        f'<meta property="og:url" content="{esc_canonical}">\n    '
        f'<meta property="og:image" content="{esc_image}">\n    '
        f'<meta property="og:image:alt" content="{esc_title}">\n    '
        f'<meta property="og:site_name" content="Jiphyeonjeon">\n    '
        f'<meta property="og:locale" content="{esc_locale}">\n    '
        f'<meta property="og:locale:alternate" content="{alternate_locale}">\n    '
        f'{article_meta}'
        f'<meta name="twitter:card" content="summary_large_image">\n    '
        f'<meta name="twitter:title" content="{esc_title}">\n    '
        f'<meta name="twitter:description" content="{esc_desc}">\n    '
        f'<meta name="twitter:image:alt" content="{esc_title}">\n    '
        f'<meta name="twitter:image" content="{esc_image}">\n    '
        f'<link rel="alternate" type="application/rss+xml" href="/feed.xml">\n    '
        f'{ld_block}'
        f'{css}{stylesheets}'
    )

    # Set data-theme before first paint (mirrors web-ui/index.html): an explicit
    # saved choice wins, else the OS prefers-color-scheme, else dark. Keep this
    # in step with the copy in web-ui/index.html — a reader moving between an
    # SSR page and the SPA must not see the theme change under them.
    theme_script = (
        "<script>(function(){var t=null;"
        "try{t=localStorage.getItem('theme');}catch(e){}"
        "if(t!=='light'&&t!=='dark'){"
        "try{t=window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';}"
        "catch(e){t='dark';}}"
        "document.documentElement.setAttribute('data-theme',t);})();</script>"
    )

    bootstrap = ""
    if blog_post is not None:
        # Match the public API allowlist rather than serializing stored editor
        # metadata. Both bodies let the reader switch views without another GET.
        public_post = PostDetail(**blog_post).model_dump(mode="json")
        payload = json.dumps(
            {"version": 1, "route": {"slug": public_post["slug"]}, "post": public_post},
            ensure_ascii=False,
        )
        for character in ("<", ">", "&", "\u2028", "\u2029"):
            payload = payload.replace(character, f"\\u{ord(character):04x}")
        bootstrap = (
            '<script id="blog-bootstrap" type="application/json">'
            f"{payload}</script>\n    "
        )

    return (
        f'<!doctype html><html lang="{esc_lang}">\n  <head>\n    '
        '<meta charset="UTF-8">\n    '
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n    '
        f"{theme_script}\n    "
        f"{head}\n  </head>\n  <body>\n    "
        f'<div id="root">{article_html}{_SITE_FOOTER_HTML}</div>\n    '
        f"{bootstrap}"
        f"{scripts}\n  </body>\n</html>"
    )


def _render_article(
    post: dict,
    related: list[dict] | None = None,
    prev_post: dict | None = None,
    next_post: dict | None = None,
    published_slugs: set[str] | None = None,
    reading_view: str = "default",
    titles_by_slug: dict[str, str] | None = None,
) -> str:
    """Render the visible <article> body for a single blog post.

    ``related`` and ``prev_post``/``next_post`` add crawlable internal links so
    the post graph is not star-shaped (every post reachable only from the index).
    ``titles_by_slug`` lets the end-of-article series nav name the next chapter.
    """
    title = html.escape(post.get("title", ""), quote=True)
    author = html.escape(post.get("author", ""), quote=True)
    created = html.escape(_format_date(post), quote=True)
    reading_time = post.get("reading_time_min", 1)
    slug = html.escape(post.get("slug", ""), quote=True)
    has_deep_content = bool((post.get("deep_content") or "").strip())
    reading_view_link = ""
    if reading_view == "deep":
        reading_view_link = (
            '<span class="blog-detail-reading-mode">상세 읽기</span>'
            f'<a class="blog-detail-pdf-link blog-detail-reading-link" '
            f'href="/blog/{slug}" aria-label="{title} 쉬운 읽기">쉬운 읽기</a>'
        )
    elif has_deep_content:
        reading_view_link = (
            '<span class="blog-detail-reading-mode">쉬운 읽기</span>'
            f'<a class="blog-detail-pdf-link blog-detail-reading-link" '
            f'href="/blog/{slug}?view=deep" aria-label="{title} 상세 읽기">상세 읽기</a>'
        )
    # Surface the (usually Korean) excerpt as a visible lead paragraph under the
    # title. The reviews' <h1> is the English paper name, so this is the first
    # natural-language Korean text on the page — the on-page signal Korean
    # queries ("… 논문 리뷰/정리") can actually match.
    excerpt = html.escape((post.get("excerpt") or "").strip(), quote=True)
    lead_html = f'<p class="blog-detail-lead">{excerpt}</p>' if excerpt else ""
    # Korean subtitle dek from the stripped leading H1 (only when it adds Korean
    # beyond the English title).
    dek = _leading_h1_text(post.get("content", ""))
    dek_html = (
        f'<h2 class="blog-detail-dek">{html.escape(dek, quote=True)}</h2>'
        if dek and dek != post.get("title", "")
        else ""
    )
    tags_html = "".join(
        f'<span class="blog-tag">{html.escape(str(t), quote=True)}</span>'
        for t in post.get("tags", [])
    )
    # Drop the duplicate leading H1 so the title <h1> is the page's only H1.
    rendered_html = _md.render(_normalize_blog_markdown(post.get("content", ""), ssr_math_fallback=True))

    # Series banner: anchors every member post to its pillar page and to the
    # previous/next post in reading order (crawlable cluster signal). Reading
    # order is filtered to published slugs so the banner never links a 404.
    series_html = ""
    series_next_html = ""
    slug = post.get("slug", "")
    for series_id, series in BLOG_SERIES.items():
        slugs = [
            s
            for s in series["slugs"]
            if published_slugs is None or s in published_slugs
        ]
        if slug not in slugs:
            continue
        position = slugs.index(slug) + 1
        total = len(slugs)
        parts = [
            f'<a href="/blog/series/{html.escape(series_id, quote=True)}">'
            f'{html.escape(series["title"], quote=True)}</a>'
            f" · {position}/{total}편"
        ]
        if position > 1:
            parts.append(
                f'<a rel="prev" href="/blog/{html.escape(slugs[position - 2], quote=True)}">'
                "← 시리즈 이전 글</a>"
            )
        if position < total:
            parts.append(
                f'<a rel="next" href="/blog/{html.escape(slugs[position], quote=True)}">'
                "시리즈 다음 글 →</a>"
            )
        series_html = (
            f'<nav class="blog-series" aria-label="Series">{" ".join(parts)}</nav>'
        )
        series_next_html = _series_next_html(
            series_id, series, slugs, position, titles_by_slug or {}
        )
        break

    def _link(p: dict) -> str:
        return (
            f'/blog/{html.escape(p.get("slug", ""), quote=True)}',
            html.escape(p.get("title", ""), quote=True),
        )

    related_html = ""
    if related:
        rel_items = "".join(
            f'<li><a href="{href}">{name}</a></li>'
            for href, name in (_link(p) for p in related)
        )
        related_html = (
            '<nav class="blog-related" aria-label="Related posts">'
            f"<h2>Related posts</h2><ul>{rel_items}</ul></nav>"
        )

    nav_parts = []
    if prev_post:
        href, name = _link(prev_post)
        nav_parts.append(f'<a class="blog-prev" rel="prev" href="{href}">← {name}</a>')
    if next_post:
        href, name = _link(next_post)
        nav_parts.append(f'<a class="blog-next" rel="next" href="{href}">{name} →</a>')
    # Members already carry their reading-order neighbours in the series nav;
    # a second rel=prev/next block would just repeat the same two links.
    prevnext_html = (
        f'<nav class="blog-prevnext" aria-label="More posts">{"".join(nav_parts)}</nav>'
        if nav_parts and not series_next_html
        else ""
    )

    return (
        '<div class="blog-container"><div class="blog-content">'
        '<div class="blog-detail">'
        f'<h1 class="blog-detail-title">{title}</h1>'
        f"{dek_html}"
        f"{lead_html}"
        '<div class="blog-detail-meta">'
        f'<span class="blog-detail-author">{author}</span>'
        f'<span class="blog-detail-date">{created}</span>'
        f'<span class="blog-detail-reading-time">{reading_time} min read</span>'
        f"{reading_view_link}"
        "</div>"
        f'<div class="blog-detail-tags">{tags_html}</div>'
        f"{series_html}"
        f'<div class="blog-detail-content">{rendered_html}</div>'
        f"{series_next_html}"
        f"{related_html}"
        f"{prevnext_html}"
        "</div></div></div>"
    )


def _series_next_html(
    series_id: str,
    series: dict,
    slugs: list[str],
    position: int,
    titles_by_slug: dict[str, str],
) -> str:
    """End-of-article continuation for a series member (mirrors the SPA nav)."""
    total = len(slugs)
    current = slugs[position - 1]
    hub = f'/blog/series/{html.escape(series_id, quote=True)}'
    comparison = load_geo_comparisons().get(series_id, {})
    stage_title = ""
    for step in comparison.get("reading_guide", []):
        if current in step.get("slugs", []):
            stage_title = step.get("title", "")
            break
    meta = (
        f'<div class="blog-series-next-meta"><a href="{hub}">'
        f'{html.escape(series["title"], quote=True)}</a>'
        f'<span class="blog-series-next-sep" aria-hidden="true">·</span>'
        f"<span>{position}/{total}편</span>"
    )
    if stage_title:
        meta += (
            '<span class="blog-series-next-stage">'
            f"{html.escape(stage_title, quote=True)}</span>"
        )
    meta += "</div>"
    parts = [meta]
    # Primary action first; the previous chapter is tertiary.
    if position < total:
        next_slug = slugs[position]
        label = html.escape(titles_by_slug.get(next_slug) or "시리즈 다음 글", quote=True)
        parts.append(
            '<a class="blog-series-next-primary" rel="next" '
            f'href="/blog/{html.escape(next_slug, quote=True)}">다음: {label} →</a>'
        )
    else:
        compare = (
            f'<a href="{hub}#geo-comparison-title">논문 선택 비교 보기</a>'
            if comparison else ""
        )
        parts.append(
            '<div class="blog-series-next-done"><span>시리즈의 마지막 글입니다</span>'
            f'<a href="{hub}#series-reading-title">시리즈 목차로 돌아가기</a>{compare}</div>'
        )
    if position > 1:
        parts.append(
            '<a class="blog-series-next-prev" rel="prev" '
            f'href="/blog/{html.escape(slugs[position - 2], quote=True)}">← 시리즈 이전 글</a>'
        )
    return (
        '<nav class="blog-series-next" aria-label="시리즈 이어 읽기">'
        f'{"".join(parts)}</nav>'
    )


def _blog_seo_meta(post: dict) -> tuple[str, str]:
    """SEO ``<title>`` + meta description for a post.

    Enriches paper reviews with the reviewed paper's arXiv id and a Korean
    "논문 리뷰" cue so the page matches how people actually search (real GSC
    queries look like ``deepwalk ... arxiv 1403.6652``). The reader-facing
    ``<h1>`` (``post['title']``) is deliberately left untouched — only the
    search-facing title/description carry the keywords. Mirrors
    ``blogSeoMeta`` in the frontend so SSR and client render agree.
    """
    title = post.get("title", "")
    excerpt = (post.get("excerpt") or title).strip()
    ref = _extract_primary_paper_reference(post)
    arxiv_id = ref.get("arxiv_id") if ref else None
    if arxiv_id:
        return f"{title} — arXiv:{arxiv_id} 논문 리뷰 · 집현전", f"arXiv:{arxiv_id} · {excerpt}"[:300]
    if ref:
        return f"{title} 논문 리뷰 · 집현전", excerpt
    return f"{title} | Jiphyeonjeon Blog", excerpt


# ── Endpoints ─────────────────────────────────────────────────────────


@router.api_route("/blog/tags", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def blog_tags_ssr() -> HTMLResponse:
    """Server-render the indexable tag hub.

    Registered BEFORE ``/blog/{slug}``: FastAPI matches routes in registration
    order, so a later literal loses to the earlier path parameter and ``tags``
    would be looked up as a post slug and 404 (verified — that is exactly what
    production did). The SPA paginates client-side; the crawlable body lists
    every merged tag as a link so the hub carries real content.
    """
    with _posts_lock:
        posts = _load_posts()

    tags = sorted(_merged_tag_counts(posts), key=lambda tc: tc[0].casefold())
    items = "".join(
        f'<li><a href="/blog?tag={html.escape(t, quote=True)}">{html.escape(t, quote=True)}</a></li>'
        for t, _ in tags
    )
    description = "집현전의 모든 글을 태그로 찾아볼 수 있습니다."
    body = (
        '<div class="blog-container"><div class="blog-content">'
        '<nav aria-label="breadcrumb"><a href="/blog">Blog</a></nav>'
        "<h1>Tags</h1>"
        f"<p>{html.escape(description, quote=True)}</p>"
        f"<ul>{items}</ul>"
        "</div></div>"
    )
    document = _build_document(
        title="Tags | Jiphyeonjeon Blog",
        description=description,
        canonical=f"{SITE_URL}/blog/tags",
        og_type="website",
        image=OG_DEFAULT_IMAGE,
        json_ld=None,
        article_html=body,
        noindex=not tags,
    )
    return HTMLResponse(content=document, status_code=200)


@router.api_route("/blog/{slug}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def blog_post_ssr(
    slug: str,
    view: str | None = None,
) -> HTMLResponse:
    """Server-render a single blog post.

    Returns a ``noindex`` page with status 410 when the slug was deleted
    (present in the tombstone), or 404 when it is unpublished or unknown.
    """
    with _posts_lock:
        posts = _load_posts()
        deleted = _load_deleted()

    post = next(
        (p for p in posts if p.get("slug") == slug and p.get("published")), None
    )

    if not post:
        if slug in deleted:
            body = (
                '<div class="blog-container">'
                "<p>This post is no longer available.</p></div>"
            )
            document = _build_document(
                title="Post no longer available | Jiphyeonjeon Blog",
                description="This post is no longer available.",
                canonical=f"{SITE_URL}/blog/{slug}",
                og_type="website",
                image=OG_DEFAULT_IMAGE,
                json_ld=None,
                article_html=body,
                noindex=True,
            )
            return HTMLResponse(content=document, status_code=410, headers={"Cache-Control": "no-store"})

        body = '<div class="blog-container"><p>Post not found.</p></div>'
        document = _build_document(
            title="Post not found | Jiphyeonjeon Blog",
            description="Post not found.",
            canonical=f"{SITE_URL}/blog/{slug}",
            og_type="website",
            image=OG_DEFAULT_IMAGE,
            json_ld=None,
            article_html=body,
            noindex=True,
        )
        return HTMLResponse(content=document, status_code=404, headers={"Cache-Control": "no-store"})

    published = [p for p in posts if p.get("published")]
    published = _sort_posts_by_publication(published)
    related = _related_posts(post, published)
    idx = next((i for i, p in enumerate(published) if p.get("slug") == slug), None)
    older = published[idx + 1] if idx is not None and idx + 1 < len(published) else None
    newer = published[idx - 1] if idx is not None and idx - 1 >= 0 else None
    published_by_slug = {p.get("slug", ""): p for p in published}

    displayed_post = dict(post)
    deep_content = post.get("deep_content") or ""
    reading_view = "deep" if view == "deep" and deep_content.strip() else "default"
    if reading_view == "deep":
        displayed_post["content"] = deep_content
        displayed_post["reading_time_min"] = _estimate_reading_time(deep_content)

    lang = _detect_lang(post["title"] + " " + displayed_post.get("content", ""))
    locale = _locale(lang)
    seo_title, seo_description = _blog_seo_meta(post)
    index_deep_view = bool(post.get("index_deep_view") and deep_content.strip())
    canonical = f"{SITE_URL}/blog/{slug}"
    if index_deep_view:
        seo_title += " · 상세 읽기" if reading_view == "deep" else " · 쉬운 읽기"
        if reading_view == "deep":
            canonical += "?view=deep"
    document = _build_document(
        title=seo_title,
        description=seo_description,
        canonical=canonical,
        og_type="article",
        image=_absolute_url(post.get("thumbnail_url")) or OG_DEFAULT_IMAGE,
        json_ld=_blog_posting_graph(
            displayed_post, identity_post=post,
            deep_view=index_deep_view and reading_view == "deep",
        ),
        article_html=_render_article(
            displayed_post,
            related=related,
            prev_post=older,
            next_post=newer,
            published_slugs=set(published_by_slug),
            reading_view=reading_view,
            titles_by_slug={s: p.get("title", "") for s, p in published_by_slug.items()},
        ),
        lang=lang,
        locale=locale,
        published_time=post.get("created_at") or None,
        modified_time=post.get("updated_at") or post.get("created_at") or None,
        blog_post=post,
    )
    return HTMLResponse(content=document, status_code=200, headers={"Cache-Control": "no-store"})


@router.api_route("/blog", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def blog_index_ssr() -> HTMLResponse:
    """Server-render the blog index with links to every published post."""
    with _posts_lock:
        posts = _load_posts()

    published = [p for p in posts if p.get("published")]
    published = _sort_posts_by_publication(published)
    def _index_section(cat: str) -> str:
        label, _desc = BLOG_CATEGORIES[cat]
        cat_posts = [p for p in published if _category_of(p) == cat]
        if not cat_posts:
            return ""
        items = "".join(
            f'<li><a href="/blog/{html.escape(p.get("slug", ""), quote=True)}">'
            f'{html.escape(p.get("title", ""), quote=True)}</a> — '
            f'{html.escape(p.get("excerpt", ""), quote=True)}</li>'
            for p in cat_posts
        )
        return (
            f'<section><h2><a href="/blog/category/{cat}">'
            f"{html.escape(label, quote=True)}</a></h2>"
            f"<ul>{items}</ul></section>"
        )

    # Render every category section so each hub and every published post is
    # one anchor hop from /blog — non-JS crawlers (GPTBot, ClaudeBot, Yeti)
    # discover posts by following <a> links, not by executing the SPA.
    sections = "".join(_index_section(cat) for cat in BLOG_CATEGORIES)

    published_slugs = {p.get("slug", "") for p in published}
    series_links = "".join(
        f'<li><a href="/blog/series/{html.escape(sid, quote=True)}">'
        f'{html.escape(series["title"], quote=True)}</a></li>'
        for sid, series in BLOG_SERIES.items()
        if any(s in published_slugs for s in series["slugs"])
    )
    series_block = (
        f'<nav aria-label="Series"><h2>Series</h2><ul>{series_links}</ul></nav>'
        if series_links
        else ""
    )

    body = (
        '<div class="blog-container"><div class="blog-content">'
        f"<h1>Blog</h1>{series_block}{sections}"
        "</div></div>"
    )

    document = _build_document(
        title=BLOG_TITLE,
        description=BLOG_DESCRIPTION,
        canonical=f"{SITE_URL}/blog",
        og_type="website",
        image=OG_DEFAULT_IMAGE,
        json_ld=_blog_index_graph(published),
        article_html=body,
    )
    return HTMLResponse(content=document, status_code=200)


@router.api_route("/blog/series/{series_id}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def blog_series_ssr(series_id: str) -> HTMLResponse:
    """Server-render a series pillar page in reading order.

    Unknown series 404. A series whose posts are all unpublished is served
    ``noindex`` so a thin hub is not indexed.
    """
    series = BLOG_SERIES.get(series_id)
    if series is None:
        body = '<div class="blog-container"><p>Series not found.</p></div>'
        document = _build_document(
            title="Series not found | Jiphyeonjeon Blog",
            description="Series not found.",
            canonical=f"{SITE_URL}/blog",
            og_type="website",
            image=OG_DEFAULT_IMAGE,
            json_ld=None,
            article_html=body,
            noindex=True,
        )
        return HTMLResponse(content=document, status_code=404)

    with _posts_lock:
        posts = _load_posts()

    by_slug = {p.get("slug"): p for p in posts if p.get("published")}
    ordered = [by_slug[s] for s in series["slugs"] if s in by_slug]
    comparison = load_geo_comparisons().get(series_id, {})

    reading_list = _series_reading_list_html(ordered, comparison)
    total_minutes = _series_total_minutes(ordered)
    cat = _category_of(ordered[0]) if ordered else None
    cat_label = "Engineering" if cat == "engineering" else "Paper Review" if cat else ""
    cat_html = f'<span class="blog-row-cat" data-cat="{cat}">{cat_label}</span>' if cat else ""
    # Count and minutes share one basis: published chapters.
    meta_html = (
        f'<p class="blog-series-meta">{cat_html}<span>{len(ordered)}편'
        f'{f" · 약 {total_minutes}분" if total_minutes is not None else ""}</span></p>'
        if ordered else ""
    )
    time_html = ""
    if ordered:
        first = ordered[0]
        first_url = f'/blog/{html.escape(first["slug"], quote=True)}'
        first_minutes = first.get("reading_time_min")
        time_html = (
            f'<span class="blog-series-start-time"> · {first_minutes}분</span>'
            if isinstance(first_minutes, (int, float)) else ""
        )
        first_excerpt = _first_sentence(first.get("excerpt") or "")
        thumb_url = _effective_thumbnail(first)
        # First-fold cover: never lazy, it is the page's LCP candidate.
        media_html = (
            f'<div class="blog-series-start-media"><img src="{html.escape(thumb_url, quote=True)}" '
            'alt="" decoding="async"></div>'
            if thumb_url else ""
        )
        spotlight = (
            f'<h2 id="series-start-title"><a href="{first_url}">{html.escape(first["title"])}</a></h2>'
            f'<p class="blog-series-start-excerpt">{html.escape(first_excerpt)}</p>'
            f'<a class="blog-series-start-cta" href="{first_url}">첫 글 읽기 '
            '<span aria-hidden="true">→</span></a>'
        )
    else:
        media_html = ""
        spotlight = (
            '<h2 id="series-start-title">첫 글부터 차근차근</h2>'
            '<p role="status">아직 공개된 시리즈 글이 없습니다.</p>'
        )
    nav_targets = [
        '<a href="#series-reading-title">추천 읽기 순서</a>',
        '<a href="#geo-comparison-title">논문 선택 비교</a>' if comparison else "",
        '<a href="#series-evidence-title">상세 근거와 출처</a>' if comparison else "",
    ]
    nav_targets = [t for t in nav_targets if t]
    series_nav = (
        f'<nav class="blog-series-nav" aria-label="시리즈 바로가기">{"".join(nav_targets)}</nav>'
        if len(nav_targets) >= 2 else ""
    )
    intro = _first_sentence(series["description"])
    reading_intro = (
        f'<p class="blog-series-reading-intro">'
        f'{html.escape(series["description"].split(". ", 1)[1]) if ". " in series["description"] else ""}</p>'
        if not comparison else ""
    )
    body = (
        '<div class="blog-container blog-series-page"><main id="main" class="blog-content">'
        '<header class="blog-header">'
        '<nav aria-label="breadcrumb"><a href="/blog">← 블로그로</a></nav>'
        f'<h1 class="blog-title">{html.escape(series["title"], quote=True)}</h1>'
        f'<p class="blog-subtitle">{html.escape(intro)}</p>{meta_html}</header>'
        '<section class="blog-series-start" aria-labelledby="series-start-title">'
        '<div class="blog-series-start-text">'
        f'<p class="blog-series-kicker">여기서 시작하세요{time_html}</p>{spotlight}</div>{media_html}</section>'
        f"{_series_reading_guide_html(comparison, by_slug)}"
        f"{series_nav}"
        '<section class="blog-series-reading" aria-labelledby="series-reading-title">'
        '<h2 id="series-reading-title">추천 읽기 순서</h2>'
        f'{reading_intro}'
        f'{reading_list}</section>'
        f"{_series_comparison_html(comparison, by_slug)}"
        f"{_series_comparison_html(comparison, by_slug, detailed=True)}"
        "</main></div>"
    )
    lang = _detect_lang(f'{series["title"]} {series["description"]}')
    document = _build_document(
        title=f'{series["title"]} | Jiphyeonjeon Blog',
        description=series["description"],
        canonical=f"{SITE_URL}/blog/series/{series_id}",
        og_type="website",
        image=OG_DEFAULT_IMAGE,
        json_ld=_series_graph(series_id, series["title"], series["description"], ordered),
        article_html=body,
        stylesheets=_series_stylesheets(),
        noindex=not ordered,
        lang=lang,
        locale=_locale(lang),
    )
    return HTMLResponse(content=document, status_code=200)


@router.api_route("/blog/category/{category}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def blog_category_ssr(category: str) -> HTMLResponse:
    """Server-render an indexable category hub (paper-review / engineering).

    Unknown categories 404. An empty (but valid) category is served ``noindex``
    so a thin hub is not indexed until it has posts.
    """
    meta = BLOG_CATEGORIES.get(category)
    if meta is None:
        body = '<div class="blog-container"><p>Category not found.</p></div>'
        document = _build_document(
            title="Category not found | Jiphyeonjeon Blog",
            description="Category not found.",
            canonical=f"{SITE_URL}/blog",
            og_type="website",
            image=OG_DEFAULT_IMAGE,
            json_ld=None,
            article_html=body,
            noindex=True,
        )
        return HTMLResponse(content=document, status_code=404)

    label, description = meta
    with _posts_lock:
        posts = _load_posts()

    published = [p for p in posts if p.get("published") and _category_of(p) == category]
    published = _sort_posts_by_publication(published)

    items = "".join(
        f'<li><a href="/blog/{html.escape(p.get("slug", ""), quote=True)}">'
        f'{html.escape(p.get("title", ""), quote=True)}</a> — '
        f'{html.escape(p.get("excerpt", ""), quote=True)}</li>'
        for p in published
    )
    body = (
        '<div class="blog-container"><div class="blog-content">'
        '<nav aria-label="breadcrumb"><a href="/blog">Blog</a></nav>'
        f"<h1>{html.escape(label, quote=True)}</h1>"
        f"<p>{html.escape(description, quote=True)}</p>"
        f"<ul>{items}</ul>"
        "</div></div>"
    )
    document = _build_document(
        title=f"{label} | Jiphyeonjeon Blog",
        description=description,
        canonical=f"{SITE_URL}/blog/category/{category}",
        og_type="website",
        image=OG_DEFAULT_IMAGE,
        json_ld=_category_graph(category, label, description, published),
        article_html=body,
        noindex=not published,
    )
    return HTMLResponse(content=document, status_code=200)


@router.api_route("/sitemap.xml", methods=["GET", "HEAD"])
async def sitemap() -> Response:
    """Return an XML sitemap of public URLs and published content."""
    with _posts_lock:
        posts = _load_posts()

    published = [p for p in posts if p.get("published")]

    # Site-wide freshness signal for the non-post hub rows (home/blog/category/
    # series): the most recent post date. Helps crawlers re-fetch hubs when
    # any post changes.
    site_lastmod = max((_format_date(p) for p in published), default="")
    lm = f"<lastmod>{site_lastmod}</lastmod>" if site_lastmod else ""

    rows = [
        f"  <url><loc>{SITE_URL}/</loc>{lm}<priority>1.0</priority></url>",
        f"  <url><loc>{SITE_URL}/introduce/</loc>{lm}<priority>0.8</priority></url>",
        f"  <url><loc>{SITE_URL}/ko/introduce/</loc>{lm}<priority>0.8</priority></url>",
        f"  <url><loc>{SITE_URL}/blog</loc>{lm}<priority>0.8</priority></url>",
        # Tag hub: indexable (#220) but invisible to crawlers until listed here.
        f"  <url><loc>{SITE_URL}/blog/tags</loc>{lm}<priority>0.6</priority></url>",
    ]
    # /llms.txt and /llms-full.txt are deliberately absent. llmstxt.org defines
    # discovery by the well-known root path, the way robots.txt is found, so a
    # sitemap row buys nothing — and a sitemap is a catalogue of pages meant to
    # be indexed, which these are not. Listing them only spent crawl budget and
    # filled Search Console's "discovered, not indexed" bucket, hiding the posts
    # that genuinely were not indexed. Both paths are still served at 200.
    # Category hubs — only list a hub that has at least one published post.
    cats_present = {_category_of(p) for p in published}
    for cat in BLOG_CATEGORIES:
        if cat in cats_present:
            rows.append(
                f"  <url><loc>{SITE_URL}/blog/category/{cat}</loc>"
                f"{lm}<priority>0.7</priority></url>"
            )
    # Series hubs — same nonempty rule as category hubs.
    published_slugs = {p.get("slug", "") for p in published}
    for sid, series in BLOG_SERIES.items():
        if any(s in published_slugs for s in series["slugs"]):
            rows.append(
                f"  <url><loc>{SITE_URL}/blog/series/{sid}</loc>"
                f"{lm}<priority>0.7</priority></url>"
            )
    for post in published:
        try:
            slug = post.get("slug")
            if not slug:
                continue
            lastmod = _format_date(post)
            # Google image sitemap: surface the post thumbnail for Image search.
            image_abs = _absolute_url(post.get("thumbnail_url"))
            image_tag = (
                f"<image:image><image:loc>{html.escape(image_abs)}</image:loc></image:image>"
                if image_abs
                else ""
            )
            rows.append(
                f"  <url><loc>{SITE_URL}/blog/{html.escape(slug)}</loc>"
                f"<lastmod>{lastmod}</lastmod><priority>0.7</priority>{image_tag}</url>"
            )
            if post.get("index_deep_view") and (post.get("deep_content") or "").strip():
                rows.append(
                    f"  <url><loc>{SITE_URL}/blog/{html.escape(slug)}?view=deep</loc>"
                    f"<lastmod>{lastmod}</lastmod><priority>0.7</priority>{image_tag}</url>"
                )
        except Exception:  # noqa: BLE001 - one bad post must not 500 the sitemap
            logger.warning("Skipping post in sitemap due to error", exc_info=True)
            continue

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
        ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
        + "\n".join(rows)
        + "\n</urlset>"
    )
    return Response(
        content=body,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.api_route("/feed.xml", methods=["GET", "HEAD"])
async def feed() -> Response:
    """Return an RSS 2.0 feed of the 30 newest published posts."""
    with _posts_lock:
        posts = _load_posts()

    published = [p for p in posts if p.get("published")]
    published = _sort_posts_by_publication(published)

    items = []
    for post in published[:30]:
        slug = post.get("slug", "")
        link = f"{SITE_URL}/blog/{slug}"
        pub_date = format_datetime(_parse_dt(post.get("created_at", "")))
        cat_label = BLOG_CATEGORIES.get(_category_of(post), ("", ""))[0]
        category_tag = f"      <category>{html.escape(cat_label)}</category>\n" if cat_label else ""
        items.append(
            "    <item>\n"
            f"      <title>{html.escape(post.get('title', ''))}</title>\n"
            f"      <link>{html.escape(link)}</link>\n"
            f'      <guid isPermaLink="true">{html.escape(link)}</guid>\n'
            f"      <pubDate>{pub_date}</pubDate>\n"
            f"{category_tag}"
            f"      <description><![CDATA[{post.get('excerpt', '')}]]></description>\n"
            "    </item>"
        )

    last_build = (
        format_datetime(_parse_dt(published[0].get("created_at", ""))) if published else ""
    )
    last_build_tag = f"    <lastBuildDate>{last_build}</lastBuildDate>\n" if last_build else ""
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        "    <title>Jiphyeonjeon Blog</title>\n"
        f"    <link>{SITE_URL}/blog</link>\n"
        f'    <atom:link href="{SITE_URL}/feed.xml" rel="self" type="application/rss+xml"/>\n'
        f"    <description>{html.escape(BLOG_DESCRIPTION)}</description>\n"
        "    <language>ko</language>\n"
        f"{last_build_tag}"
        + "\n".join(items)
        + "\n  </channel>\n</rss>"
    )
    return Response(
        content=body,
        media_type="application/rss+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.api_route("/llms.txt", methods=["GET", "HEAD"])
async def llms_txt() -> Response:
    """Return an llmstxt.org-format guide to the site for AI engines."""
    with _posts_lock:
        posts = _load_posts()

    published = [p for p in posts if p.get("published")]
    published = _sort_posts_by_publication(published)

    def _blog_line(post: dict) -> str:
        title = post.get("title", "")
        excerpt = post.get("excerpt", "")
        slug = post.get("slug", "")
        date = _format_date(post)
        return f"- [{title}]({SITE_URL}/blog/{slug}) ({date}): {excerpt}"

    # Group the blog list and the category-hub links by category (non-empty only).
    cat_sections: list[str] = []
    key_page_cats: list[str] = []
    for cat, (label, _desc) in BLOG_CATEGORIES.items():
        cat_posts = [p for p in published if _category_of(p) == cat and p.get("slug")]
        if not cat_posts:
            continue
        key_page_cats.append(
            f"- [{label}]({SITE_URL}/blog/category/{cat}): {label.lower()} posts"
        )
        lines = "\n".join(_blog_line(p) for p in cat_posts)
        cat_sections.append(f"### {label}\n{lines}")

    blog_section = "\n\n".join(cat_sections)
    key_pages = "\n".join(
        [
            f"- [Home / Search]({SITE_URL}/): paper search interface",
            f"- [About Jiphyeonjeon — English]({SITE_URL}/introduce/): AI paper search, "
            "multi-paper review, source-grounded claim verification, and access details",
            f"- [집현전 소개 — 한국어]({SITE_URL}/ko/introduce/): AI 논문 검색, "
            "다중 논문 리뷰, 원문 근거 검증과 이용 방법",
            f"- [Blog]({SITE_URL}/blog): research notes and write-ups",
            *key_page_cats,
        ]
    )

    # Series hubs (pillar pages) — derived from BLOG_SERIES so new series are
    # picked up automatically. Each line names the hub, its size, and the
    # recommended reading order so answer engines can cite the collection.
    published_slugs = {p.get("slug") for p in published}
    series_lines: list[str] = []
    for series_id, series in BLOG_SERIES.items():
        live_slugs = [s for s in series["slugs"] if s in published_slugs]
        if not live_slugs:
            continue
        series_lines.append(
            f"- [{series['title']}]({SITE_URL}/blog/series/{series_id}) "
            f"({len(live_slugs)} posts, in recommended reading order): "
            f"{series['description']}"
        )
    series_section = "\n".join(series_lines)

    body = (
        "# 집현전 (Jiphyeonjeon)\n"
        "\n"
        f"> {LLMS_DESCRIPTION}\n"
        "\n"
        "## About\n"
        "Jiphyeonjeon (집현전) is an AI-powered academic paper search and "
        "multi-agent deep-review web app for researchers. It is a modern software "
        "tool and is unrelated to the 15th-century Joseon-dynasty royal institute "
        "(Hall of Worthies) of the same name.\n"
        "Source: https://github.com/KimJiSeong1994/PaperReview\n"
        "\n"
        "## Capabilities\n"
        "- Academic paper search across arXiv, Google Scholar, OpenAlex, DBLP, "
        "Connected Papers, and Korean academic search\n"
        "- Multi-paper AI review that compares common findings, conflicts, and methods\n"
        "- Source-grounded claim verification that distinguishes quotation, paraphrase, "
        "inference, and unverified claims\n"
        "- Study curriculum builder\n"
        "- Citation graph explorer\n"
        "\n"
        "## Review methodology\n"
        "Jiphyeonjeon searches broadly, reviews papers side by side, and checks important "
        "interpretations against source passages before presenting follow-up reading. "
        f"See the product explanation in [English]({SITE_URL}/introduce/) or "
        f"[한국어]({SITE_URL}/ko/introduce/), and the "
        f"[public CausalRAG2 evidence example]({SITE_URL}/blog/"
        "causalrag2-hugrag-hierarchical-causal-gating).\n"
        "\n"
        "## Claude access\n"
        "The public product explanation and published paper reviews are readable without "
        "sign-in. Jiphyeonjeon Agent is a separate, optional open-source extension that "
        "lets Claude users invoke paper search, review, bookmark, and curriculum features "
        "inside a Claude conversation.\n"
        f"- [Claude extension overview]({SITE_URL}/introduce/#claude)\n"
        "- [Jiphyeonjeon Agent source](https://github.com/KimJiSeong1994/"
        "jiphyeonjeon-agent)\n"
        "\n"
        "## Key pages\n"
        f"{key_pages}\n"
        "\n"
        "## Series\n"
        f"{series_section}\n"
        "\n"
        "## Blog\n"
        f"{blog_section}\n"
        "\n"
        "## Optional\n"
        f"- [RSS feed]({SITE_URL}/feed.xml)\n"
        f"- [Sitemap]({SITE_URL}/sitemap.xml)\n"
        f"- [Full blog text index]({SITE_URL}/llms-full.txt)\n"
    )
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )


_HEADING_RE = re.compile(r"^(#{1,5}) ")
_THEMATIC_BREAK_RE = re.compile(r"^\s*-{3,}\s*$")


def _demote_headings_and_rules(markdown: str) -> str:
    """Demote ATX headings one level and rewrite ``---`` breaks as ``***``.

    In llms-full.txt each post's title is the only ``#`` heading and ``---``
    is the only post separator, so a naive chunker can split the corpus at
    post boundaries and keep every chunk attributable to its canonical URL.
    Body headings therefore move down one level (capped at ``######``) and
    in-body thematic breaks become ``***``. Fenced code blocks are untouched.
    """
    out: list[str] = []
    in_fence = False
    for line in markdown.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence:
            if _HEADING_RE.match(line):
                line = "#" + line
            elif _THEMATIC_BREAK_RE.match(line):
                line = "***"
        out.append(line)
    return "\n".join(out)


@router.api_route("/llms-full.txt", methods=["GET", "HEAD"])
async def llms_full_txt() -> Response:
    """Return the complete markdown body of every published blog post.

    ``/blog/{slug}`` remains the canonical indexable HTML page. This text feed is
    an auxiliary discovery/retrieval surface for AI search crawlers and internal
    retrieval systems that prefer a compact plaintext corpus. Drafts and deleted
    posts are excluded so unpublished content never leaks into search indexes.
    Each post is one ``# {title}`` section separated by ``---`` lines; body
    headings are demoted so those two markers stay unambiguous chunk
    boundaries (see ``_demote_headings_and_rules``).
    """
    with _posts_lock:
        posts = _load_posts()

    published = [p for p in posts if p.get("published") and p.get("slug")]
    published = _sort_posts_by_publication(published)

    sections: list[str] = [
        "# Jiphyeonjeon published blog full-text index",
        "",
        (
            "Canonical HTML pages live under /blog/{slug}; this file mirrors only "
            "published post text to help search and AI retrieval systems discover "
            "the complete article bodies."
        ),
    ]
    for post in published:
        title = post.get("title", "")
        slug = post.get("slug", "")
        excerpt = post.get("excerpt", "")
        tags = ", ".join(str(t) for t in post.get("tags", []))
        category = _category_of(post)
        date = _format_date(post)
        canonical = f"{SITE_URL}/blog/{slug}"
        content = _demote_headings_and_rules(
            _normalize_blog_markdown(post.get("content", "")).strip()
        )
        sections.append(
            "\n".join(
                [
                    "",
                    "---",
                    "",
                    f"# {title}",
                    "",
                    f"- Canonical: {canonical}",
                    f"- Date: {date}",
                    f"- Category: {category}",
                    f"- Tags: {tags}",
                    f"- Excerpt: {excerpt}",
                    "",
                    content,
                ]
            )
        )

    body = "\n".join(sections).rstrip() + "\n"
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )
