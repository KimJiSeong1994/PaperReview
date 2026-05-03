"""Deterministic v2 paper ranker with bounded score components."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, replace
from typing import Any

from src.recommendation_profiles import RecommendationProfile
from src.recommendations_artifacts import paper_id, safe_str


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


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _component_overlap(terms: Counter[str], profile: Counter[str], *, denominator: float) -> tuple[float, list[str]]:
    matched: list[str] = []
    total = 0.0
    for token, count in terms.items():
        weight = profile.get(token, 0.0)
        if weight <= 0:
            continue
        total += math.log1p(weight) * min(count, 3)
        matched.append(token)
    matched.sort(key=lambda term: profile.get(term, 0.0), reverse=True)
    return _bounded(total / denominator), matched


def _paper_terms(paper: dict[str, Any]) -> Counter[str]:
    # Reuse daily_recommendations tokenizer indirectly would create an import
    # cycle, so keep this field-capped and small here.
    import re

    token_re = re.compile(r"[A-Za-z0-9가-힣]{2,}")
    chunks: list[str] = [safe_str(paper.get("title"))]
    abstract_tokens = token_re.findall(safe_str(paper.get("abstract")))[:80]
    chunks.append(" ".join(abstract_tokens))
    for key in ("search_query", "related_query", "source"):
        chunks.append(safe_str(paper.get(key)))
    for value in paper.get("categories") if isinstance(paper.get("categories"), list) else []:
        chunks.append(safe_str(value))
    terms = [token.lower() for token in token_re.findall(" ".join(chunks)) if not token.isdigit()]
    return Counter(terms)


def _year_value(paper: dict[str, Any]) -> int | None:
    import re

    for key in ("year", "published_date", "updated_date", "collected_at"):
        match = re.search(r"(19|20)\d{2}", safe_str(paper.get(key)))
        if match:
            return int(match.group(0))
    return None


def _freshness(paper: dict[str, Any], *, current_year: int) -> float:
    year = _year_value(paper)
    if year is None:
        return 0.15
    age = max(0, current_year - year)
    return _bounded(1.0 - min(age, 10) * 0.1)


def _quality(paper: dict[str, Any]) -> float:
    score = 0.0
    if safe_str(paper.get("pdf_url")):
        score += 0.25
    if safe_str(paper.get("doi")) or safe_str(paper.get("arxiv_id")):
        score += 0.25
    if safe_str(paper.get("abstract")):
        score += 0.25
    if safe_str(paper.get("source")) in {"arxiv", "openalex", "related-papers"}:
        score += 0.25
    if paper.get("related_review_score") is not None:
        score += 0.15
    return _bounded(score)


def _source_confidence(paper: dict[str, Any]) -> float:
    source = safe_str(paper.get("source")).lower()
    if source in {"arxiv", "openalex"}:
        return 0.9
    if paper.get("related_review_score") is not None:
        return 0.85
    if source in {"related-papers", "semantic-scholar"}:
        return 0.75
    return 0.55


def rank_paper_v2(paper: dict[str, Any], profile: RecommendationProfile, *, current_year: int) -> RankedPaper:
    terms = _paper_terms(paper)
    interest_match, interest_terms = _component_overlap(terms, profile.positive_terms, denominator=12.0)
    recent_intent_match, query_terms = _component_overlap(terms, profile.query_terms, denominator=6.0)
    negative_match, negative_terms = _component_overlap(terms, profile.negative_terms, denominator=8.0)
    pid = paper_id(paper).lower()
    if pid in profile.negative_paper_ids:
        negative_match = 1.0
    paper_quality = _quality(paper)
    freshness = _freshness(paper, current_year=current_year)
    source_confidence = _source_confidence(paper)
    related_boost = _bounded(_safe_float(paper.get("related_review_score")) / 5.0)
    novelty = 1.0

    positive = (
        0.45 * interest_match
        + 0.15 * recent_intent_match
        + 0.15 * paper_quality
        + 0.10 * freshness
        + 0.10 * novelty
        + 0.05 * source_confidence
        + 0.05 * related_boost
    )
    raw_score = positive - 0.20 * negative_match
    normalized_score = _bounded(raw_score)
    display_score = round(normalized_score * 5.0, 3)
    matched_terms = []
    for term in [*query_terms, *interest_terms]:
        if term not in matched_terms and term not in negative_terms:
            matched_terms.append(term)
        if len(matched_terms) >= 5:
            break

    reason_factors: list[str] = []
    if interest_match > 0:
        reason_factors.append("북마크/행동 관심사")
    if recent_intent_match > 0:
        reason_factors.append("최근 탐색 신호")
    if paper_quality >= 0.5:
        reason_factors.append("논문 품질 신호")
    if freshness >= 0.7:
        reason_factors.append("최신성")
    if negative_match > 0:
        reason_factors.append("부정 신호 감점")

    slot_type = "recent_intent" if recent_intent_match >= interest_match and recent_intent_match > 0 else "core_interest"
    if interest_match == 0 and recent_intent_match == 0:
        slot_type = "quality_pick"
    explanation_confidence = "근거 충분" if len(reason_factors) >= 2 and matched_terms else "근거 제한"
    return RankedPaper(
        paper=paper,
        score=display_score,
        raw_score=round(raw_score, 6),
        normalized_score=round(normalized_score, 6),
        matched_terms=matched_terms,
        score_breakdown={
            "interest_match": round(interest_match, 6),
            "recent_intent_match": round(recent_intent_match, 6),
            "paper_quality": round(paper_quality, 6),
            "freshness": round(freshness, 6),
            "novelty": round(novelty, 6),
            "source_confidence": round(source_confidence, 6),
            "negative_match": round(negative_match, 6),
            "related_review": round(related_boost, 6),
        },
        reason_factors=reason_factors,
        slot_type=slot_type,
        explanation_confidence=explanation_confidence,
    )


def reason_v2(ranked: RankedPaper, *, fallback_recent: bool) -> str:
    if fallback_recent:
        return "개인화 근거가 아직 적어 최신성/품질 신호를 우선 반영했습니다."
    if ranked.matched_terms:
        terms = ", ".join(ranked.matched_terms[:4])
        return f"관심 신호와 겹치는 키워드가 있습니다: {terms}."
    if ranked.reason_factors:
        return f"{', '.join(ranked.reason_factors[:3])}를 근거로 추천했습니다."
    return "품질과 최신성 기준으로 검토할 만한 후보입니다."


def _token_set(ranked: RankedPaper) -> set[str]:
    return set(_paper_terms(ranked.paper))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def mmr_rerank(
    ranked_items: list[RankedPaper],
    *,
    limit: int,
    lambda_relevance: float = 0.75,
    min_relevance_ratio: float = 0.60,
) -> list[RankedPaper]:
    """Return a diversity-aware top-k ordering using token MMR.

    Relevance scores are not rewritten; MMR only chooses the order and records
    similarity penalties for explainability. Very low-relevance candidates cannot
    be promoted solely for diversity.
    """
    if limit <= 0 or len(ranked_items) <= 1:
        return ranked_items[:limit]
    remaining = list(ranked_items)
    selected: list[RankedPaper] = []
    token_cache = {id(item): _token_set(item) for item in remaining}
    top_relevance = max((item.normalized_score for item in remaining), default=0.0)
    floor = top_relevance * min_relevance_ratio

    while remaining and len(selected) < limit:
        if not selected:
            chosen = max(remaining, key=lambda item: (item.normalized_score, item.score))
            selected.append(replace(chosen, diversity_adjusted=False, similarity_penalty=0.0))
            remaining.remove(chosen)
            continue

        best_item: RankedPaper | None = None
        best_tuple: tuple[float, float, float] | None = None
        for item in remaining:
            if item.normalized_score < floor:
                continue
            max_similarity = max(_jaccard(token_cache[id(item)], _token_set(sel)) for sel in selected)
            mmr_score = lambda_relevance * item.normalized_score - (1.0 - lambda_relevance) * max_similarity
            key = (mmr_score, item.normalized_score, -max_similarity)
            if best_tuple is None or key > best_tuple:
                best_item = item
                best_tuple = key
        if best_item is None:
            best_item = max(remaining, key=lambda item: (item.normalized_score, item.score))
            max_similarity = max(_jaccard(token_cache[id(best_item)], _token_set(sel)) for sel in selected)
        else:
            max_similarity = -best_tuple[2] if best_tuple is not None else 0.0
        selected.append(
            replace(
                best_item,
                diversity_adjusted=max_similarity > 0,
                similarity_penalty=round(max_similarity, 6),
                slot_type="diversity" if max_similarity > 0.35 else best_item.slot_type,
            )
        )
        remaining.remove(best_item)
    return selected
