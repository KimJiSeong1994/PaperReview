#!/usr/bin/env python3
"""CLI wrapper for daily recommendation artifact generation."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.daily_recommendations import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
