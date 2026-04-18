"""Week 0 B5 Embedding Dimension Verification Gate (US-001).

This script validates that stored embeddings in data/embeddings/embeddings.json
match the target dimension (default 384) and optionally cross-checks against a
live OpenAI API probe. It is designed to run in CI (--skip-api) and locally.

Exit codes:
  0 — all checks passed; data/.embedding_dim_check.json written
  1 — dimension mismatch or file not found
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
EMBEDDINGS_PATH = REPO_ROOT / "data" / "embeddings" / "embeddings.json"
OUTPUT_PATH = REPO_ROOT / "data" / ".embedding_dim_check.json"


def load_stored_dim(path: Path) -> Optional[int]:
    """Return the dimension of the first embedding vector in *path*.

    Supports the dict-of-list format:
        {"key": [float, ...], ...}
    """
    logger.info("Reading embeddings from %s", path)
    if not path.exists():
        logger.error("Embeddings file not found: %s", path)
        return None

    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    if isinstance(data, dict):
        first_value = next(iter(data.values()), None)
        if isinstance(first_value, list):
            dim = len(first_value)
            logger.info("Measured stored dim: %d (from %d entries)", dim, len(data))
            return dim

    logger.error("Unexpected embeddings format in %s", path)
    return None


def probe_api_dim(expected_dim: int) -> Optional[int]:
    """Call OpenAI with dimensions=%d and return the actual vector length."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — skipping API probe")
        return None

    try:
        from openai import OpenAI  # type: ignore[import]
    except ImportError:
        logger.warning("openai package not installed — skipping API probe")
        return None

    logger.info("Probing OpenAI API (model=text-embedding-3-small, dimensions=%d)", expected_dim)
    client = OpenAI(api_key=api_key)
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input="probe",
        dimensions=expected_dim,
    )
    dim = len(response.data[0].embedding)
    logger.info("API returned dim: %d", dim)
    return dim


def write_result(stored: int, api: Optional[int], target: int) -> None:
    """Persist the check result to OUTPUT_PATH."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stored": stored,
        "api": api,
        "target": target,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    logger.info("Result written to %s", OUTPUT_PATH)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify embedding dimension matches the Week-0 B5 target."
    )
    parser.add_argument(
        "--skip-api",
        action="store_true",
        help="Skip OpenAI API probe (safe for CI / offline environments).",
    )
    parser.add_argument(
        "--expected-dim",
        type=int,
        default=384,
        metavar="DIM",
        help="Target embedding dimension (default: 384).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target: int = args.expected_dim

    # --- Check stored dim ---
    stored = load_stored_dim(EMBEDDINGS_PATH)
    if stored is None:
        print("FAIL: could not read stored embeddings")
        return 1

    if stored != target:
        print(f"FAIL: stored dim {stored} != target {target}")
        return 1

    # --- Optional API probe ---
    api_dim: Optional[int] = None
    if not args.skip_api:
        api_dim = probe_api_dim(target)
        if api_dim is not None and api_dim != target:
            print(f"FAIL: API returned dim {api_dim} != target {target}")
            return 1

    # --- Write result ---
    write_result(stored=stored, api=api_dim, target=target)
    print(f"PASS: stored={stored}, api={api_dim}, target={target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
