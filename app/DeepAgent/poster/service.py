"""Shared poster application service for route entry points."""

from __future__ import annotations

import asyncio
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .resource_policy import (
    DIRECT_NUM_PAPERS_MAX,
    DIRECT_REPORT_MAX_CHARS,
    POSTER_CONCURRENCY,
    POSTER_TIMEOUT_SECONDS,
)
from .result_contract import (
    CODE_ACTIVE_JOB,
    CODE_GENERATION_FAILED,
    CODE_INPUT_INVALID,
    CODE_INPUT_TOO_LARGE,
    CODE_TIMEOUT_UNCLASSIFIED,
    PosterServiceError,
    new_generation_id,
    normalize_status,
    result_envelope,
)
from .sanitizer import sanitize_poster_markup

_poster_semaphore = asyncio.Semaphore(POSTER_CONCURRENCY)
_active_jobs: dict[str, str] = {}
_active_jobs_lock = threading.Lock()


class PosterApplicationService:
    """Bounded, timed, sanitized poster generation wrapper."""

    async def generate(
        self,
        *,
        report_content: str,
        num_papers: int,
        agent_factory: Callable[[], Any],
        output_dir: Optional[Path] = None,
        papers_data: Optional[List[Dict[str, Any]]] = None,
        session_id: str = "",
        timeout_seconds: int = POSTER_TIMEOUT_SECONDS,
        provenance: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if len(report_content or "") > DIRECT_REPORT_MAX_CHARS:
            raise PosterServiceError(
                413,
                CODE_INPUT_TOO_LARGE,
                "Poster input exceeds maximum size",
                retryable=False,
            )
        if num_papers < 0 or num_papers > DIRECT_NUM_PAPERS_MAX:
            raise PosterServiceError(
                422,
                CODE_INPUT_INVALID,
                "num_papers is outside the supported range",
                retryable=False,
            )

        generation_id = new_generation_id()
        job_key = session_id or generation_id
        with _active_jobs_lock:
            if job_key in _active_jobs:
                raise PosterServiceError(
                    409,
                    CODE_ACTIVE_JOB,
                    "A poster job is already active for this session",
                    retryable=True,
                )
            _active_jobs[job_key] = generation_id

        try:
            await asyncio.wait_for(_poster_semaphore.acquire(), timeout=0.1)
        except asyncio.TimeoutError as exc:
            self._clear_active_job(job_key)
            raise PosterServiceError(
                429,
                CODE_ACTIVE_JOB,
                "Poster generation concurrency budget exhausted",
                retryable=True,
            ) from exc

        release_once = self._release_once(job_key)
        timings: Dict[str, float] = {}
        started = time.monotonic()
        loop = asyncio.get_running_loop()

        def _run_agent() -> Dict[str, Any]:
            agent = agent_factory()
            return agent.generate_poster(
                report_content=report_content,
                num_papers=num_papers,
                output_dir=output_dir,
                papers_data=papers_data,
            )

        worker_future = loop.run_in_executor(None, _run_agent)
        worker_future.add_done_callback(lambda fut: self._consume_and_release(fut, release_once))

        try:
            raw_result = await asyncio.wait_for(
                asyncio.shield(worker_future),
                timeout=timeout_seconds,
            )
            timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)
            return self._normalize_result(
                raw_result or {},
                generation_id=generation_id,
                session_id=session_id,
                timings=timings,
                provenance=provenance or {},
            )
        except asyncio.TimeoutError as exc:
            raise PosterServiceError(
                504,
                CODE_TIMEOUT_UNCLASSIFIED,
                "Poster generation timed out before the worker completed",
                retryable=False,
            ) from exc
        except PosterServiceError:
            raise
        except Exception as exc:
            raise PosterServiceError(
                500,
                CODE_GENERATION_FAILED,
                f"Poster generation failed: {exc}",
                retryable=True,
            ) from exc

    def _normalize_result(
        self,
        raw: Dict[str, Any],
        *,
        generation_id: str,
        session_id: str,
        timings: Dict[str, float],
        provenance: Dict[str, Any],
    ) -> Dict[str, Any]:
        warnings = list(raw.get("warnings") or [])
        html = str(raw.get("poster_html") or "")
        sanitized = sanitize_poster_markup(html)
        if sanitized != html:
            warnings.append("Poster markup was sanitized before delivery.")

        status = normalize_status(raw, sanitized)
        safe_provenance = self._safe_public_provenance(provenance)
        poster_path = raw.get("poster_path") or ""
        artifacts = {
            "html_bytes": len(sanitized.encode("utf-8")),
            "poster_saved": bool(poster_path),
        }

        return result_envelope(
            raw=raw,
            poster_html=sanitized,
            status=status,
            generation_id=generation_id,
            session_id=session_id,
            warnings=warnings,
            timings=timings,
            provenance=safe_provenance,
            artifacts=artifacts,
        )

    @staticmethod
    def _safe_public_provenance(provenance: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: value
            for key, value in provenance.items()
            if key not in {"report_path", "workspace_path", "poster_path"}
        }

    @staticmethod
    def _clear_active_job(job_key: str) -> None:
        with _active_jobs_lock:
            _active_jobs.pop(job_key, None)

    def _release_once(self, job_key: str):
        released = False
        release_lock = threading.Lock()

        def _release() -> None:
            nonlocal released
            with release_lock:
                if released:
                    return
                released = True
            self._clear_active_job(job_key)
            _poster_semaphore.release()

        return _release

    @staticmethod
    def _consume_and_release(fut: asyncio.Future[Any], release_once) -> None:
        try:
            if fut.cancelled():
                return
            fut.exception()
        except Exception:
            pass
        finally:
            release_once()
