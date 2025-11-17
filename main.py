import os
import sys
import argparse
from dotenv import load_dotenv

# .env 파일에서 환경 변수 로드
load_dotenv()

sys.path.append('src')
sys.path.append('app/SearchAgent')
from search_agent import SearchAgent
from app.LangGraphUI import run_langgraph_cli

def main(queries=None, max_results=5, openai_api_key=None):
    # OpenAI API 키 설정 (환경 변수 또는 인자로 전달)
    api_key = openai_api_key or os.getenv('OPENAI_API_KEY')
    agent = SearchAgent(openai_api_key=api_key)
    
    print('='*70)
    print('📚 논문 검색 및 수집 시스템')
    print('='*70)
    
    # 검색 키워드 입력
    if queries is None or len(queries) == 0:
        print('\n검색 키워드를 입력하세요 (쉼표로 구분, 예: machine learning, deep learning)')
        user_input = input('키워드: ').strip()
        
        if not user_input:
            print('❌ 키워드가 입력되지 않았습니다.')
            return
        
        search_queries = [q.strip() for q in user_input.split(',') if q.strip()]
    else:
        search_queries = queries
    
    # 기존 저장된 논문 수 확인
    initial_count = agent.get_saved_papers_count()
    print(f'\n현재 저장된 논문: {initial_count}개')
    
    # 각 키워드로 검색 및 저장
    total_new = 0
    total_duplicates = 0
    
    for i, query in enumerate(search_queries, 1):
        print(f'\n[{i}/{len(search_queries)}] 검색 중: "{query}"')
        
        # 검색 실행
        results = agent.search_all_sources(query, max_results_per_source=max_results)
        total_found = sum(len(papers) for papers in results.values())
        print(f'  → {total_found}개 논문 발견')
        
        # 저장
        save_result = agent.save_papers(results, query)
        
        if save_result['success']:
            total_new += save_result['new_papers']
            total_duplicates += save_result['duplicates']
            print(f'  ✓ 새로 저장: {save_result["new_papers"]}개, 중복: {save_result["duplicates"]}개')
            
        else:
            print(f'  ✗ 저장 실패: {save_result.get("error", "Unknown")}')
    
    # 최종 결과
    final_count = agent.get_saved_papers_count()
    print(f'\n{"="*70}')
    print('✅ 수집 완료!')
    print('='*70)
    print(f'\n총 저장된 논문: {final_count}개')
    print(f'새로 추가: {total_new}개')
    print(f'중복 제외: {total_duplicates}개')
    print(f'\n💾 저장 위치: data/raw/papers.json')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='논문 검색 및 수집 시스템')
    parser.add_argument('-q', '--queries', nargs='+', help='검색 키워드 (예: -q "machine learning" "deep learning")')
    parser.add_argument('-n', '--max-results', type=int, default = 50, help='소스당 최대 결과 수 (기본값: 20)')
    parser.add_argument('-r', '--collect-references', action='store_true', help='논문의 참고문헌도 수집')
    parser.add_argument('--max-refs', type=int, default=-1, help='논문당 최대 참고문헌 수 (-1: 제약 없음, 기본값: -1)')
    parser.add_argument('--max-papers', type=int, default=None, help='참고문헌 수집할 최대 논문 수')
    parser.add_argument('-t', '--extract-text', action='store_true', help='논문 본문 추출')
    parser.add_argument('--max-texts', type=int, default=None, help='본문 추출할 최대 논문 수')
    parser.add_argument('--openai-api-key', type=str, default=None, help='OpenAI API 키 (또는 OPENAI_API_KEY 환경 변수 사용)')
    parser.add_argument('--langgraph-ui', action='store_true', help='LangGraph CLI UI 실행')
    args = parser.parse_args()

    if args.langgraph_ui:
        run_langgraph_cli()
        sys.exit(0)
    
    # 실행
    main(queries=args.queries, max_results=args.max_results, openai_api_key=args.openai_api_key)
    
    # 참고문헌 수집
    if args.collect_references:
        print('\n' + '='*70)
        print('📖 참고문헌 수집 시작')
        print('='*70)
        
        api_key = args.openai_api_key or os.getenv('OPENAI_API_KEY')
        agent = SearchAgent(openai_api_key=api_key)
        ref_result = agent.collect_references(
            max_references_per_paper=args.max_refs,
            max_papers=args.max_papers
        )
        
        print(f'\n✅ 참고문헌 수집 완료!')
        print(f'   - 처리한 논문: {ref_result["papers_processed"]}개')
        print(f'   - 발견한 참고문헌: {ref_result["references_found"]}개')
        print(f'   - 총 논문 수: {ref_result["total_papers"]}개')
    
    # 본문 추출
    if args.extract_text:
        print('\n' + '='*70)
        print('📝 논문 본문 추출 시작')
        print('='*70)
        
        api_key = args.openai_api_key or os.getenv('OPENAI_API_KEY')
        agent = SearchAgent(openai_api_key=api_key)
        text_result = agent.extract_full_texts(max_papers=args.max_texts)
        
        print(f'\n✅ 본문 추출 완료!')
        print(f'   - 처리한 논문: {text_result["papers_processed"]}개')
        print(f'   - 본문 추출 성공: {text_result["texts_extracted"]}개')
        print(f'   - 이미 존재: {text_result["already_exists"]}개')
        print(f'   - 실패 (Abstract 사용): {text_result["failed"]}개')
        print(f'   - 총 논문 수: {text_result["total_papers"]}개')
