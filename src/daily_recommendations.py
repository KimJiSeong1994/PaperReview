"""Common local candidate ranking and the sole recommendation delivery publisher.

Source registrations are trusted operator configuration, never inferred from JSON.
This batch has no provider, embedding, LLM, API-server or deployment dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import resource
import sqlite3
import stat
import sys
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from filelock import FileLock

from src.events.feature_flags import PROFILE_RANKER_ENABLED, _db_path, is_enabled
from src.recommendation_candidates import (
    MAX_BYTES,
    CandidateSnapshot,
    CandidateValidationError,
    TrustedReceiverPolicy,
    load_candidate_snapshot,
    load_current_candidate_snapshot,
    make_candidate_snapshot,
    merge_candidate_pool,
    normalize_candidate,
)
from src.recommendation_profiles import (
    RecommendationProfile,
    _tokenize_terms,
    build_recommendation_profile,
    load_user_event_signals,
)
from src.recommendation_ranker import (
    RankedPaper,
    _component_overlap,
    _freshness,
    _metadata_completeness,
    _paper_terms,
    minimum_score_for_mode,
    mmr_rerank,
    rank_paper_v2,
    reason_v2,
)
from src.recommendation_state import RecommendationPolicy, RecommendationState
from src.recommendations_artifacts import (
    DELIVERY_SCHEMA,
    MAX_DELIVERY_BYTES,
    POLICY_VERSION,
    DeliveryValidationError,
    delivery_identifier,
    open_delivery_owner,
    parse_delivery_time,
    read_delivery,
    safe_str,
    validate_delivery,
)
from src.storage.soul_db import read_profile_readonly
from src.storage.user_db import AccountLifecycleError, UserDB
from src.storage.bookmark_db import bookmark_belongs_to_account
from src.utils.paper_utils import generate_result_key

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 12
DEFAULT_MIN_SCORE = 0.6
PROFILE_RANKER_GLOBAL_ENABLED = "PROFILE_RANKER_GLOBAL_ENABLED"
PROFILE_RANKER_ALLOWED_USERS = "PROFILE_RANKER_ALLOWED_USERS"
MAX_USERS = 100
MAX_CANDIDATES = 10000
MAX_SOURCE_FILES = 400
RANKER_VERSION = "common_local_v1"
_STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "using",
    "based",
    "towards",
    "through",
    "paper",
    "study",
    "analysis",
    "method",
    "methods",
    "model",
    "models",
    "data",
    "learning",
    "research",
    "this",
    "that",
    "into",
    "between",
    "under",
    "over",
    "via",
    "및",
    "으로",
    "에서",
    "대한",
    "논문",
    "연구",
    "분석",
}


class BatchBudgetError(RuntimeError):
    pass


class PolicyUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceRegistration:
    """Trusted deployment configuration; a payload cannot register its source."""

    relative_directory: str
    policy: TrustedReceiverPolicy

    def __post_init__(self) -> None:
        expected = (
            f"public/{self.policy.source}"
            if self.policy.scope == "public"
            else f"private/{self.policy.account_incarnation}"
        )
        if self.relative_directory != expected:
            raise ValueError("invalid_registration_directory")


DEFAULT_REGISTRATIONS = (
    SourceRegistration(
        "public/local_public",
        TrustedReceiverPolicy(
            "local_public", "public", "public-seeds-v1", public_source_qualified=True
        ),
    ),
)


@dataclass(frozen=True)
class BookmarkRecord:
    topic: str
    title: str
    papers: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PublicationResult:
    path: Path
    reused: bool
    item_count: int


def _json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value)).hexdigest()


def _run_datetime(run_at: str | None) -> datetime:
    if run_at is None:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ValueError("invalid_run_at") from None
    if parsed.tzinfo is None:
        raise ValueError("timezone_required")
    return parsed.astimezone(timezone.utc)


def _check_deadline(deadline: float, monotonic: Callable[[], float]) -> None:
    if monotonic() >= deadline:
        raise BatchBudgetError("budget_exhausted")


def _profile_ranker_per_user_override(username: str) -> bool | None:
    path = _db_path()
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT enabled FROM feature_flags WHERE flag=? AND username=?",
                (PROFILE_RANKER_ENABLED, username),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return bool(row[0]) if row is not None else None


def _profile_ranker_enabled(username: str) -> bool:
    global_gate = os.getenv(PROFILE_RANKER_GLOBAL_ENABLED, "").strip().lower() in {
        "true",
        "1",
        "yes",
    }
    allowed = {
        part.strip()
        for part in os.getenv(PROFILE_RANKER_ALLOWED_USERS, "").split(",")
        if part.strip()
    }
    override = _profile_ranker_per_user_override(username)
    if override is not None:
        return override
    try:
        return (username in allowed or global_gate) and is_enabled(
            PROFILE_RANKER_ENABLED, username=username
        )
    except (OSError, sqlite3.Error):
        return False


def load_bookmarks(
    bookmarks_db: Path | None,
    username: str,
    *,
    account_incarnation: str,
    legacy_event_cutoff: str | None = None,
) -> tuple[list[BookmarkRecord], str]:
    """Owner-bounded local read. Notes/reports are neither read nor exported."""
    if not isinstance(account_incarnation, str) or not account_incarnation:
        raise ValueError("invalid_principal")
    if bookmarks_db is None or not bookmarks_db.exists():
        return [], "unavailable"

    def belongs(owner: str, claim_type: str | None, claim: Any) -> int:
        record = {"username": owner}
        if claim_type is not None:
            record["account_incarnation"] = claim
        return int(
            bookmark_belongs_to_account(
                record,
                username=username,
                account_incarnation=account_incarnation,
                legacy_event_cutoff=legacy_event_cutoff,
            )
        )

    try:
        conn = sqlite3.connect(f"file:{bookmarks_db.resolve()}?mode=ro", uri=True)
        try:
            conn.create_function(
                "belongs_to_captured_account", 3, belongs, deterministic=True
            )
            rows = conn.execute(
                "SELECT substr(topic,1,512), substr(title,1,512), "
                "CASE WHEN length(papers)<=65536 THEN papers ELSE '[]' END "
                "FROM bookmarks WHERE username=? AND CASE "
                "WHEN metadata IS NULL THEN belongs_to_captured_account(username, NULL, NULL) "
                "WHEN json_valid(metadata) THEN CASE WHEN json_type(metadata)='object' THEN "
                "belongs_to_captured_account(username, json_type(metadata, '$.account_incarnation'), "
                "json_extract(metadata, '$.account_incarnation')) ELSE 0 END ELSE 0 END "
                "ORDER BY created_at DESC, id DESC LIMIT 500",
                (username,),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return [], "error"
    records = []
    for topic, title, raw in rows:
        try:
            papers = json.loads(raw or "[]")
        except (ValueError, TypeError):
            papers = []
        records.append(
            BookmarkRecord(
                safe_str(topic),
                safe_str(title),
                tuple(p for p in papers[:20] if isinstance(p, dict))
                if isinstance(papers, list)
                else (),
            )
        )
    return records, "ok"


def _bookmark_profile(bookmarks: list[BookmarkRecord]) -> Counter[str]:
    result: Counter[str] = Counter()
    for bookmark in bookmarks:
        for text, weight in ((bookmark.topic, 5), (bookmark.title, 4)):
            for token, count in _paper_terms({"title": text}).items():
                if token not in _STOPWORDS:
                    result[token] += count * weight
        for paper in bookmark.papers:
            for token, count in _paper_terms(
                {"title": safe_str(paper.get("title"))[:512]}
            ).items():
                if token not in _STOPWORDS:
                    result[token] += count * 7
    return result


def _safe_directory(root: Path, relative: str) -> Path:
    base = root.absolute()
    target = base / relative
    for part in (target, *target.parents):
        if part.is_symlink():
            raise CandidateValidationError("unsafe_path")
    return target


def _load_registration(
    root: Path,
    registration: SourceRegistration,
    *,
    final_root: Path,
    now: datetime,
    deadline: float,
    monotonic: Callable[[], float],
) -> tuple[CandidateSnapshot | None, str, Counter[str], Path | None]:
    rejected: Counter[str] = Counter()
    try:
        _check_deadline(deadline, monotonic)
        snapshot = load_current_candidate_snapshot(
            root,
            policy=registration.policy,
            now=now,
            final_root=final_root,
        )
        _check_deadline(deadline, monotonic)
        if snapshot is None:
            return None, "missing", rejected, None
        path = (
            root.absolute()
            / registration.relative_directory
            / (
                f"current-{registration.policy.source}-{registration.policy.provenance_id}.json"
            )
        )
        rejected.update(snapshot.rejected_counts)
        status = snapshot.acquisition_status
        if status == "ready" and (rejected or snapshot.degraded):
            status = "degraded"
        return snapshot, status, rejected, path
    except OSError:
        return None, "error", Counter({"source_io": 1}), None
    except CandidateValidationError as exc:
        return (
            None,
            "stale" if exc.code == "stale_snapshot" else "invalid",
            Counter({exc.code: 1}),
            None,
        )


def _policy_hash(policy: RecommendationPolicy) -> str:
    return _hash(
        {
            "incarnation": policy.incarnation,
            "hidden": sorted(policy.hidden),
            "already_seen": sorted(policy.already_seen),
            "seen": sorted(policy.seen),
            "interested": sorted(policy.interested),
            "topic_less": policy.topic_less,
            "recent_exposures": sorted(policy.recent_exposures),
        }
    )


def _profile_hash(profile: RecommendationProfile) -> str:
    return _hash(
        {
            "positive_terms": dict(profile.positive_terms),
            "negative_terms": dict(profile.negative_terms),
            "query_terms": dict(profile.query_terms),
            "positive_ids": sorted(profile.positive_paper_ids),
            "negative_ids": sorted(profile.negative_paper_ids),
            "event_count": profile.event_count,
            "event_status": profile.event_status,
        }
    )


def _cap_key(paper: dict[str, Any]) -> tuple:
    date = paper.get("publication_date") or f"{paper.get('year', 0):04d}-01-01"
    digits = int(date.replace("-", ""))
    return (-digits, -_metadata_completeness(paper), paper["canonical_key"])


def _score_paper(
    paper: dict[str, Any],
    profile: Counter[str],
    *,
    current_year: int,
    fallback_recent: bool,
    terms: Counter[str],
    now: datetime,
) -> float:
    """v1 bookmark overlap scale, distinct from the v2 display-score scale."""
    overlap = sum(
        math.log1p(profile[token]) * min(count, 3)
        for token, count in sorted(terms.items())
        if profile.get(token, 0) > 0
    )
    recency = _freshness(paper, current_year=current_year, now=now)
    metadata = (0.2 if paper.get("pdf_url") else 0.0) + (
        0.1 if paper.get("doi") or paper.get("arxiv_id") else 0.0
    )
    if fallback_recent:
        return recency + metadata
    return overlap + recency + metadata if overlap > 0 else recency * 0.25 + metadata


PROFILE_TERM_WEIGHT = 6.0  # positive-term weight of a research-profile interest of weight 1.0
PROFILE_KEYWORD_WEIGHT = 0.6  # profile keywords count like a 0.6-weight interest


def _use_research_profile() -> bool:
    """RECOMMEND_USE_PROFILE (default on) lets the user's research profile steer ranking."""
    return os.getenv("RECOMMEND_USE_PROFILE", "1").strip().lower() not in {"0", "false", "off", "no"}


def research_profile_terms(research: dict[str, Any] | None) -> list[tuple[str, tuple[str, ...], float]]:
    """(label, tokens, weight) from a research profile's interests (weight 0–1) and keywords."""
    if not isinstance(research, dict):
        return []
    out = []
    for item in research.get("interests") or []:
        if isinstance(item, dict) and isinstance(item.get("label"), str):
            weight = item.get("weight")
            weight = min(1.0, max(0.0, float(weight))) if isinstance(weight, (int, float)) else 0.5
            out.append((item["label"], _tokenize_terms((item["label"],)), weight))
    for keyword in research.get("keywords") or []:
        if isinstance(keyword, str):
            out.append((keyword, _tokenize_terms((keyword,)), PROFILE_KEYWORD_WEIGHT))
    return [entry for entry in out if entry[1]]


def apply_research_profile(
    profile: RecommendationProfile, v1_terms: Counter[str], terms: list[tuple[str, tuple[str, ...], float]]
) -> None:
    """Add profile terms as positive interests for both rankers (v2 profile and v1 term counter)."""
    for _, tokens, weight in terms:
        for token in tokens:
            profile.positive_terms[token] += PROFILE_TERM_WEIGHT * weight
            v1_terms[token] += PROFILE_TERM_WEIGHT * weight


_RANKED_FIELDS = ("final_rank", "score", "reason", "score_breakdown")
# Profile-keyword candidates: recent arXiv papers per account, as a private owner_local
# snapshot (the existing per-owner source; no new source in the delivery contract).
PROFILE_PROVENANCE = "research-profile-v1"
MAX_PROFILE_KEYWORDS = 3
PROFILE_RESULTS_PER_KEYWORD = 10
MAX_PROFILE_CANDIDATES = 30
PROFILE_FETCH_SECONDS = 60.0  # total network time per run, across accounts
_ENGLISH_LABEL = re.compile(r"[A-Za-z][A-Za-z0-9 +./-]*")


def profile_keywords(research: dict[str, Any] | None) -> list[str]:
    """≤3 English search phrases: heaviest English interest labels first, then profile keywords."""
    if not isinstance(research, dict):
        return []
    interests = sorted(
        (i for i in research.get("interests") or [] if isinstance(i, dict) and isinstance(i.get("label"), str)),
        key=lambda i: i.get("weight") if isinstance(i.get("weight"), (int, float)) else 0, reverse=True,
    )
    labels = [i["label"].strip() for i in interests if _ENGLISH_LABEL.fullmatch(i["label"].strip())]
    keywords = [k.strip() for k in research.get("keywords") or [] if isinstance(k, str) and k.strip()]
    return list(dict.fromkeys(labels + keywords))[:MAX_PROFILE_KEYWORDS]


def _arxiv_recent(keyword: str, deadline: float) -> list[dict[str, Any]]:
    """Newest arXiv papers for *keyword* with the search pipeline's own client."""
    from src.collector.paper.arxiv_searcher import ArxivSearcher

    return ArxivSearcher().search(
        keyword, max_results=PROFILE_RESULTS_PER_KEYWORD, sort_by="submittedDate", deadline=deadline
    )


def _as_candidate(paper: dict[str, Any]) -> dict[str, Any]:
    """arXiv collector record → candidate record fields (normalize_candidate validates the rest)."""
    out = {key: paper.get(key) for key in ("title", "abstract", "authors", "categories", "pdf_url", "arxiv_id")}
    out["publication_date"] = paper.get("published_date") or None
    if paper.get("doi"):
        out["doi"] = paper["doi"]
    if paper.get("url"):
        out["url"] = paper["url"]
    return {key: value for key, value in out.items() if value}


def fetch_profile_candidates(
    keywords: list[str],
    *,
    now: datetime,
    deadline: float,
    monotonic: Callable[[], float],
    fetch: Callable[[str, float], list[dict[str, Any]]] = _arxiv_recent,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Recent (year ≥ now−1) candidates for the keywords, ≤30, and canonical_key → keyword.

    Each keyword stops at *deadline*; any provider failure skips that keyword.
    """
    raws: list[dict[str, Any]] = []
    keyword_of: dict[str, str] = {}
    for keyword in keywords:
        if monotonic() >= deadline or len(raws) >= MAX_PROFILE_CANDIDATES:
            break
        try:
            papers = fetch(keyword, deadline)
        except Exception as exc:  # network, parsing — recommendations go on without them
            logger.warning("research-profile candidate fetch skipped: %s", type(exc).__name__)
            continue
        for paper in papers or []:
            raw = _as_candidate(paper)
            try:
                record = normalize_candidate(raw)
            except CandidateValidationError:
                continue
            if record.metadata.get("year", 0) < now.year - 1 or record.canonical_key in keyword_of:
                continue
            keyword_of[record.canonical_key] = keyword
            raws.append(raw)
            if len(raws) >= MAX_PROFILE_CANDIDATES:
                break
    return raws, keyword_of


def tag_profile_reasons(
    items: list[dict[str, Any]],
    terms: list[tuple[str, tuple[str, ...], float]],
    feature_cache: dict[str, Counter[str]],
    fetched: dict[str, str] | None = None,
) -> None:
    """Prefix "연구 프로필: <interest>" to the reason of items a profile term matched (heaviest match wins),
    or "연구 프로필: <keyword> · 최근 arXiv" to candidates the profile keywords fetched.

    Reuses the ranking pass's per-paper token cache instead of re-tokenizing.
    """
    fetched = fetched or {}
    if not terms and not fetched:
        return
    for item in items:
        if item.get("canonical_key") in fetched:
            keyword = fetched[item["canonical_key"]]
            item["reason"] = f"연구 프로필: {keyword} · 최근 arXiv · {item.get('reason', '')}"[:512]
            item["score_breakdown"] = {**item.get("score_breakdown", {}), "research_profile": 1.0}
            continue
        paper = {k: v for k, v in item.items() if k not in _RANKED_FIELDS}
        paper_terms = feature_cache.get(_hash(paper)) or _paper_terms(paper)
        matches = [(weight, label) for label, tokens, weight in terms if any(t in paper_terms for t in tokens)]
        if matches:
            weight, label = max(matches)
            item["reason"] = f"연구 프로필: {label} · {item.get('reason', '')}"[:512]
            item["score_breakdown"] = {**item.get("score_breakdown", {}), "research_profile": round(weight, 6)}


def recommend_for_user(
    papers: list[dict[str, Any]],
    *,
    profile: RecommendationProfile,
    v1_terms: Counter[str],
    policy: RecommendationPolicy,
    run_id: str,
    now: datetime,
    use_profile_ranker: bool,
    feature_cache: dict[str, Counter[str]],
    limit: int = DEFAULT_LIMIT,
    min_score: float = DEFAULT_MIN_SCORE,
    v2_min_score: float = 0.0,
    deadline: float = math.inf,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[list[dict], str, bool]:
    """Rank already validated records, with common hard policy and post-policy cap."""
    excluded = policy.excluded_for_run(run_id)
    eligible = sorted(
        (paper for paper in papers if paper["canonical_key"] not in excluded),
        key=_cap_key,
    )[:MAX_CANDIDATES]
    interest = (
        bool(
            profile.positive_terms or profile.query_terms or profile.positive_paper_ids
        )
        if use_profile_ranker
        else bool(v1_terms or profile.positive_paper_ids)
    )
    metadata_only = not interest
    mode = "v2" if use_profile_ranker and interest else "v1" if interest else "metadata"
    threshold = minimum_score_for_mode(
        "v2" if use_profile_ranker else "v1",
        v1_min_score=min_score,
        v2_min_score=v2_min_score,
    )
    ranked: list[RankedPaper] = []
    for paper in eligible:
        _check_deadline(deadline, monotonic)
        cache_key = _hash(paper)
        if cache_key not in feature_cache:
            feature_cache[cache_key] = _paper_terms(paper)
        terms = feature_cache[cache_key]
        if use_profile_ranker:
            item = rank_paper_v2(
                paper, profile, current_year=now.year, now=now, token_counts=terms
            )
        else:
            score = _score_paper(
                paper,
                v1_terms,
                current_year=now.year,
                fallback_recent=metadata_only,
                terms=terms,
                now=now,
            )
            if generate_result_key(paper) in profile.positive_paper_ids:
                score += 1.0
            negative, _ = _component_overlap(
                terms, profile.negative_terms, denominator=8.0
            )
            if generate_result_key(paper) in profile.negative_paper_ids:
                negative = 1.0
            score = max(0.0, score - 0.5 * negative)
            item = RankedPaper(
                paper,
                round(score, 6),
                round(score, 6),
                0.0,
                [],
                {
                    "content_relevance_proxy": round(score, 6),
                    "negative_match": negative,
                },
                ["공개 서지정보" if metadata_only else "관심사 관련성"],
                "metadata_pick" if metadata_only else "core_interest",
                "범주형 근거; 확률 아님",
                token_features=frozenset(terms),
            )
        if metadata_only or item.score >= threshold:
            ranked.append(item)
    if not use_profile_ranker and ranked:
        top = max(item.score for item in ranked)
        ranked = [
            replace(item, normalized_score=item.score / top if top > 0 else 0.0)
            for item in ranked
        ]
    _check_deadline(deadline, monotonic)
    selected = mmr_rerank(ranked, limit=limit)
    _check_deadline(deadline, monotonic)
    items = []
    for rank, item in enumerate(selected, 1):
        items.append(
            {
                **item.paper,
                "final_rank": rank,
                "score": item.score,
                "reason": reason_v2(item, fallback_recent=metadata_only),
                "score_breakdown": item.score_breakdown,
            }
        )
    return items, mode, metadata_only


def write_artifact(
    root: Path,
    username: str,
    artifact: dict[str, Any],
    *,
    users: UserDB,
    state: RecommendationState,
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> PublicationResult:
    """Recheck current policy under authority barrier; atomic owner-dir publication."""
    incarnation = delivery_identifier(artifact["account_incarnation"])
    run_id = delivery_identifier(artifact["run_id"])
    validate_delivery(artifact, incarnation=incarnation, now=wall_clock())
    owner_fd = open_delivery_owner(root, incarnation, create=True)
    temporary = f".delivery-{uuid.uuid4().hex}.tmp"
    fd = None
    try:
        _check_deadline(deadline, monotonic)
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=owner_fd,
        )
        with users.account_guard(username, incarnation):
            try:
                current = state.policy(incarnation, now=wall_clock())
            except (OSError, sqlite3.Error, ValueError):
                raise PolicyUnavailableError("policy_unavailable") from None
            excluded = current.excluded_for_run(run_id)
            items = [
                item
                for item in artifact["items"]
                if item["canonical_key"] not in excluded
            ]
            final = {**artifact, "items": items, "policy_hash": _policy_hash(current)}
            final["status"] = (
                "empty"
                if not items
                else "degraded"
                if final["degraded_reasons"]
                else "ready"
            )
            if not items and "no_eligible_candidates" not in final["degraded_reasons"]:
                final["degraded_reasons"] = [
                    *final["degraded_reasons"],
                    "no_eligible_candidates",
                ]
            final = validate_delivery(final, incarnation=incarnation, now=wall_clock())
            try:
                existing = read_delivery(
                    root, incarnation, now=wall_clock(), run_id=run_id
                )
            except (OSError, DeliveryValidationError):
                existing = None
            match_fields = (
                "schema",
                "producer",
                "account_incarnation",
                "run_id",
                "run_at",
                "cutoff",
                "input_manifest_hash",
                "config_hash",
                "code_hash",
                "policy_hash",
                "items",
                "scoring_mode",
                "status",
                "degraded_reasons",
                "source_statuses",
                "profile",
            )
            _check_deadline(deadline, monotonic)
            if existing is not None and all(
                existing.get(key) == final.get(key) for key in match_fields
            ):
                return PublicationResult(
                    root / incarnation / f"{run_id}.json", True, len(items)
                )
            content = _json(final) + b"\n"
            if len(content) > MAX_DELIVERY_BYTES:
                raise DeliveryValidationError("size_limit")
            with os.fdopen(fd, "wb") as handle:
                fd = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            _check_deadline(deadline, monotonic)
            os.replace(
                temporary, f"{run_id}.json", src_dir_fd=owner_fd, dst_dir_fd=owner_fd
            )
            os.fsync(owner_fd)
        return PublicationResult(
            root / incarnation / f"{run_id}.json", False, len(items)
        )
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=owner_fd)
        except FileNotFoundError:
            pass
        os.close(owner_fd)


def _prune_deliveries(
    root: Path,
    incarnation: str,
    *,
    current_run: str,
    now: datetime,
    deadline: float,
    monotonic: Callable[[], float],
) -> None:
    """Only validated common deliveries in this owner directory; no legacy data."""
    owner_fd = open_delivery_owner(root, incarnation)
    try:
        latest = read_delivery(root, incarnation, now=now)
        protected_runs = {current_run, latest["run_id"] if latest else current_run}
        with os.scandir(owner_fd) as entries:
            names = [
                entry.name
                for _, entry in zip(range(400), entries)
                if entry.name.endswith(".json")
            ]
        for name in names:
            _check_deadline(deadline, monotonic)
            if name[:-5] in protected_runs:
                continue
            try:
                run_id = delivery_identifier(name[:-5])
                before = os.stat(name, dir_fd=owner_fd, follow_symlinks=False)
                if not stat.S_ISREG(before.st_mode):
                    continue
                raw = read_delivery(root, incarnation, now=now, run_id=run_id)
                if raw and now - parse_delivery_time(raw["run_at"]) > timedelta(
                    days=30
                ):
                    after = os.stat(name, dir_fd=owner_fd, follow_symlinks=False)
                    if (before.st_ino, before.st_dev) == (after.st_ino, after.st_dev):
                        os.unlink(name, dir_fd=owner_fd)
            except (OSError, DeliveryValidationError):
                continue
    finally:
        os.close(owner_fd)


def _prune_private_staging(
    root: Path,
    registrations: tuple[SourceRegistration, ...],
    *,
    incarnation: str,
    final_root: Path,
    keep: set[Path],
    now: datetime,
    deadline: float,
    monotonic: Callable[[], float],
) -> None:
    for registration in registrations:
        if (
            registration.policy.scope != "private"
            or registration.policy.account_incarnation != incarnation
        ):
            continue
        directory = _safe_directory(root, registration.relative_directory)
        if not directory.exists():
            continue
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with os.scandir(directory_fd) as entries:
                names = [
                    entry.name
                    for _, entry in zip(range(MAX_SOURCE_FILES), entries)
                    if entry.name.endswith(".json")
                ]
            for name in names:
                _check_deadline(deadline, monotonic)
                path = directory / name
                if path in keep or name.endswith(".receipt.json"):
                    continue
                try:
                    fd = os.open(
                        name,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                        dir_fd=directory_fd,
                    )
                    with os.fdopen(fd, "rb") as handle:
                        before = os.fstat(handle.fileno())
                        if (
                            not stat.S_ISREG(before.st_mode)
                            or before.st_size > MAX_BYTES
                        ):
                            continue
                        raw = json.loads(handle.read(MAX_BYTES + 1))
                    if not isinstance(raw, dict):
                        continue
                    collected = parse_delivery_time(raw.get("collected_at"))
                    if now - collected <= timedelta(days=7):
                        continue
                    load_candidate_snapshot(
                        path,
                        root=root,
                        policy=registration.policy,
                        now=collected,
                        final_root=final_root,
                    )
                    after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if (before.st_ino, before.st_dev) == (after.st_ino, after.st_dev):
                        os.unlink(name, dir_fd=directory_fd)
                except (OSError, ValueError):
                    continue
        finally:
            os.close(directory_fd)


def _code_hash() -> str:
    root = Path(__file__).parent
    files = (
        "daily_recommendations.py",
        "recommendation_profiles.py",
        "recommendation_ranker.py",
        "recommendation_candidates.py",
        "recommendation_state.py",
        "recommendations_artifacts.py",
        "storage/user_db.py",
        "storage/bookmark_db.py",
        "utils/paper_utils.py",
        "utils/secure_directory.py",
    )
    digest = hashlib.sha256()
    for name in files:
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def generate_daily_recommendations(
    *,
    users_db: Path,
    candidate_root: Path,
    events_db: Path,
    artifacts_dir: Path,
    bookmarks_db: Path | None = None,
    souls_db: Path | None = None,
    profile_fetch: Callable[[str, float], list[dict[str, Any]]] | None = None,
    registrations: Iterable[SourceRegistration] = DEFAULT_REGISTRATIONS,
    limit: int = DEFAULT_LIMIT,
    min_score: float = DEFAULT_MIN_SCORE,
    v2_min_score: float = 0.0,
    usernames: Iterable[str] | None = None,
    run_at: str | None = None,
    compute_seconds: float = 600,
    job_seconds: float = 900,
    monotonic: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    """Sequential, leased, bounded batch. Failure details are categorical, not raw exceptions."""
    if (
        not 1 <= limit <= 12
        or not 0 < compute_seconds <= 600
        or not 0 < job_seconds <= 900
    ):
        raise ValueError("invalid_budget")
    minimum_score_for_mode("v1", v1_min_score=min_score)
    minimum_score_for_mode("v2", v1_min_score=min_score, v2_min_score=v2_min_score)
    now = _run_datetime(run_at)
    if now > wall_clock():
        raise ValueError("future_run_at")
    started = monotonic()
    compute_deadline, job_deadline = (
        started + min(compute_seconds, job_seconds),
        started + job_seconds,
    )
    run_id = now.strftime("%Y%m%dT%H%M%S") + f"-{now.microsecond:06d}"
    profile_fetch_deadline = started + PROFILE_FETCH_SECONDS
    registrations = tuple(registrations)
    if len(registrations) > 100:
        raise ValueError("registration_limit")
    registration_keys = [
        (entry.policy.source, entry.policy.scope, entry.policy.account_incarnation)
        for entry in registrations
    ]
    if len(set(registration_keys)) != len(registration_keys):
        raise ValueError("duplicate_source_registration")
    requested = set(usernames or ())
    users_db = Path(users_db)
    if not users_db.is_file():
        raise AccountLifecycleError("authority_unavailable")
    for part in (users_db, *users_db.absolute().parents):
        if part.is_symlink():
            raise AccountLifecycleError("unsafe_authority_path")
    lease = users_db.absolute().parent / ".recommendations-batch.lock"
    if lease.is_symlink():
        raise AccountLifecycleError("unsafe_batch_lease")
    with FileLock(str(lease), timeout=0):
        users = UserDB(users_db)
        all_users = users.get_all()
        selected_users = [
            (name, record)
            for name, record in sorted(all_users.items())
            if not requested or name in requested
        ]
        events_available = events_db.exists()
        flags = {
            name: _profile_ranker_enabled(name)
            for name, _ in selected_users[:MAX_USERS]
        }
        config = {
            "limit": limit,
            "min_score": min_score,
            "v2_min_score": v2_min_score,
            "max_users": MAX_USERS,
            "max_candidates": MAX_CANDIDATES,
            "mmr_shortlist": 200,
            "compute_seconds": compute_seconds,
            "job_seconds": job_seconds,
            "registrations": [asdict(registration) for registration in registrations],
            "flags_hash": _hash(flags),
            "policy_version": POLICY_VERSION,
        }
        config_hash, code_hash = _hash(config), _code_hash()
        source_cache = {}
        feature_cache: dict[str, Counter[str]] = {}
        summary: dict[str, Any] = {
            "run_id": run_id,
            "run_at": now.isoformat(),
            "cutoff": now.isoformat(),
            "config_hash": config_hash,
            "code_hash": code_hash,
            "users_seen": len(selected_users),
            "rank_success": 0,
            "publish_success": 0,
            "reused": 0,
            "artifacts_written": [],
            "failures": [],
            "unknown_requested_count": len(requested - set(all_users)),
            "provider_calls": 0,
            "paid_calls": 0,
            "source_qualification": "registered_contract_only_operational_evidence_not_verified",
        }
        try:
            state = RecommendationState(events_db, authority=users)
        except (OSError, sqlite3.Error, ValueError):
            summary["failures"] = [
                {
                    "account_incarnation": record["account_incarnation"],
                    "reason": "policy_unavailable",
                }
                for _, record in selected_users
            ]
            summary["elapsed_seconds"] = max(0.0, monotonic() - started)
            return summary
        for index, (username, record) in enumerate(selected_users):
            incarnation = record["account_incarnation"]
            if index >= MAX_USERS:
                summary["failures"].append(
                    {"account_incarnation": incarnation, "reason": "user_cap"}
                )
                continue
            stage = "authority_unavailable"
            user_started = monotonic()
            try:
                _check_deadline(compute_deadline, monotonic)
                with users.account_guard(username, incarnation):
                    stage = "policy_unavailable"
                    policy = state.policy(incarnation, now=wall_clock())
                    bookmarks, bookmark_status = load_bookmarks(
                        bookmarks_db,
                        username,
                        account_incarnation=incarnation,
                        legacy_event_cutoff=record.get("legacy_event_cutoff"),
                    )
                stage = "source_invalid"
                snapshots, keep = [], set()
                statuses = {
                    "local_public": "disabled",
                    "owner_local": "disabled",
                    "openclaw": "disabled",
                }
                rejected: Counter[str] = Counter()
                manifests = []
                for registration in registrations:
                    if (
                        registration.policy.scope == "private"
                        and registration.policy.account_incarnation != incarnation
                    ):
                        continue
                    cache_key = _hash(asdict(registration))
                    if cache_key not in source_cache:
                        source_cache[cache_key] = _load_registration(
                            candidate_root,
                            registration,
                            final_root=artifacts_dir,
                            now=now,
                            deadline=compute_deadline,
                            monotonic=monotonic,
                        )
                    snapshot, status, rejects, path = source_cache[cache_key]
                    previous_status = statuses[registration.policy.source]
                    statuses[registration.policy.source] = (
                        "degraded"
                        if previous_status != "disabled" and previous_status != status
                        else status
                    )
                    rejected.update(rejects)
                    if snapshot is not None:
                        snapshots.append(snapshot)
                        keep.add(path)
                        manifests.append(
                            {
                                "checksum": snapshot.checksum,
                                "source": snapshot.source,
                                "scope": snapshot.scope,
                                "collected_at": snapshot.collected_at,
                                "provenance_id": snapshot.provenance_id,
                                "acquisition_status": snapshot.acquisition_status,
                                "acquisition_reasons": list(
                                    snapshot.acquisition_reasons
                                ),
                            }
                        )
                research = (
                    read_profile_readonly(souls_db, username, incarnation)
                    if souls_db is not None and _use_research_profile()
                    else None
                )
                fetched: dict[str, str] = {}
                keywords = profile_keywords(research)
                if keywords and monotonic() < profile_fetch_deadline:
                    raws, fetched = fetch_profile_candidates(
                        keywords,
                        now=now,
                        deadline=min(profile_fetch_deadline, compute_deadline),
                        monotonic=monotonic,
                        fetch=profile_fetch or _arxiv_recent,
                    )
                    if raws:
                        try:
                            snapshots.append(make_candidate_snapshot(
                                raws,
                                policy=TrustedReceiverPolicy(
                                    "owner_local", "private", PROFILE_PROVENANCE, account_incarnation=incarnation
                                ),
                                source_run_id="research-profile",
                                collected_at=now,
                                now=now,
                            ))
                        except CandidateValidationError:
                            fetched = {}
                pool = merge_candidate_pool(snapshots, account_incarnation=incarnation)
                papers = [entry.to_paper() for entry in pool.records]
                public_papers = {
                    entry.canonical_key: entry.to_paper()
                    for entry in merge_candidate_pool(
                        snapshots, public_only=True
                    ).records
                }
                rejected.update(pool.rejected_counts)
                stage = "events_error"
                legacy_before = (
                    _run_datetime(record["legacy_event_cutoff"])
                    if record.get("legacy_event_cutoff")
                    else None
                )
                events = load_user_event_signals(
                    events_db if events_available else None,
                    username,
                    now=now,
                    account_incarnation=incarnation,
                    legacy_before=legacy_before,
                )
                reasons = []
                if any(
                    snapshot.acquisition_status == "disabled" for snapshot in snapshots
                ):
                    reasons.append("source_disabled")
                if any(
                    snapshot.acquisition_status == "error" for snapshot in snapshots
                ):
                    reasons.append("source_error")
                if any(
                    snapshot.acquisition_status == "degraded" for snapshot in snapshots
                ):
                    reasons.append("limited_coverage")
                if events.status != "ok":
                    reasons.append("events_" + events.status)
                if bookmark_status != "ok":
                    reasons.append("limited_coverage")
                for status in statuses.values():
                    reason = {
                        "missing": "source_missing",
                        "invalid": "source_invalid",
                        "stale": "source_stale",
                        "error": "source_error",
                        "degraded": "limited_coverage",
                    }.get(status)
                    if reason and reason not in reasons:
                        reasons.append(reason)
                terms = _bookmark_profile(bookmarks)
                interested = [
                    public_papers[key]
                    for key in sorted(policy.interested)
                    if key in public_papers
                ]
                topic_less = [
                    (public_papers[key], _run_datetime(timestamp))
                    for key, timestamp in sorted(policy.topic_less.items())
                    if key in public_papers
                ]
                durable = build_recommendation_profile(
                    terms,
                    (),
                    now=now,
                    interested_papers=interested,
                    topic_less_papers=topic_less,
                )
                profile = build_recommendation_profile(
                    terms,
                    events.signals,
                    now=now,
                    event_status=events.status,
                    interested_papers=interested,
                    topic_less_papers=topic_less,
                )
                # Unresolved ID-only preferences still affect that exact candidate;
                # bibliographic topic transfer is restricted to public metadata.
                profile.positive_paper_ids.update(policy.interested)
                profile.negative_paper_ids.update(policy.topic_less)
                # The research profile (derived from the user's soul) is one more interest signal.
                research_terms = research_profile_terms(research)
                apply_research_profile(profile, durable.positive_terms, research_terms)
                feature_inputs = {
                    "bookmark_terms": dict(terms),
                    "bookmark_count": len(bookmarks),
                    "research_profile_terms": [[label, list(tokens), weight] for label, tokens, weight in research_terms],
                    "events": [
                        {**asdict(signal), "created_at": signal.created_at.isoformat()}
                        for signal in events.signals
                    ],
                }
                input_hash = _hash(
                    {
                        "sources": manifests,
                        "pool": pool.checksum,
                        "feature_inputs_hash": _hash(feature_inputs),
                        "source_statuses": statuses,
                        "reject_counts": dict(rejected),
                        "features_hash": _profile_hash(profile),
                        "v1_terms": durable.positive_terms,
                        "policy": _policy_hash(policy),
                        "event_status": events.status,
                        "bookmark_status": bookmark_status,
                    }
                )
                stage = "ranker_error"
                try:
                    items, mode, metadata_only = recommend_for_user(
                        papers,
                        profile=profile,
                        v1_terms=durable.positive_terms,
                        policy=policy,
                        run_id=run_id,
                        now=now,
                        use_profile_ranker=flags[username],
                        feature_cache=feature_cache,
                        limit=limit,
                        min_score=min_score,
                        v2_min_score=v2_min_score,
                        deadline=compute_deadline,
                        monotonic=monotonic,
                    )
                except BatchBudgetError:
                    raise
                except (ValueError, TypeError, KeyError, ArithmeticError, RuntimeError):
                    reasons.append("ranker_error")
                    items, mode, metadata_only = recommend_for_user(
                        papers,
                        profile=profile,
                        v1_terms=durable.positive_terms,
                        policy=policy,
                        run_id=run_id,
                        now=now,
                        use_profile_ranker=False,
                        feature_cache=feature_cache,
                        limit=limit,
                        min_score=min_score,
                        v2_min_score=v2_min_score,
                        deadline=compute_deadline,
                        monotonic=monotonic,
                    )
                    if mode != "metadata":
                        mode = "v1_fallback"
                tag_profile_reasons(items, research_terms, feature_cache, fetched)
                summary["rank_success"] += 1
                if not items:
                    reasons.append(
                        "no_candidates" if not papers else "no_eligible_candidates"
                    )
                excluded = policy.excluded_for_run(run_id)
                peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                artifact = {
                    "schema": DELIVERY_SCHEMA,
                    "producer": "common_local",
                    "account_incarnation": incarnation,
                    "run_id": run_id,
                    "run_at": now.isoformat(),
                    "cutoff": now.isoformat(),
                    "policy_version": POLICY_VERSION,
                    "policy_hash": _policy_hash(policy),
                    "ranker_version": RANKER_VERSION,
                    "scoring_mode": mode,
                    "status": "empty"
                    if not items
                    else "degraded"
                    if reasons
                    else "ready",
                    "degraded_reasons": sorted(set(reasons)),
                    "source_statuses": statuses,
                    "code_hash": code_hash,
                    "config_hash": config_hash,
                    "input_manifest_hash": input_hash,
                    "input_manifest": manifests,
                    "items": items,
                    "personalization_state": "metadata_only"
                    if metadata_only
                    else "personalized",
                    "profile": profile.public_summary(
                        bookmark_count=len(bookmarks), fallback_recent=metadata_only
                    ),
                    "metrics": {
                        "candidate_count": len(papers),
                        "eligible_count": sum(
                            p["canonical_key"] not in excluded for p in papers
                        ),
                        "reject_counts": dict(rejected),
                        "provider_calls": 0,
                        "paid_calls": 0,
                        "process_peak_rss_bytes": int(
                            peak if sys.platform == "darwin" else peak * 1024
                        ),
                        "rank_seconds": max(0.0, monotonic() - user_started),
                    },
                    "source_qualification": summary["source_qualification"],
                }
                stage = "publication_failed"
                publication = write_artifact(
                    artifacts_dir,
                    username,
                    artifact,
                    users=users,
                    state=state,
                    deadline=job_deadline,
                    monotonic=monotonic,
                    wall_clock=wall_clock,
                )
                if publication.reused:
                    summary["reused"] += 1
                else:
                    summary["publish_success"] += 1
                    summary["artifacts_written"].append(str(publication.path))
                stage = "retention_failed"
                _check_deadline(job_deadline, monotonic)
                _prune_deliveries(
                    artifacts_dir,
                    incarnation,
                    current_run=run_id,
                    now=wall_clock(),
                    deadline=job_deadline,
                    monotonic=monotonic,
                )
                _prune_private_staging(
                    candidate_root,
                    registrations,
                    incarnation=incarnation,
                    final_root=artifacts_dir,
                    keep=keep,
                    now=wall_clock(),
                    deadline=job_deadline,
                    monotonic=monotonic,
                )
            except BatchBudgetError:
                summary["failures"].append(
                    {"account_incarnation": incarnation, "reason": "budget_exhausted"}
                )
            except PolicyUnavailableError:
                summary["failures"].append(
                    {"account_incarnation": incarnation, "reason": "policy_unavailable"}
                )
            except AccountLifecycleError:
                summary["failures"].append(
                    {
                        "account_incarnation": incarnation,
                        "reason": "authority_unavailable",
                    }
                )
            except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
                summary["failures"].append(
                    {"account_incarnation": incarnation, "reason": stage}
                )
        if monotonic() < job_deadline:
            try:
                state.prune(now=wall_clock())
            except (OSError, sqlite3.Error, ValueError):
                summary["failures"].append({"reason": "state_retention_failed"})
        summary["elapsed_seconds"] = max(0.0, monotonic() - started)
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        summary["process_peak_rss_bytes"] = int(
            peak if sys.platform == "darwin" else peak * 1024
        )
        return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rank registered candidates and publish common local deliveries."
    )
    parser.add_argument(
        "--candidate-root", type=Path, default=Path("data/recommendation-candidates")
    )
    parser.add_argument("--users-db", type=Path, default=Path("data/users.db"))
    parser.add_argument("--events-db", type=Path, default=Path("data/events.db"))
    parser.add_argument("--bookmarks-db", type=Path, default=Path("data/bookmarks.db"))
    parser.add_argument("--souls-db", type=Path, default=Path("data/souls.db"), help="read-only research profiles")
    parser.add_argument(
        "--artifacts-dir", type=Path, default=Path("data/recommendations")
    )
    parser.add_argument("--run-at")
    parser.add_argument("--user", action="append", dest="users")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--v2-min-score", type=float, default=0.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = generate_daily_recommendations(
        users_db=args.users_db,
        candidate_root=args.candidate_root,
        events_db=args.events_db,
        bookmarks_db=args.bookmarks_db,
        souls_db=args.souls_db,
        artifacts_dir=args.artifacts_dir,
        run_at=args.run_at,
        usernames=args.users,
        limit=args.limit,
        min_score=args.min_score,
        v2_min_score=args.v2_min_score,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
