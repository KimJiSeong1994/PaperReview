"""
논문 중복 제거 모듈
3단계 중복 제거: DOI → 정규화 제목 → 임베딩 유사도
"""

import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple


class PaperDeduplicator:
    """3단계 논문 중복 제거"""

    EMBEDDING_SIMILARITY_THRESHOLD = 0.95

    # ── 정규화 유틸 ──────────────────────────────────────────────────

    @staticmethod
    def normalize_title(title: str) -> str:
        """제목 정규화: 소문자 + NFKD→ASCII + 구두점 제거 + 공백 정규화"""
        if not title:
            return ""
        t = title.lower().strip()
        # 유니코드 → ASCII (예: é → e)
        t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")
        # 구두점 제거
        t = re.sub(r"[^\w\s]", "", t)
        # 공백 정규화
        t = re.sub(r"\s+", " ", t).strip()
        return t

    @staticmethod
    def normalize_doi(doi: str) -> str:
        """DOI 정규화: prefix 제거 + 소문자"""
        if not doi:
            return ""
        d = doi.strip().lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if d.startswith(prefix):
                d = d[len(prefix):]
        return d.strip()

    # ── 풍부도 점수 ──────────────────────────────────────────────────

    @staticmethod
    def _richness(paper: Dict[str, Any]) -> int:
        """메타데이터 풍부도 점수 (높을수록 정보가 많음)"""
        score = 0
        if paper.get("abstract"):
            score += 3
        if paper.get("doi"):
            score += 2
        if paper.get("authors"):
            score += len(paper["authors"])
        if paper.get("year"):
            score += 1
        if paper.get("citations", 0) > 0:
            score += 2
        if paper.get("url"):
            score += 1
        if paper.get("pdf_url"):
            score += 1
        return score

    # ── 병합 ─────────────────────────────────────────────────────────

    @staticmethod
    def _merge_papers(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
        """primary를 기준으로 secondary의 누락 필드 보충"""
        merged = dict(primary)

        # 누락된 필드 보충
        for key in ("abstract", "doi", "url", "pdf_url", "year", "venue"):
            if not merged.get(key) and secondary.get(key):
                merged[key] = secondary[key]

        # authors: 더 많은 쪽 사용
        if len(secondary.get("authors", [])) > len(merged.get("authors", [])):
            merged["authors"] = secondary["authors"]

        # citations: 더 큰 값 사용
        if secondary.get("citations", 0) > merged.get("citations", 0):
            merged["citations"] = secondary["citations"]

        # 소스 추적
        sources = set()
        if merged.get("source"):
            sources.add(merged["source"])
        if secondary.get("source"):
            sources.add(secondary["source"])
        if merged.get("_found_in_sources"):
            sources.update(merged["_found_in_sources"])
        merged["_found_in_sources"] = sorted(sources)

        return merged

    # ── 3단계 중복 제거 (메인 API) ───────────────────────────────────

    def deduplicate(
        self,
        papers: List[Dict[str, Any]],
        use_embeddings: bool = False,
        similarity_calculator=None,
    ) -> List[Dict[str, Any]]:
        """
        3단계 중복 제거:
        1) DOI 매칭
        2) 정규화 제목 매칭
        3) 임베딩 유사도 (선택)

        Returns:
            중복 제거된 논문 리스트 (메타데이터 병합됨)
        """
        if not papers:
            return []

        # -- Pass 1: DOI 그룹핑 --
        doi_groups: Dict[str, List[int]] = {}
        for idx, paper in enumerate(papers):
            ndoi = self.normalize_doi(paper.get("doi", ""))
            if ndoi:
                doi_groups.setdefault(ndoi, []).append(idx)

        # 머지 결과 저장 (인덱스 → 대표 인덱스)
        merged_into: Dict[int, int] = {}

        for indices in doi_groups.values():
            if len(indices) <= 1:
                continue
            # 풍부도가 가장 높은 논문을 대표로
            best_idx = max(indices, key=lambda i: self._richness(papers[i]))
            for idx in indices:
                if idx != best_idx:
                    papers[best_idx] = self._merge_papers(papers[best_idx], papers[idx])
                    merged_into[idx] = best_idx

        # -- Pass 2: 정규화 제목 그룹핑 --
        title_groups: Dict[str, List[int]] = {}
        for idx, paper in enumerate(papers):
            if idx in merged_into:
                continue
            ntitle = self.normalize_title(paper.get("title", ""))
            if ntitle:
                title_groups.setdefault(ntitle, []).append(idx)

        for indices in title_groups.values():
            if len(indices) <= 1:
                continue
            best_idx = max(indices, key=lambda i: self._richness(papers[i]))
            for idx in indices:
                if idx != best_idx and idx not in merged_into:
                    papers[best_idx] = self._merge_papers(papers[best_idx], papers[idx])
                    merged_into[idx] = best_idx

        # -- Pass 3 (선택): 임베딩 유사도 --
        if use_embeddings and similarity_calculator:
            remaining = [i for i in range(len(papers)) if i not in merged_into]
            merged_into = self._embedding_dedup_pass(
                papers, remaining, merged_into, similarity_calculator
            )

        # -- 결과 수집 --
        result = []
        for idx in range(len(papers)):
            if idx not in merged_into:
                paper = papers[idx]
                # _found_in_sources가 없으면 source 필드로 초기화
                if "_found_in_sources" not in paper and paper.get("source"):
                    paper["_found_in_sources"] = [paper["source"]]
                result.append(paper)

        return result

    def _embedding_dedup_pass(
        self,
        papers: List[Dict[str, Any]],
        remaining_indices: List[int],
        merged_into: Dict[int, int],
        similarity_calculator,
    ) -> Dict[int, int]:
        """임베딩 유사도 기반 중복 제거 (Union-Find 방식)"""
        n = len(remaining_indices)
        if n <= 1:
            return merged_into

        # Union-Find
        parent = {i: i for i in remaining_indices}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                # 풍부도가 높은 쪽을 루트로
                if self._richness(papers[ra]) >= self._richness(papers[rb]):
                    parent[rb] = ra
                else:
                    parent[ra] = rb

        try:
            # 각 논문의 텍스트 준비
            texts = {}
            for idx in remaining_indices:
                p = papers[idx]
                title = p.get("title", "")
                abstract = p.get("abstract", "")
                texts[idx] = f"{title}. {abstract}" if abstract else title

            # pairwise 비교 (소규모 데이터 가정)
            for i in range(n):
                for j in range(i + 1, n):
                    idx_i, idx_j = remaining_indices[i], remaining_indices[j]
                    if find(idx_i) == find(idx_j):
                        continue
                    # 임베딩 유사도 계산
                    sim = similarity_calculator.calculate_similarity(
                        papers[idx_i], papers[idx_j]
                    )
                    if sim >= self.EMBEDDING_SIMILARITY_THRESHOLD:
                        union(idx_i, idx_j)
        except Exception as e:
            print(f"[Dedup] Embedding dedup error: {e}")
            return merged_into

        # 그룹별 병합
        groups: Dict[int, List[int]] = {}
        for idx in remaining_indices:
            root = find(idx)
            groups.setdefault(root, []).append(idx)

        for root, members in groups.items():
            if len(members) <= 1:
                continue
            best_idx = max(members, key=lambda i: self._richness(papers[i]))
            for idx in members:
                if idx != best_idx:
                    papers[best_idx] = self._merge_papers(papers[best_idx], papers[idx])
                    merged_into[idx] = best_idx

        return merged_into

    # ── 소스별 결과 중복 제거 (SearchAgent용) ──────────────────────

    def deduplicate_cross_source(
        self,
        results_by_source: Dict[str, List[Dict[str, Any]]],
        use_embeddings: bool = False,
        similarity_calculator=None,
    ) -> List[Dict[str, Any]]:
        """
        소스별 결과를 합치고 중복 제거.
        각 논문에 _source 필드가 설정됨.
        """
        all_papers = []
        for source, papers in results_by_source.items():
            if source.startswith("_"):
                continue
            for paper in papers:
                paper["_source"] = source
                all_papers.append(paper)

        return self.deduplicate(
            all_papers,
            use_embeddings=use_embeddings,
            similarity_calculator=similarity_calculator,
        )
