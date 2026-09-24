# 최근 발행 논문 리뷰 10편 심층 검토·수정

## 결과

2026년 9월 6~15일 실제 발행된 최근 논문 리뷰 10편을 원문 판본과 대조하고, 독립 비판 검토·사실 검증을 거쳐 수정했다. 원래 있던 상세 설명과 도판을 유지하면서 방법의 작동 순서와 지표의 의미를 보강했다. 근거가 부족한 기존 비판도 삭제하거나 범위를 좁혔다.

**현재 상태: 10편 발행 및 PaperWiki 동기화 완료. 공개 API·게시물 10곳과 그림 62개를 검증했다.**

발행 시각: 2026-09-15 23:01 KST. [발행 영수증](publication-receipt.json) · [공개 본문 검증](live-publication-validation.json) · [그림 검증](live-figure-validation.json) · [PaperWiki 검증](paperwiki-publication-validation.json).

## 중요한 교정

| 글 | 확인한 문제 | 수정 |
| --- | --- | --- |
| RSI Roadmap | `first-party`를 ‘1차 출처’로 옮겨 자기 보고 가중과 출처 유형을 혼동 | 모델·시스템 제공자의 자기 보고값으로 교정. HCI 계산 예시와 B0–L5의 지속성·권한·상속 예시 추가 |
| RSI Roadmap | 반올림 원인과 저자 소속의 의미를 지나치게 확정. 주 논문 References 누락 | 가능한 설명과 확인 사실을 분리. 주 논문의 APA 서지 추가, DGM의 확인되지 않은 권·쪽수 제거 |
| InCoder | 학습/holdout 서술 차이를 실제 오염처럼 해석. 자체 벤치마크 1위 부재로 편향 부재 추정 | 분할 자료 확인 전의 불확실성으로 한정. 순위로 편향을 판정한 문장 삭제 |
| InCoder | G-exe의 분모가 확정된 것처럼 서술. 360M→540M를 ‘배증’이라 표현 | 원문과 일관된 조건부 해석으로 표시하고 분모 미명시 유지. 1.5배로 교정 |
| InCoder | 체크포인트 차이를 사고 학습의 순수 효과로 귀속 | 데이터량도 다른 비교임을 명시. ECoT·ICWM·최종 코드 모델의 학습 신호를 표로 구분 |
| WikiProfile | 같은 이름의 `Knows`가 도표별로 다른 집계임을 놓치기 쉬움 | Figure 4/13의 잠재적 knowledge, Table 2의 Direct Inference 포함 처리, thinking 성능을 구분. 문턱·비채점 예시 추가 |
| CLAUSE | list-wise 선택을 예산 내 최적 부분집합 탐색으로 오독할 수 있음 | Algorithm 4의 최고점 후보 선택과 초과 시 종료를 설명. 실행의 근거 흐름과 학습의 지연 보상을 연결 |

위 내용은 기존 리뷰 대비 이번 수정이다. TTPO의 +5.0pp, PG의 sign test, CFM의 비교 범위처럼 기존 글에 이미 반영되어 있던 정확한 내용은 대조 후 유지했으며 이번에 새로 고쳤다고 집계하지 않았다.

## 글별 수정본과 근거

| 글 | 보강한 논문 설명 | 산출물 |
| --- | --- | --- |
| RSI Roadmap | HCI 계산, 같은 에이전트의 B0–L5 분류 예시 | [수정본](articles/rsi-roadmap/revised.md) · [근거](articles/rsi-roadmap/evidence.md) |
| TTPO | 다수 답 A와 소수 답 B/C의 KL·GRPO 분기, 잘못된 벌점이 남는 조건 | [수정본](articles/ttpo/revised.md) · [근거](articles/ttpo/evidence.md) |
| InCoder-32B-Thinking | 실제 실행 궤적과 개별 턴이 두 모델의 학습으로 이어지는 경로 | [수정본](articles/incoder-32b-thinking/revised.md) · [근거](articles/incoder-32b-thinking/evidence.md) |
| CodeNib | commit manifest 확인→검색/내비게이션→Eager/Compact 컨텍스트 전달 | [수정본](articles/codenib/revised.md) · [근거](articles/codenib/evidence.md) |
| RAG vs. GraphRAG | 같은 top-10의 다른 토큰량, token-matched 결과와 Temporal 예외 | [수정본](articles/rag-vs-graphrag-systematic-evaluation/revised.md) · [근거](articles/rag-vs-graphrag-systematic-evaluation/evidence.md) |
| Procedural Graphs | episode 내 guidance와 batch 경계의 graph evolution 구분 | [수정본](articles/procedural-graphs/revised.md) · [근거](articles/procedural-graphs/evidence.md) |
| Agent Memory Distillation | WF/ST 사전 주입과 오류 후 함수명으로 제한한 FN 검색 | [수정본](articles/agent-memory-distillation/revised.md) · [근거](articles/agent-memory-distillation/evidence.md) |
| Causal Foundation Models | 관측 context, 두 처치 CEPO query, posterior mean 차이의 CATE 추정 | [수정본](articles/causal-foundation-models/revised.md) · [근거](articles/causal-foundation-models/evidence.md) |
| WikiProfile | 존재/전칭 판정과 엄격한 문턱의 가상 예시, knowledge 집계 | [수정본](articles/wikiprofile-empty-shelves-lost-keys/revised.md) · [근거](articles/wikiprofile-empty-shelves-lost-keys/evidence.md) |
| CLAUSE | 세 정책의 상호 의존성과 Curator의 종료 조건 | [수정본](articles/clause-budget-aware-kg-reasoning/revised.md) · [근거](articles/clause-budget-aware-kg-reasoning/evidence.md) |

## 에이전트 검토와 재판정

논문별 작성 담당과 후속 검토 담당을 분리했다. 초기 [비판 검토](critical-pass.json)에서 RSI·CLAUSE·WikiProfile에 대해 제기한 항목을 원문과 다시 대조했다. 필요한 수정은 반영했으며, 이미 의사코드 범위로 명확히 한정된 CLAUSE의 hard-cap 비판은 근거를 기록하고 기각했다. [재판정 기록](critique-resolution.json)과 [최종 비판 검토](final-critical-pass.json)에 결과를 남겼다. 최종 필수 수정 사항은 없다.

[별도 사실 검증](verification-pass.json)의 유일한 후속 항목인 CFM의 CEPO 첫 사용 정의 누락은 한영 정의를 추가해 해결했다. 초기 검증 기록은 당시 판정을 보존하며, 해결 여부는 재판정·최종 검증 기록으로 확인한다. 주요 결과와 신규 설명을 대조했으며, 논문의 모든 실험을 독립 재현했다는 의미는 아니다.

## 변경 범위

- 게시 데이터: `data/blog/posts.json`의 대상 10편 본문·요약·수정일·읽기 시간.
- 로컬 목록에 없던 최신 4편은 공개 API의 기존 게시물 ID·최초 발행일·제목·태그·도판 주소를 그대로 가져와 수정했다. 새 게시물을 생성하거나 URL을 바꾸지 않았다.
- 기존 도판 62개의 URL과 순서를 보존했다. 로컬에 없던 도판 26개는 이미 발행된 파일을 내려받았다. 신규 도판 생성·편집은 하지 않았다.
- 대상 외 76편은 작업 시작 상태와 동일하다. 다른 코드 변경은 이번 작업의 범위에 포함하지 않았다.
- 각 article 폴더에 원본, 수정본, 적용 JSON, 근거, 변경 요약과 diff를 보존했다. `baseline-posts.json`은 변경 전 로컬 전체 목록이다.

## 검증

| 검증 | 결과 |
| --- | --- |
| 백엔드 블로그·검색·태그·SEO | 78개 통과 |
| 프런트엔드 블로그·논문 메타데이터 | 31개 통과 |
| TypeScript + Vite build | 통과 |
| 10편 수식 KaTeX 엄격 파싱 | 392개 통과 |
| 기존 도판 URL·순서·로컬 파일 | 62개 보존·확인 |
| 실제 서버 렌더러와 논문 메타데이터 추출 | 10편 통과 |
| JSON·섹션 번호·References·메타데이터·대상 외 보존 | 통과 |

실행 명령:

```sh
.venv/bin/pytest -q tests/test_blog_slug.py tests/test_blog_search.py tests/test_blog_tags.py tests/test_seo.py
npm --prefix web-ui test -- src/test/blogPaperReference.test.ts src/test/BlogPage.search.test.tsx src/test/BlogPage.tag.test.tsx src/test/BlogTagsPage.test.tsx
npm --prefix web-ui run build
node docs/reviews/recent-paper-audit-2026-09-15/validate-content.mjs
git diff --check -- data/blog/posts.json docs/reviews/recent-paper-audit-2026-09-15
```

테스트에는 기존 의존성의 deprecation 경고, 빌드에는 큰 JavaScript chunk 경고가 있었으며 실패는 없었다. 결과는 [내용 검증](content-validation.json), [서버 렌더링](ssr-validation.json), [로컬 반영](local-integration.json), [최종 검증](final-verification.json)에 보존했다.

## 발행·PaperWiki 상태와 남은 범위

- **블로그:** 검토된 10편을 기존 URL에 반영했다. 대상 외 76편과 최초 발행일·태그·제목·ID를 보존했다.
- **PaperWiki:** 기존 원고 10편을 백업하고 수정 내용을 병합했다. 원래 YAML 메타데이터와 PaperWiki에만 있던 추가 출처 링크를 보존했다. [대응 경로](paperwiki-sync-map.json)와 [백업](paperwiki-backups/)을 남겼다.
- **실험:** PDF·공식 공개 자료를 대조했으며 모델 재학습, 벤치마크 재실행, 모델의 생산 환경 성능 평가는 수행하지 않았다. 게시물·그림의 실제 HTTP 응답은 발행 후 검증했다.
- 원논문의 불일치, 공개되지 않은 분모·분할·원자료 등은 각 글에서 확인된 사실과 추론을 나누어 명시했다.

## 발행 후 확인

- 전체 게시 데이터 86편 가운데 대상 10편만 변경했다. 운영 서버에서 파일 잠금·변경 충돌 검사·원자적 교체를 사용했다.
- 운영 원본 백업: `/home/ubuntu/PaperReviewAgent/data/blog/backups/posts-before-recent-review-20260915T140124945725Z.json`.
- 공개 API의 본문·요약·메타데이터가 검토한 `post.json`과 일치한다.
- 기존 URL 10곳이 HTTP 200으로 응답하며 요약·References·도판을 포함한다.
- 그림 62개의 HTTP 응답과 파일 해시가 로컬 검증 파일과 일치한다.
- `local-integration.json`은 발행 전 로컬 반영 시점의 기록이며, 최신 발행 상태는 `publication-receipt.json`과 `final-verification.json`을 따른다.

## 후속 excerpt 수정

동일한 10편의 excerpt를 별도로 검토해 연구 기여·결과 중심의 두 문장으로 수정하고 발행했다. 최신 excerpt와 수정일은 [후속 검토 보고서](excerpt-revision/REPORT.md) 및 [공개 검증](excerpt-revision/live-validation.json)을 따른다. 기존 본문은 그대로 유지했다.
