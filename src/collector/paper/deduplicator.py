"""Deterministic Unicode-aware paper deduplication with conservative identity."""

import copy
import json
import logging
import math
from typing import Any, Dict, List

from src.utils.paper_utils import generate_result_key, normalize_doi, normalize_title, normalize_kci_id

logger = logging.getLogger(__name__)


class PaperDeduplicator:
    EMBEDDING_SIMILARITY_THRESHOLD = 0.90
    FUZZY_TITLE_JACCARD_THRESHOLD = 0.85
    FUZZY_TITLE_LENGTH_RATIO = 0.80

    normalize_title = staticmethod(normalize_title)
    normalize_doi = staticmethod(normalize_doi)

    @staticmethod
    def _richness(paper: Dict[str, Any]) -> int:
        return (3 * bool(paper.get("abstract")) + 2 * bool(paper.get("doi"))
                + len(paper.get("authors") or []) + bool(paper.get("year"))
                + 2 * bool(paper.get("citations")) + bool(paper.get("url"))
                + bool(paper.get("pdf_url")))

    @classmethod
    def _representative_key(cls, paper):
        return (-cls._richness(paper), generate_result_key(paper),
                json.dumps(paper, sort_keys=True, ensure_ascii=False, default=str))

    @staticmethod
    def _merge_papers(primary, secondary):
        merged = copy.deepcopy(primary)
        for key, value in secondary.items():
            if not merged.get(key) and value:
                merged[key] = copy.deepcopy(value)
        if len(secondary.get("authors") or []) > len(merged.get("authors") or []):
            merged["authors"] = copy.deepcopy(secondary["authors"])
        merged["citations"] = max(primary.get("citations") or 0, secondary.get("citations") or 0)
        sources = set()
        for paper in (primary, secondary):
            sources.update(paper.get("_found_in_sources") or [])
            sources.update(str(paper[k]) for k in ("source", "_source", "_source_tag") if paper.get(k))
        merged["_found_in_sources"] = sorted(sources)
        return merged

    @staticmethod
    def _conflicting_ids(left, right):
        a, b = normalize_doi(left.get("doi")), normalize_doi(right.get("doi"))
        if a and b:
            return a != b
        # A title (especially an editorial heading) is not an identifier.
        kci_left = next((identifier for field in ('kci_id', 'id', 'url')
                         if (identifier := normalize_kci_id(left.get(field)))), '')
        kci_right = next((identifier for field in ('kci_id', 'id', 'url')
                          if (identifier := normalize_kci_id(right.get(field)))), '')
        if kci_left and kci_right:
            return kci_left != kci_right
        # Distinct explicit identifiers cannot be overridden by title similarity.
        ka, kb = generate_result_key(left), generate_result_key(right)
        if ka == kb and not ka.startswith('metadata:'):
            return False
        if ka.startswith('arxiv:') and kb.startswith('arxiv:'):
            return ka != kb
        if ka.startswith('provider:') and kb.startswith('provider:') and ka.split(':')[1] == kb.split(':')[1]:
            return ka != kb
        # Do not bridge two different works through a DOI-less catalog record.
        years = [str(p.get('year') or '')[:4] for p in (left, right)]
        if all(y.isdigit() for y in years) and years[0] != years[1]:
            return True
        def authors(paper):
            values = paper.get('authors') or []
            if isinstance(values, str):
                values = [values]
            return {normalize_title(v.get('name', '') if isinstance(v, dict) else str(v))
                    for v in values} - {''}
        la, ra = authors(left), authors(right)
        return bool(la and ra and la.isdisjoint(ra))

    def deduplicate(self, papers: List[Dict[str, Any]], use_embeddings=False,
                    similarity_calculator=None) -> List[Dict[str, Any]]:
        remaining = sorted(copy.deepcopy(papers), key=self._representative_key)
        # Merge each stage immediately: a DOI-less bridge cannot join conflicting
        # DOI groups later, because the representative already carries its DOI.
        for stage in ("identity", "title", "fuzzy", "embedding"):
            if stage == "embedding" and not (use_embeddings and similarity_calculator):
                continue
            result = []
            for paper in remaining:
                for index, candidate in enumerate(result):
                    if self._conflicting_ids(candidate, paper):
                        continue
                    left, right = normalize_title(candidate.get("title")), normalize_title(paper.get("title"))
                    duplicate = False
                    if stage == "identity":
                        key = generate_result_key(candidate)
                        duplicate = not key.startswith("metadata:") and key == generate_result_key(paper)
                    elif stage == "title":
                        duplicate = bool(left and right and left == right)
                    elif stage == "fuzzy" and left and right:
                        a, b = set(left.split()), set(right.split())
                        duplicate = (min(len(a), len(b)) / max(len(a), len(b)) >= self.FUZZY_TITLE_LENGTH_RATIO
                                     and len(a & b) / len(a | b) >= self.FUZZY_TITLE_JACCARD_THRESHOLD)
                    elif stage == "embedding" and left and right:
                        try:
                            score = similarity_calculator.calculate_similarity(candidate, paper)
                            duplicate = math.isfinite(score) and score >= self.EMBEDDING_SIMILARITY_THRESHOLD
                        except Exception as exc:
                            logger.warning("[Dedup] Embedding comparison failed: %s", exc)
                    if duplicate:
                        primary, secondary = sorted((candidate, paper), key=self._representative_key)
                        result[index] = self._merge_papers(primary, secondary)
                        break
                else:
                    result.append(paper)
            remaining = sorted(result, key=self._representative_key)
        for paper in remaining:
            sources = set(paper.get("_found_in_sources") or [])
            sources.update(str(paper[k]) for k in ("source", "_source", "_source_tag") if paper.get(k))
            paper["_found_in_sources"] = sorted(sources)
        return sorted(remaining, key=lambda p: (generate_result_key(p), self._representative_key(p)))

    def deduplicate_cross_source(self, results_by_source, use_embeddings=False,
                                 similarity_calculator=None):
        papers = [dict(paper, _source=source) for source, rows in results_by_source.items()
                  if not source.startswith("_") for paper in rows]
        return self.deduplicate(papers, use_embeddings, similarity_calculator)
