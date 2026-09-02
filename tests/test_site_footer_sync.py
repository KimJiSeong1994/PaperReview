"""The site footer must stay in sync between the SPA and the SSR HTML.

web-ui/src/components/SiteFooter.tsx renders the footer for real users;
routers/seo.py::_SITE_FOOTER_HTML is a static copy injected into #root so
crawlers on SSR blog pages see the same links. Both headers say "keep in
sync" — this file is what makes that true, so a link added or renamed in one
copy cannot silently go missing from the other.

Only the Korean variant is compared: _SITE_FOOTER_HTML is injected by
_build_document, which serves Korean pages, so the 서비스 소개 link points at
/ko/introduce/ in both copies. The React component swaps in /introduce/ on
English routes; that switch is covered by the frontend test.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from routers.seo import _SITE_FOOTER_HTML

FOOTER_TSX = Path("web-ui/src/components/SiteFooter.tsx")

Column = tuple[str, list[tuple[str, str]]]


def _parse_tsx_footer() -> tuple[str, list[Column]]:
    """Read the TS literals without a JS engine.

    Only the shapes this file actually uses are supported: single-quoted
    string literals, and `href` values given either as a literal or as the
    name of a `export const NAME = '...'` in the same file.
    """
    source = FOOTER_TSX.read_text(encoding="utf-8")
    consts = dict(re.findall(r"^export const ([A-Z_]+) = '([^']*)';$", source, re.M))
    brand = consts["SITE_FOOTER_BRAND"]

    body = source[source.index("export const SITE_FOOTER_COLUMNS") : source.index("\n];\n")]
    heads = list(re.finditer(r"^    heading: '([^']+)',$", body, re.M))
    columns: list[Column] = []
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(body)
        links = [
            (consts.get(href, href.strip("'")), label)
            for href, label in re.findall(
                r"\{ href: ('[^']*'|[A-Z_]+), label: '([^']+)' \}", body[head.end() : end]
            )
        ]
        columns.append((head.group(1), links))
    return brand, columns


def _parse_ssr_footer() -> tuple[str, list[Column]]:
    brand = re.search(r'<span class="site-footer-brand">([^<]+)</span>', _SITE_FOOTER_HTML)
    chunks = _SITE_FOOTER_HTML.split('<nav class="site-footer-column"')[1:]
    columns: list[Column] = []
    for chunk in chunks:
        heading = re.search(r'<p class="site-footer-heading">([^<]+)</p>', chunk)
        links = re.findall(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', chunk)
        columns.append((heading.group(1), links))
    return brand.group(1), columns


def test_footer_columns_and_links_match() -> None:
    assert _parse_tsx_footer() == _parse_ssr_footer()


def test_external_profile_links_open_safely_in_both_copies() -> None:
    """rel="me" carries the Organization sameAs identity claim; don't drop it."""
    # The SPA renders every off-site link through one JSX branch; SSR spells
    # each out, so check the attributes ride along with each external href.
    assert 'rel="me noopener noreferrer"' in FOOTER_TSX.read_text(encoding="utf-8")
    external = [
        (href, tag)
        for href, tag in re.findall(r'<a href="(https?://[^"]+)"([^>]*)>', _SITE_FOOTER_HTML)
    ]
    assert len(external) == 2
    for href, tag in external:
        assert 'rel="me noopener noreferrer"' in tag, href
        assert 'target="_blank"' in tag, href


def test_parsers_read_the_real_files() -> None:
    """Guard the guard: parsers that silently return nothing would pass everything."""
    for brand, columns in (_parse_tsx_footer(), _parse_ssr_footer()):
        assert brand == "© Jiphyeonjeon (집현전)"
        assert [heading for heading, _ in columns] == ["집현전", "블로그", "만든 사람"]
        assert sum(len(links) for _, links in columns) == 7
        assert all(href and label for _, links in columns for href, label in links)
        assert ast.literal_eval(repr(columns)) == columns
