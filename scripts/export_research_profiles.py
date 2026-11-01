"""Export every account's research profile as JSON lines for downstream newsletter jobs.

    python scripts/export_research_profiles.py --out profiles.jsonl [--souls-db data/souls.db] [--build-missing]

Each line: {"username", "account_incarnation", "profile"}. Cached profiles are exported as
stored; with --build-missing, accounts whose profile is missing or stale get the
deterministic profile (no model call), so the export runs offline. No email is sent here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.assistant.profile import build_research_profile, source_hash  # noqa: E402
from src.storage.soul_db import SoulDB  # noqa: E402


def export_profiles(souls_db: Path, out: Path, build_missing: bool = False) -> int:
    """Write the JSONL file; returns the number of lines written."""
    db = SoulDB(souls_db)
    rows = {(r["username"], r["account_incarnation"]): r["profile"] for r in db.all_profiles()}
    if build_missing:
        for username, incarnation in db.owners():  # accounts with a soul but no current profile
            soul = db.get_soul(username, incarnation)
            digest = source_hash(soul)
            cached = rows.get((username, incarnation))
            if cached is None or cached.get("source_hash") != digest:
                profile = asyncio.run(build_research_profile(soul, use_model=False))
                rows[(username, incarnation)] = {**profile, "source_hash": digest}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for (username, incarnation), profile in sorted(rows.items()):
            handle.write(json.dumps({"username": username, "account_incarnation": incarnation, "profile": profile},
                                    ensure_ascii=False) + "\n")
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--souls-db", type=Path, default=Path("data/souls.db"))
    parser.add_argument("--build-missing", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps({"written": export_profiles(args.souls_db, args.out, args.build_missing)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
