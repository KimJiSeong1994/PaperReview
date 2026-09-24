# HAN 심층 분석: "Heterogeneous Graph Attention Network" 논문 해설

**Paper:** Wang, Xiao; Ji, Houye; Shi, Chuan; Wang, Bai; Ye, Yanfang; Cui, Peng; Yu, Philip S. (2019). "Heterogeneous Graph Attention Network." *The World Wide Web Conference (WWW '19)*, pp. 2022–2032. https://doi.org/10.1145/3308558.3313562. arXiv:1903.07293. Code: github.com/Jhy1993/HAN

**HAN**은 이종 그래프에서 meta-path별 GAT식 node-level attention과 meta-path 간 semantic-level attention을 계층 구조로 결합해 노드 임베딩을 학습하는 GNN이다(Wang et al., WWW 2019). ACM 노드 분류에서 최강 baseline(GCN) 대비 최대 2.6%p를 앞서며, attention 기반 이종 그래프 신경망의 "first attempt"로 인용된다.

**Abstract:** 본 문서는 이종 그래프에 attention을 가져온 초기 GNN인 HAN 논문을 해설한다. 설계는 두 층의 계층적 attention이다. node-level attention은 meta-path로 유도된 이웃들 사이의 중요도를 GAT식으로 학습하고, semantic-level attention은 meta-path들 자체의 중요도를 학습해 meta-path별 임베딩을 가중합한다. DBLP·ACM·IMDB 세 이종 그래프의 노드 분류·군집화에서 baseline 대비 우위를 보고했고, attention 값이 meta-path의 유효성을 해석하는 도구가 된다는 것을 함께 보였다. 다만 meta-path 집합 자체는 사람이 지정하는 입력이고, semantic 가중치는 노드 구분 없는 전역 스칼라이며, baseline 비교 방식(meta-path별 최고치 보고)은 이후 통일 벤치마크 HGB(Lv et al., 2021) 재평가에서 문제로 지적된다. 이 간극들이 이 글의 후반부 주제다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 노드·관계 타입이 여럿인 이종 그래프에서, "어떤 이웃이 중요한가"(노드 수준)와 "어떤 의미 관계(meta-path)가 중요한가"(의미 수준)를 attention으로 동시에 학습할 수 있는가? |
| 핵심 기여 | meta-path별 GAT식 node-level attention 위에, meta-path들의 중요도를 학습하는 semantic-level attention을 얹은 2층 계층 구조. 논문 표현으로는 attention 기반 이종 그래프 신경망의 "first attempt". |
| 방법적 결과 | 타입별 투영 \(\mathbf{h}'_i = \mathbf{M}_{\phi_i}\mathbf{h}_i\) → meta-path별 \(\mathbf{z}^\Phi_i\)(masked attention + multi-head) → \(\mathbf{Z} = \sum_p \beta_{\Phi_p}\mathbf{Z}_{\Phi_p}\)를 semi-supervised cross-entropy로 학습한다(Eq. 1–10). |
| 실험 결과 | 저자 보고 기준 분류(Table 3)에서 ACM은 최강 baseline(GCN) 대비 +1.2~2.6점, DBLP는 1점 미만(2개 셀은 HERec과 동률), IMDB는 GAT 대비 최대 +2.34(Macro-F1 60%). 군집화(Table 4)는 ACM NMI 61.56 vs GAT 57.29. |
| 핵심 한계 | meta-path 집합은 모델 입력(Algorithm 1)이고 중간 노드 정보는 정의상 버려진다. semantic 가중치 β는 전 노드 공통 스칼라다. inductive는 주장만 있고 실험이 없다. baseline은 meta-path별 최고치 보고 방식이라 이후 HGB 재평가의 표적이 됐다. |

**TL;DR** — (1) HAN은 meta-path별 이웃에 node-level attention을 적용하고, meta-path 간 의미 중요도를 semantic-level attention으로 학습하는 2층 계층 이종 그래프 신경망이다. (2) 저자 보고 기준 ACM 노드 분류에서 최강 baseline(GCN) 대비 최대 2.6%p 이득, 군집화 NMI에서 ACM 61.56 대 GAT 57.29를 달성했다. (3) meta-path 집합을 사람이 지정해야 하고 semantic 가중치가 전역 스칼라라는 점에서, meta-path 자동 탐색이나 노드별 의미 가중이 필요한 설정에는 적합하지 않다.

## 목차

1. 서론
2. 예비 지식
3. HAN 프레임워크
4. 실험 설정
5. 실험 결과
6. 주의해서 읽을 점
7. 방법적 한계와 확장
8. 결론

---

## 1. 서론

### 1.1 연구 배경

HetGNN 리뷰(blog/hetgnn)에서 본 것과 같은 문제의식이다. GNN은 동종 그래프에서 성과를 냈지만, 실제 그래프는 노드·관계 타입이 여럿이다. HAN이 드는 예시는 영화 데이터 IMDB다: 영화·배우·감독 세 타입의 노드가 있고, 관계도 출연(role-play)과 연출(shoot)로 나뉜다(§3, Figure 1). 이런 그래프에서 노드 간 관계는 **meta-path**로 표현된다. "영화–배우–영화"(MAM)는 같은 배우가 나온 관계, "영화–감독–영화"(MDM)는 같은 감독이 만든 관계다. 어떤 meta-path가 유효한지는 과제에 따라 다르다. 논문의 예시로, The Terminator의 장르를 맞추는 데는 MAM(같은 배우 Schwarzenegger가 나온 The Terminator 2와 연결)이 "영화–연도–영화"(같은 1984년작 Birdy와 연결)보다 중요하다(§1).

한편 attention은 딥러닝 전반에서 "데이터의 중요한 부분에 집중하는" 장치로 자리 잡았고, 그래프에서는 GAT가 동종 그래프에 이를 가져왔다. 논문의 출발점은 이 둘의 교집합이 비어 있다는 것이다: "attention은 이종 그래프용 GNN 프레임워크에서는 고려된 적이 없다"(§1).

### 1.2 세 가지 요구사항

논문은 이종 그래프용 attention GNN이 충족해야 할 "new requirements" 셋을 IMDB 예시와 함께 제시한다(§1).

- **이질성(heterogeneity):** 타입마다 특징이 다른 공간에 산다. 배우의 특징은 성별·나이·국적이고 영화의 특징은 플롯과 배우다. 복잡한 구조 정보를 다루면서 다양한 특징 정보를 동시에 보존해야 한다. → 타입별 투영 행렬(3장).
- **semantic-level attention:** meta-path마다 드러내는 의미가 다르고, 과제에 가장 유효한 meta-path를 고르고 융합하는 것은 열린 문제다. 모든 meta-path를 동등 취급하면 유용한 meta-path의 의미 정보가 희석된다. → meta-path 중요도 학습(3장).
- **node-level attention:** 같은 meta-path 안에서도 이웃별 중요도가 다르다. MDM으로 The Terminator는 (James Cameron을 매개로) Titanic·The Terminator 2와 연결되는데, SF 장르 식별에는 후자가 더 중요하다. → 이웃 중요도 학습(3장).

요구사항의 나열 순서(이질성 → semantic → node)와 모델의 계산 순서(투영 → node-level → semantic-level)가 반대라는 점만 기억해 두면 §4를 읽을 때 헷갈리지 않는다.

![HAN Figure 1: IMDB heterogeneous graph and meta-paths](/api/blog/figures/han-fig1-metapath.png)

*그림 1 — 원논문 Figure 1: (a) 노드 타입, (b) IMDB 이종 그래프, (c) meta-path 두 종(MAM·MDM), (d) meta-path 기반 이웃 — MAM 기준 \(m_1\)의 이웃은 자기 자신을 포함해 \(m_1, m_2, m_3\)이다.*

### 1.3 학술적 위치

§2 Related Work의 구도는 2×2다. GNN 갈래(GCN·GAT 등)는 "동종 그래프에만 적용 가능"하고(§2.1 말미), 이종 그래프 임베딩 갈래(ESim·metapath2vec·HERec 등)는 "attention을 고려하지 않는다"(§2.2 말미). 두 결핍의 교집합이 HAN의 자리다. 개별 방법 수준에서 논거가 실제로 작동하는 것은 둘이다: ESim은 여러 meta-path를 쓸 수 있으나 중요도를 학습하지 못해 grid search(후보 조합의 전수 시험)에 의존하고, metapath2vec은 meta-path를 하나만 쓴다(§2.2). 이 두 결함이 정확히 semantic-level attention이 풀겠다는 문제다.

최초성 주장은 신중하게 좁혀져 있다. §1 기여 1의 원문은 "To our best knowledge, this is the first attempt to study the heterogeneous graph neural network based on attention mechanism"이다. GNN × 이종 그래프 × attention의 3중 교집합에 국한된 주장이고, 논문 스스로 §2.1에서 GNN 밖의 attention 응용(meta-path 기반 추천 모델)을 인용해 경계를 그어 둔다.

시리즈 관점에서 보면 HAN은 GAT 리뷰(blog/gat)의 직접 후속이다. node-level attention은 meta-path로 유도된 동종 그래프 위에서 도는 GAT 층에 타입별 입력 투영을 붙인 것으로 읽을 수 있고(대응표는 3장 말미), 고유한 새 부품은 그 위의 semantic-level attention이다. 같은 해의 HetGNN(Zhang et al., 2019)과는 같은 문제에 대한 반대 노선이다: HetGNN은 meta-path 없이 restart 랜덤워크로 이웃을 모으고, HAN은 사람이 지정한 meta-path로 의미론을 먼저 고정한 뒤 그 사이의 가중치만 학습한다. 이 대비는 7장에서 다시 본다.

## 2. 예비 지식

원논문 §3 Preliminary에 해당한다.

### 이종 그래프 (Definition 3.1)

이종 그래프 \(\mathcal{G} = (\mathcal{V}, \mathcal{E})\)는 노드 타입 매핑 \(\phi: \mathcal{V} \to \mathcal{A}\)와 링크 타입 매핑 \(\psi: \mathcal{E} \to \mathcal{R}\)이 딸린 그래프로, 조건은 \(|\mathcal{A}| + |\mathcal{R}| > 2\)다(§3; Sun & Han, 2013 인용). HetGNN 리뷰에서 본 C-HetG의 \(|O_V| + |R_E| \ge 3\)과 같은 꼴의 조건으로, 노드 타입 하나·링크 타입 하나인 동종 그래프만 배제하는 최소 기준이다.

### Meta-path (Definition 3.2)

meta-path \(\Phi\)는 \(A_1 \xrightarrow{R_1} A_2 \xrightarrow{R_2} \cdots \xrightarrow{R_l} A_{l+1}\) 형태의 타입 수준 경로로, 두 끝 타입 사이의 합성 관계 \(R = R_1 \circ R_2 \circ \cdots \circ R_l\)을 기술한다(§3, Sun et al., 2011의 PathSim에서 온 개념). "다른 meta-path는 항상 다른 의미를 드러낸다"(§3)는 것이 이 논문의 기본 가정이다.

### Meta-path 기반 이웃 (Definition 3.3)

노드 \(i\)의 meta-path 기반 이웃 \(\mathcal{N}^\Phi_i\)는 \(\Phi\)로 \(i\)와 연결되는 노드들의 집합이고, **자기 자신을 포함한다**(§3). 계산은 인접행렬들의 곱으로 한다(§3). 두 가지를 눈여겨봐야 한다. 첫째, 이웃은 경로의 **양 끝점만**으로 정의된다. MAM에서 두 영화를 잇는 배우는 이웃 집합에 남지 않는다(7.2절에서 재론). 둘째, 자기 포함은 GCN의 self-loop와 같은 역할(자기 특징 보존)을 하는데 논문은 이유를 따로 설명하지 않는다.

### GAT식 attention

두 노드의 특징을 이어 붙여 attention 벡터와 내적하고, softmax로 이웃 위에서 정규화한 가중치로 이웃 특징을 가중합하는 층이다. multi-head(독립 attention K개를 병렬로 돌려 연결)로 학습을 안정화한다. 자세한 도출과 성질은 blog/gat 3장을 참조. HAN의 node-level attention이 이 구조를 그대로 쓴다.

## 3. HAN 프레임워크

원논문 §4에 해당한다. 전체 구조는 그림 2: 타입별 투영 → meta-path별 node-level attention → semantic-level attention → MLP 예측.

![HAN Figure 2: overall framework](/api/blog/figures/han-fig2-architecture.png)

*그림 2 — 원논문 Figure 2: (a) node-level attention — 타입별 투영(Proj) 후 meta-path \(\Phi_0, \dots, \Phi_P\)마다 별도의 attention으로 \(\mathbf{Z}_{\Phi_p}\)를 만들고, (b) semantic-level attention이 이들을 융합해 \(\mathbf{Z}\)를 얻은 뒤, (c) MLP로 예측한다.*

### Node-level attention (원논문 §4.1)

**타입별 투영.** 타입마다 특징 공간이 다르므로, 노드 타입 \(\phi_i\)별 변환 행렬로 공통 공간에 투영한다:

\[ \mathbf{h}'_i = \mathbf{M}_{\phi_i} \cdot \mathbf{h}_i \quad \text{(Eq. 1)} \]

원문은 이 변환이 엣지 타입이 아니라 **노드 타입** 기준임을 명시한다("Unlike (Hamilton et al., 2018), the type-specific transformation matrix is based on node-type rather than edge-type", §4.1). 여기서 인용된 Hamilton et al. 2018은 GraphSAGE와는 다른, 지식그래프 질의 임베딩 논문이다.

**중요도와 masked attention.** meta-path \(\Phi\)로 연결된 노드쌍 \((i,j)\)의 중요도는 self-attention(Vaswani et al., 2017 인용)으로 계산한다: \(e^\Phi_{ij} = att_{node}(\mathbf{h}'_i, \mathbf{h}'_j; \Phi)\)(Eq. 2). \(att_{node}\)는 한 meta-path 안에서 모든 노드쌍에 공유된다. 하나의 meta-path 아래에는 유사한 연결 패턴이 있다는 것이 논문의 근거다(§4.1). 구조 정보는 masked attention으로 넣는다: \(e^\Phi_{ij}\)를 \(j \in \mathcal{N}^\Phi_i\)에 대해서만 계산하고 softmax로 정규화한다:

\[ \alpha^\Phi_{ij} = \frac{\exp\big(\sigma(\mathbf{a}^T_\Phi \cdot [\mathbf{h}'_i \| \mathbf{h}'_j])\big)}{\sum_{k \in \mathcal{N}^\Phi_i} \exp\big(\sigma(\mathbf{a}^T_\Phi \cdot [\mathbf{h}'_i \| \mathbf{h}'_k])\big)} \quad \text{(Eq. 3)} \]

\(\mathbf{a}_\Phi\)는 meta-path별 attention 벡터, \(\|\)는 연결, \(\sigma\)는 활성 함수다(구체 함수는 §4.1이 특정하지 않는데, GAT가 LeakyReLU로 못 박은 것과 다르다). 논문은 \(\alpha^\Phi_{ij}\)의 비대칭성을 강조한다: 분자의 연결 순서와 분모의 이웃 집합이 \(i\)·\(j\)에서 다르므로 \(\alpha^\Phi_{ij} \ne \alpha^\Phi_{ji}\)이고, 이것이 "이종 그래프의 핵심 속성인 비대칭성"을 보존한다는 것이다(§4.1). 다만 분모 차이로 인한 비대칭성은 GAT의 softmax 정규화에서도 똑같이 성립하는 성질이라, 이종성 고유의 장치라기보다 GAT식 attention의 일반 성질에 가깝다(논문 외 관찰).

**집계와 multi-head.** meta-path별 임베딩은 이웃의 투영 특징을 attention 가중합해 얻고(\(\mathbf{z}^\Phi_i = \sigma(\sum_{j \in \mathcal{N}^\Phi_i} \alpha^\Phi_{ij} \cdot \mathbf{h}'_j)\), Eq. 4), 이종 그래프의 scale-free 성질 탓에 분산이 크므로 attention을 K회 반복해 연결하는 multi-head로 안정화한다(Eq. 5; 실험에서 K=8). 결과물은 meta-path마다 하나씩, 총 P개의 semantic-specific 임베딩 \(\mathbf{Z}_{\Phi_1}, \dots, \mathbf{Z}_{\Phi_P}\)다.

![HAN Figure 3: node-level and semantic-level aggregation](/api/blog/figures/han-fig3-aggregation.png)

*그림 3 — 원논문 Figure 3: (a) node-level 집계 — meta-path별 이웃에서 \(\mathbf{z}^{\Phi}_i\)를 만들고, (b) semantic-level 집계 — \(\beta_{\Phi_p}\)로 가중합해 \(\mathbf{Z}_i\)를 만든다.*

### Semantic-level attention (원논문 §4.2)

meta-path 하나의 임베딩은 노드를 한 측면에서만 반영하므로, meta-path들의 중요도 \((\beta_{\Phi_1}, \dots, \beta_{\Phi_P}) = att_{sem}(\mathbf{Z}_{\Phi_1}, \dots, \mathbf{Z}_{\Phi_P})\)를 학습해 융합한다(Eq. 6). 중요도는 세 단계로 잰다: semantic-specific 임베딩을 1층 비선형 변환(tanh)에 통과시키고, semantic-level attention 벡터 \(\mathbf{q}\)와의 유사도를 잰 뒤, **전체 노드에 대해 평균**한다:

\[ w_{\Phi_p} = \frac{1}{|\mathcal{V}|} \sum_{i \in \mathcal{V}} \mathbf{q}^T \cdot \tanh(\mathbf{W} \cdot \mathbf{z}^{\Phi_p}_i + \mathbf{b}) \quad \text{(Eq. 7)} \]

\(\mathbf{W}, \mathbf{b}, \mathbf{q}\)는 "의미 있는 비교를 위해" 모든 meta-path에 공유된다(§4.2). node-level의 \(\mathbf{a}_\Phi\)가 meta-path별인 것과 대조적이다. softmax 정규화로 \(\beta_{\Phi_p}\)를 얻고(Eq. 8), 최종 임베딩은 가중합이다:

\[ \mathbf{Z} = \sum_{p=1}^{P} \beta_{\Phi_p} \cdot \mathbf{Z}_{\Phi_p} \quad \text{(Eq. 9)} \]

두 가지 특징을 짚어 둔다. 첫째, Eq. 7의 평균 때문에 \(\beta_{\Phi_p}\)는 **meta-path당 스칼라 하나**이고 모든 노드에 동일하게 적용된다. 논문이 인정하는 변이는 과제 간 차이뿐이다("for different tasks, meta-path \(\Phi_p\) may has different weights", §4.2). 둘째, node-level은 multi-head 연결, semantic-level은 가중합이라는 결합 방식의 비대칭이 있는데 이유는 논문에 없다.

학습은 semi-supervised다. 라벨된 노드에 cross-entropy \(L = -\sum_{l \in \mathcal{Y}_L} \mathbf{Y}^l \ln(\mathbf{C} \cdot \mathbf{Z}^l)\)를 최소화한다(Eq. 10). Algorithm 1이 전체 절차를 정리하는데, **입력에 meta-path 집합 \(\{\Phi_0, \Phi_1, \dots, \Phi_P\}\)가 명시되어 있다**. meta-path는 모델의 산출물이 아니라 입력이다.

### 모델 분석 (원논문 §4.3)

논문이 스스로 내세우는 성질 넷이다. (1) 다양한 타입의 노드·관계를 다루고 의미를 융합한다. (2) node-level attention의 복잡도는 \(O(V_\Phi F_1 F_2 K + E_\Phi F_1 K)\)로 노드 수와 meta-path 기반 노드쌍 수 \(E_\Phi\)에 선형이고(\(F_1, F_2\)는 변환 행렬의 행·열 수), 노드쌍·meta-path 단위로 병렬화된다. (3) 계층적 attention이 그래프 전체에 공유되므로 파라미터 수가 그래프 규모에 의존하지 않고, "inductive 문제에 쓰일 수 있다"(unseen 노드·그래프에 대한 임베딩 생성으로 정의, GraphSAGE(Hamilton et al., 2017) 인용). (4) attention 값으로 어떤 노드·meta-path가 과제에 기여하는지 해석할 수 있다.

(2)와 (3)은 주의해서 읽어야 한다. 선형 복잡도는 \(E_\Phi\)를 주어진 것으로 놓은 주장인데, meta-path 이웃 그래프는 원 그래프보다 훨씬 조밀해질 수 있고 인접행렬 곱의 전처리 비용도 식에 없다(논문 외 비판). inductive 주장은 6.3절에서 실험과 대조한다.

### GAT와의 대응 (논문 외 해석)

1.3절에서 예고한 대응표를 정리해 둔다. **같은 것:** concat 후 attention 벡터 내적과 softmax라는 attention 골격(Eq. 3), masked attention이라는 장치와 용어, multi-head K회 연결(Eq. 5)과 안정화 동기. **추가된 것:** 타입별 투영 \(\mathbf{M}_{\phi_i}\)(Eq. 1), 이웃 정의의 교체(1-hop 인접 → meta-path 기반 이웃), meta-path별로 분리된 attention 벡터 \(\mathbf{a}_\Phi\), 그리고 GAT에 대응물이 없는 semantic-level attention(Eq. 6–9). **달라진 것:** GAT가 LeakyReLU로 못 박은 attention 내부 활성 함수를 HAN은 \(\sigma\)로만 표기한다. 요약하면 HAN은 meta-path별 그래프마다 GAT 층을 하나씩 돌리고 그 출력을 \(\beta_{\Phi_p}\)로 가중합하는 모델이고, 원문도 이 계보를 숨기지 않는다(§2.1에서 GAT를 직접 인용, §4.1의 attention 전거는 Vaswani et al., 2017).

## 4. 실험 설정

원논문 §5.1–5.3과, §5.4–5.5의 평가 프로토콜 부분에 해당한다.

### 데이터셋 (Table 2)

| 데이터셋 | 노드 | 분류 대상·클래스 | Feature | 분할(train/val/test) | Meta-path |
|---|---|---|---|---|---|
| DBLP | paper 14,328 / author 4,057 / conf 20 / term 8,789 | author 4분야(DB·DM·ML·IR) | author 키워드 BoW 334차원 | 800/400/2,857 | APA, APCPA, APTPA |
| ACM | paper 3,025 / author 5,835 / subject 56 | paper 3분야(DB·무선통신·DM) | paper 키워드 BoW 1,830차원 | 600/300/2,125 | PAP, PSP |
| IMDB | movie 4,780 / actor 5,841 / director 2,269 | movie 3장르(액션·코미디·드라마) | movie 플롯 BoW 1,232차원 | 300/300/2,687 | MAM, MDM |

ACM은 KDD·SIGMOD·SIGCOMM·MobiCOMM·VLDB 게재 논문에서 추출했고 라벨은 게재 학회 기준, DBLP의 저자 분야 라벨은 **저자가 투고한 학회 기준**이다(§5.1). 이 구성이 뒤에서 APCPA 해석에 영향을 준다(7.4절). 특징이 명시된 노드는 데이터셋마다 분류 대상 타입 하나뿐이고(저자·논문·영화), meta-path는 전부 대칭형(타깃 타입에서 시작해 타깃 타입으로 끝남)이라는 것만 기억해 두면 7.2절이 빨라진다.

### Baseline (원논문 §5.2)

총 9열이다: DeepWalk(Perozzi et al., 2014), ESim(Shang et al., 2016), metapath2vec(Dong et al., 2017), HERec(Shi et al., 2019), GCN(Kipf & Welling, 2017), GAT(Veličković et al., 2018), 그리고 HAN의 변형 2종 — HAN\(_{nd}\)(node-level attention을 제거하고 이웃 균등 가중)와 HAN\(_{sem}\)(semantic-level attention을 제거하고 meta-path 균등 가중) — 에 HAN 본체다.

동종 그래프 모델을 어떻게 적용했는지가 비교의 성격을 가른다. DeepWalk는 이질성을 무시하고 전체 그래프에서 돌렸다. metapath2vec·HERec·GCN·GAT는 **meta-path별로 만든 그래프 각각에서 돌려 최고 성능을 보고**했다("we test all the meta-paths ... and report the best performance", §5.2). 어느 기준(validation/test)으로 최고를 골랐는지는 서술이 없다. ESim은 meta-path 가중치 탐색이 어렵다는 이유로 **HAN이 학습한 가중치를 받아** 돌렸다(§5.2). 이 설정들의 함의는 6.2절에서 본다.

### 구현과 프로토콜 (원논문 §5.3–5.5)

HAN: Adam, learning rate 0.005, regularization 0.001, semantic attention 벡터 \(\mathbf{q}\) 차원 128, head 수 K=8, attention dropout 0.6, early stopping patience 100. 모든 알고리즘의 임베딩 차원은 64로 통일. 랜덤워크 계열은 window 5, walk 길이 100, 노드당 40개, negative 5. GCN·GAT·HAN은 같은 분할을 쓰고 validation으로 튜닝한다(§5.3).

평가는 두 과제다. **분류**(§5.4): 학습된 임베딩 위에 KNN(k=5) 분류기를 얹고, train 비율 20/40/60/80%에서 10회 반복 평균 Macro/Micro-F1을 보고한다(Table 3). 이 비율이 Table 2의 고정 분할과 어떤 관계인지(무엇의 20%인지)는 논문이 설명하지 않는다. **군집화**(§5.5): 학습된 모델에서 feed forward로 임베딩을 뽑아 KMeans(K=클래스 수), 분류와 같은 라벨을 정답으로 NMI·ARI를 10회 평균 보고한다(Table 4). 표준편차·유의성 검정은 없다.

## 5. 실험 결과

### 분류 (Table 3, 원논문 §5.4)

데이터셋별로 그림이 다르다(수치는 전부 원문 표 그대로, 격차는 표 원값의 뺄셈).

- **ACM:** 최강 baseline은 전 구간 GCN이고, HAN이 +1.2~2.6점으로 앞선다(Macro-F1 20%: 89.40 vs 86.81; 80%: 90.63 vs 88.29; 60% 열만 1점대).
- **DBLP:** 격차가 1점 미만이고, **HERec과 두 번 동률이다**(Macro-F1 60%: 92.80 = 92.80, Micro-F1 60%: 93.70 = 93.70). 논문 스스로 이유를 설명한다: APCPA가 다른 meta-path보다 압도적으로 중요해서, 융합의 이득이 작다(§5.4, §5.6).
- **IMDB:** 최강 baseline은 GAT이고, 격차는 구간에 따라 다르다(Micro-F1 20% +0.45, 40% +2.06). 절대 수준 자체가 낮은 과제다(최고 Micro-F1 58.51).

ablation은 방향이 뚜렷하다. node-level attention 제거(HAN\(_{nd}\))가 semantic-level 제거(HAN\(_{sem}\))보다 대체로 더 아프다(ACM 분류에서 전 구간 1점 이상 하락 대 대체로 0.5점 안팎 하락). 다만 **full HAN이 자기 변형에 지는 셀이 3곳 있다**(ACM Macro/Micro-F1 60%에서 HAN\(_{sem}\)이 우세, IMDB Macro-F1 20%도 HAN\(_{sem}\) 50.87 vs 50.00). §5.4의 "모든 데이터셋에서 최고"라는 서술과 표가 어긋난다(6.1절).

### 군집화 (Table 4, 원논문 §5.5)

HAN이 전 셀에서 최고다: ACM NMI 61.56/ARI 64.39(GAT 57.29/60.43), DBLP NMI 79.12/ARI 84.76(HERec 76.73/80.98), IMDB NMI 10.87/ARI 10.01(GAT 8.45/7.46). 두 가지 단서가 필요하다. DBLP에서는 랜덤워크 계열(DeepWalk 76.53, HERec 76.73)이 GCN(75.01)·GAT(71.50)를 앞서 "GNN 계열이 대체로 낫다"는 §5.5의 서술에 예외가 있고, IMDB는 전 모델이 NMI 10.87 이하로 사실상 실패하는 과제 위의 상대 우위다.

### Attention 분석 (원논문 §5.6, Figures 4–5)

이 논문에서 가장 설득력 있는 부분이다. node-level에서는 ACM 논문 P831의 PAP 이웃별 attention을 열거한다. 자기 자신이 최대이고, 같은 Data Mining 클래스인 이웃 2편이 다음 순위, 다른 클래스 이웃들은 낮다(Figure 4). semantic-level에서는 **단일 meta-path만 쓴 군집화 NMI와 그 meta-path의 attention 값이 나란히 간다**는 것을 보인다(Figure 5): DBLP에서는 APCPA(저자–논문–학회–논문–저자)가 최대 가중치를 받고 실제 단일 성능도 최고인 반면 APA(공저)는 둘 다 낮다. ACM에서는 PAP와 PSP의 성능이 비등해서, meta-path를 균등 평균하는 HAN\(_{sem}\)도 좋은 성능을 낸다고 논문이 직접 인정한다(§5.6).

### 시각화와 민감도 (원논문 §5.7–5.8)

DBLP 저자 임베딩의 t-SNE 시각화(Figure 6)에서 GCN·GAT는 분야가 섞이고 metapath2vec은 낫지만 경계가 흐리며 HAN이 가장 뚜렷하다. 정량 지표 없는 정성 비교다. 민감도(Figure 7)는 ACM 군집화 NMI 한정으로 셋을 본다: 최종 임베딩 차원(오르다 완만 하락), \(\mathbf{q}\) 차원(128 최적), head 수(늘리면 오르지만 "improve only slightly").

## 6. 주의해서 읽을 점

### 6.1 "best on all datasets"의 실제 강도

§5.4의 요약 서술("HAN achieves the best performance on all datasets")과 Table 3 사이에는 간극이 있다. DBLP에서 HERec과 두 번 동률이고, 자기 변형 HAN\(_{sem}\)에 지는 셀이 3곳 있다. 10회 반복 평균이라고만 밝히고 표준편차를 보고하지 않으므로, DBLP의 1점 미만 격차나 역전 셀들의 유의성은 판단할 수 없다. 반복의 동기로 "그래프 데이터의 분산이 크다"(§5.4)를 들면서 정작 분산은 보고하지 않는다. 같은 유형의 간극이 하나 더 있다: §5.6은 DBLP에서 meta-path를 동등 취급하면 성능이 크게 떨어진다고 쓰지만, Table 3의 HAN−HAN\(_{sem}\) 격차는 +0.21~0.55다. 그 서술은 분류 표보다 군집화(NMI +1.81)나 단일 meta-path 성능 격차 쪽에 부합한다. 확실하게 남는 격차는 ACM 분류의 +1.2~2.6점과 군집화(특히 ACM NMI +4.27)다.

### 6.2 baseline 비교의 구도

비교의 의미를 제한하는 설정이 셋 있다. GCN·GAT는 **전체 이종 그래프가 아니라 meta-path 하나로 만든 그래프에서** 돌았고 그중 최고치가 보고됐다. 따라서 HAN 대 GAT는 "여러 meta-path의 융합 대 최선의 단일 meta-path" 비교다. 이것을 "이종성 처리 대 미처리"의 비교로 읽으면 과하다. ESim은 HAN이 학습한 가중치를 받아 돌았다. baseline이 제안 모델의 산출물에 의존하는 순환 설정이다. 랜덤워크 계열은 노드 특징을 쓰지 않는 방법들이라, 이들 대비 격차의 상당 부분은 특징 사용에서 온다(논문도 §5.4에서 GNN 계열이 대체로 낫다고 인정한다). attention의 순수 기여는 GNN 계열·변형 모델과의 격차로 읽어야 한다. 분류에서 그 크기는 데이터셋별 최강 GNN baseline 대비 +0.45~+2.59(ACM은 GCN, IMDB는 GAT 기준)이고, 군집화에서는 ACM NMI +4.27까지 벌어진다.

### 6.3 inductive 주장 vs transductive 실험

§4.3은 파라미터가 그래프 규모에 의존하지 않으므로 "inductive 문제에 쓰일 수 있다"고 쓰고 inductive를 unseen 노드·그래프에 대한 임베딩 생성으로 정의하지만, §5의 실험은 전부 단일 그래프의 고정 분할 위 transductive 프로토콜이다. unseen 노드 실험은 없다. 구조적 근거(GAT처럼 파라미터가 그래프 크기와 무관)는 성립하나, 같은 문구의 전거로 인용된 GraphSAGE가 실제 unseen 노드 실험을 수행한 것과 대비된다. 새 노드의 meta-path 이웃을 얻으려면 인접행렬 곱을 다시 계산해야 한다는 실무 경로도 논문에는 없다. 같은 유형의 주장-실험 간극이 하나 더 있다: §1 기여 2는 "large-scale 이종 그래프에 적용 가능"을 주장하지만 세 데이터셋 모두 수천 노드 규모이고, 확장성은 복잡도 분석으로만 뒷받침된다.

### 6.4 군집화 평가의 비대칭

§5.5의 군집화는 분류 라벨로 **지도 학습한 임베딩**을, 같은 라벨을 정답 삼아 평가한다. DeepWalk·ESim·metapath2vec·HERec은 비지도 방법이므로, Table 4는 지도 신호를 받은 방법과 받지 않은 방법을 같은 기준으로 재는 구도다. 이 비대칭은 논문에서 언급되지 않는다. HAN 계열(GCN·GAT 포함)의 군집화 우위를 읽을 때 감안해야 한다.

## 7. 방법적 한계와 확장

### 7.1 논문이 남긴 것

§6 Conclusion에는 한계 서술도 future work도 없다. 전부 성과 요약이다("limitation"·"future" 계열 표현이 본문 전체에 없다). 대신 본문 곳곳에 저자가 사실상 인정한 약점이 흩어져 있다.

| 논문이 인정한 사실 | 위치 |
|---|---|
| DBLP에서 개선이 작다 — APCPA가 압도적이라 융합의 이득이 없다 | §5.4, §5.6 |
| ACM에서는 meta-path 성능이 비등해 단순 평균(HAN\(_{sem}\))도 잘 된다 | §5.6 |
| head 수를 늘려도 개선은 근소하다 | §5.8 |
| meta-path 집합은 모델의 입력이다 | Algorithm 1 |

앞의 두 항목을 붙여 읽으면, semantic-level attention이 이기는 조건은 "meta-path 간 품질 격차가 크지도(하나가 지배) 작지도(균등 평균으로 충분) 않은 중간 지대"로 좁아진다. 논문은 이를 attention의 해석력을 보여주는 사례로 소비하지만, 이후 "semantic attention이 정말 필요한가" 논쟁의 씨앗이 된 관찰이기도 하다(7.3절).

### 7.2 방법 내재적 한계 (논문 외 비판)

- **meta-path는 결국 사람이 고른다.** 3장 말미에서 본 대로 후보 집합은 입력이고, 학습되는 것은 후보 안의 가중치뿐이다. §1이 open problem이라 부른 "가장 유의미한 meta-path의 선택" 중 후보 생성 문제는 그대로 남는다. 논문 자신의 동기 예시가 이를 보여준다. §1은 Movie-Year-Movie를 예로 들지만, 정작 IMDB 실험 그래프에는 Year 타입이 없어서 그 의미는 모델이 볼 수조차 없다.
- **중간 노드 정보가 버려진다.** 이웃이 경로 양 끝점으로 정의되므로(Definition 3.3, 인접행렬 곱), MAM에서 두 영화를 잇는 배우의 특징은 attention에도 집계에도 들어가지 않는다. 실험에서는 타깃 타입에만 특징이 있으므로(4장), 타입 간 특징 공간을 통합한다는 Eq. 1의 설계 동기가 실험에서 한 번도 발동되지 않는다.
- **semantic 가중치가 전역이다.** \(\beta_{\Phi_p}\)는 전 노드 평균(Eq. 7)에서 나온 스칼라라, 노드마다 유효한 의미 관계가 다를 수 있다는 논문 자신의 국소성 직관(node-level의 동기)이 semantic 수준에는 적용되지 않는다.
- **임베딩되는 것은 타깃 타입뿐이다.** meta-path가 전부 대칭형이므로 conference·term·actor·director는 임베딩을 얻지 못한다. §4.3의 "여러 타입의 노드 임베딩이 상호 촉진한다"는 서술을 뒷받침하는 실험 구성이 아니다.
- **loss가 단일 과제 semi-supervised다.** β 자체가 과제 의존적이라고 논문이 명시하므로, 학습된 Z는 특정 과제에 조건화된 임베딩이다. 라벨 없는 상황을 위한 비지도 목적함수는 논문에 없다.

### 7.3 이후 계보 (논문 외 지식)

- **meta-path 유지·보완 노선:** MAGNN(Fu et al., 2020)은 HAN이 버리는 meta-path 중간 노드를 instance 인코더로 복원했다. GTN(Yun et al., 2019)은 meta-path 자체를 인접행렬의 소프트 선택·곱으로 자동 학습해 수동 지정을 없앴다.
- **meta-path-free 노선:** HetGNN(Zhang et al., 2019)은 restart 랜덤워크 샘플링으로, HGT(Hu et al., 2020)는 노드·관계 타입별 파라미터 분해로 meta-path 없이 이종성을 처리한다.
- **재평가:** Lv et al. (2021)의 HGB 벤치마크는 기존 이종 GNN 논문들의 동종 baseline이 부적절한 입력·튜닝으로 과소평가됐음을 지적했다. HAN의 "meta-path별 그래프에서 GCN/GAT 최고치 보고"(6.2절)가 대표 사례다. 전체 이종 그래프와 엣지 타입 임베딩을 받은 단순 GAT 변형(Simple-HGN)이 HAN을 포함한 다수 이종 GNN을 넘어섰다. 다만 HGB도 HAN의 문제 설정 기여와 semantic attention의 해석 도구로서의 가치는 부정하지 않으며, HAN은 이 분야에서 가장 많이 인용되는 논문 중 하나로 남아 있다.

시리즈 관점의 요약: 같은 이종 그래프 문제에서 HAN(사람이 의미론 지정, 가중치만 학습)과 HetGNN(샘플링으로 의미론 지정 회피)은 반대 노선이고, HGB 이후의 잠정 결론은 "엣지 타입 정보만 가볍게 주입한 GAT면 충분한 경우가 많다"는 제3의 답이다. 계층적 semantic attention 없이도 그만큼 됐다는 이 결과는, semantic attention이 이기는 조건이 좁다는 7.1절의 관찰과 이어진다.

### 7.4 위키·사회연결망 관점에서 (논문 외 해석)

HAN의 DBLP 실험은 사회연결망 언어로 번역할 가치가 있다. 저자의 연구 분야 식별에서 semantic attention은 APCPA(같은 학회에 투고한 저자들)에 최대 가중치를 주고 APA(공저)는 거의 무력하다고 판정한다(§5.6, Figure 5). 즉 "연구 정체성은 공저 유대보다 투고 장(venue)이라는 제도적 소속이 더 잘 예측한다"는 관찰이고, \(\beta_\Phi\)는 그 명제를 데이터에서 잰 측정값이다. 다만 4장에서 본 단서가 필요하다: DBLP의 분야 라벨 자체가 투고 학회에서 유도됐으므로, APCPA의 지배는 부분적으로 라벨 구성이 만든 결과이기도 하다. 이 관찰을 사회학적 명제로 일반화하려면 라벨이 독립적으로 정의된 데이터가 필요하다. HetGNN 리뷰 7.5절에서 본 공저 예측과 겹쳐 보면, 같은 학술 그래프에서도 과제(협업 예측 vs 분야 식별)에 따라 유효한 관계가 달라진다는 것을 두 논문이 각자의 방식으로 보여준다. 이 위키의 노트-링크 그래프에서 "노트-개념-노트"와 "직접 링크" 중 어느 관계가 군집 식별에 유효한가를 묻는다면, 그것이 바로 semantic-level attention이 형식화한 질문이다. 다만 이는 유비이지 적용 제안이 아니다.

## 8. 결론

HAN은 GAT의 attention을 meta-path로 유도된 이종 그래프에 이식하고, 그 위에 meta-path 중요도를 학습하는 semantic-level attention을 얹은 논문이다. 방법의 골격이 단순하고(GAT 층 P개 + 가중합) attention 값이 해석 도구로 기능한다는 것이 강점이며, §5.6 같은 meta-path 중요도 분석은 이후 이종 GNN 논문들이 즐겨 따라 하는 서사가 됐다(논문 외 관찰). 성능 주장은 데이터셋에 따라 강도가 다르고(ACM 뚜렷, DBLP 근소·동률), baseline 설정의 한계 때문에 이후 재평가에서 상당 부분 조정됐다. 그럼에도 "이종 그래프 + attention"이라는 문제 설정과 2층 계층 구조는 이 분야의 기준점으로 남았다.

읽는 법을 정리하면:

| 목적 | 어디를 읽나 |
|---|---|
| 계층적 attention의 구조 | §4.1–4.2, Figure 2–3, 이 글 3장 |
| GAT와의 정확한 관계 | §2.1·§4.1(Vaswani 인용), 이 글 1.3절·3장 |
| 성능 주장의 실제 강도 | Table 3–4를 §5.4의 요약 서술과 대조, 이 글 5장·6.1절 |
| baseline 설정의 함의 | §5.2의 "best performance" 문장, 이 글 6.2절 |
| meta-path 의존성 논쟁의 출발점 | Algorithm 1의 Input, §5.6, 이 글 7.1–7.3절 |

시리즈의 다음 연결로는, HAN이 버린 중간 노드를 복원한 MAGNN, meta-path를 학습으로 대체한 GTN, 그리고 이 분야의 실험 관행을 재점검한 HGB 논문이 자연스러운 후속이다.

## References

Dong, Y., Chawla, N. V., & Swami, A. (2017). metapath2vec: Scalable representation learning for heterogeneous networks. *Proceedings of the 23rd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 135–144. https://doi.org/10.1145/3097983.3098036 ([PDF 보기](/paper-viewer?title=metapath2vec%3A+Scalable+Representation+Learning+for+Heterogeneous+Networks&source=blog-reference&authors=Yuxiao+Dong%3BNitesh+V.+Chawla%3BAnanthram+Swami&year=2017&doi=10.1145%2F3097983.3098036&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3097983.3098036))

Fu, X., Zhang, J., Meng, Z., & King, I. (2020). MAGNN: Metapath aggregated graph neural network for heterogeneous graph embedding. *Proceedings of The Web Conference 2020*, 2331–2341. https://doi.org/10.1145/3366423.3380297 ([PDF 보기](/paper-viewer?title=MAGNN%3A+Metapath+Aggregated+Graph+Neural+Network+for+Heterogeneous+Graph+Embedding&source=blog-reference&authors=Xinyu+Fu%3BJiani+Zhang%3BZhongying+Meng%3BIrwin+King&year=2020&doi=10.1145%2F3366423.3380297&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3366423.3380297))

Hamilton, W., Bajaj, P., Zitnik, M., Jurafsky, D., & Leskovec, J. (2018). Embedding logical queries on knowledge graphs. *Advances in Neural Information Processing Systems*, *31*. https://arxiv.org/abs/1806.01445 ([PDF 보기](/paper-viewer?title=Embedding+Logical+Queries+on+Knowledge+Graphs&source=blog-reference&authors=William+L.+Hamilton%3BPrajit+Bajaj%3BMarinka+Zitnik%3BDan+Jurafsky%3BJure+Leskovec&year=2018&arxiv_id=1806.01445&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1806.01445.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F1806.01445))

Hamilton, W., Ying, Z., & Leskovec, J. (2017). Inductive representation learning on large graphs. *Advances in Neural Information Processing Systems*, *30*. https://arxiv.org/abs/1706.02216 ([PDF 보기](/paper-viewer?title=Inductive+Representation+Learning+on+Large+Graphs&source=blog-reference&authors=William+L.+Hamilton%3BRex+Ying%3BJure+Leskovec&year=2017&arxiv_id=1706.02216&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1706.02216.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F1706.02216))

Hu, Z., Dong, Y., Wang, K., & Sun, Y. (2020). Heterogeneous graph transformer. *Proceedings of The Web Conference 2020*, 2704–2710. https://doi.org/10.1145/3366423.3380027 ([PDF 보기](/paper-viewer?title=Heterogeneous+Graph+Transformer&source=blog-reference&authors=Ziniu+Hu%3BYuxiao+Dong%3BKuansan+Wang%3BYizhou+Sun&year=2020&doi=10.1145%2F3366423.3380027&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3366423.3380027))

Kipf, T. N., & Welling, M. (2017). Semi-supervised classification with graph convolutional networks. *International Conference on Learning Representations*. https://arxiv.org/abs/1609.02907 ([PDF 보기](/paper-viewer?title=Semi-Supervised+Classification+with+Graph+Convolutional+Networks&source=blog-reference&authors=Thomas+N.+Kipf%3BMax+Welling&year=2017&arxiv_id=1609.02907&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1609.02907.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F1609.02907))

Lv, Q., Ding, M., Liu, Q., Chen, Y., Feng, W., He, S., Zhou, C., Jiang, J., Dong, Y., & Tang, J. (2021). Are we really making much progress? Revisiting, benchmarking and refining heterogeneous graph neural networks. *Proceedings of the 27th ACM SIGKDD Conference on Knowledge Discovery & Data Mining*, 1150–1160. https://doi.org/10.1145/3447548.3467350 ([PDF 보기](/paper-viewer?title=Are+We+Really+Making+Much+Progress%3F+Revisiting%2C+Benchmarking%2C+and+Refining+Heterogeneous+Graph+Neural+Networks&source=blog-reference&authors=Qiaoyu+Lv%3BMing+Ding%3BQiang+Liu%3BYuxiang+Chen%3BWenqiang+Feng%3BSiming+He%3BChang+Zhou%3BJianguo+Jiang%3BYuxiao+Dong%3BJie+Tang&year=2021&doi=10.1145%2F3447548.3467350&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3447548.3467350))

Perozzi, B., Al-Rfou, R., & Skiena, S. (2014). DeepWalk: Online learning of social representations. *Proceedings of the 20th ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 701–710. https://doi.org/10.1145/2623330.2623732 ([PDF 보기](/paper-viewer?title=DeepWalk%3A+Online+Learning+of+Social+Representations&source=blog-reference&authors=Bryan+Perozzi%3BRami+Al-Rfou%3BSteven+Skiena&year=2014&doi=10.1145%2F2623330.2623732&arxiv_id=1403.6652&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1403.6652.pdf&url=https%3A%2F%2Fdoi.org%2F10.1145%2F2623330.2623732))

Shang, J., Qu, M., Liu, J., Kaplan, L. M., Han, J., & Peng, J. (2016). *Meta-path guided embedding for similarity search in large-scale heterogeneous information networks*. arXiv. https://arxiv.org/abs/1610.09769 ([PDF 보기](/paper-viewer?title=Meta-Path+Guided+Embedding+for+Similarity+Search+in+Large-Scale+Heterogeneous+Information+Networks&source=blog-reference&authors=Jian+Shang%3BMeng+Qu%3BJialu+Liu%3BLance+M.+Kaplan%3BJiawei+Han%3BJian+Peng&year=2016&arxiv_id=1610.09769&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1610.09769.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F1610.09769))

Shi, C., Hu, B., Zhao, W. X., & Yu, P. S. (2019). Heterogeneous information network embedding for recommendation. *IEEE Transactions on Knowledge and Data Engineering*, *31*(2), 357–370. https://doi.org/10.1109/TKDE.2018.2833443 ([PDF 보기](/paper-viewer?title=Heterogeneous+Information+Network+Embedding+for+Recommendation&source=blog-reference&authors=Chuan+Shi%3BBinbin+Hu%3BWayne+Xin+Zhao%3BPhilip+S.+Yu&year=2019&doi=10.1109%2FTKDE.2018.2833443&url=https%3A%2F%2Fdoi.org%2F10.1109%2FTKDE.2018.2833443))

Sun, Y., & Han, J. (2013). Mining heterogeneous information networks: A structural analysis approach. *ACM SIGKDD Explorations Newsletter*, *14*(2), 20–28. https://doi.org/10.1145/2481244.2481248 ([PDF 보기](/paper-viewer?title=Mining+Heterogeneous+Information+Networks%3A+A+Structural+Analysis+Approach&source=blog-reference&authors=Yizhou+Sun%3BJiawei+Han&year=2013&doi=10.1145%2F2481244.2481248&url=https%3A%2F%2Fdoi.org%2F10.1145%2F2481244.2481248))

Sun, Y., Han, J., Yan, X., Yu, P. S., & Wu, T. (2011). PathSim: Meta path-based top-k similarity search in heterogeneous information networks. *Proceedings of the VLDB Endowment*, *4*(11), 992–1003. https://doi.org/10.14778/3402707.3402736 ([PDF 보기](/paper-viewer?title=PathSim%3A+Meta+Path-Based+Top-K+Similarity+Search+in+Heterogeneous+Information+Networks&source=blog-reference&authors=Yizhou+Sun%3BJiawei+Han%3BXifeng+Yan%3BPhilip+S.+Yu%3BTianyi+Wu&year=2011&doi=10.14778%2F3402707.3402736&url=https%3A%2F%2Fdoi.org%2F10.14778%2F3402707.3402736))

Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, Ł., & Polosukhin, I. (2017). Attention is all you need. *Advances in Neural Information Processing Systems*, *30*. https://arxiv.org/abs/1706.03762 ([PDF 보기](/paper-viewer?title=Attention+Is+All+You+Need&source=blog-reference&authors=Ashish+Vaswani%3BNoam+Shazeer%3BNiki+Parmar%3BJakob+Uszkoreit%3BLlion+Jones%3BAidan+N.+Gomez%3B%C5%81ukasz+Kaiser%3BIllia+Polosukhin&year=2017&arxiv_id=1706.03762&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1706.03762.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F1706.03762))

Veličković, P., Cucurull, G., Casanova, A., Romero, A., Liò, P., & Bengio, Y. (2018). Graph attention networks. *International Conference on Learning Representations*. https://arxiv.org/abs/1710.10903 ([PDF 보기](/paper-viewer?title=Graph+Attention+Networks&source=blog-reference&authors=Petar+Veli%C4%8Dkovi%C4%87%3BGuillem+Cucurull%3BArantxa+Casanova%3BAdriana+Romero%3BPietro+Li%C3%B2%3BYoshua+Bengio&year=2018&arxiv_id=1710.10903&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1710.10903.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F1710.10903))

Wang, X., Ji, H., Shi, C., Wang, B., Ye, Y., Cui, P., & Yu, P. S. (2019). Heterogeneous graph attention network. *The World Wide Web Conference*, 2022–2032. https://doi.org/10.1145/3308558.3313562 ([PDF 보기](/paper-viewer?title=Heterogeneous+Graph+Attention+Network&source=blog-reference&authors=Xiao+Wang%3BHouye+Ji%3BChuan+Shi%3BBai+Wang%3BYanfang+Ye%3BPeng+Cui%3BPhilip+S.+Yu&year=2019&doi=10.1145%2F3308558.3313562&arxiv_id=1903.07293&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1903.07293.pdf&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3308558.3313562))

Yun, S., Jeong, M., Kim, R., Kang, J., & Kim, H. J. (2019). Graph transformer networks. *Advances in Neural Information Processing Systems*, *32*. https://arxiv.org/abs/1911.06455 ([PDF 보기](/paper-viewer?title=Graph+Transformer+Networks&source=blog-reference&authors=Seongjun+Yun%3BMinbyul+Jeong%3BRaehyun+Kim%3BJaewoo+Kang%3BHyunwoo+J.+Kim&year=2019&arxiv_id=1911.06455&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1911.06455.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F1911.06455))

Zhang, C., Song, D., Huang, C., Swami, A., & Chawla, N. V. (2019). Heterogeneous graph neural network. *Proceedings of the 25th ACM SIGKDD International Conference on Knowledge Discovery & Data Mining*, 793–803. https://doi.org/10.1145/3292500.3330961 ([PDF 보기](/paper-viewer?title=Heterogeneous+Graph+Neural+Network&source=blog-reference&authors=Chuxu+Zhang%3BDongjin+Song%3BChao+Huang%3BAnanthram+Swami%3BNitesh+V.+Chawla&year=2019&doi=10.1145%2F3292500.3330961&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3292500.3330961))
