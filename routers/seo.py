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

_md = MarkdownIt("default", {"html": True, "linkify": True})

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


def _normalize_blog_markdown(content: str) -> str:
    """Apply SSR-safe blog markdown normalizations before rendering."""
    return _normalize_latex_delimiters(_strip_leading_h1(content))


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
        "sameAs": ["https://github.com/KimJiSeong1994/PaperReview"],
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
        "image": post.get("thumbnail_url") or OG_DEFAULT_IMAGE,
    }
    return {
        "@context": "https://schema.org",
        "@graph": [_organization_node(), posting, _breadcrumb(title, slug)],
    }


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
        f'<div id="root">{article_html}</div>\n    '
        f"{scripts}\n  </body>\n</html>"
    )


def _render_article(
    post: dict,
    related: list[dict] | None = None,
    prev_post: dict | None = None,
    next_post: dict | None = None,
) -> str:
    """Render the visible <article> body for a single blog post.

    ``related`` and ``prev_post``/``next_post`` add crawlable internal links so
    the post graph is not star-shaped (every post reachable only from the index).
    """
    title = html.escape(post.get("title", ""), quote=True)
    author = html.escape(post.get("author", ""), quote=True)
    created = html.escape(_format_date(post), quote=True)
    reading_time = post.get("reading_time_min", 1)
    tags_html = "".join(
        f'<span class="blog-tag">{html.escape(str(t), quote=True)}</span>'
        for t in post.get("tags", [])
    )
    # Drop the duplicate leading H1 so the title <h1> is the page's only H1.
    rendered_html = _md.render(_normalize_blog_markdown(post.get("content", "")))

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
        '<div class="blog-detail-meta">'
        f'<span class="blog-detail-author">{author}</span>'
        f'<span class="blog-detail-date">{created}</span>'
        f'<span class="blog-detail-reading-time">{reading_time} min read</span>'
        "</div>"
        f'<div class="blog-detail-tags">{tags_html}</div>'
        f'<div class="blog-detail-content">{rendered_html}</div>'
        f"{related_html}"
        f"{prevnext_html}"
        "</div></div></div>"
    )


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
    document = _build_document(
        title=f"{post['title']} | Jiphyeonjeon Blog",
        description=post.get("excerpt") or post["title"],
        canonical=f"{SITE_URL}/blog/{slug}",
        og_type="article",
        image=post.get("thumbnail_url") or OG_DEFAULT_IMAGE,
        json_ld=_blog_posting_graph(post),
        article_html=_render_article(post, related=related, prev_post=older, next_post=newer),
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
    default_category = "engineering"

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

    # /blog defaults to the Engineering category; other categories remain
    # available through their explicit /blog/category/<category> hubs.
    sections = _index_section(default_category)
    body = (
        '<div class="blog-container"><div class="blog-content">'
        f"<h1>Blog</h1>{sections}"
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


@router.get("/llms-full.txt")
async def llms_full_txt() -> Response:
    """Return the complete markdown body of every published blog post.

    ``/blog/{slug}`` remains the canonical indexable HTML page. This text feed is
    an auxiliary discovery/retrieval surface for AI search crawlers and internal
    retrieval systems that prefer a compact plaintext corpus. Drafts and deleted
    posts are excluded so unpublished content never leaks into search indexes.
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
        content = _normalize_blog_markdown(post.get("content", "")).strip()
        sections.append(
            "\n".join(
                [
                    "",
                    "---",
                    "",
                    f"## {title}",
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
