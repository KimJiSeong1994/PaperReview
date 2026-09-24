# GNNExplainer: Generating Explanations for Graph Neural Networks

**Paper:** Ying, Rex; Bourgeois, Dylan; You, Jiaxuan; Zitnik, Marinka; Leskovec, Jure. "GNNExplainer: Generating Explanations for Graph Neural Networks." *Advances in Neural Information Processing Systems 32 (NeurIPS 2019)*, arXiv:1903.03894v4, 2019-11-13. Code: https://github.com/RexYing/gnn-model-explainer.

**GNNExplainer**는 훈련된 GNN을 수정하거나 재학습하지 않고, 특정 예측을 보존하는 compact computation subgraph와 node feature mask를 mutual information 최대화 문제로 찾는 post-hoc model-agnostic GNN explanation 프레임워크다(Ying et al., NeurIPS 2019). synthetic benchmark에서 GRAD·ATT baseline 대비 평균 17.1% 높은 explanation accuracy를 보고했다.

**Abstract:** 본 문서에서는 GNN 설명가능성 연구의 대표적 기준점으로 자주 인용되는 GNNExplainer를 체계적으로 해설한다. GNNExplainer의 핵심은 훈련된 GNN의 예측을 가장 잘 보존하는 작은 computation subgraph와 node feature subset을 찾는 것이다. 논문은 이를 mutual information 최대화 문제로 정식화하고, 이산 subgraph 탐색을 연속 mask 최적화로 완화한다. 아울러 저자가 보고한 synthetic benchmark 성능과 real-world qualitative 사례를 분리해 읽고, 이 방법이 causal explanation이 아니라 prediction-preserving post-hoc explanation이라는 점을 비판적으로 정리한다.

---

> **논문 설명 요약**
> 이 논문은 훈련된 Graph Neural Network의 특정 예측을 설명하기 위해, 예측을 보존하는 compact subgraph와 node feature mask를 찾는 GNNExplainer를 제안한다.
> 방법적으로는 설명을 mutual information 최대화 문제로 정식화하고, 이산적인 부분 그래프 선택을 연속 adjacency/feature mask 최적화로 완화한다.
> 실험은 synthetic benchmark에서 구조적 explanation을 정량 평가하고, MUTAG·REDDIT-BINARY에서는 정성 사례를 제시하지만, 설명은 causal explanation이 아니라 prediction-preserving post-hoc explanation으로 읽어야 한다.

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | GNN의 특정 예측은 어떤 graph structure와 node feature에 의해 만들어졌는가? |
| 핵심 기여 | 훈련된 GNN을 수정하거나 재학습하지 않고, 예측을 설명하는 compact subgraph와 feature mask를 찾는 post-hoc, model-agnostic GNN explanation 프레임워크를 제안한다. |
| 방법적 결과 | `MI(Y, (G_S, X_S))`를 최대화하는 설명을 찾되, 실제 최적화에서는 conditional entropy를 줄이는 adjacency mask `M`과 feature selector `F`를 학습한다. 이산 subgraph 탐색은 mean-field relaxation과 sigmoid mask로 연속화된다. |
| 실험 결과 | 저자 보고 기준, synthetic node classification에서 GRAD/ATT baseline 대비 평균 17.1% 높은 explanation accuracy를 보였고, TREE-GRID에서는 최대 43.0% 높은 accuracy를 보고한다. MUTAG와 REDDIT-BINARY에서는 qualitative explanation을 제시한다. |
| 핵심 한계 | 정량 평가는 ground-truth motif가 있는 synthetic dataset에 크게 의존한다. 또한 설명은 현실의 인과 원인이 아니라, 훈련된 GNN의 prediction을 유지하는 입력 부분이다. |

**TL;DR** — (1) GNNExplainer는 훈련된 GNN의 예측을 보존하는 최소 subgraph와 feature mask를 mutual information 최대화로 찾는 post-hoc, model-agnostic 설명 프레임워크다. (2) synthetic node classification에서 GRAD·ATT baseline 대비 평균 17.1% 높은 explanation accuracy를 보고했으며, TREE-GRID에서는 최대 43.0%p 이득을 달성했다. (3) 정량 평가가 synthetic dataset에 집중되어 있고, 이 방법의 설명은 인과 원인이 아니라 훈련된 GNN의 prediction을 유지하는 입력 부분이라는 점을 함께 고려해야 한다.

## 목차

1. 서론
2. 예비 지식
3. 방법적 프레임워크
4. GNNExplainer 아키텍처 심층
5. 기존 방법과의 비교
6. 실험 결과 및 분석
7. 해석의 범위와 한계
8. 재현성과 구현 관찰
9. 결론

---

## 1. 서론

### 1.1 연구 배경: 왜 GNN 설명은 어려운가

이미지 모델을 설명할 때는 보통 어떤 pixel이나 region이 중요했는지를 묻는다. 텍스트 모델을 설명할 때는 어떤 token이나 phrase가 예측에 기여했는지를 묻는다. 그러나 graph neural network(GNN)는 이보다 복잡하다. GNN의 예측은 노드 feature만이 아니라, 이웃 노드와 edge를 따라 전달되는 message passing 경로에 의해 만들어진다.

즉 GNN 설명에서 물어야 할 질문은 하나가 아니다.

- 어떤 node feature가 중요했는가?
- 어떤 neighbor가 중요했는가?
- 어떤 edge 또는 path를 통해 정보가 전달되었는가?
- 어떤 motif나 subgraph pattern이 예측을 만들었는가?

GNNExplainer는 이 문제를 다음처럼 정식화한다.

> 특정 prediction을 만든 GNN의 computation graph 안에서, 예측을 가장 잘 보존하는 작은 subgraph와 feature subset을 찾는다.

이 관점은 이후 많은 GNN XAI 문헌이 공유하거나 비판적으로 확장하는 기준점이 되었다. 오늘날의 PGExplainer, XGNN, CF-GNNExplainer 같은 후속 연구도 GNNExplainer가 제시한 “설명 단위”를 확장하거나 비판하는 방식으로 읽을 수 있다.

![gnnexplainer fig1 overview](/api/blog/figures/gnnexplainer-fig1-overview.png)
*그림 1. GNNExplainer 전체 개요 — 훈련된 GNN이 social interaction graph에서 만든 예측을, target node 주변의 작은 subgraph와 feature subset으로 사후 설명한다. — GNNExplainer(arXiv:1903.03894) Figure 1, 원논문 figure를 리뷰 목적으로 인용·요약.*

### 1.2 핵심 질문

| 질문 | 내용 |
| --- | --- |
| Q1 | GNN의 prediction을 설명하는 작고 충분한 compact graph structure는 무엇인가? |
| Q2 | 구조뿐 아니라 node feature 차원도 함께 설명할 수 있는가? |
| Q3 | 훈련된 GNN을 수정하거나 재학습하지 않고도 explanation을 만들 수 있는가? |
| Q4 | 하나의 instance 설명을 넘어 class-level 또는 multi-instance explanation으로 확장할 수 있는가? |

### 1.3 학술적 위치

GNNExplainer는 NeurIPS 2019 논문으로, GNN 전용 post-hoc explanation 방법을 일반 프레임워크로 제시한 초기 대표작이다. 논문은 자신들의 방법을 model-agnostic으로 설명한다. 여기서 model-agnostic은 임의의 black-box 모델 전체에 적용된다는 뜻이라기보다, message-passing GNN의 구체 아키텍처를 바꾸지 않고 prediction 이후에 explanation mask를 학습한다는 의미에 가깝다.

따라서 이 논문은 "모든 GNN/모든 그래프 task에서 실험적으로 완전히 검증된 만능 설명기"라기보다, **GNN prediction을 subgraph와 feature mask로 설명하는 표준 문제 설정을 만든 논문**으로 읽는 편이 정확하다.

---

## 2. 예비 지식

### 2.1 GNN computation graph

> **Definition 1 (GNN computation graph).** 특정 node `v`의 prediction을 계산할 때 GNN이 실제로 message를 모으는 graph 영역을 `G_c(v)`라 한다. L-layer message-passing GNN이라면 보통 `v`의 L-hop neighborhood 또는 sampling된 neighborhood가 computation graph가 된다.

노드 분류 문제를 기준으로 하면, GNN의 prediction은 다음처럼 볼 수 있다.

```text
ŷ = Φ(G_c(v), X_c(v))
```

여기서 `Φ`는 훈련된 GNN, `G_c(v)`는 target node의 computation graph, `X_c(v)`는 그 computation graph에 포함된 node feature다.

### 2.2 Explanation subgraph

> **Definition 2 (Explanation subgraph).** GNNExplainer에서 explanation은 computation graph 전체가 아니라, 그 안에서 prediction을 가장 잘 보존하는 작은 subgraph `G_S`와 feature subset `X_S^F`다.

| 기호 | 의미 |
| --- | --- |
| `G_c(v)` | target node `v`의 computation graph |
| `A_c(v)` | computation graph의 adjacency matrix |
| `X_c(v)` | computation graph의 node feature matrix |
| `G_S` | explanation subgraph |
| `F` | feature selector 또는 feature mask |
| `X_S^F` | `G_S` 안에서 선택된 feature subset |

### 2.3 Prediction-preserving explanation

GNNExplainer의 설명은 "현실의 원인"을 바로 뜻하지 않는다. 이 방법은 훈련된 GNN의 예측을 보존하는 입력 부분을 찾는다. 따라서 모델이 실제 도메인 원인을 배웠다면 그 원인을 드러낼 수 있지만, 모델이 shortcut이나 spurious pattern을 배웠다면 그 shortcut도 그대로 설명할 수 있다.

이 구분은 중요하다.

| 표현 | 의미 |
| --- | --- |
| Prediction-preserving | 이 부분을 남겼을 때 GNN의 예측이 유지된다 |
| Faithful to model | 모델이 실제로 사용한 신호와 가깝다 |
| Human-plausible | 사람이 보기에 그럴듯하다 |
| Causal | 개입했을 때 결과가 바뀌는 원인이다 |

GNNExplainer는 주로 앞의 두 범주, 즉 prediction-preserving 및 model-faithful explanation에 가까운 방법이다. 후속 counterfactual/causal XAI 의미의 인과 설명을 주장하려면 별도의 intervention, counterfactual perturbation, stability 검증이 필요하다.

![gnnexplainer fig2 computation mask](/api/blog/figures/gnnexplainer-fig2-computation-mask.png)
*그림 2. Computation graph와 feature mask — 초록 edge/path는 target prediction에 중요한 message-passing pathway, 주황 edge/path는 덜 중요한 pathway를 나타낸다. 오른쪽은 subgraph 안에서도 일부 feature dimension만 explanation에 남기는 feature mask 개념을 보여준다. — GNNExplainer(arXiv:1903.03894) Figure 2, 원논문 figure를 리뷰 목적으로 인용·요약.*

---

## 3. 방법적 프레임워크

> **이 섹션의 결론:** GNNExplainer는 “좋은 설명 subgraph를 고르는 조합 문제”를 soft adjacency/feature mask 최적화 문제로 완화한다.

### 3.1 Mutual information objective

GNNExplainer의 핵심 목적함수는 다음과 같다.

```text
maximize  MI(Y, (G_S, X_S))
        = H(Y) - H(Y | G = G_S, X = X_S)
```

훈련된 GNN `Φ`가 고정되어 있으면 `H(Y)`는 상수다. 따라서 실제로는 explanation subgraph와 feature subset을 주었을 때의 conditional entropy를 줄이는 문제가 된다.

직관적으로는 다음 질문을 푼다.

> 이 작은 subgraph와 feature subset만 남겨도 GNN이 원래 예측을 자신 있게 유지하는가?

### 3.2 Compactness constraint

설명이 전체 neighborhood만큼 크다면 해석 가치가 떨어진다. 그래서 논문은 explanation subgraph의 크기를 제한한다.

```text
|G_S| ≤ K_M
```

여기서 `K_M`은 논문 표기상 explanation subgraph size를 제한하는 hyperparameter다. 이 제약은 GNN computation graph에서 noise를 제거하고, prediction에 중요한 message-passing pathway만 남기려는 장치다.

### 3.3 Continuous relaxation: adjacency mask

직접 subgraph를 고르는 것은 조합폭발 문제다. edge가 많아질수록 가능한 subgraph 수가 지수적으로 증가한다. GNNExplainer는 이를 피하기 위해 이산 subgraph 선택을 연속 mask 학습으로 바꾼다.

```text
masked adjacency = A_c ⊙ σ(M)
```

- `A_c`: 원래 computation graph의 adjacency matrix
- `M`: 학습 가능한 real-valued edge mask
- `σ(M)`: sigmoid로 `[0, 1]` 범위에 놓인 soft edge weight
- `⊙`: element-wise multiplication

학습 후에는 mask 값이 낮은 edge를 thresholding해 최종 explanation subgraph를 얻는다.

### 3.4 Mean-field relaxation

논문은 subgraph 분포를 factorized Bernoulli distribution으로 근사한다. 각 edge가 explanation에 포함될지를 독립 Bernoulli 변수처럼 보고, 그 기대값을 soft adjacency mask로 최적화한다.

이 relaxation은 계산 가능성을 주지만, 전역 최적 보장을 주지는 않는다. 논문도 neural network의 비선형성 때문에 Jensen bound의 convexity assumption이 실제로 성립하지 않는다고 설명한다. 따라서 GNNExplainer의 최적화는 이론적으로 완전한 보장보다, regularization과 gradient descent로 좋은 local solution을 찾는 실용적 접근이다.

### 3.5 Feature mask

구조만 설명하면 불충분하다. 예를 들어 molecule graph에서는 어떤 atom type이 중요한지, social graph에서는 어떤 user feature가 중요한지 함께 알아야 한다. GNNExplainer는 feature selector `F`도 학습한다.

```text
X_S^F = X_S F
```

feature mask는 중요한 node feature 차원만 남긴다. 논문은 feature importance를 안정적으로 학습하기 위해 empirical marginal distribution에서 feature sample을 뽑고 reparameterization trick을 사용한다.

---

## 4. GNNExplainer 아키텍처 심층

### 4.1 전체 구조

GNNExplainer의 흐름은 다음처럼 요약할 수 있다.

```text
Trained GNN Φ + target prediction ŷ
        │
        ▼
Computation graph G_c(v), features X_c(v)
        │
        ▼
Learn structural mask M and feature mask F
        │
        ▼
Optimize prediction-preserving objective + regularizers
        │
        ▼
Threshold masks
        │
        ▼
Explanation: compact subgraph G_S + feature subset X_S^F
```

### 4.2 구성요소

| 구성요소 | 역할 | 설계 근거 |
| --- | --- | --- |
| Computation graph extraction | target prediction에 실제로 관여할 수 있는 graph 영역을 제한 | 전체 graph 대신 local computation graph를 설명 대상으로 삼아 계산량과 noise를 줄인다 |
| Structural mask `M` | 중요한 edge/pathway를 선택 | GNN prediction은 message-passing 구조에 의존하므로 edge-level mask가 필요하다 |
| Feature selector `F` | 중요한 node feature 차원을 선택 | graph structure만으로는 feature-driven prediction을 설명할 수 없다 |
| Entropy regularization | mask가 애매한 soft weight에 머무는 것을 줄임 | 해석 가능한 discrete explanation에 가깝게 만든다 |
| Size penalty | explanation이 너무 커지는 것을 방지 | compactness와 interpretability를 유지한다 |
| Thresholding | soft mask를 최종 subgraph로 변환 | 연속 최적화 결과를 사람이 읽을 수 있는 graph explanation으로 바꾼다 |

### 4.3 Single-instance explanation

기본 설정은 single-instance explanation이다. 노드 분류라면 특정 노드의 prediction을 설명하고, graph classification이라면 특정 graph-level label prediction을 설명한다. link prediction에도 같은 틀을 확장할 수 있다고 논문은 설명한다.

single-instance explanation의 장점은 prediction 단위로 설명이 구체적이라는 점이다. 같은 edge라도 어떤 target node를 설명하느냐에 따라 중요도가 달라질 수 있다. 이 점에서 GNNExplainer는 모든 prediction에 동일한 attention pattern을 해석하는 방식보다 instance-specific하다.

### 4.4 Multi-instance prototype

논문은 여러 instance를 함께 설명하는 multi-instance explanation도 제안한다. 방식은 단일 설명들을 align한 뒤, median 기반 prototype adjacency를 만드는 것이다.

```text
single-instance explanations
        │
        ▼
align explanation subgraphs to reference
        │
        ▼
aggregate aligned adjacency matrices
        │
        ▼
class-level prototype explanation
```

다만 이 부분은 본문 핵심 실험보다 예비적 성격이 강하다. appendix는 graph alignment가 noise와 neighborhood variance 때문에 어렵고 maximum common subgraph 문제와 관련된다는 점을 언급한다. 따라서 multi-instance prototype은 GNNExplainer의 중요한 아이디어이지만, 가장 강하게 검증된 성과는 single-instance explanation 쪽에 있다.

![gnnexplainer fig6 prototype](/api/blog/figures/gnnexplainer-fig6-prototype.png)
*그림 3. Multi-instance prototype 예시 — 여러 single-instance explanation을 reference subgraph에 align하고 집계해 class-level prototype을 만드는 아이디어를 보여준다. — GNNExplainer(arXiv:1903.03894) Figure 6, 원논문 figure를 리뷰 목적으로 인용·요약.*

---

## 5. 기존 방법과의 비교

### 5.1 기존 NN XAI와의 차이

비그래프 neural network XAI는 주로 feature attribution, surrogate model, gradient/backprop 계열로 발전했다. 그러나 GNN에서는 edge, path, motif, neighborhood aggregation이 prediction을 만든다. 단순 feature saliency만으로는 relational structure를 설명하기 어렵다.

| 방법군 | 핵심 아이디어 | GNN에서의 한계 | GNNExplainer의 대응 |
| --- | --- | --- | --- |
| Surrogate model | 복잡한 model을 단순 model로 근사 | graph structure와 path interaction을 충분히 담기 어렵다 | GNN computation graph 자체에서 subgraph를 찾는다 |
| Gradient saliency | input 또는 feature에 대한 gradient를 본다 | discrete adjacency에서는 gradient가 불안정하거나 해석이 어렵다 | adjacency mask를 직접 최적화한다 |
| Attention weight | attention coefficient를 importance로 본다 | attention이 prediction-specific explanation을 보장하지 않는다 | 훈련된 GNN의 prediction을 post-hoc objective로 설명한다 |
| Counterfactual | 입력을 바꿔 prediction 변화 관찰 | 당시 GNN 전용 counterfactual 방법은 초기 단계 | GNNExplainer는 desired label에 대한 objective 변형을 언급하지만, 후속 counterfactual XAI 의미의 인과 개입 방법이라기보다 prediction-preserving subgraph를 찾는 쪽에 가깝다 |

### 5.2 GNN attention과의 차이

Graph Attention Network(GAT)의 attention coefficient는 message aggregation에서 이웃의 weight를 조절한다. 그러나 attention weight가 곧 explanation이라고 보기는 어렵다.

논문은 attention 기반 설명의 한계를 다음처럼 본다.

- attention weight는 architecture 내부 값이지 post-hoc explanation objective가 아니다.
- 특정 node prediction마다 다른 explanation을 제공하기 어렵다.
- node feature explanation과 graph structure explanation을 함께 제공하지 못한다.
- ATT baseline은 GAT architecture를 별도로 학습해야 하므로, 같은 trained GNN을 설명하는 조건이 아니다.

GNNExplainer는 이와 달리 원래 훈련된 GNN을 고정하고, 그 prediction을 유지하는 구조와 feature mask를 별도로 학습한다.

### 5.3 후속 연구에서의 위치

GNNExplainer 이후 연구는 대체로 다음 질문으로 확장된다.

| 후속 질문 | 대표 방향 | GNNExplainer와의 관계 |
| --- | --- | --- |
| 매 instance마다 mask를 새로 최적화해야 하는가? | PGExplainer | explanation generator를 학습해 inductive/multi-instance 설정으로 확장 |
| 모델 전체가 배운 graph pattern은 무엇인가? | XGNN | instance-level explanation에서 model-level graph pattern generation으로 이동 |
| 무엇을 바꾸면 prediction이 바뀌는가? | CF-GNNExplainer | importance explanation에서 counterfactual explanation으로 이동 |

이 관점에서 GNNExplainer는 완성형이라기보다 기준점이다. 후속 방법들은 GNNExplainer가 만든 설명 object를 더 빠르게, 더 일반적으로, 또는 counterfactual하게 확장하려 한다.

---

## 6. 실험 결과 및 분석

### 6.1 실험 설정

| 축 | 구성 |
| --- | --- |
| Synthetic node classification | BA-SHAPES, BA-COMMUNITY, TREE-CYCLES, TREE-GRID |
| Real-world graph classification | MUTAG, REDDIT-BINARY |
| Baseline | GRAD, ATT |
| 정량 평가 | ground-truth explanation이 있는 synthetic dataset에서 edge-level explanation accuracy 계산 |
| 정성 평가 | synthetic motif, MUTAG functional group, REDDIT thread pattern, feature heatmap |
| Hyperparameter | synthetic에서는 `K_M`을 ground-truth explanation size에 맞춰 설정, real-world에서는 `K_M = 10`, 모든 dataset에서 `K_F = 5` |

![gnnexplainer table1 synthetic results](/api/blog/figures/gnnexplainer-table1-synthetic-results.png)
*그림 4. Synthetic benchmark 구성과 explanation accuracy — BA-SHAPES, BA-COMMUNITY, TREE-CYCLES, TREE-GRID의 planted motif와 node feature 조건, 그리고 ATT/GRAD/GNNExplainer의 저자 보고 explanation accuracy를 함께 보여준다. — GNNExplainer(arXiv:1903.03894) Table 1, 원논문 figure를 리뷰 목적으로 인용·요약.*

### 6.2 Synthetic benchmark 결과

논문은 synthetic node classification에서 GNNExplainer가 GRAD 및 ATT baseline보다 평균 17.1% 높은 explanation accuracy를 보였다고 보고한다. 특히 TREE-GRID에서는 최대 43.0% 높은 accuracy를 보고한다.

이 결과는 논문의 가장 강한 정량 근거다. planted motif가 있는 synthetic graph에서는 정답 explanation이 알려져 있으므로, edge-level explanation accuracy를 계산할 수 있다. GNNExplainer가 house, cycle, grid 같은 motif를 찾아낸다는 점은 method가 구조적 explanation을 잘 포착할 수 있음을 보여준다.

![gnnexplainer fig3 synthetic explanations](/api/blog/figures/gnnexplainer-fig3-synthetic-explanations.png)
*그림 5. Synthetic node classification의 single-instance explanation — 각 dataset에서 computation graph, GNNExplainer, GRAD, ATT, ground truth explanation을 나란히 비교한다. GNNExplainer가 planted motif에 더 가까운 subgraph를 찾는다는 저자 보고 시각화다. — GNNExplainer(arXiv:1903.03894) Figure 3, 원논문 figure를 리뷰 목적으로 인용·요약.*

### 6.3 Real-world qualitative 결과

MUTAG에서는 논문이 MUTAG로 지칭한 molecule graph의 mutagenicity prediction과 관련된 carbon ring, `NH2`, `NO2` 같은 구조가 설명으로 제시된다. REDDIT-BINARY에서는 Question-Answer thread와 Online-Discussion thread의 구조적 차이를 설명하는 subgraph pattern이 제시된다.

다만 real-world 결과는 synthetic benchmark처럼 ground-truth explanation accuracy로 강하게 검증된 것은 아니다. 논문은 domain knowledge와 visual plausibility에 기반해 설명의 타당성을 보여준다. 따라서 이 부분은 정량 성능보다 qualitative demonstration으로 읽어야 한다.

![gnnexplainer fig4 realworld explanations](/api/blog/figures/gnnexplainer-fig4-realworld-explanations.png)
*그림 6. MUTAG와 REDDIT-BINARY의 qualitative explanation — MUTAG에서는 mutagenicity와 관련된 ring/NO₂ group, REDDIT-BINARY에서는 QA와 discussion thread의 구조적 pattern을 설명 예시로 제시한다. 정량 ground truth 평가가 아니라 domain-plausible qualitative 사례로 읽어야 한다. — GNNExplainer(arXiv:1903.03894) Figure 4, 원논문 figure를 리뷰 목적으로 인용·요약.*

### 6.4 Feature explanation 결과

논문은 MUTAG와 BA-COMMUNITY에서 feature heatmap을 통해 GNNExplainer가 중요한 feature 차원을 더 잘 강조한다고 보고한다. 이는 구조와 feature를 동시에 설명한다는 논문의 핵심 주장과 연결된다.

다만 feature explanation의 실험 근거는 구조 explanation보다 제한적이다. 많은 synthetic topology task는 node feature가 없거나 제한적이며, feature explanation visualization은 일부 dataset 중심으로 제시된다.

![gnnexplainer fig5 feature importance](/api/blog/figures/gnnexplainer-fig5-feature-importance.png)
*그림 7. Feature importance 시각화 — MUTAG graph classification과 BA-COMMUNITY node classification에서 ground-truth feature importance, GNNExplainer, GRAD, ATT를 비교한다. ATT는 feature explanation에는 적용되지 않는 것으로 표시된다. — GNNExplainer(arXiv:1903.03894) Figure 5, 원논문 figure를 리뷰 목적으로 인용·요약.*

---

## 7. 해석의 범위와 한계

> **읽기 경고:** 아래 항목들은 별도 비판 섹션이 아니라, 논문 결과를 과장하지 않기 위한 발행 전 검증 포인트다.

### 7.1 "Any GNN, any graph task"의 범위

논문은 GNNExplainer가 node classification, link prediction, graph classification으로 확장 가능하다고 설명한다. 또한 다양한 message-passing GNN에 적용 가능하다고 주장한다. 그러나 실험 검증은 synthetic node classification과 MUTAG/REDDIT-BINARY graph classification 중심이다.

따라서 "any GNN / any graph task"는 모든 설정에서 실험적으로 동일하게 검증되었다는 뜻이 아니다. 더 정확히는 **message-passing computation graph를 갖는 GNN에 적용 가능한 일반 설계**라는 의미로 읽어야 한다.

### 7.2 Synthetic benchmark의 유리한 조건

Synthetic dataset에서는 ground-truth motif가 있고, 논문은 `K_M`을 ground-truth size로 설정한다. 실제 문제에서는 explanation subgraph의 적절한 크기를 미리 알기 어렵다. real-world dataset에서는 `K_M = 10`, 모든 dataset에서는 `K_F = 5`를 사용한다.

이 설정은 실험을 명확하게 만들지만, 실전에서는 explanation size 선택 자체가 중요한 hyperparameter가 된다.

### 7.3 ATT baseline 비교의 해석

GRAD와 GNNExplainer는 같은 GNN의 prediction을 설명한다. 반면 ATT baseline은 GAT architecture를 별도로 학습한 뒤 edge attention weight를 explanation proxy로 사용한다. 따라서 ATT와의 비교는 "같은 모델을 설명하는 두 방법"의 완전한 apples-to-apples 비교라기보다, 당시 가능한 attention 기반 해석 proxy와의 비교로 읽는 것이 안전하다.

### 7.4 최적화 보장

GNNExplainer는 mean-field relaxation과 mask regularization을 사용하지만, neural network의 비선형성 때문에 전역 최적 보장을 제공하지 않는다. 논문도 convexity assumption이 실제로는 성립하지 않는다고 설명한다. 따라서 결과는 initialization, regularization, thresholding, computation graph 크기에 영향을 받을 수 있다.

### 7.5 Causal explanation이 아니다

가장 중요한 주의점은 causal claim이다. GNNExplainer가 찾는 것은 "GNN prediction을 유지하는 subgraph와 feature"다. 이것이 실제 세계의 원인이라는 뜻은 아니다. causal explanation을 주장하려면 intervention, counterfactual perturbation, stability check 등 추가 검증이 필요하다.

---

## 8. 재현성과 구현 관찰

공식 저장소 `RexYing/gnn-model-explainer`는 2026-07-09 확인 기준, 논문 source code라고 명시하고, 재현에 필요한 주요 실행 경로를 제공한다.

| 항목 | 내용 | 실무 해석 |
| --- | --- | --- |
| 공식 코드 | `https://github.com/RexYing/gnn-model-explainer` | 논문 재현의 1차 출발점 |
| 실행 흐름 | `python train.py --dataset=...`, `python explainer_main.py --dataset=...` | GNN 학습 후 explainer 실행 |
| 시각화 | TensorBoard, Jupyter Notebook, d3.js export | explanation subgraph와 mask를 확인 가능 |
| 의존성 | Python 3.7 및 PyTorch 1.x 계열 문서/requirements가 혼재 | 현재 환경에서는 dependency drift 가능 |
| 데이터 | 일부 benchmark는 수동 다운로드 필요 | 완전한 one-command 재현은 아닐 수 있음 |
| 유지보수 신호 | release 없음, README에 일부 미완성 안내 존재 | production package보다 research code로 접근하는 것이 안전 |

재현을 목표로 한다면 최신 PyTorch/PyG 환경에 바로 옮기기보다, 논문 당시 의존성에 가까운 환경 또는 container를 먼저 구성하는 편이 안전하다. 이후 최신 graph learning stack에 porting하면서 결과가 유지되는지 확인하는 방식이 좋다.

---

## 9. 결론

GNNExplainer의 가장 큰 기여는 GNN explanation의 산출물을 분명히 정의했다는 점이다. 설명은 단순한 scalar importance가 아니라, **예측을 유지하는 compact subgraph와 feature mask**다. 이 정의 덕분에 GNN 설명가능성 연구는 다음 질문으로 발전할 수 있었다.

- 더 빠르게 explanation을 만들 수 있는가?
- unseen graph에도 inductive하게 explanation을 만들 수 있는가?
- instance-level explanation을 model-level 또는 class-level pattern으로 올릴 수 있는가?
- explanation은 counterfactual하게 검증되는가?
- explanation은 perturbation에 안정적인가?
- prediction-preserving explanation과 causal explanation을 어떻게 구분할 것인가?

이 논문을 읽을 때는 결론을 과장하지 않는 것이 중요하다. GNNExplainer는 모든 그래프 도메인에서 causal truth를 알려주는 방법이 아니다. 대신 훈련된 GNN이 특정 prediction을 만들 때 어떤 구조와 feature에 의존했는지를 열어보는 강력한 첫 도구다.

따라서 GNNExplainer의 가치는 여전히 크다. 최신 GNN XAI 논문을 읽을 때도, 다음 네 질문은 상당수가 GNNExplainer가 정식화한 질문과 맞닿아 있다.

> 이 explainer는 어떤 subgraph와 feature를 설명 대상으로 삼는가?  
> 그 설명은 모델 예측에 faithful한가, 아니면 사람이 보기 좋은 이야기인가?  
> explanation size, baseline, perturbation, domain prior가 결과를 얼마나 좌우하는가?  
> causal 또는 counterfactual claim을 하려면 어떤 추가 검증이 필요한가?

이 네 질문을 남겼다는 점에서 GNNExplainer는 GNN 설명가능성의 대표적 기준점으로 아직도 읽을 가치가 있다.

---

## References

Ying, R., Bourgeois, D., You, J., Zitnik, M., & Leskovec, J. (2019). *GNNExplainer: Generating Explanations for Graph Neural Networks*. Advances in Neural Information Processing Systems 32. arXiv:1903.03894. https://arxiv.org/abs/1903.03894 ([PDF 보기](/paper-viewer?title=GNNExplainer%3A+Generating+Explanations+for+Graph+Neural+Networks&arxiv_id=1903.03894&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1903.03894.pdf&year=2019&authors=Rex+Ying%3BDylan+Bourgeois%3BJiaxuan+You%3BMarinka+Zitnik%3BJure+Leskovec))

Veličković, P., Cucurull, G., Casanova, A., Romero, A., Liò, P., & Bengio, Y. (2018). *Graph Attention Networks*. ICLR. arXiv:1710.10903. https://arxiv.org/abs/1710.10903 ([PDF 보기](/paper-viewer?title=Graph+Attention+Networks&arxiv_id=1710.10903&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1710.10903v3.pdf&year=2018&authors=Petar+Veli%C4%8Dkovi%C4%87%3BGuillem+Cucurull%3BArantxa+Casanova%3BAdriana+Romero%3BPietro+Li%C3%B2%3BYoshua+Bengio))

Luo, D., Cheng, W., Xu, D., Yu, W., Zong, B., Chen, H., & Zhang, X. (2020). *Parameterized Explainer for Graph Neural Network*. arXiv:2011.04573. https://arxiv.org/abs/2011.04573 ([PDF 보기](/paper-viewer?title=Parameterized+Explainer+for+Graph+Neural+Network&arxiv_id=2011.04573&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2011.04573v1.pdf&year=2020&authors=Dongsheng+Luo%3BWei+Cheng%3BDongkuan+Xu%3BWenchao+Yu%3BBo+Zong%3BHaifeng+Chen%3BXiang+Zhang))

Yuan, H., Tang, J., Hu, X., & Ji, S. (2020). *XGNN: Towards Model-Level Explanations of Graph Neural Networks*. arXiv:2006.02587. https://arxiv.org/abs/2006.02587 ([PDF 보기](/paper-viewer?title=XGNN%3A+Towards+Model-Level+Explanations+of+Graph+Neural+Networks&arxiv_id=2006.02587&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2006.02587v1.pdf&year=2020&authors=Hao+Yuan%3BJiliang+Tang%3BXia+Hu%3BShuiwang+Ji))

Lucic, A., ter Hoeve, M. A., Tolomei, G., de Rijke, M., & Silvestri, F. (2022). *CF-GNNExplainer: Counterfactual Explanations for Graph Neural Networks*. AISTATS. arXiv:2102.03322. https://arxiv.org/abs/2102.03322 ([PDF 보기](/paper-viewer?title=CF-GNNExplainer%3A+Counterfactual+Explanations+for+Graph+Neural+Networks&arxiv_id=2102.03322&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2102.03322v4.pdf&year=2021&authors=Ana+Lucic%3BMaartje+A.+ter+Hoeve%3BGabriele+Tolomei%3BMaarten+de+Rijke%3BFabrizio+Silvestri))
