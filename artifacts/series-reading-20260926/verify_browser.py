"""Fixture-only Chromium qualification of the built series UI; no external calls."""

from __future__ import annotations

import ast
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DIST = ROOT / "web-ui/dist"


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if not Path(self.translate_path(self.path)).is_file():
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, *_args):
        pass


def main():
    tree = ast.parse((ROOT / "routers/seo.py").read_text())
    series = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "BLOG_SERIES"
    )
    raw = json.loads((ROOT / "data/blog/posts.json").read_text())
    published = {post["slug"]: post for post in raw["posts"] if post.get("published")}
    wanted = list(
        dict.fromkeys(slug for item in series.values() for slug in item["slugs"])
    )
    members = [
        {
            key: published[slug].get(key, "")
            for key in ("slug", "title", "excerpt", "reading_time_min")
        }
        for slug in wanted
        if slug in published
    ]
    filler = [
        {
            "slug": f"fixture-{i}",
            "title": f"Unrelated fixture {i}",
            "excerpt": "",
            "reading_time_min": 1,
        }
        for i in range(100)
    ]
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Handler, directory=str(DIST))
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    calls, scenarios, errors = [], [], []
    fail = False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.on("pageerror", lambda error: errors.append(str(error)))

            def route_request(route):
                nonlocal fail
                url = urlsplit(route.request.url)
                if url.hostname != "127.0.0.1":
                    route.abort()
                elif url.path == "/api/blog/posts":
                    number = int(parse_qs(url.query).get("page", ["1"])[0])
                    calls.append(number)
                    if fail:
                        route.fulfill(
                            status=503, json={"detail": "controlled_fixture_failure"}
                        )
                    else:
                        route.fulfill(
                            json={
                                "posts": filler if number == 1 else members,
                                "total": len(filler) + len(members),
                                "page": number,
                                "pages": 2,
                            }
                        )
                elif url.path.startswith("/api/"):
                    route.fulfill(
                        status=401, json={"detail": "fixture_unauthenticated"}
                    )
                else:
                    route.continue_()

            page.route("**/*", route_request)
            for theme in ("light", "dark"):
                for width in (320, 390, 768, 1280):
                    page.set_viewport_size({"width": width, "height": 844})
                    page.goto(base + "/blog/series/gnn")
                    page.evaluate(
                        "theme => { document.documentElement.setAttribute('data-theme', theme); document.documentElement.classList.toggle('dark', theme === 'dark'); }",
                        theme,
                    )
                    expect(page.locator(".blog-series-list > li")).to_have_count(
                        len(series["gnn"]["slugs"])
                    )
                    mobile = width < 768
                    expect(
                        page.locator(".geo-comparison-cards")
                    ).to_be_visible() if mobile else expect(
                        page.locator(".geo-comparison-cards")
                    ).not_to_be_visible()
                    expect(
                        page.locator(".geo-comparison-desktop")
                    ).not_to_be_visible() if mobile else expect(
                        page.locator(".geo-comparison-desktop")
                    ).to_be_visible()
                    metrics = page.evaluate("""() => ({
                        overflow: document.documentElement.scrollWidth > innerWidth + 1,
                        excerptSize: parseFloat(getComputedStyle(document.querySelector('.blog-series-item-excerpt')).fontSize),
                        targets: [...document.querySelectorAll('.blog-series-nav a')].map(el => el.getBoundingClientRect().height),
                        limitsBeforeEvidence: !!(document.querySelector('.geo-comparison-limits').compareDocumentPosition(document.querySelector('.geo-comparison-scroll')) & Node.DOCUMENT_POSITION_FOLLOWING)
                    })""")
                    assert not metrics["overflow"], (theme, width, metrics)
                    assert metrics["excerptSize"] >= 16
                    assert min(metrics["targets"]) >= 44
                    assert metrics["limitsBeforeEvidence"]
                    page.screenshot(
                        path=str(OUT / f"gnn-{theme}-{width}.jpg"),
                        type="jpeg",
                        quality=80,
                    )
                    page.get_by_role("navigation", name="시리즈 바로가기").get_by_role(
                        "link", name="논문 선택 비교"
                    ).click()
                    page.screenshot(
                        path=str(OUT / f"comparison-{theme}-{width}.jpg"),
                        type="jpeg",
                        quality=80,
                    )
                    scenarios.append({"theme": theme, "width": width, **metrics})
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(base + "/blog/series/graphrag")
            expect(page.locator(".blog-series-list > li")).to_have_count(
                len(series["graphrag"]["slugs"])
            )
            expect(page.locator(".geo-comparison-card")).to_have_count(3)
            fail = True
            page.goto(base + "/blog/series/gnn")
            expect(page.get_by_role("alert")).to_contain_text("불러오지 못했습니다")
            expect(page.locator(".blog-series-list > li")).to_have_count(0)
            expect(page.locator(".geo-comparison-card").first).to_contain_text("GCN")
            fail = False
            page.get_by_role("button", name="다시 시도").click()
            expect(page.locator(".blog-series-list > li")).to_have_count(11)
            assert 2 in calls, (
                "Older members must be fetched beyond the first 100 posts"
            )
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
    receipt = {
        "fixtureOnly": True,
        "layoutScenarios": scenarios,
        "apiPagesRequested": calls,
        "graphRagVerified": True,
        "failureAndRetryVerified": True,
        "pageErrors": errors,
        "limitations": "Built SPA with fixture API; not production browsing or full assistive-technology certification.",
    }
    (OUT / "browser-transcript.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "layoutScenarios": len(scenarios),
                "apiCalls": len(calls),
                "fixtureOnly": True,
            }
        )
    )


if __name__ == "__main__":
    main()
