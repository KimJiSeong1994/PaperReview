---
title: "Procedural Graphs: Self-Evolving Execution Structures for LLM Agents"
slug: procedural-graphs
excerpt: "Procedural Graphs가 절차 지식을 그래프로 저장·안내·진화시키는 방식을 설명하고, soft guidance의 범위, held-out gate, 구성 비교, token 비용과 EnterpriseArena 결과를 v1 기준으로 검토합니다."
category: AI Agents
tags:
  - procedural-graphs
  - agent-memory
  - self-evolution
  - tool-use
  - context-engineering
status: "published"
published_at: "2026-09-11T09:30:00.424776+00:00"
blog_url: "https://jiphyeonjeon.kr/blog/procedural-graphs"
date: "2026-09-11"
reviewed_at: "2026-09-15"
paper_version: "arXiv:2609.09153v1, 2026-09-08"
source_paper: "https://arxiv.org/pdf/2609.09153v1"
thumbnail: "figures/pg-fig2-framework.png"
updated_at: "2026-09-15T13:51:19.265918+00:00"
---

# Procedural Graphs: Self-Evolving Execution Structures for LLM Agents

**Paper:** Yuxing Lu; Yicheng Chen; Shanchan Wu; Sercan Ö. Arık (2026). "Procedural Graphs: Self-Evolving Execution Structures for LLM Agents". https://arxiv.org/abs/2609.09153v1 · arXiv:2609.09153v1. 이 글은 2026년 9월 8일 공개된 36쪽의 v1을 기준으로 한다. [PDF](https://arxiv.org/pdf/2609.09153v1) · [HTML](https://arxiv.org/html/2609.09153v1).

**Abstract:** 긴 과제를 수행하는 에이전트는 실행 기록을 기억하는 것만으로 충분하지 않다. 어떤 행동이 다음에 가능한지, 무엇을 먼저 확인해야 하는지, 언제 멈춰야 하는지를 현재 진행 상황에 연결해야 한다. Procedural Graph(PG)는 이런 절차 지식을 노드·관계·텍스트 속성으로 외부화한다. 실행 중에는 마지막 행동에 해당하는 노드를 찾아 주변 그래프를 읽고, guidance LLM이 다음 행동을 위한 상황별 조언을 생성한다. 그래프는 각 과제 안에서는 고정되지만, 별도의 진화 과정에서 성공·실패 궤적을 비교해 수정된다. 후보는 구조 검사를 거쳐 검증 점수가 유지되거나 오를 때 채택되며, 기각된 수정도 기록한다. 본평가에서 PG는 24개 모델·벤치마크 조합 중 21개에서 단독 또는 공동 최고였지만, 모든 조합을 이기지는 않았다. 별도 구성 실험에서는 부적절한 전문가 그래프를 수정할 수 있었고, 주변 그래프만 활용한 guidance가 전체 그래프를 활용한 조건보다 적은 토큰으로 높은 성능을 보였다. 다만 guidance 호출은 추가 비용을 만들고, 검증 점수의 비감소가 일반화 성능의 단조 향상을 보장하지는 않는다. [논문 §§3–5](https://arxiv.org/pdf/2609.09153v1#page=7)

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 절차 지식을 편집 가능한 그래프로 표현하고, 현재 실행 상태에 맞춰 안내하며, 경험으로 구조를 개선할 수 있는가? |
| 표현 | `(procedure, relation, procedure)`와 `condition`, `guidance`, `pitfalls` 속성. |
| 실행 | 마지막 procedure의 노드를 정확히 매칭하고, 기본 2-hop 이웃과 최근 3-step 기록으로 상황별 안내를 생성한다. |
| 진화 | 학습 과제 실행 → 그래프 수정 → 구조 검사 → 별도 검증 집합 평가 → 채택 또는 기각 기록. |
| 주요 결과 | 4개 LLM × 6개 benchmark에서 최고 baseline 대비 19승·2동률·3패. |
| 구성 실험 | HotpotQA에서 scratch 진화의 test F1 78.79, baseline 71.21. MultiChallenge에서는 expert 진화가 92.86으로 최고다. |
| 장기 실험 | 별도 EnterpriseArena 진화 실험의 반환 그래프는 test 생존율 85%. 중간 최고 95%는 최종 결과로 선택하지 않는다. |
| 핵심 한계 | Soft guidance이며 실행 강제 장치가 아니다. 본평가와 진화 실험의 설정이 다르고, 추가 토큰·반복 validation·시뮬레이터 의존성을 고려해야 한다. |

수치와 평가 범위는 [논문 Tables 1–3 및 11](https://arxiv.org/pdf/2609.09153v1#page=32)에 따른다.

## 목차

1. 사실을 저장하는 그래프에서 행동을 안내하는 그래프로
2. 절차 그래프는 무엇을 표현하는가
3. 현재 위치를 찾고 상황별 guidance를 만든다
4. 그래프를 진화시키는 검증 기반 수정 루프
5. 평가 범위와 기존 방법의 비교축
6. 본평가와 그래프 구성 실험의 결과
7. 적은 step과 낮은 비용은 같은가
8. EnterpriseArena: 장기 실행과 그래프 진화
9. 한계, 적용 조건과 결론

---

## 1. 사실을 저장하는 그래프에서 행동을 안내하는 그래프로

에이전트가 검색으로 필요한 자료를 찾았다고 해서 다음 행동이 자명해지는 것은 아니다. 자료를 읽고, 필요한 값을 추출하고, 계산하고, 답이 요구 조건을 만족하는지 확인한 뒤 제출해야 할 수 있다. 이전 기록이 길어지면 아직 하지 않은 단계와 이미 반복한 단계를 구분하기도 어려워진다.

논문은 이 문제를 factual knowledge와 procedural knowledge의 차이로 설명한다. Knowledge graph의 `(entity, relation, entity)`가 무엇이 어디에 있고 어떤 관계인지 표현한다면, PG의 `(procedure, relation, procedure)`는 어떤 절차 다음에 무엇을 할 수 있는지를 표현한다. [논문 §1](https://arxiv.org/pdf/2609.09153v1#page=2)

[![Knowledge Graph의 개체 관계와 Procedural Graph의 검색·읽기·계산·검증·출력 절차 관계를 비교한 그림](figures/pg-fig1-knowledge-to-procedure.png)](figures/pg-fig1-knowledge-to-procedure.png)

*원논문 Figure 1. 왼쪽은 사실 질의에 필요한 관계를, 오른쪽은 다음 행동을 판단하는 데 필요한 절차 연결을 보여준다. 그림의 관계 이름은 개념 설명용이며, 실제 실험의 relation vocabulary는 §2에서 따로 정리한다. Lu et al. (2026), [PDF p. 2](https://arxiv.org/pdf/2609.09153v1#page=2). 원본 도판 영역 직접 추출.*

그림을 누르면 원본 해상도로 볼 수 있다. 아래 도판도 같은 방식으로 확대할 수 있다.

이 접근의 가치가 드러나는 지점은 독립적인 조언들의 연결이다. “제출하라”는 규칙과 “답을 검증하라”는 규칙을 따로 검색하는 것보다, 검증을 거쳐 제출로 이어지는 관계를 함께 읽는 편이 절차를 이해하기 쉽다. PG는 이러한 연결을 구조로 보존하고, 구체적인 현재 상황으로 번역하는 단계까지 추가한다.

다만 이 그래프는 solver를 완전히 대신하는 프로그램이 아니다. 최종 행동은 여전히 LLM이 생성한다. 그래서 표현의 구조성, 안내의 유연성, 실제 실행의 강제력을 구분하는 것이 이 논문을 읽는 출발점이다.

## 2. 절차 그래프는 무엇을 표현하는가

### 2.1 노드와 관계, 그리고 간선의 텍스트 속성

논문은 PG를 다음과 같이 정의한다.

$$
\mathcal G=(V,R,E,\Phi),\qquad E\subseteq V\times R\times V.
$$

노드는 도구 함수, 스킬, 내부 추론 단계 또는 task status를 추상화한다. 간선 $(u,r,v)$는 관계 $r$ 아래에서 $u$ 다음의 $v$라는 전이를 표현한다. $\Phi$는 그 간선의 속성이다. v1은 세 텍스트 필드를 사용한다. [논문 §3.1, Eq. 1](https://arxiv.org/pdf/2609.09153v1#page=3)

| 속성 | 답하는 질문 | 해석 |
| --- | --- | --- |
| `condition` | 언제 이 전이가 적절한가? | 현재 상태와 전이의 적용 조건 |
| `guidance` | 어떻게 진행할 것인가? | 다음 단계 수행을 위한 설명 |
| `pitfalls` | 어떤 실수를 피해야 하는가? | 반복 오류, 누락, 잘못된 호출에 대한 주의 |

실험의 관계 어휘는 `LEADS_TO`, `TRIGGERS`, `PROVIDES_INPUT_FOR`, `CONVERGES_TO`다. 따라서 그래프는 단순한 도구 목록보다 풍부하지만, 속성 자체가 기계적으로 실행되는 논리식이라고 보아서는 안 된다. 조건과 주의사항을 읽고 현재 상황에 맞게 해석하는 주체는 guidance LLM이다. [논문 Appendix B.4](https://arxiv.org/pdf/2609.09153v1#page=21)

### 2.2 연결 구조가 있다고 모든 제약이 강제되는 것은 아니다

예를 들어 “결과 확인 → 제출”이라는 전이에 제출 형식과 누락 방지 조언을 붙일 수 있다. 그러나 solver가 실제로 그 순서를 반드시 지키도록 action space를 차단하는 방식은 아니다. PG의 전이는 **권장되는 절차 구조**이며, 실행 시에는 그 구조에서 생성한 guidance를 prompt에 추가한다.

이 구분은 ‘실행 구조’라는 제목을 해석할 때 중요하다. 그래프가 유효하더라도 solver가 안내를 무시하거나 잘못 이해할 수 있다. 권한 검사, 입력 schema 검증, 실행 상한 같은 강제 조건은 별도 실행 환경이 다뤄야 한다. 논문이 검증한 것은 soft guidance를 추가한 시스템의 성능이지, 구조 밖 행동이 불가능하다는 보장이 아니다.

### 2.3 주 실험의 그래프는 대체로 작다

| Benchmark | 노드 수 | Triplet 수 |
| --- | ---: | ---: |
| HotpotQA | 9 | 9 |
| MultiChallenge | 7 | 7 |
| GDPval | 15 | 22 |
| ALFWorld | 11 | 27 |
| τ-bench | 17 | 18 |
| BFCL v3 | 131 | 265 |
| EnterpriseArena | 11 | 13 |

[논문 Table 7](https://arxiv.org/pdf/2609.09153v1#page=21)

BFCL을 제외하면 수십 개 이하의 전이로 구성된다. 이는 작은 절차 표현만으로도 실험상 이득을 낼 수 있다는 장점이다. 동시에 수천 개의 procedure와 여러 도메인이 섞인 거대한 그래프에서 local retrieval이 어떻게 작동할지는 아직 별도의 문제다. 또한 이 표는 본평가의 그래프 크기이며 모든 진화 round의 크기를 나타내지 않는다.

## 3. 현재 위치를 찾고 상황별 guidance를 만든다

[![절차 그래프, 온라인 generative guidance와 오프라인 refiner·validation·rejection memory를 연결한 프레임워크](figures/pg-fig2-framework.png)](figures/pg-fig2-framework.png)

*원논문 Figure 2. 가운데는 그래프를 고정한 실행 과정이고, 오른쪽은 실행 기록으로 그래프를 바꾸는 진화 과정이다. 그림의 validation 마름모는 개선을 묻지만, 실제 채택식은 동점도 허용하는 `≥`다. Lu et al. (2026), [PDF p. 4](https://arxiv.org/pdf/2609.09153v1#page=4). 원본 도판 영역 직접 추출.*

### 3.1 Localize: 최근 행동을 노드에 정확히 매칭한다

질문을 $q$, 현재 step까지의 행동·관측 기록을 $\mathcal T_t$라 하자. 첫 step은 `Start`에서 시작한다. 이후 가장 최근 procedure, 예를 들어 마지막 tool call의 이름을 그래프 노드에 정확히 매칭해 현재 위치 $u_t$를 찾는다.

$$
u_t=\operatorname{Match}(a_{t-1},V).
$$

이 `Match`는 이름을 정확히 일치시키는 exact matching이다. 의미 embedding이나 별도 LLM으로 현재 위치를 추론하는 방식과 구분된다. [논문 §3.2](https://arxiv.org/pdf/2609.09153v1#page=4)

### 3.2 Extract: 진행 방향의 2-hop 이웃을 읽는다

매칭에 성공하면 현재 노드에서 출발해 최대 $h$번의 전이를 따라가는 directed neighborhood를 가져온다. 매칭에 실패하면 전체 그래프를 사용한다.

$$
\mathcal G_t=
\begin{cases}
\mathcal N_h(u_t),&u_t\ne\varnothing,\\
\mathcal G,&\text{otherwise}.
\end{cases}
$$

기본값은 $h=2$다. 즉, 단편적인 전이 문장들을 독립적으로 고르는 대신 진행 방향으로 연결된 경로를 함께 제시한다. 다만 명시된 연산은 **현재 노드에서 나가는 전이의 확장**이다. 모든 선행 조건을 역방향으로 추적하거나 만족 여부를 증명하는 알고리즘은 아니다.

이 구조는 노드 이름과 실제 action 이름의 일치에 의존한다. 매칭 실패 시에는 오류를 내는 대신 full graph로 돌아가지만, 그 경우 local context의 장점이 줄어들 수 있다. 성공적인 매칭의 빈도와 실패 유형도 재현 연구에서 유용한 지표가 된다.

### 3.3 Generate: 그래프를 그대로 붙이지 않고 상황에 맞는 조언으로 바꾼다

Guidance LLM $\Psi$는 현재 그래프 문맥, 질문, 최근 기록을 받아 다음 행동을 위한 상황별 안내 $g_t$를 생성한다.

$$
g_t=\Psi\bigl(\mathcal G_t,q,\mathcal T_{t-w:t}\bigr),
\qquad
a_t\sim P_{\mathrm{solver}}(\cdot\mid q,\mathcal T_t,g_t).
$$

Guidance에 쓰는 최근 trajectory window는 기본 $w=3$이다. 그러나 solver 자체가 전체 기록을 세 step으로 잘라서 사용한다는 뜻은 아니다. 수식상 guidance는 짧은 window를 참고하고, solver는 자신의 trajectory와 생성된 guidance를 함께 받는다. [논문 Eqs. 2–3](https://arxiv.org/pdf/2609.09153v1#page=5)

예를 들어 “이제 결과를 확인하고, 이전 검색을 반복하지 말라”는 조언을 현재 단계에 맞게 만든다. 정적인 graph attribute를 단순히 복사한 것과 다른 부분이다. 동시에 매 decision step마다 별도의 guidance 호출이 생기므로, 더 짧은 solver trajectory가 곧 더 낮은 총비용을 뜻하지는 않는다.

### 3.4 Online과 offline은 그래프 수정 여부를 기준으로 나뉜다

한 과제를 수행하는 동안 그래프는 고정된다. 바뀌는 것은 현재 위치, retrieved subgraph와 guidance다. 그래프 자체의 수정은 training batch를 실행한 뒤 별도 refiner가 수행한다.

이후 등장하는 `Online Evolution`이라는 구성 모드 이름도 이 점을 염두에 두어야 한다. 학습 과제를 batch별로 처리하며 점진적으로 수정한다는 뜻이며, **하나의 평가 episode 안에서 solver가 그래프를 계속 고치는 방식은 아니다.** [논문 §§3, 3.3, Appendix D.2](https://arxiv.org/pdf/2609.09153v1#page=30)

#### 같은 그래프를 읽는 시간과 그래프를 고치는 시간을 나누기

한 episode에서는 첫 step이 `Start`에서 출발하고, 다음 step부터는 방금 수행한 procedure 이름을 노드에 exact match한다. 일치하면 그 노드에서 나가는 2-hop 전이와 최근 세 step을 guidance LLM에 주고, 그 LLM이 이번 **다음 행동**을 위한 문장을 만든다. 일치하지 않으면 full graph가 그 호출의 문맥이 된다. 어느 경우에도 이 호출이 간선을 추가·삭제하지는 않는다. 즉 guidance가 매 step 달라져도 graph topology는 해당 episode 전체에서 같은 상태다.

수정은 별도의 batch 경계에서만 시작한다. 유지된 graph로 training batch를 끝낸 뒤 refiner가 candidate edit을 제안하고, 구조 검사와 held-out validation을 통과한 candidate만 다음 batch의 retained graph가 된다. 그래서 “현재 상황에 맞춘 guidance”와 “경험으로 고쳐진 절차”는 둘 다 PG의 일부이지만 시간 척도와 검증 단위가 다르다. 전자는 한 행동을 안내하는 생성 단계이고, 후자는 다음 여러 episode가 공유할 구조를 선택하는 offline loop다. [논문 §3.2–3.3, Algorithm 1, Appendix D.2](https://arxiv.org/pdf/2609.09153v1#page=30)

## 4. 그래프를 진화시키는 검증 기반 수정 루프

### 4.1 좋은 실행과 나쁜 실행을 대조한다

현재 유지 중인 그래프로 training batch를 실행하고 각 궤적과 점수를 모은다. Refiner는 높은 점수와 낮은 점수의 기록을 대조해, 반복되는 오류와 유효했던 실행 순서를 찾는다. 점수가 이진이면 성공·실패 비교가 되고, rubric처럼 연속적이면 상대적으로 높은·낮은 성과를 비교한다.

수정은 노드·간선의 추가와 삭제로 표현한다. Attribute를 바꾸려면 기존 간선을 지우고 바뀐 속성으로 다시 넣는다. 원문의 JSON 인터페이스에서 source와 target만 지정한 삭제는 같은 두 endpoint의 모든 relation을 제거하므로, 남길 관계가 있으면 다시 추가해야 한다. [논문 §3.3, Appendix B.5](https://arxiv.org/pdf/2609.09153v1#page=23)

이때 참조하는 것은 매 round의 **유지된 checkpoint**다. 기각된 후보를 다음 round의 출발점으로 사용하지 않는다. 실패한 수정을 기록하는 것과 그 수정을 실제 그래프에 유지하는 것은 분리된다.

### 4.2 구조 검사는 무엇을 보장하는가

후보는 기존 그래프의 복사본에 삭제 후 추가 순서로 edits를 적용한다. 잘못된 edit 형식, 유효하지 않은 타입, 없는 endpoint 등을 검사한다. Cycle을 금지하는 설정에서는 cycle-closing edge를 제거하고, cycle을 허용하는 설정에서는 해당 검사를 생략한다.

나머지 노드는 out-degree가 0인 terminal에 도달하는 directed path를 가져야 한다. 여기서 terminal은 반드시 이름이 `End`인 노드일 필요가 없다. 또한 action-node 이름이 실제 도구 목록에 있는지는 generic validator가 독립적으로 강제하지 않고, refiner prompt가 요구하는 조건이다. [논문 Appendix B.6](https://arxiv.org/pdf/2609.09153v1#page=24)

따라서 이 검사는 graph well-formedness에 대한 검사다. 실제 tool schema, 올바른 인자, 업무 정책, solver의 종료까지 전부 보증하는 검증기로 읽을 수는 없다. 그래프에 terminal로 가는 경로가 있어도 soft guidance를 따르는 solver가 실제로 그 경로를 선택한다는 보장은 없다.

### 4.3 Validation gate는 동점도 채택한다

구조적으로 유효한 후보만 held-out validation set에서 평가한다. 초기 그래프의 점수는 먼저 계산해 저장하고, 이후 후보는 유지된 checkpoint의 저장된 점수와 비교한다.

$$
S_{\mathrm{val}}(\mathcal G)
=\frac1{|D_{\mathrm{val}}|}\sum_{(q,y)\in D_{\mathrm{val}}}
S\bigl(f_{\mathrm{solver}}(q\mid\mathcal G),y\bigr).
$$

$$
\mathcal G_k=
\begin{cases}
\mathcal G_k^{\mathrm{cand}},&S_{\mathrm{val}}(\mathcal G_k^{\mathrm{cand}})\ge S_{k-1},\\
\mathcal G_{k-1},&\text{otherwise}.
\end{cases}
$$

$S_{k-1}$은 현재 checkpoint의 cached validation score다. 이 규칙은 strict improvement가 아니라 **측정된 검증 점수가 낮아지지 않으면 채택하는 규칙**이다. 동점인 후보도 구조가 달라질 수 있다. [논문 Eqs. 4–5, Algorithm 1](https://arxiv.org/pdf/2609.09153v1#page=24)

이 규칙이 보장하는 것은 저장된 검증 점수의 비감소다. 실제 일반화 성능의 단조 향상, 새로 실행해도 같은 점수를 얻는다는 보장, 검증 집합에 대한 적응적 과적합의 부재는 아니다. 또한 후보를 평가할 때마다 기존 그래프도 다시 실행해 짝지어 비교하는 방식은 아니다.

### 4.4 Rejection memory에는 무엇이 남는가

후보가 validation에서 낮은 점수를 얻으면 후보 그래프, 수정 내용, training 궤적과 평가 결과를 기록한다. 구조 검사에서 실패한 경우도 diagnostics와 함께 저장한다. 다음 refiner는 이 정보를 보고 비슷한 무익한 수정을 반복하지 않도록 유도받는다.

본문의 $L_{\max}$는 training trajectory들을 이어 붙인 context에 적용한다. 넘치는 앞부분을 버리고 마지막 토큰들을 보존한다. 이는 rejection memory 전체의 크기를 제한한다는 규칙이 아니다. Rejection history의 장기 압축·삭제 정책은 별도로 명시되지 않는다. [논문 §3.3, Appendix B.6](https://arxiv.org/pdf/2609.09153v1#page=24)

### 4.5 유지된 상태를 중심으로 본 알고리즘

```text
입력: 초기 그래프, train/validation 분할, 최대 진화 round

retained_graph ← 초기 그래프
retained_score ← validation에서 초기 그래프 평가
rejections ← 빈 기록

각 round에서:
    traces ← retained_graph로 training batch 실행
    candidate ← refiner가 traces와 rejections를 보고 제안한 수정 적용
    구조 검사에 실패하면:
        diagnostics를 rejections에 기록하고 다음 round로 이동
    candidate_score ← validation에서 candidate 평가
    candidate_score ≥ retained_score이면:
        retained_graph와 retained_score를 함께 교체
    아니면:
        후보와 평가 결과를 rejections에 기록

반환: 마지막 retained_graph
```

원문 Algorithm 1의 상태 관리만 드러내도록 재구성한 의사코드다. 반환하는 것은 마지막으로 승인된 그래프이며, 관측한 test 성능이 가장 높았던 중간 후보를 고르는 규칙이 아니다.

## 5. 평가 범위와 기존 방법의 비교축

### 5.1 일곱 benchmark지만 본평가 표는 여섯 개다

| Benchmark | 주요 목적 | 보고된 test 규모와 평가 |
| --- | --- | --- |
| HotpotQA | 도구를 활용한 multi-hop QA | 본평가 1,000개, LLM-judged answer accuracy |
| MultiChallenge | 대화 중 제약과 지시 유지 | 본평가 166개, 구성 실험은 별도 56개 |
| GDPval | 전문 업무 산출물 | 44개, task별 rubric score |
| ALFWorld | 가정 내 embodied task의 행동 순서 | 134개, task success |
| τ-bench | 사용자와 상호작용하며 정책에 맞게 도구 사용 | Retail 115개, 최종 DB 상태 기준 Pass@1 |
| BFCL v3 | Multi-turn function calling | Base-category 100개, 공식 accuracy |
| EnterpriseArena | 장기 유동성 관리 | 기본 비교는 test 50 episodes, 진화 실험은 별도 20 episodes |

[논문 Tables 5·8·11, Appendix B.1–B.2](https://arxiv.org/pdf/2609.09153v1#page=20)

Table 1의 24개 조합은 EnterpriseArena를 제외한 6개 benchmark × 4개 LLM이다. 모델은 Claude Sonnet 4.6, Gemini 3.1 Pro, Gemini 3.5 Flash, Grok 4.1 Fast다. 각 조건에서 solver·guidance·refiner는 같은 underlying LLM을 사용하며 temperature 0으로 실행한다고 보고한다. 다만 greedy decoding과 시뮬레이터 결과의 무변동은 같은 뜻이 아니다. [논문 §4](https://arxiv.org/pdf/2609.09153v1#page=6)

### 5.2 본평가, 구성 실험, guidance ablation을 섞지 않는다

HotpotQA 본평가는 Gemini 3.1 Pro judge가 정답의 의미적 동등성을 판정한 accuracy다. 반면 그래프 구성 실험은 strict string EM과 word-level F1을 사용한다. 이 둘의 숫자를 같은 지표의 전후 변화로 비교할 수 없다.

MultiChallenge도 본평가 166개와 구성 실험의 56개 fast split이 다르다. 구성 실험은 Gemini 3.5 Flash로 train/validation/test를 별도로 두며, HotpotQA는 각각 1,000개, MultiChallenge는 100/100/56개다. Table 3의 guidance ablation도 fixed subset의 별도 결과다. [논문 Appendix B.1–B.2, D.3](https://arxiv.org/pdf/2609.09153v1#page=31)

또한 v1은 Table 1의 각 PG 행이 뒤의 다섯 구성 모드 중 어느 방식과 checkpoint에서 만들어졌는지 명시적으로 연결하지 않는다. 따라서 본평가의 모든 향상을 ‘self-evolution의 효과’나 ‘수작업 그래프의 효과’로 귀속해서는 안 된다. 온라인 실행 중 그래프가 고정된다는 사실만 확인된다.

### 5.3 무엇과 비교했는가

| 방법 | 재사용하는 지식 | PG와의 비교축 |
| --- | --- | --- |
| Vanilla ReAct | 별도 memory 없음 | Trajectory 기반 action selection에 외부 구조를 더했는가? |
| MemoryBank | 요약된 경험과 forgetting | 연결 구조 없는 경험 저장과의 차이 |
| RAP | 이전 trajectory 예시 | 원시 사례 재사용과 절차 구조의 차이 |
| ExpeL | 성공·실패에서 추출한 insight | 자연어 지침과 연결된 전이의 차이 |
| AutoGuide | 상태별 행동 guideline | 독립적인 조건부 지침 검색과 neighborhood 읽기의 차이 |
| AWM | 재사용 가능한 workflow | Workflow 묶음과 편집 가능한 graph topology의 차이 |
| KnowAgent | 텍스트 action knowledge와 전이 규칙 | Static rule prefix와 step별 generative guidance의 차이 |

논문은 같은 ReAct solver와 tool interface를 사용하고, 학습 기반 비교 방법에 같은 training split·경험을 제공한다고 설명한다. 각 baseline의 memory 형태와 적용 방식은 Appendix B.3에 정리되어 있다. 이는 비교를 이해할 중요한 통제지만, 원래 각 방법의 모든 설정을 같은 총비용으로 최적 튜닝했다는 의미는 아니다. [논문 Table 6](https://arxiv.org/pdf/2609.09153v1#page=21)

가까운 선행연구를 직접 보면 PG의 위치가 더 명확해진다. AutoGuide는 현재 context에 맞는 조건부 guideline을 생성·선택하고, AWM은 재사용 가능한 workflow를 유도해 활용한다. 특히 AWM 원 연구는 offline뿐 아니라 online 경험에서 workflow를 얻는 경우도 다룬다. KnowAgent 역시 행동 지식과 planning path를 연결한다. 따라서 기존 연구에 절차나 갱신 개념이 전혀 없다는 대비보다, **전이에 붙은 속성·주변 그래프 검색·생성형 안내·검증 기반 연결 구조 수정을 결합했다**는 설명이 적절하다. [AutoGuide](https://arxiv.org/abs/2403.08978), [AWM](https://proceedings.mlr.press/v267/wang25bx.html), [KnowAgent](https://aclanthology.org/2025.findings-naacl.205/)

## 6. 본평가와 그래프 구성 실험의 결과

### 6.1 24개 조합 중 21개에서 단독 또는 공동 최고

아래는 Table 1의 PG 점 추정값을 발췌한 것이다. 원문에는 각 값의 95% confidence interval도 제시된다. 열마다 accuracy·rubric score·success·Pass@1의 의미가 다르므로 한 가지 정확도처럼 합산하지 않는다.

| PG의 solver | HotpotQA | MultiChallenge | GDPval | ALFWorld | τ-bench | BFCL v3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Claude Sonnet 4.6 | 74.50 | 89.76 | 51.49 | 93.28 | 73.91 | 67.00 |
| Gemini 3.1 Pro | 87.30 | 95.78 | 78.78 | 100.00 | 80.00 | 66.00 |
| Gemini 3.5 Flash | 84.50 | 91.57 | 64.42 | 94.03 | 44.35 | 67.00 |
| Grok 4.1 Fast | 74.40 | 86.75 | 71.19 | 39.55 | 67.83 | 60.00 |

[논문 Table 1](https://arxiv.org/pdf/2609.09153v1#page=7)

해당 조합의 가장 높은 baseline과 비교하면 19승·2동률·3패다. 동률은 confidence interval이 겹친다는 뜻이 아니라 보고된 점 추정값이 같다는 뜻이다. Claude와 Gemini Flash의 MultiChallenge가 동률에 해당한다.

| 대표 비교 | PG | 최고 baseline | 차이 |
| --- | ---: | ---: | ---: |
| Gemini 3.5 Flash, BFCL v3 | 67.00 | 58.00 | +9.00 |
| Gemini 3.1 Pro, GDPval | 78.78 | 71.37 | +7.41 |
| Gemini 3.1 Pro, τ-bench | 80.00 | 73.04 | +6.96 |
| Claude Sonnet 4.6, HotpotQA | 74.50 | 75.40 | −0.90 |
| Grok 4.1 Fast, ALFWorld | 39.55 | 42.54 | −2.99 |
| Grok 4.1 Fast, τ-bench | 67.83 | 68.70 | −0.87 |

차이는 원문 Table 1에서 계산했다. Accuracy·성공률은 퍼센트포인트(%p), GDPval은 rubric 점수 차이다.

저자는 동률을 제외한 단측 exact binomial sign test로 $p=4.3\times10^{-4}$를 보고한다. 이는 여러 모델·benchmark 조합에서 우세한 방향이 반복됐다는 집계다. 19개 각각의 차이가 통계적으로 유의하다는 뜻은 아니며, 같은 benchmark와 LLM을 공유하는 조합들의 의존성도 염두에 두어야 한다. 원문은 CI를 95% 구간으로 제시하지만 구체적인 산출법은 충분히 설명하지 않는다. [논문 §5.1](https://arxiv.org/pdf/2609.09153v1#page=7)

### 6.2 전문가 prior와 scratch를 어떻게 비교하는가

다섯 mode는 초기 그래프와 수정 횟수, validation 사용 여부를 함께 바꾼다.

| Mode | 초기화 | 수정 방식 | Validation gate |
| --- | --- | --- | --- |
| 1 | 전문가 그래프 | 수정 없음 | 없음 |
| 2 | 전문가 그래프 | Training 기록을 모아 한 번 수정 | 없음, 직접 채택 |
| 3 | 전문가 그래프 | Batch별 점진적 진화 | 있음 |
| 4 | `Start → End` | 한 번에 scratch build | 없음, 직접 채택 |
| 5 | `Start → End` | Batch별 점진적 진화 | 있음 |

[논문 Appendix D.2](https://arxiv.org/pdf/2609.09153v1#page=30)

따라서 Mode 2와 3의 차이를 validation gate 하나의 순수한 ablation이라고 읽을 수는 없다. Batch 처리, 반복 수정, 새로운 실행 feedback과 rejection memory도 함께 달라진다. Scratch도 모델 자체가 지식 없이 시작한다는 뜻이 아니라 외부 그래프가 최소 구조에서 출발한다는 뜻이다.

| 구성 | HotpotQA EM | HotpotQA F1 | MultiChallenge Overall |
| --- | ---: | ---: | ---: |
| Unguided baseline | 58.80 | 71.21 | 87.50 |
| Mode 1 | 62.80 | 76.61 | 58.93 |
| Mode 2 | 63.80 | 77.16 | 53.57 |
| Mode 3 | 63.10 | 76.34 | 92.86 |
| Mode 4 | 55.40 | 69.49 | 89.29 |
| Mode 5 | 66.30 | 78.79 | 91.07 |

[논문 Table 2](https://arxiv.org/pdf/2609.09153v1#page=9)

HotpotQA에서는 scratch에서 반복 진화한 Mode 5가 가장 높다. 반면 MultiChallenge에서는 전문가 그래프에서 진화한 Mode 3이 가장 높다. “Scratch가 항상 전문가보다 좋다”는 결론은 나오지 않는다.

MultiChallenge의 초기 전문가 그래프는 baseline 87.50보다 낮은 58.93이고, 한 번의 수정은 53.57로 더 낮아진다. 점진적 진화는 이를 92.86으로 회복한다. 중요한 것은 사람이 만든 구조가 항상 유익하지 않다는 점과, 반복 피드백을 통한 수정이 그 부적합성을 줄일 수 있었다는 점이다. 다만 이 전문가 prior가 얼마나 넓은 설계 후보 중 선택되었는지까지 비교한 결과는 아니다.

[![HotpotQA와 MultiChallenge에서 expert prior와 scratch 초기화의 validation 성능 진화 곡선](figures/pg-fig6-cross-task-evolution.png)](figures/pg-fig6-cross-task-evolution.png)

*원논문 Figure 6. 왼쪽은 validation F1, 오른쪽은 validation accuracy다. 채택·기각 후보와 그래프의 개선 경향을 보여주며, Table 2의 최종 test 점수와는 다른 값이다. Lu et al. (2026), [PDF p. 35](https://arxiv.org/pdf/2609.09153v1#page=35). 원본 도판 영역 직접 추출.*

이 그림의 HotpotQA validation 최고 F1 83.31과 Table 2의 test F1 78.79는 평가 분할이 다르다. MultiChallenge의 validation 54.0→93.9와 test 58.93→92.86도 각각 다른 분할의 관측이다. [논문 Appendix E.4](https://arxiv.org/pdf/2609.09153v1#page=35)

## 7. 적은 step과 낮은 비용은 같은가

### 7.1 Full graph와 localized guidance의 비교

Table 3은 Gemini 3.5 Flash와 같은 그래프를 사용해 raw injection, full-graph generative guidance, subgraph generative guidance를 비교한다. 아래 점수는 각 데이터셋의 accuracy·rubric·success이며, 토큰과 step은 sample당 평균이다.

| Benchmark·구성 | 점수 | 평균 토큰 | 평균 solver step |
| --- | ---: | ---: | ---: |
| MultiChallenge, no graph | 80.27 | 6629 | 3.87 |
| MultiChallenge, full raw | 86.60 | 10164 | 4.54 |
| MultiChallenge, full generative | 87.35 | 14434 | 3.08 |
| MultiChallenge, subgraph generative | 89.31 | 12295 | 4.22 |
| GDPval, no graph | 54.80 | 275638 | 28.20 |
| GDPval, full raw | 57.17 | 264680 | 33.55 |
| GDPval, full generative | 56.75 | 448972 | 22.07 |
| GDPval, subgraph generative | 63.99 | 367738 | 18.57 |
| ALFWorld, no graph | 72.58 | 18055 | 21.84 |
| ALFWorld, full raw | 70.34 | 21062 | 25.00 |
| ALFWorld, full generative | 54.48 | 96360 | 30.05 |
| ALFWorld, subgraph generative | 81.53 | 28064 | 18.80 |

[논문 Table 3](https://arxiv.org/pdf/2609.09153v1#page=10)

주변 그래프에서 생성한 guidance는 이 세 조건에서 가장 높은 점수를 보인다. 특히 ALFWorld에서 전체 그래프를 주는 것은 raw와 generative 모두 baseline보다 낮다. 그래프를 제공한다는 사실 자체보다 **현재 단계와 관련된 범위를 골라 해석하는 것**이 중요하다는 결과다.

그러나 이 ablation에는 ‘localized subgraph를 raw로 주입’하는 셀이 없다. 따라서 localization과 generative transformation 사이의 모든 상호작용을 완전히 분해한 2×2 실험은 아니다. 확인할 수 있는 비교는 full graph에서 raw 대 generative, 그리고 generative 조건에서 full 대 local이다.

### 7.2 주변 그래프만 읽어도 baseline보다 토큰은 늘어난다

ALFWorld에서 full generative 대비 local guidance의 토큰은 약 70.9% 줄어든다. 하지만 baseline과 비교하면 18,055에서 28,064로 **약 55.4% 증가**한다. GDPval도 solver step은 28.20에서 18.57로 줄지만 토큰은 약 33.4% 늘어난다. [논문 §5.5](https://arxiv.org/pdf/2609.09153v1#page=10)

MultiChallenge에서는 local guidance의 점수가 가장 높지만 solver step은 4.22로 baseline 3.87보다 많고, full generative 3.08보다도 많다. 따라서 “PG는 항상 덜 생각하고 더 싸게 푼다”는 결론은 맞지 않는다. 이 설계는 추가적인 guidance 계산을 들여 더 나은 행동 선택을 얻는 경우도 포함한다.

### 7.3 진화 모드의 자원 사용도 과제에 따라 달라진다

별도 구성 실험에서 HotpotQA Mode 5는 3.97 step으로 baseline 4.88보다 짧지만, 토큰은 4,003.24에서 10,115.89로 늘고 latency도 18.06초에서 31.53초로 늘어난다. 반면 MultiChallenge Mode 5는 성공률을 높이면서 step과 latency를 줄이지만, 토큰은 baseline보다 약간 많다. [논문 Tables 9–10](https://arxiv.org/pdf/2609.09153v1#page=29)

여기서 parsing failure도 sample당 횟수다. 예를 들어 MultiChallenge baseline의 1.05는 105%의 실패 확률이 아니다. Mode 5의 0.57은 호출·파싱 실패 빈도의 감소를 보여주지만, task 성공률과 같은 지표가 아니다. 자원과 오류의 단위를 정확히 구분해야 성능 개선의 의미를 해석할 수 있다.

## 8. EnterpriseArena: 장기 실행과 그래프 진화

### 8.1 생존율, 평균 lifespan, 기업 score는 다르다

EnterpriseArena는 최대 132개월 동안 금융기관의 유동성을 관리하는 시뮬레이터다. 자금 조달 요청과 실제 입금 사이에 1–6개월 지연이 있고, cash가 음수가 되면 파산으로 종료한다. 위기는 32·59·112개월에 발생하지만 에이전트에게 사전 공개하지 않는다고 설명한다. [논문 Appendix C.1](https://arxiv.org/pdf/2609.09153v1#page=25)

Full survival은 132개월을 끝까지 완료한 비율이고, 평균 lifespan은 조기 종료를 포함한 월수의 평균이다. 평균 enterprise score는 각 실행의 종료 시점까지 기록한 월별 score를 먼저 평균하므로, 파산한 실행도 양의 평균 score를 가질 수 있다. 따라서 score가 높다는 것과 생존했다는 것은 동일하지 않다.

Tools/Mo 역시 전체 계산량이 아니다. Arena의 정보 조회 도구 호출 수를 월수로 나눈 지표이며, 메모리 연산과 상태를 바꾸는 행동은 제외한다. Raised는 요청액이 아니라 실제로 받은 자금의 누적 평균이다. 이들은 시뮬레이터 안의 행동과 결과를 설명하는 지표다.

[![네 LLM의 EnterpriseArena 생존곡선과 현금 경로를 PG·baseline·memory 방법별로 비교한 그림](figures/pg-fig3-cash-survival.png)](figures/pg-fig3-cash-survival.png)

*원논문 Figure 3. 각 모델에서 위쪽은 생존곡선, 아래쪽은 cash 경로다. 세로선은 위기 시점이며, 파란색이 PG다. 특히 Gemini 3.5 Flash는 이 비교에서 모든 방법의 full-horizon 생존율이 0%다. 뒤의 별도 진화 실험과 혼동하지 않아야 한다. Lu et al. (2026), [PDF p. 8](https://arxiv.org/pdf/2609.09153v1#page=8). 원본 도판 영역 직접 추출.*

| Solver | Baseline 생존율 | PG 생존율 | Baseline 평균 월수 | PG 평균 월수 |
| --- | ---: | ---: | ---: | ---: |
| Claude Sonnet 4.6 | 44.0 | 58.0 | 89.80 | 98.58 |
| Gemini 3.1 Pro | 6.0 | 34.0 | 50.28 | 79.22 |
| Gemini 3.5 Flash | 0.0 | 0.0 | 33.58 | 40.62 |
| Grok 4.1 Fast | 26.0 | 40.0 | 63.76 | 75.14 |

[논문 Table 8](https://arxiv.org/pdf/2609.09153v1#page=26)

PG는 세 모델의 full survival과 네 모델 모두의 lifespan을 높인다. 그러나 Flash의 lifespan 개선을 파산 방지 성공으로 바꿔 말할 수는 없다. 또한 이 표의 비교는 구성당 50개 test episodes이고, 아래 진화 실험은 다른 20개 test episodes를 사용한다.

### 8.2 진화 과정에서 무엇이 채택되었는가

별도 진화 연구는 Gemini 3.5 Flash와 train/validation/test 각각 20 episodes를 사용한다. Table 11의 후보 validation 생존율과 채택 상태를 발췌하면 다음과 같다.

| Round | 후보 validation 생존율 | 채택 여부 | 보고된 test 생존율 |
| --- | ---: | --- | ---: |
| Baseline | 0.0 | 기준 | 0.0 |
| 1 | 45.0 | 채택 | 70.0 |
| 2 | 80.0 | 채택 | 80.0 |
| 3 | 65.0 | 기각 | — |
| 4 | 75.0 | 기각 | — |
| 5 | — | 구조 검사 실패 | — |
| 6 | 65.0 | 기각 | — |
| 7 | 80.0 | 채택 | 95.0 |
| 8 | 90.0 | 채택 | 85.0 |
| 9 | 90.0 | 채택 | 85.0 |
| 10 | 85.0 | 기각 | — |

[논문 Table 11](https://arxiv.org/pdf/2609.09153v1#page=32)

Round 5는 새 validation을 수행하지 않는다. 원문 표에는 직전 Round 4의 표시값을 이월한 행이 있지만, 이를 Round 5 후보의 새 성능으로 읽어서는 안 된다. 유지된 그래프는 그보다 앞서 채택된 checkpoint다. 또한 위 표는 생존율과 실제 채택 결과를 보여주는 발췌이며, 모든 기업 지표가 동시에 개선돼야 채택된다는 뜻은 아니다.

[![열 번의 PG 진화에서 평균 생존 개월과 실제 조달 자금이 train·validation·test에서 변하는 그래프](figures/pg-fig4-evolution-outcomes.png)](figures/pg-fig4-evolution-outcomes.png)

*원논문 Figure 4. 회색은 training, 붉은색은 validation, 초록색은 baseline과 채택된 checkpoint의 test 결과다. Validation 곡선에는 기각 후보의 측정값도 포함되므로, 유지된 checkpoint의 cached score가 비감소한다는 규칙과 같은 곡선이 아니다. Lu et al. (2026), [PDF p. 9](https://arxiv.org/pdf/2609.09153v1#page=9). 원본 도판 영역 직접 추출.*

반환되는 것은 Round 9 그래프이며 test 생존율은 85%다. Round 7의 95%를 고르면 test를 보고 최종 모델을 선택한 셈이 되므로, 저자들은 그 수치를 최종 결과로 쓰지 않는다. 이 보고 구분은 적절하다. 다만 split당 20 episodes라 생존 한두 건이 채택 여부에 영향을 줄 수 있고, 저자도 각 round를 개별 유의성 검정처럼 읽지 말라고 설명한다. [논문 §5.4](https://arxiv.org/pdf/2609.09153v1#page=10)

### 8.3 Topology 변화와 simulator adapter의 의미

[![최소 Start-End 구조에서 cash 확인, forecast, note 저장·회수, 자금 판단 분기와 종료 경로가 추가·삭제되는 CFO 그래프](figures/pg-fig5-topology-evolution.png)](figures/pg-fig5-topology-evolution.png)

*원논문 Figure 5. 초록은 추가, 붉은 점선은 삭제·수정된 구조다. 원그림 패널의 round 표기 일부는 바로 아래 본문 및 Table 11의 설명과 다르다. 이 글의 단계 해석은 Appendix E.3 서술과 Table 11을 기준으로 하며, 도판 내부 표기는 원형 그대로 유지했다. Lu et al. (2026), [PDF p. 34](https://arxiv.org/pdf/2609.09153v1#page=34). 원본 도판 영역 직접 추출.*

초기 `Start → End`는 실행 구조에 거의 아무 정보도 주지 않는다. 첫 개선에서는 월 시작, cash 확인, runway forecast, note 저장, 시장 확인과 자금 조달 판단의 순서가 만들어진다. 이후 `recall_notes`가 추가되어 앞선 달의 기록을 재사용한다. Round 7에서는 `pass_action` 분기가 제거되고, Round 8에서는 자금 조달 요청 뒤의 종료 경로가 바뀐다.

원문이 마지막 변경을 administrative bypass라고 부르지만, 이 문맥에서 우회하는 대상은 월말 처리의 중복 실행이다. **환경 adapter가 자금 조달 요청 뒤에 이미 월을 진행하기 때문**이다. 바로 이어서 `book_closing()`을 호출하면 또 한 달 진행할 수 있으므로, 해당 procedure를 `End`로 마치고 새 월의 상태를 다시 평가하도록 바꾼 것이다. [논문 Appendix E.3](https://arxiv.org/pdf/2609.09153v1#page=34)

이 사례는 PG가 도구의 실제 상태 전이 방식에 맞춰 실행 순서를 고칠 수 있음을 보여준다. 동시에 simulator adapter에 특화된 수정이므로, 이를 실제 기업의 재무 절차에 일반화되는 정책으로 볼 수는 없다. 그래프 개선의 의미는 환경에서 action이 무엇을 실제로 바꾸는지와 함께 읽어야 한다.

## 9. 한계, 적용 조건과 결론

### 9.1 검증을 반복한다고 모든 개선이 검증되는 것은 아니다

Held-out validation은 training batch의 성능만 보고 수정을 채택하는 것보다 유용하다. 하지만 같은 validation을 반복 사용하면 그 집합 자체가 탐색 과정의 선택 신호가 된다. 특히 동점을 허용하는 gate는 해당 측정값을 유지하면서 구조를 바꿀 수 있다. 무엇을 보존했고 어떤 실패를 새로 만들었는지는 별도 test와 진단으로 확인해야 한다.

정교한 기능별 ablation도 더 필요하다. 구성 모드 비교는 초기화, batch 수, feedback 갱신, validation과 rejection memory를 함께 바꾸며, 사용 방식 ablation은 local raw 조건이 빠져 있다. 따라서 성공을 모든 구성요소 각각의 독립 효과로 분해한 실험은 아니다.

### 9.2 공개 구현과 재현 조건

v1은 그래프 schema, solver·guidance·refiner prompt, 의사코드와 데이터 분할을 상당히 자세히 제공한다. 그러나 이 검토에서는 저자가 제공한 공식 구현 저장소, 각 표에 사용한 saved graph, 정확한 실행 configuration과 원시 평가 artifact의 공개 위치를 확인하지 못했다. 이는 **공식 구현이 없다는 주장**이 아니라, 2026년 9월 15일 이 검토가 확인한 arXiv v1 자료에서 공개 위치를 검증하지 못했다는 뜻이다. 따라서 이 글의 재현성 검토는 **원문에 제시된 명세와 보고 결과를 확인한 범위**에 한정된다.

재현 시에는 Table 1의 PG construction mode 매핑, 정확한 모델 snapshot, judgment와 CI 산출법, guidance 비용 집계, matching 실패 빈도, graph cycle policy와 validation score 정의가 필요하다. 특히 생성 temperature 0이라는 설정만으로 외부 API와 시뮬레이션을 포함한 전체 과정이 무변동이라고 가정할 수는 없다.

### 9.3 앞선 메모리 연구와 연결해서 읽기

앞서 검토한 [Agent Memory Distillation](https://jiphyeonjeon.kr/blog/agent-memory-distillation)이 교사의 성공 경험을 학생이 사용할 수 있는 WF·ST·FN 예시로 바꾸는 데 초점을 맞췄다면, PG는 **현재 진행 위치에 연결된 절차 구조와 그 구조의 갱신**을 중심에 둔다. AMD의 비교는 teacher–student 전달을, PG의 비교는 같은 LLM의 solver·guidance·refiner 구성을 사용한다. 두 연구를 같은 종류의 distillation 성능 경쟁으로 볼 수는 없다. [AMD 논문](https://arxiv.org/abs/2608.07169v1), [PG §4](https://arxiv.org/pdf/2609.09153v1#page=6)

실제로 PG를 적용하려면 다음 질문들이 중요하다.

| 설계 질문 | 확인할 대상 |
| --- | --- |
| 현재 action을 graph node에 안정적으로 연결할 수 있는가? | 노드 명명 규칙, exact match 실패, full-graph fallback 빈도 |
| 필요한 절차가 2-hop 안에 표현되는가? | 분기·검증·의존 관계의 범위와 누락 |
| Guidance가 도움이 되는가? | 원문 그래프 주입 대비 성능과 추가 호출 비용 |
| Graph validator가 검사하지 않는 것은 무엇인가? | Tool schema, 권한, 업무 규칙과 실제 종료 조건 |
| 진화가 실제 일반화를 개선하는가? | Train/validation/test 분리, 반복 선택 효과, 최종 checkpoint 기준 |
| 환경이 바뀌어도 같은 절차가 유효한가? | Adapter 상태 전이, API 의미, action side effect의 변화 |

PG의 기여는 경험을 그래프에 저장했다는 사실 하나에 있지 않다. 노드에 현재 행동을 연결하고, 주변 전이를 상황별 guidance로 바꾸며, 성공·실패 기록을 바탕으로 그래프 자체를 수정하는 연결된 절차에 있다. 본평가의 넓은 우세와 별도 진화 실험의 개선은 이 접근을 검토할 충분한 근거를 준다.

동시에 soft guidance의 한계, 추가 token 비용, construction-mode 매핑과 검증 과정의 조건을 유지해야 결론이 선명해진다. **절차 지식을 모델 밖의 편집 가능한 상태로 만들면, 실행의 일관성과 경험을 통한 개선을 함께 다룰 수 있다.** 그 상태가 실제로 더 좋은 행동을 만드는지는 각 환경의 평가 기준과 비용을 통해 계속 확인해야 한다.

*원논문 Figures 1–6을 도판 영역만 추출해 인용하고 한국어 해설을 덧붙였다. 원본 그래프·축·범례·수치는 유지했다. 이 글은 v1의 원문 검토이며, 모델·시뮬레이터 실험을 새로 실행한 것은 아니다.*

## References

Fu, Y., Kim, D.-K., Kim, J., Sohn, S., Logeswaran, L., Bae, K., & Lee, H. (2024). *AutoGuide: Automated generation and selection of context-aware guidelines for large language model agents* (arXiv:2403.08978). arXiv. [arXiv 논문](https://arxiv.org/abs/2403.08978)

Kim, T., Kim, K., & Hwang, S. J. (2026). *Agent memory distillation: Empowering small LLM agents with hierarchical teacher memory* (arXiv:2608.07169v1). arXiv. [arXiv 논문](https://arxiv.org/abs/2608.07169v1)

Lu, Y., Chen, Y., Wu, S., & Arık, S. Ö. (2026). *Procedural graphs: Self-evolving execution structures for LLM agents* (arXiv:2609.09153v1). arXiv. [arXiv 논문](https://arxiv.org/abs/2609.09153v1)

Wang, Z. Z., Mao, J., Fried, D., & Neubig, G. (2025). Agent workflow memory. In *Proceedings of the 42nd International Conference on Machine Learning* (Vol. 267, pp. 63897–63911). PMLR. [PMLR proceedings](https://proceedings.mlr.press/v267/wang25bx.html)

Zhu, Y., Qiao, S., Ou, Y., Deng, S., Lyu, S., Shen, Y., Liang, L., Gu, J., Chen, H., & Zhang, N. (2025). KnowAgent: Knowledge-augmented planning for LLM-based agents. In *Findings of the Association for Computational Linguistics: NAACL 2025* (pp. 3709–3732). Association for Computational Linguistics. [ACL Anthology](https://aclanthology.org/2025.findings-naacl.205/)
