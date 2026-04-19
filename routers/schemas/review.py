"""Pydantic schemas used with OpenAI ``response_format={"type": "json_schema"}``.

US-010 introduces strict-mode schema enforcement on three LLM call sites:

1. ``routers.paper_review_service.generate_paper_review`` — per-paper review
2. ``routers.paper_reviews.explain_math_formula`` — ``POST /api/math-explain``
3. ``app.DeepAgent.tools.fact_verification.ClaimExtractor`` — claim extraction

OpenAI's strict JSON-schema mode rejects Pydantic's default
``model_json_schema()`` output because it:

* marks optional fields as non-required;
* uses ``$ref`` + ``$defs`` to point at nested models;
* omits ``additionalProperties: false`` at every object; and
* sometimes emits ``anyOf`` / ``allOf`` to represent unions (``Optional[...]``
  in particular).

``build_openai_strict_schema`` takes a plain Pydantic model, asks for its JSON
schema, inlines every ``$ref``, forces ``additionalProperties: false`` +
``required`` to the full property list on every object, and drops metadata
that OpenAI does not accept (e.g. ``title``). The returned dict can be passed
directly to the API as the inner ``schema`` field of
``response_format={"type": "json_schema", "json_schema": {...}}``.

Note on ``Field`` constraints: OpenAI strict mode accepts ``enum``, ``type``,
``items``, ``properties``, ``required``, ``additionalProperties``. It does NOT
accept ``minimum``/``maximum``/``minLength``/``pattern`` — those are silently
ignored when ``strict=True``. We therefore keep the Pydantic-level
constraints for local validation but strip them from the outbound schema.
"""

from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Paper review schema ────────────────────────────────────────────────


class MethodologyAssessment(BaseModel):
    """Sub-schema for the ``methodology_assessment`` field of a paper review."""

    rigor: int = Field(ge=1, le=5, description="Experimental rigor score (1-5).")
    novelty: int = Field(ge=1, le=5, description="Novelty score (1-5).")
    reproducibility: int = Field(
        ge=1, le=5, description="Reproducibility score (1-5)."
    )
    commentary: str = Field(description="2-3 sentence methodology commentary.")


class ReviewStrength(BaseModel):
    """Sub-schema for a single strength entry in a paper review.

    Mirrors the FE contract in ``web-ui/src/api/paper-review.ts`` —
    the ``PaperReviewPanel`` component reads ``point``, ``evidence``,
    and ``significance`` directly from each item.
    """

    point: str = Field(description="Concrete strength point grounded in the paper.")
    evidence: str = Field(description="Supporting detail (section / table / quote).")
    significance: Literal["high", "medium", "low"] = Field(
        description="Impact tier — high|medium|low."
    )


class ReviewWeakness(BaseModel):
    """Sub-schema for a single weakness entry in a paper review.

    Mirrors the FE contract in ``web-ui/src/api/paper-review.ts`` —
    the ``PaperReviewPanel`` component reads ``point``, ``evidence``,
    and ``severity`` directly from each item.
    """

    point: str = Field(description="Concrete weakness point grounded in the paper.")
    evidence: str = Field(description="Supporting detail (section / table / quote).")
    severity: Literal["major", "minor"] = Field(
        description="Severity tier — major|minor."
    )


class PaperReviewSchema(BaseModel):
    """Top-level schema for a single-paper review."""

    summary: str = Field(description="2-3 sentence overview of the contribution.")
    strengths: list[ReviewStrength] = Field(
        description="Concrete strengths grounded in paper evidence."
    )
    weaknesses: list[ReviewWeakness] = Field(
        description="Concrete weaknesses grounded in paper evidence."
    )
    methodology_assessment: MethodologyAssessment
    key_contributions: list[str]
    questions_for_authors: list[str]
    overall_score: float = Field(
        ge=1.0, le=10.0, description="Overall score on a 1-10 scale."
    )
    confidence: float = Field(
        ge=1.0, le=5.0, description="Reviewer confidence on a 1-5 scale."
    )
    detailed_review_markdown: str = Field(
        description="Full markdown review body (≥800 chars)."
    )


# ── Math explanation schema ────────────────────────────────────────────


class VariableDefinition(BaseModel):
    """Single symbol/meaning pair in the math explanation."""

    symbol: str
    meaning: str


class MathExplainSchema(BaseModel):
    """Top-level schema for ``POST /api/math-explain``."""

    explanation: str = Field(
        description="1-3 sentence plain-language explanation of the formula."
    )
    variables: list[VariableDefinition] = Field(
        description="List of (symbol, meaning) pairs for variables in the formula."
    )
    formula_type: Literal[
        "loss function",
        "probability",
        "optimization",
        "definition",
        "theorem",
        "other",
    ] = Field(description="Formula category.")


# ── Claim extraction schema ────────────────────────────────────────────


class ClaimItem(BaseModel):
    """Single verifiable claim extracted from a review section."""

    text: str = Field(description="Exact claim text preserved from the source.")
    type: Literal[
        "statistical",
        "methodological",
        "comparative",
        "factual",
        "interpretive",
    ] = Field(description="Claim type — ``interpretive`` claims are filtered out.")


class ClaimExtractionSchema(BaseModel):
    """Top-level schema for claim extraction LLM output."""

    claims: list[ClaimItem]


# ── Strict-mode helper ─────────────────────────────────────────────────


# Keys that are safe to keep at any node under OpenAI strict mode. Everything
# else (title, minimum, maximum, minLength, pattern, default, examples, ...)
# is stripped during normalisation.
_ALLOWED_SCHEMA_KEYS: frozenset[str] = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "description",
        "const",
    }
)


def _resolve_refs(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Inline every ``$ref`` in ``schema`` using the top-level ``$defs`` map.

    The returned schema contains no ``$ref`` / ``$defs`` / ``definitions``
    entries — required because OpenAI strict mode does not accept ``$ref``.
    """

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                # Supported refs: ``#/$defs/Name`` or ``#/definitions/Name``.
                key = ref.rsplit("/", 1)[-1]
                target = defs.get(key)
                if target is None:
                    # Fall through to stripping if the ref is unknown.
                    stripped = {k: v for k, v in node.items() if k != "$ref"}
                    return {k: walk(v) for k, v in stripped.items()}
                resolved = copy.deepcopy(target)
                # Merge any sibling fields (rare but Pydantic can emit them).
                for k, v in node.items():
                    if k == "$ref":
                        continue
                    resolved[k] = v
                return walk(resolved)
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def _strip_and_tighten(node: Any) -> Any:
    """Recursively prune disallowed keys and force strict-mode object shape.

    ``node`` is always a schema node (object/array/scalar schema). The
    ``properties`` container — a mapping ``name -> sub-schema`` — is handled
    specially so property names are preserved regardless of the allow-list.
    """
    if isinstance(node, dict):
        cleaned: dict[str, Any] = {}
        for key, value in node.items():
            if key not in _ALLOWED_SCHEMA_KEYS:
                continue
            if key == "properties" and isinstance(value, dict):
                # Property names are user-defined keys, not schema keywords —
                # recurse into each sub-schema but keep every name.
                cleaned["properties"] = {
                    pname: _strip_and_tighten(psub) for pname, psub in value.items()
                }
            else:
                cleaned[key] = _strip_and_tighten(value)
        if cleaned.get("type") == "object":
            # OpenAI strict mode requires every declared property to appear
            # in ``required`` and forbids extras.
            cleaned.setdefault("properties", {})
            cleaned["required"] = list(cleaned["properties"].keys())
            cleaned["additionalProperties"] = False
        return cleaned
    if isinstance(node, list):
        return [_strip_and_tighten(v) for v in node]
    return node


def build_openai_strict_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Build an OpenAI strict-mode-compatible JSON schema from a Pydantic model.

    The returned dict is suitable as the ``schema`` field in
    ``response_format={"type": "json_schema", "json_schema": {"schema": ..., ...}}``.
    """
    raw = model_cls.model_json_schema()
    defs = raw.pop("$defs", None) or raw.pop("definitions", None) or {}
    inlined = _resolve_refs(raw, defs)
    return _strip_and_tighten(inlined)
