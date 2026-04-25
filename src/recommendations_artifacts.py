"""Utilities for reading AutoResearchClaw paper-recommender artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EMPTY_RECOMMENDATIONS: dict[str, Any] = {
    "items": [],
    "grouped_items": [],
    "unread_count": 0,
    "raw_count": 0,
    "latest_run_at": None,
    "scoring_mode": None,
    "score_stats": {},
}


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


def coerce_score(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def coerce_rank(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def display_score(score: float | None) -> str | None:
    if score is None:
        return None
    return f"{score:.1f}"


def confidence_label(score: float | None, rank: int | None) -> str:
    if rank == 1:
        return "상위 추천"
    if score is None:
        return "추천"
    if score >= 4.5:
        return "강한 추천"
    if score >= 3.5:
        return "관련도 높음"
    return "검토 추천"


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


def _sort_key(item: dict[str, Any]) -> tuple[float, int]:
    score = item.get("score")
    rank = item.get("rank")
    return (
        score if isinstance(score, (int, float)) else -1,
        -(rank if isinstance(rank, int) else 9999),
    )


def _paper_row(run_at: str, variant: str, item: dict[str, Any]) -> dict[str, Any]:
    title = safe_str(item.get("title")) or "Untitled paper"
    item_id = paper_id(item)
    score = coerce_score(item.get("score"))
    rank = coerce_rank(item.get("rank"))
    label = confidence_label(score, rank)
    return {
        "id": f"{run_at}:{variant}:{item_id}",
        "paper_id": item_id,
        "title": title,
        "reason": safe_str(item.get("reason")),
        "variant": str(variant),
        "run_at": run_at,
        "score": score,
        "display_score": display_score(score),
        "confidence_label": label,
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


def _group_items(items: list[dict[str, Any]], run_at: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in items:
        group = grouped.setdefault(
            row["paper_id"],
            {
                "id": f"{run_at}:{row['paper_id']}",
                "paper_id": row["paper_id"],
                "title": row["title"],
                "top_reason": "",
                "run_at": row["run_at"],
                "score": row["score"],
                "display_score": row["display_score"],
                "confidence_label": row["confidence_label"],
                "rank": row["rank"],
                "year": row["year"],
                "authors": row["authors"],
                "venue": row["venue"],
                "source": row["source"],
                "url": row["url"],
                "pdf_url": row["pdf_url"],
                "doi": row["doi"],
                "arxiv_id": row["arxiv_id"],
                "variants": [],
            },
        )
        if _sort_key(row) > _sort_key(group):
            for key in (
                "title",
                "score",
                "display_score",
                "confidence_label",
                "rank",
                "year",
                "authors",
                "venue",
                "source",
                "url",
                "pdf_url",
                "doi",
                "arxiv_id",
            ):
                group[key] = row[key]
        if row["reason"] and not group["top_reason"]:
            group["top_reason"] = row["reason"]
        group["variants"].append(
            {
                "variant": row["variant"],
                "reason": row["reason"],
                "score": row["score"],
                "display_score": row["display_score"],
                "confidence_label": row["confidence_label"],
                "rank": row["rank"],
            }
        )

    groups = list(grouped.values())
    for group in groups:
        group["variants"].sort(key=_sort_key, reverse=True)
    groups.sort(key=_sort_key, reverse=True)
    return groups


def empty_response() -> dict[str, Any]:
    return dict(EMPTY_RECOMMENDATIONS)


def load_recommendation_artifact(root: Path, username: str, limit: int) -> dict[str, Any]:
    raw_path = latest_raw_file(root, username)
    if raw_path is None:
        return empty_response()

    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_response()

    run_at = parse_run_at(raw, raw_path)
    items: list[dict[str, Any]] = []
    variants = raw.get("variants") if isinstance(raw.get("variants"), dict) else {}
    for variant, papers in variants.items():
        if not isinstance(papers, list):
            continue
        for item in papers:
            if isinstance(item, dict):
                items.append(_paper_row(run_at, str(variant), item))

    items.sort(key=_sort_key, reverse=True)
    grouped_items = _group_items(items, run_at)
    return {
        "items": items[:limit],
        "grouped_items": grouped_items[:limit],
        "unread_count": len(grouped_items),
        "raw_count": len(items),
        "latest_run_at": run_at or None,
        "scoring_mode": safe_str(raw.get("scoring_mode")) or None,
        "score_stats": raw.get("score_stats") if isinstance(raw.get("score_stats"), dict) else {},
    }
