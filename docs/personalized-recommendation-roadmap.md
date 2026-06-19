# 개인화 논문 추천 고도화 검토 및 로드맵

## 결론 요약

현재 PaperReviewAgent의 추천 표면은 안정적인 `raw.json` 알림 계약을 중심으로 구성되어 있지만, 로컬 추천기는 북마크 텍스트와 후보 논문 텍스트의 토큰 중복에 크게 의존한다. 즉시 개선해야 할 축은 **(1) 사용자 행동 이벤트를 추천 피처로 연결**, **(2) 후보 생성과 랭킹을 분리**, **(3) 하이브리드/임베딩/그래프 신호를 점진 도입**, **(4) 오프라인-온라인 평가와 안전한 배포 루프를 만드는 것**이다.

이 문서는 구현 제안서이며, 이번 변경은 코드 구현을 포함하지 않는다.

## 코드 근거 기반 현재 파이프라인

### 1. 생성 배치와 API 계약

- `scripts/generate_daily_recommendations.py`는 `src.daily_recommendations.main()`을 호출하는 얇은 CLI 래퍼다.
- `src/daily_recommendations.py`는 사용자 DB, 북마크 DB, `data/raw/papers.json` 후보 목록을 읽고 사용자별 `data/recommendations/{username}/{YYYY-MM-DD}/raw.json` 아티팩트를 쓴다.
- `routers/recommendations.py`의 `/api/recommendations/notifications`는 로그인 사용자명으로 최신 아티팩트를 읽어 알림 응답을 반환한다. 응답 계약은 `items`, `grouped_items`, `unread_count`, `latest_run_at`, `scoring_mode`, `score_stats`를 포함한다.
- `.github/workflows/daily-recommendations.yml`은 OpenClaw 아티팩트가 있으면 먼저 import하고, 없거나 실패하면 로컬 생성기를 `--skip-existing`으로 실행한다.

### 2. 현재 로컬 추천 로직

`src/daily_recommendations.py`의 핵심 흐름은 다음과 같다.

1. `load_users()`가 `users` 테이블에서 안전한 username만 읽는다.
2. `load_bookmarks()`가 `bookmarks` 테이블에서 `topic`, `title`, `papers`, `report`, `notes`를 읽는다.
3. `_user_profile()`은 북마크 topic/title/notes/report와 북마크된 paper title/authors를 가중 토큰 카운터로 누적한다.
4. `_paper_text()`는 후보 논문의 title/abstract/search_query/authors/categories를 결합한다.
5. `_score_paper()`는 프로필 토큰과 후보 토큰의 overlap, recency, PDF/DOI/arXiv 보너스를 합산한다.
6. `recommend_for_user()`는 이미 북마크한 논문 identity를 제외하고, 점수순으로 `limit`개를 `variants: {"daily": [...]}`에 담는다.
7. 북마크가 없는 사용자는 `fallback_recent=True`로 최근성/소스 보너스 중심 추천을 받는다.

### 3. 이미 존재하는 개인화 가능 신호

- 명시적 관심: 북마크 추가/삭제, 북마크 topic/title/notes/report, 북마크 안의 paper 목록.
- 행동 이벤트: `src/events/event_types.py`는 `BOOKMARK_ADD`, `BOOKMARK_REMOVE`, `HIGHLIGHT_*`, `REVIEW_*`, `SCORE_OVERRIDE`, `SEARCH_CLICK`, `PAPER_OPEN`, `QUERY_SUBMIT`를 정의한다.
- 검색 이벤트: `routers/search.py`는 검색 실행 시 query hash, 결과 수, 랭킹 적용 여부, source counts, latency, cache hit 여부를 `QUERY_SUBMIT` 이벤트로 남기고, `/api/search/click`에서 `SEARCH_CLICK`을 남긴다.
- 검색 랭킹 자산: `src/graph_rag/hybrid_ranker.py`에는 BM25, semantic, citation, recency, cross-encoder, HyDE/RRF 계열 랭킹 컴포넌트가 있다.
- 논문 저장 자산: `src/storage/paper_db.py`는 PaperDB와 FTS5 검색을 제공하지만, 일일 추천 로컬 생성기는 현재 `data/raw/papers.json`을 읽는다.

## 주요 한계와 리스크

1. **개인화 신호가 북마크에 과집중**
   - 검색 클릭, query submit, paper open, highlight, review, score override 이벤트가 추천 scoring path로 연결되어 있지 않다.
   - 콜드스타트 사용자는 개인별 탐색 의도 대신 최근 논문 중심 fallback을 받는다.

2. **토큰 overlap 중심이라 의미적 유사도와 부정 신호가 약함**
   - 동의어, 약어, 방법론/도메인 분리, 한국어/영어 혼합 의도에 취약하다.
   - `BOOKMARK_REMOVE`, 낮은 score override, 반복 노출 무시 같은 negative feedback이 현재 랭킹에 반영되지 않는다.

3. **후보 생성과 랭킹이 결합되어 확장성이 낮음**
   - 후보 풀은 `data/raw/papers.json`에 묶여 있고, PaperDB FTS, GraphRAG, OpenClaw candidate source, 검색 이력 기반 후보 생성이 단계적으로 조합되지 않는다.
   - ranking 후보 cap, source diversity, dedup 같은 검색 파이프라인의 검증된 패턴이 추천 생성기에 재사용되지 않는다.

4. **아티팩트 계약은 안정적이지만 실험/평가 정보가 부족함**
   - `score_stats`는 단순 분포만 제공한다.
   - 추천 이유는 overlap 키워드 위주라 사용자가 왜 추천받았는지, 어떤 신호가 주요했는지 설명력이 부족하다.
   - variant 계약은 있지만 로컬 생성기는 `daily` 단일 variant만 생성한다.

5. **운영 리스크**
   - OpenClaw 우선 + 로컬 fallback은 안전하지만, OpenClaw와 로컬 scoring mode 품질 비교/드리프트 감시 지표가 없다.
   - 사용자별 이벤트를 추천에 쓰려면 privacy, 보존 기간, payload 최소화, 사용자 삭제/GDPR 흐름과 함께 설계해야 한다.
   - `latest_raw_file()`은 mtime 기반으로 최신 raw 파일을 고르므로 명시적 `run_at` 검증과 freshness SLO가 없으면 stale artifact가 조용히 노출될 수 있다.

6. **계약/스코어 의미 불일치**
   - `paper_id()`의 최종 fallback은 `title::year`라서 안정 ID가 없는 흔한 제목 논문은 충돌할 수 있다.
   - `confidence_label()`은 4.5/3.5 같은 고정 threshold를 쓰지만, 로컬 daily score는 비정규화 overlap 합이고 OpenClaw score scale은 다를 수 있다.
   - OpenClaw import는 titled item이 있으면 score/rank가 없어도 valid artifact가 될 수 있어, 외부 artifact 품질 envelope를 별도로 정의해야 한다.

## 제안 아키텍처

### 레이어 A. 피처/이벤트 수집 정리

추천 피처 테이블 또는 일별 materialized artifact를 추가한다.

- Positive strong: bookmark add, review create/update, score override high, repeated paper open.
- Positive medium: search click, highlight create/update, long dwell/open if client가 제공 가능할 때.
- Intent/context: query submit의 query hash만으로는 추천 피처가 부족하므로, privacy-safe query embedding 또는 짧은 normalized query topic을 별도 저장하는 방안을 검토한다.
- Negative: bookmark remove, score override low, recommendation dismiss/hide, repeated impression with no click.
- Freshness: 최근 7/30/90일 감쇠 가중치와 장기 관심사 가중치를 분리한다.

권장 산출물:

```text
user_interest_profile_v1
- user_id
- term_weights
- embedding_centroid_short
- embedding_centroid_long
- positive_paper_ids
- negative_paper_ids
- source_signal_counts
- updated_at
```

### 레이어 B. 후보 생성 분리

`recommend_for_user()` 내부에서 scoring까지 한 번에 수행하는 구조를 다음처럼 분리한다.

1. **candidate generators**
   - bookmark-neighbor: 북마크 논문 title/abstract/authors 기반 유사 논문.
   - query-intent: 최근 검색 query/topic 기반 후보.
   - graph-neighbor: citation/reference/co-topic/PageRank 주변 후보.
   - fts/keyword: PaperDB FTS 또는 기존 token profile 후보.
   - freshness/exploration: 새 논문/인기 논문 탐색 슬롯.
   - OpenClaw import: 외부 추천을 하나의 candidate source로 정규화.

2. **candidate normalization**
   - `paper_id()` 기준 dedup을 강화하고 DOI/arXiv/title canonicalization을 별도 단계로 둔다.
   - source별 recall/precision 로그를 남긴다.

3. **ranking input contract**
   - 후보별 `features`, `source_tags`, `explanations`, `privacy_level`을 함께 넘긴다.

### 레이어 C. 하이브리드 랭킹 v2

초기에는 새 모델 학습 없이 점진 개선한다.

- Content: 현재 token overlap 유지하되 TF-IDF/BM25 스타일 정규화와 field weight(title > abstract > author/category)를 명시한다.
- Semantic: 기존 embedding/GraphRAG 자산을 활용해 사용자 centroid와 candidate embedding cosine을 추가한다.
- Graph: citation/PageRank/co-citation/co-bookmark 근접도를 추가한다.
- Behavior: search_click, paper_open, review/highlight, score_override에서 나온 사용자별 affinity를 추가한다.
- Freshness: 분야별 recency prior를 분리한다. 모든 분야에 동일한 최신성 보너스를 주면 고전/기초 논문이 불리해진다.
- Diversity: MMR 또는 xQuAD로 같은 세부 주제/저자/venue 과밀을 줄인다.
- Exploration: 상위 N개 중 1~2개는 uncertainty/exploration 슬롯으로 유지하되 이유를 명시한다. 현재 `DEFAULT_MIN_SCORE = 0.6`에서는 프로필이 있는 사용자의 zero-overlap 후보가 대부분 cutoff 아래로 떨어지므로, 탐색 슬롯은 hard filter 뒤가 아니라 별도 경로로 주입해야 한다.
- Negative filters: 이미 북마크/삭제/낮은 점수/최근 노출 무반응 논문은 제외 또는 강등한다.
- Calibration: source별 raw score를 먼저 정규화한 뒤 confidence label을 붙인다. 로컬 daily, OpenClaw, future personalized variant의 점수 scale을 직접 비교하지 않는다.

권장 점수식 초안:

```text
score = 0.25 * bm25_profile
      + 0.25 * semantic_user_centroid
      + 0.15 * graph_affinity
      + 0.15 * behavior_affinity
      + 0.10 * source_quality
      + 0.05 * calibrated_recency
      + 0.05 * exploration_prior
      - negative_feedback_penalty
```

가중치는 고정값으로 시작하고, 충분한 로그가 쌓이면 learning-to-rank 또는 contextual bandit으로 전환한다.

### 레이어 D. 설명 가능성/아티팩트 계약 확장

기존 `raw.json` 계약을 깨지 않고 optional field를 늘린다.

- `variants.personalized_v2`: 새 랭커 결과.
- `variants.daily`: 현재 결과 유지 또는 fallback.
- paper item optional fields:
  - `explanation_factors`: `["북마크 주제: graph neural networks", "최근 검색 클릭과 유사", "새 arXiv 논문"]`
  - `source_tags`: `["bookmark_neighbor", "semantic", "freshness"]`
  - `model_version`: `personalized_v2_YYYYMMDD`
  - `impression_id`: 온라인 평가/피드백 연결용 비식별 ID.
- `score_stats.personalized_v2`: n/mean/min/max/spread 외 coverage, diversity, fallback rate 추가.
- `artifact_health`: optional `generated_for`, `validated_at`, `expires_at`, `candidate_count`, `quality_warnings`를 두어 stale/corrupt artifact를 운영에서 감지한다.

`src.recommendations_artifacts.load_recommendation_artifact()`는 unknown field를 현재 버리므로 UI/API에서 쓰려면 별도 optional schema 확장이 필요하다. 단, 기존 클라이언트 호환성은 유지 가능하다.

## 평가 전략

### 오프라인 평가

- 데이터셋: 과거 이벤트를 시간순 split한다. T일까지의 신호로 T+1~T+7의 bookmark/click/open/review를 예측한다.
- 지표:
  - Recall@K, NDCG@K, MRR@K.
  - 기존 북마크 재추천 방지율, duplicate rate.
  - source diversity, topic diversity, author/venue concentration.
  - cold-start coverage, fallback rate.
  - explanation coverage: 추천 이유가 비어 있지 않은 비율.
- Baseline:
  - current `daily_content_v1`.
  - recency-only.
  - OpenClaw artifact when available.
  - personalized_v2 candidate/ranker variants.

### 온라인 평가

- 노출 단위 impression logging을 추가하고 click/bookmark/review/dismiss로 연결한다.
- 사용자별 또는 세션별 A/B: `daily_content_v1` vs `personalized_v2`.
- Guardrail:
  - 알림 클릭률 하락.
  - hide/dismiss 증가.
  - latency/배치 실패율.
  - 특정 source/field 편중.
  - 사용자 삭제 이후 잔존 피처 없음.

### 품질 검증 테스트

- 현재 `tests/test_daily_recommendations.py`의 사용자별 분리/중복 제외/skip-existing 테스트를 확장한다.
- 새 테스트:
  - negative feedback 강등.
  - semantic signal이 token overlap 없는 후보를 끌어올림.
  - diversity rerank가 동일 topic 과밀을 줄임.
  - fallback_recent 사용자도 안전한 exploration 이유를 받음.
  - OpenClaw와 로컬 variant가 같은 raw contract로 병합됨.

## 우선순위 로드맵

### P0 — 관측성과 안전장치 정비 (1주)

- 현재 추천 배치에 생성 summary를 더 남긴다: users_seen, papers_seen, empty users, fallback users, duplicate-filtered count, stale artifact skipped count.
- 아티팩트에 optional `model_version`, `source_tags`, `explanation_factors`, `artifact_health`를 허용하는 문서/테스트를 추가한다.
- 추천 노출/클릭/숨김 이벤트 설계를 확정한다. 특히 query 원문 저장 여부는 privacy 리뷰 후 결정한다.
- 기존 `daily_content_v1`을 baseline으로 고정하고 회귀 테스트를 추가한다.

### P1 — 개인화 피처 연결 (2~3주)

- 이벤트 저장소에서 사용자별 recent/long-term profile을 만드는 offline job을 추가한다.
- bookmark profile에 search_click, paper_open, review/highlight, score_override를 가중 결합한다.
- negative feedback과 이미 노출된 추천의 재노출 억제를 추가한다.
- cold-start는 role/onboarding topic/recent query 기반 fallback으로 개선한다.

### P2 — 후보 생성/랭킹 분리 (3~4주)

- `candidate_generators`와 `ranker` 인터페이스를 분리한다.
- PaperDB FTS와 기존 `HybridRanker`/embedding 자산을 dependency-light 옵션으로 연결한다.
- OpenClaw 결과를 `external_openclaw` candidate source로 정규화해 로컬 후보와 병합한다.
- RRF/MMR 기반 diversity reranking을 적용한다.

### P3 — 평가 및 실험 배포 (2~3주)

- 오프라인 replay 평가 스크립트와 golden fixtures를 만든다.
- `variants.personalized_v2`를 shadow mode로 생성하되 UI 기본 노출은 유지한다.
- score_stats에 variant별 coverage/diversity/fallback/impression 준비 지표를 넣는다.
- 충분한 지표 확인 후 소수 사용자 A/B를 시작한다.

### P4 — 모델링 고도화 (데이터 축적 후)

- Learning-to-rank 또는 contextual bandit으로 전환한다.
- 사용자 embedding centroid를 short-term/long-term으로 분리하고 session intent를 반영한다.
- 분야별 recency prior와 source reliability calibration을 학습한다.
- 설명 품질을 자동 평가하고 나쁜 설명을 fallback template로 대체한다.

## 구현 시 권장 경계

- 기존 `/api/recommendations/notifications` 응답 필드는 삭제하지 않는다.
- `raw.json` reader는 unknown optional fields를 허용하되, 새 UI 기능은 명시적 schema 확장 후 사용한다.
- 배치 실패 시 현재처럼 로컬 fallback 또는 이전 valid artifact serving을 유지한다.
- 개인화 피처는 원문 query/report 전체 저장보다 hash, topic, embedding, bounded snippets 우선으로 설계한다.
- 새 의존성은 embedding/ranker 재사용이 불가능한 경우에만 도입한다.

## 제안된 다음 작업

1. `personalized_v2` PRD와 테스트 명세 작성.
2. 이벤트 기반 profile builder를 read-only offline job으로 추가.
3. current baseline vs v2 shadow artifact를 동시에 생성하는 실험 플래그 추가.
4. 오프라인 replay 평가 스크립트로 Recall@K/NDCG@K와 diversity를 측정.
5. UI에서 추천 이유와 feedback 버튼(dismiss/not interested/save)을 연결.
