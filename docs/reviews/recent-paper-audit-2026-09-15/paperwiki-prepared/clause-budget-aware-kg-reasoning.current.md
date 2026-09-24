**Paper:** Zhao, Y., Dai, C., Zhuo, W., Xiu, Y., & Niyato, D. (2026). *CLAUSE: Agentic Neuro-Symbolic Knowledge Graph Reasoning via Dynamic Learnable Context Engineering*. International Conference on Learning Representations. [ICLR 공식 논문 페이지](https://proceedings.iclr.cc/paper_files/paper/2026/hash/8598c5d05e1d045919962e430b0bdf0d-Abstract-Conference.html) · [컨퍼런스 PDF](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf). 이 글은 본문과 부록을 포함한 27쪽의 컨퍼런스 판을 기준으로 한다.

**Abstract:** 지식 그래프를 활용한 다중 홉 질의응답에서는 최종 LLM의 추론 능력만큼 어떤 근거를 보여주는지가 중요하다. 주변 그래프를 넓게 가져오면 필요한 관계를 찾을 가능성은 높아지지만, 불필요한 간선과 텍스트도 함께 늘어난다. CLAUSE는 이 맥락 구성 과정을 순차 의사결정으로 모델링한다. Subgraph Architect가 작업용 그래프를 편집하고, Path Navigator가 경로를 탐색하며, Context Curator가 최종 근거를 선택한다. 세 정책은 LC-MAPPO로 공동 학습하며 그래프 편집·상호작용 단계·선택 토큰을 별도 비용으로 취급한다. 저자 실험에서 Qwen3-32B를 reader로 쓴 CLAUSE는 MetaQA 2-hop에서 87.3 EM@1을 기록했고, GraphRAG의 48.0보다 높으면서 정규화 지연과 간선 지표도 낮았다. 그러나 강한 agent baseline인 KG-Agent와의 차이는 9.3%p이며, 별도 제약 학습 실험의 feasibility rate는 34.0%다. 따라서 이 연구는 학습 가능한 맥락 제어의 유용성을 보여주지만, 정확도 우위·개별 질의의 예산 준수·실제 응답시간 보장을 각각 다른 근거로 읽어야 한다. [논문 §§3–5, Tables 2–4, Figure 3](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=8)

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 그래프 확장, 경로 탐색, 근거 선택, 종료 시점을 함께 학습해 질의별 자원 제약에 맞출 수 있는가? |
| 핵심 기여 | Context engineering을 지식 그래프 위의 예산 조건부 순차 의사결정으로 정식화한다. |
| 구조 | Architect·Navigator·Curator의 세 정책과 중앙 task/cost critic을 결합한다. |
| 학습 | LC-MAPPO가 task reward와 세 비용의 가치를 분리하고, 자원별 Lagrange multiplier를 갱신한다. |
| 대표 결과 | MetaQA 2-hop에서 GraphRAG 대비 +39.3 EM percentage points, 정규화 평균 지연 18.6% 감소, 간선 지표 40.9% 감소. |
| 중요한 비교 | 동일 과제의 KG-Agent 대비 EM 차이는 +9.3%p다. HotpotQA·FactKG에서 CLAUSE가 가장 빠른 것은 아니다. |
| 해석의 경계 | 평균 비용 제약과 실행 시 강제 상한은 다르다. 학습 제약 실험은 완전한 준수를 보이지 않으며, 이론의 적용 가정과 구현 세부에도 확인할 부분이 남는다. |

대표 결과는 저자 표를 재계산한 값이며, 비교 대상과 분모는 §6에서 설명한다. [논문 Tables 2–4](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=8)

## 목차

1. 더 오래 생각하기 전에, 무엇을 볼지 결정해야 한다
2. 세 에이전트가 구성하는 하나의 맥락
3. 상태·행동·비용을 어떻게 정의하는가
4. LC-MAPPO는 정확도와 자원 비용을 어떻게 함께 학습하는가
5. 실험 환경과 기존 방법의 비교축
6. 결과 분석: 정확도, 지연, 간선, 토큰, 제약 준수
7. Ablation과 사례로 확인하는 각 구성요소의 역할
8. 보장과 재현성을 제한해서 읽어야 하는 이유
9. 적용 조건과 후속 연구

---

## 1. 더 오래 생각하기 전에, 무엇을 볼지 결정해야 한다

“어떤 배우와 함께 출연한 사람은 누구인가?”라는 질문을 생각해 보자. 답에 필요한 관계는 배우에서 영화로, 영화에서 다른 배우로 이어진다. 그러나 그래프의 주변 간선을 모두 가져오면 감독, 장르, 제작사와 다른 작품의 배우까지 섞일 수 있다. LLM의 입력은 길어지지만 정답을 뒷받침하는 관계가 더 선명해지는 것은 아니다.

CLAUSE는 이 상황에서 세 결정을 연결한다. 어느 간선을 작업용 그래프에 추가할지, 어느 경로를 계속 따라가거나 되돌아갈지, 최종적으로 어떤 근거만 LLM에 보여줄지다. 근거가 충분하면 일찍 멈추고, 추가 탐색의 가치가 클 때만 더 많은 자원을 쓰도록 학습한다. [논문 §§1, 4](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=5)

이때 context engineering은 프롬프트의 문장을 잘 쓰는 작업보다 넓다. **LLM이 보게 될 근거 집합과 그 근거를 얻기 위한 행동을 함께 설계하는 문제**다. 고정된 hop 수나 top-k를 사람이 조정하는 대신, 질문과 남은 예산을 조건으로 선택하도록 만드는 것이 이 논문의 방법적 중심이다.

앞선 WikiProfile 리뷰가 모델 내부 지식에 대한 접근 조건을 다뤘다면, CLAUSE는 외부 지식 그래프에서 근거를 조립하는 절차를 다룬다. 두 연구 모두 “정보가 존재하는 것”과 “현재 질문에 쓸 수 있는 형태로 접근하는 것”을 구분하지만, CLAUSE는 후자의 외부 탐색 과정을 학습 대상으로 삼는다.

## 2. 세 에이전트가 구성하는 하나의 맥락

[![CLAUSE의 Architect, Navigator, Curator와 중앙 task 및 cost critic의 연결 구조](/api/blog/figures/clause-fig1-workflow.png)](/api/blog/figures/clause-fig1-workflow.png)

*원논문 Figure 1. 아래의 edit → traverse → curate는 실행 시 맥락을 만드는 경로이고, 위의 critic과 dual update는 학습을 위한 경로다. 예산 또는 가격이 세 정책에 전달되며, 최종 reader는 선별된 맥락으로 답한다. Zhao et al. (2026), [PDF p. 5](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=5). 원본 도판 영역을 추출했으며 내부 표기와 연결 관계를 보존했다.*

그림을 누르면 원본 해상도로 볼 수 있다. 아래 도판도 같은 방식으로 확대할 수 있다.

### 2.1 에이전트는 무엇으로 구현되는가

CLAUSE의 세 에이전트는 각각 거대한 LLM 대화를 유지하는 구조로 설명되지 않는다. 논문은 공유 인코더와 작은 정책 head를 사용하고, 지식 그래프의 후보에 점수를 주는 경량 controller로 구성한다고 설명한다. 최종 답변을 생성하는 reader LLM은 이 제어 과정 뒤에 놓인다. [논문 §4.3, Appendix F](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=24)

| 정책 | 주요 관측 | 행동 | 만들어지는 결과 |
| --- | --- | --- | --- |
| Subgraph Architect | 질문, 현재 부분 그래프, 확장 가능한 경계, 남은 예산 | ADD, DELETE, STOP | 작고 질문에 맞는 작업용 부분 그래프 |
| Path Navigator | 현재 노드, 관계별 다음 후보, 지나온 경로 | CONTINUE, BACKTRACK, STOP | 답을 지지할 수 있는 경로와 탐색 기록 |
| Context Curator | 텍스트화된 노드·간선·경로 후보, 이미 고른 근거, 토큰 잔량 | SELECT, STOP | reader에게 전달할 근거 목록 |

여기서 ADD와 DELETE의 대상은 질의별 작업용 부분 그래프다. 전역 KG의 사실을 생성하거나 원본 데이터베이스에서 삭제하는 절차로 읽으면 안 된다. 또한 경로 기록은 어떤 근거를 따라왔는지 추적하게 해 주지만, KG의 사실 자체가 참인지나 최종 LLM의 문장이 모두 그 근거에 충실한지까지 증명하지는 않는다.

### 2.2 Neuro-symbolic이라는 이름의 실질

기호적 부분은 개체·관계·간선·경로와 그 위의 이산 행동이다. 신경망 부분은 후보의 우선순위, 계속 탐색할 가치, 다음 근거를 선택할 가치를 예측한다. 즉, 명시적인 그래프 상태와 학습된 점수가 결합된다. 논문은 이 구조를 path/rule search 계열의 neuro-symbolic 접근으로 위치시킨다. [논문 §2.1](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=2)

따라서 differentiable logic을 구현했다거나 완전한 논리 증명기를 학습했다는 주장으로 넓힐 필요는 없다. 이 논문에서 확인할 대상은 **기호적 행동을 학습된 정책이 얼마나 잘 선택하고, 그 행동의 자원 사용을 얼마나 잘 제어하는가**다.

## 3. 상태·행동·비용을 어떻게 정의하는가

### 3.1 질문 하나가 하나의 episode다

전역 그래프를 $\mathcal K=(V,R,E)$라 하자. $V$는 개체, $R$은 관계 유형, $E\subseteq V\times R\times V$는 사실 triple 집합이다. 질문 $q$에 대해 시스템은 다음 상태를 유지한다.

$$
s_t=(q,G_t,F_t,P_t,b_t).
$$

$G_t$는 작업용 부분 그래프, $F_t$는 현재 확장 가능한 경계 노드 집합(frontier), $P_t$는 텍스트화된 근거 후보, $b_t$는 남은 예산이다. 각 정책은 이 전체 상태를 그대로 처리하기보다 자기 역할에 필요한 작은 관측 요약을 받는다. [논문 §3](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=4)

### 3.2 Architect: 질문 주변 전체가 아니라 frontier에서 선택한다

우선 질문의 개체 이름과 별칭을 매칭해 seed를 고른다. 매칭이 약하면 고정된 인코더로 개체 텍스트를 검색하는 fallback을 사용한다. 이후 후보 간선은 frontier에서 출발하는 관계로 제한한다.

각 후보에는 개체와 질문의 유사도, 관계의 관련성, 주변 구조, degree에 따른 우선순위 등을 결합한 점수를 준다. 논문의 핵심 선택 규칙은 다음과 같이 표현된다.

$$
g(a,e\mid q,G_t)=s(e\mid q,G_t)-\lambda_{\mathrm{edge}}c_{\mathrm{edge}}(a,e).
$$

점수가 충분하고 예산이 남아 있을 때 편집을 적용한다. 많은 노드에 연결된 hub를 무조건 넓게 따라가는 대신, degree와 질문 관련성을 함께 반영해 과도한 확장을 억제하려는 설계다. [논문 §4.3](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=6)

이 점수식은 후보를 조직하는 설명이며 전체 강화학습 목적을 대체하지 않는다. 학습에서는 탐색과 근거 선택까지 포함한 최종 성과와 비용을 함께 평가한다.

### 3.3 Navigator와 Curator: 경로를 찾는 것과 보여줄 근거를 고르는 것은 다르다

Navigator는 현재 경로에서 다음 관계로 이동하거나, 이전 지점으로 되돌아가거나, 멈춘다. BACKTRACK은 잘못 들어간 경로를 수정할 수 있게 한다. 그러나 무제한 탐색은 아니며, 기본 설정에는 최대 hop 수가 따로 존재한다.

Curator는 탐색 중 얻은 근거 후보를 순서 있게 선택한다. 핵심은 독립적인 relevance 점수만 보는 top-k보다, **이미 선택한 항목을 고려해 중복과 보완 관계를 반영한다**는 데 있다. 같은 사실을 표현만 바꾼 문장 두 개보다, 답에 필요한 다른 관계를 담은 두 문장이 유용할 수 있기 때문이다. 다만 논문이 이를 구현하는 scorer의 세부 구조와 학습 효과를 모두 분리해 입증한 것은 아니다. [논문 §4.3, Algorithm 4](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=20)

### 3.4 세 비용은 서로 다른 자원을 센다

논문의 정식화에서 episode 비용은 다음과 같다.

$$
C_k=\sum_t c_t^{(k)},\qquad k\in\{\mathrm{edge},\mathrm{lat},\mathrm{tok}\}.
$$

| 비용 | 정식화에서 세는 것 | 해석할 때 구분할 점 |
| --- | --- | --- |
| $C_{\mathrm{edge}}$ | ADD·DELETE 편집 횟수 | 최종 그래프의 간선 수나 고유하게 방문한 간선 수와 자동으로 같지 않다. |
| $C_{\mathrm{lat}}$ | 탐색 상호작용 단계. §4.3과 Algorithm 1에서는 Navigator의 hop에 귀속한다. | 실제 wall-clock 시간의 대리 지표이며 세 agent의 모든 행동을 합산한 값으로 단정하지 않는다. |
| $C_{\mathrm{tok}}$ | 새로 선택해 맥락에 포함하는 항목의 토큰 수 | 전체 학습 비용, 모든 API 호출 비용, 출력 토큰까지 합친 비용을 뜻하지 않는다. |

[논문 §3, Table 1](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=4)

DELETE도 편집 비용을 소비한다. 그래프를 줄이는 행동이라고 이미 사용한 탐색 비용이 환불되는 것은 아니다. 이 구분은 나중에 Table 4의 “average edge budget”을 해석할 때 중요하다. 실험 표는 그 지표를 탐색한 간선의 평균 수로 설명하므로, 정식화의 편집 카운터와 완전히 동일한 통계라고 단정할 수 없다.

지연 카운터의 세부 단위도 재현 시 확인해야 한다. §3은 STOP을 제외한 행동으로 쓰고, §4.3은 Navigator의 hop마다 증가한다고 설명하며, Algorithm 2는 바깥 반복마다 카운터를 증가시킨다. 이 글은 이를 탐색의 상호작용 비용으로 설명하되, 해당 표기들이 실제 구현에서 동일한 단위를 센다고 가정하지 않는다.

## 4. LC-MAPPO는 정확도와 자원 비용을 어떻게 함께 학습하는가

### 4.1 정확도만 보상하면 탐색을 멈출 이유가 약해진다

최종 답변이 맞았는지만 보상하면 불필요한 확장도 성공 경로의 일부로 남을 수 있다. CLAUSE는 이를 constrained Markov decision process, 즉 비용 제약이 있는 순차 의사결정으로 정식화한다.

$$
\max_{\pi}\;\mathbb E_{\tau\sim\pi}[R_{\mathrm{acc}}(\tau)]
\quad\text{s.t.}\quad
\mathbb E[C_k]\le\beta_k\quad \forall k.
$$

$\tau$는 한 질문에 대한 행동 궤적이고, $\beta_k$는 자원별 예산이다. 이 식은 논문의 Equation 1을 재표기한 것이다. 중요한 점은 제약이 **기댓값**에 걸린다는 것이다. 모든 질문에서 한 번도 넘지 않는 경로별 상한과 같은 명제가 아니다. [논문 §3, Eq. 1](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=5)

### 4.2 각 자원에 별도의 가격을 붙인다

세 비용에 비음수 multiplier $\lambda_k$를 두면, 부록 G의 전체 Lagrangian은 다음과 같다.

$$
\mathcal L(\pi,\lambda)=\mathbb E\!\left[R_{\mathrm{acc}}-\sum_k\lambda_k(C_k-\beta_k)\right].
$$

정책을 갱신할 때 $\lambda_k\beta_k$는 상수이므로 행동에 영향을 주는 부분은 다음 shaped reward다.

$$
r'_t=r_t^{\mathrm{acc}}
-\lambda_{\mathrm{edge}}c_t^{\mathrm{edge}}
-\lambda_{\mathrm{lat}}c_t^{\mathrm{lat}}
-\lambda_{\mathrm{tok}}c_t^{\mathrm{tok}}.
$$

예산을 초과하는 자원은 더 비싸게 만들고, 그 자원을 쓰는 행동의 평가를 낮춘다. 비용을 하나의 상수 패널티로 뭉치지 않고 나누면, 토큰은 충분하지만 탐색 단계가 부족한 상황을 구분할 수 있다. [논문 §4.4, Eq. 2, Appendix G](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=7)

### 4.3 중앙 critic과 counterfactual advantage

학습 중 중앙 critic은 세 정책의 상태·행동을 함께 보고 task value와 세 cost value를 추정한다. 실행 중에는 각 정책이 자신의 관측으로 행동한다. 이것이 centralized training with decentralized execution, CTDE다.

어떤 에이전트의 행동이 기여했는지를 평가하기 위해, 다른 에이전트의 행동을 고정한 채 해당 에이전트만 다른 행동을 했을 경우의 기대값과 비교한다. 부록 Algorithm 3을 간단히 쓰면 다음과 같다.

$$
A^{i,h}(s,a)=Q_h(s,a)
-\mathbb E_{a'_i\sim\pi_i}\!\left[Q_h(s,(a_{-i},a'_i))\right],
$$

$$
A^{i,\lambda}=A^{i,\mathrm{task}}
-\sum_k\lambda_k A^{i,k}.
$$

$i$는 에이전트, $h$는 task 또는 비용 head다. “현재 Navigator의 선택이, 같은 조건에서 다른 선택을 했을 때보다 얼마나 유리했는가”를 task와 비용 각각에 대해 계산하고 결합한다. 이 advantage로 PPO의 clipped policy update를 수행한다. [논문 §4.4, Algorithms 1·3](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=19)

다만 위 재구성은 Algorithm 3을 따른 것이다. Algorithm 1은 shaped reward로 GAE를 계산한다고 설명한 뒤, 표시된 counterfactual advantage와 actor update에서는 task head만 명시한다. Algorithm 3은 cost head까지 결합한 advantage를 반환하므로 두 의사코드는 실제 PPO에 어떤 신호를 넣는지 완전히 일치하지 않는다. **Shaped-return GAE와 head별 counterfactual advantage의 결합 방식은 구현 확인이 필요한 부분**이다. [논문 Appendix C](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=19)

여기서 LC-MAPPO는 MAPPO, COMA식 counterfactual credit assignment, 자원별 Lagrangian 가격을 결합한 구조다. 세 역할로 분해했다는 사실만으로 이 구조의 모든 요소가 필수라는 결론이 나오지는 않는다. 실제 근거는 ablation이 제거한 요소와 대체 방식의 범위 안에서 읽어야 한다.

### 4.4 예산 위반량에 따라 multiplier를 갱신한다

논문에 제시된 갱신은 다음과 같다.

$$
\lambda_k\leftarrow
\left[\lambda_k+\eta\bigl(\widehat{\mathbb E}[C_k]-\beta_k\bigr)\right]_+.
$$

평균 사용량이 예산보다 크면 가격이 올라간다. 낮으면 가격이 내려가되 0 아래로 내려가지 않는다. “추가 간선 하나의 가치가 그 가격보다 높은가”라는 설명이 가능한 이유다. [논문 §4.4](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=7)

부록 G는 최적 multiplier를 예산을 조금 늘렸을 때 최적 성과가 얼마나 좋아지는지 나타내는 shadow price로 해석한다. 이 해석은 최적성·정규성 등 조건 아래의 관계다. 실제 신경망 정책에서 학습 중 얻은 $\lambda$를 측정된 “토큰당 정확도 이득”으로 그대로 간주할 수는 없다. 이론의 적용 범위는 §8.4에서 다시 살핀다.

### 4.5 Cap mode와 price mode는 다른 약속을 한다

Cap mode에서는 남은 예산을 검사해 더 이상의 행동이나 항목 추가를 막는다. Price mode에서는 고정한 $\lambda$로 자원 사용을 유도한다. 논문은 같은 checkpoint로 이런 조건을 바꿀 수 있다고 설명한다. [논문 §4.5, Algorithms 2·4](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=19)

하지만 비용에 큰 벌점을 준다는 것만으로 초과가 불가능해지지는 않는다. 실행 시 강제 상한은 행동 전 검사나 초과 선택의 취소 같은 제어가 담당해야 한다. 학습은 그 상한 안에서 유용한 일을 하도록 돕는 역할이다. 이 구분을 유지해야 Figure 3의 예산 위반 결과와 cap mode의 목표를 혼동하지 않는다.

## 5. 실험 환경과 기존 방법의 비교축

### 5.1 공통 reader와 경량 검색 구성

주 결과의 RAG·agent 방법들은 Qwen3-32B reader를 공유한다. 검색에는 GTE-small 임베딩, spaCy NER, BM25와 FAISS를 사용한다. 부록은 L20 48GB GPU 환경을 기재하지만, reader 호출에는 SiliconFlow / Groq API도 사용한다고 설명한다. 따라서 최종 LLM까지 모두 그 한 GPU에서 실행된 실험이라고 읽으면 안 된다. [논문 §5, Appendix D](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=21)

| 기본 설정 | 논문 보고값 |
| --- | --- |
| 근거 토큰 예산 | 512 |
| Reranker 단계 / 최소 선택 수 | 15 / 2 |
| 경로 탐색 상한 | 4 hops, 학습된 STOP으로 조기 종료 가능 |
| 근거 후보 pool | 128 |
| Dense fallback pool | 64 |

이 설정은 [Appendix D](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=21)를 따른다. Learned STOP을 사용해도 hop cap, 후보 수, 최소 선택 수 같은 수동 설정이 사라지는 것은 아니다.

### 5.2 데이터셋마다 다른 KG를 사용한다

| 벤치마크 | 그래프 출처와 성격 | 논문이 보고한 규모 |
| --- | --- | --- |
| MetaQA 1/2/3-hop | 영화 도메인 KB | 약 4.3만 노드, 13.5만 간선, 관계 9종 |
| HotpotQA distractor | Wikidata에서 구축한 부분 그래프 | 노드 $O(10^6)$, 간선 $O(10^7)$, 관계 $O(10^3)$ |
| FactKG | DBpedia 기반 사실 그래프 | 약 400만 노드, 1억 간선, 관계 약 1,000종 |

[논문 Appendix D, Table 7](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=21)

이들은 하나의 통합 KG에 대한 실험이 아니다. 특히 HotpotQA 그래프는 질문과 supporting paragraphs에서 개체를 인식·연결한 뒤 고정된 Wikidata dump의 주변 이웃을 추출해 만든다고 설명한다. 정확한 dump 버전과 이웃 반경은 본문에 고정되어 있지 않다. Supporting paragraphs가 어떤 분할과 절차에서 사용됐는지도 재현 시 확인해야 한다. 이 설명만으로 정답 누출을 단정할 수는 없지만, **질문만 받아 공개 KG 전체를 탐색하는 설정과 동일하다고 가정해서도 안 된다.**

FactKG는 사실 검증 성격의 데이터셋이다. 논문은 모든 열을 EM@1로 묶어 보고하므로, 이를 모든 데이터셋에서 동일한 형태의 개체 답변을 생성한 결과로 읽기보다 각 벤치마크의 과제 성격을 구분해 해석하는 편이 적절하다.

### 5.3 비교에서 무엇이 달라지는가

| 비교 계열 | 주된 비교축 | CLAUSE의 변화 |
| --- | --- | --- |
| Vanilla·Hybrid RAG | 검색 결과를 reader 맥락으로 만드는 방법 | 근거를 얻는 그래프 행동부터 선택·종료까지 학습한다. |
| GraphRAG·LightRAG | 그래프를 활용한 근거 조직 | 편집·탐색·선택에 별도 자원 비용을 부여한다. |
| ReAct·GoT·AutoGen·KG-Agent | 여러 단계의 reasoning/acting 또는 graph 탐색 | 경량 정책을 공동 학습하고 예산 조건을 관측에 넣는다. |
| MAPPO·fixed-penalty PPO·RCPO | 제약을 학습 목적에 반영하는 방식 | task/cost head와 자원별 multiplier로 비용을 분리한다. |

이는 [논문 §§2, 5](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=3)의 실험 구도를 정리한 것이다. 동일 reader를 사용하는 것은 통제의 장점이다. 그러나 reader가 같다는 것만으로 각 baseline의 원래 query mode, 튜닝 수준, 전처리 비용과 실행 조건까지 모두 같아지는 것은 아니다. 낮게 나온 특정 baseline의 점수를 그 방법 전체의 일반 성능으로 확장해서는 안 된다.

학습 방법의 계보도 구분할 필요가 있다. PPO는 수집한 경험으로 정책의 surrogate objective를 반복 최적화하는 기반 알고리즘이고, MAPPO 연구는 협력적 다중 에이전트 과제에서도 PPO를 적절히 구성하면 강한 기준선이 될 수 있음을 보여준다. CLAUSE는 이 틀을 그래프 맥락 구성에 적용하면서 자원별 비용과 multiplier를 추가한다. 따라서 기여는 PPO를 대체하는 완전히 새로운 optimizer보다는 **그래프의 세 의사결정과 다중 비용 제약을 결합한 문제 구성**에 더 가깝다. [Schulman et al. (2017)](https://arxiv.org/abs/1707.06347), [Yu et al. (2022)](https://arxiv.org/abs/2103.01955)

보상과 제약을 함께 다루는 constrained policy optimization 자체에도 선행연구가 있다. Achiam et al. (2017)의 CPO는 그 대표적 예다. 다만 CLAUSE가 그 알고리즘의 보장을 그대로 계승한 것은 아니며, 자신의 PPO·critic·dual 조합에 맞는 가정과 검증이 필요하다. [Achiam et al. (2017)](https://proceedings.mlr.press/v70/achiam17a.html)

## 6. 결과 분석: 정확도, 지연, 간선, 토큰, 제약 준수

### 6.1 정확도: 가장 큰 차이와 가장 강한 비교 대상은 다르다

다음은 Table 2의 Qwen3-32B 기반 결과 중 주요 비교 방법을 옮긴 것이다. 단위는 EM@1이며 높은 값이 좋다.

| 방법 | HotpotQA | FactKG | MetaQA 1-hop | MetaQA 2-hop | MetaQA 3-hop |
| --- | ---: | ---: | ---: | ---: | ---: |
| Vanilla RAG | 62.1 | 77.0 | 60.2 | 37.6 | 33.0 |
| Hybrid RAG | 66.0 | 80.2 | 63.0 | 41.5 | 34.1 |
| LightRAG | 44.3 | 64.5 | 54.0 | 35.0 | 32.0 |
| GraphRAG | 50.1 | 72.0 | 63.5 | 48.0 | 44.4 |
| ReAct | 63.5 | 78.2 | 82.3 | 52.1 | 49.4 |
| KG-Agent | 68.7 | 82.1 | 87.3 | 78.0 | 75.4 |
| CLAUSE | 71.7 | 84.2 | 91.0 | 87.3 | 85.5 |

[논문 Table 2, PDF p. 8](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=8)

초록의 +39.3은 MetaQA 2-hop에서 $87.3-48.0$으로 얻는 **EM percentage-point 차이**다. GraphRAG는 그 열에서 가장 강한 RAG 계열 비교 대상이지만, agent 계열까지 포함하면 KG-Agent가 78.0이다. 이 경우 차이는 9.3%p다. 같은 방식으로 HotpotQA와 FactKG에서 KG-Agent 대비 차이는 각각 3.0%p와 2.1%p다. CLAUSE의 우위는 표에 나타나지만, 그 크기는 비교 대상에 따라 달라진다.

또한 GraphRAG가 모든 데이터셋에서 가장 강한 RAG는 아니다. HotpotQA와 FactKG에서는 Hybrid RAG의 점수가 더 높다. 따라서 초록의 비교 대상을 일반적인 최고 기준선으로 부르는 것은 범위를 벗어난다.

### 6.2 효율: 정확도 개선과 항상 가장 빠름은 다른 주장이다

MetaQA 2-hop에서 정확도·지연·간선을 함께 보면 다음과 같다. 지연과 간선 지표는 모두 **같은 과제의 Vanilla RAG를 1.0으로 정규화**했다.

| 방법 | EM@1 | 정규화 평균 지연 | 정규화 간선 지표 |
| --- | ---: | ---: | ---: |
| Vanilla RAG | 37.6 | 1.00 | 1.00 |
| Hybrid RAG | 41.5 | 1.20 | 1.12 |
| GraphRAG | 48.0 | 1.40 | 1.32 |
| KG-Agent | 78.0 | 1.62 | 1.32 |
| CLAUSE | 87.3 | 1.14 | 0.78 |

[논문 Tables 2–4](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=8)

초록의 효율 개선은 각각 $(1.40-1.14)/1.40\approx18.6\%$, $(1.32-0.78)/1.32\approx40.9\%$로 확인된다. 여기서 감소율은 GraphRAG 대비 상대 감소이며, EM의 39.3%p와 계산 방식이 다르다.

반면 HotpotQA의 지연은 CLAUSE 1.48, GraphRAG 1.45이고, FactKG는 1.36 대 1.35다. 이 두 조건에서는 CLAUSE의 정확도가 더 높지만 GraphRAG보다 빠르지는 않다. Table 4도 CLAUSE가 모든 조건에서 간선을 가장 적게 쓴다는 서술을 그대로 지지하지는 않는다. MetaQA 1-hop에서는 LightRAG 0.75 대 CLAUSE 0.77, 3-hop에서는 0.82 대 0.90이다. [논문 Tables 3–4](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=8)

따라서 결과의 의미는 “모든 축에서 모든 방법을 지배한다”가 아니라, **여러 조건에서 높은 정확도와 상대적으로 절제된 자원 사용을 함께 얻었다**는 데 있다.

### 6.3 토큰: 방법군 평균과의 비교임을 기억해야 한다

[![HotpotQA, FactKG, MetaQA에서 no-RAG, RAG 계열, agent 계열과 CLAUSE의 정규화 토큰 사용 비교](/api/blog/figures/clause-fig2-token-consumption.png)](/api/blog/figures/clause-fig2-token-consumption.png)

*원논문 Figure 2. 세 패널의 기준은 Vanilla RAG의 토큰 사용량 1.0이다. RAG-based와 Agent-based는 개별 방법이 아닌 방법군 평균이며, MetaQA는 hop 설정들의 평균이다. 그림의 음영은 mean ± SD로 표시되어 있다. CLAUSE와 각 방법의 정확한 개별 토큰 차이는 이 그림만으로 읽을 수 없다. Zhao et al. (2026), [PDF p. 9](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=9). 원본 도판 영역 직접 추출.*

그림은 CLAUSE의 토큰 사용이 RAG·agent 계열 평균보다 낮다는 경향을 보여준다. 검색 맥락을 붙이지 않는 Qwen3-32B가 가장 적게 쓰는 것은 자연스럽지만, 정확도 표까지 함께 봐야 의미가 있다. 적은 토큰 자체가 목표가 아니라 주어진 자원으로 필요한 근거를 구성하는 것이 목표이기 때문이다.

다만 이 집계 그림만으로 “모든 개별 baseline과 같은 토큰을 쓰면서 더 정확하다”는 강한 비교는 확인할 수 없다. 정확한 방법별 토큰 수, 조건별 예산과 분산의 집계 단위가 더 있어야 그 주장을 세밀하게 평가할 수 있다.

### 6.4 제약 준수: 개선은 크지만 완전한 충족은 아니다

[![MAPPO, Fixed-Penalty PPO, RCPO, LC-MAPPO의 feasibility와 지연 위반·비용·dual 값 비교](/api/blog/figures/clause-fig3-constraint-satisfaction.png)](/api/blog/figures/clause-fig3-constraint-satisfaction.png)

*원논문 Figure 3. 첫 패널은 feasibility, 둘째와 셋째는 지연 위반 및 비용, 마지막은 dual 값이다. LC-MAPPO의 첫 막대가 더 높아도 1.0에는 도달하지 않는다. 마지막 패널의 큰 dual 값은 강한 비용 가격을 뜻할 수 있으나 그 자체가 더 좋은 정책의 증거는 아니다. Zhao et al. (2026), [PDF p. 9](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=9). 원본 도판 영역 직접 추출.*

이 실험은 MetaQA에서 edge budget 0.5, latency budget 0.7이라는 제약 조건을 둔다. 본문이 명시한 LC-MAPPO와 MAPPO의 비교는 다음과 같다.

| 보고 지표 | MAPPO | LC-MAPPO |
| --- | ---: | ---: |
| Feasibility rate | 0.117 | 0.340 |
| Latency violation rate | 0.880 | 0.577 |
| 정규화 latency cost | 0.838 | 0.738 |

[논문 §5.1, Figure 3](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=9)

Feasibility의 상대 개선은 약 191%지만, 절대 수준은 11.7%에서 34.0%로 바뀐 것이다. Latency violation도 여전히 0.577이다. 이 결과는 unconstrained MAPPO보다 제약을 더 잘 반영했다는 근거이며, 학습만으로 예산 위반을 없앴다는 증거가 아니다.

Feasibility를 어떤 자원들의 동시 충족으로 계산했는지, 이 실험에 cap mode가 어느 수준으로 적용됐는지는 본문에서 충분히 정의되지 않는다. 따라서 이 그림으로 hard cap의 성공이나 실패를 단정하기보다, **학습된 비용 반영과 실행 시 강제 제약을 따로 평가해야 한다**는 문제로 읽는 편이 타당하다.

### 6.5 Reader를 바꿔도 경향은 유지되는가

부록은 두 추가 reader에서 CLAUSE와 baseline을 비교한다. 아래는 각 reader의 CLAUSE 결과만 모은 것이다.

| Reader + CLAUSE | HotpotQA | FactKG | MetaQA 1-hop | MetaQA 2-hop | MetaQA 3-hop |
| --- | ---: | ---: | ---: | ---: | ---: |
| Qwen3-32B | 71.7 | 84.2 | 91.0 | 87.3 | 85.5 |
| LLaMA3.3-70B | 73.5 | 85.0 | 92.7 | 87.7 | 87.2 |
| GPT-OSS-120B | 75.0 | 85.8 | 92.2 | 88.0 | 87.5 |

[논문 Tables 2, 8–9](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=22)

저자 표에서는 세 reader 모두 CLAUSE가 비교 방법보다 높은 EM을 보인다. 이는 특정 reader 하나에서만 우연히 작동한 구성이라는 우려를 줄인다. 그러나 더 큰 reader의 이득이 완전히 사라지지는 않는다. Qwen3-32B의 좋은 성능을 곧바로 “대형 모델을 대체한다”는 결론으로 옮길 수는 없다. 또한 이 표만으로 controller checkpoint의 무학습 전이나 세 reader의 총비용 동등성이 증명되지는 않는다.

## 7. Ablation과 사례로 확인하는 각 구성요소의 역할

### 7.1 가장 큰 손실은 Architect 제거에서 나타난다

다음은 Table 5의 ablation이다. **이 표의 효율 기준은 Vanilla RAG가 아니라 full CLAUSE=1.0**이므로 앞 절과 분모가 다르다.

| 구성 | EM@1 | 정규화 지연 | 정규화 간선 지표 |
| --- | ---: | ---: | ---: |
| CLAUSE 전체 | 87.3 | 1.00 | 1.00 |
| Architect 제거: StaticRAG / no-KG | 74.8 | 1.32 | 1.44 |
| Navigator 제거: Greedy-Hop | 82.1 | 1.18 | 1.22 |
| Curator 제거: Top-k Rerank | 80.6 | 1.24 | 1.07 |
| MAPPO, dual 없음 | 85.0 | 1.08 | 1.28 |
| 고정 λ, 갱신 없음 | 84.6 | 1.06 | 1.15 |

[논문 Table 5](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=10)

Architect 제거의 감소 폭은 12.5%p로 가장 크다. 다만 이 조건은 학습된 편집 정책만 끄는 것이 아니라 StaticRAG/no-KG 대체와 묶여 있다. 따라서 이 값을 “Architect의 neural policy만으로 얻은 순수한 기여”라고 해석할 수는 없다.

Navigator와 Curator의 제거도 정확도와 효율을 악화시킨다. 그 결과는 탐색 경로를 잘 선택하는 것과 찾은 근거를 잘 압축하는 것이 서로 다른 역할임을 지지한다. 그러나 agent 수, 정책 표현력, 동일 연산량을 통제한 단일 정책과의 비교까지 제시한 것은 아니다. 세 에이전트 구조의 유용성은 보여주지만, 어떤 대안보다 반드시 우월한 최소 구성이라는 결론은 더 강한 주장이다.

### 7.2 한 사례에서 어떤 경로가 만들어지는가

[![Brian Backer를 anchor로 잡고 그래프 경로를 탐색한 뒤 공동 출연 배우와 영화 관계를 구성한 사례](/api/blog/figures/clause-fig4-case-study.png)](/api/blog/figures/clause-fig4-case-study.png)

*원논문 Figure 4. (a) 질문의 anchor를 찾고 지역 그래프를 구성한다. (b) 정책이 관련 경로를 따라 탐색한다. (c) 개체와 관계가 드러나는 근거 구조를 얻는다. 이 그림은 단일 사례의 동작 설명이며 일반적인 성공률이나 출력 완전성을 측정한 결과가 아니다. Zhao et al. (2026), [PDF p. 10](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=10). 원본 도판 영역 직접 추출.*

논문의 질문은 Brian Backer와 함께 출연한 배우를 묻는다. Architect가 배우를 anchor로 삼고 *Moving Violations*와의 출연 관계를 추가한다. Navigator는 배우–영화–배우 경로를 찾고, Curator는 Jennifer Tilly와 John Murray에 대한 두 snippet을 골라 reader에 전달한다. [논문 §5.3](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=10)

저자는 토큰 예산 512에서 실제 선택량이 약 36토큰이고, 사례의 지연이 238.6ms라고 보고한다. 이는 예산을 끝까지 채우지 않고 멈추는 의도를 보여준다. 다만 한 사례의 수치를 전체 서비스의 응답시간으로 일반화할 수 없고, 이 출력이 가능한 모든 공동 출연자를 완전하게 열거했다는 평가도 아니다.

경로를 기록한다는 장점과 reader의 근거 충실성도 별도로 봐야 한다. 이 사례에서 인용된 두 snippet만으로 anchor와의 연결 전체가 텍스트에 어떻게 보존되는지까지 상세히 제시되지는 않는다. 전체 경로 trace, Curator가 보여준 텍스트, 최종 답변을 함께 감사하는 평가가 있어야 provenance-preserving이라는 주장을 더 강하게 뒷받침할 수 있다.

## 8. 보장과 재현성을 제한해서 읽어야 하는 이유

### 8.1 지연 대리 지표와 실제 서비스 시간의 차이

CLAUSE는 탐색 단계 수를 직접 가격화한다. 이는 반복 횟수의 폭주를 막는 데 유용하지만, 한 단계의 비용은 후보 수, 노드 degree, 인덱스 조회, cache 상태에 따라 달라진다. Reader API의 대기시간도 별도다.

부록 E의 계산량 분석은 이러한 변수를 고정하거나 제한했을 때 예산과 작업량의 관계를 설명한다. 이를 토큰 수가 정해지면 실제 wall-clock 지연도 정확히 선형이고 일정하다는 보증으로 읽어서는 안 된다. Table 3은 정규화 평균만 제시하므로 절대 시간 분포, tail latency, 외부 API 변동을 확인하기 어렵다. [논문 Appendix E–F](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=22)

### 8.2 Hard cap은 구현의 세부 순서에 달려 있다

Algorithm 4의 Curator는 다음 항목을 추가하면 토큰 예산을 넘는지 먼저 검사한다. 이런 방식은 상한을 지키는 제어를 명확하게 표현한다. 반면 Algorithm 2는 간선 편집을 적용한 뒤 카운터가 상한을 넘으면 중단하는 형태이고, 토큰 초과에도 마지막 추가를 취소하거나 STOP을 강제한다고 적는다. [논문 Algorithms 2·4](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=19)

이미 사용한 자원이 상한을 넘었다면 STOP만으로 그 사용량을 되돌릴 수는 없다. 따라서 의사코드만 보고 모든 자원에 엄격한 경로별 보장이 구현됐다고 확인하기는 어렵다. 실제 구현의 사전 action mask, 선택 취소, 편집 적용 순서를 점검해야 한다. 이는 코드에서 위반이 발생했다고 확인한 결과가 아니라, **공개 의사코드의 표현만으로 보장 범위를 확정하기 어렵다는 검토**다.

### 8.3 학습 비용과 재현 조건의 공개 수준

논문은 supplementary code archive에 seed와 run script를 제공한다고 밝힌다. 본문의 하드웨어, 검색 도구, 기본 예산은 알려져 있지만, 본문·부록만으로는 학습 episode 수, 실제 학습시간, 모든 optimizer 설정과 실험별 seed 분산을 재구성하기 어렵다. Appendix F도 주로 비용 분해식과 보고해야 할 항목을 제시한다. [논문 Reproducibility Statement, Appendix D·F](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=11)

이 리뷰에서는 공식 페이지의 supplemental 링크를 확인했으나 archive 내용을 확보하지 못했다. 따라서 위 판단은 본문·부록의 공개 서술 범위에 한정하며, 별도 archive에도 필요한 정보가 없다고 주장하지 않는다.

정확도와 ablation 표에는 반복 실험의 신뢰구간이 없다. Figure 2의 음영을 EM 표의 통계적 안정성 근거로 사용할 수도 없다. 따라서 큰 성능 차이는 저자 보고 결과로 받아들이되, 작은 차이의 유의성이나 seed에 대한 안정성은 별도 재현 전까지 미확정으로 남겨야 한다.

HotpotQA의 KG dump·추출 반경, 간선 지표가 편집 횟수와 어떤 관계인지, 실제 지연 측정에 어떤 단계가 포함되는지도 중요한 재현 조건이다. 많은 간선을 가진 KG를 사용했다는 사실과, 그 전체 크기에서 indexing·갱신 비용까지 검증했다는 주장은 구분해야 한다.

### 8.4 이론은 조건부 해석이며, dual 서술에는 정합성 문제가 있다

부록 H는 보상·비용의 유계성, smoothness, 점근적으로 편향이 사라지는 gradient 추정, 제한된 분산, critic–actor–dual의 시간척도 분리, 작은 PPO surrogate bias 등을 가정한다. 고정된 multiplier에서의 정상점 논의는 이런 조건에 의존한다. 실제 신경망 정책의 모든 학습 실행에서 전역 최적성과 제약 준수가 보장된다는 뜻이 아니다. [논문 Appendix H.1–H.2](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=26)

또 하나는 수식 자체에서 확인되는 문제다. 원문의 부호를 유지해

$$
D(\lambda)=\max_\theta\mathcal L(\theta,\lambda)
$$

로 놓으면, 고정된 $\theta$에 대해 affine인 함수들의 최댓값이므로 $D$는 convex이며 dual에서는 이를 최소화한다. 정확한 inner maximization과 표준 subgradient 조건 아래에서는, 본문의 $\lambda\leftarrow[\lambda+\eta(C-\beta)]_+$가 이 $D$의 descent 방향에 대응한다. 그런데 Appendix H.3은 같은 $D$를 concave라 부르며 ascent로 설명한다. H.1의 가정에서는 $F=\mathcal L$로 정의하지만 H.2 Equation 3에서는 $F=-\mathcal L$로 바꾸어 descent 증명을 진행하는 부호 불일치도 있다. **업데이트 식의 실용적 방향과, 그 식을 정당화하는 dual 서술을 구분해서 읽어야 하는 지점**이다. [논문 Appendix H](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf#page=26)

또한 고정된 $\lambda$에서 actor가 국소 정상점에 도달한다는 결과만으로, $\max_\theta$를 전제로 한 전역 dual 최적성까지 바로 따라오지는 않는다. 따라서 shadow-price 해석은 유용한 설계 직관이지만, 공개 증명을 그대로 전역 최적성이나 배포 상한의 완결된 보증으로 인용하는 데에는 주의가 필요하다. 이 평가는 원문의 수식과 가정에서 도출한 해석이며, 보고된 실험 수치의 진위를 부정하는 주장은 아니다.

## 9. 적용 조건과 후속 연구

CLAUSE의 실용적인 아이디어는 근거 조립의 세 결정을 별도로 관측하면서도 공동 목적 아래 학습한다는 것이다. 그래프를 크게 만드는 행동과, 답에 필요한 경로를 찾는 행동과, reader에게 보여줄 문장을 고르는 행동은 자원 소비와 성공 조건이 다르다. Task reward와 비용을 분리한 critic은 그 차이를 학습 신호로 활용하려는 시도다.

이하 내용은 실험에서 직접 검증된 배포 기능이 아니라, 방법과 한계에서 도출한 적용 조건이다.

| 적용하거나 재현할 때의 질문 | 필요한 근거 |
| --- | --- |
| KG에 답을 지지하는 관계가 존재하는가? | Anchor 정확도, 누락 관계, 지원 경로의 존재 여부를 별도로 평가해야 한다. |
| 예산 변경에 잘 적응하는가? | 같은 checkpoint에서 학습 때와 다른 예산을 sweep하고 정확도·실사용량·위반률을 함께 측정해야 한다. |
| 추가 학습 비용이 정당화되는가? | Heuristic 또는 단일 정책 대비 학습비용과 질의당 절감량을 함께 보고해야 한다. |
| 실제 응답시간 상한이 필요한가? | Step budget과 별도로 wall-clock timeout, API 비용, tail latency를 검증해야 한다. |
| 경로가 곧 근거 충실성인가? | KG 경로, 선택된 텍스트, 최종 답변의 연결을 평가해야 한다. |

후속 연구에서 가장 가치 있는 비교는 token budget 하나를 맞춘 정확도 경쟁을 넘어선다. 동일 KG·동일 reader·동일 wall-clock 조건에서, 각 단계의 정책과 hard cap을 독립적으로 켜고 끄며 어떤 비용이 어디서 줄어드는지를 보여주는 실험이 필요하다. 특히 세 정책 대신 한 정책을 쓰는 경우와의 비교, 예산 분포 밖의 적응, 불완전한 KG에서의 중단과 fallback이 중요한 축이다.

CLAUSE는 **맥락 구성을 학습 가능한 제어 문제로 만든다**는 점에서 읽을 가치가 있다. 저자 표는 그 선택이 높은 QA 정확도와 절제된 자원 사용을 함께 얻을 수 있음을 보여준다. 다만 성능 비교의 분모, 제약 실험의 절대 준수율, 비용의 정의, 이론과 구현의 조건을 분리할 때 기여가 더 명확해진다. 이 논문에서 가져갈 가장 단단한 교훈은, 더 많은 그래프나 더 긴 추론을 공급하기 전에 **어떤 근거를 얻기 위해 얼마의 자원을 쓰고 언제 멈출지**를 명시적인 학습·평가 대상으로 삼을 수 있다는 것이다.

*원논문 Figures 1–4를 도판 영역만 추출해 인용했다. 원본 그래프·축·범례·수치는 유지하고, 한국어 캡션과 해석을 덧붙였다. 모든 실험 수치는 컨퍼런스 판의 저자 보고값이며, 이 글에서 모델 실험을 독립 재실행한 것은 아니다.*

## References

Achiam, J., Held, D., Tamar, A., & Abbeel, P. (2017). Constrained policy optimization. In *Proceedings of the 34th International Conference on Machine Learning* (Vol. 70, pp. 22–31). PMLR. [PMLR proceedings](https://proceedings.mlr.press/v70/achiam17a.html)

Schulman, J., Wolski, F., Dhariwal, P., Radford, A., & Klimov, O. (2017). *Proximal policy optimization algorithms* (arXiv:1707.06347). arXiv. [https://doi.org/10.48550/arXiv.1707.06347](https://doi.org/10.48550/arXiv.1707.06347)

Yu, C., Velu, A., Vinitsky, E., Gao, J., Wang, Y., Bayen, A., & Wu, Y. (2022). *The surprising effectiveness of PPO in cooperative, multi-agent games*. Advances in Neural Information Processing Systems. [arXiv:2103.01955](https://arxiv.org/abs/2103.01955)

Zhao, Y., Dai, C., Zhuo, W., Xiu, Y., & Niyato, D. (2026). *CLAUSE: Agentic neuro-symbolic knowledge graph reasoning via dynamic learnable context engineering*. International Conference on Learning Representations. [ICLR proceedings](https://proceedings.iclr.cc/paper_files/paper/2026/hash/8598c5d05e1d045919962e430b0bdf0d-Abstract-Conference.html)
