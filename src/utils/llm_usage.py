"""Append-only LLM usage ledger: one JSON line per call, never raises."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LEDGER_PATH = Path("logs/llm_usage.jsonl")


def _nested(obj: Any, *names: str) -> Any:
    for name in names:
        obj = getattr(obj, name, None)
        if obj is None:
            return None
    return obj


def record_llm_usage(stage: str, model: str, usage: Any, **extra: Any) -> None:
    """Append one usage row for ``stage``; accepts Chat or Responses usage shapes."""
    counts = tuple(getattr(usage, name, None) for name in ("prompt_tokens", "completion_tokens", "total_tokens"))
    if not any(isinstance(c, int) and not isinstance(c, bool) for c in counts):
        return  # None or a test mock: nothing real to record
    raw = getattr(usage, "response_usage", None) or usage
    row = {
        "ts": round(time.time(), 3),
        "stage": stage,
        "model": model,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
        "cached_tokens": _nested(raw, "input_tokens_details", "cached_tokens")
        or _nested(raw, "prompt_tokens_details", "cached_tokens"),
        "reasoning_tokens": _nested(raw, "output_tokens_details", "reasoning_tokens")
        or _nested(raw, "completion_tokens_details", "reasoning_tokens"),
        **extra,
    }
    try:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        logger.warning("LLM usage ledger write failed: %s", exc)
