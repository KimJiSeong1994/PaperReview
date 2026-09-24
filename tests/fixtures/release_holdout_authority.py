from __future__ import annotations

import os
from pathlib import Path

from src.search_eval.release_holdout import (
    RELEASE_HOLDOUT_AUTHORITY,
    RELEASE_HOLDOUT_AUTHORITY_CONTEXT_ENV,
    RELEASE_HOLDOUT_AUTHORITY_CONTEXT_VERSION,
    RELEASE_HOLDOUT_MANIFEST_VERSION,
)
from src.search_eval.skillopt_run_contract import canonical_json_bytes, canonical_value_hash


def release_manifest_payload(
    root: Path,
    *,
    generation_id: str,
    object_version: str,
    issuer_identity: str,
    evaluator_identity: str,
    verifier_identity: str = "release-verifier:v1",
) -> dict[str, object]:
    store_root = root / "release-authority-store"
    namespace = "private-release-holdouts"
    object_key = f"holdouts/{generation_id.replace(':', '-')}.jsonl"
    object_path = store_root / namespace / object_key
    object_path.parent.mkdir(parents=True, exist_ok=True)
    payload = b'{"private":"release-holdout-fixture"}\n'
    object_path.write_bytes(payload)
    holdout_sha = "sha256:" + __import__("hashlib").sha256(payload).hexdigest()
    acl_hash = "sha256:" + "c" * 64
    context: dict[str, object] = {
        "version": RELEASE_HOLDOUT_AUTHORITY_CONTEXT_VERSION,
        "allowed_manifest_issuers": [issuer_identity],
        "allowed_evaluator_identities": [evaluator_identity],
        "allowed_verifier_identities": [verifier_identity],
        "immutable_store": {
            "root": str(store_root.resolve()),
            "store_id": "release-store:v1",
            "namespace": namespace,
            "object_prefix": "holdouts/",
            "retention_mode": "governance-compliance",
            "receipt_issuer_identity": "release-store-receipt-issuer:v1",
        },
        "acl_receipt": {
            "issuer_identity": "release-acl-issuer:v1",
            "receipt_hash": acl_hash,
        },
        "valid_from": "2020-01-01T00:00:00Z",
        "expires_at": "2035-01-01T00:00:00Z",
    }
    context["context_hash"] = canonical_value_hash(context)
    context_path = root / "release_holdout_authority_context.json"
    context_path.write_bytes(canonical_json_bytes(context))
    os.environ[RELEASE_HOLDOUT_AUTHORITY_CONTEXT_ENV] = str(context_path.resolve())
    receipt: dict[str, object] = {
        "store_id": "release-store:v1",
        "namespace": namespace,
        "object_key": object_key,
        "object_version": object_version,
        "holdout_sha256": holdout_sha,
        "holdout_size_bytes": len(payload),
        "retention_mode": "governance-compliance",
        "acl_receipt_hash": acl_hash,
        "receipt_issuer_identity": "release-store-receipt-issuer:v1",
    }
    receipt["receipt_hash"] = canonical_value_hash(receipt)
    return {
        "version": RELEASE_HOLDOUT_MANIFEST_VERSION,
        "generation_id": generation_id,
        "object_version": object_version,
        "holdout_sha256": holdout_sha,
        "holdout_size_bytes": len(payload),
        "authority_classification": RELEASE_HOLDOUT_AUTHORITY,
        "issuer_identity": issuer_identity,
        "verifier_identity": verifier_identity,
        "authority_context_hash": context["context_hash"],
        "immutable_store_receipt": receipt,
    }
