#!/usr/bin/env python3
"""Import an OpenClaw paper-recommender raw.json into PaperReviewAgent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.openclaw_recommendations import OpenClawArtifactError, import_openclaw_artifact  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import an OpenClaw recommendation raw.json artifact.")
    parser.add_argument("raw_json", type=Path, help="Path to OpenClaw paper-recommender artifacts/YYYY-MM-DD/raw.json")
    parser.add_argument("--artifacts-dir", type=Path, default=Path("data/recommendations"))
    parser.add_argument("--date", help="Override destination date (YYYY-MM-DD).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = import_openclaw_artifact(args.raw_json, args.artifacts_dir, date_override=args.date)
    except OpenClawArtifactError as exc:
        print(f"OpenClaw artifact import failed: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "imported": True,
                "user_id": result.user_id,
                "date": result.date,
                "destination_path": str(result.destination_path),
                "variant_count": result.variant_count,
                "item_count": result.item_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
