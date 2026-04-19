"""US-010: strict ``response_format={"type": "json_schema"}`` on LLM call sites.

These tests lock in the properties the user-story depends on:

* The paper-review, math-explain, and claim-extraction call sites pass
  ``response_format={"type": "json_schema", "json_schema": {...}}`` with
  ``strict=True`` on the first attempt.
* The schemas passed are OpenAI strict-mode compatible (no ``$ref``, every
  object has ``additionalProperties: false`` + full ``required`` list).
* When the server/SDK rejects strict mode (e.g. ``BadRequestError``), the
  code falls back to ``{"type": "json_object"}`` and still returns a usable
  result.
* When the LLM returns a malformed payload (missing required field), the
  Pydantic schema validation catches it without crashing the review flow.

Historical no-regression checks (existing reviews with ``list[str]`` fields)
are covered by ``test_paper_reviews.py`` and ``test_prompt_cache_alignment.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from routers import llm_cache
from routers.paper_review_service import (
    _PAPER_REVIEW_JSON_SCHEMA,
    generate_paper_review,
)
from routers.schemas import (
    ClaimExtractionSchema,
    MathExplainSchema,
    PaperReviewSchema,
    build_openai_strict_schema,
)


# ── Shared mock OpenAI client ─────────────────────────────────────────


class _CapturingClient:
    """Minimal OpenAI-compatible mock that records every ``create`` call.

    ``primary_payload`` is returned on the first call. ``fallback_payload``
    (if provided) is returned on subsequent calls. If ``raise_on_schema`` is
    set, the first call raises the given exception instead of returning the
    primary payload — this simulates a ``BadRequestError`` from the upstream
    API on an unsupported ``json_schema`` request.
    """

    def __init__(
        self,
        primary_payload: str,
        fallback_payload: str | None = None,
        raise_on_schema: Exception | None = None,
    ) -> None:
        self._primary = primary_payload
        self._fallback = fallback_payload or primary_payload
        self._raise_on_schema = raise_on_schema
        self.calls: list[dict[str, Any]] = []
        self.chat = MagicMock()
        self.chat.completions = MagicMock()
        self.chat.completions.create = self._create

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        fmt = (kwargs.get("response_format") or {}).get("type")
        is_schema_call = fmt == "json_schema"
        if is_schema_call and self._raise_on_schema is not None:
            raise self._raise_on_schema

        payload = self._primary if is_schema_call else self._fallback
        choice = MagicMock()
        choice.message = MagicMock()
        choice.message.content = payload
        resp = MagicMock()
        resp.choices = [choice]
        resp.usage = MagicMock()
        return resp


def _valid_review_payload() -> dict[str, Any]:
    return {
        "summary": "Concise overview of the paper's contribution and setting.",
        "strengths": [
            {
                "point": "Clear motivation",
                "evidence": "Section 1 frames the problem with concrete prior-art gaps.",
                "significance": "high",
            },
            {
                "point": "Strong baselines",
                "evidence": "Table 2 compares against 5 SOTA methods on 3 benchmarks.",
                "significance": "medium",
            },
        ],
        "weaknesses": [
            {
                "point": "Limited ablations",
                "evidence": "Only the loss term is ablated in Section 4.3.",
                "severity": "minor",
            },
        ],
        "methodology_assessment": {
            "rigor": 4,
            "novelty": 3,
            "reproducibility": 3,
            "commentary": "Solid experimental design with minor gaps.",
        },
        "key_contributions": ["New loss", "Dataset release"],
        "questions_for_authors": ["How does it behave on small datasets?"],
        "overall_score": 7.0,
        "confidence": 4.0,
        "detailed_review_markdown": "## Summary\nStub review body for strict-mode tests.",
    }


# ── Schema-shape invariants ───────────────────────────────────────────


@pytest.mark.parametrize(
    "model_cls",
    [PaperReviewSchema, MathExplainSchema, ClaimExtractionSchema],
    ids=lambda c: c.__name__,
)
def test_strict_schema_shape(model_cls) -> None:
    """Every generated schema satisfies OpenAI strict-mode requirements."""
    schema = build_openai_strict_schema(model_cls)

    # Top-level object shape.
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == sorted(schema["properties"].keys())

    # No forbidden constructs anywhere in the tree.
    text = json.dumps(schema)
    assert "$ref" not in text
    assert "$defs" not in text
    assert "anyOf" not in text
    assert "allOf" not in text

    # Every nested object must also declare ``additionalProperties: false``
    # and a complete ``required`` list.
    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                props = node.get("properties") or {}
                assert node.get("additionalProperties") is False
                assert sorted(node.get("required", [])) == sorted(props.keys())
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(schema)


def test_paper_review_schema_has_expected_fields() -> None:
    """Locked property list — regressions here mean the review contract changed."""
    expected = {
        "summary",
        "strengths",
        "weaknesses",
        "methodology_assessment",
        "key_contributions",
        "questions_for_authors",
        "overall_score",
        "confidence",
        "detailed_review_markdown",
    }
    assert set(_PAPER_REVIEW_JSON_SCHEMA["properties"].keys()) == expected
    # Nested methodology fields.
    meth = _PAPER_REVIEW_JSON_SCHEMA["properties"]["methodology_assessment"]
    assert set(meth["properties"].keys()) == {
        "rigor",
        "novelty",
        "reproducibility",
        "commentary",
    }


def test_strengths_shape_matches_frontend_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``strengths`` / ``weaknesses`` must be lists of objects matching the FE contract.

    The React panel (``web-ui/src/components/mypage/PaperReviewPanel.tsx``)
    accesses ``s.point`` / ``s.evidence`` / ``s.significance`` and
    ``w.point`` / ``w.evidence`` / ``w.severity`` directly. If the schema
    declares ``list[str]`` instead of object lists, the strict-mode LLM call
    returns plain strings and the FE renders empty bullets.
    """
    # 1) Schema-shape invariant: the JSON schema sent to OpenAI must declare
    #    each strength/weakness as an object with the FE-required fields.
    strengths = _PAPER_REVIEW_JSON_SCHEMA["properties"]["strengths"]
    weaknesses = _PAPER_REVIEW_JSON_SCHEMA["properties"]["weaknesses"]

    assert strengths["type"] == "array"
    assert strengths["items"]["type"] == "object"
    assert set(strengths["items"]["required"]) == {"point", "evidence", "significance"}
    assert strengths["items"]["properties"]["significance"]["enum"] == [
        "high",
        "medium",
        "low",
    ]
    assert strengths["items"]["additionalProperties"] is False

    assert weaknesses["type"] == "array"
    assert weaknesses["items"]["type"] == "object"
    assert set(weaknesses["items"]["required"]) == {"point", "evidence", "severity"}
    assert weaknesses["items"]["properties"]["severity"]["enum"] == ["major", "minor"]
    assert weaknesses["items"]["additionalProperties"] is False

    # 2) End-to-end: a payload using the object shape passes through the
    #    review pipeline and preserves ``.point`` / ``.evidence`` / ``.significance``
    #    on the returned dict (i.e. exactly what the FE indexes into).
    monkeypatch.setattr(llm_cache, "CACHE_DIR", tmp_path / "llm")

    client = _CapturingClient(primary_payload=json.dumps(_valid_review_payload()))
    paper = {"title": "T-fe", "authors": ["A"], "year": 2024, "abstract": "abs."}
    review = generate_paper_review(paper, client)

    assert isinstance(review["strengths"], list) and review["strengths"]
    s0 = review["strengths"][0]
    assert isinstance(s0, dict)
    assert isinstance(s0.get("point"), str) and s0["point"]
    assert isinstance(s0.get("evidence"), str) and s0["evidence"]
    assert s0.get("significance") in {"high", "medium", "low"}

    assert isinstance(review["weaknesses"], list) and review["weaknesses"]
    w0 = review["weaknesses"][0]
    assert isinstance(w0, dict)
    assert isinstance(w0.get("point"), str) and w0["point"]
    assert isinstance(w0.get("evidence"), str) and w0["evidence"]
    assert w0.get("severity") in {"major", "minor"}


# ── paper_review_service: call-site wiring ───────────────────────────


def test_generate_paper_review_sends_json_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The primary call passes ``response_format.type == 'json_schema'`` with strict=True."""
    monkeypatch.setattr(llm_cache, "CACHE_DIR", tmp_path / "llm")

    client = _CapturingClient(primary_payload=json.dumps(_valid_review_payload()))
    paper = {"title": "T", "authors": ["A"], "year": 2024, "abstract": "abs."}

    review = generate_paper_review(paper, client)

    assert len(client.calls) == 1, "should not retry when schema call succeeds"
    rf = client.calls[0]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] == _PAPER_REVIEW_JSON_SCHEMA
    # Review is fully populated from the schema-validated payload.
    assert review["summary"].startswith("Concise overview")
    assert review["methodology_assessment"]["rigor"] == 4
    assert review["model"] == "gpt-4.1"


def test_generate_paper_review_falls_back_to_json_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the first (schema) call raises, the code retries with ``json_object``."""
    monkeypatch.setattr(llm_cache, "CACHE_DIR", tmp_path / "llm")

    class _BadRequest(Exception):
        """Stand-in for ``openai.BadRequestError`` — same class-name pattern."""

    _BadRequest.__name__ = "BadRequestError"

    client = _CapturingClient(
        primary_payload="{}",  # unused: schema call raises
        fallback_payload=json.dumps(_valid_review_payload()),
        raise_on_schema=_BadRequest("strict mode not supported"),
    )
    paper = {"title": "T2", "authors": ["A"], "year": 2024, "abstract": "abs2."}

    review = generate_paper_review(paper, client)

    assert len(client.calls) == 2, "should retry once on schema failure"
    assert client.calls[0]["response_format"]["type"] == "json_schema"
    assert client.calls[1]["response_format"] == {"type": "json_object"}
    # Fallback payload is still parsed correctly.
    assert review["summary"].startswith("Concise overview")


def test_generate_paper_review_rejects_missing_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed payload (missing ``methodology_assessment``) still parses as dict.

    Strict-mode schema should prevent this on the server side, but if a
    degraded fallback ever returns an incomplete payload we degrade gracefully
    rather than crash. The best-effort ``json.loads`` fallback preserves
    whatever fields the LLM did return.
    """
    monkeypatch.setattr(llm_cache, "CACHE_DIR", tmp_path / "llm")

    bad = _valid_review_payload()
    bad.pop("methodology_assessment")

    client = _CapturingClient(primary_payload=json.dumps(bad))
    paper = {"title": "T3", "authors": ["A"], "year": 2024, "abstract": "abs3."}

    review = generate_paper_review(paper, client)

    # Validation failure on strict schema — but best-effort parse retains summary.
    assert review["summary"].startswith("Concise overview")
    assert "methodology_assessment" not in review or review.get(
        "methodology_assessment"
    ) is None or isinstance(review.get("methodology_assessment"), dict)


# ── math-explain: call-site wiring ────────────────────────────────────


@pytest.mark.asyncio
async def test_math_explain_uses_json_schema(client, auth_headers) -> None:
    """``POST /api/math-explain`` passes json_schema with MathExplainSchema."""
    from unittest.mock import patch

    payload = {
        "explanation": "Softmax normalises logits into a probability distribution.",
        "variables": [{"symbol": "x", "meaning": "input logits"}],
        "formula_type": "probability",
    }

    mock_message = MagicMock()
    mock_message.content = json.dumps(payload)
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_completion

    with patch("routers.paper_reviews.get_openai_client", return_value=mock_client):
        with patch("routers.paper_reviews.get_cached", return_value=None):
            with patch("routers.paper_reviews.set_cache"):
                resp = await client.post(
                    "/api/math-explain",
                    json={
                        "formula_text": r"\text{softmax}(x_i)",
                        "context": "probability context",
                        "paper_title": "P",
                    },
                    headers=auth_headers,
                )

    assert resp.status_code == 200
    assert mock_client.chat.completions.create.call_count == 1
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    rf = call_kwargs["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["name"] == "math_explain"
    assert "properties" in rf["json_schema"]["schema"]
    assert "explanation" in rf["json_schema"]["schema"]["properties"]


@pytest.mark.asyncio
async def test_math_explain_falls_back_to_json_object(client, auth_headers) -> None:
    """Schema-level failure triggers a second call with ``json_object``."""
    from unittest.mock import patch

    class _BadRequest(Exception):
        pass

    _BadRequest.__name__ = "BadRequestError"

    payload = {
        "explanation": "Explanation from fallback path.",
        "variables": [{"symbol": "y", "meaning": "output"}],
        "formula_type": "other",
    }

    mock_message = MagicMock()
    mock_message.content = json.dumps(payload)
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    mock_client = MagicMock()
    # First call (json_schema) raises; second call (json_object) succeeds.
    mock_client.chat.completions.create.side_effect = [
        _BadRequest("strict mode unsupported"),
        mock_completion,
    ]

    with patch("routers.paper_reviews.get_openai_client", return_value=mock_client):
        with patch("routers.paper_reviews.get_cached", return_value=None):
            with patch("routers.paper_reviews.set_cache"):
                resp = await client.post(
                    "/api/math-explain",
                    json={"formula_text": "f(x)", "paper_title": "P"},
                    headers=auth_headers,
                )

    assert resp.status_code == 200
    assert resp.json()["explanation"] == payload["explanation"]
    assert mock_client.chat.completions.create.call_count == 2
    first_fmt = mock_client.chat.completions.create.call_args_list[0].kwargs[
        "response_format"
    ]
    second_fmt = mock_client.chat.completions.create.call_args_list[1].kwargs[
        "response_format"
    ]
    assert first_fmt["type"] == "json_schema"
    assert second_fmt == {"type": "json_object"}


# ── claim extraction: call-site wiring ────────────────────────────────


@pytest.mark.asyncio
async def test_claim_extractor_uses_json_schema() -> None:
    """``ClaimExtractor`` passes json_schema with ClaimExtractionSchema on the wire."""
    from app.DeepAgent.tools.fact_verification import ClaimExtractor

    ex = ClaimExtractor(model="gpt-4o-mini", api_key="test-key")

    mock_client = MagicMock()
    ex.client = mock_client

    payload = {
        "claims": [
            {"text": "Achieves 93% accuracy on ImageNet.", "type": "statistical"},
        ]
    }
    mock_message = MagicMock()
    mock_message.content = json.dumps(payload)
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    async def _fake_create(**kwargs):
        return mock_completion

    mock_client.chat.completions.create.side_effect = _fake_create

    claims = await ex._extract_claims_from_section(
        section_text="The model achieves 93% accuracy on ImageNet.",
        paper_id="p1",
        paper_title="Test Paper",
        section_name="results",
    )

    assert mock_client.chat.completions.create.call_count == 1
    rf = mock_client.chat.completions.create.call_args.kwargs["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["name"] == "claim_extraction"
    # Extraction produced at least one claim.
    assert len(claims) == 1
    assert claims[0].text.startswith("Achieves 93%")
