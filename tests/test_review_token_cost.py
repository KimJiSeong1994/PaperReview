"""Token-cost guards for the review paths: cache-stable fast prefix, no SDK
retry amplification, capped/parallel mini analyses, tool model for highlights."""
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from tests.test_review_llm_safety import (
    _cleanup_session,
    _clear_deep_review_skillopt_env,
    _make_choice,
    _make_workspace,
    _seed_session,
)


def _run_fast(reviews_mod, monkeypatch, tmp_path, session_id, papers):
    workspace = _make_workspace(tmp_path)
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _make_choice("# Report\n\nBody")
    monkeypatch.setattr(reviews_mod, "get_openai_client", lambda: fake_client)
    assert reviews_mod.run_fast_review(session_id, ["x"], "gpt-4.1", workspace, papers)["status"] == "completed"
    return fake_client.chat.completions.create.call_args.kwargs


def test_fast_review_user_prompt_has_cache_stable_prefix(tmp_path, monkeypatch):
    import routers.reviews as reviews_mod

    _clear_deep_review_skillopt_env(monkeypatch)
    a = [{"title": "Alpha", "abstract": "A " * 50, "authors": ["A"], "year": 2024}]
    b = [{"title": "Beta", "abstract": "B " * 80, "authors": ["B", "C"], "year": 2025},
         {"title": "Gamma", "abstract": "G " * 20, "authors": [], "year": 2023}]
    _seed_session("review_tc_a")
    _seed_session("review_tc_b")
    try:
        ka = _run_fast(reviews_mod, monkeypatch, tmp_path / "a", "review_tc_a", a)
        kb = _run_fast(reviews_mod, monkeypatch, tmp_path / "b", "review_tc_b", b)
    finally:
        _cleanup_session("review_tc_a")
        _cleanup_session("review_tc_b")
    ua, ub = ka["messages"][1]["content"], kb["messages"][1]["content"]
    common = 0
    for x, y in zip(ua, ub):
        if x != y:
            break
        common += 1
    assert common >= 2000, common
    assert ua.startswith(reviews_mod.FAST_REVIEW_USER_PREFIX) and ub.startswith(reviews_mod.FAST_REVIEW_USER_PREFIX)
    assert "석학 교수" not in ua and "석학 교수" in ka["messages"][0]["content"]
    assert ua.index("## 분석 대상 논문들") > ua.index("최종 점검") and "Alpha" in ua and "2편" in ub
    assert ka["max_tokens"] == 20000


def test_without_sdk_retries_only_affects_real_clients():
    from openai import OpenAI

    from routers.reviews import _without_sdk_retries

    real = OpenAI(api_key="test-key")
    assert _without_sdk_retries(real).max_retries == 0
    assert real.max_retries != 0  # with_options returns a copy
    mock = MagicMock()
    assert _without_sdk_retries(mock) is mock


def test_deep_review_runs_analyses_concurrently_in_input_order(monkeypatch, tmp_path):
    from app.DeepAgent import deep_review_agent as module

    active, peak, lock = [0], [0], threading.Lock()

    def analyze(payload):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.15)
        with lock:
            active[0] -= 1
        return json.dumps({"analysis": "ok " + json.loads(payload["paper_json"])["id"]})

    monkeypatch.setattr(module, "analyze_paper_deep", SimpleNamespace(invoke=analyze))
    agent = module.DeepReviewAgent.__new__(module.DeepReviewAgent)
    agent.num_researchers = 2
    agent.workspace = MagicMock(session_id="s", session_path=tmp_path)
    agent.workspace.load_all_analyses.return_value = [{"analysis": "ok"}]
    papers = [{"id": f"p{i}", "title": f"T{i}"} for i in range(4)]
    started = time.perf_counter()
    assert agent.review_papers([p["id"] for p in papers], verbose=False, papers_data=papers)["status"] == "completed"
    assert time.perf_counter() - started < 0.45  # 4 x 0.15s sequential would be 0.6s
    assert peak[0] > 1
    saved = [c.kwargs for c in agent.workspace.save_researcher_analysis.call_args_list]
    assert [s["paper_id"] for s in saved] == ["p0", "p1", "p2", "p3"]
    assert [s["researcher_id"] for s in saved] == ["researcher_1", "researcher_2"] * 2


def test_get_llm_pins_effort_and_output_cap(monkeypatch):
    from app.DeepAgent import deep_review_agent as module

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(module, "_llm_instance", None)
    llm = module.get_llm()
    assert llm.reasoning_effort == "none" and llm.max_tokens == 1200


def test_highlights_use_tool_model(monkeypatch):
    import routers.highlight_service as hs

    monkeypatch.setattr(hs, "get_cached", lambda *a, **k: None)
    monkeypatch.setattr(hs, "set_cache", lambda *a, **k: None)
    client = MagicMock()
    client.chat.completions.create.return_value = _make_choice(json.dumps({"highlights": [{"text": "x"}]}))
    assert hs.generate_highlights("## Abstract\nSome report", "q", "t", client) == [{"text": "x"}]
    assert client.chat.completions.create.call_args.kwargs["model"] == hs.DEFAULT_TOOL_MODEL
