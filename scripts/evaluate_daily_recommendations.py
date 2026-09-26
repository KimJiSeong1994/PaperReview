#!/usr/bin/env python3
"""Offline evaluation only. Exit 0: validation; 1: gate failure; 2: invalid; 3: nonpromotion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.recommendation_evaluation import (  # noqa: E402
    EvaluationError,
    evaluate_manifest,
    load_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", required=True, help="Frozen JSON under data/recommendation_eval"
    )
    parser.add_argument(
        "--offline",
        required=True,
        action="store_true",
        help="Required; never accesses providers or user stores",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Check frozen evidence consistency, not quality/promotion",
    )
    parser.add_argument(
        "--report-out",
        help="New JSON file under data/recommendation_eval; existing files are never overwritten",
    )
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest, root=ROOT)
        if args.validate_only:
            report = {
                "status": "valid",
                "consistency": "passed",
                "promotion": False,
                "quality_evaluated": False,
                "bindings": manifest["bindings"],
            }
            exit_code = 0
        else:
            report = evaluate_manifest(manifest, root=ROOT)
            exit_code = 1 if report["status"] == "fail" else 3
        encoded = (
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )
        if args.report_out:
            path = Path(args.report_out)
            if path.is_absolute():
                path = path.relative_to(ROOT)
            if path.parts[:2] != ("data", "recommendation_eval") or ".." in path.parts:
                raise EvaluationError("unsafe_report_path")
            current = ROOT
            for part in path.parts:
                current = current / part
                if current.is_symlink():
                    raise EvaluationError("symlink_report_path")
            with current.open("x", encoding="utf-8") as handle:
                handle.write(encoded)
        print(encoded, end="")
        return exit_code
    except (EvaluationError, OSError, ValueError, TypeError, KeyError) as exc:
        # Do not echo a path, private payload, or arbitrary exception text.
        reason = (
            str(exc)
            if isinstance(exc, EvaluationError)
            else "invalid_or_unreadable_evidence"
        )
        print(json.dumps({"status": "invalid", "promotion": False, "reason": reason}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
