# 최근 리뷰 10편 excerpt 심층 검토·수정

## 결과와 검토 기준

최근 발행한 동일한 10편을 대상으로 excerpt를 수정했다. 기존 문구에는 검토 항목·약어·재현성 쟁점을 열거하는 형태가 많아, 목록 카드에서 연구 기여를 바로 파악하기 어려웠다. 수정본은 두 문장, 110~138자로 구성하며 첫 문장에 방법·기여, 둘째 문장에 결과와 필요한 해석 범위를 배치한다.

- 확정된 본문과 근거 기록을 기준으로 대조했다. 새로운 실험 결과나 수치를 덧붙이지 않았다.
- 리스트 카드가 두 줄로 제한되므로 핵심을 앞에 배치했다. 모든 화면에서 전체 문구가 두 줄 안에 보인다고 가정하지 않는다.
- 문체를 ‘한다’로 통일하고 ‘분석하고 검토합니다’라는 글 소개를 실제 연구 내용의 요약으로 바꿨다.
- 방법마다 필요한 범위 제한을 남겼다. 모든 글에 같은 재현성 경고를 반복하지 않았다.

## 독립 검토와 반영

[사실 검토](factual-review.json)와 [한국어 편집 검토](editorial-review.json)를 서로 다른 에이전트가 수행했다. 최종 [재검토](final-review.json)는 통과했다.

| 항목 | 판단과 반영 |
| --- | --- |
| PG의 ‘다음 과제에 반영’ | ‘별도 개선 단계’에서 수정안을 검증한다고 바꿔 실행 중 안내와 그래프 개선을 구분했다. |
| WikiProfile의 ‘추가 추론’ | ‘thinking을 켜면’의 관측 결과로 바꿔 회상 촉진과 추론의 기여를 단정하지 않았다. ‘행동 평가’임을 앞에서 명시했다. |
| TTPO의 ‘다른 답변’ | 유사라벨과의 일치·불일치에 따른 ‘답변의 생성 과정’으로 풀었다. 카드에서 GRPO·rollout 약어를 늘리는 제안은 가독성을 고려해 적용하지 않았다. |
| AMD의 평가 조건 | 평가 과제의 교사 경험이 메모리에 포함됐는지에 따라 결과를 구분해야 한다고 구체화했다. |
| RAG 비교 | 긴 둘째 문장을 압축하면서 질문·근거 표현·토큰 통제의 핵심을 유지했다. |

## 변경 전후

| 게시물 | 이전 excerpt | 최종 excerpt | 글자 수 |
| --- | --- | --- | ---: |
| [The Last AI Built by Humans: Toward Genuine Recursive Self-Improvement](https://jiphyeonjeon.kr/blog/rsi-roadmap) | 재귀적 자기개선을 능력이 아니라 개선 루프의 책임 이전으로 정의하고 다섯 수준으로 나눈 75쪽 서베이를 검토한다. 헤드룸 지표가 실제로 보여 주는 것, 구조적 재귀와 실효적 재귀의 구분, 그리고 491편이라는 조사 규모가 논문 안에서 어디까지 확인되는지를 따진다. | AI가 개선 실행부터 전략·경험 수집·배포 적응·개선 절차 자체까지 맡는 과정을 다섯 수준으로 정리한 서베이다. 자율성의 확대와 실제 성능 향상을 구분하며, 세대를 거친 개선 능력의 누적은 아직 입증 과제로 남는다. | 120 |
| [TTPO: Test-Time Policy Optimization](https://jiphyeonjeon.kr/blog/ttpo) | TTPO가 다수결과 일치하는 롤아웃에는 증류를, 다른 답에는 GRPO 벌점을 적용하는 원리를 설명하고, 사고모드 교사·체크포인트 선택·실험 해석을 검토합니다. | TTPO는 다수결로 얻은 유사라벨과 일치하는 답변의 생성 과정에는 자기증류를, 불일치하는 과정에는 선택적 벌점을 적용한다. 정답 라벨 없이 수학 추론 성능을 높였지만, 틀린 다수결이 정답에 벌점을 주는 위험은 남는다. | 121 |
| [InCoder-32B-Thinking: Industrial Code World Model for Thinking](https://jiphyeonjeon.kr/blog/incoder-32b-thinking) | 실행 오류에서 추론 사슬을 합성하는 ECoT와 툴체인 피드백을 대신 예측하는 산업용 코드 월드 모델의 설계를 설명하고, 일반·산업 벤치마크 결과를 자기 instruct 판본과 대조해 '모든 도메인 최고'라는 서술이 어디까지 성립하는지 검토합니다. | InCoder-32B-Thinking은 실제 실행 오류와 수정 기록으로 추론 데이터를 만들고, 학습된 실행 예측 모델로 이를 늘린다. 같은 계열의 비사고 모델보다 코드 추론 성능은 높지만, 산업 과제의 성능 변화는 지표마다 다르다. | 129 |
| [CodeNib: A Multi-View Data System for Serving Repository Context to Coding Agents](https://jiphyeonjeon.kr/blog/codenib) | CodeNib의 커밋별 lexical·dense·structural 뷰와 컨텍스트 전달 흐름을 설명하고, 검색·증분 갱신·내비게이션 실험의 품질과 비용을 분석합니다. | CodeNib은 저장소 커밋별로 문자열·의미·코드 구조 색인을 만들어 에이전트의 검색과 컨텍스트 구성을 지원한다. 검색·갱신·위치 파악의 품질과 비용을 나눠 평가하며, 보고된 속도 향상은 각 실험의 품질 조건을 통과한 범위에 한정된다. | 131 |
| [RAG vs. GraphRAG: A Systematic Evaluation and Key Insights](https://jiphyeonjeon.kr/blog/rag-vs-graphrag-systematic-evaluation) | RAG와 GraphRAG의 검색 단위와 토큰 통제 실험을 비교하고, 질문 유형별 성능·혼합 검색·평가자 편향·구축 비용을 공개 v3 근거로 분석합니다. | RAG와 여러 GraphRAG를 질의응답·요약에서 비교한 연구다. 우열은 질문 유형과 근거 표현에 따라 달라지며, 입력 토큰량을 맞추면 일부 차이가 줄어 구조와 맥락 길이의 효과를 함께 봐야 한다. | 110 |
| [Procedural Graphs: Self-Evolving Execution Structures for LLM Agents](https://jiphyeonjeon.kr/blog/procedural-graphs) | Procedural Graphs가 절차 지식을 그래프로 저장·안내·진화시키는 방식을 설명하고, soft guidance의 범위, held-out gate, 구성 비교, token 비용과 EnterpriseArena 결과를 v1 기준으로 검토합니다. | Procedural Graphs는 절차 그래프로 행동을 안내하고, 별도 개선 단계에서 경험을 반영한 그래프 수정안을 검증한다. 여러 모델·벤치마크 조합에서 우세했지만, 안내가 행동을 강제하거나 이후 성능 향상을 보장하지는 않는다. | 128 |
| [Agent Memory Distillation: Empowering Small LLM Agents with Hierarchical Teacher Memory](https://jiphyeonjeon.kr/blog/agent-memory-distillation) | AMD의 교사 궤적을 Workflow·Subtask·Function 메모리로 바꾸는 절차를 설명하고, 본평가와 과제 분리 평가, 구성요소·교사 ablation, 비용·재현성 경계를 원문 v1 기준으로 검토합니다. | AMD는 교사의 성공 경험을 전체 계획·하위 과제·함수 호출 메모리로 나눠, 작은 에이전트가 가중치 갱신 없이 활용하게 한다. 세 도구 사용 벤치마크에서 성능이 개선됐으며, 평가 과제의 교사 경험이 메모리에 포함됐는지에 따라 결과를 구분해야 한다. | 138 |
| [Causal Foundation Models](https://jiphyeonjeon.kr/blog/causal-foundation-models) | 관측 데이터에서 인과효과를 추정하도록 사전학습한 CFM의 원리, 세 모델의 prior와 예측 분포 차이, RealCause-Lalonde 실험과 속도 비교를 분석하고 식별가능성·불확실성·일반화의 한계를 검토합니다. | 다양한 인과적 데이터 생성 과정을 미리 학습해 새 관측 데이터에서 처치 효과를 추정하는 CFM을 설명하고 세 모델을 비교한 연구다. 과제별 학습 부담을 줄일 수 있지만, 효과를 식별하는 가정과 사전학습 분포의 적합성은 여전히 필요하다. | 131 |
| [Empty Shelves or Lost Keys? Recall Is the Bottleneck for Parametric Factuality](https://jiphyeonjeon.kr/blog/wikiprofile-empty-shelves-lost-keys) | WikiProfile이 LLM의 사실 지식을 저장·회상·재인으로 나누는 방법과 주요 실험을 분석하고, 행동적 지표로 내부 기억을 해석할 때의 한계, thinking과 RAG에 주는 시사점을 검토한다. | WikiProfile은 같은 사실의 문맥 속 복원, 정·역방향 질문 응답, 객관식 선택을 비교하는 행동 평가다. 일부 강한 모델도 문맥에서 복원한 사실에 안정적으로 답하지 못하며, thinking을 켜면 그중 일부가 개선된다. | 126 |
| [CLAUSE: Agentic Neuro-Symbolic Knowledge Graph Reasoning via Dynamic Learnable Context Engineering](https://jiphyeonjeon.kr/blog/clause-budget-aware-kg-reasoning) | CLAUSE의 세 에이전트와 LC-MAPPO가 그래프 확장·경로 탐색·근거 선택을 예산 아래 공동 학습하는 원리를 설명하고, 정확도·효율 실험과 제약 보장·이론·재현성의 경계를 분석한다. | CLAUSE는 지식 그래프의 편집·경로 탐색·근거 선택을 세 정책으로 공동 학습해 정확도와 자원 비용을 조절한다. 저자 실험에서 질의응답 정확도와 일부 효율 지표가 개선됐지만, 학습된 비용 제약만으로 모든 질의의 예산 준수가 보장되지는 않는다. | 136 |

## 반영과 검증

- 실제 게시 데이터 86편 중 대상 10편의 excerpt와 수정일만 변경했다. 본문·제목·URL·최초 발행일·태그·읽기 시간과 대상 외 76편을 보존했다.
- PaperWiki의 대응 원고 10편도 excerpt와 수정일만 동기화하고 이전 파일을 백업했다. RSI 원고의 메타데이터가 동기화 중 다시 저장된 것을 확인해, 현재 서식과 나머지 필드를 보존한 채 excerpt만 재병합했다.
- 블로그·검색·SEO 관련 테스트 64개가 통과했다.
- 공개 목록/상세 API, 상세 페이지 요약, 검색 설명·Open Graph·Twitter 메타데이터, JSON-LD, RSS, PaperWiki가 확정 excerpt와 일치하는지 확인했다.
- 수정 전후 본문이 동일함을 검증했다. excerpt만 바뀌었으므로 모델 실험이나 프런트엔드 코드를 변경하지 않았다.

[운영 반영 영수증](publication-receipt.json) · [PaperWiki 영수증](wiki-receipt.json) · [공개 검증](live-validation.json)

```sh
.venv/bin/pytest -q tests/test_seo.py tests/test_blog_search.py
.venv/bin/python docs/reviews/recent-paper-audit-2026-09-15/excerpt-revision/verify-live.py
node docs/reviews/recent-paper-audit-2026-09-15/validate-content.mjs
```
