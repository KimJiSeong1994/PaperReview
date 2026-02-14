"""
Light Context Builder - 검색 결과를 LLM 컨텍스트로 변환

LightRAG 검색 결과(엔티티, 관계, 청크, 논문)를
LLM 프롬프트에 사용할 구조화된 컨텍스트로 조립한다.
"""
from typing import Dict, List, Any, Optional
import networkx as nx


class LightContextBuilder:
    """검색 결과를 LLM 프롬프트용 컨텍스트로 변환"""

    def build_context(
        self,
        retrieval_result: Dict[str, Any],
        query: str,
        paper_graph: Optional[nx.MultiDiGraph] = None,
        max_entity_tokens: int = 1500,
        max_relation_tokens: int = 1000,
        max_paper_tokens: int = 1500,
    ) -> str:
        """엔티티/관계/논문 정보를 구조화된 컨텍스트로 조립"""
        sections = []

        # 섹션 1: 핵심 엔티티 정보
        entities = retrieval_result.get("entities", [])
        if entities:
            entity_section = self._build_entity_section(entities, max_entity_tokens)
            if entity_section:
                sections.append(entity_section)

        # 섹션 2: 엔티티 간 관계 정보
        relationships = retrieval_result.get("relationships", [])
        if relationships:
            relation_section = self._build_relation_section(relationships, max_relation_tokens)
            if relation_section:
                sections.append(relation_section)

        # 섹션 3: 관련 청크 (naive 모드에서 사용)
        chunks = retrieval_result.get("chunks", [])
        if chunks:
            chunk_section = self._build_chunk_section(chunks, max_paper_tokens)
            if chunk_section:
                sections.append(chunk_section)

        # 섹션 4: 출처 논문 요약
        paper_ids = retrieval_result.get("paper_ids", [])
        if paper_ids and paper_graph:
            paper_section = self._build_paper_section(
                paper_ids, paper_graph, max_paper_tokens
            )
            if paper_section:
                sections.append(paper_section)

        context = "\n\n".join(sections)
        return context if context else "No relevant information found in the knowledge graph."

    def _build_entity_section(
        self, entities: List[Dict[str, Any]], max_tokens: int
    ) -> str:
        """엔티티 정보 섹션"""
        lines = ["## Key Entities"]
        current_len = 0

        for entity in entities:
            name = entity.get("name", "")
            etype = entity.get("type", "")
            desc = entity.get("description", "")
            score = entity.get("match_score", 0)

            line = f"- **{name}** [{etype}] (relevance: {score:.2f}): {desc}"

            if current_len + len(line) > max_tokens:
                break
            lines.append(line)
            current_len += len(line)

        return "\n".join(lines) if len(lines) > 1 else ""

    def _build_relation_section(
        self, relationships: List[Dict[str, Any]], max_tokens: int
    ) -> str:
        """관계 정보 섹션"""
        lines = ["## Entity Relationships"]
        current_len = 0

        for rel in relationships:
            source = rel.get("source", "")
            target = rel.get("target", "")
            desc = rel.get("description", "")
            keywords = ", ".join(rel.get("keywords", []))

            line = f"- {source} → {target}: {desc}"
            if keywords:
                line += f" [themes: {keywords}]"

            if current_len + len(line) > max_tokens:
                break
            lines.append(line)
            current_len += len(line)

        return "\n".join(lines) if len(lines) > 1 else ""

    def _build_chunk_section(
        self, chunks: List[Dict[str, Any]], max_tokens: int
    ) -> str:
        """청크 텍스트 섹션"""
        lines = ["## Relevant Text Passages"]
        current_len = 0

        for i, chunk in enumerate(chunks, 1):
            text = chunk.get("text", "")[:500]
            score = chunk.get("match_score", 0)

            line = f"\n[Passage {i}] (relevance: {score:.2f})\n{text}"

            if current_len + len(line) > max_tokens:
                break
            lines.append(line)
            current_len += len(line)

        return "\n".join(lines) if len(lines) > 1 else ""

    def _build_paper_section(
        self,
        paper_ids: List[str],
        paper_graph: nx.MultiDiGraph,
        max_tokens: int,
    ) -> str:
        """출처 논문 요약 섹션"""
        lines = ["## Source Papers"]
        current_len = 0

        for paper_id in paper_ids:
            if paper_id not in paper_graph:
                continue

            paper = paper_graph.nodes[paper_id]
            title = paper.get("title", paper_id)
            authors = ", ".join(paper.get("authors", [])[:3])
            year = paper.get("published_date", "")[:4]
            abstract = paper.get("abstract", "")[:300]

            line = f"- **{title}**"
            if authors:
                line += f" ({authors}"
                if year:
                    line += f", {year}"
                line += ")"
            if abstract:
                line += f"\n  {abstract}..."

            if current_len + len(line) > max_tokens:
                break
            lines.append(line)
            current_len += len(line)

        return "\n".join(lines) if len(lines) > 1 else ""

    def build_structured_context(
        self, retrieval_result: Dict[str, Any], query: str
    ) -> Dict[str, Any]:
        """구조화된 JSON 컨텍스트 (API 응답용)"""
        return {
            "query": query,
            "entities": [
                {
                    "name": e.get("name", ""),
                    "type": e.get("type", ""),
                    "description": e.get("description", ""),
                    "relevance": e.get("match_score", 0),
                }
                for e in retrieval_result.get("entities", [])
            ],
            "relationships": [
                {
                    "source": r.get("source", ""),
                    "target": r.get("target", ""),
                    "description": r.get("description", ""),
                    "keywords": r.get("keywords", []),
                }
                for r in retrieval_result.get("relationships", [])
            ],
            "paper_count": len(retrieval_result.get("paper_ids", [])),
            "chunk_count": len(retrieval_result.get("chunks", [])),
        }
