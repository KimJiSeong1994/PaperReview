#!/usr/bin/env python3
"""Submit every indexable jiphyeonjeon.kr URL to IndexNow (Bing/Naver/Yandex/…).

Self-contained (stdlib only) so it runs anywhere — the scheduled GitHub Action
or a laptop. It reads the *live* ``/sitemap.xml`` and submits every ``<loc>`` it
lists (home, blog, category & series hubs, every published post), so it always
tracks the site exactly — new posts and new series hubs are picked up with no
code change, whatever path added them (create API, direct data-file edit +
deploy, …).

IndexNow verifies ownership by fetching ``keyLocation`` from production. The key
is served at the host ROOT (``/<key>.txt``); a key under a subfolder (e.g.
``/api/indexnow/``) would only be allowed to verify URLs in that subfolder, so
``/blog/*`` submissions would be rejected with HTTP 422.

Note: IndexNow does NOT cover Google. Google discovers new posts via the same
auto-updated ``/sitemap.xml`` (there is no reliable push API for Google); a
manual GSC "Request indexing" is the only accelerant and cannot be scripted.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

SITE_URL = os.environ.get("SITE_URL", "https://jiphyeonjeon.kr").rstrip("/")
INDEXNOW_KEY = os.environ.get("INDEXNOW_KEY", "8f3a1c07b94e2d65a0f8c3b12e6d47a9")
HOST = SITE_URL.split("://", 1)[-1].split("/", 1)[0]
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "jiphyeonjeon-indexnow/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed host
        return resp.read()


def build_url_list() -> list[str]:
    """Every <loc> in the live sitemap, restricted to this host."""
    xml = _get(f"{SITE_URL}/sitemap.xml").decode("utf-8", "replace")
    urls = [u for u in _LOC_RE.findall(xml) if u.startswith(SITE_URL)]
    return list(dict.fromkeys(urls))  # dedup, preserve order


def submit(urls: list[str]) -> int:
    payload = json.dumps(
        {
            "host": HOST,
            "key": INDEXNOW_KEY,
            # Root-scoped key so /blog/* and hub URLs pass verification.
            "keyLocation": f"{SITE_URL}/{INDEXNOW_KEY}.txt",
            "urlList": urls,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        INDEXNOW_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed host
        return resp.status


def main() -> int:
    urls = build_url_list()
    if not urls:
        print("ERROR: sitemap yielded no URLs", file=sys.stderr)
        return 1
    status = submit(urls)
    print(f"IndexNow: submitted {len(urls)} URLs -> HTTP {status}")
    # 200 (accepted) and 202 (accepted, queued) are both success.
    return 0 if status in (200, 202) else 1


if __name__ == "__main__":
    raise SystemExit(main())
