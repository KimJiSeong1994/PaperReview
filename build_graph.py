"""
Graph RAG 그래프 구축 스크립트
"""
import sys
import os

sys.path.append('src')
sys.path.append('app/GraphRAG')

from app.GraphRAG.rag_agent import GraphRAGAgent

def main():
    print("="*70)
    print("🚀 Graph RAG 그래프 구축")
    print("="*70)
    
    agent = GraphRAGAgent()
    
    # 그래프 구축
    graph = agent.build_graph_from_papers(
        create_citation_edges=True,
        create_similarity_edges=True,
        similarity_threshold=0.7,
        similarity_top_k=10
    )
    
    print("\n" + "="*70)
    print("✅ 그래프 구축 완료!")
    print("="*70)
    print(f"\n다음 명령으로 쿼리를 실행할 수 있습니다:")
    print(f"  python -m app.GraphRAG.cli query \"your query here\"")

if __name__ == '__main__':
    main()

