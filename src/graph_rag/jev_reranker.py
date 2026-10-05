"""Bounded, fail-closed live Jev reranking for hybrid-ranked papers."""

from __future__ import annotations

import asyncio
import math
import os
import time
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

import httpx

from src.utils.jev_client import (
    MODEL,
    RUBRIC_HASH,
    JevError,
    async_score_candidate,
    validate_score_result,
)
from src.utils.paper_utils import generate_result_key

_CANDIDATE_CAP = 20
_MAX_CONCURRENCY = 8
_MAX_WALL_SECONDS = 8.0
_DEFAULT_SCORE_TIMEOUT = 10.0
_STOP_POLL_SECONDS = 0.01
_RERANKER_VERSION = "jev-head20-v1"


class _StopRequested(Exception):
    """A cooperative stop observed by a worker before network admission."""


class _DeadlineExpired(TimeoutError):
    """The request deadline elapsed before a queued worker was admitted."""


def ranking_cache_variant() -> str:
    """Return a cache discriminator without exposing the configured API key."""
    api_key = os.environ.get("TYPESAFE_API_KEY")
    key_presence = (
        "key-present" if isinstance(api_key, str) and api_key.strip() else "key-absent"
    )
    return (
        f"{_RERANKER_VERSION}|{key_presence}|{MODEL}|{RUBRIC_HASH}|"
        f"candidate-cap={_CANDIDATE_CAP}"
    )


async def rerank_papers(
    query: str,
    papers: Sequence[MutableMapping[str, Any]],
    *,
    deadline: float | None = None,
    stop_event=None,
) -> tuple[list[MutableMapping[str, Any]], dict[str, Any]]:
    """Rerank the eligible head of a hybrid list or preserve it unchanged on failure."""
    original = list(papers)

    def metadata(mode: str, scored_count: int = 0) -> dict[str, Any]:
        return {"mode": mode, "model": MODEL, "scored_count": scored_count}

    if _stop_requested(stop_event):
        return original, metadata("cancelled")

    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not isinstance(api_key, str) or not api_key.strip():
        return original, metadata("disabled_no_api_key")

    if not isinstance(query, str) or not query.strip() or len(query) > 2_000:
        return original, metadata("skipped_insufficient_evidence")

    eligible: list[tuple[int, MutableMapping[str, Any], str, str, str]] = []
    for index, paper in enumerate(original[:_CANDIDATE_CAP]):
        if not isinstance(paper, MutableMapping):
            continue
        title = paper.get("title")
        abstract = paper.get("abstract")
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > 1_000
            or not isinstance(abstract, str)
            or not abstract.strip()
            or len(abstract) > 12_000
        ):
            continue
        eligible.append((index, paper, generate_result_key(paper), title, abstract))

    if len(eligible) < 2:
        return original, metadata("skipped_insufficient_evidence")

    now = time.monotonic()
    if deadline is None:
        budget = _MAX_WALL_SECONDS
    elif isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
        return original, metadata("fallback_error")
    else:
        try:
            deadline_value = float(deadline)
        except (OverflowError, ValueError):
            return original, metadata("fallback_error")
        if not math.isfinite(deadline_value):
            return original, metadata("fallback_error")
        budget = min(_MAX_WALL_SECONDS, deadline_value - now)
    if budget <= 0:
        return original, metadata("fallback_timeout")
    expires_at = now + budget

    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    scoring_tasks: list[asyncio.Task[dict[str, Any]]] = []
    stop_task: asyncio.Task[None] | None = None
    results_by_index: dict[int, dict[str, Any]] = {}
    mode: str | None = None

    try:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            try:
                for _, _, paper_key, title, abstract in eligible:
                    scoring_tasks.append(
                        asyncio.create_task(
                            _score_one(
                                semaphore,
                                client,
                                query,
                                {
                                    "paper_key": paper_key,
                                    "title": title,
                                    "abstract": abstract,
                                },
                                api_key,
                                expires_at,
                                stop_event,
                            )
                        )
                    )
                if stop_event is not None:
                    stop_task = asyncio.create_task(_wait_for_stop(stop_event))

                pending = set(scoring_tasks)
                task_indexes = {
                    task: eligible[index][0] for index, task in enumerate(scoring_tasks)
                }
                while pending:
                    waiters = set(pending)
                    if stop_task is not None:
                        waiters.add(stop_task)
                    remaining = expires_at - time.monotonic()
                    if remaining <= 0:
                        mode = "fallback_timeout"
                        break
                    done, _ = await asyncio.wait(
                        waiters,
                        timeout=remaining,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        mode = "fallback_timeout"
                        break
                    if stop_task is not None and stop_task in done:
                        stop_task.result()
                        mode = "cancelled"
                        break
                    for task in done:
                        if task is stop_task:
                            continue
                        pending.remove(task)
                        results_by_index[task_indexes[task]] = task.result()
            finally:
                await _cancel_and_wait(
                    [*scoring_tasks, *([stop_task] if stop_task is not None else [])]
                )
    except asyncio.CancelledError:
        raise
    except _StopRequested:
        mode = "cancelled"
    except Exception as exc:
        mode = "fallback_timeout" if _is_timeout_error(exc) else "fallback_error"

    if mode is not None:
        return original, metadata(mode)
    if len(results_by_index) != len(eligible):
        return original, metadata("fallback_error")

    ordered_eligible = sorted(
        eligible,
        key=lambda item: (-results_by_index[item[0]]["score"], item[0]),
    )
    output = list(original)
    for slot, (_, paper, _, _, _) in zip(
        (item[0] for item in eligible), ordered_eligible, strict=True
    ):
        output[slot] = paper

    if _stop_requested(stop_event):
        return original, metadata("cancelled")
    if time.monotonic() >= expires_at:
        return original, metadata("fallback_timeout")

    for index, paper, _, _, _ in eligible:
        existing = paper.get("_score_breakdown")
        breakdown = dict(existing) if isinstance(existing, Mapping) else {}
        breakdown["jev"] = results_by_index[index]
        paper["_score_breakdown"] = breakdown

    return output, metadata("completed", len(eligible))


async def _score_one(
    semaphore: asyncio.Semaphore,
    client: httpx.AsyncClient,
    query: str,
    candidate: dict[str, str],
    api_key: str,
    expires_at: float,
    stop_event,
) -> dict[str, Any]:
    async with semaphore:
        if _stop_requested(stop_event):
            raise _StopRequested
        timeout = min(_DEFAULT_SCORE_TIMEOUT, expires_at - time.monotonic())
        if timeout <= 0:
            raise _DeadlineExpired
        result = await async_score_candidate(
            query,
            candidate,
            api_key=api_key,
            client=client,
            timeout=timeout,
        )
        validate_score_result(result)
        return result


async def _wait_for_stop(stop_event) -> None:
    while not stop_event.is_set():
        await asyncio.sleep(_STOP_POLL_SECONDS)


async def _cancel_and_wait(tasks: list[asyncio.Task[Any]]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _stop_requested(stop_event) -> bool:
    if stop_event is None:
        return False
    return bool(stop_event.is_set())


def _is_timeout_error(error: Exception) -> bool:
    return isinstance(error, (TimeoutError, httpx.TimeoutException)) or (
        isinstance(error, JevError) and str(error) == "TypeSafe request timed out"
    )
