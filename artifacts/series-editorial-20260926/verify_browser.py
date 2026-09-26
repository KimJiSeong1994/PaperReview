"""Real Chromium, built SPA, real SSR handler; fixture metadata and no external calls."""

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
    metadata = [
        {k: p.get(k, "") for k in ("slug", "title", "excerpt", "reading_time_min")}
        for p in public.values()
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

    with tempfile.TemporaryDirectory(prefix="series-editorial-runtime-") as data:
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
        assert not (uploaded / ".vite").exists()
        record(
            "artifact-stage",
            "uploaded-dist",
            excludesHiddenFiles=True,
            manifestPreserved=True,
        )
        with (
            patch.object(seo, "_load_posts", return_value=list(public.values())),
            patch.object(seo, "_load_deleted", return_value=set()),
            patch.object(seo, "DIST_INDEX", uploaded / "index.html"),
        ):
            ssr = {
                sid: asyncio.run(seo.blog_series_ssr(sid)).body.decode()
                for sid in series
            }
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
                            members = (
                                metadata
                                if mode != "missing-first"
                                else [
                                    p
                                    for p in metadata
                                    if p["slug"] != series["gnn"]["slugs"][0]
                                ]
                            )
                            posts = filler if number == 1 else members
                            if mode == "empty":
                                posts = []
                            route.fulfill(
                                json={
                                    "posts": posts,
                                    "total": len(filler) + len(members),
                                    "page": 0 if mode == "invalid-page" else number,
                                    "pages": 1 if mode == "empty" else 2,
                                }
                            )
                    elif url.path.startswith("/api/blog/posts/"):
                        slug = url.path.rsplit("/", 1)[1]
                        if slug in public:
                            route.fulfill(
                                json={
                                    **public[slug],
                                    "content": "# Public fixture\n\nThis is the controlled article navigation fixture.",
                                    "deep_content": None,
                                }
                            )
                        else:
                            route.fulfill(status=404, json={"detail": "not found"})
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
                        expect(page.locator("html")).to_have_attribute("lang", "ko")
                        box = page.locator(".blog-series-start-cta").bounding_box()
                        title = page.locator("#series-start-title").bounding_box()
                        assert (
                            box
                            and title
                            and box["y"] >= 0
                            and box["y"] + box["height"] <= 844
                        )
                        assert title["y"] >= 0 and title["y"] + title["height"] <= 844
                        metrics = page.evaluate("""() => ({overflow: document.documentElement.scrollWidth > innerWidth + 1,
                          excerptPx: parseFloat(getComputedStyle(document.querySelector('.blog-series-item-excerpt')).fontSize),
                          targets: [...document.querySelectorAll('.blog-series-start-cta,.blog-series-nav a,.blog-series-path a')].map(e => e.getBoundingClientRect().height),
                          summaryCells: document.querySelectorAll('.geo-decision dd').length,
                          evidenceCells: document.querySelectorAll('.geo-evidence dd').length})""")
                        assert (
                            not metrics["overflow"]
                            and metrics["excerptPx"] >= 16
                            and min(metrics["targets"]) >= 44
                        )
                        assert (
                            metrics["summaryCells"] == 12
                            and metrics["evidenceCells"] == 24
                        )
                        page.screenshot(path=str(OUT / f"start-{theme}-{width}.png"))
                        page.locator(
                            '.blog-series-nav a[href="#geo-comparison-title"]'
                        ).click()
                        page.screenshot(path=str(OUT / f"compare-{theme}-{width}.png"))
                        record(
                            "click",
                            '.blog-series-nav a[href="#geo-comparison-title"]',
                            theme=theme,
                            width=width,
                            firstPaperVisible=True,
                        )
                        report["layouts"].append(
                            {
                                "theme": theme,
                                "width": width,
                                "ctaBottom": box["y"] + box["height"],
                                **metrics,
                            }
                        )
                page.set_viewport_size({"width": 390, "height": 844})
                page.goto(base + "/blog/series/gnn")
                expect(page.locator(".blog-series-start-cta")).to_be_visible()
                page.locator(".blog-series-start-cta").focus()
                page.keyboard.press("Enter")
                expect(page).to_have_url(base + "/blog/" + series["gnn"]["slugs"][0])
                expect(
                    page.get_by_text(
                        "This is the controlled article navigation fixture."
                    )
                ).to_be_visible()
                record(
                    "keypress",
                    ".blog-series-start-cta",
                    key="Enter",
                    articleNavigation=True,
                )
                page.goto(base + "/blog/series/gnn")
                expect(page.locator(".blog-series-list > li")).to_have_count(11)
                page.locator(".geo-decision .blog-series-text-link").first.focus()
                page.keyboard.press("Enter")
                expect(page).to_have_url(base + "/blog/series/gnn#series-evidence-1")
                record(
                    "keypress",
                    ".geo-decision .blog-series-text-link",
                    key="Enter",
                    evidenceJump=True,
                )
                page.add_style_tag(
                    content=".blog-series-page p,.blog-series-page dd,.blog-series-page dt,.blog-series-page a,.blog-series-page h1,.blog-series-page h2,.blog-series-page h3 { font-size: 200% !important; }"
                )
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth + 1"
                )
                page.locator(".blog-series-start-cta").focus()
                expect(page.locator(".blog-series-start-cta")).to_be_in_viewport()
                page.screenshot(path=str(OUT / "text-enlarged-390.png"))
                record(
                    "focus",
                    ".blog-series-start-cta",
                    enlargedText="targeted CSS text enlargement, not browser zoom",
                    overflow=False,
                )
                for sid in ("graphrag", "dwe", "graph-causality", "jiphyeonjeon-build"):
                    for width in (320, 390):
                        page.set_viewport_size({"width": width, "height": 844})
                        page.goto(base + "/blog/series/" + sid)
                        expect(page.locator(".blog-series-start-cta")).to_be_visible()
                        expect(page.locator(".blog-series-list > li")).to_have_count(
                            sum(s in public for s in series[sid]["slugs"])
                        )
                        box = page.locator(".blog-series-start-cta").bounding_box()
                        assert box and box["y"] + box["height"] <= 844
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth + 1"
                        )
                        page.screenshot(path=str(OUT / f"start-{sid}-{width}.png"))
                        record(
                            "navigate",
                            "/blog/series/" + sid,
                            width=width,
                            completeMembership=True,
                            firstPaperVisible=True,
                        )
                for state in ("missing-first", "failure", "empty", "invalid-page"):
                    mode = state
                    page.goto(base + "/blog/series/gnn")
                    if state == "missing-first":
                        expect(
                            page.locator(".blog-series-start-cta")
                        ).to_have_attribute(
                            "href", "/blog/" + series["gnn"]["slugs"][1]
                        )
                    elif state == "empty":
                        expect(page.get_by_role("status")).to_contain_text(
                            "아직 공개된"
                        )
                        expect(page.locator(".blog-series-start-cta")).to_have_count(0)
                    else:
                        expect(page.get_by_role("alert")).to_contain_text(
                            "불러오지 못했습니다"
                        )
                        expect(page.locator(".blog-series-start-cta")).to_have_count(0)
                        mode = "normal"
                        page.get_by_role("button", name="다시 시도").click()
                        expect(page.locator(".blog-series-list > li")).to_have_count(11)
                    record(
                        "navigate",
                        "/blog/series/gnn",
                        adversarialState=state,
                        passed=True,
                    )
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
                    else:
                        route.continue_()

                nojs.route("**/*", ssr_route)
                reader = nojs.new_page()
                for sid in series:
                    reader.goto(base + "/blog/series/" + sid)
                    expect(reader.locator(".blog-series-start-cta")).to_be_visible()
                    expect(reader.locator(".blog-series-list > li")).to_have_count(
                        sum(s in public for s in series[sid]["slugs"])
                    )
                    expect(reader.locator("html")).to_have_attribute("lang", "ko")
                    box = reader.locator(".blog-series-start-cta").bounding_box()
                    assert (
                        box and box["height"] >= 44 and box["y"] + box["height"] <= 844
                    )
                    assert reader.locator(".blog-series-start-cta").evaluate(
                        "el => getComputedStyle(el).display === 'inline-flex'"
                    ), "No-JS SSR must load the lazy series stylesheet"
                    if sid == "gnn":
                        reader.screenshot(path=str(OUT / "ssr-nojs-390.png"))
                    record(
                        "navigate",
                        "/blog/series/" + sid,
                        javaScript=False,
                        renderer="real SEO handler with fixture metadata",
                    )
                assert not report["pageErrors"], report["pageErrors"]
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)
    report["limitations"] = (
        "Fixture public metadata/API, no production requests. Text enlargement uses targeted CSS, not browser zoom. Screenshot review remains distinct from dimension assertions."
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
                "fixtureOnly": True,
            }
        )
    )


if __name__ == "__main__":
    main()
