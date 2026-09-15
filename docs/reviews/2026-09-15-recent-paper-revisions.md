# 최근 논문 리뷰 10편 수정 기록 — 2026-09-15

논문 본문의 방법·실험 결과를 더 명확히 전달하고, 기존 리뷰의 근거보다 강한 해석을 교정했다. Excerpt는 검토 항목의 나열에서 핵심 기여와 결과·해석 범위를 전달하는 두 문장(110~138자)으로 바꿨다.

## 범위

- `data/blog/posts.json`의 기존 리뷰 10편에서 `content`, `excerpt`, `updated_at`, `reading_time_min`만 변경했다.
- 기존 ID·제목·URL·최초 발행일·태그·카테고리·그림을 보존했다. 대상 외 76편과 기존 그림 62개는 변경하지 않았다.
- 작성 담당과 독립 사실·비판 검토 담당을 분리했다. 아래 설명은 논문 보고와 직접적인 해석을 구분하며, 실험을 독립 재현했다는 의미는 아니다.

## 글별 변경과 근거

| 리뷰 | 주요 변경 | 검토한 논문 판본 |
| --- | --- | --- |
| [The Last AI Built by Humans: Toward Genuine Recursive Self-Improvement](https://jiphyeonjeon.kr/blog/rsi-roadmap) | first-party를 자기 보고값으로 교정하고 HCI 계산 및 B0–L5 상속 예시를 보강했다. 반올림 원인·소속의 의미를 단정하지 않으며 주 논문의 서지를 추가했다. | [원문](https://arxiv.org/abs/2609.11873v1) |
| [TTPO: Test-Time Policy Optimization](https://jiphyeonjeon.kr/blog/ttpo) | 다수 답과 소수 답에 적용하는 증류·GRPO 분기를 예시로 설명하고, 잘못된 유사라벨이 정답에 벌점을 줄 수 있다는 한계를 요약에 반영했다. | [원문](https://arxiv.org/abs/2608.27448v1) |
| [InCoder-32B-Thinking: Industrial Code World Model for Thinking](https://jiphyeonjeon.kr/blog/incoder-32b-thinking) | 코드 모델과 실행 예측 모델의 학습 신호를 구분했다. 평가 분할·G-exe 분모를 확정한 표현을 완화하고, 360M→540M를 1.5배로 교정했다. | [원문](https://arxiv.org/abs/2604.03144v1) |
| [CodeNib: A Multi-View Data System for Serving Repository Context to Coding Agents](https://jiphyeonjeon.kr/blog/codenib) | 커밋 manifest→검색·내비게이션→컨텍스트 전달을 연결하고 속도 결과의 실험 조건을 요약했다. | [원문](https://arxiv.org/abs/2607.25431v1) |
| [RAG vs. GraphRAG: A Systematic Evaluation and Key Insights](https://jiphyeonjeon.kr/blog/rag-vs-graphrag-systematic-evaluation) | 같은 top-10의 다른 토큰량과 토큰 통제 실험을 설명하고 질문 유형·근거 표현에 따른 결과 차이를 요약했다. | [원문](https://arxiv.org/abs/2502.11371v3) |
| [Procedural Graphs: Self-Evolving Execution Structures for LLM Agents](https://jiphyeonjeon.kr/blog/procedural-graphs) | 실행 중 guidance와 별도 graph evolution의 시간 구분을 보강하고 검증 성능과 이후 일반화를 구분했다. | [원문](https://arxiv.org/abs/2609.09153v1) |
| [Agent Memory Distillation: Empowering Small LLM Agents with Hierarchical Teacher Memory](https://jiphyeonjeon.kr/blog/agent-memory-distillation) | WF/ST 사전 주입과 오류 후 FN 검색을 연결하고 평가 과제의 교사 메모리 포함 여부를 요약에 명시했다. | [원문](https://arxiv.org/abs/2608.07169v1) |
| [Causal Foundation Models](https://jiphyeonjeon.kr/blog/causal-foundation-models) | 관측 context와 두 처치 query에서 CATE로 이어지는 추정을 재구성하고 CEPO 정의를 보강했다. | [원문](https://arxiv.org/abs/2609.03003v1) |
| [Empty Shelves or Lost Keys? Recall Is the Bottleneck for Parametric Factuality](https://jiphyeonjeon.kr/blog/wikiprofile-empty-shelves-lost-keys) | 존재·전칭 판정과 비채점 예시를 추가하고 도표별 Knows 집계를 구분했다. thinking의 효과를 관측된 행동 변화로 요약했다. | [원문](https://arxiv.org/abs/2602.14080v2) |
| [CLAUSE: Agentic Neuro-Symbolic Knowledge Graph Reasoning via Dynamic Learnable Context Engineering](https://jiphyeonjeon.kr/blog/clause-budget-aware-kg-reasoning) | Curator의 점수 순 선택·예산 초과 시 종료와 세 정책의 학습 보상을 설명하고 기대 비용 제약을 개별 질의 보장과 구분했다. | [원문](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf) |

## 최종 excerpt

### The Last AI Built by Humans: Toward Genuine Recursive Self-Improvement

AI가 개선 실행부터 전략·경험 수집·배포 적응·개선 절차 자체까지 맡는 과정을 다섯 수준으로 정리한 서베이다. 자율성의 확대와 실제 성능 향상을 구분하며, 세대를 거친 개선 능력의 누적은 아직 입증 과제로 남는다.

### TTPO: Test-Time Policy Optimization

TTPO는 다수결로 얻은 유사라벨과 일치하는 답변의 생성 과정에는 자기증류를, 불일치하는 과정에는 선택적 벌점을 적용한다. 정답 라벨 없이 수학 추론 성능을 높였지만, 틀린 다수결이 정답에 벌점을 주는 위험은 남는다.

### InCoder-32B-Thinking: Industrial Code World Model for Thinking

InCoder-32B-Thinking은 실제 실행 오류와 수정 기록으로 추론 데이터를 만들고, 학습된 실행 예측 모델로 이를 늘린다. 같은 계열의 비사고 모델보다 코드 추론 성능은 높지만, 산업 과제의 성능 변화는 지표마다 다르다.

### CodeNib: A Multi-View Data System for Serving Repository Context to Coding Agents

CodeNib은 저장소 커밋별로 문자열·의미·코드 구조 색인을 만들어 에이전트의 검색과 컨텍스트 구성을 지원한다. 검색·갱신·위치 파악의 품질과 비용을 나눠 평가하며, 보고된 속도 향상은 각 실험의 품질 조건을 통과한 범위에 한정된다.

### RAG vs. GraphRAG: A Systematic Evaluation and Key Insights

RAG와 여러 GraphRAG를 질의응답·요약에서 비교한 연구다. 우열은 질문 유형과 근거 표현에 따라 달라지며, 입력 토큰량을 맞추면 일부 차이가 줄어 구조와 맥락 길이의 효과를 함께 봐야 한다.

### Procedural Graphs: Self-Evolving Execution Structures for LLM Agents

Procedural Graphs는 절차 그래프로 행동을 안내하고, 별도 개선 단계에서 경험을 반영한 그래프 수정안을 검증한다. 여러 모델·벤치마크 조합에서 우세했지만, 안내가 행동을 강제하거나 이후 성능 향상을 보장하지는 않는다.

### Agent Memory Distillation: Empowering Small LLM Agents with Hierarchical Teacher Memory

AMD는 교사의 성공 경험을 전체 계획·하위 과제·함수 호출 메모리로 나눠, 작은 에이전트가 가중치 갱신 없이 활용하게 한다. 세 도구 사용 벤치마크에서 성능이 개선됐으며, 평가 과제의 교사 경험이 메모리에 포함됐는지에 따라 결과를 구분해야 한다.

### Causal Foundation Models

다양한 인과적 데이터 생성 과정을 미리 학습해 새 관측 데이터에서 처치 효과를 추정하는 CFM을 설명하고 세 모델을 비교한 연구다. 과제별 학습 부담을 줄일 수 있지만, 효과를 식별하는 가정과 사전학습 분포의 적합성은 여전히 필요하다.

### Empty Shelves or Lost Keys? Recall Is the Bottleneck for Parametric Factuality

WikiProfile은 같은 사실의 문맥 속 복원, 정·역방향 질문 응답, 객관식 선택을 비교하는 행동 평가다. 일부 강한 모델도 문맥에서 복원한 사실에 안정적으로 답하지 못하며, thinking을 켜면 그중 일부가 개선된다.

### CLAUSE: Agentic Neuro-Symbolic Knowledge Graph Reasoning via Dynamic Learnable Context Engineering

CLAUSE는 지식 그래프의 편집·경로 탐색·근거 선택을 세 정책으로 공동 학습해 정확도와 자원 비용을 조절한다. 저자 실험에서 질의응답 정확도와 일부 효율 지표가 개선됐지만, 학습된 비용 제약만으로 모든 질의의 예산 준수가 보장되지는 않는다.

## 검증 및 발행

- 공개 게시본에 본문 수정과 excerpt 수정을 반영했고, 대응 PaperWiki 원고 10편을 백업 후 동기화했다.
- 공개 API·상세 페이지 10곳의 본문과 메타데이터, 기존 그림 62개의 응답·파일 해시를 확인했다.
- 최종 excerpt가 목록/상세 API, 상세 페이지 요약, 검색 설명·Open Graph·Twitter, JSON-LD, RSS에 일치함을 확인했다.
- 검토 과정에서 수식 392개를 KaTeX 엄격 모드로 확인했다. Excerpt 수정 전후 본문은 동일하다.
- 이 PR의 게시 JSON 전체가 발행된 게시 JSON과 일치함을 확인하고, 최신 main을 기준으로 블로그·검색·태그·논문 참조·시리즈·썸네일·SEO 테스트를 실행했다.

```sh
pytest -q tests/test_blog_slug.py tests/test_blog_search.py tests/test_blog_tags.py tests/test_blog_references.py tests/test_blog_series_sync.py tests/test_blog_thumbnails.py tests/test_seo.py
git diff --check
```

발행된 내용의 버전 관리를 위한 PR이며 모델·서버·프런트엔드 구현은 변경하지 않는다.
