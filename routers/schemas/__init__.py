"""Pydantic schemas for OpenAI ``response_format={"type": "json_schema"}`` calls.

The schemas here are the canonical shape for structured LLM outputs. Each
module also exposes the flattened, OpenAI-strict-mode-compatible JSON schema
dict (``_OPENAI_SCHEMA``) built at import time so the LLM call site can pass
it directly in ``response_format``.
"""

from .review import (
    ClaimExtractionSchema,
    ClaimItem,
    MathExplainSchema,
    MethodologyAssessment,
    PaperReviewSchema,
    ReviewStrength,
    ReviewWeakness,
    VariableDefinition,
    build_openai_strict_schema,
)

__all__ = [
    "ClaimExtractionSchema",
    "ClaimItem",
    "MathExplainSchema",
    "MethodologyAssessment",
    "PaperReviewSchema",
    "ReviewStrength",
    "ReviewWeakness",
    "VariableDefinition",
    "build_openai_strict_schema",
]
