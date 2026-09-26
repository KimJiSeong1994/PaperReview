"""Deterministic local ranking. Metadata proxies are not scientific quality."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from src.recommendation_profiles import RecommendationProfile
from src.recommendations_artifacts import safe_str
from src.utils.paper_utils import generate_result_key

_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣_\-]{1,48}")
MMR_SHORTLIST_LIMIT = 200


@dataclass(frozen=True)
class RankedPaper:
    paper: dict[str, Any]
    score: float
    raw_score: float
    normalized_score: float
    matched_terms: list[str]
    score_breakdown: dict[str, float]
    reason_factors: list[str]
    slot_type: str
    explanation_confidence: str
    diversity_adjusted: bool = False
    similarity_penalty: float = 0.0
    token_features: frozenset[str] | None = None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, _safe_float(value)))


def minimum_score_for_mode(
    mode: str, *, v1_min_score: float, v2_min_score: float = 0.0
) -> float:
    """Independent explicit display-score thresholds; never rescale v1 into v2."""
    if mode not in {"v1", "v2"}:
        raise ValueError("unsupported recommendation mode")
    value = float(v2_min_score if mode == "v2" else v1_min_score)
    if not math.isfinite(value) or value < 0 or (mode == "v2" and value > 5):
        raise ValueError("invalid recommendation threshold")
    return value


def _component_overlap(
    terms: Counter[str], profile: Counter[str], *, denominator: float
) -> tuple[float, list[str]]:
    matched: list[str] = []
    total = 0.0
    for token, count in sorted(terms.items()):
        weight = _safe_float(profile.get(token, 0.0))
        if weight <= 0:
            continue
        total += math.log1p(weight) * min(count, 3)
        matched.append(token)
    matched.sort(key=lambda term: (-_safe_float(profile.get(term)), term))
    return _bounded(total / denominator), matched


def _paper_terms(paper: dict[str, Any]) -> Counter[str]:
    """Only bounded public bibliographic features; never query/source/notes."""
    chunks = [safe_str(paper.get("title"))[:512]]
    chunks.append(
        " ".join(_TOKEN_RE.findall(safe_str(paper.get("abstract"))[:8000])[:80])
    )
    categories = paper.get("categories")
    if isinstance(categories, list):
        chunks.extend(safe_str(value)[:128] for value in categories[:16])
    return Counter(
        token.strip("_-").lower()
        for token in _TOKEN_RE.findall(" ".join(chunks))
        if len(token.strip("_-")) >= 2 and not token.isdigit()
    )


def _year_value(paper: dict[str, Any]) -> int | None:
    for key in ("publication_date", "published_date", "year"):
        raw = safe_str(paper.get(key))
        if not raw:
            continue
        if re.fullmatch(r"\d{4}", raw):
            year = int(raw)
            return year if 1 <= year <= 9999 else None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).year
        except (ValueError, OverflowError):
            return None
    return None


def _freshness(
    paper: dict[str, Any], *, current_year: int, now: datetime | None = None
) -> float:
    if now is not None:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        for field in ("publication_date", "published_date"):
            raw = safe_str(paper.get(field))
            if not raw:
                continue
            try:
                published = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                if published > now:
                    return 0.0
            except (ValueError, OverflowError):
                pass
            break
    year = _year_value(paper)
    if year is None:
        return 0.15
    if year > current_year:
        return 0.0
    return _bounded(1.0 - min(current_year - year, 10) * 0.1)


def _metadata_completeness(paper: dict[str, Any]) -> float:
    return (
        sum(
            (
                bool(safe_str(paper.get("pdf_url"))),
                bool(safe_str(paper.get("doi")) or safe_str(paper.get("arxiv_id"))),
                bool(safe_str(paper.get("abstract"))),
                bool(_year_value(paper)),
            )
        )
        / 4.0
    )


def rank_paper_v2(
    paper: dict[str, Any],
    profile: RecommendationProfile,
    *,
    current_year: int,
    now: datetime | None = None,
    token_counts: Counter[str] | None = None,
) -> RankedPaper:
    terms = _paper_terms(paper) if token_counts is None else token_counts
    interest, _ = _component_overlap(terms, profile.positive_terms, denominator=12.0)
    intent, _ = _component_overlap(terms, profile.query_terms, denominator=6.0)
    negative, _ = _component_overlap(terms, profile.negative_terms, denominator=8.0)
    key = generate_result_key(paper)
    if key in profile.positive_paper_ids:
        interest = max(interest, 0.5)
    if key in profile.negative_paper_ids:
        negative = 1.0
    metadata = _metadata_completeness(paper)
    freshness = _freshness(paper, current_year=current_year, now=now)
    # Citation availability is a bounded bibliographic proxy, not validity.
    citations = max(0.0, _safe_float(paper.get("citation_count")))
    citation_proxy = _bounded(math.log1p(citations) / math.log1p(1000))
    raw = (
        0.55 * interest
        + 0.20 * intent
        + 0.15 * metadata
        + 0.05 * freshness
        + 0.05 * citation_proxy
        - 0.20 * negative
    )
    normalized = _bounded(raw)
    factors = []
    if interest > 0:
        factors.append("관심사 관련성")
    if intent > 0:
        factors.append("최근 탐색 관련성")
    if metadata >= 0.5:
        factors.append("서지정보 충실도")
    if freshness >= 0.7:
        factors.append("발행연도")
    if negative > 0:
        factors.append("명시적 선호 감점")
    slot = "recent_intent" if intent > 0 and intent >= interest else "core_interest"
    if interest == 0 and intent == 0:
        slot = "metadata_pick"
    return RankedPaper(
        paper=paper,
        score=round(normalized * 5, 3),
        raw_score=round(raw, 6),
        normalized_score=round(normalized, 6),
        matched_terms=[],
        score_breakdown={
            "interest_match": round(interest, 6),
            "recent_intent_match": round(intent, 6),
            "metadata_completeness": metadata,
            "freshness": round(freshness, 6),
            "citation_proxy": round(citation_proxy, 6),
            "negative_match": round(negative, 6),
        },
        reason_factors=factors,
        slot_type=slot,
        explanation_confidence="범주형 근거; 확률 아님",
        token_features=frozenset(terms),
    )


def reason_v2(ranked: RankedPaper, *, fallback_recent: bool) -> str:
    if fallback_recent:
        return "개인화 근거가 적어 공개 서지정보와 발행연도를 반영했습니다. 과학적 품질 평가는 아닙니다."
    if ranked.reason_factors:
        return f"{', '.join(ranked.reason_factors[:3])}를 반영했습니다."
    return "공개 서지정보를 기준으로 선택한 후보입니다. 과학적 품질 평가는 아닙니다."


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    return intersection / (len(a) + len(b) - intersection)


def mmr_rerank(
    ranked_items: list[RankedPaper],
    *,
    limit: int,
    lambda_relevance: float = 0.75,
    min_relevance_ratio: float = 0.60,
) -> list[RankedPaper]:
    """Post-policy shortlist only. Preserve MMR order, never refill below floor.

    Hard exclusions must already be applied by the caller and are never relaxed.
    Scores remain relevance scores, not MMR ranks or scientific probabilities.
    """
    if limit <= 0:
        return []
    relevance = _bounded(lambda_relevance)
    ratio = _bounded(min_relevance_ratio)
    valid = [
        item
        for item in ranked_items
        if all(
            math.isfinite(value)
            for value in (item.score, item.normalized_score, item.raw_score)
        )
    ]
    valid.sort(
        key=lambda item: (
            -item.normalized_score,
            -item.score,
            generate_result_key(item.paper),
        )
    )
    remaining: list[RankedPaper] = []
    identities: set[str] = set()
    for item in valid:
        key = generate_result_key(item.paper)
        if key not in identities:
            identities.add(key)
            remaining.append(item)
        if len(remaining) >= MMR_SHORTLIST_LIMIT:
            break
    if not remaining:
        return []
    floor = remaining[0].normalized_score * ratio
    remaining = [item for item in remaining if item.normalized_score >= floor]
    features = {
        id(item): item.token_features
        if item.token_features is not None
        else frozenset(_paper_terms(item.paper))
        for item in remaining
    }
    selected: list[RankedPaper] = []
    selected_features: list[frozenset[str]] = []
    while remaining and len(selected) < min(limit, MMR_SHORTLIST_LIMIT):
        penalties = {
            id(item): max(
                (_jaccard(features[id(item)], tokens) for tokens in selected_features),
                default=0.0,
            )
            for item in remaining
        }
        chosen = min(
            remaining,
            key=lambda item: (
                -(
                    relevance * item.normalized_score
                    - (1 - relevance) * penalties[id(item)]
                ),
                -item.normalized_score,
                penalties[id(item)],
                generate_result_key(item.paper),
            ),
        )
        penalty = penalties[id(chosen)]
        selected.append(
            replace(
                chosen,
                diversity_adjusted=penalty > 0,
                similarity_penalty=round(penalty, 6),
                slot_type="diversity" if penalty > 0.35 else chosen.slot_type,
            )
        )
        selected_features.append(features[id(chosen)])
        remaining.remove(chosen)
    return selected
