#!/usr/bin/env python3
"""Public-only fixed-seed candidate staging and bibliographic wiki CLI."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.related_paper_wiki import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
