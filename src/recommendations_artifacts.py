"""Utilities for reading AutoResearchClaw paper-recommender artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def safe_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def paper_id(item: dict[str, Any]) -> str:
    for key in ("paper_id", "arxiv_id", "doi", "id", "doc_id"):
        value = safe_str(item.get(key))
        if value:
            return value
    title = safe_str(item.get("title")).lower()
    return f"{title}::{item.get('year') or ''}"


def coerce_authors(value: Any) -> list[str]:
    if isinstance(value, list):
        return [safe_str(v) for v in value if safe_str(v)][:6]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()][:6]
    return []


def parse_run_at(raw: dict[str, Any], fallback_path: Path) -> str:
    run_at = safe_str(raw.get("run_at"))
    if run_at:
        return run_at
    try:
        return datetime.fromtimestamp(fallback_path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return ""


def artifact_belongs_to_user(root: Path, path: Path, raw: dict[str, Any], username: str) -> bool:
    user_id = safe_str(raw.get("user_id"))
    if user_id:
        return user_id == username

    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        return False
    return username in relative_parts


def latest_raw_file(root: Path, username: str) -> Path | None:
    if not root.exists():
        return None

    candidates = sorted(root.glob("**/raw.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if artifact_belongs_to_user(root, path, raw, username):
            return path
    return None


def load_recommendation_artifact(root: Path, username: str, limit: int) -> dict[str, Any]:
    raw_path = latest_raw_file(root, username)
    if raw_path is None:
        return {
            "items": [],
            "unread_count": 0,
            "latest_run_at": None,
            "scoring_mode": None,
            "score_stats": {},
        }

    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "items": [],
            "unread_count": 0,
            "latest_run_at": None,
            "scoring_mode": None,
            "score_stats": {},
        }

    run_at = parse_run_at(raw, raw_path)
    items: list[dict[str, Any]] = []
    variants = raw.get("variants") if isinstance(raw.get("variants"), dict) else {}
    for variant, papers in variants.items():
        if not isinstance(papers, list):
            continue
        for item in papers:
            if not isinstance(item, dict):
                continue
            title = safe_str(item.get("title")) or "Untitled paper"
            item_id = paper_id(item)
            score = item.get("score")
            rank = item.get("rank")
            try:
                score = float(score) if score is not None else None
            except (TypeError, ValueError):
                score = None
            try:
                rank = int(rank) if rank is not None else None
            except (TypeError, ValueError):
                rank = None
            items.append(
                {
                    "id": f"{run_at}:{variant}:{item_id}",
                    "title": title,
                    "reason": safe_str(item.get("reason")),
                    "variant": str(variant),
                    "run_at": run_at,
                    "score": score,
                    "rank": rank,
                    "year": item.get("year"),
                    "authors": coerce_authors(item.get("authors")),
                    "venue": safe_str(item.get("venue")) or None,
                    "source": safe_str(item.get("source")) or None,
                    "url": safe_str(item.get("url")) or None,
                    "pdf_url": safe_str(item.get("pdf_url")) or None,
                    "doi": safe_str(item.get("doi")) or None,
                    "arxiv_id": safe_str(item.get("arxiv_id")) or None,
                }
            )

    items.sort(
        key=lambda x: (
            x["score"] if x["score"] is not None else -1,
            -(x["rank"] or 9999),
        ),
        reverse=True,
    )
    return {
        "items": items[:limit],
        "unread_count": len(items),
        "latest_run_at": run_at or None,
        "scoring_mode": safe_str(raw.get("scoring_mode")) or None,
        "score_stats": raw.get("score_stats") if isinstance(raw.get("score_stats"), dict) else {},
    }
