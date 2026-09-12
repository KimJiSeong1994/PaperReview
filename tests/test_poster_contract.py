"""Poster backend API and resource contract tests."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import threading
import time

import pytest
from pydantic import ValidationError

from app.DeepAgent.agents.poster_agent import (
    REFINE_INPUT_MAX_CHARS,
    PosterGenerationAgent,
)
from app.DeepAgent.agents.poster_critic_agent import CritiqueResult
from app.DeepAgent.poster import resource_policy
from app.DeepAgent.poster import service as poster_service_module
from app.DeepAgent.poster.result_contract import (
    CODE_ACTIVE_JOB,
    CODE_TIMEOUT_UNCLASSIFIED,
)
from app.DeepAgent.poster.service import PosterApplicationService, PosterServiceError
from routers.autofigure import MethodToSvgRequest, PosterFiguresRequest


_LOWER_SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_SAMPLE_REPORT = "# Title\n\n## Abstract\nbody text\n\n## Results\n95% accuracy"


def _offline_agent(**kwargs) -> PosterGenerationAgent:
    """Agent with the diagram clients detached so tests never touch the network."""
    agent = PosterGenerationAgent(api_key=None, design_pattern_manager=None, **kwargs)
    agent._paperbanana_client = None
    agent._autofigure_client = None
    return agent


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
    assert result["validation_score"] is None
    assert result["quality"]["validation_score"] is None
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


def test_agent_reports_no_score_when_neither_critic_nor_validator_runs() -> None:
    """D2: an unevaluated poster must carry no score at all."""
    agent = _offline_agent(enable_critic=False, enable_validation=False)

    result = agent.generate_poster(_SAMPLE_REPORT, num_papers=1)

    assert result["status"] == "succeeded"
    assert result["validation_score"] is None
    assert result["quality"]["validation_score"] is None
    assert result["quality"]["evaluator"] is None


def test_poster_service_response_id_is_the_service_id_not_the_agent_id() -> None:
    """D1: one job, one id — the agent's own id must not reach the response."""
    result = PosterApplicationService()._normalize_result(
        {
            "success": True,
            "poster_html": "<main>safe</main>",
            "generation_id": "poster_agentside",
        },
        generation_id="poster_serviceside",
        session_id="session-1",
        timings={"total_ms": 1.0},
        provenance={"route": "direct"},
    )

    assert result["generation_id"] == "poster_serviceside"


def test_poster_quality_score_describes_the_delivered_bytes() -> None:
    """D3: the score is bound to the exact bytes the caller receives."""
    agent = _offline_agent(enable_critic=True)
    raw = agent.generate_poster(_SAMPLE_REPORT, num_papers=1)

    assert raw["quality"]["validation_score"] is not None
    assert raw["quality"]["scored_sha256"] == hashlib.sha256(
        raw["poster_html"].encode("utf-8")
    ).hexdigest()

    result = PosterApplicationService()._normalize_result(
        raw,
        generation_id="poster_test",
        session_id="session-1",
        timings={"total_ms": 1.0},
        provenance={"route": "direct"},
    )

    assert result["quality"]["validation_score"] == raw["quality"]["validation_score"]
    assert result["artifacts"]["html_sha256"] == hashlib.sha256(
        result["poster_html"].encode("utf-8")
    ).hexdigest()
    assert result["quality"]["scored_sha256"] == result["artifacts"]["html_sha256"]


def test_poster_service_drops_score_when_delivery_changes_the_scored_bytes() -> None:
    """D3: service-side sanitization invalidates the agent's score."""
    scored_html = "<main>safe<script>alert(1)</script></main>"

    result = PosterApplicationService()._normalize_result(
        {
            "success": True,
            "poster_html": scored_html,
            # 실제 agent는 최상위 validation_score도 항상 함께 내보낸다.
            "validation_score": 0.9,
            "quality": {
                "validation_score": 0.9,
                "scored_sha256": hashlib.sha256(scored_html.encode("utf-8")).hexdigest(),
                "evaluator": "rule_based",
            },
        },
        generation_id="poster_test",
        session_id="session-1",
        timings={"total_ms": 1.0},
        provenance={"route": "direct"},
    )

    assert result["poster_html"] != scored_html
    assert result["quality"]["validation_score"] is None
    assert result["validation_score"] is None
    assert result["quality"]["evaluator"] is None
    assert result["quality"]["scored_sha256"] is None
    assert any("differ from scored bytes" in warning for warning in result["warnings"])


def test_agent_past_deadline_skips_diagram_generation() -> None:
    """D5: an expired budget must not start a new AutoFigure call."""
    calls: list[str] = []

    class SpyClient:
        async def health_check(self) -> bool:
            calls.append("health_check")
            return False

    agent = _offline_agent(enable_critic=False, enable_validation=False)
    agent._autofigure_client = SpyClient()
    content = agent.content_agent.extract(_SAMPLE_REPORT, 1)

    assert agent._generate_autofigure_svgs(content, deadline=time.monotonic() - 1) == []
    assert calls == []

    agent._generate_autofigure_svgs(content, deadline=None)
    assert calls == ["health_check"]


def test_agent_past_deadline_skips_critic_rounds() -> None:
    """D5: an expired budget stops critic rounds; only the free rescore remains."""
    agent = _offline_agent(enable_critic=True, enable_validation=False, max_critic_rounds=2)
    rounds: list[int] = []
    real_critique = agent.critic_agent.critique

    def spy(poster_html, style_guide="", round_idx=0):
        rounds.append(round_idx)
        return real_critique(poster_html, style_guide, round_idx)

    agent.critic_agent.critique = spy

    agent.generate_poster(_SAMPLE_REPORT, num_papers=1, deadline=time.monotonic() - 1)
    assert rounds == [0]

    rounds.clear()
    agent.generate_poster(_SAMPLE_REPORT, num_papers=1)
    assert len(rounds) > 1


def _stub_critique():
    return CritiqueResult(score=0.5, suggestions="tighten the layout", revised_description="")


def test_critic_loop_discards_a_refinement_that_invents_numbers() -> None:
    """B2: an unverified rewrite must not put numbers on the poster that were never there."""
    agent = _offline_agent(enable_critic=True, enable_validation=False)
    before = "<main><p>attribution 18.4 points</p></main>"
    agent.critic_agent.critique = lambda *args, **kwargs: _stub_critique()
    agent._refine_with_gemini = lambda *args, **kwargs: "<main><p>attribution 99.9 points</p></main>"

    warnings: list[str] = []
    html, _ = agent._critic_loop(before, style_guide="", max_rounds=2, warnings=warnings)

    assert html == before
    assert any("99.9" in warning for warning in warnings)


def test_critic_loop_accepts_a_refinement_that_keeps_the_numbers() -> None:
    """B2: the number guard must not reject an honest rewrite."""
    agent = _offline_agent(enable_critic=True, enable_validation=False)
    before = "<main><p>attribution 18.4 points</p></main>"
    after = "<main><section><p>Attribution: 18.4 points</p></section></main>"
    agent.critic_agent.critique = lambda *args, **kwargs: _stub_critique()
    agent._refine_with_gemini = lambda *args, **kwargs: after

    warnings: list[str] = []
    html, _ = agent._critic_loop(before, style_guide="", max_rounds=1, warnings=warnings)

    assert html == after
    assert warnings == []


def test_critic_loop_skips_refinement_when_html_exceeds_the_prompt_limit() -> None:
    """B2: a truncated poster must not be sent back asking for 'complete HTML'."""
    agent = _offline_agent(enable_critic=True, enable_validation=False)
    oversized = "<main>" + "<p>evidence paragraph</p>" * 1500 + "</main>"
    assert len(oversized) > REFINE_INPUT_MAX_CHARS

    refine_calls: list[str] = []
    agent.critic_agent.critique = lambda *args, **kwargs: _stub_critique()

    def spy_refine(*args, **kwargs):
        refine_calls.append("called")
        return "<main>rewritten</main>"

    agent._refine_with_gemini = spy_refine

    warnings: list[str] = []
    html, _ = agent._critic_loop(oversized, style_guide="", max_rounds=2, warnings=warnings)

    assert refine_calls == []
    assert html == oversized
    assert any("Refinement skipped" in warning for warning in warnings)


def test_critic_loop_discards_a_refinement_that_drops_numbers() -> None:
    """F8: 근거 수치 소실은 날조와 같은 급이다. 단방향 검사로는 통과해버린다."""
    agent = _offline_agent(enable_critic=True, enable_validation=False)
    before = "<main><p>attribution 18.4 points across 3 papers</p></main>"
    agent.critic_agent.critique = lambda *args, **kwargs: _stub_critique()
    agent._refine_with_gemini = (
        lambda *args, **kwargs: "<main><p>attribution across 3 papers</p></main>"
    )

    warnings: list[str] = []
    html, _ = agent._critic_loop(before, style_guide="", max_rounds=1, warnings=warnings)

    assert html == before
    assert any("dropped: 18.4" in warning for warning in warnings)


def test_critic_loop_number_guard_ignores_trailing_zero_notation() -> None:
    """F8: 18.4 → 18.40 은 값이 달라진 것이 아니다."""
    agent = _offline_agent(enable_critic=True, enable_validation=False)
    before = "<main><p>attribution 18.4 points</p></main>"
    after = "<main><p>Attribution: 18.40 points</p></main>"
    agent.critic_agent.critique = lambda *args, **kwargs: _stub_critique()
    agent._refine_with_gemini = lambda *args, **kwargs: after

    warnings: list[str] = []
    html, _ = agent._critic_loop(before, style_guide="", max_rounds=1, warnings=warnings)

    assert html == after
    assert warnings == []


def test_critic_loop_keeps_critiquing_after_a_discarded_round() -> None:
    """F8: 롤백은 그 라운드의 수정본만 버린다. 비평까지 포기할 이유는 아니다."""
    agent = _offline_agent(enable_critic=True, enable_validation=False, max_critic_rounds=2)
    before = "<main><p>attribution 18.4 points</p></main>"
    honest = "<main><section><p>Attribution: 18.4 points</p></section></main>"
    rounds: list[int] = []

    def critique(poster_html, style_guide="", round_idx=0):
        rounds.append(round_idx)
        return _stub_critique()

    agent.critic_agent.critique = critique
    replies = ["<main><p>attribution 99.9 points</p></main>", honest]
    agent._refine_with_gemini = lambda *args, **kwargs: replies.pop(0)

    html, _ = agent._critic_loop(before, style_guide="", max_rounds=2, warnings=[])

    assert rounds == [0, 1]
    assert html == honest


def test_critic_loop_refines_a_poster_whose_inline_figure_exceeds_the_prompt_limit() -> None:
    """F7: 도판 base64가 refine 예산을 통째로 잡아먹으면 안 된다."""
    figure_b64 = base64.b64encode(b"\x00" * 75_000).decode()
    poster = (
        "<main>"
        + "<p>evidence paragraph 18.4 points</p>" * 200
        + f'<figure><img src="data:image/png;base64,{figure_b64}" alt="fig" /></figure>'
        + "</main>"
    )
    assert len(poster) > REFINE_INPUT_MAX_CHARS

    agent = _offline_agent(enable_critic=True, enable_validation=False)
    agent.critic_agent.critique = lambda *args, **kwargs: _stub_critique()

    prompt_sizes: list[int] = []

    def spy_refine(poster_html, *args, **kwargs):
        prompt_sizes.append(len(poster_html))
        assert figure_b64 not in poster_html
        return poster_html.replace("<main>", "<main><section>").replace(
            "</main>", "</section></main>"
        )

    agent._refine_with_gemini = spy_refine

    warnings: list[str] = []
    html, _ = agent._critic_loop(poster, style_guide="", max_rounds=1, warnings=warnings)

    assert prompt_sizes and prompt_sizes[0] < REFINE_INPUT_MAX_CHARS
    assert figure_b64 in html
    assert warnings == []


def test_critic_loop_discards_a_refinement_that_loses_inline_figure_data() -> None:
    """F7: 플레이스홀더를 잃은 응답을 채택하면 도판이 깨진 포스터가 나간다."""
    figure_b64 = base64.b64encode(b"\x01" * 75_000).decode()
    poster = f'<main><img src="data:image/png;base64,{figure_b64}" alt="fig" /></main>'

    agent = _offline_agent(enable_critic=True, enable_validation=False)
    agent.critic_agent.critique = lambda *args, **kwargs: _stub_critique()
    agent._refine_with_gemini = lambda *args, **kwargs: "<main><p>figure removed</p></main>"

    warnings: list[str] = []
    html, _ = agent._critic_loop(poster, style_guide="", max_rounds=1, warnings=warnings)

    assert html == poster
    assert any("dropped inline figure data" in warning for warning in warnings)


def _validator_agent(score: float):
    """유료 VLM 채점을 흉내내되 호출 횟수를 센다."""
    from types import SimpleNamespace

    calls: list[str] = []

    def validate(html):
        calls.append("validate")
        return SimpleNamespace(score=score, suggestions="tighten the layout")

    return SimpleNamespace(validate=validate), calls


def test_validator_path_reports_the_vlm_score_it_paid_for() -> None:
    """F14: 계산하고 돈을 쓴 점수를 '평가하지 않았다'고 보고하면 안 된다."""
    agent = _offline_agent(enable_critic=False, enable_validation=True)
    agent.llm = None
    agent.validator_agent, calls = _validator_agent(0.82)

    result = agent.generate_poster(_SAMPLE_REPORT, num_papers=1)

    assert result["validation_score"] == 0.82
    assert result["quality"]["validation_score"] == 0.82
    assert result["quality"]["evaluator"] == "vlm"
    assert result["quality"]["scored_sha256"]
    assert len(calls) == 1  # 두 번째 유료 호출을 만들지 않는다


def test_validator_path_drops_the_score_when_refinement_changes_the_bytes() -> None:
    """F14: D3 불변식 — 점수는 전달되는 바이트를 설명할 때만 유효하다."""
    agent = _offline_agent(enable_critic=False, enable_validation=True)
    agent.llm = None
    agent.validator_agent, calls = _validator_agent(0.40)
    agent._refine_poster = lambda html, suggestions: html + "<!-- refined -->"

    result = agent.generate_poster(_SAMPLE_REPORT, num_papers=1)

    assert result["validation_score"] is None
    assert result["quality"]["evaluator"] is None
    assert result["quality"]["scored_sha256"] is None
    assert len(calls) == 1


def test_service_distinguishes_unrecorded_scored_bytes_from_a_hash_mismatch() -> None:
    """F14: 원인이 다르면 경고도 달라야 한다."""
    result = PosterApplicationService()._normalize_result(
        {"success": True, "poster_html": "<main>safe</main>", "validation_score": 0.9},
        generation_id="poster_test",
        session_id="session-1",
        timings={"total_ms": 1.0},
        provenance={"route": "direct"},
    )

    assert result["validation_score"] is None
    assert any("scored bytes were not recorded" in w for w in result["warnings"])
    assert not any("differ from scored bytes" in w for w in result["warnings"])
