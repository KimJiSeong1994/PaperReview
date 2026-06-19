# 개인화 논문 추천 고도화 검토 및 로드맵

## 목적과 범위

이 문서는 현재 PaperReviewAgent의 논문 추천 파이프라인을 코드 근거 기반으로 검토하고, 사용자별 개인화 추천 품질을 높이기 위한 데이터 신호, 랭킹/모델링 개선안, 평가 및 배포 전략을 제안한다. 이번 산출물은 **제안서와 우선순위 로드맵**이며 추천 알고리즘 구현 변경은 포함하지 않는다.

## 현재 파이프라인 요약

### 1. 일일 추천 아티팩트 생성

- `src/daily_recommendations.py::generate_daily_recommendations`는 `users.db`, `bookmarks.db`, `data/raw/papers.json`을 읽어 사용자별 `raw.json` 추천 아티팩트를 쓴다.
- `src/daily_recommendations.py::recommend_for_user`는 사용자 북마크에서 프로필을 만들고 후보 논문을 점수화한다.
- `scripts/generate_daily_recommendations.py`는 위 모듈의 CLI 래퍼이며, `.github/workflows/daily-recommendations.yml`에서 매일 실행된다.
- `docs/daily-recommendations.md`에 따르면 워크플로는 OpenClaw 아티팩트 import를 먼저 시도하고 실패하거나 누락된 사용자는 로컬 생성기로 fallback한다.

### 2. 현재 로컬 개인화 신호

`src/daily_recommendations.py::_user_profile` 기준 현재 프로필은 다음 신호로 구성된다.

| 신호 | 현재 가중 | 의미 |
| --- | ---: | --- |
| 북마크 topic | 5 | 사용자가 저장한 주제 |
| 북마크 title | 4 | 저장 묶음 제목 |
| notes | 2 | 사용자 메모 |
| report 일부 | 1 | 리뷰 보고서 텍스트 |
| 북마크된 paper title | 7 | 가장 강한 관심 논문 신호 |
| authors | 1 | 저자 관심의 약한 proxy |

후보 점수는 `src/daily_recommendations.py::_score_paper`에서 토큰 겹침, 최신성, PDF/DOI/arXiv 보너스를 더해 산출한다. 프로필이 비어 있으면 `fallback_recent=True`로 최근성 중심 추천을 수행한다.

### 3. 추천 조회 API와 아티팩트 계약

- `routers/recommendations.py::list_recommendation_notifications`는 인증된 사용자에 대해 `src.recommendations_artifacts.load_recommendation_artifact` 결과를 그대로 응답 모델에 매핑한다.
- `src/recommendations_artifacts.py::latest_raw_file`은 사용자에게 속한 최신 `raw.json`을 찾고, `::_group_items`는 variant 중복 논문을 `paper_id` 기준으로 묶는다.
- 현재 읽기 경로는 파일 기반이며 `root.glob("**/raw.json")`과 mtime에 의존한다. 사용자 수와 아티팩트 수가 늘면 색인 또는 DB-backed serving 계층이 필요하다.

### 4. 이미 존재하지만 추천에 충분히 연결되지 않은 신호

- `src/events/event_types.py::EventType`에는 `BOOKMARK_ADD`, `BOOKMARK_REMOVE`, `HIGHLIGHT_*`, `REVIEW_*`, `SEARCH_CLICK`, `PAPER_OPEN`, `QUERY_SUBMIT` 등이 정의되어 있다.
- `routers/search.py`는 `QUERY_SUBMIT` 및 `SEARCH_CLICK` 이벤트를 방출한다.
- `routers/bookmarks.py`는 북마크 추가/삭제 및 하이라이트 이벤트를 방출한다.
- `routers/paper_reviews.py`는 리뷰 생성 이벤트를 방출한다.
- `src/graph_rag/hybrid_ranker.py::HybridRanker`는 BM25, semantic, citations, recency, cross-encoder, HyDE/RRF 검색 랭킹 기능을 갖지만 일일 추천 생성기의 사용자 프로필 기반 랭킹에는 아직 직접 재사용되지 않는다.
- `src/graph_rag/ranker.py::PaperRanker`는 PageRank, citation, recency 기반 점수를 제공하므로 장기적으로 graph-aware 추천 신호 후보가 될 수 있다.

## 핵심 품질 격차

1. **개인화가 북마크 텍스트 겹침에 편중됨**  
   클릭, 열람, 검색 질의, 리뷰, 하이라이트, 삭제/무시 같은 행동 신호가 추천 프로필에 반영되지 않는다.

2. **랭킹이 학습/캘리브레이션 없는 휴리스틱임**  
   `_score_paper`의 점수는 사용자별 선호 확률이나 calibrated relevance로 해석하기 어렵고, 사용자별 score distribution 보정도 없다.

3. **한국어/다국어 토큰화가 약함**  
   `_TOKEN_RE`와 stopword 기반 토큰화는 형태소, 복합명사, 한영 synonym, 분야 약어를 충분히 다루지 못한다.

4. **후보 품질 관리가 제한적임**  
   `load_papers`는 title만 있으면 후보로 허용한다. 초록, 식별자, 수집 query, 분야 taxonomy가 부족한 후보는 개인화 점수 품질을 낮춘다.

5. **중복/기열람 논문 제외가 불안정할 수 있음**  
   `_paper_identity_values`와 `paper_id`는 여러 식별자를 사용하지만, 번역 제목·동명이 논문·불완전 DOI/arXiv 메타데이터에 취약하다.

6. **추천 serving 관측성이 부족함**  
   OpenClaw import 실패 시 fallback은 안전하지만, 품질 저하·staleness·사용자별 빈 추천 사유가 API/운영 지표로 충분히 노출되지 않는다.

## 개선 제안

### A. 데이터 신호 계층 확장

| 우선순위 | 신호 | 소스 | 활용 방식 |
| --- | --- | --- | --- |
| P0 | 북마크 add/remove | `routers/bookmarks.py`, `EventType` | positive/negative preference, seen set |
| P0 | 검색 질의와 클릭 | `routers/search.py`, `QUERY_SUBMIT`, `SEARCH_CLICK` | short-term intent, click-through preference |
| P1 | paper open / dwell proxy | `EventType.PAPER_OPEN` | 약한 positive, freshness-sensitive 관심 |
| P1 | 리뷰 생성/수정 | `routers/paper_reviews.py`, `REVIEW_CREATE` | 깊은 관심 주제 및 방법론 profile |
| P1 | 하이라이트/메모 | `HIGHLIGHT_*`, bookmark notes | passage-level 관심 키워드 |
| P2 | 추천 노출/클릭/삭제 | 신규 이벤트 필요 | 추천 품질 학습, fatigue 방지 |
| P2 | GraphRAG/PageRank | `src/graph_rag/*` | citation/community relevance |

권장 설계는 `events -> user_signal_snapshot -> daily_recommendations`의 어댑터 계층이다. 원본 이벤트는 불변 로그로 유지하고, 추천 생성 시점에는 최근 7일/30일/180일의 감쇠 가중 profile snapshot을 읽도록 분리한다.

### B. 후보 생성 개선

1. **다중 후보 소스**
   - 기존 `data/raw/papers.json` 유지.
   - OpenClaw variant별 후보 유지.
   - 검색/북마크 query에서 파생된 related-paper 수집 결과를 후보 pool로 합류.
   - GraphRAG 인접 논문, citation neighbor, 같은 저자/venue/분야 후보를 별도 variant로 생성.

2. **후보 품질 필터**
   - title-only 후보는 fallback 후보로 격하한다.
   - abstract, stable identifier, source, collected_at, search_query가 있는 후보를 personalized rerank 대상 우선순위로 둔다.
   - 같은 DOI/arXiv/openalex_id/title-normalized cluster는 하나의 canonical paper로 묶는다.

3. **탐색 다양성**
   - 상위 N개 안에 동일 topic/author/source가 과밀하지 않도록 MMR 또는 topic quota를 둔다.
   - cold-start 사용자는 global trending + role/최근 query + curriculum 관심 분야 기반으로 시작한다.

### C. 랭킹/모델링 개선

#### 단계 1: 휴리스틱 v2

- `_user_profile`에 이벤트 기반 time-decay 신호를 추가한다.
- `_score_paper`를 다음 breakdown으로 분리한다.
  - content_match: 북마크/메모/검색 질의와 후보 title/abstract/category 유사도
  - behavior_match: 클릭·열람·리뷰와 후보 유사도
  - novelty: 이미 본 논문/저자/주제 감점
  - authority: citation/PageRank/source reliability
  - freshness: 사용자별 최신성 선호 캘리브레이션
  - accessibility: PDF/DOI/arXiv/URL 보너스
- reason 문구는 breakdown의 top contributing factors에서 생성한다.

#### 단계 2: 임베딩 기반 개인화 reranker

- 사용자 profile embedding을 북마크, notes, query, highlights, review text의 time-decayed centroid로 만든다.
- 후보 embedding은 title+abstract+category로 만들고, semantic similarity를 content score로 사용한다.
- `src/graph_rag/hybrid_ranker.py::HybridRanker`의 RRF/cross-encoder 구조를 추천 후보 rerank에도 재사용하되, 검색 query 대신 사용자 profile text/embedding을 입력으로 넣는 adapter를 둔다.
- 스코어는 raw similarity가 아니라 사용자별 percentile 또는 z-score로 보정한다.

#### 단계 3: 학습 기반 랭킹

- 추천 노출, 클릭, 저장, 리뷰 작성, 삭제/무시를 label로 수집한다.
- 초기에는 logistic regression / LambdaMART / lightweight gradient boosting 같은 해석 가능한 모델을 검토한다.
- feature 예시는 user-paper semantic similarity, query overlap, bookmark overlap, author affinity, source affinity, recency preference, citation percentile, novelty, diversity penalty이다.
- LLM reranking은 비용과 지연 시간이 크므로 top-50 후보의 offline 또는 batch rerank에 제한하고, reason generation은 deterministic evidence를 우선한다.

### D. 평가 전략

#### Offline 지표

- Recall@K: 과거 사용자가 북마크/클릭/리뷰한 논문을 시간 기준 holdout으로 복원할 수 있는가.
- NDCG@K/MRR: 강한 행동 신호(리뷰, 북마크)를 높은 순위에 배치하는가.
- Coverage: 추천 가능한 사용자 비율과 후보 pool coverage.
- Novelty/Diversity: 중복 주제·저자·source 과밀을 줄이는가.
- Freshness: 최신 논문과 foundational 논문의 균형.
- Calibration: 점수 구간별 실제 클릭/저장률 일치도.

#### Regression 테스트 우선순위

1. 한국어 topic/notes가 후보 abstract/title과 매칭되는지.
2. 행동 신호가 북마크 텍스트보다 최근 관심을 높일 수 있는지.
3. 이미 북마크한 논문과 같은 DOI/arXiv/title cluster가 제외되는지.
4. profile이 빈 사용자는 cold-start reason과 최근성 추천을 받는지.
5. OpenClaw artifact가 있으면 `--skip-existing`으로 로컬 fallback이 덮어쓰지 않는지.
6. malformed/stale artifact는 다른 사용자에게 노출되지 않는지.
7. 추천 API `limit` clamp, auth, grouped variants serialization이 깨지지 않는지.

#### Online 지표

- CTR, save/bookmark rate, review-start rate, hide/dismiss rate.
- 추천 알림 open 후 실제 paper open까지 전환율.
- 사용자별 빈 추천 비율 및 stale artifact 비율.
- OpenClaw fallback rate와 import validation failure rate.
- 지연 시간, batch runtime, 아티팩트 생성 실패율.

## 배포 전략

1. **관측성 먼저**
   - 아티팩트에 `scoring_mode`, `score_stats`, `signal_coverage`, `generated_from`, `fallback_reason`을 기록한다.
   - OpenClaw import 실패와 local fallback 발생을 운영 로그/알림으로 분리한다.

2. **Shadow mode**
   - 기존 `daily_content_v1`을 유지하고 새 랭커는 `daily_personalized_v2_shadow` variant로 아티팩트에 함께 기록한다.
   - API 기본 응답은 기존 variant를 유지하되 offline 비교 리포트만 생성한다.

3. **Canary**
   - 내부 사용자 또는 opt-in 사용자에게만 v2 grouped ranking을 노출한다.
   - 사용자별 fallback/staleness/empty recommendation을 대시보드로 확인한다.

4. **A/B 테스트**
   - v1 vs v2를 사용자 단위로 고정 할당한다.
   - CTR만 보지 말고 bookmark/review-start 같은 깊은 engagement를 primary metric으로 둔다.

5. **롤백**
   - 아티팩트 contract는 `src.recommendations_artifacts.load_recommendation_artifact`와 호환되게 유지한다.
   - 문제가 생기면 `.github/workflows/daily-recommendations.yml`에서 새 variant 생성만 끄고 기존 로컬/OpenClaw 경로로 되돌린다.

## 우선순위 로드맵

| 단계 | 기간 | 목표 | 주요 산출물 | 리스크 |
| --- | --- | --- | --- | --- |
| P0 | 1주 | 현재 품질을 측정 가능하게 만들기 | 추천 아티팩트 signal/fallback 메타데이터, regression 테스트, OpenClaw 실패 관측성 | 측정 없이 모델 변경부터 진행하는 리스크 차단 |
| P1 | 1~2주 | 행동 신호 snapshot 도입 | 이벤트 로그에서 user profile snapshot 생성, time decay, seen/negative 신호 | 개인정보/민감 로그 최소화 필요 |
| P2 | 2~3주 | 휴리스틱 v2 shadow 랭커 | score breakdown, diversity, stable ID dedup, Korean regression | 기존 추천 대비 품질 저하 가능성 |
| P3 | 3~5주 | 임베딩/RRF 개인화 reranker | profile embedding, candidate embedding, `HybridRanker` adapter, offline NDCG 리포트 | 비용, embedding dimension, cold-start |
| P4 | 5주+ | 학습 기반 랭킹과 online 실험 | label store, model training/eval pipeline, A/B framework | 데이터 희소성, feedback loop, explainability |

## 즉시 실행 가능한 다음 작업

1. `tests/test_daily_recommendations.py`에 한국어 topic/notes 매칭, cold-start, min_score/tie-break regression을 추가한다.
2. `tests/test_recommendations_notifications.py`에 stale/malformed artifact와 route-level limit/auth serialization 테스트를 보강한다.
3. 추천 생성 결과에 `signal_coverage`와 `fallback_reason`을 추가하는 contract 변경안을 별도 PRD로 작성한다.
4. 이벤트 기반 profile snapshot의 읽기 전용 prototype을 만들고 기존 `_user_profile` 출력과 비교하는 offline report를 생성한다.
5. shadow variant 방식으로 `daily_personalized_v2_shadow`를 추가하되 API 기본 노출은 유지한다.

## 결론

현재 PaperReviewAgent의 로컬 추천은 구조가 단순하고 안전하지만, 개인화는 북마크 기반 키워드 겹침에 머물러 있다. 가장 높은 ROI는 새 모델을 바로 도입하는 것이 아니라, 기존 이벤트 신호를 추천 profile snapshot으로 연결하고, stable ID/dedup/한국어 매칭/평가 지표를 먼저 고정한 뒤, shadow reranker와 A/B 테스트로 단계적으로 확장하는 것이다.
