from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, TypedDict

try:
    from langgraph.graph import StateGraph, START, END

    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    START = END = StateGraph = None  # type: ignore

from app.GraphRAG.rag_agent import GraphRAGAgent


class LangGraphState(TypedDict, total=False):
    query: str
    result: Dict[str, Any]


def _build_graph(agent: GraphRAGAgent):
    if not LANGGRAPH_AVAILABLE:
        raise ImportError(
            "langgraph 패키지가 설치되어 있지 않습니다. `pip install langgraph`로 설치 후 다시 실행하세요."
        )

    builder = StateGraph(LangGraphState)

    def answer_node(state: LangGraphState) -> LangGraphState:
        query = state.get("query", "").strip()
        if not query:
            raise ValueError("질문이 비어있습니다.")

        response = agent.query(query)
        return {"result": response}

    builder.add_node("answer", answer_node)
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)

    return builder.compile()


class LangGraphCLI:
    """간단한 터미널 UI"""

    def __init__(self, graph, agent: GraphRAGAgent):
        self.graph = graph
        self.agent = agent

    def run(self):
        print("=" * 70)
        print("[INFO] LangGraph CLI - Graph RAG Paper Explorer")
        print("=" * 70)
        print("질문을 입력하면 그래프 기반 RAG 응답을 생성합니다. (종료: exit/quit)\n")

        while True:
            try:
                user_input = input("질문 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n종료합니다.")
                break

            if not user_input:
                continue

            if user_input.lower() in {"exit", "quit"}:
                print("안녕히 가세요!")
                break

            try:
                result_state = self.graph.invoke({"query": user_input})
                self._render_response(result_state.get("result", {}))
            except FileNotFoundError as exc:
                print(f"[에러] 그래프 파일을 찾을 수 없습니다: {exc}")
            except Exception as exc:  # pylint: disable=broad-except
                print(f"[에러] 요청 처리 중 문제가 발생했습니다: {exc}")

    def _render_response(self, result: Dict[str, Any]):
        answer = result.get("answer")
        sources = result.get("source_papers", [])

        if not answer:
            print("응답을 생성하지 못했습니다.\n")
            return

        print("\n[INFO] 답변")
        print("-" * 70)
        print(answer)
        print("-" * 70)

        if sources:
            print("\n[INFO] 참조 논문")
            for idx, paper in enumerate(sources, 1):
                title = paper.get("title", "제목 없음")
                score = paper.get("relevance_score", 0.0)
                url = paper.get("url", "")
                authors = ", ".join(paper.get("authors", [])[:3])
                print(f"[{idx}] {title} (score={score:.3f})")
                if authors:
                    print(f"    저자: {authors}")
                if url:
                    print(f"    URL : {url}")
        print()


def run_langgraph_cli(
    papers_json_path: str = "data/raw/papers.json",
    graph_path: str = "data/graph/paper_graph.pkl",
    embeddings_index_path: str = "data/embeddings/paper_embeddings.index",
    id_mapping_path: str = "data/embeddings/paper_id_mapping.json",
):
    """
    LangGraph 기반 CLI 실행 함수
    """
    if not LANGGRAPH_AVAILABLE:
        print("langgraph 패키지가 설치되어 있지 않아 CLI를 실행할 수 없습니다.")
        print("`pip install langgraph` 명령으로 설치한 뒤 다시 시도하세요.")
        return

    agent = GraphRAGAgent(
        papers_json_path=papers_json_path,
        graph_path=graph_path,
        embeddings_index_path=embeddings_index_path,
        id_mapping_path=id_mapping_path,
    )

    try:
        agent.initialize_response_generator()
    except FileNotFoundError as exc:
        print(f"그래프 또는 임베딩 파일을 찾을 수 없습니다: {exc}")
        print("먼저 `python build_graph.py`를 실행해 그래프를 생성하세요.")
        return

    app_graph = _build_graph(agent)
    LangGraphCLI(app_graph, agent).run()


