"""Shared poster application service for route entry points."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from src.analytics.mcp_context import record_job_started, record_job_finished

from .resource_policy import (
    DIRECT_NUM_PAPERS_MAX,
    DIRECT_REPORT_MAX_CHARS,
    POSTER_CONCURRENCY,
    POSTER_TIMEOUT_SECONDS,
    PUBLIC_QUALITY_KEYS,
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
from .sanitizer import inject_poster_csp, sanitize_poster_markup

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
        try:
            mcp_measurement = await record_job_started("poster", generation_id)
        except BaseException:
            release_once()
            raise

        def _run_agent() -> Dict[str, Any]:
            outcome = "failed"
            try:
                agent = agent_factory()
                raw_result = agent.generate_poster(
                    report_content=report_content,
                    num_papers=num_papers,
                    output_dir=output_dir,
                    papers_data=papers_data,
                    deadline=started + timeout_seconds,
                )
                timings["total_ms"] = round((time.monotonic() - started) * 1000, 2)
                result = self._normalize_result(
                    raw_result or {}, generation_id=generation_id,
                    session_id=session_id, timings=timings,
                    provenance=provenance or {},
                )
                outcome = "succeeded" if result.get("success") is True else "failed"
                return result
            finally:
                # Runs even after the HTTP caller timed out or disconnected.
                # A response timeout must not erase the worker's actual result.
                record_job_finished(mcp_measurement, "poster", generation_id, outcome)

        worker_future = loop.run_in_executor(None, _run_agent)
        worker_future.add_done_callback(lambda fut: self._consume_and_release(fut, release_once))

        try:
            return await asyncio.wait_for(
                asyncio.shield(worker_future),
                timeout=timeout_seconds,
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
        # sanitize 다음에만 심을 수 있다 — sanitizer가 입력의 http-equiv를
        # 지우므로 순서가 뒤집히면 우리 정책도 지워진다. 아래 해시는 이
        # 주입까지 끝난 최종 전달 바이트를 가리킨다.
        sanitized = inject_poster_csp(sanitized)

        # 점수는 실제로 전달되는 바이트에만 유효하다. sanitize 등으로 바이트가
        # 바뀌었으면 agent가 매긴 점수를 버린다.
        html_sha256 = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
        quality = dict(
            raw.get("quality") or {"validation_score": raw.get("validation_score")}
        )
        scored_sha256 = quality.get("scored_sha256")
        if (
            quality.get("validation_score") is not None
            and scored_sha256 != html_sha256
        ):
            # 점수와 함께 그 점수를 설명하는 메타데이터도 버린다. 남겨두면
            # "점수 없음 + evaluator=rule_based + 낡은 해시"라는 모순이 된다.
            quality["validation_score"] = None
            quality["evaluator"] = None
            quality["scored_sha256"] = None
            # 원인이 다르면 다르게 말한다. 채점 바이트를 기록하지 않은 생산자와
            # 배달 바이트가 바뀐 경우를 같은 문구로 덮으면 진단이 틀어진다.
            warnings.append(
                "Poster quality score was dropped: delivered bytes differ from scored bytes."
                if scored_sha256
                else "Poster quality score was dropped: the scored bytes were not recorded."
            )

        status = normalize_status(raw, sanitized)
        safe_provenance = self._safe_public_provenance(provenance)
        poster_path = raw.get("poster_path") or ""
        artifacts = {
            "html_bytes": len(sanitized.encode("utf-8")),
            "html_sha256": html_sha256,
            "poster_saved": bool(poster_path),
        }

        # allowlist는 해시 비교 이후, result_envelope 직전 한 곳에서만 건다.
        # 먼저 걸면 scored_sha256이 allowlist에서 빠지는 순간 모든 요청에서
        # 점수가 조용히 폐기되고 거짓 경고가 붙는다.
        public_quality = {
            key: value for key, value in quality.items() if key in PUBLIC_QUALITY_KEYS
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
            quality=public_quality,
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
