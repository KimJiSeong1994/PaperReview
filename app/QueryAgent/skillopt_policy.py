"""Runtime SkillOpt policy gate for QueryAnalyzer paper search.

This module is intentionally independent from the dev-only evaluation scaffolding
so production packaging never depends on offline benchmark helpers.
"""
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

SKILLOPT_POLICY_SCOPE = "query_analyzer_standard_search"
SKILLOPT_POLICY_ENABLED_ENV = "SKILLOPT_SEARCH_POLICY_ENABLED"
SKILLOPT_POLICY_PATH_ENV = "SKILLOPT_SEARCH_POLICY_PATH"
SKILLOPT_POLICY_HASH_ENV = "SKILLOPT_SEARCH_POLICY_HASH"
SKILLOPT_POLICY_SCOPE_ENV = "SKILLOPT_SEARCH_POLICY_SCOPE"

_TRUE_VALUES = {"1", "true", "yes", "on"}
_MAX_POLICY_BYTES = 16_384
_REQUIRED_PHRASES = (
    "QueryAnalyzer standard search path",
    "Do not enable `use_llm_search`",
    "Do not enable HyDE",
    "Do not promote RelevanceFilter",
)


class SkillOptPolicyError(RuntimeError):
    """Raised when an explicitly enabled SkillOpt policy is unsafe to apply."""


@dataclass(frozen=True)
class SkillOptPolicy:
    """Validated SkillOpt policy loaded from an explicit rollout gate."""

    enabled: bool
    content: str = ""
    source_path: str = ""
    content_hash: str = ""
    scope: str = SKILLOPT_POLICY_SCOPE
    reason: str = "disabled"


def is_skillopt_policy_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return true only for explicit opt-in environment values."""
    environ = os.environ if env is None else env
    return environ.get(SKILLOPT_POLICY_ENABLED_ENV, "").strip().lower() in _TRUE_VALUES


def _normalize_hash(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("sha256:"):
        value = value[len("sha256:"):]
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise SkillOptPolicyError(
            f"{SKILLOPT_POLICY_HASH_ENV} must be a sha256 hex digest or sha256:<digest>"
        )
    return value


def _validate_policy_content(content: str, size_bytes: int) -> None:
    if not content.strip():
        raise SkillOptPolicyError("SkillOpt policy file is empty")
    if size_bytes > _MAX_POLICY_BYTES:
        raise SkillOptPolicyError(
            f"SkillOpt policy file exceeds {_MAX_POLICY_BYTES} bytes"
        )
    missing = [phrase for phrase in _REQUIRED_PHRASES if phrase not in content]
    if missing:
        raise SkillOptPolicyError(
            "SkillOpt policy is missing required v1 safety phrases: "
            + ", ".join(missing)
        )


def load_skillopt_policy_from_env(
    env: Mapping[str, str] | None = None,
) -> SkillOptPolicy:
    """Load and validate the runtime SkillOpt policy from environment gates.

    Default/off path is intentionally inert. Once enabled, the policy must be
    supplied by path and pinned by a sha256 hash so prompt changes are explicit
    and reproducible.
    """
    environ = os.environ if env is None else env
    if not is_skillopt_policy_enabled(environ):
        return SkillOptPolicy(enabled=False)

    scope = environ.get(SKILLOPT_POLICY_SCOPE_ENV, SKILLOPT_POLICY_SCOPE).strip()
    if scope != SKILLOPT_POLICY_SCOPE:
        raise SkillOptPolicyError(
            f"{SKILLOPT_POLICY_SCOPE_ENV} must be {SKILLOPT_POLICY_SCOPE!r}"
        )

    raw_path = environ.get(SKILLOPT_POLICY_PATH_ENV, "").strip()
    if not raw_path:
        raise SkillOptPolicyError(f"{SKILLOPT_POLICY_PATH_ENV} is required when enabled")

    expected_hash = _normalize_hash(environ.get(SKILLOPT_POLICY_HASH_ENV, ""))
    path = Path(raw_path)
    if not path.is_absolute():
        raise SkillOptPolicyError(
            f"{SKILLOPT_POLICY_PATH_ENV} must be an absolute path"
        )
    raw_content = _read_regular_policy_file(path)

    actual_hash = hashlib.sha256(raw_content).hexdigest()
    if actual_hash != expected_hash:
        raise SkillOptPolicyError(
            "SkillOpt policy hash mismatch: "
            f"expected sha256:{expected_hash}, got sha256:{actual_hash}"
        )

    try:
        content = raw_content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillOptPolicyError("SkillOpt policy file must be UTF-8 text") from exc

    _validate_policy_content(content, len(raw_content))
    return SkillOptPolicy(
        enabled=True,
        content=content.strip(),
        source_path=str(path),
        content_hash=f"sha256:{actual_hash}",
        scope=scope,
        reason="enabled",
    )


def _read_regular_policy_file(path: Path) -> bytes:
    """Read one non-symlink regular file through a single descriptor."""
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    link_stat = None
    if not no_follow:
        try:
            link_stat = path.lstat()
        except OSError as exc:
            raise SkillOptPolicyError(f"Failed to inspect SkillOpt policy file: {path}") from exc
        if stat.S_ISLNK(link_stat.st_mode):
            raise SkillOptPolicyError(f"SkillOpt policy path must not be a symlink: {path}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | no_follow
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SkillOptPolicyError(f"Failed to open SkillOpt policy file: {path}") from exc
    try:
        file_stat = os.fstat(descriptor)
        if link_stat is not None:
            current_path_stat = path.lstat()
            if stat.S_ISLNK(current_path_stat.st_mode):
                raise SkillOptPolicyError(f"SkillOpt policy path became a symlink while opening: {path}")
            if (
                (file_stat.st_dev, file_stat.st_ino) != (link_stat.st_dev, link_stat.st_ino)
                or (current_path_stat.st_dev, current_path_stat.st_ino) != (file_stat.st_dev, file_stat.st_ino)
            ):
                raise SkillOptPolicyError(f"SkillOpt policy file changed while opening: {path}")
        if not stat.S_ISREG(file_stat.st_mode):
            raise SkillOptPolicyError(f"SkillOpt policy path must be a regular file: {path}")
        if file_stat.st_size > _MAX_POLICY_BYTES:
            raise SkillOptPolicyError(f"SkillOpt policy file exceeds {_MAX_POLICY_BYTES} bytes")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            raw_content = handle.read(_MAX_POLICY_BYTES + 1)
    except OSError as exc:
        raise SkillOptPolicyError(f"Failed to read SkillOpt policy file: {path}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(raw_content) > _MAX_POLICY_BYTES:
        raise SkillOptPolicyError(f"SkillOpt policy file exceeds {_MAX_POLICY_BYTES} bytes")
    return raw_content


def build_skillopt_policy_prompt_block(policy: SkillOptPolicy) -> str:
    """Render a prompt block for a validated policy, or empty text when off."""
    if not policy.enabled:
        return ""
    return f"""

SkillOpt optimized policy for {policy.scope}:
- Apply this policy only to QueryAnalyzer standard paper-search analysis and source-query generation.
- Do not enable use_llm_search, HyDE, RelevanceFilter prompt promotion, or any retrieval-stage behavior from this policy.
- Policy provenance: {policy.content_hash}

{policy.content}
""".rstrip()
