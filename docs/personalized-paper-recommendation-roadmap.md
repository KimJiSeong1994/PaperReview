# 개인화 논문 추천: 구현 계약과 평가 로드맵

## 상태와 범위

이 문서는 코드 경로와 승인된 품질 기준을 구분한다. **로컬 구현 정합성, 실제 public/OpenClaw 공급원 운영 적격성, 사용자 추천 유용성은 별도 판정**이다. 아래 링크는 구현 위치이며 테스트 통과·운영 활성화·실제 provider 확보의 증거가 아니다. 기존 opt-in/전역 flag를 이 문서나 offline evaluator가 변경하지 않는다. 운영 안내는 [daily-recommendations.md](daily-recommendations.md)를 함께 참조한다.

과거의 “북마크만 사용”, “행동 신호 미구현”, “v2는 미래 작업” 설명은 더 이상 코드 상태를 표현하지 않는다. 이벤트 어댑터·감쇠 프로필·v2 breakdown/MMR 경로는 존재하지만 실제 효과는 별도 평가가 필요하다. raw score는 확률이 아니며 metadata completeness는 과학적 품질 판정이 아니다.

## 공통 제품 경로

| 책임 | 코드와 계약 |
| --- | --- |
| 계정 생애/인증 | [user_db.py](../src/storage/user_db.py), [recommendations router](../routers/recommendations.py)의 authenticated principal: username만이 아니라 현재 account incarnation에 결합. 삭제/재가입·late publication을 같은 계정으로 취급하지 않는다. old JWT 재로그인 영향과 coordinated cutover는 운영 승인 대상이다. |
| 후보 수신 | [recommendation_candidates.py](../src/recommendation_candidates.py): trusted receiver scope/owner/provenance, bounded public bibliographic fields, canonical identity, non-serving candidate snapshot. legacy global pool을 public으로 재분류하지 않는다. |
| 공개 bootstrap | [related_paper_wiki.py](../src/related_paper_wiki.py), [collector CLI](../scripts/collect_related_papers_for_wiki.py): 고정 public seeds만 사용. 사용자 query/notes/report를 외부/shared wiki로 내보내지 않는다. 실제 provider snapshot source/time/hash와 eligible card가 확인되기 전 availability 미충족; source absent는 honest empty이며 fake fallback 없음. |
| 외부 공급원 | [openclaw_recommendations.py](../src/openclaw_recommendations.py): validated 후보 공급만. 외부 raw score/rank/reason은 개인화 증거가 아니며 serving artifact 직접 게시 또는 skip-existing 우회 금지. 미확인 source는 disabled. |
| 프로필/랭킹 | [recommendation_profiles.py](../src/recommendation_profiles.py), [recommendation_ranker.py](../src/recommendation_ranker.py): bounded event features, half-life decay, preference/read/hard suppression 분리, v1/v2 threshold 분리, MMR 최종 순서. 신규 paid LLM/embedding 없음. |
| 공통 publisher | [daily_recommendations.py](../src/daily_recommendations.py): local/public/external 후보를 공통 policy/profile/rank/publish로 처리. authority와 current policy를 publish 시 재확인. flag로 허용된 mode만 사용; feature failure와 identity/policy failure를 혼동하지 않는다. |
| 저장/조회 | [recommendations_artifacts.py](../src/recommendations_artifacts.py): common delivery schema, incarnation 소유 디렉터리, validated run time, finite values, final rank 순서. score 재정렬·전 사용자 glob/mtime 우선순위는 계약이 아니다. |
| durable actions | [recommendation_state.py](../src/recommendation_state.py): hide/already_seen는 hard suppression, seen은 read marker, interested/topic_less는 preference. analytics 손실이 accepted action을 취소하지 않는다. |
| API/UI | [recommendations.py](../routers/recommendations.py), [RecommendationBell.tsx](../web-ui/src/components/RecommendationBell.tsx): GET `/api/recommendations/notifications` 기본/최대5, POST `feedback`, `read-state`, `exposure`. run/key membership, request idempotency, 실제 가시성 기반 exposure와 hide/refill 순서가 검증 대상. |

‘오늘의 추천’은 오늘 발견할 관련 논문이지 오늘 발행된 논문 필터가 아니다. 원래 발행일을 보여주며 과거 좋은 논문도 허용한다. reserve 12에서 current policy로 숨김을 제거하고 순서를 유지해 **실제 Top5**를 채운다. evaluator도 `RecommendationPolicy.project`를 직접 호출한다.

### 저장소·공급원 경계

- 정상 policy open은 `RecommendationState(path, authority=users)` (`users`는 `UserDB`)이며 strict 검증만 한다. API startup/별도 승인된 operator 최초 provisioning만 `RecommendationState.initialize(path, authority=users)`를 명시 호출한다. 생성 CLI는 자동 provisioning하지 않는다. users.db의 immutable receipt가 resolved path/schema/store ID/device+inode를 묶으므로 missing/replaced store는 fail-closed다. backup restore는 별도 승인된 recovery가 필요하며 자동 재초기화나 발명한 복구 명령으로 우회하지 않는다. users/events 간 cross-database atomicity를 주장하지 않는다.
- 후보 staging은 `current-{source}-{provenance_id}.json` 고정 슬롯과 같은 basename receipt/wiki를 사용한다. `source_run_id`는 hash-bound envelope 안에 남는다. history scan/실행별 파일 누적 대신 current slot을 읽고, historical snapshot을 삭제하지 않는다. `acquisition_status` ready/empty/disabled/degraded/error와 sanitized reasons가 delivery 상태(`source_error` 포함)에 전달된다.
- Collector acquisition error exit3은 workflow에서 common fallback으로 이어지고, deadline/unexpected failure exit2는 중단한다. 나머지 완료 상태는 exit0이다. 아래 evaluator exit 계약과 혼동하지 않는다. Workflow는 `DATA_DIR`, `EVENTS_DB_PATH`, `FEATURE_FLAGS_DB_PATH`를 configured data root에 결합한다. flags 기본 경로도 `DATA_DIR`를 따른다. 경로 설정 자체를 기존 실행의 격리 증거로 해석하지 않는다.
- Durable interested/topic_less가 preference의 권위이며 recommendation-feedback analytics mirror는 profile 입력에서 제외한다. undo 이후 analytics로 선호를 되살리거나 이중 계산하지 않는다. Review session producer는 incarnation을 capture/persist/restore하여 new account의 후속 bookmark에도 originating identity를 유지한다.

### 현재 함수 기준 추적

- `src/daily_recommendations.py::generate_daily_recommendations` → `src/daily_recommendations.py::recommend_for_user` → `src/daily_recommendations.py::write_artifact`: 공통 생성·랭킹·최종 게시 경계다. 최종 쓰기는 `src/storage/user_db.py::UserDB.account_guard` 안에서 현재 incarnation과 policy를 재확인한다.
- `src/recommendation_candidates.py::load_candidate_snapshot`, `src/recommendation_candidates.py::merge_candidate_pool`: 등록된 scope/owner를 확인하고 private 후보는 동일 account incarnation만 사용한다. `public_only=True`에서는 private 후보를 제외한다. `src/related_paper_wiki.py::collect_review_build_wiki`는 고정 public seed acquisition 경로이며 private profile을 공급원 query로 바꾸지 않는다.
- `src/recommendation_profiles.py::load_user_event_signals` → `src/recommendation_profiles.py::build_recommendation_profile`, `src/recommendation_ranker.py::rank_paper_v2` → `src/recommendation_ranker.py::mmr_rerank`: 현재 bounded 행동 신호·감쇠·v2/MMR 구현의 기준이다.
- `src/recommendations_artifacts.py::read_delivery` → `src/recommendations_artifacts.py::load_recommendation_artifact` → `src/recommendation_state.py::RecommendationPolicy.project`: 소유자 delivery 조회와 current hide/refill을 처리한다. `routers/recommendations.py::list_recommendation_notifications`는 그 Top5 projection을 노출한다.
- `routers/recommendations.py::record_recommendation_feedback`, `routers/recommendations.py::record_recommendation_read_state`, `routers/recommendations.py::record_recommendation_exposure`: preference/hard suppression, 읽음, 실제 노출을 분리하는 API 진입점이다.
- `src/recommendation_evaluation.py::evaluate_manifest`와 `src/recommendation_evaluation.py::project_case`: frozen 비교와 제품 projection 공유 지점이다. 실행 워크플로는 [.github/workflows/daily-recommendations.yml](../.github/workflows/daily-recommendations.yml), 현재 운영 계약은 [daily-recommendations.md](daily-recommendations.md)를 따른다.

## Offline evaluator

구현: [recommendation_evaluation.py](../src/recommendation_evaluation.py), [CLI](../scripts/evaluate_daily_recommendations.py), [synthetic fixture](../data/recommendation_eval/public_fixture_manifest.json), [authored tests](../tests/test_recommendation_evaluation.py).

```sh
python3 scripts/evaluate_daily_recommendations.py --manifest data/recommendation_eval/public_fixture_manifest.json --offline
python3 scripts/evaluate_daily_recommendations.py --manifest data/recommendation_eval/public_fixture_manifest.json --offline --validate-only
python3 scripts/evaluate_daily_recommendations.py --manifest data/recommendation_eval/public_fixture_manifest.json --offline --report-out data/recommendation_eval/local-report.json
```

`--report-out`은 eval 디렉터리 안의 새 파일만 허용하고 기존 파일을 덮어쓰지 않는다. stdout은 structured JSON이다. exit **0**=manifest 정합성 검증만 통과(`--validate-only`, 품질/승격 아님), **1**=Top5/slice 또는 safety hard failure, **2**=invalid/unsafe/unreadable evidence 또는 CLI 사용 오류, **3**=평가 완료하였으나 inconclusive/nonpromotion. 포함 fixture의 예상 exit는 평가 **3**, validation **0**이다. 이는 실행 결과 주장이 아니다.

Python API:

- `load_manifest(path, *, root=None) -> dict`: `data/recommendation_eval` 아래 bounded JSON, 중복 key/nonfinite/path traversal/symlink 거절.
- `validate_manifest(manifest, *, root=None) -> None`: code/policy/config/input/protocol SHA256와 strict schema 검사.
- `evaluate_manifest(manifest, *, root=None) -> dict`: 비교별 primary/slices/@12 metrics, raw denominators, cluster paired CI, 사유와 별도 운영 필요조건 반환.
- `score_case(case, variant, *, cutoff, k=5) -> dict`, `project_case(case, variant, *, limit=5) -> list[dict]`: pure offline arithmetic/shared serving projection.

### Frozen manifest와 신뢰 경계

Manifest는 schema `recommendation-offline-v1`, scope `evaluation_only_non_serving`, evidence kind, cutoff/label_cutoff, 고정 config, code/policy hash, inline input digest, provenance/protocol digest를 가진다. 비교는 scorer 비교(동일 canonical candidate universe와 서지 metadata) 또는 candidate_supply 비교(동일 scorer/config) 하나만 지정한다. 두 효과를 한 비교에서 섞지 않는다. cases에는 opaque synthetic/public-profile cluster, 사전 지정 slice, eligible 분모, features/labels 시점, 최소 policy snapshot, finite 0–3 label, frozen baseline/candidate ranked bibliographic lists만 허용한다. notes/query/raw events/user 식별자 등의 추가 필드는 거절한다. `final_rank`는 양의 연속 정수이며 duplicate canonical key는 거절한다.

features와 수집/생성/발행 metadata는 cutoff 이하여야 하고 label time은 cutoff 이후 label_cutoff 이하여야 한다. 미래 저장/리뷰를 profile feature로 되먹이지 않는다. 같은 user/profile cluster의 여러 관측은 먼저 평균한 뒤 cluster 단위로 paired bootstrap한다. synthetic 시각은 실제 event time의 인증 증거가 아니다.

SHA256는 변조 탐지이지 provenance 진실성, independent judge, captured current-v2 baseline, tuning 전 protocol freeze의 인증이 아니다. checksum과 자기 선언만으로 독립 판정 적격성을 부여하지 않는다. source/capture, blind judge instructions/disagreement, temporal split, 실제 exposure/eligible/active/unavailable/visible user-day 분모가 검증되지 않으면 승격하지 않는다. 이 harness는 private DB/events/users를 열지 않고 network/paid judge를 호출하지 않는다. 허용된 text 필드에 민감정보가 없다는 content audit까지 hash가 대신하지 못한다.

포함 fixture는 **실제 논문이 아닌 synthetic bibliographic-shaped arithmetic records**와 저자 지정 label이다. 36개의 가상 profile cluster는 실사용자 36명이나 통계적 독립성 증거가 아니다. product candidate schema/root와 다른 eval 전용 schema이며 candidate ingestion/기본 fallback으로 사용할 수 없다. 실제 공개 paired judgments 또는 과거 current-v2 capture를 발명하지 않는다. 코드/policy 변경 시 기존 receipt가 invalid되는 것은 의도된 동작이며 새 승인된 freeze가 필요하다.

### 지표와 gate

- **Primary**: post-policy Top5 NDCG@5, unconditional positive Recall@5, eligible visible-user coverage. 후보 밖 labeled positives를 unconditional recall 분모에 포함하고 candidate-conditional recall 및 candidate positive coverage를 별도 보고한다. suppression이 분모를 몰래 줄이지 않는다.
- **Secondary**: @12 reserve NDCG/Recall/MRR, source/topic diversity, publication/collection/generated age. **@12 개선은 @5 regression을 보상할 수 없다.**
- 평가도 current serve-time policy **이전**에 final order/rank를 유지한 K12 delivery reserve를 고정한다. 첫12개가 모두 suppressed이면 @5/@12는 empty이며 rank13 이후로 refill하지 않는다. 전체 candidate universe는 unconditional/conditional recall 분모와 candidate positive coverage 진단에 별도로 유지하지만 reserve 밖 후보에 visible credit을 주지 않는다.
- Gain=`2**label-1`, positive=`label>0`. unjudged candidates/빈 positive 분모는 unknown이다. baseline NDCG=0 또는 bootstrap zero baseline은 사전 등록한 inconclusive이며 무한 개선/임의 epsilon을 쓰지 않는다.
- 결정론 seed 20260925, paired user/profile-cluster bootstrap 2,000회, percentile CI95%. NDCG@5 relative delta CI 하한≥−2%; Recall@5/eligible coverage absolute delta CI 하한≥−2%p.
- ko/en, cold/sparse/active, local/merged, old/new slice에서 NDCG/Recall/coverage absolute point drop≤5%p. 30 cluster primary/10 cluster slice는 최소 screening일 뿐 power 증명이 아니다. missing/underpowered slice는 pass가 아니라 inconclusive.
- rank/privacy/hide/incarnation/budget safety violation은 하나라도 hard fail. 보고된 0도 독립 운영 audit을 대체하지 않는다.
- merged 공급원은 Top5 judged relevance 또는 eligible candidate positive coverage gain 없으면 source utility 미판정이며 비용만 늘리는 확대 금지. local-only common을 안전 baseline으로 사용한다.
- synthetic correctness 100개 이상과 공개 bibliographic blind paired judgments 200 profile-paper pairs는 서로 다른 목표다. pair 수는 독립 user 수 또는 real-user personalization 증거가 아니다. authored parameterized tests에는 126개 size×suppression×read/hide 시나리오 외 @12-pass/@5-fail, future leak, NaN, path/privacy, empty, zero, confounding, unknown judge/power 시나리오가 있다. 작성 수는 실행 통과 수가 아니다.

## 별도 운영·온라인 gate (미측정)

Offline JSON은 `operational_metrics.observed=null`과 요구조건을 분리한다. offline 품질 수치가 통과해도 이 CLI는 `promotion=false`이다. 실제 결과는 별도 승인된 관측/독립 검토가 필요하며 fixture로 채우지 않는다.

1. **Shadow**: serving root 밖에서 최소7 daily runs. common delivery/eligible≥99%, >36h stale≤1%, rank/privacy/hide/incarnation violation0, call/time budget 초과0. unavailable도 전체 active 분모로 보고한다.
2. **Canary**: 기존 v2 eligible 중 최대10명 또는5% 작은 쪽, 최소7일 안전 관찰. 소표본은 기능 검증이지 효과 입증이 아니다.
3. **Online**: 실제 visible Top5만 outcome 귀속. primary는 visible user-day 중7일 내 귀속 저장/리뷰 시작, CTR은 secondary. user fixed assignment/activity 층화, 최소14일, α0.05/power80%/relative MDE10% 사전 표본 계산. repeated cards는 독립 users가 아니다. insufficient는 opt-in 유지/미판정.
4. **확대**: primary delta CI95% 하한>0, delivery≥99%, stale≤1%, impression duplicate≤0.1%, known-view linkage 누락≤1%, hide rate 악화 CI 상한≤1%p, safety0와 offline Top5 gate 동시 충족. 기존 eligible 내부5→25→100%, 각7일 이상; 전역 flag는 별도 승인.
5. **성능**: 100 users×10k public+user500 private/500 events, K12/M200, hardware/worker 기록. user p95≤2초, batch≤10분, RSS≤1GiB. 미측정 상태에서 빠르다고 주장하지 않는다.
6. **Source qualification**: adapter fixture, 실제 source owner/provenance/transport/cost, merged-source utility 세 receipts를 분리한다. public provider 획득과 OpenClaw 적격성이 미확인이면 운영 완료가 아니다.

### 7일 visible-outcome 관측 계약

로컬 helper [recommendation_attribution.py](../src/recommendation_attribution.py)는 성공적으로 commit된 저장/리뷰 시작 이후에만 호출한다. Producer는 기존 Users guard 밖에서 captured incarnation, 실제 committed paper metadata, stable outcome ID를 전달한다. 제한된 서지 식별 필드에 공통 `normalize_candidate`를 적용하며 private text와 클라이언트 canonical/run/exposure 주장은 사용하지 않는다. 현재 authority guard와 strict state가 최종 귀속을 수행한다. primary 실패/취소는 귀속하지 않으며, attribution 장애가 이미 성공한 저장을 실패 응답으로 바꾸어서는 안 된다.

State 계약은 동일 incarnation/paper의 직전7일 qualified visibility 중 결정론적 last touch 하나에 귀속한다. Immutable receipt 키는 `(incarnation, kind, outcome_id, canonical_key)`다. 하나의 실제 producer ID에 여러 논문이 포함될 수 있으며 같은 tuple 재전송은 원래 receipt를 유지하고 추가 credit0이다. Credit은 paper/kind/exposure-day별로 별도 중복 제거한다. 분모는 관측된 visible user-day, 분자는 저장 또는 리뷰 시작이 귀속된 distinct day의 합집합이다. Kind별 count 역시 positive user-day이며 독립 outcome 수가 아니므로 primary 분자로 합산하지 않는다. UTC exposure day의 종료+7일이 관측시각 이하일 때만 mature이며 나머지는 right-censored로 분리한다. 인과 효과나 CTR 대체 지표가 아니다.

`python -m src.recommendation_attribution --users-db ... --events-db ... --username ... --since ISO --until ISO --now ISO`는 명시적 로컬 DB/aware 시각만 사용한다. since/until은 UTC 자정 기준 half-open interval이다. 현재 active incarnation을 capture한 뒤 guard 안에서 `outcome_metrics`를 읽으며 network/public serving/private export 경로는 없다. `total`, `mature`, `right_censored` 각각 raw numerator/denominator, save/review_start count, zero denominator의 null rate를 유지한다.

Best-effort producer hook과 미확인 coverage 때문에 **observed-only, capture completeness unknown, causality false, promotion false**다. 관측 positive count는 누락 가능한 하한이지만 exposure도 누락될 수 있으므로 관측 rate를 모집단 rate 하한이라고 주장하지 않는다. outcome/receipt의 state retention과 incarnation 삭제를 검증해야 하며, pruned history는 복원된 전체 분모로 취급하지 않는다. helper/CLI 작성은 state 및 실제 producer hook 통합·테스트 완료의 증거가 아니다. 위 온라인 확대 gate는 이 관측 도구만으로 통과하지 않는다.

## 남은 검증과 확장 순서

1. authoritative lifecycle/auth와 common publisher의 file→GET5→DOM 순서, current hide/refill, 실제 visibility exposure linkage를 함께 검증한다. 이벤트 장애 시 degraded feature fallback과 policy/identity fail-closed를 구분한다.
2. 승인된 실제 public acquisition evidence를 확보하고 bootstrap source absent와 nonempty 수직 경로를 각각 검증한다. receiver credential/export/privacy/capacity boundary를 독립 검토한다.
3. frozen temporal holdout과 independent blind labels, disagreement 기록, 실제 baseline capture를 준비한다. scorer/supply 및 MMR/negative/recency/related ablation을 한 변수씩 분리하고 holdout 재튜닝을 금지한다.
4. 실제 운영/온라인 분모와 충분한 power 없이는 확대하지 않는다. 한국어 형태소·한영 synonym·metadata identity 한계는 실제 실패 slice를 근거로 개선한다. 새 embedding/semantic/LTR/paid judge는 현재 범위 밖이다.

Rollback은 외부 후보 disable→검증된 local-only common 또는 이전 안전 common ranker/config이다. lifecycle/incarnation, current suppression, schema/privacy/36h stale·72h expiry를 유지한다. old JWT 수용, raw OpenClaw serving, skip-existing, private seed export, score-sort reader로 되돌리지 않는다. 검증된 안전 artifact가 없으면 empty/stop이며 fake fallback을 만들지 않는다.
