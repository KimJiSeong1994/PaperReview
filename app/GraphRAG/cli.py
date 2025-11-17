"""
Graph RAG CLI 인터페이스
"""
import argparse
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '../../src'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))

from app.GraphRAG.rag_agent import GraphRAGAgent

def build_graph(args):
    """그래프 구축"""
    agent = GraphRAGAgent(
        papers_json_path=args.papers_json,
        graph_path=args.graph_path,
        embeddings_index_path=args.embeddings_index,
        id_mapping_path=args.id_mapping
    )
    
    agent.build_graph_from_papers(
        create_citation_edges=args.citation_edges,
        create_similarity_edges=args.similarity_edges,
        similarity_threshold=args.similarity_threshold,
        similarity_top_k=args.similarity_top_k
    )

def query(args):
    """쿼리 실행"""
    agent = GraphRAGAgent(
        graph_path=args.graph_path,
        embeddings_index_path=args.embeddings_index,
        id_mapping_path=args.id_mapping,
        llm_model=args.model
    )
    
    result = agent.query(
        query=args.query,
        top_k=args.top_k,
        max_papers=args.max_papers,
        expansion_strategy=args.expansion_strategy,
        temperature=args.temperature
    )
    
    print("\n" + "="*70)
    print("📝 응답")
    print("="*70)
    print(result.get('answer', 'No answer generated'))
    
    print("\n" + "="*70)
    print("📚 참고 논문")
    print("="*70)
    for i, paper in enumerate(result.get('source_papers', []), 1):
        print(f"\n[{i}] {paper.get('title', 'N/A')}")
        print(f"    관련도: {paper.get('relevance_score', 0):.3f}")
        print(f"    저자: {', '.join(paper.get('authors', []))}")
        print(f"    URL: {paper.get('url', 'N/A')}")

def main():
    parser = argparse.ArgumentParser(description='Graph RAG 시스템')
    subparsers = parser.add_subparsers(dest='command', help='명령어')
    
    # build 명령어
    build_parser = subparsers.add_parser('build', help='그래프 구축')
    build_parser.add_argument('--papers-json', default='data/raw/papers.json', help='논문 JSON 파일 경로')
    build_parser.add_argument('--graph-path', default='data/graph/paper_graph.pkl', help='그래프 저장 경로')
    build_parser.add_argument('--embeddings-index', default='data/embeddings/paper_embeddings.index', help='임베딩 인덱스 경로')
    build_parser.add_argument('--id-mapping', default='data/embeddings/paper_id_mapping.json', help='ID 매핑 파일 경로')
    build_parser.add_argument('--citation-edges', action='store_true', default=True, help='Citation 엣지 생성')
    build_parser.add_argument('--similarity-edges', action='store_true', default=True, help='Similarity 엣지 생성')
    build_parser.add_argument('--similarity-threshold', type=float, default=0.7, help='유사도 임계값')
    build_parser.add_argument('--similarity-top-k', type=int, default=10, help='유사도 상위 K개')
    
    # query 명령어
    query_parser = subparsers.add_parser('query', help='쿼리 실행')
    query_parser.add_argument('query', help='검색 쿼리')
    query_parser.add_argument('--graph-path', default='data/graph/paper_graph.pkl', help='그래프 파일 경로')
    query_parser.add_argument('--embeddings-index', default='data/embeddings/paper_embeddings.index', help='임베딩 인덱스 경로')
    query_parser.add_argument('--id-mapping', default='data/embeddings/paper_id_mapping.json', help='ID 매핑 파일 경로')
    query_parser.add_argument('--model', default='gpt-4', help='LLM 모델')
    query_parser.add_argument('--top-k', type=int, default=10, help='초기 검색 상위 K개')
    query_parser.add_argument('--max-papers', type=int, default=10, help='최대 논문 수')
    query_parser.add_argument('--expansion-strategy', default='hybrid', choices=['citation', 'similarity', 'hybrid'], help='확장 전략')
    query_parser.add_argument('--temperature', type=float, default=0.7, help='LLM temperature')
    
    args = parser.parse_args()
    
    if args.command == 'build':
        build_graph(args)
    elif args.command == 'query':
        query(args)
    else:
        parser.print_help()

if __name__ == '__main__':
    main()

