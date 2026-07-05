"""Runtime SkillOpt policy gate for DeepReview analysis prompts.

This module is production-runtime safe and intentionally does not import the
dev-only DeepReview approval/evaluation package.
"""
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

SKILLOPT_DEEP_REVIEW_POLICY_SCOPE = "deep_review_analysis_prompt"
SKILLOPT_DEEP_REVIEW_POLICY_ENABLED_ENV = "SKILLOPT_DEEP_REVIEW_POLICY_ENABLED"
SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV = "SKILLOPT_DEEP_REVIEW_POLICY_PATH"
SKILLOPT_DEEP_REVIEW_POLICY_HASH_ENV = "SKILLOPT_DEEP_REVIEW_POLICY_HASH"
SKILLOPT_DEEP_REVIEW_POLICY_SCOPE_ENV = "SKILLOPT_DEEP_REVIEW_POLICY_SCOPE"

_TRUE_VALUES = {"1", "true", "yes", "on"}
_MAX_POLICY_BYTES = 20_480
_REQUIRED_PHRASES = (
    "DeepReview analysis prompt path",
    "Do not change paper loading",
    "Do not bypass fact verification",
    "Do not enable production rollout",
    "Preserve evidence-based critique",
)


class SkillOptDeepReviewPolicyError(RuntimeError):
    """Raised when an explicitly enabled DeepReview SkillOpt policy is unsafe."""


@dataclass(frozen=True)
class SkillOptDeepReviewPolicy:
    """Validated DeepReview policy loaded from explicit rollout gates."""

    enabled: bool
    content: str = ""
    source_path: str = ""
    content_hash: str = ""
    scope: str = SKILLOPT_DEEP_REVIEW_POLICY_SCOPE
    reason: str = "disabled"


def is_skillopt_deep_review_policy_enabled(env: Mapping[str, str] | None = None) -> bool:
    environ = os.environ if env is None else env
    return environ.get(SKILLOPT_DEEP_REVIEW_POLICY_ENABLED_ENV, "").strip().lower() in _TRUE_VALUES


def load_skillopt_deep_review_policy_from_env(
    env: Mapping[str, str] | None = None,
) -> SkillOptDeepReviewPolicy:
    """Load and validate the DeepReview policy from env gates.

    Disabled is inert. Enabled requires an absolute UTF-8 policy path pinned by
    sha256 and the exact DeepReview scope, so prompt changes remain explicit and
    reproducible.
    """
    environ = os.environ if env is None else env
    if not is_skillopt_deep_review_policy_enabled(environ):
        return SkillOptDeepReviewPolicy(enabled=False)

    scope = environ.get(
        SKILLOPT_DEEP_REVIEW_POLICY_SCOPE_ENV,
        SKILLOPT_DEEP_REVIEW_POLICY_SCOPE,
    ).strip()
    if scope != SKILLOPT_DEEP_REVIEW_POLICY_SCOPE:
        raise SkillOptDeepReviewPolicyError(
            f"{SKILLOPT_DEEP_REVIEW_POLICY_SCOPE_ENV} must be "
            f"{SKILLOPT_DEEP_REVIEW_POLICY_SCOPE!r}"
        )

    raw_path = environ.get(SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV, "").strip()
    if not raw_path:
        raise SkillOptDeepReviewPolicyError(
            f"{SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV} is required when enabled"
        )
    expected_hash = _normalize_hash(environ.get(SKILLOPT_DEEP_REVIEW_POLICY_HASH_ENV, ""))
    path = Path(raw_path)
    if not path.is_absolute():
        raise SkillOptDeepReviewPolicyError(
            f"{SKILLOPT_DEEP_REVIEW_POLICY_PATH_ENV} must be an absolute path"
        )
    try:
        file_stat = path.stat()
    except OSError as exc:
        raise SkillOptDeepReviewPolicyError(f"Failed to stat DeepReview policy file: {path}") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise SkillOptDeepReviewPolicyError(f"DeepReview policy path must be a regular file: {path}")
    if file_stat.st_size > _MAX_POLICY_BYTES:
        raise SkillOptDeepReviewPolicyError(
            f"DeepReview policy file exceeds {_MAX_POLICY_BYTES} bytes"
        )
    try:
        raw_content = path.read_bytes()
    except OSError as exc:
        raise SkillOptDeepReviewPolicyError(f"Failed to read DeepReview policy file: {path}") from exc
    actual_hash = hashlib.sha256(raw_content).hexdigest()
    if actual_hash != expected_hash:
        raise SkillOptDeepReviewPolicyError(
            "DeepReview policy hash mismatch: "
            f"expected sha256:{expected_hash}, got sha256:{actual_hash}"
        )
    try:
        content = raw_content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillOptDeepReviewPolicyError("DeepReview policy file must be UTF-8 text") from exc
    _validate_policy_content(content, len(raw_content))
    return SkillOptDeepReviewPolicy(
        enabled=True,
        content=content.strip(),
        source_path=str(path),
        content_hash=f"sha256:{actual_hash}",
        scope=scope,
        reason="enabled",
    )


def build_skillopt_deep_review_policy_prompt_block(policy: SkillOptDeepReviewPolicy) -> str:
    """Render a DeepReview prompt block for a validated policy, or empty text."""
    if not policy.enabled:
        return ""
    return f"""

SkillOpt optimized policy for {policy.scope}:
- Apply this policy only to DeepReview analysis prompt guidance.
- Do not change paper loading, workspace persistence, session ownership, fact verification, advisor validation, report serving, or failure semantics from this policy.
- Policy provenance: {policy.content_hash}

{policy.content}
""".rstrip()


def _normalize_hash(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("sha256:"):
        value = value[len("sha256:"):]
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise SkillOptDeepReviewPolicyError(
            f"{SKILLOPT_DEEP_REVIEW_POLICY_HASH_ENV} must be a sha256 hex digest or sha256:<digest>"
        )
    return value


def _validate_policy_content(content: str, size_bytes: int) -> None:
    if not content.strip():
        raise SkillOptDeepReviewPolicyError("DeepReview policy file is empty")
    if size_bytes > _MAX_POLICY_BYTES:
        raise SkillOptDeepReviewPolicyError(
            f"DeepReview policy file exceeds {_MAX_POLICY_BYTES} bytes"
        )
    missing = [phrase for phrase in _REQUIRED_PHRASES if phrase not in content]
    if missing:
        raise SkillOptDeepReviewPolicyError(
            "DeepReview policy is missing required v1 safety phrases: " + ", ".join(missing)
        )
