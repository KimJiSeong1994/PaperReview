"""
Light Response Generator - LightRAG 전체 파이프라인 오케스트레이터

쿼리 키워드 추출 → 이중 레벨 검색 → 컨텍스트 조립 → LLM 응답 생성
의 전체 파이프라인을 관리한다.
"""
import os
import networkx as nx
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

from .kg_storage import KGStorage
from .keyword_extractor import KeywordExtractor
from .light_retriever import LightRetriever
from .light_context_builder import LightContextBuilder

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class LightResponseGenerator:
    """LightRAG 전체 파이프라인 오케스트레이터"""

    SYSTEM_PROMPT = """You are an expert academic research assistant with deep knowledge of scientific papers.
You provide comprehensive, well-structured answers based on the knowledge graph context provided.
Always cite specific entities, methods, and papers when making claims.
If the context is insufficient to fully answer the query, acknowledge the limitations."""

    RESPONSE_PROMPT = """Based on the following knowledge graph context about academic papers, answer the user's query comprehensively.

## Knowledge Graph Context
{context}

## User Query
{query}

## Instructions
1. Provide a direct, comprehensive answer to the query
2. Reference specific entities (methods, datasets, concepts) from the context
3. Explain relationships between entities when relevant
4. Mention source papers to support key claims
5. Note any gaps or limitations in the available information

Answer:"""

    def __init__(
        self,
        kg: nx.Graph,
        paper_graph: Optional[nx.MultiDiGraph] = None,
        storage: Optional[KGStorage] = None,
        llm_model: str = "gpt-4",
        storage_dir: str = "data/light_rag",
    ):
        import ssl
        try:
            ssl._create_default_https_context = ssl._create_unverified_context
        except AttributeError:
            pass

        self.kg = kg
        self.paper_graph = paper_graph
        self.storage = storage or KGStorage(storage_dir)

        api_key = os.getenv("OPENAI_API_KEY")
        if not OPENAI_AVAILABLE or not api_key:
            raise ValueError("OpenAI package and API key are required")

        self.llm_client = OpenAI(api_key=api_key)
        self.llm_model = llm_model

        self.keyword_extractor = KeywordExtractor()
        self.retriever = LightRetriever(kg, paper_graph, self.storage)
        self.context_builder = LightContextBuilder()

    def generate(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 10,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """전체 LightRAG 파이프라인 실행"""

        # 1. 쿼리 키워드 추출
        print(f"  [1/4] Extracting keywords...")
        keywords = self.keyword_extractor.extract_keywords(query)
        print(f"    Low-level: {keywords['low_level']}")
        print(f"    High-level: {keywords['high_level']}")

        # 2. 이중 레벨 검색
        print(f"  [2/4] Retrieving (mode={mode})...")
        retrieval_result = self.retriever.retrieve(query, keywords, mode=mode, top_k=top_k)
        print(f"    Found: {len(retrieval_result.get('entities', []))} entities, "
              f"{len(retrieval_result.get('relationships', []))} relations, "
              f"{len(retrieval_result.get('paper_ids', []))} papers")

        # 3. 컨텍스트 조립
        print(f"  [3/4] Building context...")
        context = self.context_builder.build_context(
            retrieval_result, query, self.paper_graph
        )

        # 4. LLM 응답 생성
        print(f"  [4/4] Generating response...")
        answer = self._generate_llm_response(context, query, temperature)

        # 결과 조립
        structured_context = self.context_builder.build_structured_context(
            retrieval_result, query
        )

        return {
            "answer": answer,
            "query": query,
            "mode": mode,
            "keywords": keywords,
            "retrieval": {
                "entities": structured_context["entities"][:10],
                "relationships": structured_context["relationships"][:10],
                "paper_count": structured_context["paper_count"],
            },
            "source_papers": self._get_source_papers(retrieval_result.get("paper_ids", [])),
            "statistics": {
                "entities_found": len(retrieval_result.get("entities", [])),
                "relationships_found": len(retrieval_result.get("relationships", [])),
                "papers_found": len(retrieval_result.get("paper_ids", [])),
                "chunks_found": len(retrieval_result.get("chunks", [])),
                "kg_total_nodes": self.kg.number_of_nodes(),
                "kg_total_edges": self.kg.number_of_edges(),
            },
        }

    def _generate_llm_response(
        self, context: str, query: str, temperature: float = 0.7
    ) -> str:
        """LLM 응답 생성"""
        prompt = self.RESPONSE_PROMPT.format(context=context, query=query)

        try:
            response = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error generating response: {str(e)}"

    def _get_source_papers(self, paper_ids: list) -> list:
        """출처 논문 정보 수집"""
        papers = []
        if not self.paper_graph:
            return papers

        for pid in paper_ids[:15]:
            if pid in self.paper_graph:
                paper = self.paper_graph.nodes[pid]
                papers.append({
                    "title": paper.get("title", pid),
                    "authors": paper.get("authors", [])[:5],
                    "published_date": paper.get("published_date", ""),
                    "url": paper.get("url", ""),
                    "source": paper.get("source", ""),
                })

        return papers
