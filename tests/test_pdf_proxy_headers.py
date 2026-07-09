import httpx

from routers.pdf_proxy import _pdf_proxy_response_headers


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
