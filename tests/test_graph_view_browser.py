"""Fixture-routed browser evidence for the local graph presentation.

Set GRAPH_UI_BASE_URL to a running local frontend to opt in. API responses are
synthetic and are labeled fixture-routed in every generated transcript.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = REPO_ROOT / ".pytest_cache" / "graph-local"
PAPER_COUNT = 62
GRAPH_NODE_COUNT = 62


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


@pytest.fixture
def graph_ui_base_url() -> str:
    base_url = os.environ.get("GRAPH_UI_BASE_URL")
    if not base_url:
        pytest.skip("set GRAPH_UI_BASE_URL to a running local frontend")
    return base_url.rstrip("/")


@pytest.fixture(scope="module")
def chromium_browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        browser = _launch_chromium_or_skip(playwright)
        try:
            yield browser
        finally:
            browser.close()


def _fixture_payloads() -> tuple[dict, dict]:
    papers = [
        {
            "doc_id": f"fixture-doc-{index}",
            "result_key": f"fixture:{index:02d}",
            "title": f"Fixture paper {index}",
            "authors": [f"Researcher {index}"],
            "year": 2020 + index % 7,
            "abstract": f"Fixture abstract for paper {index}.",
            "citations": index * 5,
            "source": "arxiv",
            "_rank": index,
        }
        for index in range(PAPER_COUNT)
    ]
    search_response = {
        "results": {"arxiv": papers},
        "total": PAPER_COUNT,
        "query_hash": "fixture-query-hash",
        "stage_modes": {"ranking_variant": "fixture"},
    }

    nodes = [
        {
            "id": paper["result_key"],
            "x": math.cos(index * math.tau / GRAPH_NODE_COUNT),
            "y": math.sin(index * math.tau / GRAPH_NODE_COUNT),
            "title": paper["title"],
            "year": paper["year"],
            "citations": paper["citations"],
            "community_id": index % 4,
            "community_label": f"Fixture topic {index % 4 + 1}",
        }
        for index, paper in enumerate(papers)
    ]

    edges: list[dict] = []
    # A dense core exercises sparse-edge filtering and node-cap ranking.
    # The seed also has a deliberately low-degree, strongest neighbor at 61.
    for source in range(36):
        for target in range(source + 1, 36):
            if source == 0:
                weight = 0.98 - target * 0.01
            else:
                weight = 0.1 + ((source * 19 + target * 11) % 70) / 100
            edges.append(
                {
                    "source": f"fixture:{source:02d}",
                    "target": f"fixture:{target:02d}",
                    "weight": round(weight, 3),
                    "shared_terms": [f"fixture clue {source}-{target}"]
                    if (source + target) % 3 == 0
                    else [],
                }
            )
    edges.append(
        {
            "source": "fixture:00",
            "target": "fixture:61",
            "weight": 0.999,
            "shared_terms": ["sparse low-degree pin"],
        }
    )
    graph_response = {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "edge_method": "semantic_cosine",
            "edge_label": "제목 의미 유사도",
            "edge_threshold": 0.42,
            "directed": False,
        },
    }
    return search_response, graph_response


def _install_fixture_routes(
    page,
    *,
    graph_status: int = 200,
    search_status: int = 200,
    graph_override: dict | None = None,
) -> list[dict]:
    search_response, graph_response = _fixture_payloads()
    if graph_override is not None:
        graph_response = graph_override
    requests: list[dict] = []

    def fulfill_api(route) -> None:
        path = urlsplit(route.request.url).path
        if not path.startswith("/api/"):
            route.continue_()
            return
        if path == "/api/search":
            requests.append({"path": path, "status": search_status})
            if search_status >= 400:
                route.fulfill(
                    status=search_status,
                    content_type="application/json",
                    body=json.dumps({"detail": "fixture search request failed"}),
                )
            else:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(search_response),
                )
            return
        if path == "/api/graph-data":
            requests.append({"path": path, "status": graph_status})
            if graph_status >= 400:
                route.fulfill(
                    status=graph_status,
                    content_type="application/json",
                    body=json.dumps({"detail": "fixture graph request failed"}),
                )
            else:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(graph_response),
                )
            return
        route.fulfill(status=200, content_type="application/json", body="{}")

    page.route("**/api/**", fulfill_api)
    return requests


def _record_assertion(steps: list[dict], description: str, passed: bool) -> None:
    steps.append(
        {
            "action": "assert",
            "description": description,
            "status": "passed" if passed else "failed",
        }
    )
    assert passed, description


def _highlighted_marker_ids(page) -> list[str]:
    return page.locator(".js-plotly-plot").evaluate(
        "gd => (gd.data || []).flatMap(trace => {"
        "const width = trace.marker?.line?.width;"
        "return trace.mode === 'markers' && Array.isArray(trace.customdata) && "
        "Array.isArray(width) && width.length > 0 && width.every(value => value === 1.4)"
        "? trace.customdata.map(String) : [];"
        "})"
    )


def _ranked_neighbors(
    graph_response: dict, selected_id: str, limit: int = 5
) -> list[dict]:
    strongest: dict[str, dict] = {}
    for edge in graph_response["edges"]:
        source = str(edge["source"])
        target = str(edge["target"])
        if source == target:
            continue
        if source == selected_id:
            neighbor_id = target
        elif target == selected_id:
            neighbor_id = source
        else:
            continue
        candidate = {
            "id": neighbor_id,
            "weight": edge.get("weight", 0) or 0,
            "shared_terms": edge.get("shared_terms", []),
        }
        previous = strongest.get(neighbor_id)
        if previous is None or candidate["weight"] > previous["weight"]:
            strongest[neighbor_id] = candidate
    return sorted(
        strongest.values(), key=lambda neighbor: (-neighbor["weight"], neighbor["id"])
    )[:limit]


def _visible_node_ids(page) -> list[str]:
    return page.locator(".js-plotly-plot").evaluate(
        "gd => (gd.data || []).flatMap(trace => "
        "trace.mode === 'markers' && Array.isArray(trace.customdata) "
        "? trace.customdata.map(String) : [])"
    )


def _focused_edge_hover_text(page) -> list[str]:
    return page.locator(".js-plotly-plot").evaluate(
        "gd => (gd.data || []).flatMap(trace => "
        "trace.hoverinfo === 'text' && trace.customdata == null && Array.isArray(trace.hovertext) "
        "? trace.hovertext.map(String) : [])"
    )


def _related_badges(page) -> list[dict]:
    return page.locator(".paper-card").evaluate_all(
        "cards => cards.map(card => ({"
        "title: card.querySelector('.paper-title')?.textContent?.trim() || '',"
        "rank: card.querySelector('.related-rank-badge')?.textContent?.trim() || ''"
        "})).filter(card => card.rank)"
    )


def _record_artifacts(
    page,
    *,
    name: str,
    viewport: dict[str, int],
    steps: list[dict],
    status: str,
    error: str | None = None,
) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_path = ARTIFACT_DIR / f"fixture-{name}.png"
    screenshot_error = None
    try:
        page.screenshot(
            path=str(screenshot_path), full_page=True, animations="disabled"
        )
    except (
        Exception
    ) as exc:  # Preserve the test outcome even if a browser teardown blocks capture.
        screenshot_error = str(exc)
    steps.append(
        {
            "action": "screenshot",
            "path": str(screenshot_path),
            "status": "passed" if screenshot_error is None else "failed",
        }
    )

    transcript = {
        "schemaVersion": 1,
        "kind": "browser-automation",
        "surface": "web",
        "mode": "fixture-routed",
        "status": "failed" if screenshot_error and status == "passed" else status,
        "url": page.url,
        "viewport": viewport,
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "steps": steps,
        "screenshot": str(screenshot_path) if screenshot_error is None else None,
        "screenshot_error": screenshot_error,
        "error": error,
    }
    (ARTIFACT_DIR / f"fixture-{name}.json").write_text(
        json.dumps(transcript, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if screenshot_error and status == "passed":
        raise RuntimeError(f"fixture browser screenshot failed: {screenshot_error}")


def _open_fixture_search(
    browser,
    base_url: str,
    viewport: dict[str, int],
    *,
    graph_status: int = 200,
    search_status: int = 200,
    graph_override: dict | None = None,
):
    context = browser.new_context(viewport=viewport, device_scale_factor=1)
    page = context.new_page()
    page.add_init_script("localStorage.clear();")
    api_requests = _install_fixture_routes(
        page,
        graph_status=graph_status,
        search_status=search_status,
        graph_override=graph_override,
    )
    steps = [
        {
            "action": "route-fixture",
            "description": "Route API requests to synthetic search and graph responses.",
            "status": "passed",
        }
    ]
    page.goto(base_url, wait_until="domcontentloaded")
    steps.append({"action": "navigate", "url": page.url, "status": "passed"})
    page.get_by_role("textbox", name="논문 검색").fill("fixture graph evidence")
    steps.append({"action": "fill", "target": "논문 검색", "status": "passed"})
    response_path = "/api/graph-data" if search_status < 400 else "/api/search"
    with page.expect_response(
        lambda response: urlsplit(response.url).path == response_path
    ) as response_info:
        page.get_by_role("button", name="논문 검색").first.click()
    steps.append({"action": "click", "target": "논문 검색", "status": "passed"})
    response_info.value.finished()
    steps.append(
        {
            "action": "response",
            "target": response_path,
            "httpStatus": response_info.value.status,
            "status": "passed",
        }
    )
    if search_status < 400 and graph_status < 400:
        page.locator(".js-plotly-plot").wait_for(state="visible", timeout=30_000)
        page.locator(".paper-card").first.wait_for(state="visible", timeout=30_000)
        steps.append(
            {
                "action": "wait",
                "target": "real Plotly graph and result card",
                "status": "passed",
            }
        )
    return context, page, steps, api_requests


@pytest.mark.parametrize(
    ("name", "width", "height"),
    [("desktop", 1280, 800), ("mobile", 390, 844)],
)
def test_fixture_graph_presentation_in_real_plotly(
    graph_ui_base_url: str,
    chromium_browser,
    name: str,
    width: int,
    height: int,
) -> None:
    viewport = {"width": width, "height": height}
    context, page, steps, _ = _open_fixture_search(
        chromium_browser, graph_ui_base_url, viewport
    )
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    status = "passed"
    error = None
    try:
        _, graph_response = _fixture_payloads()
        settings = page.get_by_role("button", name="보기 설정")
        _record_assertion(
            steps,
            "view settings are collapsed at first render",
            settings.get_attribute("aria-expanded") == "false"
            and page.locator(".graph-controls.is-open").count() == 0,
        )
        _record_assertion(
            steps,
            "a real Plotly graph is rendered",
            page.locator(".js-plotly-plot").count() == 1,
        )
        _record_assertion(
            steps,
            "the sparse-edge toggle starts off",
            page.get_by_role("button", name="전체 연결선 표시").get_attribute(
                "aria-pressed"
            )
            == "false",
        )
        _record_assertion(
            steps,
            "the full graph denominator includes all 62 fixture nodes",
            bool(
                re.search(
                    r"표시 \d+/62편", page.locator(".graph-insight-copy").inner_text()
                )
            ),
        )
        initial_ids = set(_visible_node_ids(page))
        _record_assertion(
            steps,
            "all initial ranked highlights, including low-degree fixture:61, are rendered",
            {
                "fixture:61",
                "fixture:01",
                "fixture:02",
                "fixture:03",
                "fixture:04",
            }.issubset(initial_ids),
        )

        settings.click()
        steps.append({"action": "click", "target": "보기 설정", "status": "passed"})
        node_limit = page.get_by_label("표시 논문 수")
        node_limit.select_option("20")
        steps.append(
            {
                "action": "select",
                "target": "표시 논문 수",
                "value": "20",
                "status": "passed",
            }
        )
        capped_ids = _visible_node_ids(page)
        _record_assertion(
            steps,
            "node limit 20 keeps the low-degree highlighted pin without exceeding the cap",
            len(set(capped_ids)) == 20 and "fixture:61" in capped_ids,
        )
        node_limit.select_option("50")
        steps.append(
            {
                "action": "select",
                "target": "표시 논문 수",
                "value": "50",
                "status": "passed",
            }
        )
        page.get_by_role("button", name="보기 설정 닫기").click()
        steps.append(
            {"action": "click", "target": "보기 설정 닫기", "status": "passed"}
        )

        selected_index = 10
        selected_id = f"fixture:{selected_index:02d}"
        selected_title = f"Fixture paper {selected_index}"
        selected_card = page.locator(".paper-card").filter(has_text=selected_title)
        selected_card.click()
        steps.append(
            {
                "action": "click",
                "target": f"PaperList {selected_title}",
                "status": "passed",
            }
        )
        page.locator(".detail-title").filter(has_text=selected_title).wait_for()
        steps.append(
            {
                "action": "wait",
                "target": f"graph selection {selected_title}",
                "status": "passed",
            }
        )
        expected_neighbors = _ranked_neighbors(graph_response, selected_id)
        expected_neighbor_ids = [neighbor["id"] for neighbor in expected_neighbors]
        page.wait_for_function(
            """id => document.querySelector('.js-plotly-plot')?.data?.some(
                trace => trace.mode === 'markers' && trace.customdata?.some(
                    (key, index) => key === id && trace.marker?.line?.width?.[index] === 2.2
                )
            )""",
            arg=selected_id,
        )
        list_highlights = _highlighted_marker_ids(page)
        hover_text = _focused_edge_hover_text(page)
        expected_hover_text = sorted(
            f"제목 의미 유사도 {round(neighbor['weight'] * 100)}%"
            + (
                f"<br>공통 단서 · {' · '.join(neighbor['shared_terms'])}"
                if neighbor["shared_terms"]
                else ""
            )
            for neighbor in expected_neighbors
        )
        _record_assertion(
            steps,
            "ranked neighbors retain highlight order while the seed keeps its distinct marker",
            list_highlights
            == [
                node_id for node_id in expected_neighbor_ids if node_id != "fixture:00"
            ],
        )
        _record_assertion(
            steps,
            "focused edge hover uses the edge-method label and only supplies shared terms when present",
            sorted(hover_text) == expected_hover_text,
        )

        selected_card_badges = _related_badges(page)
        page.locator(".paper-card").filter(has_text="Fixture paper 11").click()
        page.locator(".detail-title").filter(has_text="Fixture paper 11").wait_for()
        steps.append(
            {
                "action": "click",
                "target": "PaperList Fixture paper 11 before testing node selection",
                "status": "passed",
            }
        )
        page.locator(".js-plotly-plot").evaluate(
            "(gd, id) => gd.emit('plotly_click', {points: [{customdata: id}]})",
            selected_id,
        )
        steps.append(
            {
                "action": "emit",
                "target": f"Plotly node click {selected_id}",
                "status": "passed",
            }
        )
        page.locator(".detail-title").filter(has_text=selected_title).wait_for()
        steps.append(
            {
                "action": "wait",
                "target": f"graph selection {selected_title}",
                "status": "passed",
            }
        )
        node_highlights = _highlighted_marker_ids(page)
        _record_assertion(
            steps,
            "node selection produces the same ranked highlight IDs and PaperList badges as list selection",
            node_highlights == list_highlights
            and _related_badges(page) == selected_card_badges,
        )
        labels = page.locator(".js-plotly-plot .textpoint")
        label_text = labels.all_text_contents()
        if name == "mobile":
            _record_assertion(
                steps,
                "mobile Plotly labels include seed, selection and stay within the five-label budget",
                len(label_text) <= 5
                and any("Fixture paper 0" in text for text in label_text)
                and any(selected_title in text for text in label_text),
            )
            hide_labels = page.get_by_role(
                "button", name="핵심 레이블(기준·선택·관련 최대 3편) 숨기기"
            )
            _record_assertion(
                steps,
                "mobile Aa names its actual label scope",
                hide_labels.get_attribute("title")
                == "핵심 레이블(기준·선택·관련 최대 3편) 숨기기",
            )
            hide_labels.click()
            steps.append(
                {
                    "action": "click",
                    "target": "핵심 레이블(기준·선택·관련 최대 3편) 숨기기",
                    "status": "passed",
                }
            )
            page.locator(".js-plotly-plot .textpoint").first.wait_for(state="detached")
            _record_assertion(
                steps,
                "mobile Aa hides every Plotly text label",
                page.locator(".js-plotly-plot .textpoint").count() == 0,
            )
            show_labels = page.get_by_role(
                "button", name="핵심 레이블(기준·선택·관련 최대 3편) 표시"
            )
            show_labels.click()
            steps.append(
                {
                    "action": "click",
                    "target": "핵심 레이블(기준·선택·관련 최대 3편) 표시",
                    "status": "passed",
                }
            )
        else:
            _record_assertion(
                steps,
                "desktop keeps hub labels in addition to origin, selection and ranked neighbors",
                len(label_text) > 5
                and any("Fixture paper 0" in text for text in label_text)
                and any(selected_title in text for text in label_text),
            )
            _record_assertion(
                steps,
                "desktop Aa retains the general major-label wording",
                page.get_by_role("button", name="주요 레이블 숨기기").get_attribute(
                    "title"
                )
                == "주요 레이블 숨기기",
            )
        relation_chip = (
            page.locator(".graph-status-chip").filter(has_text="관계").inner_text()
        )
        before_filter = int(re.search(r"관계 (\d+)/", relation_chip).group(1))
        settings = page.get_by_role("button", name="보기 설정")
        if settings.get_attribute("aria-expanded") == "false":
            settings.click()
            steps.append({"action": "click", "target": "보기 설정", "status": "passed"})
        citation_filter = page.locator(".graph-controls input[type=number]").first
        citation_filter.fill("50")
        steps.append(
            {
                "action": "fill",
                "target": "최소 인용수",
                "value": "50",
                "status": "passed",
            }
        )
        relation_after = (
            page.locator(".graph-status-chip").filter(has_text="관계").inner_text()
        )
        after_filter = int(re.search(r"관계 (\d+)/", relation_after).group(1))
        _record_assertion(
            steps,
            "the displayed edge count drops when citation filtering removes edge endpoints",
            after_filter < before_filter
            and f"/{len(graph_response['edges'])}개" in relation_after,
        )
        citation_filter.fill("0")
        steps.append(
            {
                "action": "fill",
                "target": "최소 인용수",
                "value": "0",
                "status": "passed",
            }
        )
        page.get_by_role("button", name="보기 설정 닫기").click()
        steps.append(
            {"action": "click", "target": "보기 설정 닫기", "status": "passed"}
        )

        related_section = page.get_by_role("region", name="다음에 읽을 논문")
        page.locator(".right-panel").scroll_into_view_if_needed()
        steps.append(
            {"action": "scroll", "target": "right details panel", "status": "passed"}
        )
        related_section.scroll_into_view_if_needed()
        related_buttons = related_section.locator("button")
        related_buttons.first.scroll_into_view_if_needed()
        steps.append(
            {"action": "scroll", "target": "first next-read card", "status": "passed"}
        )
        button_text = related_buttons.all_text_contents()
        paper_title_by_key = {
            paper["result_key"]: paper["title"]
            for paper in _fixture_payloads()[0]["results"]["arxiv"]
        }
        expected_card_titles = [
            paper_title_by_key[neighbor["id"]] for neighbor in expected_neighbors
        ]
        _record_assertion(
            steps,
            "next-read cards match the top five selected-paper neighbors by fixture weight",
            len(button_text) == 5
            and all(
                title in button_text[index]
                for index, title in enumerate(expected_card_titles)
            ),
        )
        _record_assertion(
            steps,
            "semantic next-read cards show percentage, shared terms and title-only method copy",
            all(
                "제목 의미 유사도" in button_text[index]
                and f"{round(neighbor['weight'] * 100)}%" in button_text[index]
                for index, neighbor in enumerate(expected_neighbors)
            )
            and all(
                (
                    f"공통 단서: {' · '.join(neighbor['shared_terms'][:3])}"
                    if neighbor["shared_terms"]
                    else "공통 용어 정보 없음"
                )
                in button_text[index]
                for index, neighbor in enumerate(expected_neighbors)
            )
            and "제목 임베딩 코사인 유사도 · 인용·인과 관계 아님"
            in related_section.inner_text()
            and "초록" not in related_section.inner_text(),
        )
        abstract = page.locator(".detail-abstract")
        order_check = related_section.evaluate(
            "(section, abstract) => Boolean(section.compareDocumentPosition(abstract) & Node.DOCUMENT_POSITION_FOLLOWING)",
            abstract.element_handle(),
        )
        first_card_box = related_buttons.first.bounding_box()
        _record_assertion(
            steps,
            "next-read cards precede the abstract and the first card is in the viewport",
            order_check
            and first_card_box is not None
            and 0 <= first_card_box["y"]
            and first_card_box["y"] + first_card_box["height"] <= height,
        )
        page_errors_before_reset = list(page_errors)
        page.get_by_role("button", name="그래프 위치 초기화").click()
        steps.append(
            {"action": "click", "target": "그래프 위치 초기화", "status": "passed"}
        )
        _record_assertion(
            steps,
            "resetting graph position raises no browser page error",
            page_errors == page_errors_before_reset,
        )
    except BaseException as exc:
        status = "failed"
        error = str(exc)
        steps.append({"action": "error", "description": error, "status": "failed"})
        raise
    finally:
        _record_artifacts(
            page,
            name=f"graph-{name}",
            viewport=viewport,
            steps=steps,
            status=status,
            error=error,
        )
        context.close()


def test_fixture_softcap_retains_every_path_pin_above_twenty_node_limit(
    graph_ui_base_url: str,
    chromium_browser,
) -> None:
    viewport = {"width": 1280, "height": 800}
    _, base_graph = _fixture_payloads()
    path_ids = [f"fixture:{index:02d}" for index in range(25)]
    graph_override = {
        **base_graph,
        "edges": [
            *[
                {
                    "source": source,
                    "target": target,
                    "weight": 0.9,
                    "shared_terms": ["path clue"],
                }
                for source, target in zip(path_ids, path_ids[1:])
            ],
            {
                "source": "fixture:00",
                "target": "fixture:60",
                "shared_terms": ["missing score"],
            },
            {
                "source": "fixture:00",
                "target": "fixture:61",
                "weight": None,
                "shared_terms": ["null score"],
            },
        ],
    }
    context, page, steps, api_requests = _open_fixture_search(
        chromium_browser,
        graph_ui_base_url,
        viewport,
        graph_override=graph_override,
    )
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    status = "passed"
    error = None
    try:
        invalid_weight_recommendations = page.locator(".paper-card").evaluate_all(
            "cards => cards.filter(card => /Fixture paper (60|61)$/.test("
            "card.querySelector('.paper-title')?.textContent?.trim() || ''))"
            ".map(card => ({title: card.querySelector('.paper-title').textContent.trim(), "
            "badge: card.querySelector('.related-rank-badge')?.textContent || null}))"
        )
        _record_assertion(
            steps,
            "missing and null origin-edge weights do not fabricate related-neighbor rankings",
            invalid_weight_recommendations
            == [
                {"title": "Fixture paper 60", "badge": None},
                {"title": "Fixture paper 61", "badge": None},
            ]
            and page.locator(".detail-related-title").all_text_contents()
            == ["Fixture paper 1"],
        )

        page.locator(".paper-card").filter(has_text="Fixture paper 24").click()
        page.locator(".detail-title").filter(has_text="Fixture paper 24").wait_for()
        steps.append(
            {
                "action": "click",
                "target": "PaperList Fixture paper 24",
                "status": "passed",
            }
        )
        related_section = page.get_by_role("region", name="다음에 읽을 논문")
        _record_assertion(
            steps,
            "valid path edges still produce the selected paper's actual next neighbor",
            related_section.locator("button").count() == 1
            and "Fixture paper 23" in related_section.inner_text()
            and "Fixture paper 60" not in related_section.inner_text()
            and "Fixture paper 61" not in related_section.inner_text(),
        )

        settings = page.get_by_role("button", name="보기 설정")
        settings.click()
        steps.append({"action": "click", "target": "보기 설정", "status": "passed"})
        page.get_by_label("표시 논문 수").select_option("20")
        steps.append(
            {
                "action": "select",
                "target": "표시 논문 수",
                "value": "20",
                "status": "passed",
            }
        )
        page.get_by_role("button", name="기준논문 경로").click()
        steps.append({"action": "click", "target": "기준논문 경로", "status": "passed"})
        page.wait_for_function(
            """expected => {
                const gd = document.querySelector('.js-plotly-plot');
                if (!gd?.data) return false;
                const ids = gd.data.flatMap(trace =>
                    trace.mode === 'markers' && Array.isArray(trace.customdata)
                        ? trace.customdata.map(String)
                        : []
                );
                return ids.length === expected.length &&
                    new Set(ids).size === expected.length &&
                    expected.every(id => ids.includes(id));
            }""",
            arg=path_ids,
        )
        steps.append(
            {
                "action": "wait",
                "target": "all 25 actual Plotly path-node customdata IDs",
                "status": "passed",
            }
        )
        visible_path_ids = _visible_node_ids(page)
        _record_assertion(
            steps,
            "all 25 origin-to-selection path pins remain visible above the 20-node cap",
            len(visible_path_ids) == 25 and set(visible_path_ids) == set(path_ids),
        )
        _record_assertion(
            steps,
            "soft-cap counts show 25 of 62 nodes and exactly 24 drawn edges of 26 graph edges",
            page.locator(".graph-insight-copy").get_by_text("표시 25/62편").count() == 1
            and page.locator(".graph-insight-copy").get_by_text("관계 24/26개").count()
            == 1,
        )
        _record_assertion(
            steps,
            "all API fixture requests completed and no browser page error occurred",
            {"path": "/api/search", "status": 200} in api_requests
            and {"path": "/api/graph-data", "status": 200} in api_requests
            and page_errors == [],
        )
    except BaseException as exc:
        status = "failed"
        error = str(exc)
        steps.append({"action": "error", "description": error, "status": "failed"})
        raise
    finally:
        _record_artifacts(
            page,
            name="softcap",
            viewport=viewport,
            steps=steps,
            status=status,
            error=error,
        )
        context.close()


def test_graph_data_failure_keeps_results_without_graph_or_next_read(
    graph_ui_base_url: str,
    chromium_browser,
) -> None:
    viewport = {"width": 1280, "height": 800}
    context, page, steps, api_requests = _open_fixture_search(
        chromium_browser,
        graph_ui_base_url,
        viewport,
        graph_status=500,
    )
    status = "passed"
    error = None
    try:
        page.get_by_text("Fixture paper 0", exact=True).first.wait_for(state="visible")
        steps.append(
            {
                "action": "wait",
                "target": "search result after graph-data failure",
                "status": "passed",
            }
        )
        page.locator(".center-panel .app-loading").wait_for(
            state="detached", timeout=15_000
        )
        steps.append(
            {
                "action": "wait",
                "target": "graph enrichment loading complete",
                "status": "passed",
            }
        )
        _record_assertion(
            steps,
            "a graph-data request failure leaves search results visible",
            page.locator(".paper-card").count() == PAPER_COUNT,
        )
        _record_assertion(
            steps,
            "graph-data failure leaves the center pane empty without rendering Plotly",
            page.locator(".center-panel .js-plotly-plot").count() == 0
            and page.locator(".center-panel .graph-empty").count() == 0
            and page.locator(".center-panel .app-loading").count() == 0,
        )
        _record_assertion(
            steps,
            "graph-data failure does not invent next-read cards",
            page.get_by_role("region", name="다음에 읽을 논문").count() == 0,
        )
        _record_assertion(
            steps,
            "the fixture graph-data endpoint was requested and returned HTTP 500",
            {"path": "/api/graph-data", "status": 500} in api_requests,
        )
    except BaseException as exc:
        status = "failed"
        error = str(exc)
        steps.append({"action": "error", "description": error, "status": "failed"})
        raise
    finally:
        _record_artifacts(
            page,
            name="graph-failure",
            viewport=viewport,
            steps=steps,
            status=status,
            error=error,
        )
        context.close()


def test_search_request_failure_keeps_the_search_error_state(
    graph_ui_base_url: str,
    chromium_browser,
) -> None:
    viewport = {"width": 1280, "height": 800}
    context, page, steps, api_requests = _open_fixture_search(
        chromium_browser,
        graph_ui_base_url,
        viewport,
        search_status=500,
    )
    status = "passed"
    error = None
    try:
        page.get_by_text("fixture search request failed", exact=False).wait_for(
            timeout=15_000
        )
        steps.append(
            {
                "action": "wait",
                "target": "fixture search request error message",
                "status": "passed",
            }
        )
        _record_assertion(
            steps,
            "search request failure preserves the real error message and no fabricated results",
            "fixture search request failed" in page.locator("body").inner_text()
            and page.locator(".paper-card").count() == 0,
        )
        _record_assertion(
            steps,
            "search request failure does not render a graph or next-read cards",
            page.locator(".js-plotly-plot").count() == 0
            and page.get_by_role("region", name="다음에 읽을 논문").count() == 0,
        )
        _record_assertion(
            steps,
            "the fixture search endpoint was requested and returned HTTP 500",
            {"path": "/api/search", "status": 500} in api_requests,
        )
    except BaseException as exc:
        status = "failed"
        error = str(exc)
        steps.append({"action": "error", "description": error, "status": "failed"})
        raise
    finally:
        _record_artifacts(
            page,
            name="search-failure",
            viewport=viewport,
            steps=steps,
            status=status,
            error=error,
        )
        context.close()
