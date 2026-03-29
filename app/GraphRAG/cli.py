"""
Graph RAG CLI 인터페이스
"""
import argparse


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
    print("[INFO] 응답")
    print("="*70)
    print(result.get('answer', 'No answer generated'))

    print("\n" + "="*70)
    print("[INFO] 참고 논문")
    print("="*70)
    for i, paper in enumerate(result.get('source_papers', []), 1):
        print(f"\n[{i}] {paper.get('title', 'N/A')}")
        print(f"    관련도: {paper.get('relevance_score', 0):.3f}")
        print(f"    저자: {', '.join(paper.get('authors', []))}")
        print(f"    URL: {paper.get('url', 'N/A')}")

def light_build(args):
    """LightRAG 지식 그래프 구축"""
    agent = GraphRAGAgent(
        papers_json_path=args.papers_json,
        graph_path=args.graph_path,
        light_rag_dir=args.light_rag_dir,
    )
    agent.build_knowledge_graph(
        max_concurrent=args.max_concurrent,
        extraction_model=args.extraction_model,
    )


def light_query(args):
    """LightRAG 쿼리 실행"""
    agent = GraphRAGAgent(
        graph_path=args.graph_path,
        light_rag_dir=args.light_rag_dir,
        llm_model=args.model,
    )
    result = agent.light_query(
        query=args.query,
        mode=args.mode,
        top_k=args.top_k,
        temperature=args.temperature,
    )

    print("\n" + "=" * 70)
    print(f"[LightRAG] Response (mode={result.get('mode', 'hybrid')})")
    print("=" * 70)
    print(result.get("answer", "No answer generated"))

    # 키워드 표시
    keywords = result.get("keywords", {})
    if keywords:
        print(f"\n[Keywords] Low: {keywords.get('low_level', [])}")
        print(f"           High: {keywords.get('high_level', [])}")

    # 검색된 엔티티
    entities = result.get("retrieval", {}).get("entities", [])
    if entities:
        print(f"\n[Entities] ({len(entities)} found)")
        for e in entities[:5]:
            print(f"  - {e.get('name', '')} [{e.get('type', '')}]: {e.get('description', '')[:80]}")

    # 출처 논문
    papers = result.get("source_papers", [])
    if papers:
        print(f"\n[Source Papers] ({len(papers)} found)")
        for i, p in enumerate(papers[:5], 1):
            print(f"  [{i}] {p.get('title', 'N/A')}")
            authors = ", ".join(p.get("authors", [])[:3])
            if authors:
                print(f"      {authors}")

    # 통계
    stats = result.get("statistics", {})
    if stats:
        print(f"\n[Stats] Entities: {stats.get('entities_found', 0)}, "
              f"Relations: {stats.get('relationships_found', 0)}, "
              f"Papers: {stats.get('papers_found', 0)}")


def light_status(args):
    """LightRAG 지식 그래프 상태 확인"""
    agent = GraphRAGAgent(light_rag_dir=args.light_rag_dir)
    stats = agent.get_kg_stats()

    print("\n" + "=" * 70)
    print("[LightRAG] Knowledge Graph Status")
    print("=" * 70)

    import json
    print(json.dumps(stats, indent=2, ensure_ascii=False))


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
    query_parser.add_argument('--model', default='gpt-4.1', help='LLM 모델')
    query_parser.add_argument('--top-k', type=int, default=10, help='초기 검색 상위 K개')
    query_parser.add_argument('--max-papers', type=int, default=10, help='최대 논문 수')
    query_parser.add_argument('--expansion-strategy', default='hybrid', choices=['citation', 'similarity', 'hybrid'], help='확장 전략')
    query_parser.add_argument('--temperature', type=float, default=0.7, help='LLM temperature')

    # light-build 명령어 (LightRAG)
    lb_parser = subparsers.add_parser('light-build', help='LightRAG 지식 그래프 구축')
    lb_parser.add_argument('--papers-json', default='data/raw/papers.json', help='논문 JSON 파일 경로')
    lb_parser.add_argument('--graph-path', default='data/graph/paper_graph.pkl', help='논문 그래프 경로')
    lb_parser.add_argument('--light-rag-dir', default='data/light_rag', help='LightRAG 데이터 디렉토리')
    lb_parser.add_argument('--max-concurrent', type=int, default=4, help='동시 LLM 호출 수')
    lb_parser.add_argument('--extraction-model', default='gpt-4o-mini', help='엔티티 추출용 LLM 모델')

    # light-query 명령어 (LightRAG)
    lq_parser = subparsers.add_parser('light-query', help='LightRAG 쿼리 실행')
    lq_parser.add_argument('query', help='검색 쿼리')
    lq_parser.add_argument('--graph-path', default='data/graph/paper_graph.pkl', help='논문 그래프 경로')
    lq_parser.add_argument('--light-rag-dir', default='data/light_rag', help='LightRAG 데이터 디렉토리')
    lq_parser.add_argument('--model', default='gpt-4.1', help='응답 생성 LLM 모델')
    lq_parser.add_argument('--mode', default='hybrid', choices=['naive', 'local', 'global', 'hybrid', 'mix'], help='검색 모드')
    lq_parser.add_argument('--top-k', type=int, default=10, help='검색 상위 K개')
    lq_parser.add_argument('--temperature', type=float, default=0.7, help='LLM temperature')

    # light-status 명령어 (LightRAG)
    ls_parser = subparsers.add_parser('light-status', help='LightRAG 지식 그래프 상태')
    ls_parser.add_argument('--light-rag-dir', default='data/light_rag', help='LightRAG 데이터 디렉토리')

    args = parser.parse_args()

    if args.command == 'build':
        build_graph(args)
    elif args.command == 'query':
        query(args)
    elif args.command == 'light-build':
        light_build(args)
    elif args.command == 'light-query':
        light_query(args)
    elif args.command == 'light-status':
        light_status(args)
    else:
        parser.print_help()

if __name__ == '__main__':
    main()

