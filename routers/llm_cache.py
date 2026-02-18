"""
File-based LLM response cache.

Keys are SHA-256 hashes of (system_prompt + user_prompt + model + temperature).
Cached responses are stored as JSON files in data/cache/llm/ with a configurable TTL.
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


def _cache_key(system_prompt: str, user_prompt: str, model: str, temperature: float) -> str:
    raw = f"{system_prompt}\x00{user_prompt}\x00{model}\x00{temperature}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def get_cached(system_prompt: str, user_prompt: str, model: str, temperature: float) -> Optional[str]:
    """Return cached LLM response if valid, else None."""
    key = _cache_key(system_prompt, user_prompt, model, temperature)
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        expires_at = data.get("expires_at", 0)
        if time.time() > expires_at:
            path.unlink(missing_ok=True)
            return None
        logger.info("LLM cache hit: %s", key[:12])
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
) -> None:
    """Store an LLM response in the cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(system_prompt, user_prompt, model, temperature)
    data = {
        "response": response,
        "model": model,
        "created_at": time.time(),
        "expires_at": time.time() + ttl_hours * 3600,
    }
    try:
        tmp = _cache_path(key).with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_cache_path(key))
    except OSError as e:
        logger.warning("Failed to write LLM cache: %s", e)
