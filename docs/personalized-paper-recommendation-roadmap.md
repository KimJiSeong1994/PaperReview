# 개인화 논문 추천 고도화 제안서

작성일: 2026-05-03
범위: 현재 PaperReviewAgent 추천/알림 파이프라인을 코드 근거로 검토하고, 구현 없이 개인화 품질 개선안과 우선순위 로드맵을 제시한다.

## 1. 결론 요약

현재 PaperReviewAgent의 일일 추천은 **사용자별 아티팩트 스코프는 분리되어 있지만, 개인화 모델은 북마크 텍스트 기반 토큰 오버랩에 가깝다**. `src/daily_recommendations.py`는 사용자 목록, 북마크, 전역 논문 JSON을 읽고(`load_users`, `load_bookmarks`, `load_papers`), 북마크의 `topic/title/notes/report/papers`에서 만든 토큰 카운터와 후보 논문 텍스트의 겹침으로 점수를 계산한다. 북마크가 없으면 `fallback_recent=True`로 최근성 및 PDF/DOI/arXiv 보너스 중심 추천이 된다.

따라서 개인화 품질을 높이는 최우선 과제는 새 모델 도입보다 먼저 **사용자 행동 신호 수집 → 프로필/피드백 저장 → 오프라인 평가 → 제한적 롤아웃**의 닫힌 루프를 만드는 것이다. 기존 이벤트 인프라(`src/events/*`)와 추천 아티팩트 계약(`data/recommendations/{user_id}/{YYYY-MM-DD}/raw.json`)을 보존하면서, 병렬 variant로 고도화 랭커를 추가하는 방식이 가장 안전하다.

## 2. 현재 파이프라인 코드 근거

### 2.1 생성 경로: 로컬 일일 추천

- `src/daily_recommendations.py:120-165` — `users.db`와 `bookmarks.db`를 읽어 사용자와 북마크 레코드를 구성한다.
- `src/daily_recommendations.py:190-202` — 사용자 프로필은 북마크 `topic`, `title`, `notes`, `report`, 북마크된 논문 제목/저자 토큰으로만 구성된다.
- `src/daily_recommendations.py:205-216` — 후보 논문 텍스트는 `title`, `abstract`, `search_query`, 저자, 카테고리만 사용한다.
- `src/daily_recommendations.py:235-262` — 점수는 토큰 오버랩, 최근성, PDF/DOI/arXiv 보너스의 합이다.
- `src/daily_recommendations.py:300-359` — 이미 북마크된 논문은 식별자 교집합으로 제외하고, 결과를 `variants: {"daily": [...]}` 아티팩트로 반환한다.
- `src/daily_recommendations.py:362-372` — 출력은 사용자/일자별 `raw.json` 파일로 원자적 기록된다.

### 2.2 읽기/API/UI 경로

- `src/recommendations_artifacts.py:97-109` — 알림 API는 최신 `raw.json`을 전체 스캔한 뒤 `user_id` 또는 경로 파트로 사용자 소유 여부를 판단한다.
- `src/recommendations_artifacts.py:121-146` — 개별 추천 row는 `score`, `rank`, `reason`, `paper_id`, URL/DOI/arXiv 등을 정규화한다.
- `src/recommendations_artifacts.py:149-209` — 동일 `paper_id`의 여러 variant를 묶고 `_sort_key(score, rank)`로 정렬한다.
- `routers/recommendations.py:85-95` — `GET /api/recommendations/notifications`는 로그인 사용자 기준으로 아티팩트를 읽어 반환만 한다.
- `web-ui/src/components/RecommendationBell.tsx` 및 `web-ui/src/api/recommendations.ts` — 추천은 표시 전용이며, 추천 클릭/노출/숨김/피드백을 서버로 보내는 API가 없다.

### 2.3 OpenClaw 연동 및 배포

- `.github/workflows/daily-recommendations.yml:37-130` — OpenClaw 원격 추천 아티팩트를 먼저 가져오고 실패 시 로컬 fallback으로 진행한다.
- `.github/workflows/daily-recommendations.yml:147-180` — 가져온 아티팩트를 import한 뒤 `scripts/generate_daily_recommendations.py --skip-existing`로 나머지 사용자 추천을 생성한다.
- `docs/daily-recommendations.md:16-25` — OpenClaw 아티팩트 필수 shape은 최소 검증 중심이다.

### 2.4 이미 존재하지만 추천에 미연결된 행동 신호

- `src/events/event_types.py:25-38` — `BOOKMARK_ADD/REMOVE`, `HIGHLIGHT_*`, `REVIEW_*`, `SCORE_OVERRIDE`, `SEARCH_CLICK`, `PAPER_OPEN`, `QUERY_SUBMIT` 이벤트 타입이 있다.
- `src/events/migrations.py:32-55` — `user_events` 테이블과 사용자/시간, 이벤트 타입, 논문 인덱스가 있다.
- `routers/search.py`는 검색 쿼리와 클릭 이벤트를 발행하고, `routers/bookmarks.py`와 `routers/paper_reviews.py`는 북마크/하이라이트/리뷰 이벤트를 발행한다.
- 그러나 `src/daily_recommendations.py`와 `src/openclaw_recommendations.py`는 `events.db`나 사용자 프로필 DB를 읽지 않는다.

## 3. 핵심 한계와 리스크

1. **개인화 신호가 북마크 텍스트에 편중**
   명시적 선호, 비선호, 추천 노출, 추천 클릭, 숨김, dwell time, 재방문, 검색 후 저장 전환이 랭킹에 반영되지 않는다.

2. **콜드스타트가 최근성 fallback에 의존**
   북마크가 없는 사용자는 개인화 대신 최근성/소스 보너스 추천을 받는다. 온보딩 선호 수집이나 세션 검색 이력 기반 단기 프로필이 없다.

3. **검색/추천 랭킹의 사용자 인식이 분리됨**
   검색 랭킹은 글로벌 관련도 중심이며 사용자 프로필을 입력으로 받지 않는다. 개인화 검색을 추가할 경우 기존 공유 캐시와 사용자별 결과가 섞이지 않도록 캐시 키 또는 후처리 경계를 명확히 해야 한다.

4. **아티팩트 계약은 유연하지만 품질 검증이 약함**
   `score`, `rank`, `year`, `authors`, `score_stats`의 강한 schema 검증이 없다. `paper_id()` fallback은 `title::year`라 충돌 가능성이 있다.

5. **관측성과 평가 루프 부족**
   워크플로우는 성공/실패 로그 중심이고 CTR, 저장 전환율, fallback 비율, 점수 분포 drift, 추천 다양성, 중복률, 사용자별 coverage 같은 지표를 축적하지 않는다.

6. **성능 확장성 리스크**
   요청 시 `**/raw.json` 전체 스캔을 수행하고, 생성 시 전역 후보 corpus를 사용자별로 반복 scoring한다. 고도화 모델을 단순 추가하면 사용자 수 × 후보 수 비용이 빠르게 증가한다.

## 4. 개선 원칙

- 기존 알림 API와 `raw.json` 계약은 유지한다.
- 새 랭커는 먼저 `variants.personalized_v2` 같은 병렬 variant로 추가한다.
- 개인정보/민감 신호는 원문 장기 저장보다 파생 feature와 집계 지표 중심으로 설계한다.
- 추천 품질 개선은 모델 복잡도보다 데이터 신호와 평가 가능성을 우선한다.
- OpenClaw와 로컬 fallback 모두 동일한 평가/계약 검증 게이트를 통과하도록 한다.

## 5. 데이터 신호 확장안

### P0 — 즉시 설계해야 할 최소 신호

| 신호 | 수집 위치 | 용도 | 주의점 |
| --- | --- | --- | --- |
| 추천 노출(impression) | `RecommendationBell` 열림/표시 | CTR denominator, 반복 노출 억제 | 노출 batch 이벤트로 과다 쓰기 방지 |
| 추천 클릭 | 추천 카드 클릭 | 긍정 implicit feedback | 외부 링크 이동 전 fire-and-forget 필요 |
| 북마크 전환 | 추천에서 북마크 생성 | 강한 긍정 라벨 | 추천 `paper_id`, `run_at`, `variant` 연결 |
| 숨김/관심 없음 | 추천 카드 액션 | 강한 부정 라벨, suppression | 실수 취소 UX 필요 |
| 검색 쿼리 최근 이력 | 기존 `QUERY_SUBMIT` | 단기 관심사 | 원문 대신 hash+토큰/주제 요약 권장 |

### P1 — 프로필 품질 향상 신호

- 북마크 폴더/토픽 이동, 노트 길이, 하이라이트 생성 여부.
- 리뷰 생성 및 `overall_score`/강점/약점 요약.
- 논문 열람 및 재방문 이벤트(`PAPER_OPEN`)의 추천 출처 attribution.
- 선호 도메인, 방법론, 데이터셋, venue, 최신성 선호 같은 온보딩/설정형 선호.

### 저장 모델 제안

1. `user_events`는 원천 이벤트 ledger로 유지한다.
2. 별도 `user_profile_features` 또는 `profile.db` 확장 테이블에 주기적으로 집계한 feature를 저장한다.
3. 추천 아티팩트에는 `scoring_mode`, `profile_version`, `feature_snapshot_id`, `experiment_id`를 선택 필드로 추가한다.
4. 사용자 삭제 흐름(`routers/deps/user_deletion.py`)에 profile feature, recommendation feedback, embeddings 삭제 단계를 포함한다.

## 6. 랭킹/모델링 개선안

### 6.1 단기: 현행 scorer의 안전한 개선

- 토큰 카운터를 TF-IDF/BM25 스타일로 정규화해 흔한 단어 과대 반영을 줄인다.
- 북마크 제목/논문 제목뿐 아니라 abstract, category, venue, citation, 검색 쿼리 이벤트를 feature로 반영한다.
- 후보 중복 제거를 `paper_id/title::year`에서 DOI/arXiv/URL/title-normalized fingerprint 다중 키로 강화한다.
- `fallback_recent` 사용자에게 온보딩 주제 또는 최근 검색 쿼리 기반 단기 프로필을 적용한다.
- 결과 diversity 제약을 추가한다. 예: 동일 source/저자/토픽 상위 집중을 제한하고 MMR로 novelty를 보장한다.

### 6.2 중기: Two-stage 추천 구조

1. **Candidate generation**
   - 최근 수집 논문, 사용자의 검색 결과 클릭 주변 논문, 북마크와 유사한 embedding 후보, citation/reference 인접 후보를 합친다.
2. **Feature enrichment**
   - 콘텐츠 유사도, 프로필 토픽 유사도, 저자/venue 선호, 신선도, 이미 노출/무시 여부, source 신뢰도, diversity feature를 계산한다.
3. **Ranker**
   - 초기에는 규칙 기반 weighted scorer + calibration.
   - 라벨이 쌓이면 pairwise/listwise learning-to-rank로 전환한다.
4. **Post-rank guardrail**
   - 이미 본 논문 억제, 중복/near-duplicate 제거, diversity, 품질 하한, 설명 가능한 reason 생성.

### 6.3 장기: 개인화 학습 루프

- `recommendation_feedback` 라벨을 이용한 사용자별/세그먼트별 가중치 학습.
- 개인별 장기 프로필(관심 분야)과 세션 단기 프로필(최근 검색/클릭)을 결합.
- OpenClaw 추천과 로컬 추천을 같은 후보 pool/평가 로그로 비교하는 ensemble 또는 interleaving 실험.
- 이유 설명(`reason`)도 matched token 나열에서 “사용자 신호 → 추천 근거” 구조로 개선한다.

## 7. 평가 전략

### 7.1 오프라인 평가

- 과거 이벤트를 시간순 split하여 “이 시점 이전 신호로 이후 북마크/클릭/리뷰 생성을 맞히는가”를 평가한다.
- 지표: Recall@K, NDCG@K, MAP@K, MRR, coverage, novelty, diversity, 중복률, cold-start segment 성능.
- 부정 라벨은 hide/not-interested, 반복 노출 후 무클릭, 삭제된 북마크를 낮은 confidence로 사용한다.
- 기존 `tests/test_daily_recommendations.py` fixture를 확장해 rank stability, dedupe, fallback, schema compatibility 회귀 테스트를 추가한다.

### 7.2 온라인 평가

- 노출 이벤트 기준 CTR, bookmark conversion, hide rate, downstream review 생성률을 variant별로 집계한다.
- 사용자별 randomization 단위는 user_id hash로 고정한다.
- `daily_content_v1`, `personalized_v2`, `openclaw` variant를 같은 UI 계약으로 노출하되, 기본 노출은 canary 사용자부터 시작한다.
- guardrail: hide rate 급증, empty recommendation 비율, fallback 비율, workflow 실패율, latency/IO 증가를 자동 롤백 조건으로 둔다.

## 8. 배포/운영 전략

1. **계약 고정**: `raw.json` optional metadata를 추가하되 기존 필드는 유지한다.
2. **Feature flag**: 이미 존재하는 `PROFILE_RANKER_ENABLED`를 사용자/전역 단계별 rollout gate로 사용한다.
3. **Shadow mode**: 새 랭커는 처음에는 아티팩트에만 기록하고 UI 기본 노출에는 쓰지 않는다.
4. **Canary**: 내부 사용자 또는 5% 사용자에게 variant 노출.
5. **A/B**: 최소 2주 단위로 CTR/bookmark conversion/hide rate 평가.
6. **Rollback**: flag off 시 즉시 `daily_content_v1` 또는 OpenClaw 기존 아티팩트로 복귀.
7. **Observability**: 생성 요약(`users_seen`, `papers_seen`, `fallback_count`, `empty_count`, `score_stats`, schema validation errors)을 파일/로그/관리자 대시보드에 저장한다.

## 9. 우선순위 로드맵

### Phase 0 — 계약/측정 기반 다지기 (1주)

- 추천 아티팩트 schema 문서화 및 strict validator 추가.
- 추천 노출/클릭/숨김/북마크 전환 이벤트 타입 설계.
- `scoring_mode`, `profile_version`, `experiment_id`, `variant` attribution 표준화.
- 기존 테스트에 schema compatibility 및 malformed artifact negative case 추가.

### Phase 1 — 행동 신호 수집과 집계 (1-2주)

- `RecommendationBell`에서 impression/click/hide feedback API 추가.
- `events.db`에서 사용자별 feature snapshot을 만드는 batch job 추가.
- 추천 생성 요약 지표와 fallback 비율을 저장.
- 사용자 삭제 cascade에 신규 profile/feedback 데이터 포함.

### Phase 2 — personalized_v2 shadow ranker (2주)

- 기존 `daily_content_v1`은 유지하고 `personalized_v2` variant를 병렬 생성.
- profile feature + 현행 콘텐츠 scorer + diversity guardrail 적용.
- 오프라인 Recall/NDCG와 artifact 품질 리포트 생성.
- 운영 workflow에는 shadow 결과 수/score 분포만 기록하고 UI 노출은 비활성.

### Phase 3 — Canary/A-B rollout (2-4주)

- `PROFILE_RANKER_ENABLED` per-user flag로 제한 노출.
- CTR, bookmark conversion, hide rate, fallback 비율, latency를 비교.
- 부정 지표 악화 시 자동 fallback.
- OpenClaw artifact와 로컬 v2의 interleaving 또는 ensemble 후보 비교.

### Phase 4 — 학습형 ranker 전환 (4주+)

- 충분한 feedback 라벨 확보 후 pairwise/listwise ranker 도입 검토.
- 사용자 세그먼트별 calibration과 cold-start onboarding 연결.
- 장기/단기 관심사 profile decay, novelty budget, 설명 품질 개선.

## 10. 즉시 실행 가능한 next actions

1. `recommendation_impression`, `recommendation_click`, `recommendation_hide`, `recommendation_bookmark` 이벤트 타입과 payload 계약을 확정한다.
2. `src/recommendations_artifacts.py`의 아티팩트 validator를 별도 함수로 분리하고 OpenClaw/로컬 생성 모두에서 재사용한다.
3. `src/daily_recommendations.py`의 결과에 `fallback_recent` 집계와 `profile_version`을 추가한다.
4. `tests/test_daily_recommendations.py`에 “동일 제목/연도 충돌”, “빈 북마크 cold-start”, “부정 feedback suppression” 회귀 fixture를 추가한다.
5. `PROFILE_RANKER_ENABLED` flag를 추천 생성 단계에서 shadow/canary 제어점으로 연결한다.

## 부록: subagent 검토 통합

- Subagents spawned: 3 (`Ptolemy` pipeline map, `Avicenna` data-signal map, `Bacon` evaluation/deployment review).
- Integrated findings:
  - 추천 생성은 북마크 텍스트 기반이며 이벤트/피드백은 랭킹에 미연결.
  - API/UI는 추천 표시 전용이고 feedback write path가 없다.
  - OpenClaw와 로컬 fallback 모두 같은 artifact reader contract를 공유하므로 backward-compatible 확장이 필요하다.
  - 평가/관측성/스키마 검증과 rollout guardrail이 현재 가장 큰 품질 리스크다.
