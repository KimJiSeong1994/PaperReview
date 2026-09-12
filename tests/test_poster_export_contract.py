"""Poster PDF export geometry, isolation, and route contract."""

from __future__ import annotations

import base64
import hashlib
import http.server
import io
import struct
import threading
import time
import zlib

import pytest

from app.DeepAgent.poster.result_contract import (
    CODE_PDF_GEOMETRY_INVALID,
    CODE_PDF_UNAVAILABLE,
    CODE_TIMEOUT_UNCLASSIFIED,
    PosterServiceError,
    public_error_detail,
)
from app.DeepAgent.utils.poster_exporter import (
    A3_LANDSCAPE_MM,
    GEOMETRY_TOLERANCE_MM,
    render_poster_pdf,
)

_MM_PER_POINT = 25.4 / 72.0

_A3_STYLE = """
@page { size: A3 landscape; margin: 0; }
html, body { margin: 0; }
@media print { html, body { width: 420mm; height: 297mm; } }
"""


@pytest.fixture(scope="module")
def chromium() -> None:
    """Skip the whole module when the Chromium runtime is not installed.

    Mirrors the skip guard in ``tests/test_poster_browser_security.py``.
    """
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        with sync_api.sync_playwright() as playwright:
            playwright.chromium.launch(headless=True).close()
    except sync_api.Error as exc:
        message = str(exc)
        if (
            "Executable doesn't exist" in message
            or "playwright install" in message
            or "Looks like Playwright was just installed" in message
        ):
            pytest.skip("Playwright Chromium executable is not installed")
        raise


def _one_pixel_png() -> bytes:
    """Minimal valid RGB PNG, so the test needs no image dependency."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(
            ">I", zlib.crc32(body) & 0xFFFFFFFF
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


def _page_geometry(pdf_bytes: bytes) -> tuple[int, float, float]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    box = reader.pages[0].mediabox
    return (
        len(reader.pages),
        float(box.width) * _MM_PER_POINT,
        float(box.height) * _MM_PER_POINT,
    )


class _CountingHandler(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        type(self).hits.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"reached")

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def counting_server():
    """Local HTTP server that records every request it actually receives."""
    _CountingHandler.hits = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CountingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_render_produces_single_page_a3_landscape(chromium) -> None:
    pdf_bytes = render_poster_pdf(
        f"<html><head><style>{_A3_STYLE}</style></head>"
        "<body><h1>A3 poster</h1></body></html>"
    )

    assert pdf_bytes.startswith(b"%PDF-")
    pages, width_mm, height_mm = _page_geometry(pdf_bytes)
    expected_width, expected_height = A3_LANDSCAPE_MM
    assert pages == 1
    assert abs(width_mm - expected_width) <= GEOMETRY_TOLERANCE_MM
    assert abs(height_mm - expected_height) <= GEOMETRY_TOLERANCE_MM


def test_external_resources_are_never_fetched(chromium, counting_server) -> None:
    """Defense in depth: the renderer blocks network even on unsanitized HTML."""
    base = f"http://127.0.0.1:{counting_server.server_address[1]}"
    html = (
        "<html><head>"
        f"<style>@import url('{base}/imported.css');{_A3_STYLE}</style>"
        f'<link rel="stylesheet" href="{base}/linked.css">'
        f"<style>body {{ background: url('{base}/bg.png'); }}</style>"
        "</head><body>"
        f'<h1>blocked</h1><img src="{base}/pixel.png" alt="tracker">'
        f'<img src="https://example.invalid/remote.png" alt="remote">'
        "</body></html>"
    )

    pdf_bytes = render_poster_pdf(html)

    assert _CountingHandler.hits == []
    # The page still renders; blocking must not turn into a silent failure.
    assert _page_geometry(pdf_bytes)[0] == 1


def test_markup_only_egress_is_blocked(chromium, counting_server) -> None:
    """Disabling scripting does not remove a smuggled element, only its handler.

    The mXSS wrapper carries a whole <link rel=prefetch> past the sanitizer,
    and context.route never sees a prefetch — so this is closed at name
    resolution instead. Literal IPs included, which is where an SSRF points.
    """
    base = f"http://127.0.0.1:{counting_server.server_address[1]}"
    html = (
        f"<html><head><style>{_A3_STYLE}</style>"
        f'<!--><link rel="prefetch" href="{base}/smuggled">-->'
        f'<link rel="prefetch" href="{base}/plain">'
        "</head><body><h1>blocked</h1></body></html>"
    )

    pdf_bytes = render_poster_pdf(html)

    assert _CountingHandler.hits == []
    assert _page_geometry(pdf_bytes)[0] == 1


def test_data_uri_image_is_rendered(chromium) -> None:
    encoded = base64.b64encode(_one_pixel_png()).decode("ascii")
    pdf_bytes = render_poster_pdf(
        f"<html><head><style>{_A3_STYLE}</style></head><body>"
        f'<img src="data:image/png;base64,{encoded}" '
        'style="width:200mm;height:100mm" alt="inline figure">'
        "</body></html>"
    )

    from pypdf import PdfReader

    page = PdfReader(io.BytesIO(pdf_bytes)).pages[0]
    assert len(page.images) >= 1


_JS_MARKER = "PosterScriptDidRun"
_JS_PAYLOAD = f"document.body.appendChild(document.createTextNode('{_JS_MARKER}'))"


@pytest.mark.parametrize(
    "markup",
    [
        # These two survive sanitize_poster_markup: html.parser and the
        # browser's HTML5 parser disagree about where the <img> ends up.
        pytest.param(
            f'<svg><style><img src=x onerror="{_JS_PAYLOAD}"></style></svg>',
            id="svg-style-img",
        ),
        pytest.param(
            f'<!--><img src=x onerror="{_JS_PAYLOAD}">-->', id="abrupt-comment"
        ),
        # Needs no parser differential at all, so it holds even if the
        # sanitizer changes: proves scripting is off in the render context.
        pytest.param(f"<script>{_JS_PAYLOAD}</script>", id="bare-script"),
    ],
)
def test_render_context_never_executes_script(chromium, markup) -> None:
    """The PDF page carries no sandbox attribute, unlike the preview iframe.

    Scripting must therefore be off in the browser context itself — asserted by
    behaviour (no payload output in the PDF), not by reading a context option.
    """
    from pypdf import PdfReader

    pdf_bytes = render_poster_pdf(
        f"<html><head><style>{_A3_STYLE}</style></head>"
        f"<body><h1>poster</h1>{markup}</body></html>"
    )

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    assert _JS_MARKER not in text


def test_expired_deadline_refuses_to_render(monkeypatch) -> None:
    def _never_launch(*args, **kwargs):
        raise AssertionError("Chromium must not start once the budget is gone")

    monkeypatch.setattr("playwright.sync_api.sync_playwright", _never_launch)

    with pytest.raises(PosterServiceError) as excinfo:
        render_poster_pdf("<html></html>", deadline=time.monotonic() - 1)

    assert excinfo.value.error_code == CODE_TIMEOUT_UNCLASSIFIED
    assert excinfo.value.status_code == 504


def test_timeout_during_render_keeps_the_pre_render_contract(chromium, monkeypatch) -> None:
    """A timeout is a timeout on either side of the render.

    PlaywrightTimeoutError subclasses PlaywrightError, so without an earlier
    except clause the budget running out mid-render answered 500/retryable=True
    while the same cause a millisecond earlier answered 504/retryable=False —
    and retrying a timeout mostly just times out again.
    """
    sync_api = pytest.importorskip("playwright.sync_api")

    with pytest.raises(PosterServiceError) as before_entry:
        render_poster_pdf("<html></html>", deadline=time.monotonic() - 1)

    def _times_out(*args, **kwargs):
        raise sync_api.TimeoutError("Timeout 1ms exceeded.")

    monkeypatch.setattr(sync_api.Page, "set_content", _times_out)

    with pytest.raises(PosterServiceError) as mid_render:
        render_poster_pdf(f"<html><head><style>{_A3_STYLE}</style></head></html>")

    def contract(error: PosterServiceError):
        return error.error_code, error.status_code, error.retryable

    assert contract(mid_render.value) == contract(before_entry.value)
    assert contract(mid_render.value) == (CODE_TIMEOUT_UNCLASSIFIED, 504, False)


def test_geometry_violation_is_not_returned_as_pdf(chromium) -> None:
    """A poster that names a page size other than A3 landscape must be refused.

    Absence of an @page rule no longer reaches this gate — the exporter supplies
    the A3 default for that case — so the violation has to be an explicit one.
    """
    with pytest.raises(PosterServiceError) as excinfo:
        render_poster_pdf(
            "<html><head><style>@page { size: A4 portrait; margin: 0; }</style>"
            "</head><body><h1>Wrong size</h1></body></html>"
        )

    assert excinfo.value.error_code == CODE_PDF_GEOMETRY_INVALID
    assert excinfo.value.retryable is False


def test_page_rule_is_restored_when_the_stylesheet_was_emptied(chromium) -> None:
    """sanitize_css blanks an entire stylesheet over any 'url(' — url(#gradient),
    a data: URI, even the word inside a comment. The service sanitizes before
    handing the poster over, so the HTML the client holds can already have lost
    its @page, and that used to export as an unrecoverable 500 while the HTML
    download of the very same poster still worked.
    """
    expected_width, expected_height = A3_LANDSCAPE_MM
    for html in (
        # What the sanitizer actually leaves behind: emptied, not removed.
        "<html><head><style></style></head><body><h1>recovered</h1></body></html>",
        # No head to inject into, so the fallback has to lead.
        "<html><body><h1>recovered</h1></body></html>",
    ):
        pages, width_mm, height_mm = _page_geometry(render_poster_pdf(html))
        assert pages == 1
        assert abs(width_mm - expected_width) <= GEOMETRY_TOLERANCE_MM
        assert abs(height_mm - expected_height) <= GEOMETRY_TOLERANCE_MM


def test_a_poster_that_kept_its_page_rule_is_left_alone() -> None:
    """The fallback must not turn into a second source of page-size authority."""
    from app.DeepAgent.utils.poster_exporter import _ensure_page_rule

    html = f"<html><head><style>{_A3_STYLE}</style></head><body><h1>x</h1></body></html>"

    assert _ensure_page_rule(html) is html


def test_render_failure_tells_the_client_nothing_about_playwright(monkeypatch) -> None:
    """The message reaches the client verbatim through public_error_detail.

    Playwright's own text carries the API name, a call log and the browser's
    install path, so the exporter must answer with a fixed string — the same
    one the router's except-Exception fallback already uses.
    """
    sync_api = pytest.importorskip("playwright.sync_api")
    import app.DeepAgent.utils.poster_exporter as exporter

    def _boom(*args, **kwargs):
        raise sync_api.Error(
            "Page.set_content: Protocol error (Page.navigate): Target closed.\n"
            'Call log:\n  - setting frame content, waiting until "load"\n'
            "  at /ms-playwright/chromium-1217/chrome-linux/headless_shell\n"
        )

    monkeypatch.setattr(exporter, "_launch_chromium", _boom)

    with pytest.raises(PosterServiceError) as excinfo:
        render_poster_pdf(f"<html><head><style>{_A3_STYLE}</style></head></html>")

    message = public_error_detail(excinfo.value)["message"]
    assert "set_content" not in message
    assert "Call log" not in message
    assert "ms-playwright" not in message


def test_missing_chromium_reports_unavailable(monkeypatch) -> None:
    sync_api = pytest.importorskip("playwright.sync_api")

    def _no_executable(*args, **kwargs):
        raise sync_api.Error(
            "Executable doesn't exist at /nowhere/chrome\n"
            "Looks like Playwright was just installed"
        )

    monkeypatch.setattr(sync_api.BrowserType, "launch", _no_executable)

    with pytest.raises(PosterServiceError) as excinfo:
        render_poster_pdf(f"<html><head><style>{_A3_STYLE}</style></head></html>")

    assert excinfo.value.error_code == CODE_PDF_UNAVAILABLE
    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_route_sanitizes_html_and_binds_source_hash(
    client, auth_headers, monkeypatch
) -> None:
    captured: dict[str, str] = {}

    def _fake_render(html: str, *, deadline=None) -> bytes:
        captured["html"] = html
        return b"%PDF-1.4 stub"

    monkeypatch.setattr("routers.reviews.render_poster_pdf", _fake_render)

    response = await client.post(
        "/api/deep-review/poster-pdf",
        headers=auth_headers,
        json={
            "poster_html": (
                "<main><h1>Poster</h1>"
                "<script>window.__pwned = 1</script>"
                '<div onclick="alert(1)">click</div>'
                '<img src="https://attacker.example/pixel.png" alt="tracker">'
                "</main>"
            )
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"

    sanitized = captured["html"]
    assert "<script" not in sanitized
    assert "onclick" not in sanitized
    assert "attacker.example" not in sanitized

    expected = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
    assert response.headers["x-poster-html-sha256"] == expected
    assert expected[:12] in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_cross_origin_response_exposes_the_filename_header(
    client, auth_headers, monkeypatch
) -> None:
    """Content-Disposition is not on the CORS safelist.

    The browser is served from a different origin than the API in production,
    so unless it is exposed the filename the server chose is invisible to the
    download and it silently falls back to 'poster.pdf' — with the header
    still on the wire, which is why a same-origin test cannot catch this.
    """
    from api_server import ALLOWED_ORIGINS

    monkeypatch.setattr(
        "routers.reviews.render_poster_pdf", lambda html, *, deadline=None: b"%PDF-1.4"
    )

    response = await client.post(
        "/api/deep-review/poster-pdf",
        headers={**auth_headers, "Origin": ALLOWED_ORIGINS[0]},
        json={"poster_html": "<main><h1>Poster</h1></main>"},
    )

    assert response.status_code == 200
    exposed = {
        name.strip().lower()
        for name in response.headers["access-control-expose-headers"].split(",")
    }
    assert "content-disposition" in exposed


@pytest.mark.asyncio
async def test_route_rejects_html_with_no_renderable_content(
    client, auth_headers, monkeypatch
) -> None:
    def _never_render(*args, **kwargs):
        raise AssertionError("Chromium must not start for unrenderable input")

    monkeypatch.setattr("routers.reviews.render_poster_pdf", _never_render)

    response = await client.post(
        "/api/deep-review/poster-pdf",
        headers=auth_headers,
        json={"poster_html": "<script>only active content</script>"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "poster_input_invalid"


@pytest.mark.asyncio
async def test_route_requires_authentication(client) -> None:
    response = await client.post(
        "/api/deep-review/poster-pdf", json={"poster_html": "<main>x</main>"}
    )

    assert response.status_code in {401, 403}
