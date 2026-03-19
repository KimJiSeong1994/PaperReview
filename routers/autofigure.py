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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .deps import get_optional_user

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


# ── Pydantic models ──────────────────────────────────────────────────

class MethodToSvgRequest(BaseModel):
    """Request body for converting methodology text to SVG."""

    method_text: str = Field(..., min_length=1, description="Methodology text to visualise")
    paper_title: str = Field(default="", description="Optional paper title for context")
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

    image_base64: str = Field(..., min_length=1, description="Base64-encoded image data")
    mime_type: str = Field(default="image/png", description="MIME type of the image")


class PosterFiguresRequest(BaseModel):
    """Request body for batch poster figure generation."""

    session_id: str = Field(..., min_length=1, description="Deep review session ID")
    methodology: str = Field(..., min_length=1, description="Extracted methodology text")
    paper_analyses: List[Dict[str, Any]] = Field(
        default_factory=list, description="Per-paper analysis data"
    )
    max_figures: int = Field(default=3, ge=1, le=10, description="Maximum figures to generate")


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

    try:
        client = get_autofigure_client()
        result = await client.method_to_svg(
            body.method_text,
            style_hints=body.style_hints,
            optimize_iterations=body.optimize_iterations,
        )
        elapsed = time.monotonic() - start
        logger.info("[AutoFigure] method-to-svg completed in %.2fs", elapsed)
        return MethodToSvgResponse(
            success=result.success,
            svg_content=result.final_svg,
            figure_png_b64=result.figure_png_b64,
            error=result.error,
        )
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
            svg_content=result.final_svg,
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
async def generate_poster_figures(
    body: PosterFiguresRequest,
    username: str | None = Depends(get_optional_user),
) -> PosterFiguresResponse:
    """Generate multiple SVG figures for a conference poster.

    Called by the poster generation pipeline. Produces one SVG for the
    overall methodology and up to ``max_figures - 1`` SVGs for
    individual paper analyses, all generated concurrently.
    """
    _require_autofigure()
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

        # Prepare coroutines
        tasks: List[asyncio.Task[Any]] = []

        # Overall methodology SVG
        tasks.append(
            asyncio.ensure_future(
                client.method_to_svg(method_prompt)
            )
        )

        # Per-paper SVGs
        for prompt_info in paper_prompts:
            tasks.append(
                asyncio.ensure_future(
                    client.method_to_svg(prompt_info["method_prompt"])
                )
            )

        # Run concurrently, tolerating individual failures
        results = await asyncio.gather(*tasks, return_exceptions=True)

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
                "svg_content": method_result.final_svg,
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
                    "svg_content": res.final_svg,
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
