"""BLOG_SERIES must stay in sync between the Python SSR builder and the SPA.

routers/seo.py and web-ui/src/seo/series.ts each hold their own copy, and the
header of series.ts calls them a shared contract to be kept "in byte-sync" —
but nothing enforced it. The pair drives the series pillar pages, the sitemap,
the detail view's prev/next nav and the list page's series shelf, so a copy
that drifts sends readers to a page that lists different posts than the nav
that got them there.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from routers.seo import BLOG_SERIES

SERIES_TS = Path("web-ui/src/seo/series.ts")


def _parse_ts_series() -> dict[str, dict]:
    """Read the TS literal without a JS engine.

    Only the shapes this file actually uses are supported: single-quoted
    strings joined with `+`, and a slug array of string literals.
    """
    source = SERIES_TS.read_text(encoding="utf-8")
    body = source[source.index("export const BLOG_SERIES") : source.index("\n};\n")]

    out: dict[str, dict] = {}
    # Entry heads look like `gnn: {` or `'graph-causality': {` at one indent.
    for match in re.finditer(r"^  '?([A-Za-z0-9_-]+)'?: \{$", body, re.M):
        start = match.end()
        chunk = body[start : body.index("\n  },", start)]
        title = re.search(r"title: '(.*?)',$", chunk, re.M).group(1)
        desc_block = chunk[chunk.index("description:") : chunk.index("slugs:")]
        description = "".join(re.findall(r"'((?:[^'\\]|\\.)*)'", desc_block))
        slugs = re.findall(r"^      '([^']+)',$", chunk[chunk.index("slugs:") :], re.M)
        out[match.group(1)] = {
            "title": title,
            "description": description.replace("\\'", "'"),
            "slugs": slugs,
        }
    return out


def test_series_ids_and_order_match() -> None:
    assert list(_parse_ts_series()) == list(BLOG_SERIES)


def test_series_titles_descriptions_and_slugs_match() -> None:
    ts = _parse_ts_series()
    for series_id, python_entry in BLOG_SERIES.items():
        ts_entry = ts[series_id]
        assert ts_entry["title"] == python_entry["title"], series_id
        assert ts_entry["description"] == python_entry["description"], series_id
        # Order is the reading order the prev/next nav walks, so compare as a
        # list rather than a set.
        assert ts_entry["slugs"] == python_entry["slugs"], series_id


def test_every_series_slug_is_a_published_post() -> None:
    import json

    posts = json.loads(Path("data/blog/posts.json").read_text(encoding="utf-8"))
    posts = posts.get("posts", posts) if isinstance(posts, dict) else posts
    published = {p["slug"] for p in posts if p.get("published")}
    for series_id, entry in BLOG_SERIES.items():
        missing = [s for s in entry["slugs"] if s not in published]
        assert not missing, f"{series_id} points at unpublished slugs: {missing}"


def test_no_post_belongs_to_two_series() -> None:
    seen: dict[str, str] = {}
    for series_id, entry in BLOG_SERIES.items():
        for slug in entry["slugs"]:
            assert slug not in seen, f"{slug} is in both {seen[slug]} and {series_id}"
            seen[slug] = series_id


def test_parser_reads_the_real_file() -> None:
    """Guard the guard: a parser that silently returns {} would pass everything."""
    parsed = _parse_ts_series()
    assert len(parsed) == len(BLOG_SERIES) >= 5
    assert all(entry["slugs"] for entry in parsed.values())
    assert ast.literal_eval(repr(parsed)) == parsed
