# 검색 엔진 최적화 및 고도화 로드맵

## P0: 즉시 적용 (1-2일)

### P0-1. 난이도 기반 검색 전략 분기
- [x] `classify_difficulty()` 구현 (query_analyzer.py)
- [ ] `/api/deep-search`에서 max_turns 동적 설정 (easy=1, medium=2, hard=3)
- [ ] metadata에 difficulty + max_turns 기록

### P0-2. diversify_queries 캐시 버그 수정
- [ ] `self._get_from_cache` → `_get_from_cache` (모듈 레벨 함수)
- [ ] `self._set_in_cache` → `_set_in_cache`
- [ ] 캐시 키: `_cache_key()` 함수 사용으로 변경

### P0-3. HybridRanker ThreadPoolExecutor 재사용
- [ ] 모듈 레벨 `_HYDE_EXECUTOR = ThreadPoolExecutor(max_workers=4)`
- [ ] `atexit.register` 등록
- [ ] `_generate_hyde_embedding`에서 재사용

---

## P1: 단기 (1-2주)

### P1-3. 캐시 키 정규화
- [ ] 유니코드 NFKC 정규화
- [ ] 영문 stopword 제거
- [ ] 다중 공백 → 단일 공백
- [ ] (토큰 정렬/복수형 제외 — 과도한 정규화 위험)

### P1-4. Cross-encoder Reranker (RRF 5번째 신호)
- [ ] `HybridRanker`에 `_compute_cross_encoder_scores()` 추가
- [ ] `LocalRelevanceScorer` 싱글턴 재사용
- [ ] `_cross_encoder_score` 첨부 → `RelevanceFilter` 중복 호출 방지
- [ ] RRF에 `rrf_cross_encoder` 항 추가

### P1-5. 인기 쿼리 동적 관리
- [ ] `collections.Counter` 기반 검색 빈도 카운터
- [ ] `data/cache/query_freq.json` 주기적 영속화 (filelock)
- [ ] `_get_popular_queries()` 동적 반환 (빈도순 + seed 보충)
- [ ] `_prefetch_popular_queries`에서 동적 목록 사용

---

## P2: 중기 (1-2달)

### P2-1. 그래프 O(n²) → FAISS ANN
- [ ] `papers.py` Jaccard 비교 → 임베딩 기반 ANN
- [ ] FAISS IndexFlatIP 활용

### P2-2. JSON → SQLite 마이그레이션
- [ ] `data/papers.json` → SQLite DB
- [ ] FTS5 전문 검색 인덱스

### P2-3. 다국어 임베딩 모델
- [ ] multilingual-e5-large 또는 text-embedding-3-large
- [ ] 쿼리 언어 감지 → 모델 선택

### P2-4. SSE 스트리밍 응답
- [ ] `/api/deep-search` → Server-Sent Events
- [ ] 턴별 중간 결과 스트리밍
- [ ] 프론트엔드 실시간 프로그레스

### P2-5. 사용자 피드백 수집
- [ ] "유용함/관련없음" 피드백 UI
- [ ] Rubric 가중치 자동 조정

---

## P3: 장기 (3-6달)

### P3-1. Recall 벤치마크 구축
- [ ] arXiv CS/ML 15만편 초록 수집
- [ ] GPT-4o로 6만 QA 쌍 생성 (~$200)
- [ ] 200 쿼리 수동 큐레이션 Ground Truth
- [ ] Recall@10 자동 측정 파이프라인

### P3-2. RL Fine-tuning
- [ ] Qwen3-8B + SkyRL-Agent + GRPO + RaR
- [ ] 250 epochs, LR=1e-6, 8 rollouts
- [ ] AWS p4d.24xlarge (~$5000-10000)

### P3-3. 멀티모달 논문 검색
- [ ] PDF에서 figure/table 추출
- [ ] CLIP 임베딩 기반 이미지 검색

---

## 구현 순서 (의존성 기반)

```
P0-2 (버그 수정) → P0-3 (ThreadPool) → P0-1 (난이도 분기)
                                           ↓
P1-3 (캐시 정규화) → P1-5 (인기 쿼리, P1-3 의존)
P0-3 → P1-4 (Cross-encoder, P0-3 권장)
```

## 예상 성과

| 지표 | 현재 | P0 후 | P1 후 | P3 후 |
|------|------|-------|-------|-------|
| Easy 응답 시간 | 60-145초 | 15-30초 | 10-20초 | 3-10초 |
| Hard 응답 시간 | 60-145초 | 60-145초 | 50-120초 | 30-60초 |
| 캐시 히트율 | ~20% | ~20% | ~35% | ~50% |
| Precision@10 | 추정 0.5 | 0.5 | +15-25% | +30% |
| Recall@10 | 추정 0.3 | 0.35 | 0.45 | 0.58 |
