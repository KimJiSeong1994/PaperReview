"""Independent, intentionally simple reference for reward golden vectors.

This file must not import ``src.search_eval.query_analysis_reward``.  It favors
literal loops over shared helpers so golden tests can detect production drift.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any


def _tokens(value: str) -> tuple[str, ...]:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = "".join(
        c if unicodedata.category(c).startswith(("L", "N")) else " " for c in value
    )
    return tuple(value.split())


def _rounded(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("non-finite")
    return float(
        Decimal.from_float(float(value)).quantize(
            Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN
        )
    )


def domain_hash(domain: str, value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    raw = b"skillopt:" + domain.encode("ascii") + b"\x00" + encoded
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def corpus_hash(corpus: dict[str, Any]) -> str:
    payload = json.loads(json.dumps(corpus))
    payload.pop("corpus_hash", None)
    payload["documents"] = sorted(payload["documents"], key=lambda item: item["doc_id"])
    payload["queries"] = sorted(payload["queries"], key=lambda item: item["query_id"])
    return domain_hash("skillopt_reward_corpus_v1", payload)


def _has(tokens: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    return any(
        tokens[i : i + len(phrase)] == phrase
        for i in range(len(tokens) - len(phrase) + 1)
    )


def calculate(
    analysis: dict[str, Any],
    query: dict[str, Any],
    documents: list[dict[str, Any]],
    *,
    algorithm_identity: str | None = None,
    corpus_identity: str | None = None,
) -> dict[str, Any]:
    source = analysis["source_queries"]
    raw = [
        ("improved_query", None, _tokens(analysis["improved_query"])),
        ("arxiv", "arxiv", _tokens(source["arxiv"])),
        ("dblp", "dblp", _tokens(source["dblp"])),
    ]
    raw += [
        (f"scholar_{i + 1}", "scholar", _tokens(v))
        for i, v in enumerate(source["scholar_queries"])
    ]
    keyword_parts: list[tuple[str, ...]] = []
    for keyword in analysis["keywords"]:
        part = _tokens(keyword)
        if part and part not in keyword_parts:
            keyword_parts.append(part)
    keyword_join = tuple(token for part in keyword_parts for token in part)
    raw.append(("keyword_join", None, keyword_join))
    emitted = [
        (kind, src, tokens, " ".join(tokens)) for kind, src, tokens in raw if tokens
    ]
    variants: list[tuple[str, str | None, tuple[str, ...], str]] = []
    for variant in emitted:
        if not any(old[3] == variant[3] for old in variants):
            variants.append(variant)

    rankings: list[dict[str, Any]] = []
    for kind, src, query_tokens, text in variants:
        scores: dict[str, float] = {}
        qset = set(query_tokens)
        for doc in documents:
            if src is not None and doc["source"] != src:
                continue
            title = len(qset & set(_tokens(doc["title"])))
            abstract = len(qset & set(_tokens(doc["abstract"])))
            score = (2 * title + abstract) / (3 * max(len(qset), 1))
            if score:
                doc_id = unicodedata.normalize("NFC", doc["doc_id"])
                scores[doc_id] = max(scores.get(doc_id, 0), score)
        ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
        rankings.append(
            {
                "kind": kind,
                "source": src,
                "variant": text,
                "results": [
                    {"doc_id": doc_id, "score": _rounded(score)}
                    for doc_id, score in ordered
                ],
            }
        )

    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, result in enumerate(ranking["results"], 1):
            fused[result["doc_id"]] = fused.get(result["doc_id"], 0) + 1 / (60 + rank)
    merged = sorted(fused, key=lambda doc_id: (-fused[doc_id], doc_id))
    merged_documents = [
        {"doc_id": doc_id, "rrf_score": _rounded(fused[doc_id])} for doc_id in merged
    ]
    relevance = query["graded_relevance"]

    def dcg(grades: list[int]) -> float:
        return sum(
            (2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, 1)
        )

    actual = [relevance.get(doc_id, 0) for doc_id in merged[:10]]
    ideal = sorted((grade for grade in relevance.values() if grade), reverse=True)[:10]
    ideal_gain = dcg(ideal)
    ndcg = _rounded(dcg(actual) / ideal_gain if ideal_gain else 0)
    mrr = _rounded(
        next(
            (
                1 / rank
                for rank, doc_id in enumerate(merged[:10], 1)
                if relevance.get(doc_id, 0) >= 1
            ),
            0,
        )
    )
    relevant = {doc_id for doc_id, grade in relevance.items() if grade >= 1}
    recall = _rounded(
        len(relevant & set(merged[:10])) / len(relevant) if relevant else 0
    )

    fields = [_tokens(analysis["improved_query"])]
    fields += [_tokens(v) for v in analysis["keywords"]]
    fields += [_tokens(source["arxiv"]), _tokens(source["dblp"])]
    fields += [_tokens(v) for v in source["scholar_queries"]]
    fields.append(keyword_join)
    required: list[tuple[str, ...]] = []
    for value in query["required_terms"]:
        phrase = _tokens(value)
        if phrase and phrase not in required:
            required.append(phrase)
    coverage = _rounded(
        sum(any(_has(field, phrase) for field in fields) for phrase in required)
        / len(required)
        if required
        else 1
    )
    original = set(_tokens(query["original_query"]))
    anchored = sum(
        bool(original & set(tokens)) or any(_has(tokens, phrase) for phrase in required)
        for _, _, tokens, _ in variants
    )
    anchored_ratio = _rounded(anchored / len(variants) if variants else 0)
    unique_ratio = _rounded(len(variants) / len(emitted) if emitted else 0)
    compact = [
        1 <= len(_tokens(analysis["improved_query"])) <= 64,
        len(analysis["keywords"]) <= 8
        and all(1 <= len(_tokens(v)) <= 8 for v in analysis["keywords"]),
        len(analysis["core_concepts"]) <= 8
        and all(1 <= len(_tokens(v)) <= 8 for v in analysis["core_concepts"]),
        len(_tokens(analysis["research_area"])) <= 32,
        len(_tokens(analysis["search_strategy"])) <= 128,
        1 <= len(_tokens(source["arxiv"])) <= 64,
        1 <= len(_tokens(source["dblp"])) <= 64,
        1 <= len(source["scholar_queries"]) <= 3
        and all(1 <= len(_tokens(v)) <= 64 for v in source["scholar_queries"]),
    ]
    compactness = _rounded(sum(compact) / 8)
    nondrift = _rounded((anchored_ratio + unique_ratio + compactness) / 3)
    intent = _rounded(float(analysis["intent"] == query["expected_intent"]))
    structure = _rounded(
        sum(
            [
                bool(_tokens(source["arxiv"])),
                bool(_tokens(source["dblp"])),
                bool(source["scholar_queries"])
                and all(_tokens(v) for v in source["scholar_queries"]),
            ]
        )
        / 3
    )
    constraint = _rounded((intent + coverage + structure + nondrift) / 4)
    soft = _rounded(0.5 * ndcg + 0.2 * mrr + 0.2 * recall + 0.1 * constraint)
    result = {
        "hard": 1.0,
        "soft": soft,
        "metrics": {
            "ndcg_at_10": ndcg,
            "mrr_at_10": mrr,
            "recall_at_10": recall,
            "intent_match": intent,
            "required_term_coverage": coverage,
            "source_query_structure": structure,
            "anchored_ratio": anchored_ratio,
            "unique_variant_ratio": unique_ratio,
            "schema_bound_field_ratio": compactness,
            "non_drift_compactness": nondrift,
            "query_constraint_score": constraint,
        },
        "evidence": {
            "emitted_variant_count": min(len(emitted), 8),
            "unique_variant_count": min(len(variants), 8),
            "ranking_count": min(len(rankings), 8),
            "merged_document_count_at_10": min(len(merged), 10),
        },
    }
    if algorithm_identity is not None and corpus_identity is not None:
        evidence = {
            "version": "query_analysis_reward_evidence_v1",
            "algorithm_version": "deterministic_retriever_v2",
            "algorithm_identity": algorithm_identity,
            "corpus_hash": corpus_identity,
            "query_id": query["query_id"],
            "invalid_reason": None,
            "ordered_variants": [
                {
                    "kind": kind,
                    "source": source,
                    "tokens": list(tokens),
                    "text": text,
                }
                for kind, source, tokens, text in variants
            ],
            "rankings": rankings,
            "merged_documents": merged_documents,
            "components": result["metrics"],
        }
        evidence["evidence_identity"] = domain_hash(
            "query_analysis_reward_evidence_v1", evidence
        )
        result["sealed_evidence"] = evidence
    return result


def mixed(hard: float, soft: float, weight: float = 0.8) -> float:
    return _rounded(
        (1 - _rounded(weight)) * _rounded(hard) + _rounded(weight) * _rounded(soft)
    )
