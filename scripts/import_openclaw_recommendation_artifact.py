#!/usr/bin/env python3
"""Receive a qualified local artifact into candidate staging, never serving."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.openclaw_recommendations import OpenClawArtifactError, import_openclaw_artifact  # noqa: E402
from src.recommendation_candidates import (  # noqa: E402
    CandidateValidationError,
    TrustedReceiverPolicy,
)


class CodeParser(argparse.ArgumentParser):
    def error(self, message):
        raise OpenClawArtifactError("invalid_arguments")


def build_parser() -> argparse.ArgumentParser:
    parser = CodeParser(
        description="Stage qualified OpenClaw bibliographic candidates locally."
    )
    parser.add_argument("raw_json", type=Path)
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--final-root", required=True, type=Path)
    parser.add_argument("--source", required=True, choices=["openclaw"])
    parser.add_argument("--source-qualified", action="store_true")
    parser.add_argument("--provenance-id", required=True)
    parser.add_argument("--scope", required=True, choices=["public", "private"])
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--collected-at", required=True)
    parser.add_argument("--username")
    parser.add_argument("--account-incarnation")
    parser.add_argument("--users-db", type=Path)
    parser.add_argument("--budget-seconds", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if not args.source_qualified:
            raise OpenClawArtifactError("source_disabled")
        if args.budget_seconds is not None and (
            not math.isfinite(args.budget_seconds) or args.budget_seconds <= 0
        ):
            raise OpenClawArtifactError("invalid_budget")
        deadline = (
            None
            if args.budget_seconds is None
            else time.monotonic() + args.budget_seconds
        )
        if args.scope == "private":
            if (
                not args.username
                or not args.account_incarnation
                or args.users_db is None
            ):
                raise OpenClawArtifactError("principal_required")
            if not args.users_db.is_file() or args.users_db.is_symlink():
                raise OpenClawArtifactError("principal_unavailable")
            from src.storage.user_db import UserDB

            user_db = UserDB(args.users_db)
        else:
            if args.username or args.account_incarnation or args.users_db is not None:
                raise OpenClawArtifactError("invalid_arguments")
            user_db = None
        policy = TrustedReceiverPolicy(
            "openclaw",
            args.scope,
            args.provenance_id,
            account_incarnation=args.account_incarnation,
            public_source_qualified=args.scope == "public",
        )
        result = import_openclaw_artifact(
            args.raw_json,
            candidate_root=args.candidate_root,
            final_root=args.final_root,
            policy=policy,
            source_run_id=args.source_run_id,
            collected_at=args.collected_at,
            now=datetime.now(timezone.utc),
            username=args.username,
            user_db=user_db,
            deadline=deadline,
        )
    except (OpenClawArtifactError, CandidateValidationError) as exc:
        print(json.dumps({"code": exc.code}), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"code": "receiver_failed"}), file=sys.stderr)
        return 2
    print(json.dumps(result.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
