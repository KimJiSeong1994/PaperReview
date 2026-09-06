"""
AutoFigure-Edit integration endpoints:
  POST /api/autofigure/method-to-svg
  POST /api/autofigure/figure-to-svg
  GET  /api/autofigure/health
  POST /api/autofigure/generate-poster-figures

Acts as a proxy/orchestrator between the frontend and the
AutoFigure-Edit microservice, providing SVG generation from
methodology text or raster figures.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request
from src.analytics.mcp_context import record_job_started, record_job_finished_async

from app.DeepAgent.poster.resource_policy import (
    AUTOFIGURE_IMAGE_B64_MAX_CHARS,
    AUTOFIGURE_MAX_FIGURES,
    AUTOFIGURE_PAPER_ANALYSES_MAX,
    AUTOFIGURE_POSTER_BATCH_CONCURRENCY,
    AUTOFIGURE_POSTER_BATCH_TIMEOUT_SECONDS,
    AUTOFIGURE_TEXT_MAX_CHARS,
)
from app.DeepAgent.poster.result_contract import (
    CODE_ACTIVE_JOB,
    CODE_SESSION_UNAVAILABLE,
    CODE_TIMEOUT_UNCLASSIFIED,
)
from app.DeepAgent.poster.sanitizer import sanitize_poster_markup

from .deps import get_current_user, get_optional_user, limiter, review_sessions, review_sessions_lock

logger = logging.getLogger(__name__)

# ── Graceful import of AutoFigure client ─────────────────────────────
try:
    from app.DeepAgent.tools.autofigure_client import (
        build_method_prompt,
        build_paper_figure_prompts,
        get_autofigure_client,
    )
    _autofigure_available = True
except ImportError:
    _autofigure_available = False
    logger.warning(
        "autofigure_client not available — AutoFigure endpoints will "
        "return 503 until the module is installed."
    )

router = APIRouter(prefix="/api/autofigure", tags=["autofigure"])
_poster_batch_semaphore = asyncio.Semaphore(AUTOFIGURE_POSTER_BATCH_CONCURRENCY)


# ── Pydantic models ──────────────────────────────────────────────────

class MethodToSvgRequest(BaseModel):
    """Request body for converting methodology text to SVG."""

    method_text: str = Field(
        ...,
        min_length=1,
        max_length=AUTOFIGURE_TEXT_MAX_CHARS,
        description="Methodology text to visualise",
    )
    paper_title: str = Field(default="", max_length=500, description="Optional paper title for context")
    style_hints: Optional[Dict[str, Any]] = Field(
        default=None, description="Color scheme and styling hints"
    )
    optimize_iterations: int = Field(
        default=1, ge=1, le=10, description="Number of optimisation iterations"
    )


class MethodToSvgResponse(BaseModel):
    """Shared response schema for SVG generation endpoints."""

    success: bool
    svg_content: str = Field(default="", description="Final SVG string")
    figure_png_b64: str = Field(default="", description="Base64 of LLM-generated figure")
    error: str = ""


class FigureToSvgRequest(BaseModel):
    """Request body for converting a raster image to SVG."""

    image_base64: str = Field(
        ...,
        min_length=1,
        max_length=AUTOFIGURE_IMAGE_B64_MAX_CHARS,
        description="Base64-encoded image data",
    )
    mime_type: str = Field(default="image/png", pattern=r"^image/(png|jpeg|jpg|webp)$", description="MIME type of the image")


class PosterFiguresRequest(BaseModel):
    """Request body for batch poster figure generation."""

    session_id: str = Field(..., min_length=1, max_length=128, description="Deep review session ID")
    methodology: str = Field(
        ...,
        min_length=1,
        max_length=AUTOFIGURE_TEXT_MAX_CHARS,
        description="Extracted methodology text",
    )
    paper_analyses: List[Dict[str, Any]] = Field(
        default_factory=list,
        max_length=AUTOFIGURE_PAPER_ANALYSES_MAX,
        description="Per-paper analysis data",
    )
    max_figures: int = Field(default=3, ge=1, le=AUTOFIGURE_MAX_FIGURES, description="Maximum figures to generate")


class PosterFiguresResponse(BaseModel):
    """Response for batch poster figure generation."""

    success: bool
    figures: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of generated figures with paper_title, svg_content, figure_png_b64",
    )
    total_generated: int = 0
    errors: List[str] = Field(default_factory=list)


# ── Helper ───────────────────────────────────────────────────────────

def _require_autofigure() -> None:
    """Raise 503 if the AutoFigure client module is not importable."""
    if not _autofigure_available:
        raise HTTPException(
            status_code=503,
            detail="AutoFigure service is not available. The autofigure_client module could not be imported.",
        )


def _require_poster_session_owner(session_id: str, username: str) -> None:
    """Return 404 for unknown or non-owned sessions to avoid enumeration."""
    with review_sessions_lock:
        session = review_sessions.get(session_id)
        if not session:
            raise HTTPException(
                status_code=404,
                detail={
                    "poster_status": "failed",
                    "status": "failed",
                    "success": False,
                    "error_code": CODE_SESSION_UNAVAILABLE,
                    "retryable": False,
                },
            )
        if session.get("username") != username:
            raise HTTPException(status_code=404, detail="Session not found")


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/method-to-svg", response_model=MethodToSvgResponse)
async def method_to_svg(
    body: MethodToSvgRequest,
    username: str | None = Depends(get_optional_user),
) -> MethodToSvgResponse:
    """Convert methodology text into an SVG diagram via the AutoFigure service."""
    _require_autofigure()
    start = time.monotonic()
    logger.info(
        "[AutoFigure] method-to-svg requested by=%s text_len=%d iterations=%d",
        username or "anonymous",
        len(body.method_text),
        body.optimize_iterations,
    )

    job_id = f"figure_{uuid4().hex}"
    mcp_measurement = await record_job_started("figure", job_id)
    outcome = "unknown"
    try:
        client = get_autofigure_client()
        result = await client.method_to_svg(
            body.method_text,
            style_hints=body.style_hints,
            optimize_iterations=body.optimize_iterations,
        )
        elapsed = time.monotonic() - start
        logger.info("[AutoFigure] method-to-svg completed in %.2fs", elapsed)
        response = MethodToSvgResponse(
            success=result.success,
            svg_content=sanitize_poster_markup(result.final_svg),
            figure_png_b64=result.figure_png_b64,
            error=result.error,
        )
        outcome = "succeeded" if response.success else "failed"
        return response
    except HTTPException:
        raise
    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.error(
            "[AutoFigure] method-to-svg failed after %.2fs: %s",
            elapsed,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail=f"AutoFigure service error: {exc}",
        ) from exc
    finally:
        # A disconnected/timed-out upstream request cannot prove whether its
        # remote generation finished. Only a received result establishes that.
        await record_job_finished_async(mcp_measurement, "figure", job_id, outcome)


@router.post("/figure-to-svg", response_model=MethodToSvgResponse)
async def figure_to_svg(
    body: FigureToSvgRequest,
    username: str | None = Depends(get_optional_user),
) -> MethodToSvgResponse:
    """Convert a base64-encoded raster image into an SVG via the AutoFigure service."""
    _require_autofigure()
    start = time.monotonic()
    logger.info(
        "[AutoFigure] figure-to-svg requested by=%s mime=%s payload_len=%d",
        username or "anonymous",
        body.mime_type,
        len(body.image_base64),
    )

    try:
        client = get_autofigure_client()
        result = await client.figure_to_svg(body.image_base64, body.mime_type)
        elapsed = time.monotonic() - start
        logger.info("[AutoFigure] figure-to-svg completed in %.2fs", elapsed)
        return MethodToSvgResponse(
            success=result.success,
            svg_content=sanitize_poster_markup(result.final_svg),
            figure_png_b64=result.figure_png_b64,
            error=result.error,
        )
    except HTTPException:
        raise
    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.error(
            "[AutoFigure] figure-to-svg failed after %.2fs: %s",
            elapsed,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail=f"AutoFigure service error: {exc}",
        ) from exc


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Check whether the AutoFigure microservice is reachable.

    No authentication required.
    """
    if not _autofigure_available:
        return {"available": False, "service_url": ""}

    try:
        client = get_autofigure_client()
        available = await client.health_check()
        return {"available": available, "service_url": client.base_url}
    except Exception as exc:
        logger.warning("[AutoFigure] health check failed: %s", exc)
        return {"available": False, "service_url": ""}


@router.post("/generate-poster-figures", response_model=PosterFiguresResponse)
@limiter.limit("3/minute")
async def generate_poster_figures(
    request: Request,
    body: PosterFiguresRequest,
    username: str = Depends(get_current_user),
) -> PosterFiguresResponse:
    """Generate multiple SVG figures for a conference poster.

    Called by the poster generation pipeline. Produces one SVG for the
    overall methodology and up to ``max_figures - 1`` SVGs for
    individual paper analyses, all generated concurrently.
    """
    del request
    _require_autofigure()
    _require_poster_session_owner(body.session_id, username)
    start = time.monotonic()
    logger.info(
        "[AutoFigure] generate-poster-figures requested by=%s session=%s "
        "papers=%d max_figures=%d",
        username or "anonymous",
        body.session_id,
        len(body.paper_analyses),
        body.max_figures,
    )

    try:
        try:
            await asyncio.wait_for(_poster_batch_semaphore.acquire(), timeout=0.1)
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=429,
                detail={
                    "error_code": CODE_ACTIVE_JOB,
                    "message": "AutoFigure poster batch concurrency budget exhausted",
                    "retryable": True,
                },
            ) from exc

        try:
            client = get_autofigure_client()

            # ContentProxy: build_method_prompt expects a content-like object
            class _ContentProxy:
                def __init__(self, methodology: str):
                    self.methodology = methodology
                    self.contributions: List[str] = []

            content_proxy = _ContentProxy(body.methodology)
            method_prompt = build_method_prompt(content_proxy, body.paper_analyses)
            paper_prompts = build_paper_figure_prompts(body.paper_analyses)

            # Limit paper prompts so total figures do not exceed max_figures
            # (1 slot is reserved for the overall methodology figure)
            paper_prompts = paper_prompts[: max(body.max_figures - 1, 0)]

            tasks: List[asyncio.Task[Any]] = [
                asyncio.create_task(client.method_to_svg(method_prompt))
            ]
            for prompt_info in paper_prompts:
                tasks.append(
                    asyncio.create_task(
                        client.method_to_svg(prompt_info["method_prompt"])
                    )
                )

            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=AUTOFIGURE_POSTER_BATCH_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail={
                    "error_code": CODE_TIMEOUT_UNCLASSIFIED,
                    "message": "AutoFigure poster batch timed out",
                    "retryable": False,
                },
            ) from exc
        finally:
            _poster_batch_semaphore.release()

        figures: List[Dict[str, Any]] = []
        errors: List[str] = []

        # Process methodology result (index 0)
        method_result = results[0]
        if isinstance(method_result, Exception):
            errors.append(f"Methodology figure failed: {method_result}")
            logger.warning("[AutoFigure] methodology figure failed: %s", method_result)
        elif not method_result.success:
            errors.append(f"Methodology figure failed: {method_result.error}")
        else:
            figures.append({
                "paper_title": "Overall Methodology",
                "svg_content": sanitize_poster_markup(method_result.final_svg),
                "figure_png_b64": method_result.figure_png_b64,
            })

        # Process per-paper results (index 1+)
        for idx, res in enumerate(results[1:]):
            paper_title = (
                paper_prompts[idx]["paper_title"]
                if idx < len(paper_prompts)
                else f"Paper {idx + 1}"
            )
            if isinstance(res, Exception):
                errors.append(f"Figure for '{paper_title}' failed: {res}")
                logger.warning(
                    "[AutoFigure] figure for '%s' failed: %s", paper_title, res
                )
            elif not res.success:
                errors.append(f"Figure for '{paper_title}' failed: {res.error}")
            else:
                figures.append({
                    "paper_title": paper_title,
                    "svg_content": sanitize_poster_markup(res.final_svg),
                    "figure_png_b64": res.figure_png_b64,
                })

        elapsed = time.monotonic() - start
        logger.info(
            "[AutoFigure] generate-poster-figures completed in %.2fs — "
            "%d figures generated, %d errors",
            elapsed,
            len(figures),
            len(errors),
        )

        return PosterFiguresResponse(
            success=len(figures) > 0,
            figures=figures,
            total_generated=len(figures),
            errors=errors,
        )
    except HTTPException:
        raise
    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.error(
            "[AutoFigure] generate-poster-figures failed after %.2fs: %s",
            elapsed,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail=f"AutoFigure service error: {exc}",
        ) from exc
