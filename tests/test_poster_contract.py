"""Poster backend API and resource contract tests."""

from __future__ import annotations

import asyncio
import re
import threading

import pytest
from pydantic import ValidationError

from app.DeepAgent.agents.poster_agent import PosterGenerationAgent
from app.DeepAgent.poster import resource_policy
from app.DeepAgent.poster import service as poster_service_module
from app.DeepAgent.poster.result_contract import (
    CODE_ACTIVE_JOB,
    CODE_TIMEOUT_UNCLASSIFIED,
)
from app.DeepAgent.poster.service import PosterApplicationService, PosterServiceError
from routers.autofigure import MethodToSvgRequest, PosterFiguresRequest


_LOWER_SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def test_public_phase_security_flags_are_enabled() -> None:
    assert resource_policy.POSTER_SECURITY_PHASE == "phase_1_strict"
    assert resource_policy.MANDATORY_SANITIZER_ENABLED is True


def test_agent_returns_degraded_fallback_when_content_extraction_fails(
    monkeypatch,
) -> None:
    agent = PosterGenerationAgent(
        api_key=None,
        enable_critic=False,
        enable_validation=False,
        design_pattern_manager=None,
    )

    def fail_extract(*args, **kwargs):
        raise RuntimeError("extract failed")

    monkeypatch.setattr(agent.content_agent, "extract", fail_extract)

    result = agent.generate_poster("# Title\n\n## Body\nsafe", num_papers=1)

    assert result["status"] == "degraded"
    assert result["success"] is False
    assert result["poster_html"].startswith("<!DOCTYPE html>")
    assert result["validation_score"] == 0.5
    assert "extract failed" in result["error"]


def test_poster_service_normalizes_success_from_raw_agent_result() -> None:
    result = PosterApplicationService()._normalize_result(
        {"success": True, "poster_html": "<main>safe</main>"},
        generation_id="poster_test",
        session_id="session-1",
        timings={"total_ms": 1.0},
        provenance={"route": "direct"},
    )

    assert result["status"] == "succeeded"


def test_poster_service_normalizes_degraded_fallback_from_error_result() -> None:
    result = PosterApplicationService()._normalize_result(
        {
            "success": False,
            "poster_html": "<main>fallback</main>",
            "error": "upstream unavailable",
        },
        generation_id="poster_test",
        session_id="session-1",
        timings={"total_ms": 1.0},
        provenance={"route": "direct"},
    )

    assert result["status"] == "degraded"
    assert result["success"] is False


def test_poster_service_normalization_sanitizes_html_before_delivery() -> None:
    result = PosterApplicationService()._normalize_result(
        {"success": True, "poster_html": "<main>safe<script>alert(1)</script></main>"},
        generation_id="poster_test",
        session_id="session-1",
        timings={"total_ms": 1.0},
        provenance={"route": "direct"},
    )

    assert "<script" not in result["poster_html"]


def test_poster_service_error_codes_are_lower_snake_in_normalized_fallback() -> None:
    result = PosterApplicationService()._normalize_result(
        {
            "success": False,
            "poster_html": "<main>fallback</main>",
            "error": "upstream unavailable",
            "error_code": "poster_fallback_used",
        },
        generation_id="poster_test",
        session_id="session-1",
        timings={"total_ms": 1.0},
        provenance={"route": "direct"},
    )

    assert _LOWER_SNAKE_RE.match(result["error_code"])


def test_poster_service_normalization_excludes_raw_paths_from_public_provenance() -> None:
    result = PosterApplicationService()._normalize_result(
        {"success": True, "poster_html": "<main>safe</main>"},
        generation_id="poster_test",
        session_id="session-1",
        timings={"total_ms": 1.0},
        provenance={
            "route": "deep-review/visualize",
            "report_path": "/tmp/private/report.md",
            "workspace_path": "/tmp/private/workspace",
        },
    )

    assert "report_path" not in result["provenance"]
    assert "workspace_path" not in result["provenance"]


def test_poster_service_normalization_excludes_raw_agent_provenance_paths_and_nested_secrets() -> None:
    result = PosterApplicationService()._normalize_result(
        {
            "success": True,
            "poster_html": "<main>safe</main>",
            "provenance": {
                "workspace_path": "/tmp/private/workspace",
                "report_path": "/tmp/private/report.md",
                "poster_path": "/tmp/private/poster.html",
                "nested": {
                    "secret": "/tmp/private/token",
                    "safe_label": "redacted-ok",
                },
            },
        },
        generation_id="poster_test",
        session_id="session-1",
        timings={"total_ms": 1.0},
        provenance={"route": "deep-review/visualize"},
    )

    assert result["provenance"] == {"route": "deep-review/visualize"}
    assert "private" not in str(result["provenance"])
    assert "secret" not in str(result["provenance"])


@pytest.mark.asyncio
async def test_poster_service_rejects_oversized_direct_report_before_agent_call() -> None:
    calls = []

    async def run() -> None:
        await PosterApplicationService().generate(
            report_content="x" * 200_001,
            num_papers=1,
            agent_factory=lambda: calls.append("called"),
        )

    with pytest.raises(PosterServiceError) as exc_info:
        await run()

    assert exc_info.value.error_code == "poster_input_too_large"
    assert calls == []


@pytest.mark.asyncio
async def test_poster_service_rejects_negative_paper_count_before_agent_call() -> None:
    calls = []

    async def run() -> None:
        await PosterApplicationService().generate(
            report_content="safe",
            num_papers=-1,
            agent_factory=lambda: calls.append("called"),
        )

    with pytest.raises(PosterServiceError) as exc_info:
        await run()

    assert exc_info.value.error_code == "poster_input_invalid"
    assert calls == []


@pytest.mark.asyncio
async def test_poster_service_rejects_duplicate_active_session_before_second_agent_call() -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    calls = []

    class BlockingAgent:
        def generate_poster(self, **kwargs):
            calls.append(kwargs["session_id"] if "session_id" in kwargs else "agent")
            first_started.set()
            release_first.wait(timeout=2)
            return {"success": True, "poster_html": "<main>done</main>"}

    class FastAgent:
        def generate_poster(self, **kwargs):
            calls.append("second-agent")
            return {"success": True, "poster_html": "<main>duplicate</main>"}

    service = PosterApplicationService()
    first = asyncio.create_task(
        service.generate(
            report_content="safe",
            num_papers=1,
            session_id="session-dup",
            agent_factory=BlockingAgent,
        )
    )
    await asyncio.to_thread(first_started.wait, 2)

    try:
        with pytest.raises(PosterServiceError) as exc_info:
            await service.generate(
                report_content="safe",
                num_papers=1,
                session_id="session-dup",
                agent_factory=FastAgent,
            )

        assert exc_info.value.error_code == CODE_ACTIVE_JOB
        assert "second-agent" not in calls
    finally:
        release_first.set()
        await first


@pytest.mark.asyncio
async def test_poster_service_timeout_retains_capacity_until_worker_exits(
    monkeypatch,
) -> None:
    first_started = threading.Event()
    release_worker = threading.Event()
    second_called = threading.Event()

    class BlockingAgent:
        def generate_poster(self, **kwargs):
            first_started.set()
            release_worker.wait(timeout=2)
            return {"success": True, "poster_html": "<main>late</main>"}

    class SecondAgent:
        def generate_poster(self, **kwargs):
            second_called.set()
            return {"success": True, "poster_html": "<main>second</main>"}

    monkeypatch.setattr(
        poster_service_module,
        "_poster_semaphore",
        asyncio.Semaphore(1),
    )
    service = PosterApplicationService()

    with pytest.raises(PosterServiceError) as timeout_info:
        await service.generate(
            report_content="safe",
            num_papers=1,
            agent_factory=BlockingAgent,
            timeout_seconds=0.01,
        )
    assert timeout_info.value.error_code == CODE_TIMEOUT_UNCLASSIFIED
    assert first_started.is_set()

    try:
        with pytest.raises(PosterServiceError) as budget_info:
            await service.generate(
                report_content="safe",
                num_papers=1,
                agent_factory=SecondAgent,
                timeout_seconds=0.5,
            )

        assert budget_info.value.error_code == CODE_ACTIVE_JOB
        assert not second_called.is_set()
    finally:
        release_worker.set()


def test_autofigure_method_request_rejects_zero_iterations() -> None:
    with pytest.raises(ValidationError):
        MethodToSvgRequest(method_text="pipeline", optimize_iterations=0)


def test_autofigure_method_request_rejects_more_than_ten_iterations() -> None:
    with pytest.raises(ValidationError):
        MethodToSvgRequest(method_text="pipeline", optimize_iterations=11)


def test_poster_figures_request_rejects_zero_max_figures() -> None:
    with pytest.raises(ValidationError):
        PosterFiguresRequest(
            session_id="s1",
            methodology="pipeline",
            max_figures=0,
        )


def test_poster_figures_request_rejects_more_than_ten_max_figures() -> None:
    with pytest.raises(ValidationError):
        PosterFiguresRequest(
            session_id="s1",
            methodology="pipeline",
            max_figures=11,
        )


def test_poster_figures_request_accepts_service_limit_boundary() -> None:
    request = PosterFiguresRequest(
        session_id="s1",
        methodology="pipeline",
        paper_analyses=[{"title": "Paper A"}],
        max_figures=10,
    )

    assert request.max_figures == 10
