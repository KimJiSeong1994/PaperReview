import httpx

from routers import pdf_proxy
from routers.pdf_proxy import _pdf_proxy_response_headers


RLT_PDF_URL = (
    "https://yifanzhang-pro.github.io/recurrent-looped-tranformer/"
    "Recurrent_Looped_Transformer.pdf"
)


def test_pdf_proxy_allows_the_rlt_official_pdf_host(monkeypatch):
    monkeypatch.setattr(pdf_proxy, "_runtime_allowed_domains", set())
    monkeypatch.setattr(pdf_proxy, "_is_private_ip", lambda _hostname: False)

    assert pdf_proxy._is_allowed_url(RLT_PDF_URL)


def test_pdf_proxy_does_not_allow_other_github_pages_hosts(monkeypatch):
    monkeypatch.setattr(
        pdf_proxy, "_runtime_allowed_domains", {"yifanzhang-pro.github.io"}
    )
    monkeypatch.setattr(pdf_proxy, "_is_private_ip", lambda _hostname: False)

    assert not pdf_proxy._is_allowed_url("https://unrelated-project.github.io/paper.pdf")
    assert not pdf_proxy._is_allowed_url(
        "https://child.yifanzhang-pro.github.io/paper.pdf"
    )
    assert not pdf_proxy._is_allowed_url(
        "https://yifanzhang-pro.github.io.attacker.example/paper.pdf"
    )


def test_pdf_proxy_response_headers_preserve_range_metadata():
    headers = httpx.Headers({
        "content-length": "1024",
        "content-range": "bytes 0-1023/2048",
        "accept-ranges": "bytes",
        "etag": '"paper"',
        "last-modified": "Thu, 09 Jul 2026 10:00:00 GMT",
    })

    proxied = _pdf_proxy_response_headers(headers)

    assert proxied["Content-Length"] == "1024"
    assert proxied["Content-Range"] == "bytes 0-1023/2048"
    assert proxied["Accept-Ranges"] == "bytes"
    assert proxied["ETag"] == '"paper"'
    assert proxied["Last-Modified"] == "Thu, 09 Jul 2026 10:00:00 GMT"
    assert proxied["Content-Disposition"] == "inline"


def test_pdf_proxy_response_headers_default_accept_ranges():
    proxied = _pdf_proxy_response_headers(httpx.Headers({}))

    assert proxied["Accept-Ranges"] == "bytes"
