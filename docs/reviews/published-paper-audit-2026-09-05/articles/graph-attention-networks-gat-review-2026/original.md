# GAT 심층 분석: "Graph Attention Networks" 논문 해설

**Paper:** Veličković, Petar; Cucurull, Guillem; Casanova, Arantxa; Romero, Adriana; Liò, Pietro; Bengio, Yoshua. (2018). "Graph Attention Networks." *International Conference on Learning Representations (ICLR 2018)*, arXiv:1710.10903. Code: https://github.com/PetarV-/GAT

**GAT**는 GNN의 이웃 집계 가중치를 구조 기반 고정값 대신 노드 feature 쌍으로부터 학습하는 masked self-attention 층으로 계산하는 그래프 신경망이다(Veličković et al., ICLR 2018). 고유값분해 없이 GCN급 복잡도 O(VFF'+EF')를 유지하면서 inductive 설정에 바로 적용되며, PPI micro-F1 0.973으로 당시 최고를 달성했다.

**Abstract:** 본 문서는 이웃 집계에 attention을 도입한 GAT(Graph Attention Networks) 논문을 해설한다. 논문의 제안은 이웃별 가중치를 그래프 구조(차수 기반 정규화)에서 가져오는 대신, 노드 feature 쌍으로부터 학습된 함수로 계산하는 masked self-attention 층이다. 고유값분해 같은 무거운 행렬 연산 없이 GCN과 같은 복잡도를 유지하면서, 같은 이웃 안의 노드들에 서로 다른 중요도를 부여하고, 전체 그래프 구조를 미리 알 필요가 없어 inductive 설정에 바로 적용된다. 네 벤치마크(Cora, Citeseer, Pubmed, PPI)에서 당시 최고 수준을 달성하거나 동률을 기록했고, 특히 PPI에서 상수 attention 대조군(Const-GAT) 대비 3.9%p 이득으로 attention 자체의 기여를 분리해 보였다. 다만 해석가능성 주장은 논문 안에서 검증되지 않았고, transductive 결과는 고정 분할 위의 수치이며, attention 형식의 표현력 한계는 이후 연구(GATv2)에서 지적됐다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 이웃 집계의 가중치를 구조 기반 고정값이 아니라 노드 feature로부터 학습하면, 성능·적용 범위에서 무엇이 달라지는가? |
| 핵심 기여 | 이웃쌍별 attention 계수 \(\alpha_{ij}\)를 학습하는 graph attentional layer(Eq 1–4)와 multi-head 안정화(Eq 5–6)를 제안하고, 고유값분해 없이 GCN급 복잡도 \(O(VFF' + EF')\)로 inductive 적용까지 확보한다. |
| 방법적 결과 | \(\vec h'_i = \sigma\big(\sum_{j\in\mathcal N_i} \alpha_{ij} \mathbf W \vec h_j\big)\), \(\alpha_{ij}\)는 LeakyReLU 단층 attention의 softmax(Eq 3). |
| 실험 결과 | 저자 보고 기준(각 100 runs) Cora 83.0±0.7, Citeseer 72.5±0.7, Pubmed 79.0±0.3, PPI micro-F1 0.973±0.002(10 runs). PPI에서 Const-GAT(0.934) 대비 +3.9%p(Table 2·3). |
| 핵심 한계 | 해석가능성은 전망 수준으로만 제시(future work). sparse 구현의 batch 제약과 receptive field 깊이 상한은 논문 스스로 명시. attention 형식의 표현력은 이후 GATv2가 재검토했다. |

**TL;DR** — (1) GAT는 이웃 노드별 attention 계수를 feature 쌍으로부터 학습해 고정 가중 집계를 대체하는 graph attention network다. (2) 저자 보고 기준 Cora 83.0%, Citeseer 72.5%, Pubmed 79.0%, PPI micro-F1 0.973을 달성했으며, 특히 PPI에서 Const-GAT 0.934 대비 3.9%p를 앞섰다. (3) attention 계수의 해석가능성은 future work로만 제시됐고, sparse 구현의 batch 제약과 GATv2에서 지적된 표현력 한계를 함께 고려해야 한다.

## 목차

1. 서론
2. 예비 지식
3. Graph attentional layer
4. Multi-head attention과 설계 비교
5. 실험 설정
6. 실험 결과 및 분석
7. 주의해서 읽을 점
8. 방법적 한계와 확장
9. 결론

---

## 1. 서론

### 1.1 연구 배경

이 논문의 배경에는 두 연구 계열이 있다. 한쪽은 그래프 합성곱의 spectral 계열이다. Bruna et al.(2014)의 Laplacian 고유분해 기반 정의에서 출발해 ChebNet의 다항식 근사를 거쳐 GCN의 1-hop 단순화까지 이어졌는데, 논문이 짚는 공통 한계는 학습된 필터가 Laplacian eigenbasis에, 즉 특정 그래프 구조에 묶인다는 점이다. 특정 구조에서 훈련한 모델을 다른 구조의 그래프에 그대로 적용할 수 없다(§1).

다른 쪽은 시퀀스 모델링의 attention이다. 가변 크기 입력을 다루면서 가장 관련 있는 부분에 집중하는 메커니즘으로, Bahdanau et al.(2015)의 번역 정렬에서 Vaswani et al.(2017)의 self-attention 단독 아키텍처까지 발전했다. 논문은 이 계열에서 영감을 받았다고 밝히고, 노드 쌍에 공유 연산을 적용한다는 점에서 relational networks·VAIN과도 닿아 있다고 적는다(§1).

GAT의 제안은 두 계열의 결합이다. 이웃 집계라는 GNN의 틀은 유지하되, 이웃 각각에 줄 가중치를 노드 feature 쌍으로부터 학습되는 attention 함수로 계산한다. 구조에서 오는 고정 계수(GCN의 차수 기반 정규화)가 feature에서 오는 학습 계수로 바뀐다. GAT의 이 설계 변화가 논문 기여의 중심이다.

### 1.2 핵심 질문

| 질문 | 내용 |
| --- | --- |
| Q1 | 같은 이웃 안의 노드들에 서로 다른 중요도를 학습으로 부여하면 성능이 오르는가? |
| Q2 | 그 attention 층이 고유값분해 없이, 전체 그래프 구조를 미리 알지 못해도 작동할 수 있는가? |
| Q3 | 그 결과 spectral 계열이 갇혀 있던 transductive 제약을 벗어나 inductive 과제(unseen graph)에 적용되는가? |

### 1.3 학술적 위치

논문이 §1에서 내세우는 성질은 세 가지다: (1) node-neighbor 쌍에 걸쳐 병렬화 가능한 효율적 연산, (2) 서로 다른 크기의 이웃을 다루면서 이웃 내 차등 가중, (3) 전체 그래프 구조 불요 — unseen graph 평가를 포함한 inductive 학습에 직접 적용.

이 위키의 흐름에서 보면 GAT는 GCN(고정 가중 평균)과 GraphSAGE(샘플링 + 고정 aggregator)가 남긴 선택지의 나머지 한 칸을 채운다. 샘플링 대신 전체 이웃을 쓰고, 고정 함수 대신 가중치를 학습한다. 이후 GIN 논문은 이 attention 가중 집계를 판별력 분석의 범위 밖에 두었는데(blog/gin 5.2절), 그 접점은 8.3절에서 다룬다.

---

## 2. 예비 지식

**Spectral과 non-spectral.** 그래프 위 합성곱의 일반화는 두 갈래로 나뉜다(§1). spectral 계열은 그래프 Laplacian의 고유공간에서 필터를 정의한다. 계산이 무겁고 필터가 공간적으로 국소화되지 않는 문제를 ChebNet(Table 2의 Chebyshev)과 GCN(1-hop 제한)이 차례로 완화했지만, eigenbasis가 그래프 구조에 종속된다는 근본 제약은 남는다. non-spectral(spatial) 계열은 이웃 위에서 직접 합성곱을 정의하며, 서로 다른 크기의 이웃을 다루면서 가중치 공유를 유지하는 것이 난제다. 차수별 가중치(Duvenaud et al.), 전이행렬 거듭제곱으로 이웃을 정의하는 DCNN(Atwood & Towsley), 고정 크기 이웃 추출(Niepert et al.), 샘플링과 aggregator의 GraphSAGE, 그리고 통합 프레임인 MoNet이 여기에 속한다(§1).

GAT는 spatial 계열이면서 MoNet의 특수 사례로 재정식화될 수 있다. pseudo-coordinate를 \(u(x,y) = f(x) \Vert f(y)\)(f는 노드의 — 경우에 따라 MLP 변환된 — feature), weight 함수를 \(w_j(u) = \mathrm{softmax}(\mathrm{MLP}(u))\)(softmax는 이웃 전체 위에서)로 두면 MoNet의 patch operator가 GAT와 유사해진다(원논문 §2.2). 차이는 유사도를 무엇으로 계산하느냐에 있다. 기존 MoNet 인스턴스들이 노드의 구조적 속성(사전에 그래프 구조를 안다는 가정)을 쓰는 반면, GAT는 노드 feature를 쓴다.

**표기.** 노드 feature 집합 \(\mathbf h = \{\vec h_1, \dots, \vec h_N\}\), \(\vec h_i \in \mathbb R^F\)를 입력으로 받아 새 feature \(\vec h'_i \in \mathbb R^{F'}\)를 내는 층을 만든다. \(\mathcal N_i\)는 노드 i의 이웃인데, 실험에서는 정확히 i의 1차 이웃에 **i 자신을 포함**한 집합이다(원논문 §2.1).

---

## 3. Graph attentional layer

층 하나는 네 단계로 구성된다(원논문 §2.1).

**1) 공유 선형변환.** 모든 노드에 가중치 행렬 \(\mathbf W \in \mathbb R^{F' \times F}\)를 적용한다. 표현력 확보를 위한 최소 한 개의 학습 변환이다.

**2) attention 계수.** 공유 attention 메커니즘 \(a: \mathbb R^{F'} \times \mathbb R^{F'} \to \mathbb R\)가 "노드 j의 feature가 노드 i에 갖는 중요도"를 계산한다:

$$
e_{ij} = a(\mathbf W \vec h_i, \mathbf W \vec h_j) \tag{Eq 1}
$$

가장 일반적인 형태라면 모든 노드 쌍에 대해 계산할 수 있지만, 그러면 구조 정보를 전부 버리게 된다. 그래서 **masked attention**으로 \(j \in \mathcal N_i\)에 대해서만 계산해 그래프 구조를 주입한다(§2.1).

**3) softmax 정규화.** 노드마다 이웃 간 계수를 비교 가능하게 만든다:

$$
\alpha_{ij} = \mathrm{softmax}_j(e_{ij}) = \frac{\exp(e_{ij})}{\sum_{k\in\mathcal N_i} \exp(e_{ik})} \tag{Eq 2}
$$

실험에서 \(a\)는 가중치 벡터 \(\vec{\mathbf a} \in \mathbb R^{2F'}\)로 매개화된 단층 feedforward 신경망이고, 두 노드의 변환된 feature를 이어 붙인(concat) 뒤 내적하고 LeakyReLU(음수 기울기 0.2)를 씌운다(Eq 3). Bahdanau et al.(2015)의 방식을 따른 선택이며(내적 대신 덧셈형 결합을 쓴다는 뜻에서 흔히 additive 계열로 불린다 — 논문 외 통칭), 프레임워크 자체는 attention 형식에 무관하다고 논문은 명시한다(§2.1). 이 언급은 7.4절의 GATv2 논의와 이어진다.

**4) 가중 집계.** 정규화된 계수로 이웃 feature의 선형결합을 만든다:

$$
\vec h'_i = \sigma\Big(\sum_{j\in\mathcal N_i} \alpha_{ij} \mathbf W \vec h_j\Big) \tag{Eq 4}
$$

GCN과 나란히 놓으면 차이가 선명하다. GCN의 집계 계수는 \(1/\sqrt{d_i d_j}\)처럼 구조(차수)에서 결정되는 상수지만(이 식은 Kipf & Welling(2017)의 것으로, GAT 논문에 명시된 식은 아니다), GAT의 \(\alpha_{ij}\)는 feature 내용으로부터 매 층 계산되는 학습값이다. 논문이 "같은 이웃 내 노드들에 (implicitly) 다른 중요도를 부여한다"고 쓸 때의 implicitly는, 가중치를 명시적 규칙으로 지정하는 게 아니라 학습된 함수가 데이터 의존적으로 산출한다는 뜻으로 읽힌다(§2.2; 이 해석은 이 글의 정리다).

![GAT Figure 1: attention mechanism and multi-head](/api/blog/figures/gat-fig1-attention.png)
*그림 1. 왼쪽: \(\vec{\mathbf a} \in \mathbb R^{2F'}\)와 LeakyReLU로 구성된 attention 메커니즘. 오른쪽: K=3 head의 multi-head attention — 화살표 스타일이 독립적인 attention 계산을 나타내고, head별 집계 결과가 concat 또는 평균된다. — Veličković et al. (2018), Figure 1에서 연구·학습 목적상 발췌.*

---

## 4. Multi-head attention과 설계 비교

### 4.1 Multi-head: 안정화 장치

self-attention의 학습을 안정화하기 위해 K개의 독립적인 attention을 병렬로 돌리고 결과를 이어 붙인다(§2.1):

$$
\vec h'_i = \Big\Vert_{k=1}^{K} \sigma\Big(\sum_{j\in\mathcal N_i} \alpha^k_{ij} \mathbf W^k \vec h_j\Big) \tag{Eq 5}
$$

중간층 출력은 노드당 \(KF'\) 차원이 된다. 마지막(예측) 층에서는 concat이 더 이상 의미가 없으므로 평균을 쓰고, 최종 비선형(softmax 또는 sigmoid)을 그때까지 미룬다(Eq 6). 도입 동기가 표현력이 아니라 "안정화"라는 점은 기억해 둘 만하다(7.4절).

### 4.2 기존 설계와의 비교 (§2.2)

논문 §2.2는 이 층이 선행 설계들의 문제를 어떻게 피하는지 항목별로 정리한다(\(|V|\)는 노드 수, \(|E|\)는 엣지 수).

| 비교 대상 | 논점 |
| --- | --- |
| spectral 계열 | 고유값분해 등 고비용 행렬 연산 불필요. 단일 head 복잡도 \(O(VFF' + EF')\)로 GCN과 동급. |
| GCN | 같은 이웃 내 차등 가중 → "모델 용량의 도약(a leap in model capacity)"(논문 표현). 학습된 가중치 분석이 해석가능성에 도움이 될 수 있다는 전망. |
| 전역 구조 의존 기법 | attention이 엣지에 공유 적용되므로 전체 구조·전체 노드에 대한 사전 접근 불요. 무향 그래프일 필요도 없고(j→i 엣지가 없으면 \(\alpha_{ij}\) 생략), inductive 적용 가능. |
| GraphSAGE | 고정 크기 이웃 샘플링이 불필요하다. 이웃 전체를 쓰는 대신 가변 계산량을 감수한다. LSTM aggregator가 이웃에 순서를 가정하는 문제도 없다. |
| MoNet | 유사도를 구조적 속성이 아니라 노드 feature로 계산한다(2장의 재정식화 참조). |

같은 절 말미에는 §4가 "practical problems"라고 부르는 제약들도 적혀 있다. sparse 구현이 rank-2 텐서 곱만 지원하는 프레임워크 제약으로 batch 처리가 제한되고(특히 다중 그래프), sparse 연산에서는 GPU가 CPU 대비 큰 이득을 못 줄 수 있으며, receptive field(k층 모델이 볼 수 있는 최대 범위 = k-hop)가 깊이에 상한되고(완화책으로 skip connection 언급), 이웃이 크게 겹치는 그래프에서 엣지 병렬화가 중복 계산을 유발할 수 있다(§2.2). 첫 항목은 §4 결론에서 future work 첫 번째로 다시 등장한다.

---

## 5. 실험 설정

### 5.1 데이터셋 4종 (Table 1)

| Dataset | Task | Nodes | Edges | Features | Classes | Train/Val/Test |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Cora | Transductive | 2,708 | 5,429 | 1,433 | 7 | 140 / 500 / 1,000 |
| Citeseer | Transductive | 3,327 | 4,732 | 3,703 | 6 | 120 / 500 / 1,000 |
| Pubmed | Transductive | 19,717 | 44,338 | 500 | 3 | 60 / 500 / 1,000 |
| PPI | Inductive | 56,944 (24 graphs) | 818,716 | 50 | 121 (multi-label) | 20 / 2 / 2 graphs |

transductive 3종은 Planetoid(Yang et al., 2016)의 고정 분할을 그대로 따르고, 훈련 시 모든 노드의 feature에 접근하되 클래스당 20개 노드의 라벨만 쓴다(§3.1). PPI는 GraphSAGE 논문이 전처리한 데이터로, 테스트 그래프 2개는 훈련 중 완전히 미관측이다(§3.1). 그래프당 평균 노드 수는 2,372개다.

### 5.2 아키텍처와 학습 (§3.3)

- **Transductive**: 2층. 1층은 K=8 head × F′=8(총 64) + ELU(exponential linear unit), 2층은 single head + softmax. L2 정규화 λ=0.0005, dropout 0.6을 층 입력과 **정규화된 attention 계수 양쪽**에 적용한다. 매 iteration 각 노드가 확률적으로 샘플된 이웃에 노출되는 효과다. Pubmed만 출력층 K=8, λ=0.001로 조정. 하이퍼파라미터는 Cora에서 최적화한 뒤 Citeseer에 재사용했다.
- **Inductive(PPI)**: 3층. 1·2층 K=4 × F′=256(총 1024) + ELU, 최종층은 K=6 head가 각각 121차원을 출력해 평균 + logistic sigmoid. 데이터가 충분해 L2·dropout 미적용, 중간 층에 skip connection, batch size 2 graphs.
- 공통: Glorot(Xavier) 초기화, Adam(Pubmed 0.01, 나머지 0.005), early stopping은 validation의 cross-entropy loss와 accuracy(PPI는 micro-F1) 양쪽 기준, patience 100 epochs.

### 5.3 비교 대상과 프로토콜

transductive는 100 runs 평균±표준편차를 보고하고, baseline 수치(DeepWalk, Planetoid, Chebyshev, GCN, MoNet 등)는 Kipf & Welling(2017)과 Monti et al.(2017)의 보고값을 재사용한다(§3.4). 저자들이 직접 돌린 강화 대조군이 둘 있다. **GCN-64\***는 GAT 1층과 폭을 맞춘 64 hidden feature GCN이다. ReLU와 ELU를 둘 다 시도해 좋은 쪽(세 데이터셋 모두 ReLU)을 보고했다. **Const-GAT**는 GAT와 완전히 같은 아키텍처에 상수 attention \(a(x,y)=1\)만 쓴 모델이다. Table 3 캡션이 "GCN-like inductive operator"라고 부르는, attention의 순수 기여를 분리하는 ablation이다. PPI는 10 runs 평균 micro-F1이고, **GraphSAGE\***(0.768)는 저자들이 GraphSAGE 아키텍처를 수정해 얻은 최선이다(3층 GraphSAGE-LSTM, 층별 [512, 512, 726] features, 이웃 집계에 128 features)(§3.4).

---

## 6. 실험 결과 및 분석

### 6.1 Transductive (Table 2, 분류 정확도 %)

| Method | Cora | Citeseer | Pubmed |
| --- | ---: | ---: | ---: |
| MLP | 55.1 | 46.5 | 71.4 |
| ManiReg | 59.5 | 60.1 | 70.7 |
| SemiEmb | 59.0 | 59.6 | 71.7 |
| LP | 68.0 | 45.3 | 63.0 |
| DeepWalk | 67.2 | 43.2 | 65.3 |
| ICA | 75.1 | 69.1 | 73.9 |
| Planetoid | 75.7 | 64.7 | 77.2 |
| Chebyshev | 81.2 | 69.8 | 74.4 |
| GCN | 81.5 | 70.3 | **79.0** |
| MoNet | 81.7±0.5 | — | 78.8±0.3 |
| GCN-64\* | 81.4±0.5 | 70.9±0.5 | **79.0±0.3** |
| **GAT** | **83.0±0.7** | **72.5±0.7** | **79.0±0.3** |

GAT는 Cora 83.0±0.7%, Citeseer 72.5±0.7%, Pubmed 79.0±0.3%를 달성했다.

Cora와 Citeseer에서 GAT가 최고이고, Pubmed에서는 GCN 계열과 79.0으로 동률이다. 논문은 Cora +1.5%, Citeseer +1.6%의 GCN 대비 개선을 "같은 이웃의 노드들에 다른 가중치를 주는 것이 유익할 수 있다"는 근거로 제시한다(§3.4). 이 마진의 기준 모델에는 주의할 점이 있다(7.2절).

### 6.2 Inductive (Table 3, PPI micro-F1)

| Method | PPI |
| --- | ---: |
| Random | 0.396 |
| MLP | 0.422 |
| GraphSAGE-GCN | 0.500 |
| GraphSAGE-mean | 0.598 |
| GraphSAGE-LSTM | 0.612 |
| GraphSAGE-pool | 0.600 |
| GraphSAGE\* | 0.768 |
| Const-GAT | 0.934±0.006 |
| **GAT** | **0.973±0.002** |

GAT는 PPI micro-F1 0.973±0.002를 달성해 Const-GAT 0.934 대비 3.9%p를 앞섰다.

이 표에는 세 겹의 비교가 들어 있다. GraphSAGE 원 논문 최고치(LSTM 0.612) 대비로는 격차가 크지만, 저자들이 강화해 준 GraphSAGE\*(0.768) 대비로도 +20.5%p다. 논문은 이를 "이웃 전체를 관찰함으로써 더 큰 예측력을 끌어낼 수 있다"는 증거로 읽는다(§3.4). 가장 정보량이 많은 것은 마지막 비교다. Const-GAT(0.934)와의 +3.9%p 차이를 논문은 "서로 다른 이웃에 다른 가중치를 부여하는 능력의 유의성을 직접 입증"하는 결과로 제시한다(§3.4).

### 6.3 정성 분석 (Figure 2)

![GAT Figure 2: t-SNE of Cora representations](/api/blog/figures/gat-fig2-tsne.png)
*그림 2. Cora에 사전학습된 GAT 1층 표현의 t-SNE 투영. 색은 7개 클래스, 엣지 두께는 8개 head에 걸쳐 합산한 정규화 attention 계수(\(\sum_k \alpha^k_{ij} + \alpha^k_{ji}\); 논문 본문 §3.4의 표현은 "averaged"로, 캡션 수식과 서로 어긋난다)다. — Veličković et al. (2018), Figure 2에서 연구·학습 목적상 발췌.*

1층 표현이 7개 클래스로 구분되는 클러스터를 이룬다는 정성 확인이다. attention 계수의 강도도 엣지 두께로 시각화했지만, 논문은 이 계수를 제대로 해석하려면 데이터셋에 대한 도메인 지식이 필요하다며 future work로 남긴다(§3.4). 해석가능성 주장의 실제 검증 수위가 여기까지라는 점은 7.3절에서 다룬다.

---

## 7. 주의해서 읽을 점

### 7.1 고정 분할과 시드 분산

transductive 결과는 Planetoid 고정 분할 하나 위의 수치다. 100 runs의 ±는 초기화·dropout 등 시드에 대한 분산일 뿐, 데이터 분할에 대한 분산이 아니다. 분할을 다시 뽑으면 이 규모의 마진(1~2%p)에서 순위가 흔들릴 수 있다는 지적은 이후 GNN 벤치마킹 문헌에서 반복됐다(논문 외 지식). baseline 다수가 타 논문 수치의 재사용이라는 점도 같은 맥락이다. 다만 GCN-64\*를 직접 100 runs로 재실행해 폭을 맞춘 것은 공정성을 높인 설계다.

### 7.2 Citeseer "+1.6%"의 기준 모델

논문 본문은 "GCN 대비 Cora 1.5%, Citeseer 1.6% 개선"이라고 쓴다(§3.4). Cora는 83.0−81.5=1.5로 맞지만, Citeseer는 GCN(70.3) 대비면 2.2이고 GCN-64\*(70.9) 대비여야 1.6이 나온다. 논문 내부의 사소한 불일치로, 이 마진은 기준에 따라 1.6%p와 2.2%p로 달라진다. 그리고 Pubmed에서는 개선이 없다(79.0 동률). transductive 3종 중 attention의 이득이 관측된 것은 2종이다.

### 7.3 해석가능성: 주장과 검증의 거리

§2.2는 학습된 attention 가중치의 분석이 해석가능성에 "도움이 될 수 있다(may lead to)"고 전망하지만, 논문 안의 검증은 Figure 2의 시각화가 전부이고 계수 해석 자체는 future work로 남았다(§3.4, §4). attention 계수를 곧 설명으로 읽어도 되는지는 이후 NLP 쪽에서 독립적인 논쟁("attention is not explanation" 계열)이 있었던 주제이기도 하다(논문 외 지식). GAT를 인용하며 "해석 가능한 GNN"이라고 쓰는 것은 논문이 실제로 보인 것보다 앞서 나간 서술이다.

### 7.4 Attention 형식의 표현력 (논문 외 비판)

Eq 3의 attention은 \(\vec{\mathbf a}^\top[\mathbf W\vec h_i \Vert \mathbf W\vec h_j]\)에 LeakyReLU를 씌운 구조라, 이후 연구(Brody et al., 2022, GATv2)는 이웃들의 점수 순위가 query 노드 i와 사실상 무관하게 정해지는 "static attention"이라고 분석하고 연산 순서를 바꾼 GATv2를 제안했다. 논문 스스로 "프레임워크는 attention 선택에 무관"이라고 적어 둔 부분(§2.1)을 후속 연구가 실제로 손본 것이다. 다만 과제에 따라 원 GAT가 GATv2보다 나은 경우도 보고되므로, 결함 있는 모델이라는 단정으로 읽을 일은 아니다. multi-head도 도입 명분이 안정화였고 head 간 역할 분화는 분석되지 않았다. K개의 독립 계산을 마지막에 concat 또는 평균하는 구조여서 K개 모델의 앙상블에 가깝다고 볼 수도 있다(이 글의 해석).

### 7.5 전체 이웃 사용의 비용 (논문 외 해석)

샘플링을 버리고 이웃 전체를 쓰는 선택은 PPI 성능의 근거이자 비용의 원천이다. 계산량이 노드 차수에 따라 가변적이고(논문도 "가변 계산 footprint 감수"를 명시, §2.2), sparse 구현 전의 저장은 노드 쌍 규모였다고 역산할 수 있다(§2.2의 "저장 복잡도를 선형으로 낮췄다"는 서술에서 나온 추론이다). hub가 많은 대규모 그래프에서 이 설계의 함의는 8.3절에서 GraphSAGE와 묶어 본다.

---

## 8. 방법적 한계와 확장

### 8.1 논문이 명시한 한계·제약

| 한계·제약 | 키워드 | 출처 | 상세 |
| --- | --- | --- | --- |
| Batch 제한 | sparse rank-2 텐서 제약, 다중 그래프; future work 1순위 | §2.2, §4 | 4.2절 |
| GPU 병목 | sparse 연산, 엣지 병렬화의 중복 계산 | §2.2 | 4.2절 |
| Receptive field | 깊이 상한; skip connection은 제안 수준 | §2.2 | 4.2절 |
| 해석가능성 | 계수 해석은 future work | §3.4, §4 | 7.3절 |
| 확장 미탐구 | graph classification, edge feature | §4 | — |

### 8.2 이후 연구 계보 (논문 외 지식)

- **표준 baseline화**: GAT는 GCN·GraphSAGE와 함께 GNN 실험의 관례적 baseline이 됐고, 주요 라이브러리(PyTorch Geometric, DGL)에 기본 층으로 구현돼 있다.
- **GATv2**: Brody et al.(2022)이 static attention 분석과 함께 dynamic attention 변형을 제안했다(7.4절).
- **Transformer와의 수렴**: GAT의 masked self-attention은 "Transformer attention을 그래프 인접성으로 마스킹한 것"으로 자주 재서술된다. 이후 Graph Transformer 계열은 반대로 마스크를 걷고 전역 attention에 구조 정보를 인코딩으로 주입하는 방향으로 갔다. 논문 §2.1이 이미 "가장 일반적 형태에서는 모든 노드가 모든 노드에 attend할 수 있다"고 적어 둔 문장이 이 수렴 논의에서 회고적으로 주목받는다.

### 8.3 이 위키의 세 논문과의 자리 (논문 외 해석)

GraphSAGE, GIN, GAT는 이웃 집계의 서로 다른 축을 하나씩 맡는다. GraphSAGE는 "무엇을 집계하나"(전체 vs 샘플), GAT는 "어떻게 가중하나"(고정 vs 학습), GIN은 "그 집계가 무엇을 구별할 수 있나"(판별력)를 물었다. 전체 이웃과 샘플링의 trade-off에서 GAT와 GraphSAGE는 정확히 반대 선택을 했고, hub가 많은 대규모 그래프에서는 GAT의 선택이 그대로 통하지 않는다.

GIN의 틀에서 보면 GAT의 집계는 softmax로 계수 합이 1이 되는 가중 평균 계열이라, mean처럼 multiset의 중복도 정보를 잃는 쪽에 가깝다. 다만 가중치가 feature로부터 학습되므로 고정 mean과 판별력이 같다고 단정할 수는 없고, GIN 논문 자체가 attention 집계를 미분석으로 남겼다(blog/gin 5.2절). 세 논문을 나란히 읽으면 판별력 기준의 서열과 벤치마크 성능의 서열이 서로 다른 질문임이 보인다.

---

## 9. 결론

GAT는 이웃 집계의 가중치를 구조에서 feature로, 고정값에서 학습값으로 옮겼다. 그 하나의 변화로 spectral 계열의 구조 종속을 벗어나고(inductive), GCN급 복잡도를 유지하면서, 이웃 내 차등 가중이라는 표현 요소를 얻었다. Const-GAT ablation은 그 이득이 아키텍처가 아니라 attention 자체에서 온다는 것을 분리해 보였다.

이 논문을 읽을 때 잡아야 할 균형은 이렇다.

| 기여 | 읽는 법 |
| --- | --- |
| 학습형 이웃 가중 | Const-GAT 대비 +3.9%p(PPI)가 가장 깨끗한 근거다. transductive 마진은 기준 모델과 분할에 주의해 읽어야 한다. |
| Inductive 적용 | 전체 그래프 구조 불요라는 설계 성질에서 나온다. PPI 0.973은 GraphSAGE 계열 대비 큰 폭이지만, 전체 이웃 사용의 비용을 동반한다. |
| 효율성 주장 | 복잡도는 GCN급이 맞지만, sparse 구현의 batch 제약과 GPU 병목을 논문 스스로 명시했다. |
| 해석가능성 | 전망으로 제시됐고 검증은 future work로 남았다. 인용 시 과대 해석하기 쉽다. |

GAT의 지속적인 가치는 "이웃을 어떻게 가중할 것인가"를 학습 문제로 바꾼 데 있다. 구체적 형식(additive 계열, static)은 이후 연구가 고쳤지만, 가중치를 학습한다는 접근 자체는 attention 기반 GNN 연구로 이어졌다.

## References

Atwood, J., & Towsley, D. (2016). Diffusion-convolutional neural networks. *Advances in Neural Information Processing Systems*, *29*. https://arxiv.org/abs/1511.02136 ([PDF 보기](/paper-viewer?title=Diffusion-convolutional+neural+networks&authors=Atwood%2C+James%3BTowsley%2C+Don&year=2016&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1511.02136.pdf&arxiv_id=1511.02136&url=https%3A%2F%2Farxiv.org%2Fabs%2F1511.02136&source=blog-reference))

Bahdanau, D., Cho, K., & Bengio, Y. (2015). Neural machine translation by jointly learning to align and translate. *International Conference on Learning Representations*. https://arxiv.org/abs/1409.0473 ([PDF 보기](/paper-viewer?title=Neural+machine+translation+by+jointly+learning+to+align+and+translate&authors=Bahdanau%2C+Dzmitry%3BCho%2C+Kyunghyun%3BBengio%2C+Yoshua&year=2015&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1409.0473.pdf&arxiv_id=1409.0473&url=https%3A%2F%2Farxiv.org%2Fabs%2F1409.0473&source=blog-reference))

Brody, S., Alon, U., & Yahav, E. (2022). How attentive are graph attention networks? *International Conference on Learning Representations*. https://arxiv.org/abs/2105.14491 ([PDF 보기](/paper-viewer?title=How+attentive+are+graph+attention+networks%3F&authors=Brody%2C+Shaked%3BAlon%2C+Uri%3BYahav%2C+Eran&year=2022&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2105.14491.pdf&arxiv_id=2105.14491&url=https%3A%2F%2Farxiv.org%2Fabs%2F2105.14491&source=blog-reference))

Bruna, J., Zaremba, W., Szlam, A., & LeCun, Y. (2014). Spectral networks and locally connected networks on graphs. *International Conference on Learning Representations*. https://arxiv.org/abs/1312.6203 ([PDF 보기](/paper-viewer?title=Spectral+networks+and+locally+connected+networks+on+graphs&authors=Bruna%2C+Joan%3BZaremba%2C+Wojciech%3BSzlam%2C+Arthur%3BLeCun%2C+Yann&year=2014&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1312.6203.pdf&arxiv_id=1312.6203&url=https%3A%2F%2Farxiv.org%2Fabs%2F1312.6203&source=blog-reference))

Defferrard, M., Bresson, X., & Vandergheynst, P. (2016). Convolutional neural networks on graphs with fast localized spectral filtering. *Advances in Neural Information Processing Systems*, *29*. https://arxiv.org/abs/1606.09375 ([PDF 보기](/paper-viewer?title=Convolutional+neural+networks+on+graphs+with+fast+localized+spectral+filtering&authors=Defferrard%2C+Micha%C3%ABl%3BBresson%2C+Xavier%3BVandergheynst%2C+Pierre&year=2016&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1606.09375.pdf&arxiv_id=1606.09375&url=https%3A%2F%2Farxiv.org%2Fabs%2F1606.09375&source=blog-reference))

Duvenaud, D., Maclaurin, D., Aguilera-Iparraguirre, J., Gómez-Bombarelli, R., Hirzel, T., Aspuru-Guzik, A., & Adams, R. P. (2015). Convolutional networks on graphs for learning molecular fingerprints. *Advances in Neural Information Processing Systems*, *28*. https://arxiv.org/abs/1509.09292 ([PDF 보기](/paper-viewer?title=Convolutional+networks+on+graphs+for+learning+molecular+fingerprints&authors=Duvenaud%2C+David%3BMaclaurin%2C+Dougal%3BAguilera-Iparraguirre%2C+Jorge%3BG%C3%B3mez-Bombarelli%2C+Rafael%3BHirzel%2C+Timothy%3BAspuru-Guzik%2C+Al%C3%A1n%3BAdams%2C+Ryan+P.&year=2015&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1509.09292.pdf&arxiv_id=1509.09292&url=https%3A%2F%2Farxiv.org%2Fabs%2F1509.09292&source=blog-reference))

Hamilton, W. L., Ying, R., & Leskovec, J. (2017). Inductive representation learning on large graphs. *Advances in Neural Information Processing Systems*, *30*. https://arxiv.org/abs/1706.02216 ([PDF 보기](/paper-viewer?title=Inductive+representation+learning+on+large+graphs&authors=Hamilton%2C+William+L.%3BYing%2C+Rex%3BLeskovec%2C+Jure&year=2017&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1706.02216.pdf&arxiv_id=1706.02216&url=https%3A%2F%2Farxiv.org%2Fabs%2F1706.02216&source=blog-reference))

Kipf, T. N., & Welling, M. (2017). Semi-supervised classification with graph convolutional networks. *International Conference on Learning Representations*. https://arxiv.org/abs/1609.02907 ([PDF 보기](/paper-viewer?title=Semi-supervised+classification+with+graph+convolutional+networks&authors=Kipf%2C+Thomas+N.%3BWelling%2C+Max&year=2017&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1609.02907.pdf&arxiv_id=1609.02907&url=https%3A%2F%2Farxiv.org%2Fabs%2F1609.02907&source=blog-reference))

Monti, F., Boscaini, D., Masci, J., Rodolà, E., Svoboda, J., & Bronstein, M. M. (2017). Geometric deep learning on graphs and manifolds using mixture model CNNs. *Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition*, 5425–5434. https://doi.org/10.1109/CVPR.2017.576 ([PDF 보기](/paper-viewer?title=Geometric+deep+learning+on+graphs+and+manifolds+using+mixture+model+CNNs&authors=Monti%2C+Federico%3BBoscaini%2C+Davide%3BMasci%2C+Jonathan%3BRodol%C3%A0%2C+Emanuele%3BSvoboda%2C+Jan%3BBronstein%2C+Michael+M.&year=2017&doi=10.1109%2FCVPR.2017.576&url=https%3A%2F%2Fdoi.org%2F10.1109%2FCVPR.2017.576&source=blog-reference))

Niepert, M., Ahmed, M., & Kutzkov, K. (2016). Learning convolutional neural networks for graphs. *Proceedings of the 33rd International Conference on Machine Learning*, 2014–2023. https://arxiv.org/abs/1605.05273 ([PDF 보기](/paper-viewer?title=Learning+convolutional+neural+networks+for+graphs&authors=Niepert%2C+Mathias%3BAhmed%2C+Mohamed%3BKutzkov%2C+Konstantin&year=2016&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1605.05273.pdf&arxiv_id=1605.05273&url=https%3A%2F%2Farxiv.org%2Fabs%2F1605.05273&source=blog-reference))

Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, Ł., & Polosukhin, I. (2017). Attention is all you need. *Advances in Neural Information Processing Systems*, *30*. https://arxiv.org/abs/1706.03762 ([PDF 보기](/paper-viewer?title=Attention+is+all+you+need&authors=Vaswani%2C+Ashish%3BShazeer%2C+Noam%3BParmar%2C+Niki%3BUszkoreit%2C+Jakob%3BJones%2C+Llion%3BGomez%2C+Aidan+N.%3BKaiser%2C+%C5%81ukasz%3BPolosukhin%2C+Illia&year=2017&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1706.03762.pdf&arxiv_id=1706.03762&url=https%3A%2F%2Farxiv.org%2Fabs%2F1706.03762&source=blog-reference))

Veličković, P., Cucurull, G., Casanova, A., Romero, A., Liò, P., & Bengio, Y. (2018). Graph attention networks. *International Conference on Learning Representations*. https://arxiv.org/abs/1710.10903 ([PDF 보기](/paper-viewer?title=Graph+attention+networks&authors=Veli%C4%8Dkovi%C4%87%2C+Petar%3BCucurull%2C+Guillem%3BCasanova%2C+Arantxa%3BRomero%2C+Adriana%3BLi%C3%B2%2C+Pietro%3BBengio%2C+Yoshua&year=2018&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1710.10903.pdf&arxiv_id=1710.10903&url=https%3A%2F%2Farxiv.org%2Fabs%2F1710.10903&source=blog-reference))

Xu, K., Hu, W., Leskovec, J., & Jegelka, S. (2019). How powerful are graph neural networks? *International Conference on Learning Representations*. https://arxiv.org/abs/1810.00826 ([PDF 보기](/paper-viewer?title=How+powerful+are+graph+neural+networks%3F&authors=Xu%2C+Keyulu%3BHu%2C+Weihua%3BLeskovec%2C+Jure%3BJegelka%2C+Stefanie&year=2019&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1810.00826.pdf&arxiv_id=1810.00826&url=https%3A%2F%2Farxiv.org%2Fabs%2F1810.00826&source=blog-reference))

Yang, Z., Cohen, W. W., & Salakhutdinov, R. (2016). Revisiting semi-supervised learning with graph embeddings. *Proceedings of the 33rd International Conference on Machine Learning*, 40–48. https://arxiv.org/abs/1603.08861 ([PDF 보기](/paper-viewer?title=Revisiting+semi-supervised+learning+with+graph+embeddings&authors=Yang%2C+Zhilin%3BCohen%2C+William+W.%3BSalakhutdinov%2C+Ruslan&year=2016&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1603.08861.pdf&arxiv_id=1603.08861&url=https%3A%2F%2Farxiv.org%2Fabs%2F1603.08861&source=blog-reference))