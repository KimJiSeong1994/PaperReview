"""Real Chromium against the built SPA and the real SSR handler; fixture data only."""

from __future__ import annotations

import ast
import asyncio
import functools
import json
import os
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DIST = ROOT / "web-ui/dist"
ORDER = [
    "series-start-title",
    "series-guide-title",
    "series-reading-title",
    "geo-comparison-title",
    "series-evidence-title",
]


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
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.AnnAssign)
        and isinstance(n.target, ast.Name)
        and n.target.id == "BLOG_SERIES"
    )
    raw = json.loads((ROOT / "data/blog/posts.json").read_text())
    wanted = {slug for item in series.values() for slug in item["slugs"]}
    public = {
        p["slug"]: p for p in raw["posts"] if p.get("published") and p["slug"] in wanted
    }
    # List summaries carry the same public shape the API returns (tags, author,
    # dates); the blog page iterates tags even while a chapter is open.
    keys = (
        "id",
        "slug",
        "title",
        "excerpt",
        "reading_time_min",
        "category",
        "thumbnail_url",
        "tags",
        "author",
        "created_at",
        "updated_at",
        "published",
    )
    metadata = [{k: p.get(k) for k in keys} for p in public.values()]
    filler = [
        {
            "id": f"fixture-{i}",
            "slug": f"fixture-{i}",
            "title": f"Unrelated fixture {i}",
            "excerpt": "",
            "reading_time_min": 1,
            "category": "paper-review",
            "tags": [],
            "author": "fixture",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": None,
            "published": True,
            "thumbnail_url": None,
        }
        for i in range(100)
    ]
    gnn = series["gnn"]["slugs"]
    report = {
        "schemaVersion": 1,
        "tool": "playwright",
        "kind": "web-automation-transcript",
        "fixtureOnly": True,
        "actions": [],
        "layouts": [],
        "apiCalls": [],
        "pageErrors": [],
    }

    def record(kind, selector, **facts):
        report["actions"].append(
            {
                "type": kind,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "selector": selector,
                **facts,
            }
        )

    with tempfile.TemporaryDirectory(prefix="series-design-runtime-") as data:
        os.environ.update(
            DATA_DIR=data,
            EVENTS_DB_PATH=f"{data}/events.db",
            PROFILE_DB_PATH=f"{data}/profile.db",
            FEATURE_FLAGS_DB_PATH=f"{data}/flags.db",
            RECOMMENDATIONS_ARTIFACTS_DIR=f"{data}/recommendations",
            OPENAI_API_KEY="sk-test-fixture",
            JWT_SECRET="fixture-jwt-only",
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
        )
        sys.path.insert(0, str(ROOT))
        from routers import seo

        uploaded = Path(data) / "uploaded-dist"
        shutil.copytree(DIST, uploaded, ignore=shutil.ignore_patterns(".*"))
        assert (uploaded / seo._SERIES_MANIFEST).is_file()
        with (
            patch.object(seo, "_load_posts", return_value=list(public.values())),
            patch.object(seo, "_load_deleted", return_value=set()),
            patch.object(seo, "DIST_INDEX", uploaded / "index.html"),
        ):
            ssr = {
                sid: asyncio.run(seo.blog_series_ssr(sid)).body.decode()
                for sid in series
            }
            ssr_post = asyncio.run(seo.blog_post_ssr(gnn[0])).body.decode()
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(Handler, directory=str(uploaded))
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"
        mode = "normal"
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                context = browser.new_context(viewport={"width": 390, "height": 844})
                page = context.new_page()
                page.on("pageerror", lambda e: report["pageErrors"].append(str(e)))

                def route_request(route):
                    url = urlsplit(route.request.url)
                    if url.hostname != "127.0.0.1":
                        route.abort()
                    elif url.path == "/api/blog/posts":
                        number = int(parse_qs(url.query).get("page", ["1"])[0])
                        report["apiCalls"].append({"page": number, "mode": mode})
                        if mode == "failure":
                            route.fulfill(
                                status=503,
                                json={"detail": "controlled_fixture_failure"},
                            )
                        else:
                            posts = filler if number == 1 else metadata
                            route.fulfill(
                                json={
                                    "posts": posts,
                                    "total": 100 + len(metadata),
                                    "page": number,
                                    "pages": 2,
                                }
                            )
                    elif url.path.startswith("/api/blog/posts/"):
                        slug = url.path.rsplit("/", 1)[1]
                        if slug in public:
                            route.fulfill(
                                json={
                                    **public[slug],
                                    "content": "# Fixture\n\nControlled article body.",
                                    "deep_content": None,
                                }
                            )
                        else:
                            route.fulfill(status=404, json={"detail": "not found"})
                    elif url.path.startswith("/api/blog/figures/"):
                        route.fulfill(
                            status=200,
                            content_type="image/png",
                            body=(ROOT / "web-ui/public/icon-192.png").read_bytes(),
                        )
                    elif url.path.startswith("/api/"):
                        route.fulfill(
                            status=401, json={"detail": "fixture_unauthenticated"}
                        )
                    else:
                        route.continue_()

                context.route("**/*", route_request)
                for theme in ("light", "dark"):
                    for width in (320, 390, 768, 1280):
                        page.set_viewport_size({"width": width, "height": 844})
                        page.goto(base + "/blog/series/gnn")
                        page.evaluate(
                            "theme => document.documentElement.setAttribute('data-theme', theme)",
                            theme,
                        )
                        expect(page.locator(".blog-series-list > li")).to_have_count(11)
                        expect(page.locator(".blog-app-header")).to_be_visible()
                        expect(page.locator("main#main")).to_be_visible()
                        box = page.locator(".blog-series-start-cta").bounding_box()
                        title = page.locator("#series-start-title").bounding_box()
                        assert (
                            box
                            and title
                            and box["y"] + box["height"] <= 844
                            and title["y"] >= 0
                        )
                        metrics = page.evaluate(
                            """(order) => {
                              const tops = order.map(id => document.getElementById(id).getBoundingClientRect().top + scrollY);
                              const cs = sel => getComputedStyle(document.querySelector(sel));
                              return {
                                overflow: document.documentElement.scrollWidth > innerWidth + 1,
                                ordered: tops.every((t, i) => i === 0 || t > tops[i - 1]),
                                excerptPx: parseFloat(cs('.blog-row-excerpt').fontSize),
                                keepAll: cs('main#main').wordBreak,
                                h1Px: parseFloat(cs('h1').fontSize),
                                h2Px: parseFloat(cs('#series-reading-title').fontSize),
                                h3Px: parseFloat(cs('.blog-series-stage h3').fontSize),
                                targets: [...document.querySelectorAll('.blog-series-start-cta,.blog-series-nav a,.blog-series-path a,.blog-row')].map(e => e.getBoundingClientRect().height),
                                summaryCells: document.querySelectorAll('.geo-decision dd').length,
                                evidenceCells: document.querySelectorAll('.geo-evidence dd').length,
                                statePills: document.querySelectorAll('.geo-state').length,
                                minutes: document.querySelectorAll('.blog-series-time').length,
                                thumbs: document.querySelectorAll('.blog-series-list .blog-row-thumb img').length,
                              };
                            }""",
                            ORDER,
                        )
                        assert not metrics["overflow"] and metrics["ordered"], metrics
                        assert (
                            metrics["excerptPx"] >= 16
                            and metrics["keepAll"] == "keep-all"
                        )
                        assert metrics["h1Px"] > metrics["h2Px"] > metrics["h3Px"], (
                            metrics
                        )
                        assert min(metrics["targets"]) >= 44
                        assert (
                            metrics["summaryCells"] == 12
                            and metrics["evidenceCells"] == 24
                        )
                        assert metrics["statePills"] >= 7 and metrics["minutes"] >= 11
                        page.screenshot(
                            path=str(OUT / f"new-start-{theme}-{width}.png")
                        )
                        page.locator(
                            '.blog-series-nav a[href="#geo-comparison-title"]'
                        ).click()
                        page.screenshot(
                            path=str(OUT / f"new-compare-{theme}-{width}.png")
                        )
                        record(
                            "click",
                            '.blog-series-nav a[href="#geo-comparison-title"]',
                            theme=theme,
                            width=width,
                        )
                        report["layouts"].append(
                            {"theme": theme, "width": width, **metrics}
                        )
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(OUT / "new-full-mobile.png"), full_page=True)
                page.set_viewport_size({"width": 1280, "height": 844})
                page.goto(base + "/blog/series/gnn")
                expect(page.locator(".blog-series-list > li")).to_have_count(11)
                page.screenshot(path=str(OUT / "new-full-desktop.png"), full_page=True)

                # Hash deep link survives hydration.
                page.set_viewport_size({"width": 390, "height": 844})
                page.goto(base + "/blog/series/gnn#series-evidence-2")
                expect(page.locator(".blog-series-list > li")).to_have_count(11)
                page.wait_for_timeout(300)
                top = page.locator("#series-evidence-2").bounding_box()["y"]
                assert -4 <= top <= 200, top
                record(
                    "navigate",
                    "#series-evidence-2",
                    hashRestoredAfterHydration=True,
                    top=top,
                )

                # Article end-of-series nav names the next chapter on a deep link.
                page.goto(base + "/blog/" + gnn[0])
                nav = page.get_by_role("navigation", name="시리즈 이어 읽기")
                expect(nav).to_be_visible()
                expect(nav.locator("a[rel=next]")).to_contain_text(
                    public[gnn[1]]["title"]
                )
                expect(nav.locator("a[rel=next]")).to_have_attribute(
                    "href", "/blog/" + gnn[1]
                )
                page.screenshot(path=str(OUT / "new-post-end-nav-390.png"))
                record("navigate", "/blog/" + gnn[0], endOfArticleNextNamed=True)

                # Theme toggle now exists on the series page.
                page.goto(base + "/blog/series/graphrag")
                expect(page.locator(".blog-series-list > li")).to_have_count(11)
                expect(
                    page.locator(".geo-decision-grid[data-count='3']")
                ).to_be_visible()
                page.locator(
                    ".blog-app-header .theme-toggle, .blog-app-header button[aria-label]"
                ).first.click()
                record(
                    "click", ".blog-app-header theme toggle", themeToggleOnSeries=True
                )

                # Failure / retry still truthful.
                mode = "failure"
                page.goto(base + "/blog/series/gnn")
                expect(page.get_by_role("alert")).to_contain_text("불러오지 못했습니다")
                expect(page.locator(".blog-series-start-cta")).to_have_count(0)
                mode = "normal"
                page.get_by_role("button", name="다시 시도").click()
                expect(page.locator(".blog-series-list > li")).to_have_count(11)
                record("click", "다시 시도", retryRecovered=True)

                # SSR without JavaScript: styled, ordered, and the post's end nav names the next chapter.
                nojs = browser.new_context(
                    java_script_enabled=False, viewport={"width": 390, "height": 844}
                )

                def ssr_route(route):
                    url = urlsplit(route.request.url)
                    sid = url.path.rsplit("/", 1)[-1]
                    if url.hostname != "127.0.0.1":
                        route.abort()
                    elif url.path.startswith("/blog/series/") and sid in ssr:
                        route.fulfill(content_type="text/html", body=ssr[sid])
                    elif url.path == "/blog/" + gnn[0]:
                        route.fulfill(content_type="text/html", body=ssr_post)
                    else:
                        route.continue_()

                nojs.route("**/*", ssr_route)
                reader = nojs.new_page()
                for sid in series:
                    reader.goto(base + "/blog/series/" + sid)
                    expect(reader.locator(".blog-series-start-cta")).to_be_visible()
                    assert (
                        reader.locator(".blog-series-start-cta").evaluate(
                            "el => getComputedStyle(el).display"
                        )
                        == "inline-flex"
                    )
                    if sid == "gnn":
                        ok = reader.evaluate(
                            "(order) => { const t = order.map(id => document.getElementById(id).getBoundingClientRect().top + scrollY); return t.every((v, i) => i === 0 || v > t[i-1]); }",
                            ORDER,
                        )
                        assert ok
                        reader.screenshot(path=str(OUT / "new-ssr-nojs-390.png"))
                    record("navigate", "/blog/series/" + sid, javaScript=False)
                reader.goto(base + "/blog/" + gnn[0])
                end_nav = reader.get_by_role("navigation", name="시리즈 이어 읽기")
                expect(end_nav.locator("a[rel=next]")).to_contain_text(
                    public[gnn[1]]["title"]
                )
                # Top pill + end nav both point at chapter 2; no chronological block.
                hrefs = reader.locator("a[rel=next]").evaluate_all(
                    "els => els.map(e => e.getAttribute('href'))"
                )
                assert hrefs and set(hrefs) == {"/blog/" + gnn[1]}, hrefs
                expect(reader.locator(".blog-prevnext")).to_have_count(0)
                record(
                    "navigate",
                    "/blog/" + gnn[0],
                    javaScript=False,
                    seriesOrderPrevNext=True,
                )
                assert not report["pageErrors"], report["pageErrors"]
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)
    report["limitations"] = (
        "Built SPA + real SSR handler with fixture metadata/API; not production browsing or accessibility certification."
    )
    (OUT / "browser-transcript.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "actions": len(report["actions"]),
                "layouts": len(report["layouts"]),
                "apiCalls": len(report["apiCalls"]),
            }
        )
    )


if __name__ == "__main__":
    main()
