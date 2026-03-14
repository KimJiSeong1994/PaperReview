"""
논문 관련 공유 유틸리티.

doc_id 생성, 제목 정규화, paper_id 생성 등
코드베이스 전역에서 중복 구현되던 함수들을 통합.
"""

import hashlib
import re
import unicodedata
from typing import Any, Dict


def generate_doc_id(title: str) -> str:
    """djb2 해시 기반 doc_id 생성 (프론트엔드 hashString 함수와 동일).

    routers/search.py, routers/papers.py, app/DeepAgent/tools/paper_loader.py
    에서 각각 독립 구현되어 있던 것을 통합.
    """
    if not title:
        return ""
    hash_value = 0
    for char in title:
        hash_value = ((hash_value << 5) - hash_value) + ord(char)
        hash_value = hash_value & 0x7FFFFFFF
    return str(hash_value)


def generate_md5_doc_id(title: str) -> str:
    """MD5 기반 doc_id 생성 (레거시 호환용)."""
    if not title:
        return ""
    return str(int(hashlib.md5(title.encode("utf-8")).hexdigest()[:15], 16))


def normalize_title(title: str) -> str:
    """제목 정규화: 소문자 + NFKD→ASCII + 구두점 제거 + 공백 정규화.

    PaperDeduplicator.normalize_title 의 canonical 구현을 그대로 사용.
    exploration_service.py 등에서 NFKD 없이 구현되어 불일치가 발생하던 문제를 해결.
    """
    if not title:
        return ""
    t = title.lower().strip()
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def normalize_doi(doi: str) -> str:
    """DOI 정규화: prefix 제거 + 소문자."""
    if not doi:
        return ""
    d = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.strip()


def generate_paper_id(paper: Dict[str, Any]) -> str:
    """논문 고유 ID 생성 (DOI 우선, 없으면 정규화 제목).

    node_creator, edge_creator, embedding_generator, search_agent
    에서 각각 독립 구현되어 있던 것을 통합.
    """
    doi = normalize_doi(paper.get("doi", ""))
    if doi:
        return f"doi:{doi}"
    title = normalize_title(paper.get("title", ""))
    return title[:100] if title else str(hash(str(paper)))
