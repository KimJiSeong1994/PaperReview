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

_md = MarkdownIt("default", {"html": True, "linkify": True})

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

    posting = {
        "@type": "BlogPosting",
        "headline": title,
        "description": excerpt,
        "author": {"@type": "Person", "name": author},
        "datePublished": created_at,
        "dateModified": updated_at,
        "keywords": tags,
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
        '<meta name="robots" content="noindex,nofollow">\n    ' if noindex else ""
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

    return (
        f'<!doctype html><html lang="{esc_lang}">\n  <head>\n    '
        '<meta charset="UTF-8">\n    '
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n    '
        f"{head}\n  </head>\n  <body>\n    "
        f'<div id="root">{article_html}</div>\n    '
        f"{scripts}\n  </body>\n</html>"
    )


def _render_article(post: dict) -> str:
    """Render the visible <article> body for a single blog post."""
    title = html.escape(post.get("title", ""), quote=True)
    author = html.escape(post.get("author", ""), quote=True)
    created = html.escape(_format_date(post), quote=True)
    reading_time = post.get("reading_time_min", 1)
    tags_html = "".join(
        f'<span class="blog-tag">{html.escape(str(t), quote=True)}</span>'
        for t in post.get("tags", [])
    )
    rendered_html = _md.render(post.get("content", ""))

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

    lang = _detect_lang(post["title"] + " " + post.get("content", ""))
    locale = _locale(lang)
    document = _build_document(
        title=f"{post['title']} | Jiphyeonjeon Blog",
        description=post.get("excerpt") or post["title"],
        canonical=f"{SITE_URL}/blog/{slug}",
        og_type="article",
        image=post.get("thumbnail_url") or OG_DEFAULT_IMAGE,
        json_ld=_blog_posting_graph(post),
        article_html=_render_article(post),
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

    items = "".join(
        f'<li><a href="/blog/{html.escape(p.get("slug", ""), quote=True)}">'
        f'{html.escape(p.get("title", ""), quote=True)}</a> — '
        f'{html.escape(p.get("excerpt", ""), quote=True)}</li>'
        for p in published
    )
    body = (
        '<div class="blog-container"><div class="blog-content">'
        f"<h1>Blog</h1><ul>{items}</ul>"
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


@router.get("/sitemap.xml")
async def sitemap() -> Response:
    """Return an XML sitemap of public URLs (home, blog index, published posts)."""
    with _posts_lock:
        posts = _load_posts()

    published = [p for p in posts if p.get("published")]

    rows = [
        f"  <url><loc>{SITE_URL}/</loc><priority>1.0</priority></url>",
        f"  <url><loc>{SITE_URL}/blog</loc><priority>0.8</priority></url>",
    ]
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

    blog_lines = []
    for post in published:
        slug = post.get("slug", "")
        if not slug:
            continue
        title = post.get("title", "")
        excerpt = post.get("excerpt", "")
        blog_lines.append(f"- [{title}]({SITE_URL}/blog/{slug}): {excerpt}")

    blog_section = "\n".join(blog_lines)

    body = (
        "# 집현전 (Jiphyeonjeon)\n"
        "\n"
        f"> {LLMS_DESCRIPTION}\n"
        "\n"
        "## Blog\n"
        f"{blog_section}\n"
        "\n"
        "## Key pages\n"
        f"- [Home / Search]({SITE_URL}/): paper search interface\n"
        f"- [Blog]({SITE_URL}/blog): research notes and write-ups\n"
    )
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )
