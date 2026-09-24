# Explaining Temporal Graph Neural Networks via Feature-induced Information Flow

**Paper:** Xiong, Ping; Schnake, Thomas; Müller, Klaus-Robert; Nakajima, Shinichi. "Explaining Temporal Graph Neural Networks via Feature-induced Information Flow." arXiv:2606.27201v1 [cs.LG], 2026-06-25.

**Event Relevance(ER)**는 Event-based Temporal Graph Neural Network(ETGNN)의 EP·Embedding·Decoding 모듈별 정보 흐름을 분해해 event feature 경로와 event-induced message 경로를 모두 추적함으로써 각 이벤트의 최종 예측 기여도를 수치화하는 post-hoc 설명 방법이다(Xiong et al., arXiv:2606.27201, 2026). Infection Recall-chain에서 ER 0.844를 기록해 TGNNExplainer 0.055를 크게 앞섰다.

**Abstract:** 이 논문은 Event-based Temporal Graph Neural Networks(ETGNNs)의 예측을 설명할 때, 기존 방법들이 주로 최종 embedding/decoder 쪽 정보 흐름만 추적하고, 시간 순서대로 누적되는 node memory evolution 경로를 충분히 보지 못한다는 문제에서 출발한다. 저자들은 Normalized Relevance Measure(NRM)를 기반으로, 이벤트 feature뿐 아니라 이벤트가 유도한 message 변수와 memory update 경로까지 포함하는 Event Relevance(ER)를 정의한다. 핵심은 "어떤 이벤트가 최종 예측에 영향을 주었는가"를 단순히 최근 event-subgraph로 찾는 것이 아니라, ETGNN 내부의 EP(Event Processing) → Embedding → Decoding 전체 정보 흐름 위에서 계산한다는 점이다. 실험에서는 Infection, Attacker 합성 데이터와 ICEWS18 정치 이벤트 데이터에서 기존 baseline보다 강한 설명 품질을 보이지만, 실제 데이터에는 ground-truth explanation이 없고, 일부 지표에서는 Grad×Input이 더 높으며, 대규모 그래프에서 계산비용이 작지 않다는 점을 함께 읽어야 한다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 시간 순서의 이벤트가 node memory를 계속 바꾸는 ETGNN에서, 특정 이벤트가 최종 예측에 기여한 정도를 어떻게 더 충실하게 설명할 수 있는가? |
| 핵심 기여 | ETGNN의 전체 정보 흐름을 대상으로 Event Relevance(ER)를 정의하고, NRM을 복잡한 temporal graph architecture에 적용하기 위한 modular decomposition 절차를 제안한다. |
| 방법적 결과 | ETGNN을 EP, Emb, Dec 모듈로 나눈 뒤, event feature 경로(ER-feat), event-induced message 경로(ER-msg), Emb-only 경로(ER-Emb)를 구분한다. 최종 ER은 feature/message 관련 흐름을 함께 고려하며, Joint ER은 여러 이벤트의 상호작용을 설명한다. |
| 실험 결과 | Infection Recall-chain에서 ER/ER-msg는 0.844로 Occlusion 0.352, TGNNExplainer 0.055보다 높다. Attacker Precision/Recall에서도 ER은 0.874/0.535로 강하다. ICEWS18에서는 ER이 pruning 0.098로 baseline보다 높지만, activation에서는 Grad×Input 0.198이 ER 0.173보다 높다. |
| 핵심 한계 | 평가는 두 개의 합성 데이터와 ICEWS18 일부 샘플에 기반한다. ICEWS18에는 ground-truth explanation이 없고, ER은 ICEWS18에서 약 20분의 계산시간이 보고되어 TGNNExplainer보다 느리다. |

**TL;DR** — (1) Event Relevance(ER)는 ETGNN의 EP→Embedding→Decoding 정보 흐름을 모듈별로 분해해 event feature·message 경로를 모두 추적하는 ETGNN 특화 post-hoc 설명 프레임워크다. (2) Infection Recall-chain에서 ER·ER-msg 0.844, Attacker Precision 0.874·Recall 0.535로 TGNNExplainer·Occlusion 대비 강한 설명 품질을 보고했다. (3) ICEWS18에서는 ER pruning이 가장 높지만 activation 지표에서는 Grad×Input 0.198이 ER 0.173을 앞서며, ICEWS18 기준 약 20분의 계산 시간이 TGNNExplainer보다 느리다.

## 목차

1. 서론
2. 예비 지식
3. 방법적 프레임워크
4. Event Relevance 정의
5. 기존 방법과의 비교
6. 실험 결과 및 분석
7. 주의해서 읽을 지점
8. 결론
9. References

---

## 1. 서론

### 1.1 왜 temporal graph 설명은 어려운가

Temporal Graph Neural Network는 시간에 따라 바뀌는 관계 데이터를 다룬다. 예를 들어 감염 추적에서는 "누가 언제 누구와 접촉했는가"가 중요하고, 정치 이벤트 예측에서는 "어떤 국가·기관·행위자가 언제 어떤 관계를 맺었는가"가 중요하다. 이때 그래프의 edge는 정적인 연결이 아니라 timestamp를 가진 event다.

ETGNN의 어려움은 여기서 시작된다. 하나의 이벤트는 단지 최종 embedding에만 영향을 주는 것이 아니라, 중간의 node memory를 바꾸고, 그 memory가 다시 이후 이벤트 처리와 최종 예측에 영향을 준다. 즉 정보 흐름은 다음처럼 누적된다.

```text
event sequence
  → event-induced messages
  → node memory updates
  → final node embeddings
  → downstream prediction
```

기존 설명 방법이 마지막 embedding 또는 event-subgraph 선택에 집중하면, "어떤 이벤트가 최종 출력에 가까운 표현에 영향을 주었는가"는 볼 수 있지만, "어떤 이벤트가 memory evolution을 통해 장거리 시간 의존성을 만들었는가"는 놓칠 수 있다.

이 논문은 바로 이 빈틈을 겨냥한다.

![Figure 1. Proposed Event Relevance overview](/api/blog/figures/tgnn-infoflow-fig1-overview.png)
<p class="blog-figure-caption"><em>그림 1. 기존 ETGNN 설명 방법과 제안된 Event Relevance(ER)의 비교. ER은 event-related embedding feature뿐 아니라 event-induced memory evolution과 higher-order joint relevance까지 추적한다. — Xiong et al. (2026) Figure 1, 연구·리뷰 목적 인용.</em></p>

### 1.2 핵심 질문

| 질문 | 내용 |
| --- | --- |
| Q1 | ETGNN의 예측을 event 단위로 설명할 때, event feature뿐 아니라 event-induced message와 memory update 경로까지 포함할 수 있는가? |
| Q2 | NRM을 복잡한 ETGNN architecture에 적용하기 위해 relevance 구조를 어떻게 모듈 단위로 분해할 수 있는가? |
| Q3 | 이렇게 정의한 ER이 기존 TGNNExplainer, Occlusion, Grad×Input 계열보다 더 충실하거나 해석 가능한 설명을 제공하는가? |

### 1.3 논문의 위치

이 논문은 세 흐름이 만나는 지점에 있다.

| 계보 | 대표 개념 | 이 논문에서의 역할 |
| --- | --- | --- |
| LRP / propagation-based XAI | output relevance를 backward로 입력 feature에 분해 | relevance propagation의 계산 원리 |
| NRM | relevance를 walk 위의 normalized signed measure로 정의 | layer 간 비교, joint relevance, arbitrary neuron set relevance 정의 |
| ETGNN XAI | TGNNExplainer, TempME 등 temporal graph explainer | 기존 방법이 EP module의 memory evolution을 놓친다는 문제의식 |

따라서 이 논문은 "새로운 temporal graph model" 논문이라기보다, **기존 ETGNN을 더 충실하게 설명하기 위한 attribution 방법 논문**으로 읽는 것이 맞다.

## 2. 예비 지식

### 2.1 Event-based Temporal Graph Neural Network

이 논문에서 ETGNN은 시간순 event를 입력으로 받는 temporal graph model이다. 각 event `e`는 다음 정보를 가진다.

```text
e = (origin node, destination node, event type, timestamp)
```

ETGNN의 forward process는 크게 세 모듈로 나뉜다.

| 모듈 | 역할 | 설명 관점에서 중요한 이유 |
| --- | --- | --- |
| EP(Event Processing) | event를 시간순으로 처리하고 node memory를 업데이트 | 장거리 시간 의존성이 주로 memory evolution에 저장된다 |
| Emb(Embedding) | 최종 node memory와 graph 상태를 바탕으로 node embedding 생성 | 기존 explainer들이 주로 보는 후반부 표현 |
| Dec(Decoding) | node/edge/graph-level prediction 수행 | 설명의 대상이 되는 최종 출력 |

핵심은 EP module이다. 이벤트가 발생하면 origin/destination node 사이에 message가 생성되고, 이 message가 aggregation/update 과정을 거쳐 node memory를 바꾼다. 이후의 예측은 이 누적된 memory에 의존한다.

![Figure 4. ETGNN forward computation](/api/blog/figures/tgnn-infoflow-fig4-etgnn.png)
<p class="blog-figure-caption"><em>그림 2. ETGNN의 forward computation과 proper FFNN 관점. EP module이 event를 처리해 node memory를 업데이트하고, Emb module과 Dec module이 최종 예측을 만든다. — Xiong et al. (2026) Figure 4, 연구·리뷰 목적 인용.</em></p>

### 2.2 LRP와 NRM

Layer-wise Relevance Propagation(LRP)은 모델의 출력 relevance를 입력 방향으로 분해하는 post-hoc explanation 방법이다. 직관적으로는 "최종 예측 점수 중 얼마가 어떤 입력 feature에서 왔는가"를 backward pass로 추적한다.

NRM(Normalized Relevance Measure)은 이를 더 일반화한다. NRM은 relevance를 neural network의 **walk** 위에 정의된 normalized signed measure로 본다.

```text
walk = input neuron에서 output neuron까지 이어지는 경로
```

이 관점의 장점은 다음과 같다.

| 장점 | 의미 |
| --- | --- |
| arbitrary neuron set relevance | 특정 layer의 neuron 집합뿐 아니라 여러 layer에 걸친 구조의 relevance를 정의할 수 있다 |
| comparability across layers | 서로 다른 layer의 latent variable relevance를 비교할 수 있다 |
| joint relevance | 여러 event 또는 neuron set의 상호작용을 higher-order relevance로 정의할 수 있다 |

이 논문은 NRM의 이 장점을 ETGNN 설명에 가져온다.

## 3. 방법적 프레임워크

### 3.1 문제 설정

논문이 설명하려는 대상은 다음 질문이다.

```text
최종 예측 y에 대해, event e는 얼마나 중요한가?
```

기존 event-subgraph explainer는 중요한 event edge 집합을 찾는다. 하지만 ETGNN에서는 event가 단순히 edge로 존재하는 것이 아니라, message를 만들고 memory를 업데이트한다. 따라서 event relevance는 event feature 자체뿐 아니라 event가 유도한 중간 변수까지 포함해야 한다.

이 논문은 event relevance를 다음 세 경로로 분해해 생각한다.

| 경로 | 의미 |
| --- | --- |
| event feature 경로 | event type, time encoding 등 event embedding 자체가 출력에 미친 영향 |
| event-induced message 경로 | event가 origin/destination node에 만든 message가 memory update를 통해 미친 영향 |
| Emb-only 경로 | 최종 embedding 단계에서 event feature가 출력에 미친 영향 |

### 3.2 왜 modular decomposition이 필요한가

NRM은 feed-forward network의 walk relevance를 기반으로 한다. 하지만 ETGNN은 단순한 FFNN이 아니다. EP module 안에는 message function, aggregation, GRU update, memory copy, batch-wise processing이 섞여 있다.

따라서 저자들은 복잡한 network를 모듈로 나누는 절차를 제안한다.

| 구조 | 처리 방식 |
| --- | --- |
| series connection | 앞 모듈의 relevance와 뒤 모듈의 relevance를 조건부 relevance 형태로 연결 |
| parallel connection | 병렬 branch를 분리하고 필요하면 duplication layer를 삽입 |
| hierarchical module | EP → EPB → message/aggregate/update처럼 점진적으로 세분화 |

이 modular decomposition의 역할은 "수식을 예쁘게 만들기"가 아니라, 복잡한 ETGNN 안에서 relevance structure를 체계적으로 만들 수 있게 하는 것이다.

### 3.3 ETGNN을 세 모듈로 보는 관점

논문은 ETGNN 전체를 다음과 같은 series module로 본다.

```text
EP module → Emb module → Dec module
```

- EP는 초기 node memory와 event feature를 받아 마지막 node memory와 event embedding copy를 낸다.
- Emb는 마지막 memory와 graph 상태를 바탕으로 최종 node embedding을 만든다.
- Dec는 최종 embedding으로 node/edge/graph prediction을 수행한다.

이렇게 보면, 최종 output relevance를 Dec에서 Emb로, Emb에서 EP로, 다시 event feature/message 변수로 흘려보낼 수 있다.

## 4. Event Relevance 정의

![Figure 6. Four event relevance definitions](/api/blog/figures/tgnn-infoflow-fig6-er-definitions.png)
<p class="blog-figure-caption"><em>그림 3. 네 가지 ER 정의. ER-feat는 event feature 도착 relevance, ER-msg는 event-induced message 경로, ER-Emb는 Emb module 중심 경로, ER은 이 흐름들의 union을 본다. — Xiong et al. (2026) Figure 6, 연구·리뷰 목적 인용.</em></p>

### 4.1 ER-feat: event feature로 들어오는 흐름

`ER-feat`는 event feature `ε(e)`에 도착하는 relevance를 본다. 여기서 event feature는 event type과 time encoding을 포함한다.

```text
ER-feat(e) = event feature ε(e)에 도착하는 모든 walk relevance
```

이 정의는 event 자체의 feature가 예측에 얼마나 영향을 주었는지 설명한다. 하지만 event가 만든 message와 memory update 경로를 충분히 보지는 못한다.

### 4.2 ER-msg: event-induced message를 통과하는 흐름

`ER-msg`는 이 논문의 핵심에 가깝다. event `e`가 origin node와 destination node에 대해 만든 message 변수들을 본다.

```text
ER-msg(e) = event e가 유도한 message 변수를 통과하는 relevance
```

이 경로는 event가 node memory를 어떻게 바꾸었는지, 그리고 그 memory evolution이 최종 예측에 어떤 영향을 주었는지를 포착한다.

논문의 주장에 따르면, 기존 ETGNN explainer들이 놓친 중요한 경로가 바로 이 EP module 내부의 message/memory update 경로다.

### 4.3 ER-Emb: Embedding module만 보는 대응물

`ER-Emb`는 Emb module에서 event feature가 받은 relevance만 고려한다. 논문은 이를 강한 제안 방법이라기보다, 기존 explainer들이 주로 보는 후반부 정보 흐름에 대응하는 NRM 버전으로 둔다.

실험에서도 ER-Emb는 대체로 약하게 나온다. 이는 "ETGNN 설명에서 EP module을 무시하면 중요한 정보 흐름을 놓친다"는 논문의 메시지를 뒷받침한다.

### 4.4 Full ER: feature 경로와 message 경로를 함께 보기

최종 Event Relevance(ER)는 event 관련 정보 흐름 전체를 보려는 정의다. 논문 설명상 ER은 ER-msg와 ER-Emb의 union/sum 관점으로 이해할 수 있다.

| 정의 | 보는 경로 | 해석 |
| --- | --- | --- |
| ER-feat | event feature 도착 relevance | event embedding 자체의 영향 |
| ER-msg | event-induced message 통과 relevance | memory evolution을 통한 영향 |
| ER-Emb | Emb module 내 event feature relevance | 기존 후반부 explainer에 가까운 관점 |
| ER | feature/message 관련 전체 event-induced flow | 논문이 제안하는 주된 event relevance |

### 4.5 Joint ER: 여러 이벤트의 상호작용

Temporal graph에서는 단일 이벤트보다 이벤트의 연쇄가 중요할 때가 많다. 감염 예측에서는 "A가 B를 감염시키고, B가 C와 접촉하고, C가 D에게 영향을 준다" 같은 chain이 중요하다.

논문은 NRM을 통해 여러 이벤트의 joint relevance도 정의한다.

```text
Joint ER(e1, ..., eK)
= 여러 event-induced message path의 상호작용 relevance
```

Infection 실험에서 단일 marginal ER이 체인 전체를 모두 양의 relevance로 잡지 못하는 경우, 3-event joint relevance가 ground-truth infection chain을 가장 관련 높은 조합으로 잡는 예시가 제시된다. 이 부분은 NRM 기반 접근의 장점을 잘 보여준다.

## 5. 기존 방법과의 비교

| 방법 | 핵심 아이디어 | 이 논문 관점의 한계 |
| --- | --- | --- |
| TGNNExplainer | MCTS로 중요한 temporal event subgraph 탐색 | 주로 Emb/Dec 쪽 event influence에 집중하며 EP memory evolution을 충분히 보지 못한다 |
| TempME | temporal motif를 sampling하고 importance MLP를 학습 | 관련 연구로 논의되지만 본문 실험 baseline에는 포함되지 않는다 |
| Occlusion | event를 masking했을 때 출력 변화 측정 | 큰 temporal graph에서는 event 수만큼 forward가 필요해 계산비용이 폭증한다 |
| Grad×Input | gradient와 input의 곱으로 relevance 계산 | 계산은 빠르지만, message/memory 경로의 구조적 relevance를 명시적으로 모델링하지 않는다 |
| ER | NRM 기반으로 event feature와 event-induced message 흐름을 추적 | 더 충실한 설명을 목표로 하지만 대규모 그래프에서 backward relevance 계산비용이 있다 |

핵심 차이는 "중요한 event edge를 찾는다"와 "event가 유도한 내부 정보 흐름을 따라간다"의 차이다. 이 논문은 후자를 택한다.

## 6. 실험 결과 및 분석

### 6.1 실험 설정

논문은 세 데이터셋을 사용한다.

| 데이터셋 | 유형 | 과제 | 설명 |
| --- | --- | --- | --- |
| Infection | 합성 | node-level binary classification | 500명 contact network에서 감염 여부 예측 |
| Attacker | 합성 | graph-level binary classification | 빠르게 형성된 house motif attacker subgraph 탐지 |
| ICEWS18 | 실제 정치 이벤트 | event-level multi-class classification | 두 entity 사이에 발생할 event type 예측 |

baseline은 TGNNExplainer, TGNNExplainer-EP, Occlusion, Grad×Input 등이다. 저자 방법은 ER, ER-feat, ER-msg, ER-Emb, G×I-msg 변형으로 비교된다.

### 6.2 Infection 결과

![Figure 8. Infection explanation comparison](/api/blog/figures/tgnn-infoflow-fig8-infection.png)
<p class="blog-figure-caption"><em>그림 4. Infection 데이터셋의 top-20 relevant event edge 비교. 논문은 ER-feat, ER-msg, ER이 ground-truth infection chain을 더 잘 포착한다고 보고한다. — Xiong et al. (2026) Figure 8, 연구·리뷰 목적 인용.</em></p>

Infection 데이터는 감염 chain이라는 ground-truth explanation을 만들 수 있는 합성 환경이다. 논문은 Recall-chain 지표를 사용한다. 이는 top-k event가 initial infected node에서 target node까지 이어지는 ground-truth infection chain을 포함하는지를 본다.

| 방법 | Recall-chain |
| --- | ---: |
| ER | 0.844 |
| ER-msg | 0.844 |
| ER-feat | 0.563 |
| Occlusion | 0.352 |
| Grad×Input | 0.125 |
| ER-Emb | 0.104 |
| TGNNExplainer | 0.055 |
| TGNNExplainer-EP | 0.021 |

ER과 ER-msg는 Infection Recall-chain 0.844를 달성해 TGNNExplainer 0.055, Occlusion 0.352를 크게 앞섰다.

이 결과는 논문의 핵심 주장을 잘 보여준다. event-induced message 경로를 포함하는 ER/ER-msg가 가장 강하고, Emb 쪽만 보는 ER-Emb는 약하다. 즉 감염 chain처럼 장거리 temporal dependency가 중요한 과제에서는 EP module 내부의 memory evolution을 설명에 포함해야 한다.

### 6.3 Attacker 결과

![Figure 11. Attacker explanation comparison](/api/blog/figures/tgnn-infoflow-fig11-attacker.png)
<p class="blog-figure-caption"><em>그림 5. Attacker 데이터셋의 설명 heatmap 비교. 논문은 ER이 두 attacker subgraph를 모두 양의 relevance로 식별한다고 보고한다. — Xiong et al. (2026) Figure 11, 연구·리뷰 목적 인용.</em></p>

Attacker 데이터는 temporal graph 안에 빠르게 형성된 house motif가 있는지를 분류하는 합성 데이터다. house motif subgraph가 6개 edge로 7 time step 안에 만들어지면 attacker로 정의된다. 모델의 test accuracy는 99.0%로 보고된다.

| 지표 | ER | ER-feat | Occlusion | Grad×Input | TGNNExplainer |
| --- | ---: | ---: | ---: | ---: | ---: |
| Precision | 0.874 | 0.726 | 0.714 | 0.290 | 0.237 |
| Recall | 0.535 | 0.415 | 0.450 | 0.171 | 0.142 |
| Pruning | 0.843 | 0.845 | 0.698 | 0.255 | 0.336 |
| Activation | 0.565 | 0.206 | 0.443 | 0.006 | 0.025 |

ER은 Attacker Precision 0.874, Recall 0.535로 모든 baseline 대비 가장 강한 설명 품질을 보였다.

ER은 Precision, Recall, Activation에서 강하다. 다만 Pruning에서는 ER-feat 0.845가 ER 0.843보다 아주 약간 높다. 따라서 "ER이 모든 지표에서 항상 최고"라고 쓰면 부정확하다. 더 안전한 해석은 다음이다.

> Attacker 데이터에서 ER은 대체로 가장 강한 설명 품질을 보이며, 특히 attacker subgraph edge를 찾는 Precision/Recall과 activation 기준에서 baseline보다 우수하다. 다만 일부 지표에서는 ER-feat가 근소하게 앞선다.

### 6.4 ICEWS18 결과

ICEWS18은 실제 정치 이벤트 데이터다. 2018-01-01부터 2018-10-31까지 468,558개 political event를 포함하고, 304 time step, 평균 1,541 event/time step, 256개 event tag를 가진다. 모델은 event type을 예측하며, 논문은 약 33% accuracy와 55% Hit@3를 보고한다.

ICEWS18에는 ground-truth explanation이 없기 때문에, 논문은 pruning/activation metric과 qualitative example을 사용한다. 정량 평가는 정확히 예측된 이벤트 중 무작위로 뽑은 50개 이벤트의 top-20 relevance를 대상으로 한다.

| 방법 | Pruning | Activation |
| --- | ---: | ---: |
| ER | 0.098 | 0.173 |
| ER-feat | 0.092 | 0.170 |
| ER-msg | 0.065 | 0.180 |
| ER-Emb | 0.090 | 0.174 |
| G×I-msg | 0.023 | 0.183 |
| Grad×Input | 0.003 | 0.198 |
| TGNNExplainer | -0.021 | 0.077 |
| TGNNExplainer-EP | -0.023 | 0.066 |

ICEWS18에서 ER은 pruning 지표 0.098로 모든 방법 중 가장 높다.

여기서 해석은 신중해야 한다. ER은 pruning에서 가장 좋지만, activation에서는 Grad×Input이 0.198로 ER 0.173보다 높다. 따라서 ICEWS18에서 "ER이 모든 perturbation 지표를 압도한다"고 말할 수 없다. 논문 자체도 ER 방법들이 pruning test에서는 baseline보다 강하지만 activation test에서는 Grad×Input보다 약간 낮다고 설명한다.

정성적으로는 "United Nations—Make an appeal or request→ Legislature (Poland)" 예측에 대해 ER이 폴란드 의회, EU, 시민 시위, UN 관련 이벤트 등 직관적으로 관련 있어 보이는 사건을 찾는 예시가 제시된다. 그러나 이는 ground-truth explanation이 아니라 저자 해석과 외부 뉴스 맥락에 기반한 qualitative example이다.

### 6.5 계산 시간

논문은 M1Pro CPU에서 approximate runtime도 제시한다.

| 방법 | ICEWS18 | Attacker |
| --- | ---: | ---: |
| ER | 20 min | 3.5 sec |
| Occlusion | infeasible | 1 sec |
| Grad×Input | 5 min | 0.03 sec |
| TGNNExplainer | 10 sec | 3 sec |

ER은 설명 품질 측면에서 강하지만 계산비용이 작지 않다. 특히 ICEWS18에서 forward 준비 약 2분, backward relevance propagation 약 18분이 보고된다. 반대로 Occlusion은 Attacker 같은 작은 그래프에서는 빠르지만, ICEWS18에서는 event 수만큼 forward가 필요해 infeasible로 처리된다.

따라서 실용적 관점에서는 다음 trade-off가 있다.

| 관점 | ER의 장점 | ER의 비용 |
| --- | --- | --- |
| 충실도 | EP memory evolution을 포함한 전체 event-induced flow 설명 | relevance 구조와 LRP rule 구성이 복잡 |
| 해석력 | infection chain, attacker motif처럼 temporal interaction 설명에 강함 | 실제 데이터에서는 ground-truth 부재로 검증이 간접적 |
| 확장성 | Occlusion보다 대규모 그래프에서 현실적 | Grad×Input, TGNNExplainer보다 느릴 수 있음 |

## 7. 주의해서 읽을 지점

### 7.1 평가는 제한된 데이터셋 위에 있다

논문은 두 개의 합성 데이터와 ICEWS18 하나를 사용한다. 합성 데이터는 ground-truth explanation이 있어 XAI 방법 비교에 유용하지만, 동시에 논문의 강점인 event chain/motif 구조가 잘 드러나도록 설계된 환경이기도 하다. 따라서 "모든 temporal graph 문제에서 검증됐다"는 식의 일반화는 피해야 한다.

### 7.2 실제 데이터에는 정답 설명이 없다

ICEWS18에서는 ground-truth explanation이 없다. 논문은 pruning/activation과 qualitative example로 설명 품질을 평가한다. 이는 XAI 연구에서 흔한 방식이지만, "정답 설명을 맞췄다"와는 다르다. 더 정확한 표현은 다음이다.

> ER은 모델 출력 변화 기준과 정성 사례에서 더 설득력 있는 설명을 제공했다.

### 7.3 ER이 모든 지표에서 최고는 아니다

Infection과 Attacker에서는 ER/ER-msg가 매우 강하지만, ICEWS18 activation에서는 Grad×Input이 더 높다. Attacker pruning에서도 ER-feat가 ER보다 근소하게 높다. 논문의 핵심 성과는 "전 지표 압도"가 아니라, **EP module과 message 경로를 포함하면 기존 event-subgraph/embedding 중심 설명보다 더 충실한 설명이 가능하다**는 데 있다.

### 7.4 계산비용과 구현 복잡도

ER은 NRM과 modular decomposition 위에서 작동한다. 이는 이론적으로 깔끔하지만, 실제 모델마다 relevance structure와 propagation rule을 구성해야 한다. 논문도 향후 연구로 relevance structure construction을 더 자동화하는 도구와 forward-hook trick 기반 효율화를 언급한다. 또한 구현은 "upon publication"으로 공개 예정이라고 되어 있어, 외부 재현성은 코드 공개 전까지 제한적이다.

## 8. 결론

### 8.1 핵심 기여 요약

| 기여 | 내용 |
| --- | --- |
| 문제 재정의 | ETGNN 설명에서 event feature뿐 아니라 event-induced message와 memory evolution을 설명 대상으로 포함 |
| 방법론 | NRM 기반 Event Relevance와 modular decomposition 제안 |
| 확장성 | Joint ER을 통해 여러 이벤트의 higher-order interaction 설명 가능 |
| 실험 | Infection, Attacker, ICEWS18에서 정성·정량 평가 수행 |
| 실용적 경계 | 대규모 그래프에서 계산비용이 있고, 실제 데이터 설명 평가는 ground-truth 없이 간접 평가에 의존 |

### 8.2 이 방법이 특히 잘 맞는 조건

ER은 다음 조건에서 특히 설득력이 있다.

- 예측이 단일 이벤트보다 이벤트 연쇄에 의존할 때
- node memory evolution이 중요한 ETGNN architecture일 때
- 감염 chain, 공격자 motif처럼 ground-truth explanation을 어느 정도 구성할 수 있을 때
- 단순 event-subgraph selection보다 내부 정보 흐름을 보고 싶을 때

반대로 다음 상황에서는 추가 검증이 필요하다.

- memory update 비중이 낮은 temporal graph model
- 매우 큰 실제 그래프에서 다수 예측을 반복 설명해야 하는 경우
- ground-truth explanation이 없고 perturbation metric도 불안정한 도메인
- LRP rule 선택에 민감할 수 있는 복잡한 architecture

### 8.3 향후 연구 방향

가장 중요한 후속 작업은 세 가지다.

1. **자동화**  
   ETGNN마다 relevance structure를 수작업으로 구성하는 부담을 줄여야 한다.

2. **효율화**  
   ICEWS18에서 ER이 약 20분 걸리는 만큼, forward-hook trick 등으로 대규모 그래프 설명 비용을 줄일 필요가 있다.

3. **외부 검증**  
   더 다양한 temporal graph architecture, 실제 데이터셋, human/domain-expert evaluation에서 ER의 해석 품질을 검증해야 한다.

이 논문은 ETGNN 설명에서 "최종 embedding에 가까운 event 영향"만 보는 것이 충분하지 않다는 점을 분명하게 보여준다. 특히 temporal graph의 본질이 시간에 따른 memory evolution이라면, 설명 역시 그 evolution 경로를 따라가야 한다. 이 점에서 ER은 temporal graph XAI의 설명 단위를 event-subgraph에서 event-induced information flow로 확장하는 의미 있는 시도다.

## References

Xiong, P., Schnake, T., Müller, K.-R., & Nakajima, S. (2026). *Explaining temporal graph neural networks via feature-induced information flow* (arXiv:2606.27201v1). arXiv. https://arxiv.org/abs/2606.27201 ([PDF 보기](/paper-viewer?title=Explaining+temporal+graph+neural+networks+via+feature-induced+information+flow&arxiv_id=2606.27201&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2606.27201.pdf&year=2026&authors=Ping+Xiong%3BThomas+Schnake%3BKlaus-Robert+M%C3%BCller%3BShinichi+Nakajima))

Xiong, P., Schnake, T., Montavon, G., Müller, K.-R., & Nakajima, S. (2026). *Normalized relevance measure as a unifying framework to explain neural network latent structures* (arXiv:2606.00557). arXiv. https://arxiv.org/abs/2606.00557 ([PDF 보기](/paper-viewer?title=Normalized+relevance+measure+as+a+unifying+framework+to+explain+neural+network+latent+structures&arxiv_id=2606.00557&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2606.00557.pdf&year=2026&authors=Ping+Xiong%3BThomas+Schnake%3BGr%C3%A9goire+Montavon%3BKlaus-Robert+M%C3%BCller%3BShinichi+Nakajima))

Xia, W., Lai, M., Shan, C., Zhang, Y., Dai, X., Li, X., & Li, D. (2023). *Explaining temporal graph models through an explorer-navigator framework*. ICLR. https://openreview.net/forum?id=BR_ZhvcYbGJ ([PDF 보기](/paper-viewer?title=Explaining+temporal+graph+models+through+an+explorer-navigator+framework&pdf_url=https%3A%2F%2Fopenreview.net%2Fpdf%3Fid%3DBR_ZhvcYbGJ&year=2023&authors=Wenwen+Xia%3BMingyu+Lai%3BChaozhuo+Shan%3BYing+Zhang%3BXiaowei+Dai%3BXiang+Li%3BDongsheng+Li&url=https%3A%2F%2Fopenreview.net%2Fforum%3Fid%3DBR_ZhvcYbGJ&source=openreview))

Chen, J., & Ying, R. (2023). *TempME: Towards the explainability of temporal graph neural networks via motif discovery*. NeurIPS. https://arxiv.org/abs/2310.19324 ([PDF 보기](/paper-viewer?title=TempME%3A+Towards+the+explainability+of+temporal+graph+neural+networks+via+motif+discovery&arxiv_id=2310.19324&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2310.19324.pdf&year=2023&authors=Jialin+Chen%3BRex+Ying))

Rossi, E., Chamberlain, B., Frasca, F., Eynard, D., Monti, F., & Bronstein, M. M. (2020). *Temporal graph networks for deep learning on dynamic graphs* (arXiv:2006.10637). arXiv. https://arxiv.org/abs/2006.10637 ([PDF 보기](/paper-viewer?title=Temporal+graph+networks+for+deep+learning+on+dynamic+graphs&arxiv_id=2006.10637&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2006.10637.pdf&year=2020&authors=Emanuele+Rossi%3BBen+Chamberlain%3BFabrizio+Frasca%3BDavide+Eynard%3BFederico+Monti%3BMichael+Bronstein))

Schnake, T., Eberle, O., Lederer, J., Nakajima, S., Schütt, K. T., Müller, K.-R., & Montavon, G. (2022). Higher-order explanations of graph neural networks via relevant walks. *IEEE Transactions on Pattern Analysis and Machine Intelligence, 44*(11), 7581–7596. https://doi.org/10.1109/TPAMI.2021.3115452 ([PDF 보기](/paper-viewer?title=Higher-order+explanations+of+graph+neural+networks+via+relevant+walks&arxiv_id=2006.03589&doi=10.1109%2FTPAMI.2021.3115452&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2006.03589.pdf&year=2022&authors=Thomas+Schnake%3BOliver+Eberle%3BJonas+Lederer%3BShinichi+Nakajima%3BKristof+T.+Sch%C3%BCtt%3BKlaus-Robert+M%C3%BCller%3BGr%C3%A9goire+Montavon))

Bach, S., Binder, A., Montavon, G., Klauschen, F., Müller, K.-R., & Samek, W. (2015). On pixel-wise explanations for non-linear classifier decisions by layer-wise relevance propagation. *PLOS ONE, 10*(7), e0130140. https://doi.org/10.1371/journal.pone.0130140 ([PDF 보기](/paper-viewer?title=On+pixel-wise+explanations+for+non-linear+classifier+decisions+by+layer-wise+relevance+propagation&pdf_url=https%3A%2F%2Fjournals.plos.org%2Fplosone%2Farticle%2Ffile%3Fid%3D10.1371%2Fjournal.pone.0130140%26type%3Dprintable&doi=10.1371%2Fjournal.pone.0130140&year=2015&authors=Sebastian+Bach%3BAlexander+Binder%3BGr%C3%A9goire+Montavon%3BFrederick+Klauschen%3BKlaus-Robert+M%C3%BCller%3BWojciech+Samek&url=https%3A%2F%2Fdoi.org%2F10.1371%2Fjournal.pone.0130140&source=plos))

Boschee, E., Lautenschlager, J., O’Brien, S., Shellman, S., Starz, J., & Ward, M. (2015). *ICEWS coded event data*. Harvard Dataverse. https://doi.org/10.7910/DVN/28075
