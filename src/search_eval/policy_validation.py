"""Shared validation for SkillOpt policies crossing into runtime artifacts."""

from __future__ import annotations

from .skillopt_contract import ValidationError

RUNTIME_POLICY_MAX_BYTES = 16_384
RUNTIME_POLICY_REQUIRED_PHRASES = (
    "QueryAnalyzer standard search path",
    "Do not enable `use_llm_search`",
    "Do not enable HyDE",
    "Do not promote RelevanceFilter",
)


def validate_runtime_policy_text(text: str) -> None:
    """Validate that a ``best_skill.md`` can pass the runtime policy gate."""
    missing = [
        phrase for phrase in RUNTIME_POLICY_REQUIRED_PHRASES if phrase not in text
    ]
    if missing:
        raise ValidationError(
            f"approved SkillOpt policy missing runtime safety phrases: {missing}"
        )
    if len(text.encode("utf-8")) > RUNTIME_POLICY_MAX_BYTES:
        raise ValidationError(
            "approved SkillOpt policy exceeds runtime policy size limit"
        )
