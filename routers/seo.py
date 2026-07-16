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

from .blog import _load_deleted, _load_posts, _posts_lock

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

# Maintainer profile links shown site-wide for service credibility. Keep in
# sync with web-ui/src/components/SiteFooter.tsx and structuredData.ts.
GITHUB_PROFILE_URL = "https://github.com/KimJiSeong1994"
LINKEDIN_PROFILE_URL = "https://www.linkedin.com/in/jiseong-kim-868218193/"

# Pre-hydration footer appended inside #root on SSR pages so non-JS crawlers
# and users see the same maintainer links the React SiteFooter renders.
_SITE_FOOTER_HTML = (
    '<footer class="site-footer">'
    '<span class="site-footer-brand">© Jiphyeonjeon (집현전)</span>'
    '<nav class="site-footer-links" aria-label="Maintainer profiles">'
    f'<a href="{GITHUB_PROFILE_URL}" target="_blank" rel="me noopener noreferrer">GitHub</a>'
    '<span class="site-footer-sep" aria-hidden="true">·</span>'
    f'<a href="{LINKEDIN_PROFILE_URL}" target="_blank" rel="me noopener noreferrer">LinkedIn</a>'
    "</nav></footer>"
)

# Ordered blog series hubs (pillar pages). Keys are the /blog/series/{id}
# path segment; ``slugs`` is the recommended reading order. Keep in sync with
# web-ui/src/seo/series.ts (shared contract, like the JSON-LD builders).
BLOG_SERIES: dict[str, dict] = {
    "gnn": {
        "title": "GNN 논문 리뷰 시리즈",
        "description": (
            "그래프 신경망(GNN)의 핵심 논문 11편을 랜덤워크 임베딩부터 "
            "메시지 패싱, 어텐션, 표현력, 이종 그래프, 설명가능성, 강한 베이스라인 재평가까지 "
            "권장 순서로 깊이 있게 읽는 한국어 딥리뷰 시리즈. 스탠퍼드 "
            "CS224W(Machine Learning with Graphs) 커리큘럼과 나란히 읽을 "
            "수 있도록 구성했다."
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
            "단어 의미의 시간적 변화를 임베딩으로 추적하는 동적 단어 임베딩"
            "(Dynamic Word Embeddings)의 핵심 논문 5편을 변화점 탐지부터 "
            "의미 변화의 통계 법칙, 베이지안 공동 학습, 공동 행렬 분해, "
            "확률적 생성 모델까지 시간순으로 깊이 있게 읽는 한국어 딥리뷰 "
            "시리즈. 시간 구간별로 따로 학습한 임베딩을 사후에 맞추던 정렬 "
            "문제가 학습 안으로, 다시 모델 설계 안으로 흡수되는 흐름을 "
            "계보로 따라간다."
        ),
        "slugs": [
            "statistically-significant-detection-linguistic-change-review",
            "diachronic-word-embeddings-statistical-laws-semantic-change-review",
            "dynamic-word-embeddings-bayesian-skip-gram-review",
            "dynamic-word-embeddings-evolving-semantic-discovery-review-2026",
            "dynamic-bernoulli-embeddings-language-evolution-review-2026",
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
    """
    return re.sub(
        r"\$\$([\s\S]*?)\$\$",
        lambda m: f"$$\n{m.group(1).strip()}\n$$",
        content,
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
_QUOTED_TITLE_RE = re.compile(r'"([^"]+)"')
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")


def _extract_primary_paper_reference(post: dict) -> dict | None:
    """Return the reviewed paper's citation parsed from the post content.

    Mirrors ``extractPrimaryPaperReference`` in the frontend. Returns a dict
    with ``title``, ``authors`` and optional ``year``/``arxiv_id``/``doi``/
    ``url``, or ``None`` when no citation can be recovered.
    """
    content = post.get("content", "") or ""
    match = _PAPER_BLOCK_RE.search(content)
    if not match and post.get("category") != "paper-review":
        return None

    block = (match.group(1) if match else content[:1000]).strip()
    if not block:
        return None

    arxiv_match = _ARXIV_RE.search(block)
    arxiv_id = arxiv_match.group(1).strip().rstrip(".,;:") if arxiv_match else None
    doi_match = _DOI_URL_RE.search(block) or _DOI_TEXT_RE.search(block)
    doi = doi_match.group(1).rstrip(".,;:") if doi_match else None
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
        ref["arxiv_id"] = arxiv_id
        ref["url"] = f"https://arxiv.org/abs/{arxiv_id}"
    elif doi:
        ref["url"] = f"https://doi.org/{doi}"
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
        "alternateName": "집현전",
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
            GITHUB_PROFILE_URL,
            LINKEDIN_PROFILE_URL,
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


def _blog_posting_graph(post: dict) -> dict:
    """Return the @graph for a single BlogPosting page."""
    title = post.get("title", "")
    slug = post.get("slug", "")
    excerpt = post.get("excerpt", "")
    author = post.get("author", "")
    created_at = post.get("created_at", "")
    updated_at = post.get("updated_at") or created_at
    tags = post.get("tags", [])
    content = post.get("content", "")
    url = f"https://jiphyeonjeon.kr/blog/{slug}"
    section = "Paper Reviews" if post.get("category") == "paper-review" else "Engineering"

    image = _absolute_url(post.get("thumbnail_url")) or OG_DEFAULT_IMAGE

    posting = {
        "@type": "BlogPosting",
        "headline": title,
        "description": excerpt,
        "author": {"@type": "Person", "name": author},
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

    membership = _series_membership(slug)
    if membership:
        series_id, _position = membership
        posting["isPartOf"] = {
            "@id": f"https://jiphyeonjeon.kr/blog/series/{series_id}#collection"
        }

    graph = [_organization_node(), posting]
    # Link the review to the paper it discusses so answer engines can connect
    # "what does <paper> propose?" queries to this post as a citable source.
    ref = _extract_primary_paper_reference(post)
    if ref and ref.get("url"):
        posting["about"] = {"@id": ref["url"]}
        posting["citation"] = {"@id": ref["url"]}
        graph.append(_scholarly_article_node(ref))
    graph.append(_breadcrumb(title, slug))

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
    """Return the @graph for a category hub page (CollectionPage)."""
    url = f"https://jiphyeonjeon.kr/blog/category/{category}"
    blog_posts = [
        {
            "@type": "BlogPosting",
            "headline": p.get("title", ""),
            "url": f"https://jiphyeonjeon.kr/blog/{p.get('slug', '')}",
        }
        for p in posts[:20]
    ]
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
                "hasPart": blog_posts,
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


# ── HTML document builder ─────────────────────────────────────────────


def _json_ld_script(obj: dict) -> str:
    """Serialize a JSON-LD object into a safe <script> tag."""
    payload = json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")
    return f'<script type="application/ld+json">{payload}</script>'


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
        f'<meta property="og:site_name" content="Jiphyeonjeon">\n    '
        f'<meta property="og:locale" content="{esc_locale}">\n    '
        f'<meta property="og:locale:alternate" content="{alternate_locale}">\n    '
        f'<meta name="twitter:card" content="summary_large_image">\n    '
        f'<meta name="twitter:title" content="{esc_title}">\n    '
        f'<meta name="twitter:description" content="{esc_desc}">\n    '
        f'<meta name="twitter:image" content="{esc_image}">\n    '
        f'<link rel="alternate" type="application/rss+xml" href="/feed.xml">\n    '
        f'{ld_block}'
        f'{css}'
    )

    # Set data-theme before first paint (mirrors web-ui/index.html): the saved
    # choice, else dark by default; light is opt-in via the header toggle.
    theme_script = (
        "<script>(function(){try{var t=localStorage.getItem('theme');"
        "if(t!=='light'&&t!=='dark'){t='dark';}"
        "document.documentElement.setAttribute('data-theme',t);}"
        "catch(e){document.documentElement.setAttribute('data-theme','dark');}})();</script>"
    )

    return (
        f'<!doctype html><html lang="{esc_lang}">\n  <head>\n    '
        '<meta charset="UTF-8">\n    '
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n    '
        f"{theme_script}\n    "
        f"{head}\n  </head>\n  <body>\n    "
        f'<div id="root">{article_html}{_SITE_FOOTER_HTML}</div>\n    '
        f"{scripts}\n  </body>\n</html>"
    )


def _render_article(
    post: dict,
    related: list[dict] | None = None,
    prev_post: dict | None = None,
    next_post: dict | None = None,
    published_slugs: set[str] | None = None,
) -> str:
    """Render the visible <article> body for a single blog post.

    ``related`` and ``prev_post``/``next_post`` add crawlable internal links so
    the post graph is not star-shaped (every post reachable only from the index).
    """
    title = html.escape(post.get("title", ""), quote=True)
    author = html.escape(post.get("author", ""), quote=True)
    created = html.escape(_format_date(post), quote=True)
    reading_time = post.get("reading_time_min", 1)
    # Surface the (usually Korean) excerpt as a visible lead paragraph under the
    # title. The reviews' <h1> is the English paper name, so this is the first
    # natural-language Korean text on the page — the on-page signal Korean
    # queries ("… 논문 리뷰/정리") can actually match.
    excerpt = html.escape((post.get("excerpt") or "").strip(), quote=True)
    lead_html = f'<p class="blog-detail-lead">{excerpt}</p>' if excerpt else ""
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
    prevnext_html = (
        f'<nav class="blog-prevnext" aria-label="More posts">{"".join(nav_parts)}</nav>'
        if nav_parts
        else ""
    )

    return (
        '<div class="blog-container"><div class="blog-content">'
        '<div class="blog-detail">'
        f'<h1 class="blog-detail-title">{title}</h1>'
        f"{lead_html}"
        '<div class="blog-detail-meta">'
        f'<span class="blog-detail-author">{author}</span>'
        f'<span class="blog-detail-date">{created}</span>'
        f'<span class="blog-detail-reading-time">{reading_time} min read</span>'
        "</div>"
        f'<div class="blog-detail-tags">{tags_html}</div>'
        f"{series_html}"
        f'<div class="blog-detail-content">{rendered_html}</div>'
        f"{related_html}"
        f"{prevnext_html}"
        "</div></div></div>"
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


@router.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_post_ssr(slug: str) -> HTMLResponse:
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
            return HTMLResponse(content=document, status_code=410)

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
        return HTMLResponse(content=document, status_code=404)

    published = [p for p in posts if p.get("published")]
    published.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    related = _related_posts(post, published)
    idx = next((i for i, p in enumerate(published) if p.get("slug") == slug), None)
    older = published[idx + 1] if idx is not None and idx + 1 < len(published) else None
    newer = published[idx - 1] if idx is not None and idx - 1 >= 0 else None

    lang = _detect_lang(post["title"] + " " + post.get("content", ""))
    locale = _locale(lang)
    seo_title, seo_description = _blog_seo_meta(post)
    document = _build_document(
        title=seo_title,
        description=seo_description,
        canonical=f"{SITE_URL}/blog/{slug}",
        og_type="article",
        image=_absolute_url(post.get("thumbnail_url")) or OG_DEFAULT_IMAGE,
        json_ld=_blog_posting_graph(post),
        article_html=_render_article(
            post,
            related=related,
            prev_post=older,
            next_post=newer,
            published_slugs={p.get("slug", "") for p in published},
        ),
        lang=lang,
        locale=locale,
    )
    return HTMLResponse(content=document, status_code=200)


@router.get("/blog", response_class=HTMLResponse)
async def blog_index_ssr() -> HTMLResponse:
    """Server-render the blog index with links to every published post."""
    with _posts_lock:
        posts = _load_posts()

    published = [p for p in posts if p.get("published")]
    published.sort(key=lambda p: p.get("created_at", ""), reverse=True)
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


@router.get("/blog/series/{series_id}", response_class=HTMLResponse)
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

    items = "".join(
        f'<li><a href="/blog/{html.escape(p.get("slug", ""), quote=True)}">'
        f'{html.escape(p.get("title", ""), quote=True)}</a> — '
        f'{html.escape(p.get("excerpt", ""), quote=True)}</li>'
        for p in ordered
    )
    body = (
        '<div class="blog-container"><div class="blog-content">'
        '<nav aria-label="breadcrumb"><a href="/blog">Blog</a></nav>'
        f'<h1>{html.escape(series["title"], quote=True)}</h1>'
        f'<p>{html.escape(series["description"], quote=True)}</p>'
        f"<ol>{items}</ol>"
        "</div></div>"
    )
    document = _build_document(
        title=f'{series["title"]} | Jiphyeonjeon Blog',
        description=series["description"],
        canonical=f"{SITE_URL}/blog/series/{series_id}",
        og_type="website",
        image=OG_DEFAULT_IMAGE,
        json_ld=_series_graph(series_id, series["title"], series["description"], ordered),
        article_html=body,
        noindex=not ordered,
    )
    return HTMLResponse(content=document, status_code=200)


@router.get("/blog/category/{category}", response_class=HTMLResponse)
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
    published.sort(key=lambda p: p.get("created_at", ""), reverse=True)

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


@router.get("/sitemap.xml")
async def sitemap() -> Response:
    """Return an XML sitemap of public URLs (home, blog index, published posts)."""
    with _posts_lock:
        posts = _load_posts()

    published = [p for p in posts if p.get("published")]

    rows = [
        f"  <url><loc>{SITE_URL}/</loc><priority>1.0</priority></url>",
        f"  <url><loc>{SITE_URL}/blog</loc><priority>0.8</priority></url>",
        f"  <url><loc>{SITE_URL}/llms.txt</loc><priority>0.5</priority></url>",
        f"  <url><loc>{SITE_URL}/llms-full.txt</loc><priority>0.5</priority></url>",
    ]
    # Category hubs — only list a hub that has at least one published post.
    cats_present = {_category_of(p) for p in published}
    for cat in BLOG_CATEGORIES:
        if cat in cats_present:
            rows.append(
                f"  <url><loc>{SITE_URL}/blog/category/{cat}</loc>"
                f"<priority>0.7</priority></url>"
            )
    # Series hubs — same nonempty rule as category hubs.
    published_slugs = {p.get("slug", "") for p in published}
    for sid, series in BLOG_SERIES.items():
        if any(s in published_slugs for s in series["slugs"]):
            rows.append(
                f"  <url><loc>{SITE_URL}/blog/series/{sid}</loc>"
                f"<priority>0.7</priority></url>"
            )
    for post in published:
        try:
            slug = post.get("slug")
            if not slug:
                continue
            lastmod = _format_date(post)
            rows.append(
                f"  <url><loc>{SITE_URL}/blog/{html.escape(slug)}</loc>"
                f"<lastmod>{lastmod}</lastmod><priority>0.7</priority></url>"
            )
        except Exception:  # noqa: BLE001 - one bad post must not 500 the sitemap
            logger.warning("Skipping post in sitemap due to error", exc_info=True)
            continue

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(rows)
        + "\n</urlset>"
    )
    return Response(
        content=body,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/feed.xml")
async def feed() -> Response:
    """Return an RSS 2.0 feed of the 30 newest published posts."""
    with _posts_lock:
        posts = _load_posts()

    published = [p for p in posts if p.get("published")]
    published.sort(key=lambda p: p.get("created_at", ""), reverse=True)

    items = []
    for post in published[:30]:
        slug = post.get("slug", "")
        link = f"{SITE_URL}/blog/{slug}"
        pub_date = format_datetime(_parse_dt(post.get("created_at", "")))
        items.append(
            "    <item>\n"
            f"      <title>{html.escape(post.get('title', ''))}</title>\n"
            f"      <link>{html.escape(link)}</link>\n"
            f'      <guid isPermaLink="true">{html.escape(link)}</guid>\n'
            f"      <pubDate>{pub_date}</pubDate>\n"
            f"      <description><![CDATA[{post.get('excerpt', '')}]]></description>\n"
            "    </item>"
        )

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "  <channel>\n"
        "    <title>Jiphyeonjeon Blog</title>\n"
        f"    <link>{SITE_URL}/blog</link>\n"
        f"    <description>{html.escape(BLOG_DESCRIPTION)}</description>\n"
        "    <language>en</language>\n"
        + "\n".join(items)
        + "\n  </channel>\n</rss>"
    )
    return Response(
        content=body,
        media_type="application/rss+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/llms.txt")
async def llms_txt() -> Response:
    """Return an llmstxt.org-format guide to the site for AI engines."""
    with _posts_lock:
        posts = _load_posts()

    published = [p for p in posts if p.get("published")]
    published.sort(key=lambda p: p.get("created_at", ""), reverse=True)

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
            f"- [Blog]({SITE_URL}/blog): research notes and write-ups",
            *key_page_cats,
        ]
    )

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
        "- Academic paper search across arXiv, Google Scholar, and OpenAlex\n"
        "- Multi-agent deep paper review\n"
        "- Study curriculum builder\n"
        "- Citation graph explorer\n"
        "\n"
        "## Key pages\n"
        f"{key_pages}\n"
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


@router.get("/llms-full.txt")
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
    published.sort(key=lambda p: p.get("created_at", ""), reverse=True)

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
