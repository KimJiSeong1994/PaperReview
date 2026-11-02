"""Export one stored conversation as a public, sanitised sample for the logged-out home.

    python scripts/export_sample_conversation.py --conversation <id> --slug <slug> --title "<title>" [--asof YYYY-MM-DD]

Run by the operator (owner-agnostic). Reads DATA_DIR/conversations.db and writes
data/samples/conversations/<slug>.json, which /api/samples serves.

Sanitising: no username/account fields anywhere; error/running turns dropped;
"내 연구와의 연결" lines and research-profile leads removed (they describe the
demo account, not the reader); only search_results and graph blocks kept, with
≤20 papers and the graph trimmed to those papers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = ROOT / "data" / "samples" / "conversations"
MAX_SAMPLE_PAPERS = 20
KEEP_BLOCKS = {"search_results", "graph"}
PRIVATE_KEYS = {"username", "account_incarnation", "searched_by", "owner", "user_id"}
NEUTRAL_LEAD = "관련 논문을 찾아 근거와 함께 답해 볼게요."
_PROFILE_LEAD = re.compile(r"^연구 프로필 기준으로[^\n]*")
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


def _scrub(value: Any) -> Any:
    """Drop user/account keys at any depth."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def clean_content(text: str) -> str:
    """Remove profile-specific lines; neutralise a research-profile lead."""
    text = _PROFILE_LEAD.sub(NEUTRAL_LEAD, text or "")
    lines = [line for line in text.split("\n") if not line.lstrip("-•* ").startswith("내 연구와의 연결")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def clean_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep search_results (≤20 papers) and graph (only those papers' nodes and edges)."""
    kept, keys = [], None
    for block in blocks or []:
        if block.get("type") not in KEEP_BLOCKS:
            continue
        block = _scrub(block)
        if block["type"] == "search_results":
            block["papers"] = block.get("papers", [])[:MAX_SAMPLE_PAPERS]
            block["total"] = len(block["papers"])
            keys = {p.get("result_key") or p.get("doc_id") for p in block["papers"]}
        kept.append(block)
    for block in kept:
        if block["type"] == "graph" and keys is not None:
            graph = block.get("graph") or {}
            nodes = [n for n in graph.get("nodes", []) if n.get("id") in keys]
            ids = {n["id"] for n in nodes}
            edges = [e for e in graph.get("edges", []) if e.get("source") in ids and e.get("target") in ids]
            block["graph"] = {**graph, "nodes": nodes, "edges": edges}
    return kept


def build_sample(turns: List[Dict[str, Any]], *, slug: str, title: str, asof: str) -> Dict[str, Any]:
    """The public sample document from stored turn rows ({seq, role, content, blocks_json|blocks, intent, status})."""
    out = []
    for turn in sorted(turns, key=lambda t: t["seq"]):
        if turn.get("status", "done") != "done":
            continue
        blocks = turn.get("blocks")
        if blocks is None:
            blocks = json.loads(turn.get("blocks_json") or "[]")
        out.append({
            "seq": len(out) + 1, "role": turn["role"], "content": clean_content(turn.get("content", "")),
            "blocks": clean_blocks(blocks), "intent": turn.get("intent"),
        })
    question = next((t["content"] for t in out if t["role"] == "user"), "")
    return {"id": f"sample-{slug}", "slug": slug, "title": title, "question": question, "asof": asof, "turns": out}


def export_sample(db_path: Path, conversation_id: str, *, slug: str, title: str, asof: str, out_dir: Path) -> Path:
    """Read the conversation (any owner), sanitise it and write <out_dir>/<slug>.json."""
    if not _SLUG.fullmatch(slug):
        raise ValueError("slug must be lowercase letters, digits and hyphens")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        turns = [dict(r) for r in conn.execute(
            "SELECT seq, role, content, blocks_json, intent, status FROM turns WHERE conversation_id = ? ORDER BY seq",
            (conversation_id,),
        )]
    finally:
        conn.close()
    if not turns:
        raise LookupError(f"conversation {conversation_id} not found")
    sample = build_sample(turns, slug=slug, title=title, asof=asof)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{slug}.json"
    path.write_text(json.dumps(sample, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--conversation", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--asof", default=date.today().isoformat())
    parser.add_argument("--db", type=Path, default=Path(os.getenv("DATA_DIR", "data")) / "conversations.db")
    parser.add_argument("--out-dir", type=Path, default=SAMPLES_DIR)
    args = parser.parse_args(argv)
    path = export_sample(args.db, args.conversation, slug=args.slug, title=args.title, asof=args.asof,
                         out_dir=args.out_dir)
    print(json.dumps({"written": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
