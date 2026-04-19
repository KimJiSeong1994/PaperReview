"""Tests for Phase-1 US-001 OpenAI prompt-caching alignment.

These tests lock in the properties the user-story relies on:

1. The system prompt passed to the LLM is byte-identical across calls.
2. Every ``*_SYSTEM(_PROMPT)`` constant exceeds the 1024-token threshold
   OpenAI's automatic prompt cache requires.
3. :mod:`routers.llm_cache` supports the split-key storage scheme while
   remaining backward-compatible with legacy single-key entries.
4. A golden-output regression harness exists for 20 reference reviews
   (currently ``xfail`` until the golden dataset is checked in).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from routers import llm_cache
from tests._review_hash import canonical_review_hash
from routers.highlight_service import (
    AUTO_HIGHLIGHT_SYSTEM,
    AUTO_HIGHLIGHT_SYSTEM_PROMPT,
    AUTO_HIGHLIGHT_USER_PREFIX,
    PDF_HIGHLIGHT_SYSTEM,
    PDF_HIGHLIGHT_SYSTEM_PROMPT,
    PDF_HIGHLIGHT_USER_PREFIX,
)
from routers.paper_review_service import (
    PAPER_REVIEW_SYSTEM_PROMPT,
    PAPER_REVIEW_USER_PREFIX,
    generate_paper_review,
)
from routers.reviews import DEEP_REVIEW_SYSTEM_PROMPT, FAST_REVIEW_SYSTEM_PROMPT


# ── tiktoken with 4-char fallback ─────────────────────────────────────


def _count_tokens(text: str) -> int:
    """Return token count; fall back to ``len(text)//4`` if tiktoken missing."""
    try:
        import tiktoken

        enc = tiktoken.encoding_for_model("gpt-4")
        return len(enc.encode(text))
    except Exception:  # pragma: no cover — CI without tiktoken
        return len(text) // 4


# ── AC #5: system prompts must be ≥1024 tokens ────────────────────────


@pytest.mark.parametrize(
    "name, text",
    [
        ("PAPER_REVIEW_SYSTEM_PROMPT", PAPER_REVIEW_SYSTEM_PROMPT),
        ("AUTO_HIGHLIGHT_SYSTEM", AUTO_HIGHLIGHT_SYSTEM),
        ("PDF_HIGHLIGHT_SYSTEM", PDF_HIGHLIGHT_SYSTEM),
    ],
)
def test_system_prompt_token_count_ge_1024(name: str, text: str) -> None:
    n = _count_tokens(text)
    assert n >= 1024, f"{name} has {n} tokens, OpenAI prompt cache requires ≥1024"


def test_system_aliases_match_canonical() -> None:
    """The ``_SYSTEM`` alias must be the exact same object as ``_SYSTEM_PROMPT``."""
    assert AUTO_HIGHLIGHT_SYSTEM is AUTO_HIGHLIGHT_SYSTEM_PROMPT
    assert PDF_HIGHLIGHT_SYSTEM is PDF_HIGHLIGHT_SYSTEM_PROMPT


# ── AC #1-3: system prompt immutability at the LLM boundary ───────────


class _CapturingClient:
    """Minimal OpenAI-compatible mock that records the last ``create`` payload."""

    def __init__(self, response_payload: str = '{"summary": "ok", "strengths": [], "weaknesses": [], "methodology_assessment": {"rigor": 3, "novelty": 3, "reproducibility": 3, "commentary": "c"}, "key_contributions": [], "questions_for_authors": [], "overall_score": 5, "confidence": 3, "detailed_review_markdown": "## Summary\\nstub"}') -> None:
        self._payload = response_payload
        self.last_kwargs: dict[str, Any] | None = None
        self.chat = MagicMock()
        self.chat.completions = MagicMock()
        self.chat.completions.create = self._create

    def _create(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        choice = MagicMock()
        choice.message = MagicMock()
        choice.message.content = self._payload
        resp = MagicMock()
        resp.choices = [choice]
        resp.usage = MagicMock()
        return resp


def test_paper_review_system_is_immutable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling ``generate_paper_review`` on two different papers must send the
    byte-identical ``system`` content each time. The ``user`` message may (and
    must) vary, but its fixed prefix must also be byte-identical."""
    # Isolate file cache to tmpdir so we actually hit the client both times.
    monkeypatch.setattr(llm_cache, "CACHE_DIR", tmp_path / "llm")

    client = _CapturingClient()

    paper_a = {"title": "Paper A", "authors": ["Alice"], "year": 2024, "abstract": "A abstract."}
    paper_b = {"title": "Paper B with unicode 논문", "authors": ["Bob"], "year": 2025, "abstract": "Different abstract with 한국어 content."}

    generate_paper_review(paper_a, client)
    first_system = client.last_kwargs["messages"][0]["content"]
    first_user = client.last_kwargs["messages"][1]["content"]

    generate_paper_review(paper_b, client)
    second_system = client.last_kwargs["messages"][0]["content"]
    second_user = client.last_kwargs["messages"][1]["content"]

    assert first_system == second_system, "system prompt must be byte-identical"
    assert first_system == PAPER_REVIEW_SYSTEM_PROMPT

    # Fixed user prefix cached across calls
    assert first_user.startswith(PAPER_REVIEW_USER_PREFIX)
    assert second_user.startswith(PAPER_REVIEW_USER_PREFIX)

    # The variable body after the prefix must differ (different papers).
    assert first_user != second_user


def test_paper_review_system_has_no_fstring_markers() -> None:
    """Guard-rail against accidental interpolation regressions."""
    # Placeholders that suggest unfinished f-string interpolation.
    for token in ("{title}", "{abstract}", "{authors}", "{year}", "{paper}"):
        assert token not in PAPER_REVIEW_SYSTEM_PROMPT
    assert "{title}" not in AUTO_HIGHLIGHT_SYSTEM
    assert "{title}" not in PDF_HIGHLIGHT_SYSTEM


def test_reviews_py_system_prompts_are_stable() -> None:
    """AC #3: fast_review / deep_review system prompts are immutable strings."""
    assert isinstance(FAST_REVIEW_SYSTEM_PROMPT, str)
    assert isinstance(DEEP_REVIEW_SYSTEM_PROMPT, str)
    # No dynamic interpolation artefacts (f-string placeholders like {var}).
    for s in (FAST_REVIEW_SYSTEM_PROMPT, DEEP_REVIEW_SYSTEM_PROMPT):
        assert not re.search(r"\{[A-Za-z_][A-Za-z0-9_]*\}", s), (
            f"f-string interpolation placeholder found: {s!r}"
        )


# ── AC #4: llm_cache split-key behaviour ──────────────────────────────


def test_llm_cache_split_keys_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Writing with ``fixed_prefix`` and reading with the same prefix must hit."""
    monkeypatch.setattr(llm_cache, "CACHE_DIR", tmp_path / "llm")

    system = "SYSTEM_PROMPT " * 10
    prefix = "FIXED_PREFIX"
    user_a = prefix + "variable body A"
    user_b = prefix + "variable body B"

    llm_cache.set_cache(system, user_a, "m", 0.0, "resp-A", fixed_prefix=prefix)
    llm_cache.set_cache(system, user_b, "m", 0.0, "resp-B", fixed_prefix=prefix)

    assert llm_cache.get_cached(system, user_a, "m", 0.0, fixed_prefix=prefix) == "resp-A"
    assert llm_cache.get_cached(system, user_b, "m", 0.0, fixed_prefix=prefix) == "resp-B"

    # Different variable body must miss.
    assert llm_cache.get_cached(system, prefix + "other", "m", 0.0, fixed_prefix=prefix) is None


def test_llm_cache_legacy_single_key_still_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Legacy callers that omit ``fixed_prefix`` must keep reading their entries."""
    monkeypatch.setattr(llm_cache, "CACHE_DIR", tmp_path / "llm")

    llm_cache.set_cache("sys", "user", "m", 0.0, "legacy-resp")
    assert llm_cache.get_cached("sys", "user", "m", 0.0) == "legacy-resp"


def test_llm_cache_split_key_entries_are_distinct_from_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Split-key entries must not collide with legacy entries for the same
    ``(system, user)`` pair, so migrating callers cannot accidentally serve
    stale responses from the old scheme."""
    monkeypatch.setattr(llm_cache, "CACHE_DIR", tmp_path / "llm")

    prefix = "PFX"
    system = "SYS"
    user = prefix + "body"

    # Legacy entry claims "old".
    llm_cache.set_cache(system, user, "m", 0.0, "old")
    # Split entry claims "new" with the same user_prompt but a prefix hint.
    llm_cache.set_cache(system, user, "m", 0.0, "new", fixed_prefix=prefix)

    # Both must be reachable via their respective lookup signatures.
    assert llm_cache.get_cached(system, user, "m", 0.0) == "old"
    assert llm_cache.get_cached(system, user, "m", 0.0, fixed_prefix=prefix) == "new"


def test_llm_cache_stats_increment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful hits and misses must update the process-local stats."""
    monkeypatch.setattr(llm_cache, "CACHE_DIR", tmp_path / "llm")
    # Reset counters so a previous test run does not leak into this one.
    for k in list(llm_cache._cache_stats):
        llm_cache._cache_stats[k] = 0

    llm_cache.set_cache("s", "pfx-body", "m", 0.0, "r", fixed_prefix="pfx-")
    assert llm_cache.get_cached("s", "pfx-body", "m", 0.0, fixed_prefix="pfx-") == "r"
    assert llm_cache.get_cached("s", "pfx-other", "m", 0.0, fixed_prefix="pfx-") is None

    stats = llm_cache.get_cache_stats()
    assert stats["full_hit"] == 1
    assert stats["miss"] == 1


# ── AC #6: 20-sample golden regression (scaffolded, xfail until data lands) ──

_GOLDEN_DIR = Path(__file__).parent / "goldens" / "paper_reviews"


def _load_goldens() -> list[dict]:
    """Load ``tests/goldens/paper_reviews/*.json``.

    Each file is a dict of the shape::

        {"paper": {..}, "review": {..}, "review_hash": "<sha256 hex>"}

    Generate goldens with ``python scripts/generate_review_goldens.py`` once
    the dataset is curated (see the xfail reason below).
    """
    if not _GOLDEN_DIR.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(_GOLDEN_DIR.glob("*.json"))]


@pytest.mark.xfail(
    reason="golden dataset (tests/goldens/paper_reviews/*.json, 20 samples) TBD — "
    "drop curated papers + expected review hashes into that directory to activate.",
    strict=False,
)
def test_paper_review_golden_hash_regression() -> None:
    goldens = _load_goldens()
    assert len(goldens) == 20, f"expected 20 goldens, found {len(goldens)}"

    for fixture in goldens:
        got = canonical_review_hash(fixture["review"])
        assert got == fixture["review_hash"], (
            f"hash drift for {fixture['paper'].get('title', '?')}: "
            f"got {got}, want {fixture['review_hash']}"
        )
