"""
논문 관련 공유 유틸리티.

doc_id 생성, 제목 정규화, paper_id 생성 등
코드베이스 전역에서 중복 구현되던 함수들을 통합.
"""

import hashlib
import json
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
    """NFKC/casefold title tokens, retaining Unicode and punctuation boundaries."""
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", title).casefold()
    t = "".join(c if c.isalnum() or unicodedata.category(c).startswith("M") else " " for c in t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def normalize_doi(doi: str) -> str:
    """DOI 정규화: prefix 제거 + 소문자."""
    if not doi:
        return ""
    d = unicodedata.normalize("NFKC", str(doi)).strip().casefold()
    d = re.sub(r"^(?:doi:\s*)?(?:https?://(?:dx\.)?doi\.org/)?", "", d)
    return d.strip()


def generate_result_key(paper: Dict[str, Any]) -> str:
    """Stable selection identity; never uses historical title-derived doc_id.

    Empty metadata yields the same explicitly unidentified fingerprint, not a
    claim that two empty records identify different known papers.
    """
    doi = normalize_doi(paper.get("doi", ""))
    if doi:
        return f"doi:{doi}"
    for value in (paper.get("arxiv_id"), paper.get("url"), paper.get("id")):
        match = re.fullmatch(
            r"(?:https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/|arxiv:\s*)?"
            r"(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z-]+)?/\d{7})(?:v\d+)?(?:\.pdf)?/?",
            str(value or "").strip(), re.IGNORECASE,
        )
        if match:
            return f"arxiv:{match.group(1).casefold()}"
    for field, namespace in (
        ("openalex_id", "openalex"), ("semantic_scholar_id", "semantic_scholar"),
        ("paperId", "semantic_scholar"), ("pmid", "pubmed"),
    ):
        if paper.get(field):
            return f"provider:{namespace}:{str(paper[field]).strip()}"
    source = str(paper.get("source") or paper.get("_source") or paper.get("_source_tag") or "").strip().casefold()
    provider_id = paper.get("id") or paper.get("paper_id")
    if source and provider_id:
        return f"provider:{source}:{str(provider_id).strip()}"
    authors = paper.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    metadata = {
        "title": normalize_title(paper.get("title") or ""),
        "authors": sorted(normalize_title(a.get("name", "") if isinstance(a, dict) else str(a)) for a in authors),
        "year": str(paper.get("year") or ""),
        "source": source,
        "url": str(paper.get("url") or "").strip(),
        "pdf_url": str(paper.get("pdf_url") or "").strip(),
    }
    digest = hashlib.sha256(json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"metadata:{digest}"


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
