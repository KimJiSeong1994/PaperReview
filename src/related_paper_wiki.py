"""Public-only fixed-seed acquisition; no user storage or legacy mixed pool."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import multiprocessing
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.recommendation_candidates import (
    MAX_BYTES,
    CandidateValidationError,
    TrustedReceiverPolicy,
    make_candidate_snapshot,
    merge_candidate_pool,
    write_candidate_snapshot,
)

PUBLIC_SEEDS = ("graph neural networks", "information retrieval", "urban mobility")
PROVENANCE_ID = "public-seeds-v1"


def load_seed_queries() -> list[str]:
    return list(PUBLIC_SEEDS)


def _provider_worker(connection, query, deadline):
    from src.collector.paper.openalex_searcher import OpenAlexSearcher

    searcher = OpenAlexSearcher()
    try:
        attempts = []
        papers = searcher.search_public(
            query,
            max_results=8,
            deadline=deadline,
            attempts=attempts,
            max_response_bytes=MAX_BYTES,
        )
        connection.send((papers, attempts))
    except Exception:
        connection.send(([], [{"status": "error"}]))
    finally:
        searcher.close()
        connection.close()


def _provider_attempt(query: str, deadline: float) -> tuple[list, list]:
    """One process owns the blocking request; stop and join before releasing capacity."""
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_provider_worker, args=(sender, query, deadline))
    process.start()
    sender.close()
    try:
        if receiver.poll(max(0, deadline - time.monotonic())):
            return receiver.recv()
        return [], [{"status": "timeout"}]
    except (EOFError, OSError):
        return [], [{"status": "error"}]
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=0.2)
        if process.is_alive():
            process.kill()
            process.join()


def _atomic(path: Path, content: str) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise CandidateValidationError("unsafe_path")
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".public-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def collect_review_build_wiki(
    *,
    candidate_root: Path,
    final_root: Path,
    run_at: str,
    source_qualified: bool = False,
    attempt: Callable | None = None,
    clock: Callable[[], float] = time.monotonic,
    stop_event=None,
) -> dict:
    """Collect <=3x8 fixed public seeds, <=6 attempts, serial capacity, 60s total.

    Injected attempts are fixtures, never proof of actual provider availability.
    Wiki and acquisition receipt live alongside validated public staging only.
    """
    parsed = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
    policy = TrustedReceiverPolicy(
        "local_public", "public", PROVENANCE_ID, public_source_qualified=True
    )
    run_id = parsed.strftime("%Y%m%dT%H%M%S%fZ")
    # Validate time and root before any provider work; no fallback to legacy data.
    make_candidate_snapshot(
        [], policy=policy, source_run_id=run_id, collected_at=run_at, now=parsed
    )
    root, final = Path(candidate_root).resolve(), Path(final_root).resolve()
    if root == final or root.is_relative_to(final) or final.is_relative_to(root):
        raise CandidateValidationError("final_root_overlap")
    if any(
        p.is_symlink()
        for p in (
            Path(candidate_root).absolute(),
            *Path(candidate_root).absolute().parents,
        )
    ):
        raise CandidateValidationError("unsafe_path")
    deadline = clock() + 60
    records, receipts = [], []
    provider = attempt or _provider_attempt
    if source_qualified:
        for seed in PUBLIC_SEEDS:
            for retry in range(2):
                if clock() >= deadline or (
                    stop_event is not None and stop_event.is_set()
                ):
                    break
                attempt_deadline = min(deadline, clock() + 10)
                try:
                    papers, evidence = provider(seed, attempt_deadline)
                except Exception:
                    papers, evidence = [], [{"status": "error"}]
                status = evidence[-1].get("status", "error") if evidence else "error"
                if clock() >= attempt_deadline:
                    status, papers = "timeout", []
                safe = {
                    "seed_sha256": hashlib.sha256(seed.encode()).hexdigest(),
                    "source": "openalex",
                    "collected_at": run_at,
                    "attempt": retry + 1,
                    "status": status
                    if status in {"searched", "searched_empty", "timeout"}
                    else "error",
                }
                if evidence and isinstance(evidence[-1].get("response_sha256"), str):
                    digest = evidence[-1]["response_sha256"]
                    if len(digest) == 64 and all(
                        c in "0123456789abcdef" for c in digest
                    ):
                        safe["response_sha256"] = digest
                        size = evidence[-1].get("response_bytes")
                        if isinstance(size, int) and 0 <= size <= MAX_BYTES:
                            safe["response_bytes"] = size
                receipts.append(safe)
                if status in {"searched", "searched_empty"}:
                    records.extend(papers[:8])
                    break
    if clock() >= deadline or (stop_event is not None and stop_event.is_set()):
        return {
            "code": "collection_deadline",
            "status": "empty",
            "attempt_count": len(receipts),
            "item_count": 0,
        }
    failures = any(item["status"] in {"error", "timeout"} for item in receipts)
    successes = any(
        item["status"] in {"searched", "searched_empty"} for item in receipts
    )
    reasons = []
    if not source_qualified:
        health, reasons = "disabled", ["source_disabled"]
    elif failures:
        health = "degraded" if successes else "error"
        reasons = sorted(
            {
                (
                    "provider_timeout"
                    if item["status"] == "timeout"
                    else "provider_error"
                )
                for item in receipts
                if item["status"] in {"error", "timeout"}
            }
        )
        if successes:
            reasons.append("partial_failure")
    else:
        health = None
    snapshot = make_candidate_snapshot(
        records,
        policy=policy,
        source_run_id=run_id,
        collected_at=run_at,
        now=parsed,
        acquisition_status=health,
        acquisition_reasons=reasons,
    )
    if snapshot.rejected_counts:
        snapshot = make_candidate_snapshot(
            records,
            policy=policy,
            source_run_id=run_id,
            collected_at=run_at,
            now=parsed,
            acquisition_status="degraded",
            acquisition_reasons=[*reasons, "records_rejected"],
        )
    if clock() >= deadline or (stop_event is not None and stop_event.is_set()):
        return {
            "code": "collection_deadline",
            "status": "empty",
            "attempt_count": len(receipts),
            "item_count": 0,
        }
    destination = write_candidate_snapshot(
        snapshot, root=candidate_root, final_root=final_root
    )
    manifest = {
        "version": PROVENANCE_ID,
        "seeds": list(PUBLIC_SEEDS),
        "source": "openalex",
    }
    manifest_hash = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt = {
        "schema": "public_acquisition_v1",
        "public_seed_manifest": manifest,
        "manifest_sha256": manifest_hash,
        "snapshot_checksum": snapshot.checksum,
        "collected_at": run_at,
        "source": "openalex",
        "attempts": receipts,
        "availability": "disabled"
        if not source_qualified
        else "fixture"
        if attempt
        else "observed_nonempty"
        if snapshot.records
        else "observed_empty",
    }
    _atomic(
        destination.with_suffix(".receipt.json"), json.dumps(receipt, sort_keys=True)
    )
    pool = merge_candidate_pool([snapshot], public_only=True)
    lines = ["# Public bibliographic candidates", "", f"Collection time: {run_at}", ""]
    for record in pool.records:
        paper = record.metadata
        lines.extend(
            [
                "## " + html.escape(paper["title"]),
                "",
                html.escape(paper.get("abstract", "")),
                "",
                "Canonical key: " + html.escape(record.canonical_key),
                "",
            ]
        )
    if not pool.records:
        lines.append("No validated public candidates available.")
    _atomic(destination.with_suffix(".wiki.md"), "\n".join(lines))
    return {
        "code": "public_candidates_staged",
        "status": snapshot.status,
        "acquisition_status": snapshot.acquisition_status,
        "acquisition_reasons": list(snapshot.acquisition_reasons),
        "attempt_count": len(receipts),
        "item_count": len(snapshot.records),
        "rejected_counts": snapshot.rejected_counts,
        "availability": receipt["availability"],
    }


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CandidateValidationError("invalid_arguments")


def build_parser():
    parser = _Parser(description="Public-only fixed-seed candidate acquisition.")
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--final-root", required=True, type=Path)
    parser.add_argument("--run-at", required=True)
    parser.add_argument("--source-qualified", action="store_true")
    return parser


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
        result = collect_review_build_wiki(
            candidate_root=args.candidate_root,
            final_root=args.final_root,
            run_at=args.run_at,
            source_qualified=args.source_qualified,
        )
    except CandidateValidationError as exc:
        print(json.dumps({"code": exc.code}))
        return 2
    except Exception:
        print(json.dumps({"code": "collection_failed"}))
        return 2
    print(json.dumps(result, sort_keys=True))
    if result["code"] == "collection_deadline":
        return 2
    return 3 if result.get("acquisition_status") == "error" else 0
