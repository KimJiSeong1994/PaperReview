#!/usr/bin/env python3.12
"""Generate the 20-sample golden regression dataset for paper review output.

Usage::

    python3.12 scripts/generate_review_goldens.py \
        --input path/to/sample_papers.jsonl \
        --output tests/goldens/paper_reviews/ \
        --limit 20

Each line of ``sample_papers.jsonl`` must contain a JSON object with at
least ``title``, ``abstract``, and optional ``authors`` / ``year`` /
``full_text`` fields. One golden fixture file is written per paper.

The golden file schema is::

    {
        "paper": {...},
        "review": {...},
        "review_hash": "<sha256 of canonical review JSON>",
        "generated_at": "2026-...",
        "model": "gpt-4.1"
    }

Consumed by ``tests/test_prompt_cache_alignment.py::
test_paper_review_golden_hash_regression``. Once the fixture directory
contains 20 files the xfail in that test can be removed (or it will
naturally pass).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root importable when run directly from scripts/.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests._review_hash import canonical_review_hash as _canonical_hash  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="JSONL file of sample papers (one JSON object per line).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "tests" / "goldens" / "paper_reviews",
        help="Directory to write golden fixture files into.",
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--model", default="gpt-4.1")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from routers.deps import get_openai_client
    from routers.paper_review_service import generate_paper_review

    args.output.mkdir(parents=True, exist_ok=True)
    client = get_openai_client()

    written = 0
    with args.input.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            if written >= args.limit:
                break

            paper = json.loads(line)
            logger.info("[%d/%d] reviewing: %s", written + 1, args.limit, paper.get("title", "?"))
            try:
                review = generate_paper_review(paper, client, model=args.model)
            except Exception as exc:  # noqa: BLE001
                logger.warning("skip line %d: %s", line_no, exc)
                continue

            fixture = {
                "paper": paper,
                "review": review,
                "review_hash": _canonical_hash(review),
                "generated_at": datetime.now().isoformat(),
                "model": args.model,
            }

            stem = paper.get("arxiv_id") or paper.get("id") or f"paper_{written + 1:02d}"
            stem = str(stem).replace("/", "_")
            out_path = args.output / f"{stem}.json"
            out_path.write_text(
                json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("wrote %s (hash=%s)", out_path, fixture["review_hash"][:12])
            written += 1

    logger.info("done: %d goldens under %s", written, args.output)
    if written < args.limit:
        logger.warning("only %d/%d fixtures generated", written, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
