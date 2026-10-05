"""Offline contract tests for the TypeSafe Jev paper scoring client."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from src.utils.jev_client import (
    API_URL,
    MODEL,
    RUBRIC_HASH,
    RUBRIC_VERSION,
    JevError,
    async_score_candidate,
    score_candidate,
    validate_score_result,
)
from src.search_eval.judged_replay import digest

_API_KEY = "test-key-do-not-leak"


def _candidate(**extra):
    return {
        "paper_key": "arxiv:2401.01234",
        "title": "Graph neural networks for molecule property prediction",
        "abstract": "We study message-passing graph networks for molecular property prediction.",
        **extra,
    }


def _payload(**overrides):
    answer = {
        "type": "score",
        "score": 2.2,
        "legend": {"0": "none", "1": "weak", "2": "partial", "3": "strong"},
        "probabilities": {"0": 0.0, "1": 0.1, "2": 0.6, "3": 0.3},
        "confidence": 0.7,
    }
    response = {
        "model": MODEL,
        "answers": {"relevance": answer},
        "usage": {"input_tokens": 120, "output_tokens": 25},
    }
    for key, value in overrides.items():
        if key == "answer":
            response["answers"]["relevance"] = value
        else:
            response[key] = value
    return response


def _client_for(payload=None, *, status_code=200, content=None, follow_redirects=False):
    def handler(request):
        if content is not None:
            return httpx.Response(status_code, content=content, request=request)
        return httpx.Response(
            status_code,
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            request=request,
        )

    return httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=follow_redirects,
    )


def test_request_contract_sends_only_query_and_required_candidate_fields():
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=_payload(), request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = score_candidate(
            "molecular graph prediction",
            _candidate(secret="must not be sent", unrelated_metadata={"x": 1}),
            api_key=_API_KEY,
            client=client,
        )

    request = captured[0]
    body = json.loads(request.content)
    assert request.method == "POST"
    assert str(request.url) == API_URL
    assert request.headers["Authorization"] == f"Bearer {_API_KEY}"
    assert request.headers["Content-Type"] == "application/json"
    assert body["model"] == MODEL
    assert set(body) == {"model", "state", "questions"}
    assert body["state"] == {
        "query": "molecular graph prediction",
        "title": _candidate()["title"],
        "abstract": _candidate()["abstract"],
    }
    assert set(body["state"]) == {"query", "title", "abstract"}
    question = body["questions"]["relevance"]
    assert set(body["questions"]) == {"relevance"}
    assert question["type"] == "score"
    assert len(question["criteria"]) == 4
    assert digest(question) == RUBRIC_HASH
    assert "untrusted evidence" in question["instructions"]
    assert (
        "Missing or vague evidence cannot imply relevance." in question["instructions"]
    )
    assert set(result) == {
        "model",
        "rubric_version",
        "score",
        "confidence",
        "probabilities",
        "usage",
        "elapsed_ms",
    }
    assert "secret" not in request.content.decode()
    assert result["rubric_version"] == RUBRIC_VERSION


def test_valid_score_response_is_normalized_and_injected_client_stays_open():
    client = _client_for(_payload())
    result = score_candidate(
        "graph molecules", _candidate(), api_key=_API_KEY, client=client
    )

    assert result == {
        "model": MODEL,
        "rubric_version": RUBRIC_VERSION,
        "score": 2.2,
        "confidence": 0.7,
        "probabilities": {"0": 0.0, "1": 0.1, "2": 0.6, "3": 0.3},
        "usage": {"input_tokens": 120, "output_tokens": 25},
        "elapsed_ms": result["elapsed_ms"],
    }
    assert isinstance(result["elapsed_ms"], int)
    assert not client.is_closed
    client.close()


@pytest.mark.asyncio
async def test_async_score_response_uses_same_validated_contract_and_keeps_client_open():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json=_payload(), request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    ) as client:
        result = await async_score_candidate(
            "graph molecules", _candidate(), api_key=_API_KEY, client=client
        )
        assert not client.is_closed

    assert requests and str(requests[0].url) == API_URL
    assert requests[0].headers["Authorization"] == f"Bearer {_API_KEY}"
    assert result["model"] == MODEL
    assert result["rubric_version"] == RUBRIC_VERSION
    assert result["score"] == 2.2
    validate_score_result(result)


@pytest.mark.asyncio
async def test_async_invalid_response_reuses_strict_validation():
    async def handler(request):
        answer = {
            "type": "score",
            "score": 1.0,
            "confidence": 0.8,
            "probabilities": {"0": 0, "1": 0, "2": 1, "3": 0},
        }
        return httpx.Response(200, json=_payload(answer=answer), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(JevError, match="^Invalid score result score$"):
            await async_score_candidate(
                "graph molecules", _candidate(), api_key=_API_KEY, client=client
            )


@pytest.mark.asyncio
async def test_async_cancellation_propagates_without_closing_injected_client():
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.Event().wait()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        request_task = asyncio.create_task(
            async_score_candidate(
                "graph molecules", _candidate(), api_key=_API_KEY, client=client
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=1)
        request_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request_task
        assert not client.is_closed


def test_observed_two_decimal_wire_response_is_accepted_without_normalization():
    probabilities = {"0": 0.11, "1": 0.81, "2": 0.07, "3": 0.0}
    answer = {
        "type": "score",
        "score": 0.97,
        "confidence": 0.81,
        "probabilities": probabilities,
    }
    client = _client_for(_payload(answer=answer))

    with client:
        result = score_candidate(
            "graph molecules", _candidate(), api_key=_API_KEY, client=client
        )

    assert result["score"] == 0.97
    assert result["confidence"] == 0.81
    assert result["probabilities"] == probabilities


def test_probability_rounding_accepts_conservative_sum_of_1_01():
    probabilities = {"0": 0.11, "1": 0.81, "2": 0.08, "3": 0.01}
    answer = {
        "type": "score",
        "score": 1.0,
        "confidence": 0.81,
        "probabilities": probabilities,
    }
    client = _client_for(_payload(answer=answer))

    with client:
        result = score_candidate(
            "graph molecules", _candidate(), api_key=_API_KEY, client=client
        )

    assert result["probabilities"] == probabilities


def test_probability_rounding_tolerance_covers_float_boundary():
    validate_score_result(
        {
            "model": MODEL,
            "rubric_version": RUBRIC_VERSION,
            "score": 1.56,
            "confidence": 0.5,
            "probabilities": {"0": 0.25, "1": 0.25, "2": 0.25, "3": 0.27},
            "usage": {"input_tokens": 1, "output_tokens": 2},
            "elapsed_ms": 0,
        }
    )


@pytest.mark.parametrize(
    ("score", "probabilities"),
    [
        (1.437, {"0": 0.25, "1": 0.25, "2": 0.25, "3": 0.229}),
        (1.563, {"0": 0.25, "1": 0.25, "2": 0.25, "3": 0.271}),
    ],
)
def test_probability_sum_errors_beyond_rounding_tolerance_are_rejected(
    score, probabilities
):
    with pytest.raises(JevError, match="^Invalid score result probabilities$"):
        validate_score_result(
            {
                "model": MODEL,
                "rubric_version": RUBRIC_VERSION,
                "score": score,
                "confidence": 0.5,
                "probabilities": probabilities,
                "usage": {"input_tokens": 1, "output_tokens": 2},
                "elapsed_ms": 0,
            }
        )


def test_score_rounding_tolerance_covers_float_boundary():
    validate_score_result(
        {
            "model": MODEL,
            "rubric_version": RUBRIC_VERSION,
            "score": 2.24,
            "confidence": 0.5,
            "probabilities": {"0": 0.0, "1": 0.0, "2": 0.795, "3": 0.205},
            "usage": {"input_tokens": 1, "output_tokens": 2},
            "elapsed_ms": 0,
        }
    )


@pytest.mark.parametrize("score", [1.535001, 1.464999])
def test_score_deviations_beyond_rounding_tolerance_are_rejected(score):
    with pytest.raises(JevError, match="^Invalid score result score$"):
        validate_score_result(
            {
                "model": MODEL,
                "rubric_version": RUBRIC_VERSION,
                "score": score,
                "confidence": 0.5,
                "probabilities": {"0": 0.25, "1": 0.25, "2": 0.25, "3": 0.25},
                "usage": {"input_tokens": 1, "output_tokens": 2},
                "elapsed_ms": 0,
            }
        )


@pytest.mark.parametrize(
    "answer",
    [
        {"type": "score", "score": 2.2, "confidence": 0.7},
        {
            "type": "score",
            "score": float("nan"),
            "confidence": 0.7,
            "probabilities": {"0": 0, "1": 0, "2": 1, "3": 0},
        },
        {
            "type": "score",
            "score": True,
            "confidence": 0.7,
            "probabilities": {"0": 0, "1": 0, "2": 1, "3": 0},
        },
        {
            "type": "score",
            "score": 2,
            "confidence": True,
            "probabilities": {"0": 0, "1": 0, "2": 1, "3": 0},
        },
        {
            "type": "score",
            "score": 2,
            "confidence": 0.7,
            "probabilities": {"0": 0, "1": 0, "2": 1, "3": float("inf")},
        },
        {
            "type": "score",
            "score": 2,
            "confidence": 0.7,
            "probabilities": {"0": 0, "1": 0, "2": 1},
        },
        {
            "type": "score",
            "score": 2,
            "confidence": 0.7,
            "probabilities": {"0": 0, "1": 0, "2": 0.9, "3": 0},
        },
        {
            "type": "score",
            "score": 1,
            "confidence": 0.7,
            "probabilities": {"0": 0, "1": 0, "2": 1, "3": 0},
        },
    ],
)
def test_invalid_score_answers_fail_closed(answer):
    client = _client_for(_payload(answer=answer))
    with client, pytest.raises(JevError, match="^Invalid score result"):
        score_candidate(
            "graph molecules", _candidate(), api_key=_API_KEY, client=client
        )


def test_response_answer_type_must_match_score_question():
    answer = {
        "type": "choice",
        "score": 2,
        "confidence": 0.7,
        "probabilities": {"0": 0, "1": 0, "2": 1, "3": 0},
    }
    client = _client_for(_payload(answer=answer))
    with client, pytest.raises(JevError, match="^TypeSafe response is invalid$"):
        score_candidate(
            "graph molecules", _candidate(), api_key=_API_KEY, client=client
        )


def test_nonfinite_json_score_fails_closed():
    raw = json.dumps(_payload()).replace('"score": 2.2', '"score": NaN').encode()
    client = _client_for(content=raw)
    with client, pytest.raises(JevError, match="^Invalid score result"):
        score_candidate(
            "graph molecules", _candidate(), api_key=_API_KEY, client=client
        )


@pytest.mark.parametrize("model", ["jev-latest", "jev-1.12.0", ""])
def test_response_model_must_match_pinned_model(model):
    client = _client_for(_payload(model=model))
    with client, pytest.raises(JevError, match="^TypeSafe response is invalid$"):
        score_candidate(
            "graph molecules", _candidate(), api_key=_API_KEY, client=client
        )


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": True, "output_tokens": 0},
        {"input_tokens": -1, "output_tokens": 0},
        {"input_tokens": 1.5, "output_tokens": 0},
        {"input_tokens": 0},
    ],
)
def test_usage_requires_nonnegative_integer_token_counts(usage):
    client = _client_for(_payload(usage=usage))
    with client, pytest.raises(JevError, match="^TypeSafe response is invalid$"):
        score_candidate(
            "graph molecules", _candidate(), api_key=_API_KEY, client=client
        )


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "TypeSafe authentication failed"),
        (429, "TypeSafe rate limit exceeded"),
        (529, "TypeSafe service overloaded"),
    ],
)
def test_service_errors_are_safe_and_stable(status, message):
    client = _client_for({"detail": _API_KEY}, status_code=status)
    with client, pytest.raises(JevError, match=f"^{message}$") as caught:
        score_candidate(
            "graph molecules", _candidate(), api_key=_API_KEY, client=client
        )
    assert _API_KEY not in str(caught.value)
    assert "detail" not in str(caught.value)


def test_timeout_error_does_not_expose_credentials_or_transport_details():
    def handler(request):
        raise httpx.ReadTimeout(f"failure for {_API_KEY}", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(JevError, match="^TypeSafe request timed out$") as caught:
            score_candidate(
                "graph molecules", _candidate(), api_key=_API_KEY, client=client
            )
    assert _API_KEY not in str(caught.value)


def test_network_error_does_not_expose_credentials():
    def handler(request):
        raise httpx.ConnectError(f"failure for {_API_KEY}", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(JevError, match="^TypeSafe request failed$") as caught:
            score_candidate(
                "graph molecules", _candidate(), api_key=_API_KEY, client=client
            )
    assert _API_KEY not in str(caught.value)


def test_redirect_is_not_followed_even_when_injected_client_enables_redirects():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            307, headers={"Location": "https://other.invalid/steal"}, request=request
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        with pytest.raises(JevError, match="^TypeSafe redirects are not allowed$"):
            score_candidate(
                "graph molecules", _candidate(), api_key=_API_KEY, client=client
            )
    assert len(requests) == 1
    assert str(requests[0].url) == API_URL


@pytest.mark.parametrize(
    ("query", "candidate", "api_key", "timeout"),
    [
        ("x" * 2_001, _candidate(), _API_KEY, 10.0),
        ("query", _candidate(title="t" * 1_001), _API_KEY, 10.0),
        ("query", _candidate(abstract="a" * 12_001), _API_KEY, 10.0),
        ("query", _candidate(title="  "), _API_KEY, 10.0),
        ("query", _candidate(abstract=""), _API_KEY, 10.0),
        ("query", {"title": "title", "abstract": "abstract"}, _API_KEY, 10.0),
        ("query", _candidate(), "  ", 10.0),
        ("query", _candidate(), _API_KEY, 0),
        ("query", _candidate(), _API_KEY, 30.1),
        ("query", _candidate(), _API_KEY, float("nan")),
        ("query", _candidate(), _API_KEY, True),
    ],
)
def test_invalid_inputs_are_rejected_before_network(query, candidate, api_key, timeout):
    called = False

    def handler(request):
        nonlocal called
        called = True
        return httpx.Response(200, json=_payload(), request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(JevError):
            score_candidate(
                query, candidate, api_key=api_key, timeout=timeout, client=client
            )
    assert not called


@pytest.mark.parametrize(
    "mutate",
    [
        lambda result: result.update(score=True),
        lambda result: result.update(score=float("inf")),
        lambda result: result.update(confidence=1.01),
        lambda result: result.update(probabilities={"0": 0, "1": 0, "2": 1}),
        lambda result: result.update(probabilities={"0": 0, "1": 0, "2": 0.8, "3": 0}),
        lambda result: result.update(probabilities={"0": 0, "1": 0, "2": True, "3": 0}),
        lambda result: result.update(usage={"input_tokens": True, "output_tokens": 0}),
        lambda result: result.update(elapsed_ms=-1),
        lambda result: result.update(extra="not in the record contract"),
    ],
)
def test_replay_validator_rejects_invalid_records(mutate):
    result = {
        "model": MODEL,
        "rubric_version": RUBRIC_VERSION,
        "score": 2.0,
        "confidence": 0.5,
        "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0, "3": 0.0},
        "usage": {"input_tokens": 1, "output_tokens": 2},
        "elapsed_ms": 0,
    }
    mutate(result)
    with pytest.raises(JevError):
        validate_score_result(result)


def test_replay_validator_accepts_valid_record():
    validate_score_result(
        {
            "model": MODEL,
            "rubric_version": RUBRIC_VERSION,
            "score": 2.0,
            "confidence": 0.5,
            "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0, "3": 0.0},
            "usage": {"input_tokens": 1, "output_tokens": 2},
            "elapsed_ms": 0,
        }
    )
