"""Offline retrieval-quality scoring for SkillOpt paper-search candidates.

The scorer is dev/eval-only and deterministic. It accepts production-like search
result lists keyed by benchmark query id and computes the same metric family the
SkillOpt execution-control fixture declares.
"""
from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .skillopt_contract import ValidationError, load_json, validate_dataset_contract


@dataclass(frozen=True)
class RetrievalDocument:
    """One ranked search hit used by offline retrieval scoring."""

    title: str
    abstract: str = ""
    source: str = "offline_fixture"

    @property
    def searchable_text(self) -> str:
        return f"{self.title} {self.abstract}".lower()


@dataclass(frozen=True)
class QueryRetrievalScore:
    """Per-query retrieval metrics."""

    query_id: str
    ndcg_at_10: float
    mrr_at_10: float
    recall_at_5: float
    recall_at_10: float
    wrong_paper_handoff: float


def score_retrieval_results(
    *,
    dataset_path: str,
    results_by_query: Mapping[str, Sequence[Mapping[str, Any]]],
    p95_latency_ms: float = 0.0,
    token_estimate: float = 0.0,
    cost_estimate: float = 0.0,
) -> dict[str, Any]:
    """Score ranked paper-search results against the offline SkillOpt fixture.

    Results use production-like records with at least a ``title`` field and
    optional ``abstract``/``source`` fields. Labels are matched case-insensitively
    against title+abstract using the dataset's public/synthetic must_include,
    acceptable, and must_exclude strings.
    """
    dataset = load_json(dataset_path)
    validate_dataset_contract(dataset)
    started = time.perf_counter()

    per_query = []
    for query in dataset["queries"]:
        query_id = str(query["query_id"])
        labels = query["labels"]
        docs = [_coerce_document(item) for item in results_by_query.get(query_id, [])]
        per_query.append(_score_query(query_id=query_id, labels=labels, docs=docs))

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    summary = _summarize(per_query)
    summary.update(
        {
            "version": "skillopt-retrieval-eval-v0",
            "dataset_hash": dataset["dataset_hash"],
            "query_count": len(per_query),
            "p95_latency_ms": float(p95_latency_ms),
            "token_estimate": float(token_estimate),
            "cost_estimate": float(cost_estimate),
            "scoring_elapsed_ms": round(elapsed_ms, 3),
            "per_query": [score.__dict__ for score in per_query],
        }
    )
    return summary


def build_fixture_retrieval_results(*, dataset_path: str, quality: str) -> dict[str, list[dict[str, str]]]:
    """Build deterministic production-like search outputs for CI/demo scoring.

    ``quality='baseline'`` returns acceptable-but-not-perfect results.
    ``quality='candidate'`` returns the must-include hit first and excludes known
    wrong handoffs. This is not a live search claim; it is a reproducible scorer
    fixture used to validate the evaluation and approval pipeline.
    """
    if quality not in {"baseline", "candidate"}:
        raise ValidationError("fixture retrieval quality must be baseline or candidate")
    dataset = load_json(dataset_path)
    validate_dataset_contract(dataset)
    results: dict[str, list[dict[str, str]]] = {}
    for query in dataset["queries"]:
        labels = query["labels"]
        must_include = [str(v) for v in labels.get("must_include", [])]
        acceptable = [str(v) for v in labels.get("acceptable", [])]
        must_exclude = [str(v) for v in labels.get("must_exclude", [])]
        docs: list[dict[str, str]] = []
        if quality == "candidate":
            docs.extend(_doc(label, "candidate_exact") for label in must_include)
            docs.extend(_doc(label, "candidate_acceptable") for label in acceptable[:2])
        else:
            docs.extend(_doc(label, "baseline_acceptable") for label in acceptable[:1])
            if must_exclude:
                docs.append(_doc(must_exclude[0], "baseline_wrong_handoff"))
            docs.extend(_doc(label, "baseline_late_exact") for label in must_include[:1])
        results[str(query["query_id"])] = docs[:10]
    return results


def validate_retrieval_evaluation_record(record: Mapping[str, Any]) -> None:
    """Validate an offline retrieval evaluation summary."""
    required = {
        "version",
        "dataset_hash",
        "query_count",
        "nDCG@10",
        "MRR@10",
        "Recall@5",
        "Recall@10",
        "wrong_paper_handoff_rate",
        "p95_latency_ms",
        "token_estimate",
        "cost_estimate",
        "per_query",
    }
    missing = required - set(record)
    if missing:
        raise ValidationError(f"retrieval_evaluation missing required keys: {sorted(missing)}")
    if record.get("version") != "skillopt-retrieval-eval-v0":
        raise ValidationError("retrieval_evaluation.version is invalid")
    if int(record.get("query_count", 0)) <= 0:
        raise ValidationError("retrieval_evaluation.query_count must be positive")
    for metric in ["nDCG@10", "MRR@10", "Recall@5", "Recall@10", "wrong_paper_handoff_rate"]:
        _require_finite_metric(record.get(metric), f"retrieval_evaluation.{metric}", minimum=0.0, maximum=1.0)
    for metric in ["p95_latency_ms", "token_estimate", "cost_estimate"]:
        _require_finite_metric(record.get(metric), f"retrieval_evaluation.{metric}", minimum=0.0)
    per_query = record.get("per_query")
    if not isinstance(per_query, Sequence) or isinstance(per_query, (str, bytes)):
        raise ValidationError("retrieval_evaluation.per_query must be a list")
    if len(per_query) != int(record.get("query_count", -1)):
        raise ValidationError("retrieval_evaluation.per_query length must match query_count")
    recomputed = _summarize(_validate_per_query_rows(per_query))
    for metric in ["nDCG@10", "MRR@10", "Recall@5", "Recall@10", "wrong_paper_handoff_rate"]:
        if round(float(record[metric]), 6) != recomputed[metric]:
            raise ValidationError(f"retrieval_evaluation.{metric} does not match per_query aggregate")


def _validate_per_query_rows(rows: Sequence[Any]) -> list[QueryRetrievalScore]:
    scores: list[QueryRetrievalScore] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValidationError("retrieval_evaluation.per_query entries must be objects")
        query_id = row.get("query_id")
        if not isinstance(query_id, str) or not query_id:
            raise ValidationError("retrieval_evaluation.per_query.query_id is required")
        ndcg = _require_finite_metric(row.get("ndcg_at_10"), "retrieval_evaluation.per_query.ndcg_at_10", minimum=0.0, maximum=1.0)
        mrr = _require_finite_metric(row.get("mrr_at_10"), "retrieval_evaluation.per_query.mrr_at_10", minimum=0.0, maximum=1.0)
        recall5 = _require_finite_metric(row.get("recall_at_5"), "retrieval_evaluation.per_query.recall_at_5", minimum=0.0, maximum=1.0)
        recall10 = _require_finite_metric(row.get("recall_at_10"), "retrieval_evaluation.per_query.recall_at_10", minimum=0.0, maximum=1.0)
        wrong = _require_finite_metric(row.get("wrong_paper_handoff"), "retrieval_evaluation.per_query.wrong_paper_handoff", minimum=0.0, maximum=1.0)
        scores.append(QueryRetrievalScore(query_id, ndcg, mrr, recall5, recall10, wrong))
    return scores


def _require_finite_metric(value: Any, field: str, *, minimum: float, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValidationError(f"{field} must be finite")
    if number < minimum:
        raise ValidationError(f"{field} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ValidationError(f"{field} must be <= {maximum}")
    return round(number, 6)


def assert_candidate_beats_baseline(
    *,
    baseline_record: Mapping[str, Any],
    candidate_record: Mapping[str, Any],
    minimum_delta: float = 0.0,
) -> None:
    """Require candidate retrieval quality to improve the primary metric."""
    validate_retrieval_evaluation_record(baseline_record)
    validate_retrieval_evaluation_record(candidate_record)
    baseline = float(baseline_record["nDCG@10"])
    candidate = float(candidate_record["nDCG@10"])
    if candidate < baseline + minimum_delta:
        raise ValidationError(
            f"candidate nDCG@10 must improve baseline by >= {minimum_delta}: "
            f"baseline={baseline}, candidate={candidate}"
        )
    for metric in ("MRR@10", "Recall@5", "Recall@10"):
        if float(candidate_record[metric]) < float(baseline_record[metric]):
            raise ValidationError(f"candidate {metric} must not regress")
    if float(candidate_record["Recall@10"]) <= 0.0:
        raise ValidationError("candidate Recall@10 must be greater than zero")
    if float(candidate_record["wrong_paper_handoff_rate"]) > float(baseline_record["wrong_paper_handoff_rate"]):
        raise ValidationError("candidate wrong_paper_handoff_rate must not regress")
    for metric in ("p95_latency_ms", "token_estimate", "cost_estimate"):
        if float(candidate_record[metric]) > float(baseline_record[metric]):
            raise ValidationError(f"candidate {metric} must not regress")


def _ranked_label_gains(docs: Sequence[RetrievalDocument], labels: Mapping[str, Any]) -> list[int]:
    label_specs = _label_specs(labels)
    matched: set[int] = set()
    gains: list[int] = []
    for doc in docs:
        matches = [
            (idx, gain, len(phrase))
            for idx, phrase, gain in label_specs
            if idx not in matched and phrase in doc.searchable_text
        ]
        if not matches:
            gains.append(0)
            continue
        idx, gain, _length = max(matches, key=lambda item: (item[1], item[2]))
        matched.add(idx)
        gains.append(gain)
    return gains


def _ideal_label_gains(labels: Mapping[str, Any]) -> list[int]:
    return sorted((gain for _idx, _phrase, gain in _label_specs(labels)), reverse=True)


def _label_specs(labels: Mapping[str, Any]) -> list[tuple[int, str, int]]:
    specs: list[tuple[int, str, int]] = []
    seen: set[str] = set()
    for phrase in labels.get("must_include", []):
        normalized = str(phrase).lower()
        if normalized and normalized not in seen:
            specs.append((len(specs), normalized, 3))
            seen.add(normalized)
    for phrase in labels.get("acceptable", []):
        normalized = str(phrase).lower()
        if normalized and normalized not in seen:
            specs.append((len(specs), normalized, 1))
            seen.add(normalized)
    return specs


def _score_query(*, query_id: str, labels: Mapping[str, Any], docs: Sequence[RetrievalDocument]) -> QueryRetrievalScore:
    relevance = _ranked_label_gains(docs[:10], labels)
    ideal = _ideal_label_gains(labels)[:10]
    ndcg = _dcg(relevance) / _dcg(ideal) if _dcg(ideal) else 0.0
    first_rel = next((idx + 1 for idx, rel in enumerate(relevance) if rel > 0), None)
    mrr = 1.0 / first_rel if first_rel else 0.0
    must_include = [str(v).lower() for v in labels.get("must_include", [])]
    recall5 = _recall_at(docs, must_include, 5)
    recall10 = _recall_at(docs, must_include, 10)
    wrong = 1.0 if any(_contains_any(doc, labels.get("must_exclude", [])) for doc in docs[:10]) else 0.0
    return QueryRetrievalScore(query_id, round(ndcg, 6), round(mrr, 6), round(recall5, 6), round(recall10, 6), wrong)


def _summarize(scores: Sequence[QueryRetrievalScore]) -> dict[str, float]:
    count = max(len(scores), 1)
    return {
        "nDCG@10": round(sum(s.ndcg_at_10 for s in scores) / count, 6),
        "MRR@10": round(sum(s.mrr_at_10 for s in scores) / count, 6),
        "Recall@5": round(sum(s.recall_at_5 for s in scores) / count, 6),
        "Recall@10": round(sum(s.recall_at_10 for s in scores) / count, 6),
        "wrong_paper_handoff_rate": round(sum(s.wrong_paper_handoff for s in scores) / count, 6),
    }


def _coerce_document(item: Mapping[str, Any]) -> RetrievalDocument:
    title = str(item.get("title") or item.get("name") or "")
    abstract = str(item.get("abstract") or item.get("summary") or "")
    source = str(item.get("source") or "offline_fixture")
    return RetrievalDocument(title=title, abstract=abstract, source=source)


def _relevance(doc: RetrievalDocument, labels: Mapping[str, Any]) -> int:
    if _contains_any(doc, labels.get("must_exclude", [])):
        return 0
    if _contains_any(doc, labels.get("must_include", [])):
        return 3
    if _contains_any(doc, labels.get("acceptable", [])):
        return 1
    return 0


def _contains_any(doc: RetrievalDocument, labels: Sequence[Any]) -> bool:
    text = doc.searchable_text
    return any(str(label).lower() in text for label in labels)


def _recall_at(docs: Sequence[RetrievalDocument], must_include: Sequence[str], k: int) -> float:
    if not must_include:
        return 1.0
    top_text = "\n".join(doc.searchable_text for doc in docs[:k])
    found = sum(1 for label in must_include if label in top_text)
    return found / len(must_include)


def _dcg(gains: Sequence[int]) -> float:
    return sum((2**gain - 1) / math.log2(idx + 2) for idx, gain in enumerate(gains))


def _doc(label: str, source: str) -> dict[str, str]:
    return {"title": label, "abstract": f"Offline fixture hit for {label}", "source": source}
