"""
File-based LLM response cache with prefix/suffix split keys.

Layout of a cached entry::

    cache_key = sha256(prefix_hash + "\x00" + suffix_hash)

    prefix_hash = sha256(system_prompt + "\x00" + fixed_prefix)
    suffix_hash = sha256(variable_body + "\x00" + model + "\x00" + temperature)

The split mirrors how OpenAI's automatic prompt cache sees the request:
``system + fixed_prefix`` is identical across calls (cached remotely), while
``variable_body`` changes per call. Storing the two hashes separately lets us
re-hit entries deterministically when the variable body repeats byte-for-byte.

Backward compatibility: if ``fixed_prefix`` is not supplied (legacy callers),
we fall back to the single-key scheme so pre-existing cache files keep working.
"""

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/cache/llm")
DEFAULT_TTL_HOURS = 168  # 7 days

# Observability counters — process-local, best-effort.
# Tracks full_hit (exact split-key or legacy-key match) and miss only.
_cache_stats: dict[str, int] = {
    "full_hit": 0,
    "miss": 0,
}


def _sha(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def _legacy_cache_key(
    system_prompt: str, user_prompt: str, model: str, temperature: float
) -> str:
    """Single-key scheme used before the split refactor. Kept for compat."""
    return _sha(system_prompt, user_prompt, model, str(temperature))


def _split_hashes(
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
    fixed_prefix: str,
) -> tuple[str, str, str]:
    """Compute ``(prefix_hash, suffix_hash, cache_key)`` for the split scheme.

    ``fixed_prefix`` is the cache-stable leading segment of ``user_prompt``.
    If ``user_prompt`` does not start with ``fixed_prefix`` we still hash
    safely: the suffix portion degrades to ``user_prompt`` itself, which is
    correct but misses the prefix-reuse benefit.
    """
    if fixed_prefix and user_prompt.startswith(fixed_prefix):
        variable_body = user_prompt[len(fixed_prefix):]
    else:
        if fixed_prefix:
            logger.warning(
                "LLM cache: user_prompt does not start with fixed_prefix — "
                "falling back to full-user hashing (prefix reuse lost). "
                "prefix=%r…", fixed_prefix[:40],
            )
        variable_body = user_prompt
    prefix_hash = _sha(system_prompt, fixed_prefix or "")
    suffix_hash = _sha(variable_body, model, str(temperature))
    cache_key = _sha(prefix_hash, suffix_hash)
    return prefix_hash, suffix_hash, cache_key


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def get_cached(
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
    fixed_prefix: str | None = None,
) -> Optional[str]:
    """Return cached LLM response if valid, else ``None``.

    When ``fixed_prefix`` is supplied, looks up the split-key entry first
    and falls back to the legacy single-key entry (written by callers that
    have not been migrated yet).
    """
    # Split-key lookup (preferred).
    if fixed_prefix is not None:
        _, _, key = _split_hashes(
            system_prompt, user_prompt, model, temperature, fixed_prefix
        )
        hit = _try_load(key)
        if hit is not None:
            _cache_stats["full_hit"] += 1
            logger.info("LLM cache hit (split): %s", key[:12])
            return hit

    # Legacy single-key fallback (also used when fixed_prefix is None).
    legacy_key = _legacy_cache_key(system_prompt, user_prompt, model, temperature)
    hit = _try_load(legacy_key)
    if hit is not None:
        _cache_stats["full_hit"] += 1
        logger.info("LLM cache hit (legacy): %s", legacy_key[:12])
        return hit

    _cache_stats["miss"] += 1
    return None


def _try_load(key: str) -> Optional[str]:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        expires_at = data.get("expires_at", 0)
        if time.time() > expires_at:
            path.unlink(missing_ok=True)
            return None
        return data["response"]
    except (json.JSONDecodeError, KeyError, OSError):
        path.unlink(missing_ok=True)
        return None


def set_cache(
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
    response: str,
    ttl_hours: int = DEFAULT_TTL_HOURS,
    fixed_prefix: str | None = None,
) -> None:
    """Store an LLM response in the cache.

    When ``fixed_prefix`` is provided, writes using the split-key scheme and
    records the prefix/suffix hashes alongside the response for debugging.
    Callers that pass ``fixed_prefix=None`` retain the original single-key
    behaviour for backward compatibility.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if fixed_prefix is not None:
        prefix_hash, suffix_hash, key = _split_hashes(
            system_prompt, user_prompt, model, temperature, fixed_prefix
        )
        extra = {"prefix_hash": prefix_hash, "suffix_hash": suffix_hash}
    else:
        key = _legacy_cache_key(system_prompt, user_prompt, model, temperature)
        extra = {}

    data = {
        "response": response,
        "model": model,
        "created_at": time.time(),
        "expires_at": time.time() + ttl_hours * 3600,
        **extra,
    }
    try:
        tmp = _cache_path(key).with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_cache_path(key))
    except OSError as e:
        logger.warning("Failed to write LLM cache: %s", e)


def get_cache_stats() -> dict[str, int]:
    """Return a snapshot of the process-local cache counters.

    Keys: ``full_hit`` (split-key or legacy exact match), ``miss``.
    Not persisted across restarts.
    """
    return dict(_cache_stats)
