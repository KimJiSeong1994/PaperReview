"""Actual Chromium + local API, using disposable synthetic fixtures only."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


async def main():
    report = {
        "schemaVersion": 1,
        "tool": "playwright",
        "kind": "web-automation-transcript",
        "evidence_scope": "Real built frontend and real recommendation/auth APIs; disposable synthetic papers/accounts. Controlled 503 tests UI failure only. No provider/source qualification.",
        "actions": [],
    }
    traffic = []

    def record(action, selector, **facts):
        report["actions"].append(
            {
                "type": action,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "selector": selector,
                **facts,
            }
        )

    with tempfile.TemporaryDirectory(prefix="recommendation-browser-qa-") as temporary:
        data = Path(temporary).resolve()
        os.environ.update(
            DATA_DIR=str(data),
            EVENTS_DB_PATH=str(data / "events.db"),
            PROFILE_DB_PATH=str(data / "profile.db"),
            FEATURE_FLAGS_DB_PATH=str(data / "feature_flags.db"),
            MCP_ANALYTICS_DB_PATH=str(data / "mcp.db"),
            RECOMMENDATIONS_ARTIFACTS_DIR=str(data / "recommendations"),
            OPENAI_API_KEY="sk-fixture-not-used",
            JWT_SECRET="local-browser-fixture-secret-not-production",
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
        )
        from src.collector.paper import google_scholar_searcher
        from src.collector.paper import similarity_calculator

        similarity_calculator._DEFAULT_CACHE_DB = data / "embedding-cache.db"

        original_cookie_loader = (
            google_scholar_searcher.GoogleScholarSearcher._load_cookies
        )

        def load_isolated_cookies(searcher):
            searcher.cookies_file = data / "scholar-cookies.pkl"
            return original_cookie_loader(searcher)

        google_scholar_searcher.GoogleScholarSearcher._load_cookies = (
            load_isolated_cookies
        )

        import uvicorn
        import api_server as api
        from routers.auth import _hash_password
        from src.storage.user_db import UserDB
        from src.events.event_bus import init_event_bus
        from src.recommendation_state import RecommendationState
        from src.recommendation_candidates import (
            TrustedReceiverPolicy,
            make_candidate_snapshot,
            write_candidate_snapshot,
        )
        from src.daily_recommendations import generate_daily_recommendations
        import routers.reviews as review_routes
        from app.DeepAgent import workspace_manager

        original_workspace = workspace_manager.WorkspaceManager
        workspace_manager.WorkspaceManager = lambda: original_workspace(
            base_path=str(data / "workspace")
        )
        controlled_review_starts = []

        async def controlled_review_background(**kwargs):
            # Exercise actual review-start acceptance, never a provider or review result.
            controlled_review_starts.append(kwargs["session_id"])

        review_routes.run_deep_review_background = controlled_review_background

        # Unrelated optional outbound startup work is disabled in this harness;
        # authentication, recommendation handlers/storage/ranking are unchanged.
        api.INDEXNOW_ENABLED = False
        api._warm_cross_encoder = lambda: None
        users = UserDB(data / "users.db")
        account = users.create_account(
            "browser-fixture",
            {"role": "user", "password_hash": _hash_password("fixture-password")},
        )
        init_event_bus(data / "events.db")
        RecommendationState.initialize(data / "events.db", authority=users)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        papers = [
            {
                "title": f"Synthetic browser fixture {n:02d}",
                "authors": ["Fixture Author"],
                "openalex_id": f"W{100000 + n}",
                "year": now.year,
                "publication_date": f"{now.year}-01-01",
                "url": f"https://example.org/fixture/{n}",
            }
            for n in range(1, 15)
        ]
        snapshot = make_candidate_snapshot(
            papers,
            policy=TrustedReceiverPolicy(
                "local_public",
                "public",
                "public-seeds-v1",
                public_source_qualified=True,
            ),
            source_run_id="synthetic-browser-fixture",
            collected_at=now,
            now=now,
        )
        write_candidate_snapshot(
            snapshot, root=data / "candidates", final_root=data / "recommendations"
        )
        generated = generate_daily_recommendations(
            users_db=data / "users.db",
            candidate_root=data / "candidates",
            events_db=data / "events.db",
            bookmarks_db=data / "bookmarks.db",
            artifacts_dir=data / "recommendations",
            run_at=now.isoformat(),
            min_score=0,
        )
        assert generated["publish_success"] == 1
        artifact = next(
            (data / "recommendations" / account["account_incarnation"]).glob("*.json")
        )
        original = json.loads(artifact.read_text())
        server = uvicorn.Server(
            uvicorn.Config(api.app, host="127.0.0.1", port=0, log_level="warning")
        )
        server_task = asyncio.create_task(server.serve())
        for _ in range(100):
            if server.started:
                break
            if server_task.done():
                await server_task
                raise AssertionError("Local API failed to start")
            await asyncio.sleep(0.1)
        assert server.started
        backend = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            preview_port = sock.getsockname()[1]
        preview_out = (OUT / "preview.stdout").open("w")
        preview_err = (OUT / "preview.stderr").open("w")
        preview = subprocess.Popen(
            [
                "npm",
                "run",
                "preview",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                str(preview_port),
                "--strictPort",
            ],
            cwd=ROOT / "web-ui",
            stdout=preview_out,
            stderr=preview_err,
            start_new_session=True,
        )
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                    headless=True,
                )
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 1000}
                )
                for _ in range(100):
                    assert preview.poll() is None
                    try:
                        response = await context.request.get(
                            f"http://127.0.0.1:{preview_port}/", timeout=500
                        )
                        if response.ok:
                            break
                    except Exception:
                        await asyncio.sleep(0.1)
                login = await context.request.post(
                    backend + "/api/auth/login",
                    data={
                        "username": "browser-fixture",
                        "password": "fixture-password",
                    },
                )
                assert login.ok, await login.text()
                token = (await login.json())["access_token"]
                page = await context.new_page()
                await page.add_init_script(
                    "localStorage.setItem('access_token', "
                    + json.dumps(token)
                    + "); localStorage.setItem('username','browser-fixture');"
                )
                controlled_failure = False

                async def route_api(route):
                    path = urlsplit(route.request.url).path
                    if path.startswith(("/api/auth/", "/api/recommendations/")):
                        if controlled_failure and path.endswith("/notifications"):
                            await route.fulfill(
                                status=503,
                                content_type="application/json",
                                body='{"detail":"policy_unavailable"}',
                            )
                            traffic.append(
                                {"path": path, "status": 503, "controlled": True}
                            )
                            return
                        response = await route.fetch(
                            url=backend
                            + path
                            + (
                                "?" + urlsplit(route.request.url).query
                                if urlsplit(route.request.url).query
                                else ""
                            )
                        )
                        body = await response.json()
                        traffic.append(
                            {
                                "path": path,
                                "method": route.request.method,
                                "status": response.status,
                                "request": route.request.post_data_json
                                if route.request.post_data
                                else None,
                                "response": body
                                if path.startswith("/api/recommendations/")
                                else {"authenticated": response.ok},
                            }
                        )
                        await route.fulfill(response=response)
                    else:
                        await route.fulfill(
                            status=200, content_type="application/json", body="{}"
                        )

                await page.route("**/api/**", route_api)
                await page.goto(
                    f"http://127.0.0.1:{preview_port}/", wait_until="domcontentloaded"
                )
                bell = page.get_by_role("button", name="추천 논문 열기")
                await bell.wait_for()
                await page.wait_for_timeout(1100)
                assert not any(row["path"].endswith("/exposure") for row in traffic)
                await bell.click()
                cards = page.locator("article[data-canonical-key]")
                await expect(cards).to_have_count(5)
                initial = await cards.evaluate_all(
                    "els => els.map(e => e.dataset.canonicalKey)"
                )
                latest = next(
                    row["response"]
                    for row in reversed(traffic)
                    if row["path"].endswith("/notifications")
                )
                assert initial == [item["canonical_key"] for item in latest["items"]]
                assert not any(item["seen"] for item in latest["items"])
                await page.wait_for_timeout(1300)
                exposures = [
                    row for row in traffic if row["path"].endswith("/exposure")
                ]
                assert exposures and all(
                    row["request"]["visible_fraction"] >= 0.5
                    and row["request"]["visible_ms"] >= 1000
                    for row in exposures
                )
                record(
                    "rank-order-and-real-visibility",
                    "article[data-canonical-key]",
                    canonical_keys=initial,
                    qualified_exposures=len(exposures),
                    exposure_is_not_read=True,
                )
                viewed_key = exposures[0]["request"]["canonical_key"]
                viewed = next(
                    item
                    for item in latest["items"]
                    if item["canonical_key"] == viewed_key
                )
                await page.evaluate(
                    "window.open = (href) => { window.fixtureViewerHref = href; return null; }"
                )
                viewed_card = page.locator(
                    f'article[data-canonical-key="{viewed_key}"]'
                )
                await viewed_card.get_by_role(
                    "button", name="PDF 보기", exact=True
                ).click()
                await expect(
                    viewed_card.get_by_text("읽음", exact=True)
                ).to_be_visible()
                viewer_identity = await page.evaluate(
                    "() => Object.fromEntries(new URL(window.fixtureViewerHref, location.origin).searchParams)"
                )
                assert viewer_identity["openalex_id"] == viewed["openalex_id"]
                assert viewer_identity["result_key"] == viewed_key
                record(
                    "provider-viewer-handoff",
                    'button:has-text("PDF 보기")',
                    provider_id=viewer_identity["openalex_id"],
                    canonical_key=viewer_identity["result_key"],
                    popup="captured and suppressed; no external PDF navigation",
                )
                headers = {"Authorization": "Bearer " + token}
                bookmark_payload = {
                    "title": viewed["title"],
                    "authors": viewed["authors"],
                    "openalex_id": viewed["openalex_id"],
                    "year": viewed["year"],
                }
                saved = await context.request.post(
                    backend + "/api/bookmarks/from-paper",
                    headers=headers,
                    data=bookmark_payload,
                )
                assert saved.ok, await saved.text()
                saved_body = await saved.json()
                assert saved_body["recommendation_attribution"][0]["credited"]
                assert (
                    saved_body["recommendation_attribution"][0]["canonical_key"]
                    == viewed_key
                )
                assert viewed_key == "provider:openalex:" + viewed["openalex_id"]
                repeated = await context.request.post(
                    backend + "/api/bookmarks/from-paper",
                    headers=headers,
                    data=bookmark_payload,
                )
                assert repeated.ok, await repeated.text()
                repeated_body = await repeated.json()
                assert not repeated_body["recommendation_attribution"][0]["credited"]
                started = await context.request.post(
                    backend + "/api/deep-review",
                    headers=headers,
                    data={"paper_ids": [viewed_key], "papers": [viewed]},
                )
                assert started.ok, await started.text()
                started_body = await started.json()
                assert started_body["recommendation_attribution"][0]["credited"]
                for path, response in [
                    ("/api/bookmarks/from-paper", saved_body),
                    ("/api/bookmarks/from-paper", repeated_body),
                    ("/api/deep-review", started_body),
                ]:
                    traffic.append(
                        {
                            "path": path,
                            "method": "POST",
                            "status": 200,
                            "response": response,
                            "surface": "actual-api",
                        }
                    )
                day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                outcome_state = RecommendationState(data / "events.db", authority=users)
                metrics = outcome_state.outcome_metrics(
                    account["account_incarnation"],
                    since=day_start,
                    until=day_start + timedelta(days=1),
                    now=day_start + timedelta(days=9),
                )
                assert metrics["mature"]["visible_userdays"] == 1
                assert metrics["mature"]["positive_userdays"] == 1
                assert metrics["mature"]["per_kind_counts"] == {
                    "save": 1,
                    "review_start": 1,
                }
                record(
                    "viewed-save-and-review-start-attribution",
                    "/api/bookmarks/from-paper; /api/deep-review",
                    surface="api",
                    canonical_key=viewed_key,
                    metrics=metrics,
                    metrics_clock="controlled day-start plus nine days",
                    review_work="controlled background; no provider or completed-review claim",
                    duplicate_save_credited=False,
                )
                await page.screenshot(
                    path=str(OUT / "desktop.jpg"),
                    type="jpeg",
                    quality=95,
                    full_page=True,
                )
                await cards.first.get_by_role(
                    "button", name="숨기기", exact=True
                ).click()
                await expect(
                    page.locator(f'article[data-canonical-key="{initial[0]}"]')
                ).to_have_count(0)
                await expect(cards).to_have_count(5)
                hide_undo = (
                    page.locator(".recommendation-receipts > div")
                    .filter(has_text=": 숨기기")
                    .get_by_role("button", name="실행 취소")
                )
                await expect(hide_undo).to_be_enabled()
                hidden_order = await cards.evaluate_all(
                    "els => els.map(e => e.dataset.canonicalKey)"
                )
                assert hidden_order[:4] == initial[1:]
                await hide_undo.click()
                await expect(cards.first).to_have_attribute(
                    "data-canonical-key", initial[0]
                )
                record(
                    "durable-hide-refill-undo",
                    'button:has-text("숨기기")',
                    refilled_keys=hidden_order,
                    restored_key=initial[0],
                )
                read_key = await cards.filter(
                    has=page.get_by_text("읽지 않음", exact=True)
                ).first.get_attribute("data-canonical-key")
                read_card = page.locator(f'article[data-canonical-key="{read_key}"]')
                await read_card.get_by_role(
                    "button", name="읽음 표시", exact=True
                ).click()
                await expect(
                    read_card.get_by_role("button", name="읽음 표시", exact=True)
                ).to_be_disabled()
                record(
                    "durable-read",
                    'button:has-text("읽음 표시")',
                    canonical_key=read_key,
                )
                controlled_failure = True
                await page.evaluate("window.dispatchEvent(new Event('focus'))")
                await expect(page.get_by_role("alert")).to_be_visible()
                await expect(cards).to_have_count(0)
                await page.screenshot(
                    path=str(OUT / "unavailable.jpg"), type="jpeg", quality=95
                )
                record(
                    "controlled-policy-503-clears-cards",
                    '[role="alert"]',
                    controlled_response=True,
                    visible_cards=0,
                )
                controlled_failure = False
                await page.get_by_role("button", name="다시 시도").click()
                await expect(cards).to_have_count(5)
                stale = {
                    **original,
                    "run_at": (now - timedelta(hours=36, seconds=5)).isoformat(),
                    "cutoff": (now - timedelta(hours=36, seconds=5)).isoformat(),
                }
                artifact.write_text(json.dumps(stale))
                await page.evaluate("window.dispatchEvent(new Event('focus'))")
                await expect(
                    page.get_by_role("status").filter(has_text="이전")
                ).to_be_visible()
                record(
                    "real-api-stale-fixture",
                    '[role="status"]',
                    age_hours=36,
                    fixture_timestamp_changed=True,
                )
                await page.keyboard.press("Escape")
                await expect(bell).to_be_focused()
                await page.set_viewport_size({"width": 390, "height": 844})
                await bell.click()
                await expect(cards).to_have_count(5)
                await page.screenshot(
                    path=str(OUT / "mobile.jpg"),
                    type="jpeg",
                    quality=95,
                    full_page=True,
                )
                record(
                    "mobile-and-keyboard",
                    '[role="dialog"]',
                    viewport={"width": 390, "height": 844},
                )
                expired = {
                    **original,
                    "run_at": (now - timedelta(hours=72, seconds=5)).isoformat(),
                    "cutoff": (now - timedelta(hours=72, seconds=5)).isoformat(),
                }
                artifact.write_text(json.dumps(expired))
                await page.evaluate("window.dispatchEvent(new Event('focus'))")
                await expect(cards).to_have_count(0)
                record(
                    "real-api-expired-fixture",
                    '[role="dialog"]',
                    age_hours=72,
                    visible_cards=0,
                )
                deletion = await context.request.delete(
                    backend + "/api/me/all",
                    headers={"Authorization": "Bearer " + token},
                )
                assert deletion.ok, await deletion.text()
                revoked = await context.request.get(
                    backend + "/api/recommendations/notifications",
                    headers={"Authorization": "Bearer " + token},
                )
                assert revoked.status == 401
                after_delete = outcome_state.outcome_metrics(
                    account["account_incarnation"],
                    since=day_start,
                    until=day_start + timedelta(days=1),
                    now=day_start + timedelta(days=9),
                )
                assert after_delete["total"]["visible_userdays"] == 0
                assert after_delete["total"]["positive_userdays"] == 0
                replacement = users.create_account(
                    "browser-fixture",
                    {
                        "role": "user",
                        "password_hash": _hash_password("replacement-password"),
                    },
                )
                assert (
                    replacement["account_incarnation"] != account["account_incarnation"]
                )
                login_b = await context.request.post(
                    backend + "/api/auth/login",
                    data={
                        "username": "browser-fixture",
                        "password": "replacement-password",
                    },
                )
                token_b = (await login_b.json())["access_token"]
                fresh = await context.request.get(
                    backend + "/api/recommendations/notifications",
                    headers={"Authorization": "Bearer " + token_b},
                )
                assert fresh.ok and not (await fresh.json())["items"]
                record(
                    "actual-deletion-recreation",
                    "/api/me/all",
                    surface="api",
                    old_token_status=401,
                    replacement_cards=0,
                    prior_outcome_userdays=after_delete["total"]["positive_userdays"],
                )
                await browser.close()
            report["api_traffic"] = traffic
            (OUT / "browser-transcript.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2)
            )
            print(
                json.dumps(
                    {
                        "actual_browser_actions": len(report["actions"]),
                        "api_calls": len(traffic),
                        "fixture_only": True,
                    }
                )
            )
        finally:
            os.killpg(preview.pid, signal.SIGTERM)
            try:
                preview.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(preview.pid, signal.SIGKILL)
                preview.wait(timeout=5)
            preview_out.close()
            preview_err.close()
            server.should_exit = True
            await asyncio.wait_for(server_task, timeout=15)


if __name__ == "__main__":
    asyncio.run(main())
