"""F-05 + F-06 regression tests: LLM-safety in the review pipeline.

Covers:

- **F-05** — ``run_fast_review`` must NOT dereference ``None`` chat-completion
  content. Empty content now raises ``ValueError("empty LLM content")`` which
  is included in the retry predicate; after ``max_retries=3`` exhausts, the
  session is marked ``failed`` with an informative error (not a cryptic
  ``TypeError: object of type 'NoneType' has no len()``).
- **F-06** — ``_generate_review_report_content`` must NOT silently swallow
  LLM failures into a hard-coded fallback template while reporting
  ``status="completed"`` to the client. The session is now marked ``failed``
  with the real exception surfaced in ``error``.

Fixture style mirrors ``tests/test_review_session_access.py``: seed the JWT
user, inject a fake review session into the in-memory store, mock the
OpenAI client at ``routers.deps.get_openai_client`` so no real API calls
are made.
"""

import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────


def _make_choice(content: Optional[str]) -> MagicMock:
    """Build a MagicMock shaped like an OpenAI chat completion response."""
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp.choices = [choice]
    resp.usage = MagicMock()
    return resp


def _make_workspace(tmp_path: Path) -> Any:
    """Minimal workspace stub satisfying the attributes used by run_fast_review
    and _generate_review_report_content."""
    ws_path = tmp_path / "ws"
    (ws_path / "reports").mkdir(parents=True, exist_ok=True)
    workspace = types.SimpleNamespace(
        session_id="review_20260423_120000_testxxx",
        session_path=ws_path,
    )
    workspace.save_researcher_analysis = lambda **kw: None
    workspace.get_all_analyses = lambda: []
    return workspace


def _seed_session(session_id: str, username: Optional[str] = "alice_llmsafety") -> None:
    import routers.reviews as reviews_mod

    with reviews_mod.review_sessions_lock:
        reviews_mod.review_sessions[session_id] = {
            "session_id": session_id,
            "username": username,
            "status": "analyzing",
            "progress": "seeded",
            "report_available": False,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


def _cleanup_session(session_id: str) -> None:
    import routers.reviews as reviews_mod

    with reviews_mod.review_sessions_lock:
        reviews_mod.review_sessions.pop(session_id, None)


# Dummy paper data — skip the paper_loader fallback.
_DUMMY_PAPERS = [
    {
        "title": "A Study of Frobnication",
        "abstract": "We frobnicate widgets under adversarial conditions.",
        "authors": [{"name": "Jane Doe"}],
        "year": 2025,
    }
]


# ── F-05: empty content → retry → fail loud ──────────────────────────


def test_run_fast_review_empty_content_marks_failed(tmp_path, monkeypatch):
    """Empty LLM content must NOT crash with a TypeError-like message.

    Before the fix: ``len(None)`` raised ``TypeError: object of type
    'NoneType' has no len()`` and the outer except surfaced that string
    to the user. After: every attempt returns empty content, the retry
    loop exhausts ``max_retries=3``, and the final error clearly
    identifies "empty LLM content".
    """
    import routers.reviews as reviews_mod

    session_id = "review_20260423_120001_f05empty"
    _seed_session(session_id)
    try:
        workspace = _make_workspace(tmp_path)

        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = [
            _make_choice(None),   # attempt 1
            _make_choice(""),      # attempt 2
            _make_choice("   \n"), # attempt 3 (whitespace-only)
        ]

        monkeypatch.setattr(reviews_mod, "get_openai_client", lambda: fake_client)
        # Short-circuit the paper-loader fallback.
        from app.DeepAgent.tools import paper_loader as pl
        monkeypatch.setattr(pl, "load_papers_from_ids", lambda ids: _DUMMY_PAPERS)
        # Remove sleep latency — we already assert on retry count, not timing.
        monkeypatch.setattr(reviews_mod.time, "sleep", lambda *_a, **_k: None)

        result = reviews_mod.run_fast_review(
            session_id=session_id,
            paper_ids=["dummy-1"],
            model="gpt-4.1",
            workspace=workspace,
            papers_data=_DUMMY_PAPERS,
        )

        assert result["status"] == "failed", result
        err = (result.get("error") or "").lower()
        assert "empty llm content" in err, (
            f"error must name the empty-content cause, got: {result['error']!r}"
        )
        assert "nonetype" not in err, (
            f"error must NOT leak a TypeError-style message: {result['error']!r}"
        )
        # Retry loop should have exhausted all 3 attempts.
        assert fake_client.chat.completions.create.call_count == 3
    finally:
        _cleanup_session(session_id)


def test_run_fast_review_retries_on_empty_then_succeeds(tmp_path, monkeypatch):
    """First call returns empty, second returns valid content → status=completed."""
    import routers.reviews as reviews_mod

    session_id = "review_20260423_120002_f05retry"
    _seed_session(session_id)
    try:
        workspace = _make_workspace(tmp_path)

        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = [
            _make_choice(None),
            _make_choice(
                "# Retried Review\n\nValid body content produced on retry."
            ),
        ]

        monkeypatch.setattr(reviews_mod, "get_openai_client", lambda: fake_client)
        from app.DeepAgent.tools import paper_loader as pl
        monkeypatch.setattr(pl, "load_papers_from_ids", lambda ids: _DUMMY_PAPERS)
        monkeypatch.setattr(reviews_mod.time, "sleep", lambda *_a, **_k: None)

        result = reviews_mod.run_fast_review(
            session_id=session_id,
            paper_ids=["dummy-1"],
            model="gpt-4.1",
            workspace=workspace,
            papers_data=_DUMMY_PAPERS,
        )

        assert result["status"] == "completed", result
        assert fake_client.chat.completions.create.call_count == 2
        # Report file must exist with the retried body.
        reports = list((Path(workspace.session_path) / "reports").glob("final_review_*.md"))
        assert reports, "retry-success run must persist a report file"
        body = reports[0].read_text(encoding="utf-8")
        assert "Retried Review" in body
    finally:
        _cleanup_session(session_id)


# ── F-06: deep-review LLM failure → fails loud, no template fallback ─


def test_generate_review_report_content_llm_failure_fails_loud(tmp_path, monkeypatch):
    """LLM exception during deep-review report generation must propagate.

    Previously a silent fallback template was returned and the caller
    still marked the session "completed". Now ``_generate_review_report_content``
    raises, and the background caller ``run_deep_review_background`` marks
    the session ``failed`` with ``error`` surfacing the real cause and
    ``report_available`` stays ``False``.
    """
    import routers.reviews as reviews_mod

    session_id = "review_20260423_120003_f06loud"
    _seed_session(session_id, username="bob_f06")
    try:
        workspace = _make_workspace(tmp_path)

        # Mock _generate_review_report_content directly to raise — this is
        # the exact failure mode (network error, API policy rejection, etc.)
        # that previously fell through to _generate_fallback_report.
        sentinel_err = RuntimeError("upstream LLM 503 service unavailable")

        def _boom(*_a, **_kw):
            raise sentinel_err

        monkeypatch.setattr(reviews_mod, "_generate_review_report_content", _boom)

        # Skip the DeepReviewAgent heavy path by mocking its module-level
        # import with a stub that reports a completed result.
        class _StubAgent:
            def __init__(self, **kw):
                pass

            def review_papers(self, **kw):
                return {
                    "status": "completed",
                    "papers_reviewed": 1,
                    "workspace_path": str(workspace.session_path),
                    "verification": {},
                }

        stub_mod = types.SimpleNamespace(DeepReviewAgent=_StubAgent)
        monkeypatch.setitem(
            __import__("sys").modules,
            "app.DeepAgent.deep_review_agent",
            stub_mod,
        )

        reviews_mod.run_deep_review_background(
            session_id=session_id,
            paper_ids=["dummy-1"],
            papers_data=None,
            num_researchers=1,
            model="gpt-4.1",
            workspace=workspace,
            fast_mode=False,
        )

        with reviews_mod.review_sessions_lock:
            final = dict(reviews_mod.review_sessions[session_id])

        assert final["status"] == "failed", (
            f"session must be failed on report-gen error, got: {final}"
        )
        assert final.get("report_available") is False, (
            "report_available must stay False when report generation fails"
        )
        err = (final.get("error") or "").lower()
        assert "upstream llm 503" in err or "report generation failed" in err, (
            f"error must preserve real LLM failure info, got: {final['error']!r}"
        )

        # Crucially: no fallback-template string in any persisted report body.
        reports_dir = Path(workspace.session_path) / "reports"
        if reports_dir.exists():
            for p in reports_dir.glob("*.md"):
                body = p.read_text(encoding="utf-8")
                assert "fallback template was used" not in body.lower(), (
                    f"fallback template leaked into {p}"
                )
                assert "Systematic Literature Review: In-Depth Analysis" not in body, (
                    f"hard-coded English template leaked into {p}"
                )
    finally:
        _cleanup_session(session_id)


# ── Helper-level unit tests ──────────────────────────────────────────


def test_safe_llm_content_rejects_none_and_empty():
    """Unit-level: the helper must raise with the exact retryable phrase."""
    from routers.reviews import _safe_llm_content

    with pytest.raises(ValueError, match="empty LLM content"):
        _safe_llm_content(_make_choice(None))
    with pytest.raises(ValueError, match="empty LLM content"):
        _safe_llm_content(_make_choice(""))
    with pytest.raises(ValueError, match="empty LLM content"):
        _safe_llm_content(_make_choice("   \n\t  "))


def test_safe_llm_content_strips_and_returns():
    from routers.reviews import _safe_llm_content

    assert _safe_llm_content(_make_choice("  hello  ")) == "hello"
    assert _safe_llm_content(_make_choice("body\n")) == "body"
