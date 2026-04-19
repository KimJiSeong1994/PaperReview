"""Shared helper for deterministic review hashing.

Both ``scripts/generate_review_goldens.py`` and
``tests/test_prompt_cache_alignment.py`` must produce identical hashes for the
same review object.  The helper lives here so both sides import the exact same
normalization logic.
"""

import hashlib
import json


# Fields excluded from the canonical hash because they vary per-call and are
# not part of the stable review payload.
_VOLATILE_FIELDS = frozenset({"created_at", "model", "input_type"})


def normalize_review_for_hash(review: dict) -> str:
    """Return a deterministic JSON string for *review* suitable for hashing.

    Removes per-call volatile fields (``created_at``, ``model``,
    ``input_type``) then serialises with ``sort_keys=True`` so the result is
    independent of insertion order.
    """
    stripped = {k: v for k, v in review.items() if k not in _VOLATILE_FIELDS}
    return json.dumps(stripped, sort_keys=True, ensure_ascii=False)


def canonical_review_hash(review: dict) -> str:
    """Return the SHA-256 hex digest of the normalised *review* dict."""
    return hashlib.sha256(
        normalize_review_for_hash(review).encode("utf-8")
    ).hexdigest()
