#!/usr/bin/env python3
"""CLI wrapper for GA4 BigQuery -> analytics.db daily aggregate sync."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.analytics.ga4_bigquery_sync import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
