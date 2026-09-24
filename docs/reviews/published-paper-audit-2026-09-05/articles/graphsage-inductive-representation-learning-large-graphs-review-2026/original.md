# Inductive Representation Learning on Large Graphs

**Paper:** Hamilton, William L.; Ying, Rex; Leskovec, Jure. (2017). "Inductive Representation Learning on Large Graphs." *Advances in Neural Information Processing Systems (NIPS 2017)*, arXiv:1706.02216. DOI: https://doi.org/10.48550/arXiv.1706.02216. Code & data: https://snap.stanford.edu/graphsage/

**GraphSAGE**는 노드별 embedding lookup 대신 이웃 feature를 고정 크기로 샘플링해 aggregator 함수로 집계하는 것을 학습하는 inductive 그래프 표현 학습 프레임워크다(Hamilton et al., NeurIPS 2017). 훈련 시 보지 못한 노드와 그래프에도 재학습 없이 적용되며, feature 단독 대비 micro-F1을 평균 51% 개선했다.

**Abstract:** 본 문서는 inductive node embedding의 표준 참조점이 된 GraphSAGE 논문을 해설한다. 논문의 핵심은 노드마다 embedding 벡터를 직접 최적화하는 대신, 이웃의 feature를 샘플링하고 집계하는 **aggregator 함수**를 학습하는 것이다. 학습된 함수는 같은 형태의 node feature와 관측 가능한 이웃 정보가 있을 때, 훈련 때 보지 못한 노드와 그래프에도 적용될 수 있다. Citation과 Reddit에서는 DeepWalk 계열 transductive baseline을, PPI에서는 feature/random baseline을 웃도는 micro-F1을 보고했다. 다만 uniform sampling에 따른 embedding 비결정성, feature 기반 과제 위주의 평가, pooling aggregator에 한정된 존재 증명(Theorem 1)을 함께 읽어야 한다.


---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 훈련 시 존재하지 않던 노드(또는 완전히 새로운 그래프)의 embedding을 재학습 없이 생성할 수 있는가? |
| 핵심 기여 | 노드별 embedding look-up 대신, 이웃 feature를 고정 크기로 샘플링해 집계하는 aggregator 함수 집합을 학습하는 프레임워크를 제안한다. |
| 방법적 결과 | 각 depth k에서 \(h^k_v \leftarrow \sigma(W^k\cdot\mathrm{CONCAT}(h^{k-1}_v, \mathrm{AGG}_k(\{h^{k-1}_u\})))\)를 수행하고, 이웃은 매 iteration 고정 크기 uniform sample로 대체해 배치당 복잡도를 \(O(\prod_i S_i)\)로 고정한다. |
| 실험 결과 | 저자 보고 기준 supervised GraphSAGE는 feature 단독 대비 micro-F1을 평균 51% 개선했고, 학습형 aggregator는 GCN 유래 aggregator 대비 평균 7.4% 이득을 보였다(§1). |
| 핵심 한계 | uniform sampling과 K-hop 이웃 폭발은 논문 스스로 future work로 남겼다. Theorem 1은 학습 보장이 아닌 존재 증명이며 pooling aggregator에 의존한다. |

**TL;DR** — (1) GraphSAGE는 이웃 feature를 고정 크기로 샘플링해 aggregator 함수 집합을 학습함으로써 훈련 중 보지 못한 노드의 embedding을 재학습 없이 생성하는 inductive 프레임워크다. (2) 저자 보고 기준 supervised GraphSAGE-pool은 Citation micro-F1 0.839, Reddit 0.948을 기록하며, feature 단독 대비 평균 51% 개선을 달성했다. (3) uniform sampling으로 인한 embedding 비결정성과 K-hop 이웃 폭발은 논문 스스로 future work로 남겼으며, Theorem 1은 학습 보장이 아닌 존재 증명이다.

## 목차

1. 서론
2. 예비 지식
3. 방법적 프레임워크
4. 이웃 샘플링과 aggregator
5. 학습: unsupervised loss와 supervised 변형
6. 실험 결과 및 분석
7. Theorem 1 읽기
8. 주의해서 읽을 점
9. 방법적 한계와 확장
10. 결론

---

## 1. 서론

### 1.1 연구 배경

이 논문이 다루는 문제는 **inductive node embedding**이다. DeepWalk, node2vec 같은 당시의 대표적 node embedding 방법은 matrix-factorization 계열 목적함수로 각 노드의 embedding 벡터를 직접 최적화한다. 이 방식은 "단일 고정 그래프 위의 노드"에 대해서만 예측하는 본질적으로 transductive한 구조다(§1, §2). 새 노드가 들어오면 최소한 추가 SGD 라운드가 필요하고, 목적함수가 embedding의 직교변환에 불변이기 때문에 서로 다른 그래프(또는 재학습 전후)에서 학습된 embedding 공간은 서로 임의로 회전되어 정렬되지 않는다(§2, Appendix D).

현실 시스템은 이 설정과 맞지 않는다. 논문이 드는 동기 사례는 Reddit 게시글, YouTube의 사용자·비디오처럼 unseen 노드가 끊임없이 유입되는 진화하는 그래프다(§1). unseen 노드로 일반화하려면 새로 관측된 부분그래프를 이미 최적화된 embedding에 "정렬(aligning)"해야 하고, 노드의 지역적 역할과 전역적 위치를 함께 드러내는 이웃의 구조적 성질을 인식하도록 학습해야 한다(§1).

GraphSAGE(**SA**mple and aggre**G**at**E**)는 노드별 embedding 벡터가 아니라 함수를 학습한다. 노드의 지역 이웃에서 feature(텍스트 속성, 프로필 정보, node degree 등)를 샘플링해 집계하는 aggregator 함수 집합을 학습하고, 추론 시에는 이 함수를 새 노드에 그대로 적용해 embedding을 만든다(§1, Figure 1).

![GraphSAGE sample-and-aggregate pipeline](/api/blog/figures/graphsage-sample-aggregate-paperbanana-v2.png)
*그림 1. GraphSAGE의 sample-and-aggregate 절차를 에이전트 팀 심층 검토 결과에 맞춰 Paper Banana 스타일로 재생성한 블로그용 도식. 고정 크기 K-hop 이웃 샘플링, neighbor feature aggregation, embedding \(z_v\) 기반 label/context 예측의 세 단계를 요약한다. 원논문 Hamilton et al. (2017), Figure 1의 설명 흐름을 바탕으로 재작성했다.*

### 1.2 핵심 질문

| 질문 | 내용 |
| --- | --- |
| Q1 | 노드별 embedding 최적화 없이, 이웃 feature 집계 함수만으로 유용한 node embedding을 만들 수 있는가? |
| Q2 | 전체 이웃 대신 고정 크기 샘플만 사용해도 예측 성능을 유지하면서 배치당 계산량을 상수로 고정할 수 있는가? |
| Q3 | feature 기반 방법이 노드의 구조적 역할(예: clustering coefficient) 같은 위상 정보도 표현할 수 있는가? |

### 1.3 학술적 위치

논문은 스스로를 "GCN을 inductive unsupervised learning 과제로 확장하는 동시에, 단순 convolution을 넘어 학습 가능한 aggregation 함수로 GCN 접근을 일반화하는 프레임워크"로 규정한다(§1). Kipf & Welling의 GCN은 학습 중 전체 그래프의 Laplacian을 요구하는 transductive 설정에서 제안됐는데(§2), GraphSAGE는 (i) 전체 이웃을 고정 크기 샘플로 대체하고 (ii) aggregator를 mean 외의 학습형 함수로 일반화해 이 두 제약을 제거한다. 실험의 GraphSAGE-GCN 변형이 정확히 "GCN의 inductive 확장판"에 해당한다(§4).

이후 GNN 연구에서 이 논문은 두 흐름을 이해하는 중요한 초기 참조점 중 하나가 됐다. 하나는 이웃 집계 함수의 설계(GAT의 attention, GIN의 표현력 분석), 다른 하나는 샘플링 기반 대규모 GNN 학습(FastGCN, Cluster-GCN, GraphSAINT 등)이다. 이 계보는 9.2절에서 다시 다룬다.

---

## 2. 예비 지식

### 2.1 Transductive vs Inductive

> **Definition 1 (micro-F1).** micro-F1은 클래스 전체의 true positive, false positive, false negative를 합산해 계산하는 F1 평균이다. 이 논문의 Table 1은 node classification 성능을 micro-F1로 보고한다.

- **Transductive** 설정에서는 훈련 시점에 전체 그래프(모든 노드와 구조)가 주어지고, 그 그래프 안의 노드에 대해서만 예측한다. DeepWalk류 embedding과 원래의 GCN 실험이 여기에 속한다. 새 노드가 오면 재학습(또는 추가 최적화)이 필요하다.
- **Inductive** 설정에서는 훈련 때 보지 못한 노드(unseen 노드), 나아가 완전히 새로운 그래프에 대해 예측해야 한다. 모델이 "이 노드의 embedding"이 아니라 "이웃 정보로부터 embedding을 만드는 규칙"을 학습해야 성립한다.

이 구분이 논문 전체의 기본 틀이다. 논문의 세 실험은 모두 훈련에 쓰이지 않은 노드를 예측하며, PPI에서는 그래프 전체가 훈련에서 빠져 있다(§4).

### 2.2 왜 DeepWalk류는 inductive로 옮기기 어려운가

factorization 기반 목적함수는 embedding 내적 \(z_i^\top z_j\)에만 의존하므로, 임의의 직교행렬로 embedding 전체를 회전해도 loss가 같다(Appendix D, Eq 4–6). 따라서 두 번의 학습이 서로 정렬된 공간을 만들 이유가 없다. 새 노드를 위해 추가 SGD를 돌리면 기존 공간이 drift할 수 있고, 서로 분리된 그래프들 사이에서는 아예 비교가 성립하지 않는다.

논문이 §2에서 inductive 선행으로 언급하는 Planetoid-I는 예외지만, inference 시에는 그래프 구조를 쓰지 않고 훈련 중 정규화로만 활용한다는 점에서 GraphSAGE와 성격이 다르다(§2).

### 2.3 Weisfeiler-Lehman test와의 연결

Algorithm 1에서 (i) \(K=|\mathcal V|\), (ii) 가중치 행렬을 항등으로, (iii) aggregator를 적절한 해시 함수(비선형 없음)로 두면, 알고리즘은 WL isomorphism test("naive vertex refinement")의 인스턴스가 된다(§3.1). GraphSAGE는 이 해시 함수를 학습 가능한 신경망 aggregator로 바꾼, WL test의 연속 근사인 셈이다. 논문은 이 연결을 "이웃의 위상 구조를 학습하는 설계의 이론적 맥락"으로만 제시하며, WL 자체가 일부 그래프에서 실패한다는 점도 명시한다(§3.1).

---

## 3. 방법적 프레임워크

### 3.1 Embedding 생성: Algorithm 1

학습이 끝나 파라미터가 고정된 상태를 가정하고, embedding이 만들어지는 과정을 본다(§3.1). 파라미터는 K개의 aggregator 함수 \(\mathrm{AGGREGATE}_k\)와 K개의 가중치 행렬 \(W^k\)다.

![GraphSAGE original Figure 1: sample and aggregate](/api/blog/figures/graphsage-fig1-sample-aggregate-padded.png)
*그림 2. GraphSAGE 원논문 Figure 1 원본을 블로그 렌더링에서 잘리지 않도록 흰 캔버스에 여백만 추가해 배치한 버전. Algorithm 1의 직관을 이루는 세 단계, 즉 (1) target node 주변의 K-hop 이웃 샘플링, (2) 이웃 feature 정보를 depth별 aggregator로 집계, (3) 집계된 표현으로 graph context와 label을 예측하는 sample-and-aggregate 흐름을 보여준다. — Hamilton et al. (2017), Figure 1에서 연구·리뷰 목적상 발췌; 원문: https://arxiv.org/abs/1706.02216.*

1. **초기화**: \(h^0_v \leftarrow x_v\). depth 0의 표현은 입력 node feature 그 자체다.
2. **depth 루프** \(k = 1 \dots K\): 각 노드 \(v\)에 대해
   - **이웃 집계**: \(h^k_{\mathcal N(v)} \leftarrow \mathrm{AGGREGATE}_k(\{h^{k-1}_u, \forall u \in \mathcal N(v)\})\) — 이웃들의 직전 depth 표현을 하나의 벡터로 모은다.
   - **결합·변환**: \(h^k_v \leftarrow \sigma(W^k \cdot \mathrm{CONCAT}(h^{k-1}_v,\, h^k_{\mathcal N(v)}))\) — 자기 자신의 이전 표현과 이웃 집계 벡터를 연결(concat)한 뒤 선형 변환과 비선형을 통과시킨다.
   - **정규화**: \(h^k_v \leftarrow h^k_v / \lVert h^k_v \rVert_2\) — 매 depth마다 \(\ell_2\) 정규화한다.
3. **출력**: \(z_v \equiv h^K_v\).

K는 search depth이자 층 수다. 반복될수록 노드는 더 먼 hop의 정보를 얻는다. K=2면 최종 표현은 (샘플링된) 2-hop 이웃까지를 반영한다(§3.1). 여기서 \(\mathcal N(v)\)는 전체 이웃이 아니라 고정 크기 uniform 샘플인데, 정확한 정의는 4.1절에서 다룬다.

concat은 설계상 중요한 선택이다. 논문은 이를 서로 다른 depth 사이의 단순한 "skip connection"으로 해석하고, 상당한 성능 이득을 준다고 밝힌다(§3.3). 실제로 concat이 없는 GraphSAGE-GCN 변형은 실험에서 일관되게 뒤처진다(§4.4).

표기에 관한 주의 하나. Algorithm 1의 4행은 집계 결과를 \(h^k_{\mathcal N(v)}\)로 쓰는데, §3.1 본문 산문에서는 같은 것을 \(h^{k-1}_{\mathcal N(v)}\)로 쓰는 곳이 있다. 논문 자체의 표기 비일관이고 의미는 동일하다.

### 3.2 Minibatch 버전: forward sampling

Algorithm 1은 모든 노드를 한꺼번에 처리하는 서술이고, 실제 학습은 minibatch로 한다(Appendix A, Algorithm 2). 배치의 target 노드 집합 \(\mathcal B\)에서 시작해, 계산에 필요한 노드만 거꾸로 모으는 방식이다: \(\mathcal B^K = \mathcal B\)로 두고, \(\mathcal B^{k-1}\)은 \(\mathcal B^k\)의 노드와 그 이웃 샘플을 합친 집합으로 확장한다. K=2, depth별 샘플 크기 \(S_1, S_2\)라면 target 노드 하나당 immediate neighbor \(S_2\)개, 2-hop neighbor \(S_1 \cdot S_2\)개를 샘플한다(Appendix A). 샘플 크기가 degree보다 크면 복원추출한다.

---

## 4. 이웃 샘플링과 aggregator

### 4.1 고정 크기 uniform sampling

전체 이웃을 쓰면 배치 하나의 메모리와 실행시간이 예측 불가능해지고 최악의 경우 \(O(|\mathcal V|)\)가 된다. GraphSAGE는 \(\mathcal N(v)\)를 전체 이웃 집합에서의 고정 크기 uniform 샘플로 재정의하고, Algorithm 1의 매 iteration마다 다른 샘플을 새로 뽑는다(§3.1). 이로써 배치당 공간·시간 복잡도가 \(O(\prod_{i=1}^{K} S_i)\)로 고정된다.

실용 설정은 K=2, \(S_1 \cdot S_2 \le 500\)이고(§3.1), 본 실험은 \(S_1=25, S_2=10\)을 쓴다(§4). 비균일(non-uniform) 샘플러의 탐색은 논문이 명시적으로 future work로 남겼다(§3.1 각주, §6).

### 4.2 Aggregator 4종

이웃에는 자연스러운 순서가 없으므로, aggregator는 순서 없는 벡터 집합 위에서 작동해야 하고, 이상적으로는 대칭(순열 불변)이면서 학습 가능하고 표현력이 높아야 한다(§3.3).

| Aggregator | 정의 | 대칭성 | 비고 |
| --- | --- | --- | --- |
| Mean | 이웃 표현의 원소별 평균 후 concat·변환 | 대칭 | Algorithm 1 구조 그대로 |
| GCN (convolutional) | 자기 표현과 이웃 표현을 함께 평균내는 Eq 2 변형 | 대칭 | concat 없음; transductive GCN의 inductive 변형 |
| LSTM | 이웃 표현 시퀀스에 LSTM 적용 | **비대칭** | 이웃의 무작위 순열에 적용해 우회 |
| Pooling | 이웃별 독립 변환 후 원소별 max-pooling하는 Eq 3 변형 | 대칭 | 학습형 set function에 가까움 |

GCN aggregator와 pooling aggregator의 원논문 표기는 각각 다음과 같다.

$$
h^k_v \leftarrow \sigma\!\left(W\cdot\mathrm{MEAN}(\{h^{k-1}_v\}\cup\{h^{k-1}_u, \forall u\in\mathcal N(v)\})\right)
$$

$$
\mathrm{POOL}(\{h^k_{u_i}\})=\max\left(\{\sigma(W_{pool}h^k_{u_i}+b),\forall u_i\in\mathcal N(v)\}\right)
$$

GCN aggregator는 Algorithm 1의 4·5행을 통째로 Eq 2로 대체한다. 자기 표현을 이웃 집합에 합쳐 함께 평균내므로 concat 단계가 없다. 이것이 "localized spectral convolution의 거친 선형 근사"라는 의미에서 convolutional이라 불리고, Kipf & Welling의 식과는 사소한 정규화 상수만 다르다(§3.3).

LSTM aggregator는 표현력은 높지만 입력을 순차 처리하므로 본질적으로 순열 불변이 아니다. 논문은 이웃의 무작위 순열에 적용하는 것으로 타협한다(§3.3). Pooling aggregator는 각 이웃 벡터를 독립적으로 fully-connected 층에 통과시킨 뒤 원소별 max-pooling한다. max 대신 mean을 써도 개발 단계 테스트에서 유의한 차이가 없어 max로 통일했다(§3.3).

---

## 5. 학습: unsupervised loss와 supervised 변형

### 5.1 Graph-based unsupervised loss

출력 표현 \(z_u\)에 다음 loss를 적용하고, SGD로 \(W^k\)와 aggregator 파라미터를 학습한다(§3.2, Eq 1):

$$
J_{\mathcal G}(z_u) = -\log\!\big(\sigma(z_u^\top z_v)\big) - Q \cdot \mathbb E_{v_n \sim P_n(v)} \log\!\big(\sigma(-z_u^\top z_{v_n})\big)
$$

- \(v\)는 고정 길이 random walk에서 \(u\) 근처에 동시 등장하는 노드(positive), \(\sigma\)는 sigmoid, \(P_n\)은 negative sampling 분포, \(Q\)는 negative sample 수다(§3.2).
- 구현 세부(Appendix C): 노드당 길이 5의 random walk 50개로 positive 쌍을 만들고, negative sample 20개, degree에 smoothing parameter 0.75를 적용한 분포를 쓴다.

형태는 DeepWalk류의 목적함수(word2vec의 skip-gram과 같은 구조의 negative sampling loss)와 같지만, 결정적 차이는 \(z_u\)가 embedding look-up이 아니라 이웃 feature로부터 생성된다는 점이다(§3.2). 학습되는 것은 노드별 벡터가 아니라 생성 규칙이므로, 학습이 끝나면 unseen 노드에도 같은 규칙이 적용된다.

unsupervised embedding의 평가 프로토콜에도 주의할 점이 있다(Appendix C). Table 1의 "Unsup. F1"은 학습된 embedding을 scikit-learn의 logistic SGDClassifier(기본 설정)에 넣어 얻은 분류 성능이다. 이 분류기는 훈련 노드에서만 학습되고 테스트 embedding에 fine-tune되지 않는다. 즉 unsupervised 열은 "고정된 선형 분류기를 통과한" 성능이다.

### 5.2 Supervised 변형

표현을 특정 task에만 쓸 경우 Eq 1을 task별 목적함수(예: cross-entropy)로 대체하거나 증강할 수 있다(§3.2). 실험에서는 분류 loss로 끝까지 학습한 supervised 변형을 unsupervised와 나란히 평가한다. 공통 설정: ReLU, 모든 depth에서 표현 차원 256, batch size 512, TensorFlow + Adam(§4, Appendix C).

---

## 6. 실험 결과 및 분석

### 6.1 세 개의 inductive 벤치마크

| Dataset | 구성 | 규모 | Task | Inductive 분할 |
| --- | --- | --- | ---| --- |
| Citation (WoS) | 2000–2005 biology 6분야 undirected citation graph | 302,424 nodes, avg degree 9.15 | 논문 주제 분야 분류(6-class) | 2000–2004 학습 → 2005 테스트(30% validation) |
| Reddit | 2014년 9월 post-to-post 그래프(같은 사용자가 두 글에 댓글 시 연결), 댓글 수 순위 11–50위 커뮤니티 50개 | 232,965 nodes, avg degree 492 | 게시글의 커뮤니티 예측 | 앞 20일 학습 → 나머지 테스트(30% validation) |
| PPI | 조직(tissue)별 protein-protein interaction multi-graph | 그래프당 평균 2,373 nodes, avg degree 28.8 | protein 기능 multi-label 분류(121 labels) | 20개 그래프 학습 → 2 validation + 2 test **미관측 그래프** |

feature는 citation이 node degree와 abstract의 문장 embedding(300차원 word2vec 벡터에 Arora et al. 방식 적용), Reddit이 300차원 GloVe 기반 텍스트 embedding(제목·댓글 평균)과 점수·댓글 수, PPI가 positional gene sets·motif gene sets·immunological signatures다(§4.1, §4.2). 셋 모두 훈련에 없던 노드를 예측 대상으로 하고, PPI는 그래프 자체가 unseen이라 가장 강한 형태의 inductive 검증이다(§4).

### 6.2 주요 성능 (Table 1, micro-F1)

| Method | Cite Unsup. | Cite Sup. | Reddit Unsup. | Reddit Sup. | PPI Unsup. | PPI Sup. |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Random | 0.206 | 0.206 | 0.043 | 0.042 | 0.396 | 0.396 |
| Raw features | 0.575 | 0.575 | 0.585 | 0.585 | 0.422 | 0.422 |
| DeepWalk | 0.565 | 0.565 | 0.324 | 0.324 | — | — |
| DeepWalk + features | 0.701 | 0.701 | 0.691 | 0.691 | — | — |
| GraphSAGE-GCN | 0.742 | 0.772 | **0.908** | 0.930 | 0.465 | 0.500 |
| GraphSAGE-mean | 0.778 | 0.820 | 0.897 | 0.950 | 0.486 | 0.598 |
| GraphSAGE-LSTM | 0.788 | 0.832 | 0.907 | **0.954** | 0.482 | **0.612** |
| GraphSAGE-pool | **0.798** | **0.839** | 0.892 | 0.948 | **0.502** | 0.600 |
| % gain over feat. | 39% | 46% | 55% | 63% | 19% | 45% |

GraphSAGE-pool은 Citation 지도학습 micro-F1 0.839, Reddit 지도학습 0.948을 기록했고, GraphSAGE-LSTM은 PPI 지도학습 0.612로 최고를 보였다.

저자 보고 기준으로 GraphSAGE 변형들은 모든 setting에서 baseline을 웃돈다. unsupervised GraphSAGE-pool은 DeepWalk+features 대비 citation에서 13.8%, Reddit에서 29.1% 이득이고, supervised는 각각 19.7%, 37.2%다(§4.1). PPI에서 DeepWalk 열이 비어 있는 것은 2.2절에서 본 직교불변성 문제로 분리된 그래프 간 적용이 불가능해서다(§4, Appendix D).

DeepWalk가 citation(0.565)에서는 raw features에 근접하지만 Reddit(0.324)에서 크게 무너지는 데는 논문이 제시한 데이터 쪽 설명이 있다. 2005년 인용 링크의 96%가 2000–2004 훈련 그래프로 연결되는 반면, Reddit 테스트 엣지는 73%만 훈련 그래프로 연결되어 statistical drift가 더 심하다(Appendix D).

여섯 setting에서 최고 변형은 갈린다: pool이 3개(Citation 둘 다, PPI Unsup.), LSTM이 2개(Reddit Sup., PPI Sup.), GCN이 1개(Reddit Unsup., 0.908로 LSTM 0.907과 근소 차)다. 어느 aggregator가 최고인지는 데이터셋에 따라 다르다.

### 6.3 Aggregator 비교와 통계 검정

이 비교는 설계 통제가 비교적 엄격하다(§4). 모든 모델이 동일한 minibatch iterator·loss·neighborhood sampler 구현을 공유하고, GraphSAGE 변형 간에는 동일한 hyperparameter 집합을 sweep해 validation 성능으로 각 변형의 최적 설정을 골랐다. hyperparameter 후보 자체는 이후 분석에서 제외한 별도 데이터 부분집합에서 정해 "hyperparameter hacking"을 차단했다.

논문은 6개 setting(3 datasets × unsup/sup)을 시행으로 보고 Wilcoxon Signed-Rank test를 적용한다(§4.4). mean·LSTM·pool 모두 GCN aggregator 대비 유의한 이득(각각 T=1.0, p=0.02)이고, LSTM vs mean은 T=1.5, p=0.03, pool vs mean은 T=4.5, p=0.10, LSTM vs pool은 T=10.0, p=0.46으로 LSTM과 pool 사이엔 유의한 차이가 없다. 저자 스스로 표본이 6개뿐이라 검정력이 부족하다고 명시한다. pool을 살짝 선호하는 근거는 성능이 아니라 속도다. LSTM이 약 2배 느리다(§4.4).

GCN 변형과 나머지의 차이에서 concat(skip connection)의 역할이 커 보인다. 특히 mean aggregator와 GCN aggregator는 집계 방식이 거의 같고 concat 유무가 주된 차이인데도 mean이 유의하게 앞서므로, concat의 기여 가능성을 시사한다(이는 논문 결과에서 조심스럽게 도출할 수 있는 해석이다).

### 6.4 Runtime과 sample size trade-off

![GraphSAGE timing and sampling trade-off](/api/blog/figures/graphsage-timing-sampling-blog.png)
*그림 3. GraphSAGE의 runtime과 sample-size trade-off를 블로그 렌더링에 맞게 자체 재구성한 차트. A는 Reddit에서 방법별 training/inference time 차이를, B는 citation 데이터에서 sample size 증가에 따른 micro-F1과 runtime 변화를 정성적으로 요약한다. 원논문 Hamilton et al. (2017), Figure 2의 메시지를 바탕으로 재작성했다.*

학습 시간은 방법 간 비슷하다(LSTM이 가장 느림). 차이는 test time에 있다. DeepWalk는 unseen 노드마다 새 random walk와 SGD 라운드가 필요해 100–500배 느리다(§4.3). 이 timing 비교의 하드웨어 조건이 대칭적이지 않다는 점은 8.1절에서 따로 다룬다.

depth와 샘플 크기의 trade-off는 뚜렷하다. K=2는 K=1 대비 평균 10–15% 정확도 이득을 주지만, K를 2보다 키우면 이득이 0–5%로 줄면서 runtime이 10–100배 커진다(§4.3). 샘플 크기도 수확 체감을 보인다(그림 3.B). K=2, \(S_1\cdot S_2 \le 500\)이라는 권장 설정은 이 관찰의 요약이다.

---

## 7. Theorem 1 읽기

논문 §5는 "feature 기반 방법이 그래프 구조를 표현할 수 있는가"라는 질문에 하나의 사례 연구로 답한다. 대상은 clustering coefficient(1-hop 이웃 안에서 닫힌 삼각형의 비율)다.

**Theorem 1의 진술**: 모든 노드 쌍의 feature가 서로 충분히 다르면(\(\lVert x_v - x_{v'} \rVert_2 > C\)), 임의의 \(\varepsilon > 0\)에 대해 K=4 iteration 후 \(|z_v - c_v| < \varepsilon\)를 만족하는 Algorithm 1의 파라미터 설정 \(\Theta^*\)가 **존재**한다(§5).

이 정리는 다음과 같이 읽어야 한다.

- **존재 증명이지 학습 보장이 아니다.** 논문 스스로 "본질적으로 identifiability 논증"이며 "efficient learnability는 future work"라고 명시한다(Appendix E). SGD가 그 \(\Theta^*\)에 도달한다는 보장은 없다.
- **pooling aggregator에 한정된 보장이다.** 증명이 pooling aggregator의 universal approximation 성질에 의존한다(§5, Appendix E). 논문은 이것이 GraphSAGE-pool이 GCN·mean 변형보다 나은 이유에 대한 통찰이라고 본다. 실제로 random Gaussian feature를 넣은 실험에서 pool은 어느 정도 성능을 유지하지만 GCN 변형은 무너진다(Appendix E, Figure 3).
- **정리 자체는 사실상 transductive다.** 논문 스스로 Theorem 1과 Corollary 2가 "특정 주어진 그래프에 대한 진술이라 다소 transductive"라고 명시한다(Appendix E). inductive 설정으로의 확장은 별도의 Corollary 3이 맡는다: 어떤 그래프 클래스에서 k번의 iteration으로 모든 노드를 3-hop 이웃 안에서 유일하게 식별할 수 있으면, K=k+4로 그 클래스 전체에서 clustering coefficient를 근사할 수 있다(Appendix E).
- **전제 조건이 강하다.** feature가 노드 쌍마다 구분되어야 한다. 연속분포에서 샘플된 feature라면 거의 확실히 성립하지만(Corollary 2), feature가 없어 degree 같은 구조적 feature로 대체하면 동일 degree 노드들이 같은 feature를 갖게 되어 조건이 깨진다. 또 최악의 경우 필요한 차원이 \(O(|\mathcal V|)\)라는 점도 Appendix E에 명시돼 있다. 논문은 Kipf et al.의 featureless GCN도 \(O(|\mathcal V|)\) 파라미터를 쓴다는 점을 들어 아주 비합리적인 요구는 아니라고 덧붙이지만, 이론적 보장의 조건이 노드 수에 비례해 무거워진다는 사실 자체는 남는다.
- **범위가 좁다.** clustering coefficient라는 스칼라 지표 하나에 대한 결과다. "구조 정보 일반을 학습한다"는 §1의 넓은 서술을 온전히 뒷받침하는 것은 아니고, 저자도 case-study라 부른다(§5).

요약하면 Theorem 1은 "feature 기반이면서도 구조를 표현할 수 있다"는 조건부 가능성 진술이다. 과장 없이 읽으면 그 자체로 흥미로운 결과이고, 이후 GNN 표현력 연구(GIN의 WL 판별력 분석)로 이어졌다.

---

## 8. 주의해서 읽을 점

### 8.1 "100–500배 빠르다"의 조건

DeepWalk 대비 test-time 속도 주장은 알고리즘 구조 차이(look-up 재최적화 vs 함수 적용)에서 나오는 진짜 차이다. 다만 Appendix C를 보면 GraphSAGE는 GPU 4장 머신에서, DeepWalk는 CPU 144코어 머신에서 실행됐고, DeepWalk는 저자들이 TensorFlow로 재구현한 버전이다. 하드웨어와 구현이 다르므로 배수 자체는 조건부로 읽어야 한다. 논문은 이 사실을 Appendix에 투명하게 적어뒀지만, 본문 수치에는 반영하지 않았다.

### 8.2 DeepWalk baseline의 구도

DeepWalk는 transductive 방법이고, 논문 스스로 "transductive 설정에서는 훨씬 경쟁력 있다"고 인정한다(Appendix C). 같은 자리에서 Kipf et al.이 transductive link prediction에서도 GCN 계열이 DeepWalk를 일관되게 이겼다고 보고했다는 단서도 함께 단다. 즉 Table 1은 inductive 과제에 구조적으로 불리한 baseline과의 비교다.

처리 자체는 성의가 있는 편이다. unseen 노드에 대해 노드당 길이 5의 walk 50개를 돌리되 기존 embedding은 고정한 채 새 노드만 업데이트하는 "online" 방식을 쓰고, drift를 완화하는 변형과 그렇지 않은 변형을 둘 다 시험해 항상 더 나은 쪽을 채택했으며, DeepWalk에만 5 pass와 별도 learning rate sweep을 부여했다(§4, Appendix C·D). 논문은 또 test 예측에 1000배 이상의 시간을 쓰면 DeepWalk가 unsupervised GraphSAGE와 경쟁 가능해질 수 있다고 관찰하되, 그것을 inductive 과제의 의미 있는 비교로 보지 않는다(Appendix C).

당시 공정한 inductive baseline이 드물었다는 사정은 있다. 그래도 §2에서 Planetoid-I를 inductive 선행으로 언급하면서 실험 비교에 넣지 않은 점은 아쉬운 대목이고, "DeepWalk보다 우수"는 inductive 조건부 주장으로 읽는 것이 정확하다.

### 8.3 feature 기반 과제 위주의 평가

citation은 문장 embedding, Reddit은 GloVe 기반 feature, PPI는 유전자 집합 feature를 쓴다. GraphSAGE의 핵심 전제(노드 feature 활용)가 작동하는 환경에서의 평가다. 단, PPI는 feature가 매우 sparse해서 노드의 42%가 non-zero feature를 하나도 갖지 않으며, 논문은 그래서 이웃 정보 활용이 결정적이라고 설명한다(Appendix B). 따라서 "feature-rich 환경만 골랐다"는 비판은 citation·Reddit에 주로 해당한다. 논문은 feature 없는 그래프에도 degree 같은 구조적 feature로 적용 가능하다고 주장하지만(§1), 이 주장 자체는 실험으로 검증되지 않았고, 7장에서 봤듯 degree 대체는 Theorem 1의 전제와 충돌한다.

### 8.4 샘플링이 만드는 비결정성

매 iteration 이웃을 새로 뽑으므로, 같은 노드라도 실행마다 다른 embedding이 나온다. 논문은 sub-sampling이 분산을 높인다는 점을 인정하면서 정확도가 유지되므로 수용 가능한 trade-off로 본다(§4.3). 그러나 재현성이나 embedding의 안정성이 중요한 사용처(예: 시점 간 비교)에서는 이 비결정성이 문제가 될 수 있다.

정보가 어디서 손실되는지도 짚어 둘 대목이다. Reddit처럼 평균 degree 492인 그래프에서 depth당 최대 25개(\(S_1=25\))만 uniform 샘플링하면 hub 노드의 이웃 정보 대부분이 버려지고, 전처리에서 아예 degree를 128로 잘라내기도 한다(Appendix C). uniform sampling은 중요한 이웃과 주변적 이웃을 같은 확률로 취급한다. 논문이 non-uniform sampler를 future work로 남긴 이유이기도 하다.

### 8.5 Unsupervised loss의 근접성(homophily) 가정

Eq 1은 random walk상 가까운 노드가 유사한 표현을 갖도록 만든다. 구조적으로 같은 역할이지만 그래프상 멀리 떨어진 노드들은 이 loss로는 가까워지지 않는다. 그런데 논문은 PPI 과제를 "community 구조가 아니라 노드 역할 학습"으로 규정한다(§4.2). 근접성 기반 unsupervised loss와 역할 학습이라는 과제 성격은 서로 상충하는데, 논문은 이를 명시적으로 다루지 않는다. PPI에서 unsupervised와 supervised의 격차가 유독 큰 것(같은 LSTM 기준 0.482 → 0.612)과 무관하지 않을 수 있다. 5.1절에서 봤듯 unsupervised 열은 고정된 선형 분류기를 통과한 성능이므로, 격차의 일부는 loss가 아니라 평가 프로토콜에서 올 수도 있다.

### 8.6 PPI 절대 수치는 상한이 아니다

논문 각주 스스로 밝히듯, follow-up 연구(Chen et al., 2017)가 hyperparameter 최적화와 추가 기법으로 PPI에서 더 높은 성능을 달성했다(§4.2 각주; 논문 각주는 Chen and Zhu로 인용). Table 1의 PPI 수치를 프레임워크의 한계로 읽으면 안 된다.

---

## 9. 방법적 한계와 확장

### 9.1 논문이 밝힌 한계

| 한계 | 내용 | 출처 |
| --- | --- | --- |
| Uniform sampling | 비균일·학습형 샘플러는 미탐구 | §3.1 각주, §6 |
| Directed / multi-modal graph | 무향 그래프만 다룸(citation도 무향화해 사용) | §6, §4.1 |
| Depth 확장 비용 | K>2는 이득 0–5%에 runtime 10–100배 | §4.3 |
| LSTM 비대칭성 | 순열 불변이 아닌 aggregator를 무작위 순열로 우회 | §3.3 |
| 통계 검정력 | aggregator 비교의 표본이 6개뿐 | §4.4 |
| Theorem 1의 성격 | 존재 증명이며 학습 가능성은 미해결 | Appendix E |

이 목록은 논문 본문·각주·부록에 실제로 적힌 것들이다. 자기 한계를 이 정도로 명시한 것은 이 논문의 미덕이고, 각 항목이 그대로 후속 연구의 주제가 됐다.

### 9.2 이후 연구 계보

아래는 논문 이후의 전개를 이해하기 위한 간단한 맥락이다.

- **집계 함수의 설계**: GAT(Veličković et al., ICLR 2018)는 이웃 집계에 attention 가중치를 도입했다. GIN(Xu et al., ICLR 2019)은 aggregator 선택과 WL 판별력의 관계를 정식화했는데, GraphSAGE의 mean/max aggregator는 그 분석에서 표현력 한계의 사례로 다뤄진다. 본 논문이 §3.1에서 인정한 WL 근사의 실패 가능성이 이후 정밀하게 규명된 것이다.
- **샘플링 기반 확장**: node-wise 샘플링의 K-hop 이웃 곱셈 문제를 다루기 위해 FastGCN(layer-wise sampling), Cluster-GCN, GraphSAINT(subgraph sampling) 등이 이어졌다.
- **산업 적용**: PinSAGE(Ying et al., KDD 2018)는 저자진이 참여한 Pinterest의 웹스케일 추천 시스템으로, random-walk 기반 이웃 샘플링과 GraphSAGE식 집계를 수십억 규모 그래프에 적용했다.

### 9.3 동적 네트워크 관점에서의 의미

계산사회과학의 시각에서 이 논문의 의미는 "embedding"과 "embedding을 만드는 함수"의 분리에 있다. transductive embedding은 지금 이 스냅샷의 노드 좌표를 학습하고, 재학습마다 공간이 drift할 수 있다. GraphSAGE는 이웃의 속성·구조를 표현으로 바꾸는 함수를 학습하므로, 새 사용자·새 게시글·새 웨이브가 유입되는 동적 네트워크에서 재학습 없이 일관된 규칙을 적용할 수 있다. 종단 연구에서 시점 간 비교 가능한 표현이 필요할 때 유용할 수 있는 성질이다. 단, feature 스키마와 샘플링 안정성 관리가 함께 필요하다.

다만 전제도 함께 읽어야 한다. 그래프 간 일반화는 같은 형태의 feature가 공유될 때 성립하고(PPI 실험이 그 구도다), 표현이 이웃 feature의 집계로 만들어지므로 embedding이 포착하는 "위치"는 관계 구조 그 자체라기보다 관계 구조를 통과한 속성 분포다. 구조적 위치와 속성 확산을 구분해야 하는 연구 설계라면 이 차이가 구성타당도 문제로 이어질 수 있다.

---

## 10. 결론

GraphSAGE는 node embedding 문제를 "노드별 벡터 최적화"에서 "집계 함수 학습"으로 옮겼다. 고정 크기 uniform sampling으로 배치당 계산량을 상수로 만들고, aggregator를 교체 가능한 부품으로 정리했으며, unseen 노드와 그래프에 대한 평가 프로토콜을 제시했다.

이 논문을 읽을 때 잡아야 할 균형은 이렇다.

| 기여 | 읽는 법 |
| --- | --- |
| Inductive embedding 프레임워크 | 노드가 아니라 함수를 학습한다는 관점 전환이 핵심이다. |
| 세 벤치마크에서의 강한 성능 | feature 기반 과제, inductive에 불리한 baseline이라는 조건 안에서의 결과다. |
| 고정 복잡도 샘플링 | 실용적 강점이지만 비결정성과 hub 정보 희석을 동반하며, 샘플러 개선은 future work다. |
| Theorem 1 | pooling aggregator 한정, 강한 전제의 존재 증명이다. 학습 보장으로 읽으면 과장이다. |

이 논문은 이웃 샘플링과 학습형 집계라는 두 부품으로 inductive node embedding을 초기의 실용적 형태로 정리한 대표적 기준점이다. 이후의 GNN 집계 함수 연구와 샘플링 기반 확장 연구를 읽을 때 중요한 대표적 기준점으로 남았다.

## References

Hamilton, W. L., Ying, R., & Leskovec, J. (2017). *Inductive Representation Learning on Large Graphs* (arXiv:1706.02216). *Advances in Neural Information Processing Systems*, *30*. https://arxiv.org/abs/1706.02216 ([PDF 보기](/paper-viewer?title=Inductive+Representation+Learning+on+Large+Graphs&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1706.02216.pdf&arxiv_id=1706.02216&doi=10.48550%2FarXiv.1706.02216&year=2017&authors=William+L.+Hamilton%3BRex+Ying%3BJure+Leskovec&source=blog-reference))

Arora, S., Liang, Y., & Ma, T. (2017). A simple but tough-to-beat baseline for sentence embeddings. *International Conference on Learning Representations*. https://openreview.net/forum?id=SyK00v5xx ([PDF 보기](/paper-viewer?title=A+simple+but+tough-to-beat+baseline+for+sentence+embeddings&source=blog-reference&authors=Sanjeev+Arora%3BYingyu+Liang%3BTengyu+Ma&year=2017&url=https%3A%2F%2Fopenreview.net%2Fforum%3Fid%3DSyK00v5xx))

Pennington, J., Socher, R., & Manning, C. D. (2014). GloVe: Global vectors for word representation. *Proceedings of the 2014 Conference on Empirical Methods in Natural Language Processing*, 1532–1543. https://doi.org/10.3115/v1/D14-1162 ([PDF 보기](/paper-viewer?title=GloVe%3A+Global+vectors+for+word+representation&source=blog-reference&authors=Jeffrey+Pennington%3BRichard+Socher%3BChristopher+D.+Manning&year=2014&pdf_url=https%3A%2F%2Faclanthology.org%2FD14-1162.pdf&doi=10.3115%2Fv1%2FD14-1162&url=https%3A%2F%2Faclanthology.org%2FD14-1162%2F))

Perozzi, B., Al-Rfou, R., & Skiena, S. (2014). DeepWalk: Online learning of social representations. *Proceedings of the 20th ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 701–710. https://doi.org/10.1145/2623330.2623732 ([PDF 보기](/paper-viewer?title=DeepWalk%3A+Online+learning+of+social+representations&source=blog-reference&authors=Bryan+Perozzi%3BRami+Al-Rfou%3BSteven+Skiena&year=2014&doi=10.1145%2F2623330.2623732&url=https%3A%2F%2Fdoi.org%2F10.1145%2F2623330.2623732))

Grover, A., & Leskovec, J. (2016). node2vec: Scalable feature learning for networks. *Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 855–864. https://doi.org/10.1145/2939672.2939754 ([PDF 보기](/paper-viewer?title=node2vec%3A+Scalable+feature+learning+for+networks&source=blog-reference&authors=Aditya+Grover%3BJure+Leskovec&year=2016&doi=10.1145%2F2939672.2939754&url=https%3A%2F%2Fdoi.org%2F10.1145%2F2939672.2939754))

Yang, Z., Cohen, W. W., & Salakhutdinov, R. (2016). Revisiting semi-supervised learning with graph embeddings. *International Conference on Machine Learning*. https://arxiv.org/abs/1603.08861 ([PDF 보기](/paper-viewer?title=Revisiting+semi-supervised+learning+with+graph+embeddings&source=blog-reference&authors=Zhilin+Yang%3BWilliam+W.+Cohen%3BRuslan+Salakhutdinov&year=2016&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1603.08861.pdf&arxiv_id=1603.08861&url=https%3A%2F%2Farxiv.org%2Fabs%2F1603.08861))

Kipf, T. N., & Welling, M. (2017). Semi-supervised classification with graph convolutional networks. *International Conference on Learning Representations*. https://arxiv.org/abs/1609.02907 ([PDF 보기](/paper-viewer?title=Semi-supervised+classification+with+graph+convolutional+networks&source=blog-reference&authors=Thomas+N.+Kipf%3BMax+Welling&year=2017&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1609.02907.pdf&arxiv_id=1609.02907&url=https%3A%2F%2Farxiv.org%2Fabs%2F1609.02907))

Chen, J., Zhu, J., & Song, L. (2017). *Stochastic training of graph convolutional networks with variance reduction*. arXiv. https://arxiv.org/abs/1710.10568 ([PDF 보기](/paper-viewer?title=Stochastic+training+of+graph+convolutional+networks+with+variance+reduction&source=blog-reference&authors=Jie+Chen%3BJun+Zhu%3BLe+Song&year=2017&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1710.10568.pdf&arxiv_id=1710.10568&url=https%3A%2F%2Farxiv.org%2Fabs%2F1710.10568))

Veličković, P., Cucurull, G., Casanova, A., Romero, A., Liò, P., & Bengio, Y. (2018). Graph attention networks. *International Conference on Learning Representations*. https://arxiv.org/abs/1710.10903 ([PDF 보기](/paper-viewer?title=Graph+attention+networks&source=blog-reference&authors=Petar+Veli%C4%8Dkovi%C4%87%3BGuillem+Cucurull%3BArantxa+Casanova%3BAdriana+Romero%3BPietro+Li%C3%B2%3BYoshua+Bengio&year=2018&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1710.10903.pdf&arxiv_id=1710.10903&url=https%3A%2F%2Farxiv.org%2Fabs%2F1710.10903))

Chen, J., Ma, T., & Xiao, C. (2018). FastGCN: Fast learning with graph convolutional networks via importance sampling. *International Conference on Learning Representations*. https://arxiv.org/abs/1801.10247 ([PDF 보기](/paper-viewer?title=FastGCN%3A+Fast+learning+with+graph+convolutional+networks+via+importance+sampling&source=blog-reference&authors=Jie+Chen%3BTengfei+Ma%3BCao+Xiao&year=2018&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1801.10247.pdf&arxiv_id=1801.10247&url=https%3A%2F%2Farxiv.org%2Fabs%2F1801.10247))

Ying, R., He, R., Chen, K., Eksombatchai, P., Hamilton, W. L., & Leskovec, J. (2018). Graph convolutional neural networks for web-scale recommender systems. *Proceedings of the 24th ACM SIGKDD International Conference on Knowledge Discovery & Data Mining*, 974–983. https://doi.org/10.1145/3219819.3219890 ([PDF 보기](/paper-viewer?title=Graph+convolutional+neural+networks+for+web-scale+recommender+systems&source=blog-reference&authors=Rex+Ying%3BRuining+He%3BKaifeng+Chen%3BPong+Eksombatchai%3BWilliam+L.+Hamilton%3BJure+Leskovec&year=2018&doi=10.1145%2F3219819.3219890&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3219819.3219890))

Xu, K., Hu, W., Leskovec, J., & Jegelka, S. (2019). How powerful are graph neural networks? *International Conference on Learning Representations*. https://arxiv.org/abs/1810.00826 ([PDF 보기](/paper-viewer?title=How+powerful+are+graph+neural+networks%3F&source=blog-reference&authors=Keyulu+Xu%3BWeihua+Hu%3BJure+Leskovec%3BStefanie+Jegelka&year=2019&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1810.00826.pdf&arxiv_id=1810.00826&url=https%3A%2F%2Farxiv.org%2Fabs%2F1810.00826))

Chiang, W.-L., Liu, X., Si, S., Li, Y., Bengio, S., & Hsieh, C.-J. (2019). Cluster-GCN: An efficient algorithm for training deep and large graph convolutional networks. *Proceedings of the 25th ACM SIGKDD International Conference on Knowledge Discovery & Data Mining*, 257–266. https://doi.org/10.1145/3292500.3330925 ([PDF 보기](/paper-viewer?title=Cluster-GCN%3A+An+efficient+algorithm+for+training+deep+and+large+graph+convolutional+networks&source=blog-reference&authors=Wei-Lin+Chiang%3BXuanqing+Liu%3BSi+Si%3BYang+Li%3BSamy+Bengio%3BCho-Jui+Hsieh&year=2019&doi=10.1145%2F3292500.3330925&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3292500.3330925))

Zeng, H., Zhou, H., Srivastava, A., Kannan, R., & Prasanna, V. (2020). GraphSAINT: Graph sampling based inductive learning method. *International Conference on Learning Representations*. https://arxiv.org/abs/1907.04931 ([PDF 보기](/paper-viewer?title=GraphSAINT%3A+Graph+sampling+based+inductive+learning+method&source=blog-reference&authors=Hanqing+Zeng%3BHongkuan+Zhou%3BAjitesh+Srivastava%3BRajgopal+Kannan%3BViktor+Prasanna&year=2020&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1907.04931.pdf&arxiv_id=1907.04931&url=https%3A%2F%2Farxiv.org%2Fabs%2F1907.04931))
