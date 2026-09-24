# HetGNN 심층 분석: "Heterogeneous Graph Neural Network" 논문 해설

**Paper:** Zhang, Chuxu; Song, Dongjin; Huang, Chao; Swami, Ananthram; Chawla, Nitesh V. (2019). "Heterogeneous Graph Neural Network." *Proceedings of the 25th ACM SIGKDD International Conference on Knowledge Discovery & Data Mining (KDD '19)*, pp. 793–803. https://doi.org/10.1145/3292500.3330961. Code: github.com/chuxuzhang/KDD2019_HetGNN (arXiv 판 없음)

**HetGNN**은 restart 랜덤워크 기반 타입별 이웃 샘플링, Bi-LSTM 콘텐츠 인코딩, 타입 단위 attention 결합으로 이종 그래프의 구조·콘텐츠 이질성을 동시에 인코딩하는 inductive 노드 임베딩 프레임워크다(Zhang et al., KDD 2019). meta-path 지정 없이 링크 예측에서 최강 baseline 대비 학술 데이터 최대 5.6% AUC·F1을 개선했다.

**Abstract:** 본 문서는 이종 그래프(heterogeneous graph)를 위한 초기 GNN 모델인 HetGNN 논문을 해설한다. 논문의 문제 설정은 노드 타입·관계 타입이 여럿이고 노드마다 텍스트·이미지 같은 비정형 콘텐츠가 붙은 그래프에서, 구조 이질성과 콘텐츠 이질성을 동시에 인코딩하는 범용 임베딩을 학습하는 것이다. 해법은 세 부품의 결합이다: restart 랜덤워크로 타입별 고정 크기 이웃을 샘플링하고(C1), 노드별 이질 콘텐츠를 Bi-LSTM으로 인코딩하고(C2), 같은 타입 이웃을 Bi-LSTM으로 집계한 뒤 타입 단위 attention으로 결합한다(C3). 학술 그래프(AMiner) 2종과 리뷰 그래프(Amazon) 2종에서 링크 예측·추천·분류·군집화와 inductive 과제를 실험해 5개 baseline 대비 우위를 보고했다. 다만 transductive 군집화에서는 GraphSAGE에 뒤지고, "end-to-end" 주장과 사전학습 특징 고정 사이의 간극, 신규 노드의 특징 처리 미기재 등 읽을 때 주의할 서술 공백이 있다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 노드·관계 타입이 여럿이고 노드마다 이질적 비정형 콘텐츠가 붙은 그래프에서, 구조와 콘텐츠의 이질성을 동시에 담는 범용 노드 임베딩을 어떻게 학습하는가? |
| 핵심 기여 | restart 랜덤워크 기반 타입별 이웃 샘플링 + 타입별 Bi-LSTM 콘텐츠 인코딩 + 타입 단위 attention 결합이라는 3모듈 구조로, meta-path 지정 없이 이종 그래프의 inductive 임베딩을 만든다. |
| 방법적 결과 | \(f_1(v)\)(콘텐츠 인코딩) → \(f_2^t(v)\)(타입별 이웃 집계) → \(\mathcal{E}_v = \alpha^{v,v}f_1(v) + \sum_t \alpha^{v,t}f_2^t(v)\)(attention 결합)를 skip-gram형 graph context loss로 학습한다(Eq. 1–11). |
| 실험 결과 | 저자 보고 기준 링크 예측 성능(AUC·F1)을 최강 baseline 대비 학술 데이터에서 1.5–5.6%, 리뷰 데이터에서 3.4–10.5% 개선, inductive 군집화에서 GraphSAGE 대비 평균 17.3% 개선(Tables 3–6). |
| 핵심 한계 | transductive 군집화는 GraphSAGE에 열세(NMI 0.901 vs 0.914). 무순서 집합에 Bi-LSTM을 쓰는 설계의 순서 처리, 신규 노드의 사전학습 특징 처리가 본문·부록 어디에도 없다. 반복 실행·유의성 검정도 없다. |

**TL;DR** — (1) HetGNN은 meta-path 지정 없이 이종 그래프의 구조 이질성과 콘텐츠 이질성을 동시에 담는 inductive 노드 임베딩을 학습하는 프레임워크다. (2) 링크 예측 AUC·F1에서 최강 baseline 대비 학술 데이터 최대 5.6%, 리뷰 데이터 최대 10.5% 개선, inductive 군집화에서 GraphSAGE 대비 평균 17.3% 개선을 보고했다. (3) transductive 군집화에서는 GraphSAGE에 뒤지며(NMI 0.901 vs 0.914), 무순서 이웃에 Bi-LSTM을 적용하는 설계 선택과 신규 노드의 특징 처리 방식이 재검토 대상이다.

## 목차

1. 서론
2. 예비 지식
3. HetGNN 프레임워크
4. 실험 설정
5. 실험 결과
6. 주의해서 읽을 점
7. 방법적 한계와 확장
8. 결론

---

## 1. 서론

### 1.1 연구 배경

이 시리즈에서 지금까지 다룬 논문들은 모두 **동종(homogeneous) 그래프**를 전제한다. DeepWalk·node2vec은 노드별 임베딩 벡터를 직접 최적화하는 shallow 방식이고, GraphSAGE·GAT·GIN은 이웃의 feature를 신경망으로 집계한다. 그런데 실제 그래프의 상당수는 노드 타입부터 여럿이다. 학술 그래프에는 저자·논문·학회가 있고, 각 타입 사이의 관계(집필, 인용, 게재)도 다르며, 노드에는 초록 텍스트나 상품 사진 같은 비정형 콘텐츠가 붙는다. 논문은 이런 대상을 **content-associated heterogeneous graph(C-HetG)**로 정의하고(§2, Definition 2.1), 그 위의 표현학습을 다룬다.

논문이 정리하는 선행 지형은 세 갈래다(§1, §5). 이종 그래프용 shallow 임베딩(metapath2vec)은 타입은 다루지만 콘텐츠를 못 보고, 속성 그래프 임베딩(ASNE, SHNE)은 콘텐츠 일부를 보지만 이질 콘텐츠 전부를 다루지 못하거나 inductive가 안 되며, GNN(GraphSAGE, GAT)은 콘텐츠와 inductive를 다루지만 동종 그래프에 집중되어 있다. Abstract의 표현으로는, 기존 연구 중 "구조 이질성과 노드별 콘텐츠 이질성을 함께 효과적으로 고려하는 것은 드물다"는 것이 문제의식이다.

### 1.2 핵심 질문

논문은 이 공백을 세 개의 도전과제로 쪼갠다(§1, Figure 1(b)). 이 셋이 곧 모델의 세 모듈에 1:1로 대응하므로, 이 글 전체의 뼈대이기도 하다.

- **C1 — 이웃 샘플링:** 이종 그래프의 많은 노드는 모든 타입의 이웃과 직접 연결되어 있지 않다(예: 저자는 학회와 직접 연결이 없다). 이웃 수도 노드마다 다르다. 임베딩에 강하게 상관된 이질적 이웃을 어떻게 샘플링하는가?
- **C2 — 콘텐츠 인코딩:** 노드 콘텐츠는 attributes·text·image처럼 비정형이고, 타입마다 조합이 다르다. 단순 연결이나 선형 변환으로는 콘텐츠 간 깊은 상호작용을 담지 못한다. 콘텐츠 이질성을 다루는 인코더를 어떻게 설계하는가?
- **C3 — 타입별 집계:** 이웃 타입마다 기여가 다르다(저자 임베딩에는 학회보다 저자·논문 이웃이 더 중요하다는 것이 논문의 예시). 타입별 영향을 반영해 이웃을 어떻게 결합하는가?

![HetGNN Figure 1: academic/review graph and challenges C1–C3](/api/blog/figures/hetgnn-fig1-challenges.png)

*그림 1 — 원논문 Figure 1: (a) 학술 그래프와 리뷰 그래프의 예시, (b) 노드 a를 중심으로 본 세 도전과제 C1(이웃 샘플링)–C2(콘텐츠 인코딩)–C3(타입별 집계).*

### 1.3 학술적 위치

논문의 Table 1은 자신과 6개 모델을 5개 속성으로 비교한다. RL(표현학습), HG(이종 그래프), C(콘텐츠 인지), HC(이질 콘텐츠 인지), I(inductive)다.

| 속성 | DeepWalk | metapath2vec | ASNE | SHNE | GraphSAGE | GAT | HetGNN |
|---|---|---|---|---|---|---|---|
| RL | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| HG | ✗ | ✓ | ✗ | ✓ | ✗ | ✗ | ✓ |
| C | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ |
| HC | ✗ | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ |
| I | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ |

이 표에서 논문이 주장하는 자리는 "HG·HC·I를 동시에 만족하는 유일한 모델"이다. 이종 그래프를 다루는 것은 metapath2vec·SHNE·HetGNN 셋뿐인데 앞의 둘은 inductive가 안 되고, 반대로 GraphSAGE·GAT는 inductive지만 이종 그래프를 다루지 않는다는 구도다.

시리즈 관점에서 보면 HetGNN은 GraphSAGE의 설계를 이종 그래프로 옮긴 논문에 가깝다. 무순서 집합에 Bi-LSTM을 적용하는 장치는 논문 스스로 GraphSAGE에서 착안했다고 두 곳에서 밝히고(§3.2, §3.3.1의 "inspired by [7]"), 고정 크기 이웃 샘플링이라는 틀도 GraphSAGE와 나란하다(이 대응 자체는 논문 외 관찰이다). 타입 결합에는 GAT의 attention을 가져다 쓴다(§3.3.2의 "we employ the attention mechanism [31]"). **논문 외 관찰:** 비교 대상이자 계승 대상인 metapath2vec의 저자 중 Chawla와 Swami가 이 논문의 공저자이기도 하다. metapath2vec이 만든 이종 그래프 임베딩의 틀(타입 인지 skip-gram)을 같은 그룹이 GNN으로 확장한 흐름으로 읽힌다.

## 2. 예비 지식

### 2.1 C-HetG와 문제 정의

**Definition 2.1 (C-HetG):** \(G = (V, E, O_V, R_E)\). \(O_V\)는 노드 타입 집합, \(R_E\)는 관계 타입 집합인 다중 타입 그래프에, 노드별 이질 콘텐츠(attributes, text, image)가 붙은 것이다(§2). 정의 바로 뒤에서 논문은 user–item 두 타입뿐인 이분 리뷰 그래프도 \(|O_V| + |R_E| \ge 3\)이므로 C-HetG에 든다고 밝힌다. 판정 기준은 노드 타입 수 단독이 아니라 노드 타입과 관계 타입의 합계다.

**Problem 1:** C-HetG가 주어질 때 파라미터 \(\Theta\)의 모델 \(\mathcal{F}_\Theta\)를 설계해, 구조적 근접성과 비정형 콘텐츠를 동시에 인코딩하는 d차원 임베딩(\(d \ll |V|\))을 학습한다(§2). 특정 과제용이 아니라 링크 예측·추천·분류·군집화에 두루 쓰이는 범용 임베딩이 목표다. 그래서 뒤에서 task-supervised loss가 아닌 graph context loss(§3.4)를 쓴다.

### 2.2 Random Walk with Restart (RWR)

일반 랜덤워크가 매 스텝 이웃으로만 이동하는 것과 달리, RWR은 매 스텝 확률 \(p\)로 시작 노드로 되돌아간다. 원래 그래프에서 두 노드의 근접도를 재는 도구로 쓰이던 기법이다(Pan et al., 2004). 복귀 덕분에 워크가 시작 노드 주변에 머물면서도, 여러 홉을 오가며 직접 연결이 없는 타입의 노드에도 닿는다. HetGNN은 이 성질을 이웃 샘플링에 쓴다(§3.1).

### 2.3 Bi-LSTM

LSTM은 입력 시퀀스를 순서대로 읽으며 게이트(input·forget·output)로 은닉 상태를 갱신하는 RNN이고, Bi-LSTM은 시퀀스를 정방향·역방향으로 각각 읽은 은닉 상태를 이어 붙인 것이다. HetGNN에서는 은닉 상태 \(h_i \in \mathbb{R}^{(d/2) \times 1}\)로 두어 양방향 연결 후 차원이 \(d\)가 되게 한다(Eq. 2). HetGNN은 본래 순서 있는 데이터용인 이 구조를 순서 없는 집합에 적용하는데, 거기서 생기는 문제는 7.2절에서 다룬다.

### 2.4 Graph context loss와 negative sampling

word2vec의 skip-gram을 그래프로 옮긴, DeepWalk 이래의 표준 무감독 목적함수다: 랜덤워크에서 함께 등장한 노드 쌍(문맥 창 거리 \(\tau\) 이내)의 임베딩 내적은 크게, 무작위로 뽑은 negative 쌍의 내적은 작게 만든다. softmax 분모의 전체 노드 합산을 피하기 위해 negative sampling으로 근사한다(loss의 도출은 blog/deepwalk 3장, negative sampling 근사는 blog/node2vec 2장). HetGNN의 변형은 softmax 분모와 negative 샘플을 **같은 타입의 노드로 한정**한다는 것이다(§3.4).

## 3. HetGNN 프레임워크

원논문 §3에 해당한다. 아래 그림 2가 전체 구조다: 이웃 샘플링 → 콘텐츠 인코딩(NN-1) → 같은 타입 이웃 집계(NN-2) → 타입 결합(NN-3) → graph context loss.

![HetGNN Figure 2: overall architecture NN-1/NN-2/NN-3](/api/blog/figures/hetgnn-fig2-architecture.png)

*그림 2 — 원논문 Figure 2: (a) 전체 파이프라인, (b) NN-1 콘텐츠 인코딩, (c) NN-2 같은 타입 이웃 집계, (d) NN-3 attention 타입 결합.*

### 이질적 이웃 샘플링 (원논문 §3.1)

기존 GNN처럼 1차 이웃만 집계하면 이종 그래프에서 세 가지가 걸린다(§3.1): 직접 연결이 없는 타입의 이웃을 못 보고, 이웃 수 편차 때문에 hub 노드(이웃이 매우 많은 노드)는 약하게 상관된 "noise" 이웃에 시달리고 cold-start 노드(이웃이 거의 없는 노드)는 정보가 모자라며, 콘텐츠 구성이 제각각인 이웃들을 하나의 변환으로 집계하기 어렵다.

해법은 두 단계다.

- **Step-1 — RWR 샘플링:** 노드 \(v\)에서 확률 \(p\)로 복귀하는 랜덤워크를 돌려 고정 개수의 노드를 수집한다(\(RWR(v)\)). 이때 타입별 수집 개수에 제약을 걸어 모든 타입이 반드시 샘플에 들어오게 한다. 실험 설정은 \(p = 0.5\), \(|RWR(v)| = 100\)이다(§A.4).
- **Step-2 — 타입별 top-\(k_t\) 선별:** 각 타입 \(t\)에 대해 \(RWR(v)\) 안에서 방문 빈도 상위 \(k_t\)개를 골라 \(v\)의 \(t\)-타입 이웃 집합 \(N_t(v)\)로 삼는다. 실험에서는 학술 그래프 총 23개(저자 10, 논문 10, 학회 3), 리뷰 그래프 총 20개(유저 10, 아이템 10)다(§4.1.3, §A.4).

논문이 명시한 해결 논리는 세 가지다(§3.1 말미): RWR의 복귀 성질 덕분에 모든 타입의 고차 이웃이 수집되고(직접 미연결 타입 포함), 샘플 크기가 노드마다 고정되며 빈도 필터가 약한 이웃을 걸러내고(hub와 cold-start 문제의 완화), 같은 타입끼리 그룹핑되어 타입별 집계가 가능해진다. 이웃이 1차 연결이 아니라 "RWR이 자주 방문한 노드"로 재정의된다는 것이 GraphSAGE의 uniform 샘플링과의 차이다.

### 이질적 콘텐츠 인코딩 — NN-1 (원논문 §3.2)

노드 \(v\)의 콘텐츠 집합 \(C_v\)의 각 항목 \(x_i \in \mathbb{R}^{d_f \times 1}\)는 종류별로 사전학습된 특징이다: 텍스트는 Par2Vec(paragraph vector), 이미지는 CNN으로 사전학습한다(§3.2). 인코딩은

\[ f_1(v) = \frac{\sum_{i \in C_v} \left[ \overrightarrow{\mathrm{LSTM}}\{\mathcal{FC}_{\theta_x}(x_i)\} \oplus \overleftarrow{\mathrm{LSTM}}\{\mathcal{FC}_{\theta_x}(x_i)\} \right]}{|C_v|} \quad \text{(Eq. 1)} \]

콘텐츠 종류별 변환기 \(\mathcal{FC}_{\theta_x}\)(원문은 identity일 수도, FC 층일 수도 있다고 명시한다)로 차원을 맞춘 뒤 Bi-LSTM에 통과시키고, 모든 은닉 상태를 평균해 \(f_1(v) \in \mathbb{R}^{d \times 1}\)을 얻는다. 변환기는 콘텐츠 종류별로, Bi-LSTM은 노드 타입별로 따로 두는데(같은 타입 노드끼리는 공유), 이 공유 범위가 C2에 대한 직접 응답이다. 논문이 드는 장점은 셋이다: 파라미터가 적어 구현·튜닝이 쉽고, 이질 콘텐츠를 융합해 표현력이 강하고, 새 콘텐츠 종류를 추가하기 쉽다(§3.2 말미).

순서가 없는 집합 \(C_v\)에 순서 의존적인 Bi-LSTM을 쓰는 근거로 논문은 GraphSAGE의 LSTM aggregator에서 착안했다는 것만 밝힌다(§3.2). 순서를 어떻게 정하는지는 본문에도 부록에도 없다(7장에서 재론).

### 타입별 이웃 집계와 결합 — NN-2·NN-3 (원논문 §3.3)

**같은 타입 이웃 집계(NN-2, §3.3.1):** \(t\)-타입 이웃 집합 \(N_t(v)\)의 콘텐츠 임베딩들을 집계한다. 집계 함수는 무엇이든 될 수 있으나 "실전 성능"을 이유로 Bi-LSTM을 채택한다:

\[ f_2^t(v) = \frac{\sum_{v' \in N_t(v)} \left[ \overrightarrow{\mathrm{LSTM}}\{f_1(v')\} \oplus \overleftarrow{\mathrm{LSTM}}\{f_1(v')\} \right]}{|N_t(v)|} \quad \text{(Eq. 4)} \]

여기서도 이웃 타입별로 다른 Bi-LSTM을 쓰고, 무순서 집합 적용의 근거는 GraphSAGE다(§3.3.1).

**타입 결합(NN-3, §3.3.2):** 타입별 집계 임베딩 \(|O_V|\)개와 \(v\) 자신의 콘텐츠 임베딩을 attention으로 섞는다.

\[ \mathcal{E}_v = \alpha^{v,v} f_1(v) + \sum_{t \in O_V} \alpha^{v,t} f_2^t(v) \quad \text{(Eq. 5)} \]

후보 집합은 \(\mathcal{F}(v) = \{f_1(v)\} \cup \{f_2^t(v) : t \in O_V\}\)로 self가 명시적으로 포함되고, 가중치는 GAT식으로 계산한다: \(\alpha^{v,i} = \mathrm{softmax}\big(\mathrm{LeakyReLU}(u^T [f_i \oplus f_1(v)])\big)\), \(u \in \mathbb{R}^{2d \times 1}\)(Eq. 6). GAT와 다른 점이 둘 있다. attention이 이웃 노드 단위가 아니라 **타입 단위**에 걸리고(학술 그래프면 후보가 self 포함 4개뿐이다), query가 항상 자기 콘텐츠 임베딩 \(f_1(v)\)다. 콘텐츠·집계·출력 임베딩은 모두 같은 차원 \(d\)를 쓴다(§3.3 말미).

### 목적함수와 학습 (원논문 §3.4)

skip-gram형 graph context loss를 쓰되(Eq. 7) softmax를 타입별로 나눈다. 문맥 노드 \(v_c\)의 조건부 확률은 **heterogeneous softmax**로, 분모가 전체 노드가 아니라 같은 타입의 노드 집합 \(V_t\)에 대한 합이다(Eq. 8). Eq. 8은 \(\mathcal{E}_v = \mathcal{F}_\Theta(v)\)도 함께 명시한다. 임베딩이 노드별 lookup이 아니라 모델(NN-1~3)의 출력이라는 뜻으로, DeepWalk 계열과 같은 loss를 쓰면서도 inductive 추론이 되는 이유가 이 한 줄에 있다. negative sampling 근사(Eq. 9–10)에서 negative도 같은 타입에서 뽑으며, 노이즈 분포는 walk 내 빈도의 3/4승에 비례한다(\(P_t(v_{c'}) \propto dg_{v_{c'}}^{3/4}\)). negative 샘플 수는 \(M = 1\)로 두는데, \(M > 1\)이어도 영향이 거의 없다고만 적고 뒷받침 실험은 없다(§3.4).

학습 삼중항 \(\langle v, v_c, v_{c'} \rangle\)은 균일 랜덤워크(노드당 10개, 길이 30)에서 문맥 창 \(\tau = 5\)로 수집하고(§A.4), 최종 목적함수(Eq. 11)를 Adam으로 mini-batch 학습한다(§3.4). 부록의 의사코드(§A.1, Algorithm 1)는 걷기 집합 \(T_{walk}\)를 입력으로 받으므로 워크는 학습 전에 한 번 수집해 고정된다. learning rate와 batch size는 본문에도 부록에도 없다.

## 4. 실험 설정

원논문 §4.1에 해당한다.

### 데이터셋 (Table 2)

| 데이터 | 출처·범위 | 노드 | 엣지 |
|---|---|---|---|
| A-I | AMiner 논문 1996–2005 | 저자 160,713 / 논문 111,409 / 학회 150 | 저자–논문 295,103 / 논문–논문 138,464 / 논문–학회 111,409 |
| A-II | AMiner 논문 2006–2015 | 저자 28,646 / 논문 21,044 / 학회 18 | 저자–논문 69,311 / 논문–논문 46,931 / 논문–학회 21,044 |
| R-I | Amazon Movies | 유저 18,340 / 아이템 56,361 | 유저–아이템 629,125 |
| R-II | Amazon CDs | 유저 16,844 / 아이템 106,892 | 유저–아이템 555,050 |

A-II는 AI·데이터 분야 상위 학회 18곳(KDD, ICML, CVPR, ACL 등)의 논문만 뽑은 부분집합이고(§A.2), Amazon 데이터의 기간은 1996년 5월–2014년 7월이다(§A.2). 학술 그래프만 3개 타입·3개 관계를 다 갖추고 있고, 리뷰 그래프는 타입 2개·관계 1개의 이분 그래프다. Definition 2.1의 \(|O_V| + |R_E| \ge 3\)을 턱걸이로 충족하는 사례로, 7.2절에서 되짚는다.

### 콘텐츠 특징 구성 (§4.1.3, §A.4)

학술 노드의 콘텐츠는 논문 제목·초록의 Par2Vec 특징과 **DeepWalk로 사전학습한 노드 임베딩**이고, 리뷰 노드는 상품 설명 텍스트·상품 사진(CNN 특징)·사전학습 노드 임베딩이다. 콘텐츠 인코더에 들어가는 항목 수는 부록 기준 저자 3, 논문 5(사전학습 임베딩·제목·초록·저자 평균·학회), 학회 3, 유저 3, 아이템 3이다(§A.4). DeepWalk 임베딩이 "콘텐츠"로 들어간다는 설정은 6.2절에서 다시 본다.

### Baseline과 공정성 장치 (§4.1.2, §A.4)

baseline은 5종이다: metapath2vec(MP2V; Dong et al., 2017), ASNE(Liao et al., 2018), SHNE(Zhang, Swami, & Chawla, 2019), GraphSAGE(GSAGE; Hamilton et al., 2017), GAT(Veličković et al., 2018). Table 1에 있던 DeepWalk는 실험 baseline에는 없다. 비교가 공정했는지는 부록의 설정에 상당 부분 달려 있다(§A.4): GSAGE와 GAT에는 HetGNN과 **같은 입력 특징(연결한 형태)과 같은 샘플 이웃 집합**을 주었고, MP2V의 meta-path는 학술 APA·APVPA·APPA, 리뷰 UIU이며, 모든 모델의 임베딩 차원은 128로 통일했다. 즉 GNN baseline들은 "1차 이웃"이 아니라 HetGNN의 RWR 이웃 위에서 돌았다. 다만 GSAGE·GAT를 어떤 loss(지도 vs 무감독)로 학습시켰는지는 부록에도 없다.

### 과제와 프로토콜 (§4.2)

네 과제를 쓴다. (1) **링크 예측**(§4.2.1): 무작위 링크 분할이 아니라 시간순 분할이다. 학술은 연도 \(T_s\) 이전/이후(A-I은 2003·2002, A-II는 2013·2012), 리뷰는 리뷰 수 기준 7:3과 5:5. 평가는 train 노드 사이의 신규 링크만 대상으로, 같은 수의 무작위 비연결 쌍을 negative로 섞고, 링크 임베딩(두 노드 임베딩의 원소별 곱)에 binary logistic 분류기를 얹는다. 링크 타입은 저자–저자 협업(type-1)과 저자–논문 인용(type-2). (2) **추천**(§4.2.2): 학회 추천이다. 임베딩 내적 점수로 top-k(A-I은 5, A-II는 3) 리스트를 만들고, test 기간에 실제 게재한 학회를 정답으로 삼아 Rec/Pre/F1을 전체 평가 저자 평균으로 계산한다. (3) **분류·군집화**(§4.2.3): A-II 저자를 4개 도메인(DM·CV·NLP·DB, 각 도메인 상위 학회 3곳 게재 다수결)으로 라벨링, 로지스틱 회귀(train 10%/30%)와 k-means. (4) **inductive 분류·군집화**(§4.2.4): A-II를 2013년으로 잘라 train으로 학습한 모델로 test의 신규 노드 임베딩을 추론해 같은 평가를 반복한다. 구현은 PyTorch이고 GPU에서 실험했다(§4.1.3).

## 5. 실험 결과

### 5.1 링크 예측 (Table 3)

HetGNN이 24개 셀(데이터·분할·링크 타입·지표 조합) 전부에서 최고다. 대표 수치로 A-II 2013 인용 예측은 AUC 0.767/F1 0.754로 최강 baseline GAT(0.732/0.705)를 앞서고, R-I 5:5는 AUC 0.749/F1 0.735로 GAT(0.683/0.665)를 앞선다. 상대 개선율은 학술 1.5–5.6%, 리뷰 3.4–10.5%(§4.2.1). 2위는 GAT인 경우가 가장 많다. 개선 폭은 리뷰 그래프에서 더 큰데, 논문은 그 이유를 따로 설명하지 않는다. 리뷰 노드의 콘텐츠 구성(텍스트+이미지)이 더 풍부하다는 설정(§4.1.3)과 연결해 읽는 것은 논문 외 해석이다.

### 5.2 추천 (Table 4)

학술 데이터의 학회 추천 12개 셀 전부에서 최고이고, 최강 baseline은 대체로 SHNE다. 상대 개선율은 2.8–16.0%(§4.2.2)인데, 최대치 16.0%는 A-I 2003의 Precision(SHNE 0.081 → HetGNN 0.094)에서 나온다. 절대값이 작은 지표의 상대 개선율임을 감안하고 읽어야 한다. A-II 2012는 F1 0.327 → 0.368(+12.5%) 수준이다.

### 5.3 Transductive 분류·군집화 (Table 5)

여기서는 그림이 달라진다. 분류는 거의 모든 모델이 0.95 이상이다. 4개 도메인의 저자들이 서로 매우 달라 과제가 쉽다고 논문 스스로 설명한다(§4.2.3). HetGNN은 train 10%에서 Macro-F1 0.978로 GraphSAGE와 동점(Micro-F1은 0.979 vs 0.978), 30%에서 0.981/0.982로 근소하게 앞선다. 군집화에서는 GraphSAGE가 이긴다: NMI 0.914 vs HetGNN 0.901, ARI 0.945 vs 0.932. 논문의 서술은 "최고이거나 최고 방법과 comparable"이다(§4.2.3 Result (2)). 표를 직접 보면 comparable의 실체는 열세다. 이와 별도로 논문은 도메인별 저자 100명의 임베딩을 2D/3D로 시각화해(Figure 3) 군집이 나뉘는 모습을 정성적으로도 보인다.

### 5.4 Inductive 분류·군집화 (Table 6)

A-II 2013 분할에서 inductive가 가능한 GSAGE·GAT와만 비교한다. 분류는 train 10%에서 Macro/Micro-F1 0.962/0.965(GAT 0.954/0.958), 30%에서 0.964/0.968로 앞서되 격차는 작다. 격차가 크게 벌어지는 곳은 군집화다: NMI 0.840/ARI 0.894로 GSAGE(0.714/0.764)·GAT(0.765/0.803)를 크게 앞서고, 평균 상대 개선율은 GSAGE 대비 17.3%, GAT 대비 10.6%다(§4.2.4). transductive 군집화에서 졌던 모델이 inductive 군집화에서는 크게 이긴다는 역전이 이 논문 결과표에서 가장 흥미로운 부분인데, 논문 자체는 이 엇갈림을 언급하지 않는다(inductive NMI 0.840이 같은 과제의 transductive 값 0.901보다 낮아지는 것도 마찬가지다).

### 5.5 Ablation과 민감도 (Figures 4–6)

변형 3종과 비교한다(§4.3.1): No-Neigh(이웃 없이 자기 콘텐츠만), Content-FC(콘텐츠 인코더를 FC로 대체), Type-FC(attention을 FC로 대체). 평가 대상은 A-II(2013 분할)의 링크 예측 2종과 추천이고, 결과는 그림으로만 제시된다(Figure 4, 수치 표 없음). 결론은 이웃 집계·Bi-LSTM 인코딩·attention이 각각 FC 대체보다 낫다는 것이다. 다만 No-Neigh 대비 우위는 "in most cases"로 유보되어 있다. 전 케이스 승리가 아니라는 뜻이다.

민감도(§4.3.2): 임베딩 차원은 8→256 구간에서 키우면 오르다가 일정 크기 이후 정체하거나 소폭 내려가고(논문은 과적합으로 추정, Figure 5), 샘플 이웃 크기는 {6, 12, 17, 23, 28, 34} 구간에서 처음엔 오르다가 일정 크기를 넘으면 "noise" 이웃 유입으로 완만히 내려간다. 최적은 20–30 구간(§4.3.2, Figure 6).

## 6. 주의해서 읽을 점

### 6.1 논문 자체의 오기 3건

원문을 수식·그림과 대조하면 서술 오류가 셋 나온다. 결과에 영향을 주는 것은 아니지만 꼼꼼히 읽다 보면 걸리는 부분들이다.

1. **Eq. (2)의 게이트 명칭이 뒤바뀌어 있다.** 본문은 "\(z_i\), \(f_i\), \(o_i\)는 각각 forget/input/output gate"라고 쓰는데, 셀 갱신식 \(c_i = f_i \circ c_{i-1} + z_i \circ \hat{c}_i\)를 보면 \(f_i\)가 forget, \(z_i\)가 input이어야 맞다(§3.2).
2. **Par2Vec의 인용 번호가 절마다 다르다.** §3.2는 [13](Le & Mikolov의 paragraph vector)으로, §4.1.3과 §A.4는 [19](Mikolov et al.의 word2vec negative sampling 논문)로 인용한다.
3. **§3.3.2가 타입 결합 그림을 "Figure 2(c)"로 지시**하지만, Figure 2 캡션 기준으로 타입 결합(NN-3)은 (d)다. (c)는 같은 타입 이웃 집계(NN-2)다.

### 6.2 "end-to-end"의 실제 범위

Abstract는 모델을 end-to-end로 학습한다고 쓰지만, 그래프 목적함수로 갱신되는 것은 사전학습 특징 이후의 모듈(변환기 \(\mathcal{FC}_{\theta_x}\), Bi-LSTM들, attention — Eq. 8의 \(\Theta\))이다. Par2Vec·CNN 인코더 자체는 사전학습 후 고정되고, 미세조정 언급은 어디에도 없다. 더 주의할 부분은 DeepWalk 사전학습 임베딩이 "콘텐츠 특징"으로 입력에 들어간다는 사실이다(§4.1.3). 구조 정보가 이웃 집계 경로와 입력 특징 경로로 이중 주입되므로 No-Neigh ablation(이웃 제거)의 해석이 흐려진다. 이웃을 제거해도 DeepWalk 특징에 구조 정보가 이미 들어가 있기 때문이다.

### 6.3 "inductive"의 실제 의미

§4.2.4의 inductive 실험은 학습된 모델로 신규 노드의 임베딩을 추론하는 것인데, 신규 노드의 임베딩을 만들려면 RWR 이웃과 콘텐츠 특징이 필요하다. 그런데 콘텐츠 특징에 포함되는 DeepWalk 임베딩은 transductive라서 2013년 이후 신규 노드에는 존재하지 않는다. 신규 노드에서 이 특징을 어떻게 채웠는지(재학습, 제외, 영벡터?)는 본문·부록 어디에도 없다. 검증된 inductive 과제의 범위도 좁다: 데이터는 A-II 하나, 분할 연도 하나, 과제는 분류·군집화뿐이고, 논문의 주력 과제인 링크 예측·추천의 inductive 버전과 리뷰 그래프의 cold-start(실용적으로 가장 중요한 시나리오)는 평가되지 않았다.

### 6.4 수치를 읽는 눈금

Tables 3–6 전체에서 반복 실행·표준편차·유의성 검정이 없다. 단일 수치 간 비교이므로, transductive 분류 train 10%의 0.001 차이(Micro-F1 0.979 vs 0.978)나 inductive 분류의 0.008 차이 같은 셀은 랜덤워크 샘플링·초기화 분산에 묻힐 수 있는 크기다. 분류 과제는 대부분 모델이 0.95를 넘는 천장 근처 비교다. 큰 격차가 실재하는 곳은 리뷰 그래프 링크 예측(최대 10.5%)과 inductive 군집화(NMI 0.840 vs 0.765)로 보는 것이 안전하다. 그리고 6.3절에서 본 것과 같은 맥락으로, 라벨이 필요한 과제와 ablation·민감도는 모두 A-II 한 데이터셋에서만 수행됐다.

### 6.5 Table 1의 HC 열은 층위가 다르다

Table 1은 ASNE·GraphSAGE·GAT에 HC(이질 콘텐츠 인지) ✓를 준다. 이들이 이질 콘텐츠를 입력으로 받을 수는 있다는 뜻이다. 그런데 본문 C2의 비판은 그 방식(연결·선형변환)이 깊은 상호작용을 못 잡는다는 것이므로, 표의 ✓와 본문의 비판은 서로 다른 층위에 있다. 표는 입력 가능 여부를, 본문은 인코딩 품질을 말한다. 표만 보고 "기존 GNN은 이질 콘텐츠를 못 다룬다"고 읽으면 논문의 실제 주장보다 강해진다.

## 7. 방법적 한계와 확장

### 7.1 논문이 남긴 것

§6 Conclusion에는 한계 서술도 future work도 없다. 본문 곳곳에 흩어진, 저자가 사실상 인정한 약점을 모으면 이렇다.

| 논문이 인정한 한계 | 위치 |
|---|---|
| 샘플 이웃 크기가 20–30을 넘으면 "noise" 이웃 때문에 성능 하락 | §4.3.2, Figure 6 |
| transductive 군집화에서 GraphSAGE에 열세("best or comparable"로 표현) | §4.2.3, Table 5 |
| 분류 과제의 천장 효과(대부분 모델 0.95+, 도메인 간 차이가 커서) | §4.2.3 |
| No-Neigh 대비 우위가 "in most cases"에 그침 | §4.3.1 |
| M=1 선택의 근거 실험 부재("영향 거의 없음"이라고만 서술) | §3.4 |

### 7.2 방법 내재적 한계 (논문 외 비판)

- **무순서 집합 위의 Bi-LSTM은 순열 불변이 아니다.** LSTM 은닉 상태는 입력 순서의 함수이므로 \(f_1(v)\)·\(f_2^t(v)\)는 이웃·콘텐츠를 넣는 순서에 따라 달라진다. 평균 풀링이 일부 완화하지만 불변성은 성립하지 않는다. GraphSAGE 원논문은 LSTM aggregator에 무작위 순열이라는 완화책을 명시했지만, HetGNN은 순서를 어떻게 정하는지 자체를 밝히지 않는다. ablation의 Content-FC 비교도 FC 대비 우위만 보일 뿐, mean/sum pooling 같은 순열 불변 집합 인코더와의 비교는 없다.
- **빈도 기반 이웃 선별은 hub로 쏠린다.** RWR 방문 빈도는 노드 차수와 강하게 상관하므로, top-\(k_t\) 선별은 대형 학회·인기 아이템 같은 허브를 모든 노드의 이웃으로 만들기 쉽다. C1에서 해결했다고 주장한 noise 이웃 문제가 선택 규칙을 타고 다른 형태로 돌아올 수 있다. 샘플링이 학습과 분리된 1회 고정 전처리라는 사실도 태스크 적응을 막는다(§A.1의 Algorithm 1은 사전학습 특징과 걷기 집합을 고정 입력으로 받고, 학습 루프에 재샘플링이 없다).
- **attention의 해상도가 타입 수준에 그친다.** 같은 타입 안의 개별 이웃은 균등 취급되고, attention이 구분하는 대상은 self 포함 3–4개뿐이다(4장에서 본 이분 리뷰 그래프에서는 3개다). 관계 타입(집필/인용/게재)의 의미 구분도 없다.
- **복잡도·확장성 분석이 없다.** 노드 타입별 별도 Bi-LSTM과 전 노드 RWR 전처리의 비용을 다루지 않으며, 검증 규모는 수십만 노드급에 그친다.

### 7.3 meta-path를 쓰지 않는 설계의 양면 (논문 외 해석)

HetGNN은 metapath2vec류의 meta-path 지정 워크 대신 타입 제약 RWR을 쓴다. 얻는 것은 설계 자유다. meta-path 선택이라는 수동 단계가 없어 새 이종 그래프에 바로 적용된다. 잃는 것은 의미론이다. RWR 빈도는 "저자–논문–저자"(공저)와 "저자–논문–논문"(인용) 경로를 구분하지 않고 합산하므로, 특정 의미 관계가 중요한 과제에 사전지식을 넣을 통로가 없다. 후속 문헌은 이 노선을 meta-path-free로 분류한다(논문 자신은 이 표현을 쓰지 않는다).

### 7.4 이후 계보 (논문 외 지식)

- **meta-path 기반 attention 계열:** 같은 해의 HAN(Wang et al., 2019)은 meta-path별 이웃에 노드·시맨틱 두 수준의 attention을 걸었고, MAGNN(Fu et al., 2020)은 meta-path 중간 노드까지 인코딩한다. HetGNN과는 "meta-path를 사람이 고르느냐"에서 갈라진다.
- **타입 의존 파라미터 계열:** HGT(Hu et al., 2020)는 Transformer식 구조에 노드·관계 타입별 파라미터를 두어 meta-path를 암묵적으로 학습한다.
- **재평가 논쟁:** Lv et al. (2021)은 HetGNN을 포함한 이종 GNN들을 통일된 벤치마크(HGB)에서 재평가해, 입력·정규화를 잘 갖춘 단순 GAT 변형(Simple-HGN)이 다수의 전용 이종 GNN과 대등하거나 낫다고 보고했다. 초기 이종 GNN 논문들의 실험 설정 비일관성에 대한 문제 제기로, HetGNN의 Tables 3–6도 자체 실험 설정 안의 결과로 한정해 읽는 편이 맞다.

### 7.5 위키·사회연결망 관점에서 (논문 외 해석)

이 논문의 학술 그래프 type-1 링크 예측은 저자 간 협업, 즉 **공저 네트워크의 링크 예측**이다. 사회연결망 분석에서 공저 네트워크는 보통 저자–저자를 직접 잇는 동종 투영 그래프로 다루는데, 투영은 "어떤 논문·학회를 매개로 한 공저인지"를 지운다. HetGNN 계열은 author–paper–venue 그래프를 투영 없이 유지한 채, RWR 이웃 구조와 초록 텍스트를 함께 반영한 임베딩으로 공저를 예측한다. 투영에서 잃던 매개 정보를 보존하는 것이 이 계열의 SNA적 의미다. 이 위키의 노트-링크 그래프도 노트·개념·논문 스텁 등 타입이 섞인 그래프이므로, "타입을 뭉개지 않고 임베딩한다"는 문제 설정 자체가 참조점이 된다. 다만 6.3절의 교훈도 함께 가져가야 한다: inductive를 표방하는 모델이라도 입력 특징 어딘가에 transductive한 부품(여기서는 DeepWalk 특징)이 숨어 있으면 신규 노드 처리의 실체를 따로 확인해야 한다.

## 8. 결론

HetGNN은 GraphSAGE의 샘플링-집계 틀과 GAT의 attention을 이종 그래프로 옮기고, 콘텐츠 이질성이라는 축을 더한 논문이다. RWR 이웃 샘플링(C1), 타입별 Bi-LSTM 콘텐츠 인코딩(C2), 타입 단위 attention 결합(C3)이라는 세 부품의 대응이 명확해서, 이종 그래프 GNN의 설계 공간을 처음 익히기에 좋다. 결과를 보면 콘텐츠가 풍부한 리뷰 그래프와 inductive 군집화에서 크게 이기고, transductive 분류·군집화에서는 GraphSAGE와 동급이거나 뒤진다. 이 모델의 이득이 "이질 콘텐츠 활용"과 "신규 노드 일반화"에서 나온다는 신호로 읽을 수 있다.

읽는 법을 정리하면:

| 목적 | 어디를 읽나 |
|---|---|
| 이종 그래프 GNN의 기본 설계 공간 | §1의 C1–C3, Figure 2, 이 글 3장 |
| GraphSAGE·GAT와의 정확한 관계 | §3.2·§3.3의 "inspired by [7]"·"[31]", 이 글 1.3절 |
| 성능 주장의 실제 강도 | Tables 3–6을 §4.2.3의 "comparable"과 함께, 이 글 5장·6.4절 |
| inductive 주장의 범위 | §4.2.4와 §4.1.3의 DeepWalk 특징, 이 글 6.3절 |
| 이후 문헌에서의 위치 | 이 글 7.3–7.4절(논문 외) |

시리즈의 다음 연결로는, 같은 이종 그래프를 meta-path attention으로 다루는 HAN, 그리고 이종 GNN 전반의 실험 관행을 재점검한 HGB 논문이 자연스러운 후속이다.

## References

Dong, Y., Chawla, N. V., & Swami, A. (2017). metapath2vec: Scalable representation learning for heterogeneous networks. *Proceedings of the 23rd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 135–144. https://doi.org/10.1145/3097983.3098036 ([PDF 보기](/paper-viewer?title=metapath2vec%3A+Scalable+Representation+Learning+for+Heterogeneous+Networks&source=blog-reference&authors=Yuxiao+Dong%3BNitesh+V.+Chawla%3BAnanthram+Swami&year=2017&doi=10.1145%2F3097983.3098036&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3097983.3098036))

Fu, X., Zhang, J., Meng, Z., & King, I. (2020). MAGNN: Metapath aggregated graph neural network for heterogeneous graph embedding. *Proceedings of The Web Conference 2020*, 2331–2341. https://doi.org/10.1145/3366423.3380297 ([PDF 보기](/paper-viewer?title=MAGNN%3A+Metapath+Aggregated+Graph+Neural+Network+for+Heterogeneous+Graph+Embedding&source=blog-reference&authors=Xinyu+Fu%3BJiani+Zhang%3BZhongying+Meng%3BIrwin+King&year=2020&doi=10.1145%2F3366423.3380297&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3366423.3380297))

Grover, A., & Leskovec, J. (2016). node2vec: Scalable feature learning for networks. *Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 855–864. https://doi.org/10.1145/2939672.2939754 ([PDF 보기](/paper-viewer?title=node2vec%3A+Scalable+Feature+Learning+for+Networks&source=blog-reference&authors=Aditya+Grover%3BJure+Leskovec&year=2016&doi=10.1145%2F2939672.2939754&url=https%3A%2F%2Fdoi.org%2F10.1145%2F2939672.2939754))

Hamilton, W., Ying, Z., & Leskovec, J. (2017). Inductive representation learning on large graphs. *Advances in Neural Information Processing Systems*, *30*. https://arxiv.org/abs/1706.02216 ([PDF 보기](/paper-viewer?title=Inductive+Representation+Learning+on+Large+Graphs&source=blog-reference&authors=William+L.+Hamilton%3BRex+Ying%3BJure+Leskovec&year=2017&arxiv_id=1706.02216&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1706.02216.pdf))

Hu, Z., Dong, Y., Wang, K., & Sun, Y. (2020). Heterogeneous graph transformer. *Proceedings of The Web Conference 2020*, 2704–2710. https://doi.org/10.1145/3366423.3380027 ([PDF 보기](/paper-viewer?title=Heterogeneous+Graph+Transformer&source=blog-reference&authors=Ziniu+Hu%3BYuxiao+Dong%3BKuansan+Wang%3BYizhou+Sun&year=2020&doi=10.1145%2F3366423.3380027&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3366423.3380027))

Le, Q., & Mikolov, T. (2014). Distributed representations of sentences and documents. *Proceedings of the 31st International Conference on Machine Learning*, 1188–1196. https://arxiv.org/abs/1405.4053 ([PDF 보기](/paper-viewer?title=Distributed+Representations+of+Sentences+and+Documents&source=blog-reference&authors=Quoc+V.+Le%3BTomas+Mikolov&year=2014&arxiv_id=1405.4053&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1405.4053.pdf))

Liao, L., He, X., Zhang, H., & Chua, T.-S. (2018). Attributed social network embedding. *IEEE Transactions on Knowledge and Data Engineering*, *30*(12), 2257–2270. https://doi.org/10.1109/TKDE.2018.2819980 ([PDF 보기](/paper-viewer?title=Attributed+Social+Network+Embedding&source=blog-reference&authors=Lizi+Liao%3BXiaofeng+He%3BHanwang+Zhang%3BTat-Seng+Chua&year=2018&doi=10.1109%2FTKDE.2018.2819980&url=https%3A%2F%2Fdoi.org%2F10.1109%2FTKDE.2018.2819980))

Lv, Q., Ding, M., Liu, Q., Chen, Y., Feng, W., He, S., Zhou, C., Jiang, J., Dong, Y., & Tang, J. (2021). Are we really making much progress? Revisiting, benchmarking and refining heterogeneous graph neural networks. *Proceedings of the 27th ACM SIGKDD Conference on Knowledge Discovery & Data Mining*, 1150–1160. https://doi.org/10.1145/3447548.3467350 ([PDF 보기](/paper-viewer?title=Are+we+really+making+much+progress%3F+Revisiting%2C+benchmarking%2C+and+refining+heterogeneous+graph+neural+networks&source=blog-reference&authors=Qiaoyu+Lv%3BMing+Ding%3BQiang+Liu%3BYuxiang+Chen%3BWenqiang+Feng%3BSiming+He%3BChang+Zhou%3BJianguo+Jiang%3BYuxiao+Dong%3BJie+Tang&year=2021&doi=10.1145%2F3447548.3467350&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3447548.3467350))

Mikolov, T., Sutskever, I., Chen, K., Corrado, G. S., & Dean, J. (2013). Distributed representations of words and phrases and their compositionality. *Advances in Neural Information Processing Systems*, *26*. https://arxiv.org/abs/1310.4546 ([PDF 보기](/paper-viewer?title=Efficient+Estimation+of+Word+Representations+in+Vector+Space&source=blog-reference&authors=Tomas+Mikolov%3BKai+Chen%3BGreg+Corrado%3BJeffrey+Dean&year=2013&arxiv_id=1310.4546&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1310.4546.pdf))

Pan, J.-Y., Yang, H.-J., Faloutsos, C., & Duygulu, P. (2004). Automatic multimedia cross-modal correlation discovery. *Proceedings of the Tenth ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 653–658. https://doi.org/10.1145/1014052.1014135 ([PDF 보기](/paper-viewer?title=Automatic+Multimedia+Cross-modal+Correlation+Discovery&source=blog-reference&authors=Jia-Yu+Pan%3BHyung-Jeong+Yang%3BChristos+Faloutsos&year=2004&doi=10.1145%2F1014052.1014135&url=https%3A%2F%2Fdoi.org%2F10.1145%2F1014052.1014135))

Perozzi, B., Al-Rfou, R., & Skiena, S. (2014). DeepWalk: Online learning of social representations. *Proceedings of the 20th ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 701–710. https://doi.org/10.1145/2623330.2623732 ([PDF 보기](/paper-viewer?title=DeepWalk%3A+Online+Learning+of+Social+Representations&source=blog-reference&authors=Bryan+Perozzi%3BRami+Al-Rfou%3BSteven+Skiena&year=2014&doi=10.1145%2F2623330.2623732&arxiv_id=1403.6652&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1403.6652.pdf&url=https%3A%2F%2Fdoi.org%2F10.1145%2F2623330.2623732))

Veličković, P., Cucurull, G., Casanova, A., Romero, A., Liò, P., & Bengio, Y. (2018). Graph attention networks. *International Conference on Learning Representations*. https://arxiv.org/abs/1710.10903 ([PDF 보기](/paper-viewer?title=Graph+Attention+Networks&source=blog-reference&authors=Petar+Veli%C4%8Dkovi%C4%87%3BGuillem+Cucurull%3BArantxa+Casanova%3BAdriana+Romero%3BPietro+Li%C3%B2%3BYoshua+Bengio&year=2018&arxiv_id=1710.10903&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1710.10903.pdf))

Wang, X., Ji, H., Shi, C., Wang, B., Ye, Y., Cui, P., & Yu, P. S. (2019). Heterogeneous graph attention network. *The World Wide Web Conference*, 2022–2032. https://doi.org/10.1145/3308558.3313562 ([PDF 보기](/paper-viewer?title=Heterogeneous+Graph+Attention+Network&source=blog-reference&authors=Xiao+Wang%3BHouye+Ji%3BChuan+Shi%3BBai+Wang%3BYanfang+Ye%3BPeng+Cui%3BPhilip+S.+Yu&year=2019&doi=10.1145%2F3308558.3313562&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3308558.3313562))

Zhang, C., Song, D., Huang, C., Swami, A., & Chawla, N. V. (2019). Heterogeneous graph neural network. *Proceedings of the 25th ACM SIGKDD International Conference on Knowledge Discovery & Data Mining*, 793–803. https://doi.org/10.1145/3292500.3330961 ([PDF 보기](/paper-viewer?title=Heterogeneous+Graph+Neural+Network&source=blog-reference&authors=Chuxu+Zhang%3BDongjin+Song%3BChao+Huang%3BAnanthram+Swami%3BNitesh+V.+Chawla&year=2019&doi=10.1145%2F3292500.3330961&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3292500.3330961))

Zhang, C., Swami, A., & Chawla, N. V. (2019). SHNE: Representation learning for semantic-associated heterogeneous networks. *Proceedings of the Twelfth ACM International Conference on Web Search and Data Mining*, 690–698. https://doi.org/10.1145/3289600.3291001 ([PDF 보기](/paper-viewer?title=SHNE%3A+Representation+Learning+for+Semantic-Associated+Heterogeneous+Networks&source=blog-reference&authors=Chuxu+Zhang%3BAnanthram+Swami%3BNitesh+V.+Chawla&year=2019&doi=10.1145%2F3289600.3291001&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3289600.3291001))
