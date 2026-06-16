"""Central OpenAI model defaults for runtime components.

Defaults are intentionally split by workload:
- research/answering paths use the strongest current default;
- high-frequency search/tooling paths use a low-latency reasoning model;
- embedding defaults stay dimension-compatible and are not env-overridden here.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional for pure imports
    load_dotenv = None  # type: ignore[assignment]

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if load_dotenv is not None:
    load_dotenv(dotenv_path=_PROJECT_ROOT / ".env", override=False)

# User-visible answer/review/reasoning quality paths.
DEFAULT_RESEARCH_MODEL = os.getenv("RESEARCH_MODEL", "gpt-5.5")

# High-frequency search planning, extraction, relevance fallback, and JSON utility calls.
DEFAULT_TOOL_MODEL = os.getenv("TOOL_MODEL", "gpt-5.4-mini")

# Internal judge/evaluation/fact-check helper calls; keep fast by default.
DEFAULT_EVAL_MODEL = os.getenv("EVAL_MODEL", "gpt-5.4-mini")

# Keep embedding indexes dimension-compatible. Do not make these environment-driven
# in the chat-model upgrade path, because a silent dimension change would require
# rebuilding FAISS/vector caches.
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_KOREAN_EMBEDDING_MODEL = "text-embedding-3-large"
