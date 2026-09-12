"""Poster resource limits and non-bypassable security policy constants."""

from __future__ import annotations

import time
from typing import Optional


def remaining_budget(deadline: Optional[float], cap: float) -> float:
    """외부 호출이 기다려도 되는 시간. 남은 예산과 자체 상한 중 작은 쪽.

    deadline은 time.monotonic() 기준 마감 시각이다. 진입 시점에만 마감을
    확인하고 상한은 고정으로 두면, 마지막 단계 하나가 예산을 통째로 넘긴다.
    """
    return cap if deadline is None else max(0.0, min(cap, deadline - time.monotonic()))


POSTER_SECURITY_PHASE = "phase_1_strict"
FEATURE_RESULT_V2 = True
FEATURE_SAFE_PREVIEW = True
FEATURE_SPEC_RENDERER = False
FEATURE_FINAL_QUALITY_GATE = False
FEATURE_PDF_EXPORT = False
POSTER_TIMEOUT_SECONDS = 240
POSTER_CONCURRENCY = 2
DIRECT_REPORT_MAX_CHARS = 200_000
DIRECT_NUM_PAPERS_MAX = 50
AUTOFIGURE_TEXT_MAX_CHARS = 20_000
AUTOFIGURE_IMAGE_B64_MAX_CHARS = 8_000_000
AUTOFIGURE_PAPER_ANALYSES_MAX = 10
AUTOFIGURE_MAX_FIGURES = 10
AUTOFIGURE_POSTER_BATCH_TIMEOUT_SECONDS = 120
AUTOFIGURE_POSTER_BATCH_CONCURRENCY = 2
# PDF 내보내기는 클라이언트가 보유한 포스터 HTML을 되돌려 보낸다. 상한은
# DIRECT_REPORT_MAX_CHARS(마크다운)이 아니라 base64 도판이 인라인된
# 렌더 결과물 크기를 기준으로 잡는다.
POSTER_PDF_HTML_MAX_CHARS = 12_000_000
POSTER_PDF_TIMEOUT_SECONDS = 60
POSTER_PDF_CONCURRENCY = 1

MANDATORY_SANITIZER_ENABLED = True
PUBLIC_PROVENANCE_KEYS = {
    "route",
    "generator",
    "model",
    "theme",
    "fallback",
    "source_hash",
    "paper_count",
    "figure_count",
}
PUBLIC_QUALITY_KEYS = {
    "validation_score",
    "scored_sha256",
    "evaluator",
}

HTML_ALLOWED_TAGS = {
    "html", "head", "body", "meta", "title", "style",
    "main", "section", "article", "aside", "header", "footer",
    "div", "span", "p", "pre", "code", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "em", "b", "i", "u", "small", "br", "hr",
    "ul", "ol", "li",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
    "figure", "figcaption", "img",
}

SVG_ALLOWED_TAGS = {
    "svg", "g", "defs", "desc", "title",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "text", "tspan",
    "lineargradient", "radialgradient", "stop",
    "clippath", "mask", "pattern", "marker",
}

DROP_WITH_CONTENT_TAGS = {
    "script", "iframe", "object", "embed", "applet", "base",
    "form", "input", "button", "textarea", "select", "option",
    "foreignobject", "animate", "animatemotion", "animatetransform", "set",
    "audio", "video", "canvas",
}

VOID_TAGS = {"br", "hr", "img", "meta"}
