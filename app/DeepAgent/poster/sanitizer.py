"""Central sanitizer for generated poster HTML/SVG.

The poster pipeline accepts model and microservice output. Keep static poster
markup usable, but remove active content, unsafe protocols, and CSS network
fetches before returning or saving artifacts.
"""

from __future__ import annotations

from html import escape
from html.parser import HTMLParser
import re
from typing import Iterable

from .resource_policy import (
    DROP_WITH_CONTENT_TAGS,
    HTML_ALLOWED_TAGS,
    SVG_ALLOWED_TAGS,
    VOID_TAGS,
)

_ALLOWED_TAGS = HTML_ALLOWED_TAGS | SVG_ALLOWED_TAGS
_URL_ATTRS = {
    "action",
    "background",
    "cite",
    "data",
    "formaction",
    "href",
    "longdesc",
    "manifest",
    "ping",
    "poster",
    "src",
    "srcset",
    "xlink:href",
}
_ALWAYS_STRIP_URL_ATTRS = {"background", "srcset", "ping"}
_SAFE_IMAGE_DATA_RE = re.compile(
    r"^data:image/(?:png|jpeg|jpg|gif|webp);base64,[a-z0-9+/=\s]+$",
    re.IGNORECASE,
)
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
_CSS_IMPORT_RE = re.compile(r"@import\b[^;]*;?", re.IGNORECASE)
_CSS_ACTIVE_RE = re.compile(
    r"expression\s*\(|-moz-binding\s*:|behavior\s*:",
    re.IGNORECASE,
)
_CSS_ESCAPE_RE = re.compile(r"\\([0-9a-fA-F]{1,6}\s?|.)", re.DOTALL)
_CSS_NETWORK_CAPABLE_RE = re.compile(
    r"@import\b|(?:-webkit-)?image-set\s*\(|url\s*\(|expression\s*\(|"
    r"-moz-binding\s*:|behavior\s*:",
    re.IGNORECASE | re.DOTALL,
)
_URL_FUNC_RE = re.compile(r"u\s*r\s*l\s*\(", re.IGNORECASE)
_LOCAL_URL_FUNC_RE = re.compile(
    r"^\s*u\s*r\s*l\s*\(\s*(['\"]?)#[A-Za-z_][\w:.-]*\1\s*\)\s*$",
    re.IGNORECASE,
)
_ABSOLUTE_OR_RELATIVE_URL_RE = re.compile(
    r"^\s*(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//|/|\./|\.\./)"
)
_CANONICAL_TAG_NAMES = {
    "lineargradient": "linearGradient",
    "radialgradient": "radialGradient",
    "clippath": "clipPath",
}


def escape_text(value: object) -> str:
    """Escape text for HTML body, list, table, and attribute contexts."""
    return escape(str(value), quote=True)


def _decode_basic_css_escapes(css: str) -> str:
    """Decode CSS escapes enough to expose obfuscated fetch primitives."""
    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        stripped = token.strip()
        if stripped and all(ch in "0123456789abcdefABCDEF" for ch in stripped):
            try:
                codepoint = int(stripped, 16)
                if 0 <= codepoint <= 0x10FFFF:
                    return chr(codepoint)
            except ValueError:
                return ""
        return token[:1]

    previous = str(css)
    for _ in range(3):
        decoded = _CSS_ESCAPE_RE.sub(replace, previous)
        if decoded == previous:
            break
        previous = decoded
    return previous


def sanitize_css(css: str) -> str:
    """Drop CSS content that contains network-capable or active primitives."""
    raw = str(css)
    decoded = _decode_basic_css_escapes(raw)
    compact = re.sub(r"\s+", "", decoded)
    if _CSS_NETWORK_CAPABLE_RE.search(decoded) or _CSS_NETWORK_CAPABLE_RE.search(compact):
        return ""
    cleaned = _CSS_IMPORT_RE.sub("", raw)
    cleaned = _CSS_URL_RE.sub("", cleaned)
    cleaned = _CSS_ACTIVE_RE.sub("", cleaned)
    return cleaned


def sanitize_poster_markup(markup: str) -> str:
    """Sanitize a complete poster HTML or SVG fragment."""
    parser = _PosterSanitizer()
    parser.feed(str(markup or ""))
    parser.close()
    return parser.output()


def _is_safe_url(value: str, attr_name: str, tag: str) -> bool:
    if attr_name in _ALWAYS_STRIP_URL_ATTRS:
        return False
    value = value.strip()
    if not value:
        return True
    if value.startswith("#"):
        return True
    if tag == "img" and attr_name == "src" and _SAFE_IMAGE_DATA_RE.match(value):
        return True
    return False


def _has_unsafe_url_reference(value: str) -> bool:
    """Detect URL references in any attribute value.

    SVG paint/filter/clip/mask/marker attributes accept CSS url() references.
    Preserve only local fragment references, e.g. ``url(#gradient)``.
    """
    value = value.strip()
    if not value:
        return False
    if _SAFE_IMAGE_DATA_RE.match(value):
        return False
    if _URL_FUNC_RE.search(value):
        return _LOCAL_URL_FUNC_RE.match(value) is None
    return False


def _safe_attrs(attrs: Iterable[tuple[str, str | None]], tag: str) -> list[tuple[str, str]]:
    safe: list[tuple[str, str]] = []
    for raw_name, raw_value in attrs:
        name = raw_name.lower()
        attr_name = "viewBox" if name == "viewbox" else raw_name
        value = "" if raw_value is None else str(raw_value)
        if name.startswith("on"):
            continue
        if name in {"srcdoc", "http-equiv"}:
            continue
        if name == "style":
            value = sanitize_css(value)
            if not value.strip():
                continue
        elif name not in _URL_ATTRS and _has_unsafe_url_reference(value):
            continue
        elif name in _URL_ATTRS and not _is_safe_url(value, name, tag):
            continue
        elif name in {"srcset", "ping"}:
            continue
        safe.append((attr_name, value))
    return safe


class _PosterSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._parts: list[str] = []
        self._drop_depth = 0
        self._style_depth = 0
        self._style_buffer: list[str] = []

    def output(self) -> str:
        return "".join(self._parts)

    def handle_decl(self, decl: str) -> None:
        if self._drop_depth:
            return
        if decl.upper().startswith("DOCTYPE"):
            self._parts.append(f"<!{decl}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower in DROP_WITH_CONTENT_TAGS:
            self._drop_depth += 1
            return
        if self._drop_depth:
            return
        if lower not in _ALLOWED_TAGS:
            return
        if lower == "style":
            self._style_depth += 1
            self._style_buffer = []
            self._parts.append("<style>")
            return

        attr_text = self._format_attrs(_safe_attrs(attrs, lower))
        out_tag = _CANONICAL_TAG_NAMES.get(lower, tag)
        if lower in VOID_TAGS:
            self._parts.append(f"<{out_tag}{attr_text}>")
        else:
            self._parts.append(f"<{out_tag}{attr_text}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower in DROP_WITH_CONTENT_TAGS or self._drop_depth or lower not in _ALLOWED_TAGS:
            return
        attr_text = self._format_attrs(_safe_attrs(attrs, lower))
        out_tag = _CANONICAL_TAG_NAMES.get(lower, tag)
        self._parts.append(f"<{out_tag}{attr_text}>")

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in DROP_WITH_CONTENT_TAGS:
            if self._drop_depth:
                self._drop_depth -= 1
            return
        if self._drop_depth:
            return
        if lower not in _ALLOWED_TAGS:
            return
        if lower == "style":
            if self._style_depth:
                self._parts.append(sanitize_css("".join(self._style_buffer)))
                self._parts.append("</style>")
                self._style_depth = 0
                self._style_buffer = []
            return
        if lower not in VOID_TAGS:
            out_tag = _CANONICAL_TAG_NAMES.get(lower, tag)
            self._parts.append(f"</{out_tag}>")

    def handle_data(self, data: str) -> None:
        if self._drop_depth:
            return
        if self._style_depth:
            self._style_buffer.append(data)
            return
        self._parts.append(escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if not self._drop_depth:
            target = self._style_buffer if self._style_depth else self._parts
            target.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._drop_depth:
            target = self._style_buffer if self._style_depth else self._parts
            target.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        if not self._drop_depth:
            self._parts.append(f"<!--{data}-->")

    @staticmethod
    def _format_attrs(attrs: list[tuple[str, str]]) -> str:
        if not attrs:
            return ""
        return "".join(f' {name}="{escape(value, quote=True)}"' for name, value in attrs)
