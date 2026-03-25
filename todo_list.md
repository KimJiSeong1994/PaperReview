# ArxivQA 기반 검색 에이전트 고도화 로드맵

## Stage 1: 즉시 구축 (GPU 불필요, 1-2주)

### 1.1 ReAct 멀티턴 검색 에이전트
- [ ] `app/SearchAgent/react_search_agent.py` 신규 생성
- [ ] Tool 4종 구현 (keyword_search, semantic_search, read_abstract, finish)
- [ ] 멀티턴 루프 (검색→분석→재쿼리, max 3턴)
- [ ] 기존 SearchAgent의 arXiv/OpenAlex API 재사용

### 1.2 Rubric 기반 결과 평가 (RaR-Implicit)
- [ ] `app/QueryAgent/rubric_evaluator.py` 신규 생성
- [ ] 4차원 rubric (다양성/포괄성/사려깊음/관련성)
- [ ] LLM Judge 호출 (gpt-4o-mini)
- [ ] 평가 미충족 시 재검색 트리거

### 1.3 쿼리 다양화
- [ ] `query_analyzer.py`에 `diversify_queries()` 추가
- [ ] Jaccard 기반 diversity 보장 (ArxivQA P_query_diversity 역활용)
- [ ] Intent별 다양화 전략 (동의어/상위어/하위어)

### 1.4 난이도 기반 검색 전략 분기
- [ ] `query_analyzer.py`에 `classify_difficulty()` 추가
- [ ] Easy: 단일 검색, fast_mode / Medium: 다양화 3쿼리 / Hard: 멀티턴 3턴
- [ ] `routers/search.py`에 분기 로직 적용

### 1.5 초록 기반 정밀 재랭킹
- [ ] `hybrid_ranker.py`에 `rerank_with_abstracts()` 추가
- [ ] Top-20 초록 LLM 재점수
- [ ] 세트 다양성 보너스

### 1.6 ArxivQA 게이트 검증
- [ ] 4가지 게이트 (중복/제출/인용/제한) 구현
- [ ] 결과 검증 후 게이트 미통과 시 재시도

### 1.7 API + 프론트엔드 통합
- [ ] `/api/deep-search` 엔드포인트 추가
- [ ] 프론트엔드 "Deep Search" 모드 토글

---

## Stage 2: 데이터 구축 (GPU 불필요, 2-4주)

### 2.1 arXiv 코퍼스 수집
- [ ] CS/ML 카테고리 15만편 초록 수집
- [ ] `data/arxiv_corpus.jsonl` 저장

### 2.2 QA 데이터셋 생성
- [ ] PaperSearchQA 파이프라인 적용
- [ ] GPT-4o로 초록→질문 변환 (~$200)
- [ ] 6만 QA 쌍 생성

### 2.3 난이도 라벨링
- [ ] Easy/Medium/Hard 자동 분류 + 수동 검증

### 2.4 Ground Truth 구축
- [ ] 200개 쿼리에 Deep Research Agent로 정답 수집
- [ ] 수동 큐레이션 (200 × 10 paper IDs)

### 2.5 평가 벤치마크
- [ ] Recall@10 측정 파이프라인
- [ ] 다중 LLM Judge 교차 검증

---

## Stage 3: RL Fine-tuning (GPU 필요, 4-8주)

### 3.1 학습 인프라
- [ ] SkyRL-Agent 프레임워크 설정
- [ ] Qwen3-8B 베이스 모델 준비
- [ ] AWS p4d.24xlarge 인스턴스 설정

### 3.2 RaR-Implicit 학습
- [ ] GRPO + RaR 리워드 구현
- [ ] LLM Judge (GPT-4o-mini) 연동
- [ ] 250 epochs, LR=1e-6, 8 rollouts/sample

### 3.3 평가 및 배포
- [ ] Stage 2 벤치마크로 recall 측정
- [ ] 프론트엔드 모델 스위칭 (기존 vs fine-tuned)
- [ ] A/B 테스트

---

## 파일 변경 계획

### 신규 파일
| 파일 | Stage | 설명 |
|------|-------|------|
| `app/SearchAgent/react_search_agent.py` | 1.1 | ReAct 멀티턴 검색 에이전트 |
| `app/QueryAgent/rubric_evaluator.py` | 1.2 | RaR-style 4차원 평가 |
| `src/graph_rag/feedback_ranker.py` | 1.7 | 사용자 피드백 부스팅 (추후) |

### 수정 파일
| 파일 | Stage | 변경 |
|------|-------|------|
| `app/QueryAgent/query_analyzer.py` | 1.3, 1.4 | diversify_queries, classify_difficulty |
| `src/graph_rag/hybrid_ranker.py` | 1.5 | rerank_with_abstracts |
| `routers/search.py` | 1.7 | /api/deep-search + 난이도 분기 |
| `routers/deps/agents.py` | 1.7 | 신규 에이전트 싱글턴 |
| `web-ui/src/App.tsx` | 1.7 | Deep Search 모드 토글 |

---

## 예상 성과

| 지표 | 현재 | Stage 1 | Stage 3 |
|------|------|---------|---------|
| 단일턴 recall | ~0.3 | ~0.45 | ~0.58 |
| 멀티턴 recall | N/A | ~0.50 | ~0.58+ |
| 쿼리 다양성 | 1개 | 3-5개 | 학습 최적화 |
| 결과 평가 | pass/fail | 4차원 rubric | 학습된 rubric |
| 응답 (easy) | 30-90초 | 5-15초 | 3-10초 |
| 응답 (hard) | 30-90초 | 60-120초 | 30-60초 |
