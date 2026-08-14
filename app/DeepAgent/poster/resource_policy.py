"""Poster resource limits and non-bypassable security policy constants."""

from __future__ import annotations

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
