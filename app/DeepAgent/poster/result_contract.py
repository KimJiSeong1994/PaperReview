"""Poster API result and error contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional
from uuid import uuid4

from .resource_policy import PUBLIC_PROVENANCE_KEYS

PosterStatus = Literal["succeeded", "degraded", "failed"]

CODE_TIMEOUT_UNCLASSIFIED = "poster_timeout_unclassified"
CODE_ACTIVE_JOB = "poster_active_job"
CODE_RATE_LIMITED = "poster_rate_limited"
CODE_SESSION_UNAVAILABLE = "poster_session_unavailable"
CODE_INPUT_TOO_LARGE = "poster_input_too_large"
CODE_INPUT_INVALID = "poster_input_invalid"
CODE_GENERATION_FAILED = "poster_generation_failed"
CODE_EMPTY_HTML = "poster_empty_html"
CODE_FALLBACK_USED = "poster_fallback_used"
CODE_PDF_UNAVAILABLE = "poster_pdf_unavailable"
CODE_PDF_RENDER_FAILED = "poster_pdf_render_failed"
CODE_PDF_GEOMETRY_INVALID = "poster_pdf_geometry_invalid"


@dataclass
class PosterServiceError(Exception):
    status_code: int
    error_code: str
    message: str
    retryable: bool = False


def new_generation_id() -> str:
    return f"poster_{uuid4().hex[:12]}"


def success_for_status(status: str) -> bool:
    return status == "succeeded"


def normalize_status(raw: Dict[str, Any], sanitized_html: str) -> PosterStatus:
    status = raw.get("poster_status") or raw.get("status")
    if status in {"succeeded", "degraded", "failed"}:
        resolved = status
    elif raw.get("success") is True and not raw.get("error"):
        resolved = "succeeded"
    elif sanitized_html.strip():
        resolved = "degraded"
    else:
        resolved = "failed"
    if not sanitized_html.strip():
        return "failed"
    return resolved  # type: ignore[return-value]


def public_error_detail(error: PosterServiceError) -> Dict[str, Any]:
    return {
        "poster_status": "failed",
        "status": "failed",
        "success": False,
        "error_code": error.error_code,
        "retryable": error.retryable,
        "message": error.message,
        "generation_id": new_generation_id(),
    }


def sanitize_public_provenance(*items: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    safe: Dict[str, Any] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if key not in PUBLIC_PROVENANCE_KEYS:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe[key] = value
    return safe


def result_envelope(
    *,
    raw: Dict[str, Any],
    poster_html: str,
    status: PosterStatus,
    generation_id: str,
    session_id: str,
    warnings: list[str],
    timings: Dict[str, float],
    provenance: Dict[str, Any],
    artifacts: Optional[Dict[str, Any]] = None,
    quality: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    error_code = raw.get("error_code") or ""
    if status == "failed" and not error_code:
        error_code = CODE_EMPTY_HTML
    # `or` 체인은 빈 dict를 falsy로 보고 필터되지 않은 raw["quality"]로 되돌아간다.
    # allowlist가 모든 키를 걸러낸 경우가 정확히 그 경우이므로 None만 본다.
    resolved_quality = (
        quality
        if quality is not None
        else (raw.get("quality") or {"validation_score": raw.get("validation_score")})
    )
    return {
        **raw,
        "poster_status": status,
        "status": status,
        "success": success_for_status(status),
        "session_id": session_id,
        "poster_html": poster_html,
        "poster_path": "",
        "error": raw.get("error", ""),
        "warnings": warnings,
        "error_code": error_code,
        "retryable": bool(raw.get("retryable", False)),
        "generation_id": generation_id,
        "timings": {**(raw.get("timings") or {}), **timings},
        "provenance": sanitize_public_provenance(
            provenance,
            raw.get("provenance") if isinstance(raw.get("provenance"), dict) else None,
        ),
        # 최상위 점수는 quality를 그대로 따른다. raw를 그대로 흘리면 폐기된
        # 점수가 최상위에만 살아남아 HTTP 응답 본문으로 새어 나간다.
        "validation_score": resolved_quality.get("validation_score"),
        "quality": resolved_quality,
        "artifacts": artifacts or {
            "html_bytes": len(poster_html.encode("utf-8")),
        },
    }
