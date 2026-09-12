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
_CSS_IMPORT_RE = re.compile(r"@import\b", re.IGNORECASE)
_CSS_IMAGE_SET_RE = re.compile(
    r"(?<![-\w])(?:-(?:webkit|moz|o|ms)-)?image-set\s*\(",
    re.IGNORECASE,
)
_CSS_EXPRESSION_RE = re.compile(r"(?<![-\w])expression\s*\(", re.IGNORECASE)
# scroll-behavior and overscroll-behavior are ordinary layout properties, so the
# lookbehind keeps them out of the active-content rule.
_CSS_ACTIVE_DECL_RE = re.compile(
    r"(?<![-\w])(?:-moz-binding|behavior)\s*:",
    re.IGNORECASE,
)
_CSS_ESCAPE_RE = re.compile(r"\\([0-9a-fA-F]{1,6}\s?|.)", re.DOTALL)
_CSS_SANITIZE_PASSES = 5
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


def _skip_css_comment(css: str, start: int) -> int:
    """Return the index just past the ``/* ... */`` comment opening at ``start``."""
    end = css.find("*/", start + 2)
    return len(css) if end < 0 else end + 2


def _skip_css_string(css: str, start: int) -> int:
    """Return the index just past the string literal opening at ``start``.

    A raw newline ends the token, matching the CSS bad-string rule. Running past
    it would let an unterminated string hide a url() the browser still parses.
    """
    quote = css[start]
    i = start + 1
    while i < len(css):
        ch = css[i]
        if ch == "\\":
            i += 2
            continue
        if ch == quote:
            return i + 1
        if ch in "\n\r\f":
            return i
        i += 1
    return len(css)


def _read_css_function_body(css: str, start: int) -> tuple[str, int, bool]:
    """Read a function body that starts just past its ``(``.

    Returns the body, the index just past the closing ``)``, and whether it
    actually closed. An unclosed body is consumed to the end of the input so a
    truncated function can never leave its arguments behind as live CSS.
    """
    depth = 1
    i = start
    while i < len(css):
        ch = css[i]
        if ch == "/" and css.startswith("/*", i):
            i = _skip_css_comment(css, i)
            continue
        if ch in "\"'":
            i = _skip_css_string(css, i)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return css[start:i], i + 1, True
        i += 1
    return css[start:], len(css), False


def _skip_css_statement(css: str, start: int) -> int:
    """Return the index just past the declaration or at-rule starting at ``start``.

    Stops after a top-level ``;``, after a block-form at-rule's ``}``, or at the
    ``}`` that closes the enclosing rule -- which is left in place so removing a
    declaration cannot unbalance the stylesheet around it.
    """
    depth = 0
    i = start
    while i < len(css):
        ch = css[i]
        if ch == "/" and css.startswith("/*", i):
            i = _skip_css_comment(css, i)
            continue
        if ch in "\"'":
            i = _skip_css_string(css, i)
            continue
        if ch in "({":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        elif ch == "}":
            if depth == 0:
                return i
            depth -= 1
            if depth == 0:
                return i + 1
        elif ch == ";" and depth == 0:
            return i + 1
        i += 1
    return len(css)


def _is_safe_css_url(body: str) -> bool:
    """Judge a url() body exactly the way the attribute path judges one.

    Local fragments are checked with ``_LOCAL_URL_FUNC_RE``, the same predicate
    behind ``_has_unsafe_url_reference``, so the two paths cannot rule
    differently on the same string. Inline images are checked with
    ``_SAFE_IMAGE_DATA_RE``, which admits raster types only -- an
    ``image/svg+xml`` document can carry script, so it stays out.
    """
    value = body.strip()
    if _LOCAL_URL_FUNC_RE.match(f"url({value})"):
        return True
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        value = value[1:-1]
    return bool(_SAFE_IMAGE_DATA_RE.match(value.strip()))


def _strip_css_threats(css: str) -> str:
    """Remove network-capable and active constructs, keeping the rest of the CSS.

    Comments and string literals are copied verbatim: to the browser their
    contents are not url tokens either, so a comment mentioning url() or a
    ``content:'url('`` literal must not cost the page its stylesheet.
    """
    out: list[str] = []
    i = 0
    length = len(css)
    while i < length:
        ch = css[i]
        if ch == "/" and css.startswith("/*", i):
            end = _skip_css_comment(css, i)
            out.append(css[i:end])
            i = end
            continue
        if ch in "\"'":
            end = _skip_css_string(css, i)
            out.append(css[i:end])
            i = end
            continue
        if _CSS_IMPORT_RE.match(css, i) or _CSS_ACTIVE_DECL_RE.match(css, i):
            # @import cannot be made safe, and -moz-binding/behavior bind script
            # to an element even from a local fragment -- so the whole statement
            # goes, not just the keyword that names it.
            i = _skip_css_statement(css, i)
            continue
        call = _CSS_IMAGE_SET_RE.match(css, i) or _CSS_EXPRESSION_RE.match(css, i)
        if call:
            # image-set() holds URLs and expression() holds script. Neither has a
            # safe form worth parsing out, so the call goes whole.
            _, i, _ = _read_css_function_body(css, call.end())
            continue
        call = _URL_FUNC_RE.match(css, i)
        if call:
            body, end, closed = _read_css_function_body(css, call.end())
            if closed and _is_safe_css_url(body):
                out.append(f"url({body.strip()})")
            i = end
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def sanitize_css(css: str) -> str:
    """Remove network-capable and active CSS, leaving the stylesheet standing.

    What gets inspected has to be what gets returned. Decoding first and
    returning the decoded text closes the gap where an escaped ``u\\72 l(``
    passes the check and the browser turns it back into a fetch; CSS escapes do
    not change a stylesheet's meaning, so normalizing them loses nothing.

    Removal can splice new tokens together (``ur`` + a dropped call + ``l(evil)``
    reads as ``url(evil)`` once the call is gone), so decode-and-strip repeats
    until it is a no-op. Neither step can lengthen its input, so that fixpoint
    proves the returned text is unchanged by both. Input that keeps changing
    past the pass limit is fighting the sanitizer, and its stylesheet is dropped.
    """
    current = str(css)
    for _ in range(_CSS_SANITIZE_PASSES):
        stripped = _strip_css_threats(_decode_basic_css_escapes(current))
        if stripped == current:
            return current
        current = stripped
    return ""


def sanitize_poster_markup(markup: str) -> str:
    """Sanitize a complete poster HTML or SVG fragment."""
    parser = _PosterSanitizer()
    parser.feed(str(markup or ""))
    parser.close()
    return parser.output()


# 정책은 렌더된 포스터 29건을 sanitize한 뒤 실측해서 뽑았다: 인라인 <style>
# 29/29, style= 속성 23/29, data: <img> 5/29, url()은 전부 지역 조각(#id),
# 외부 폰트·스타일시트·스크립트는 0건. 그래서 인라인 CSS와 data: 도판만
# 열고 나머지 이그레스는 전부 닫는다. 목적은 인라인 CSS 금지가 아니라
# 네트워크 차단이므로 'unsafe-inline'은 정책의 전제다.
POSTER_CSP_POLICY = (
    "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
    "base-uri 'none'; form-action 'none'"
)
_POSTER_CSP_META = (
    f'<meta http-equiv="Content-Security-Policy" content="{POSTER_CSP_POLICY}">'
)
# sanitize는 http-equiv만 떼어내고 <meta content="...">를 남긴다. PDF 내보내기는
# 클라이언트가 쥔 HTML을 그대로 되돌려 보내므로, 그 잔해를 먼저 걷어내지 않으면
# 왕복마다 하나씩 쌓이고 전달 바이트 해시가 미리보기와 갈린다.
_CSP_META_RE = re.compile(r"<meta\b[^>]*default-src[^>]*>", re.IGNORECASE)


class _DocumentAnchors(HTMLParser):
    """meta CSP를 document.head 안에 넣으려면 어디를 잘라야 하는지 찾는다.

    정규식으로는 못 한다. ``<head[^>]*>``는 ``<header>``에도 매치되고, 같은
    글자가 주석 안에 있는 경우를 구분하지 못한다. 둘 다 meta를 head 밖에
    떨어뜨리고, 브라우저는 head 밖의 CSP를 무시한다 -- 주석 쪽은 경고조차
    없다. HTMLParser는 주석을 handle_comment로 따로 넘기고 태그 이름을 정확히
    주므로 두 경우 모두 구조적으로 생기지 않는다.

    body가 열린 뒤에 나오는 ``<head>``는 앵커로 쓰지 않는다. 브라우저는 그
    시점의 ``<head>`` 태그를 버리므로, 거기에 넣은 meta도 body에 남는다.
    """

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=False)
        self._line_starts = [0] + [
            index + 1 for index, char in enumerate(html) if char == "\n"
        ]
        self.head_end: int | None = None
        self.html_end: int | None = None
        self.doctype_end: int | None = None
        self._body_open = False
        self.feed(html)
        self.close()

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_starts[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        end = self._offset() + len(self.get_starttag_text() or "")
        if tag == "head":
            if self.head_end is None and not self._body_open:
                self.head_end = end
            self._body_open = True
        elif tag == "html":
            if self.html_end is None and not self._body_open:
                self.html_end = end
        else:
            self._body_open = True

    def handle_decl(self, decl: str) -> None:
        if self.doctype_end is None and decl.upper().startswith("DOCTYPE"):
            # handle_decl은 <! 와 > 사이만 넘겨준다.
            self.doctype_end = self._offset() + len(decl) + 3

    def handle_data(self, data: str) -> None:
        # BOM은 브라우저가 파싱 전에 걷어내므로 body를 열지 않는다. Python의
        # strip()은 이것을 공백으로 보지 않아서, 직접 빼주지 않으면 문서 맨 앞의
        # BOM 하나가 <html>을 "body가 열린 뒤의 태그"로 만들어 앵커를 DOCTYPE
        # 뒤로 밀어낸다 -- <head>가 <html>보다 앞에 놓이는 비정상 출력이 된다.
        if data.strip("﻿").strip():
            self._body_open = True

    def handle_entityref(self, name: str) -> None:
        self._body_open = True

    def handle_charref(self, name: str) -> None:
        self._body_open = True


def inject_poster_csp(html: str) -> str:
    """전달되는 포스터 문서에 고정 CSP <meta>를 심는다.

    sanitize 이후에만 부른다. sanitizer가 입력의 http-equiv를 지우는 것은
    공격자가 정책을 심거나 무력화하지 못하게 하는 장치이므로, 순서가 뒤집히면
    우리 정책도 함께 사라진다. 반대로 sanitize 다음에 붙이면 문서에 남는
    CSP는 이 고정 리터럴 하나뿐이다.

    meta CSP는 ``document.head`` 안에 있을 때만 적용되므로, ``<head>``가 없으면
    브라우저가 만들어 줄 암묵 head에 기대지 않고 직접 만든다 -- ``<header>``나
    다른 body 콘텐츠가 먼저 나오는 순간 파서가 meta를 body로 밀어내고, 정책은
    조용히 무시된다. poster_agent가 조각을 감싸는 경로가 정확히 그 형태다.

    빈 문서는 그대로 돌려준다. 주입이 내용을 만들어내면 렌더할 것이 없는
    실패가 호출자에게 성공으로 보인다.
    """
    if not html.strip():
        return html
    html = _CSP_META_RE.sub("", html)
    anchors = _DocumentAnchors(html)
    if anchors.head_end is not None:
        return html[: anchors.head_end] + _POSTER_CSP_META + html[anchors.head_end :]
    # <html> 다음, 없으면 DOCTYPE 다음, 그것도 없으면 맨 앞. 어느 쪽이든
    # 여는 <head>가 문서의 첫 요소가 되므로 meta는 head의 첫 자식이 된다.
    position = anchors.html_end
    if position is None:
        position = anchors.doctype_end if anchors.doctype_end is not None else 0
    return (
        html[:position] + f"<head>{_POSTER_CSP_META}</head>" + html[position:]
    )


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
        if lower not in VOID_TAGS:
            # HTMLParser routes <style/> here without entering CDATA mode, while
            # a browser reads it as an ordinary start tag. Emitting the open tag
            # alone would hand the browser a stylesheet made of every byte that
            # follows -- bytes this parser never passed to sanitize_css. Closing
            # the element is what keeps what was inspected and what is emitted
            # the same document; <title/> would swallow the poster the same way.
            self._parts.append(f"</{out_tag}>")

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
