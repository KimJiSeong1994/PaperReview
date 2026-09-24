# Can Classic GNNs Be Strong Baselines for Graph-level Tasks? Simple Architectures Meet Excellence

**Paper:** Yuankai Luo; Lei Shi; Xiao-Ming Wu (2025). "Can Classic GNNs Be Strong Baselines for Graph-level Tasks? Simple Architectures Meet Excellence". https://arxiv.org/abs/2502.09263v3 · arXiv:2502.09263v3

**Abstract:** GNN+는 GCN·GIN·GatedGCN에 엣지 특징, 정규화, 드롭아웃, 잔차 연결, FFN, 위치 인코딩을 결합해 그래프 수준 과제의 강한 기준선을 구성한다. 14개 벤치마크에서 Graph Transformer와 비교해 모든 데이터셋에서 상위 3위, 8개에서 1위를 보고한다. 이 결과는 기존 GNN에도 널리 사용된 구성요소와 학습 설정을 맞추는 것이 중요함을 보여 준다. 다만 현재 벤치마크의 결과가 모든 그래프 과제에서 전역 어텐션이 불필요함을 뜻하지는 않는다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 노드 수준 과제에서 고전 GNN이 GT와 대등하다는 선행 결과(같은 팀, NeurIPS 2024)를 그래프 수준 과제에서도 재현할 수 있는가? |
| 핵심 기여 | GNN+ 프레임워크: 고전 GNN 한 층을 "메시지 전달(+엣지 특징) → 정규화 → 활성화·드롭아웃 → 잔차 → FFN"로 재조립하고 입력에 위치 인코딩을 붙인다(식 6–12, Figure 2). 다섯 구성요소의 이진 선택과 드롭아웃 비율 하이퍼파라미터. |
| 실험 결과 | 14개 벤치마크(GNN Benchmark 5 + LRGB 표기 5 + OGB 4)에서 GNN+ 세 모델 중 최소 하나가 전부 상위 3위, 8개에서 1위(GatedGCN+ 6 + GCN+ 2). GraphGPS 대비 에폭당 최대 7.7배 빠름. 전 표 5-시드 평균±표준편차. |
| 핵심 한계 | "classic/simple GNN" 명명이 흡수한 GT 부품(FFN·위치 인코딩)을 가림, 튜닝 노력과 OGB 파라미터 예산(6M~30M)의 비대칭, ablation의 "전부 불가결" 주장이 데이터셋별 on/off 서치와 모순, 통계 검정 부재. GT 이론을 반증하지 못하며 저자도 §7에서 벤치마크 한정임을 인정. |

## 목차

1. 서론
2. 방법: GNN+ 프레임워크
3. 실험 설정
4. 실험 결과
5. 무엇이 실제로 이겼나 (ablation)
6. 해석의 범위와 한계
7. 방법적 한계와 확장
8. 결론

## 1. 서론

### 1.1 연구 배경

메시지 전달 GNN(이웃 정보를 반복 집계해 노드 표현을 학습하는 방식)은 세 가지로 비판받아 왔다(§1). 표현력 한계(1-WL 검사를 넘지 못한다는 Xu et al., 2019; Morris et al., 2019의 이론 — 1-WL은 이웃 라벨을 반복 해싱해 그래프를 구별하는 고전 동형 판별 알고리즘 Weisfeiler-Lehman 검사다), over-smoothing(층이 깊어지면 노드 표현이 구별 불가능해지는 현상), 그리고 장거리 의존 포착의 어려움이다. Graph Transformer는 전역 어텐션으로 이 한계들을 넘는다고 여겨졌고, 문헌은 특히 작은 분자 그래프의 분류·회귀 같은 그래프 수준 과제에서 GT가 GNN을 앞선다고 반복해 왔다(§1).

이 논문의 반론은 두 갈래다. 하나는 GT의 전역 어텐션이 노드 수 제곱에 비례하는 계산량을 요구해 확장성이 떨어진다는 것이고, 다른 하나는 정작 최신 GT들(SAT, GraphGPS, Exphormer, GRIT)이 명시적으로든 암묵적으로든 여전히 GNN의 메시지 전달에 의존한다는 내부 모순 지적이다(§1). 그렇다면 어텐션을 떼고 메시지 전달만 제대로 튜닝하면 어떻게 되는가. 이것이 연구 질문이다.

### 1.2 그래프 수준 과제란

Figure 1이 이 논문이 다루는 과제의 성격을 규정한다. 그래프 수준 과제는 여러 개의 작은 그래프가 각각 훈련·검증·테스트 분할의 단위가 되고(분자 그래프 분류처럼), 노드 수준 과제는 하나의 큰 그래프 안에서 노드들이 분할 단위가 된다(소셜 네트워크의 노드 분류처럼). 이 기본 단위의 차이가 방법론·훈련 전략·응용 도메인의 차이로 이어진다는 것이 §1의 주장이다.

![GNN+ Figure 1: graph-level vs node-level tasks](/api/blog/figures/gnnplus-fig1-tasks.png)

*그림 1 — 원논문 Figure 1: 그래프 수준 과제(위)는 그래프 전체가 훈련/검증/테스트 분할 단위인 여러 작은 그래프의 모음이고, 노드 수준 과제(아래)는 하나의 큰 그래프 안에서 노드들이 분할 단위다.*

한 가지 용어를 미리 짚어 둔다. 이 논문의 "graph-level tasks"는 그래프 전체를 예측하는 과제뿐 아니라 개별 노드·엣지에 대한 inductive 예측(그래프 단위로 분할하되 예측 대상은 노드)도 포함한다(§2). 그래서 14개 데이터셋 중 PATTERN·CLUSTER·PascalVOC-SP·COCO-SP 네 개는 실제로 inductive 노드 분류이면서도 그래프 수준 목록에 들어간다(Table 7). 이 넷은 그래프 풀링 없이 노드별로 예측한다.

### 1.3 학술적 위치

이 논문은 같은 팀(Luo·Shi·Wu)의 선행편을 그래프 수준으로 확장한 후속작이다. 선행편(Luo et al., 2024, NeurIPS 2024)은 GCN·GAT·GraphSAGE를 18개 노드 분류 데이터셋에서 재평가해 "같은 탐색 공간이면 고전 GNN이 최신 모델과 대등하거나 낫다"를 보였다. 이 논문의 연구 질문 자체가 "노드 수준에서는 됐는데 그래프 수준에서도 되는가"이고, 제목의 질문형("Can Classic GNNs Be Strong Baselines")도 선행편 제목("Classic GNNs are Strong Baselines")과 짝을 이룬다. 두 편은 단순 반복이 아니라 과제 수준별 처방 차이를 축적한다. 예컨대 정규화는 두 수준 모두에서 대규모 데이터에 중요하지만(일관), 최적 드롭아웃은 노드 수준에서 높고 그래프 수준에서 낮다(대비, §5.2).

그래프 ML 안에서 이 논문의 가장 가까운 선행은, 공정하게 비교하면 주장된 개선이 사라진다는 것을 보인 재평가 계보다. 그래프 분류의 Errica et al. (2020), 노드 분류 평가의 함정을 짚은 Shchur et al. (2018), 장거리 벤치마크의 격차가 튜닝으로 닫힌다는 Tönshoff et al. (2023)이 §6이 인용하는 축이다. 넓게 보면 이 흐름은 분야를 넘나든다(후속 연구 맥락). 튜닝된 고전 모델이 신형 아키텍처를 이기는 서사는 추천 시스템(Dacrema et al., 2019), 시계열 예측, 비전(ConvNeXt)에서도 반복됐다. 특히 ConvNeXt와 구조가 닮았다. 고전 아키텍처에 트랜스포머 시대의 학습·설계 기법을 이식해 트랜스포머와 동급으로 만든다는 서사가 같고, 저장소가 스스로를 "ModernGNN"으로 부르는 것도 그 계열의 브랜딩이다(해석).

한 가지 판본 사실을 적어 둔다. 초판(v1)의 제목은 "Unlocking the Potential of Classic GNNs…"였고 질문형 현행 제목과 §7 Limitations·부록 B/C는 v3(ICML 최종판)에서 들어왔다. 이 글이 인용하는 §7은 v3 신설분이다.

## 2. 방법: GNN+ 프레임워크

원논문 §2–§3에 해당한다.

### 세 베이스 모델

GNN+는 세 고전 모델을 강화 대상으로 삼는다(§2). GCN(Kipf & Welling, 2017; 식 2)은 대칭 정규화한 이웃 합산에 self-loop를 더한 뒤 비선형을 씌우고, GIN(Xu et al., 2019; 식 3)은 이웃 합산에 자기 표현을 더해 MLP에 통과시키며, GatedGCN(Bresson & Laurent, 2017; 식 4)은 각 이웃의 기여를 시그모이드 게이트로 조절해 더한다. 공통 형식은 메시지 전달(식 1)이고, 그래프 표현은 readout(노드 표현들을 그래프 하나의 벡터로 집약하는 연산, 식 5)으로 만든다. 실제 풀링 방식(합·평균·최댓값)도 데이터셋별 튜닝 대상이다(Tables 8–13). 노드 수준 선행편은 GCN·GAT·GraphSAGE를 썼는데 여기서 트리오가 바뀐 것은, 그래프 수준 벤치마크(Dwivedi et al., 2023의 GNN Benchmark)의 표준 베이스라인이 이 셋이기 때문으로 보인다(해석).

### 여섯 기법

![GNN+ Figure 2: architecture](/api/blog/figures/gnnplus-fig2-architecture.png)

*그림 2 — 원논문 Figure 2: GNN+ 아키텍처. 입력 노드 특징에 위치 인코딩을 결합해 L개 층에 통과시키고 readout한다. 각 층 내부는 아래에서 위로 메시지 전달(엣지 특징 주입) → 정규화 → 활성화·드롭아웃 → 잔차 연결 → FFN(MLP + Add & Norm) 순이다.*

§3은 GCN을 예로 층 내부 다섯 기법을 식 6부터 11까지 누적해 쌓고, 여섯 번째인 위치 인코딩(식 12)은 입력단에 따로 적용한다.

- **엣지 특징(식 6):** 엣지 벡터를 별도 가중치로 사영해 메시지 전달 집계 항 안에 더한다. 분자의 결합, 단백질의 연관도, 슈퍼픽셀의 공간 관계 같은 정보를 담는다(§3.1).
- **정규화(식 7):** 활성화 직전 배치 정규화. 층을 지나며 노드 임베딩 분포가 변하는 문제(covariate shift)를 완화해 학습률을 높이고 수렴을 앞당긴다(§3.2).
- **드롭아웃(식 8):** 활성화 직후 적용. GNN에서는 은닉 뉴런의 상호 과의존이 메시지 전달을 타고 노드 간에 전파·누적되므로 억제가 필요하다(§3.3).
- **잔차 연결(식 9):** 기울기 소실을 완화해 통상 2–5층에 머무는 GNN을 3–20층까지 깊게 만든다. 잔차 연결은 원래 vanilla GCN이 처음 채택한 것이다(§3.4).
- **FFN(식 10, 11):** 각 층 끝에 완전연결 FFN을 붙인다. 이 FFN은 내부에 자체 잔차와 정규화를 포함하므로, 한 층에 잔차가 두 번 나타난다(블록 잔차 + FFN 내부 잔차). GT의 각 층이 FFN을 핵심 부품으로 삼은 것에서 착안했다고 밝힌다(§3.5).
- **위치 인코딩(식 12):** RWSE(random walk structural encoding, 랜덤워크 반환확률로 구조를 인코딩)를 입력 노드 특징에 결합한 뒤 사영한다. 층 내부가 아니라 입력단에서 한 번 적용한다. 본문은 GT의 설계에서 착안했다고 설명하며(§3.6), Appendix C.1은 이전 GNN에서도 위치 인코딩이 사용됐음을 명시한다.

GNN+는 다섯 구성요소의 이진 선택과 연속적인 드롭아웃 비율로 구성되는 설계 공간이다(Appendix B.1). 데이터셋별 최적 설정 외에, 모든 구성요소를 사용하는 고정 설정도 평가한다. Appendix B.2의 Table 14에서는 9개 데이터셋에서 고정 설정과 튜닝 설정이 대체로 유사한 성능을 보인다.

## 3. 실험 설정

원논문 §4와 부록 A에 해당한다.

**데이터(Table 1, 7).** 14개 = GNN Benchmark 5(ZINC·MNIST·CIFAR10·PATTERN·CLUSTER) + LRGB 표기 5(Peptides-func·Peptides-struct·PascalVOC-SP·COCO-SP·MalNet-Tiny) + OGB 4(molhiv·molpcba·ppa·code2). 규모 스펙트럼이 넓다. MalNet-Tiny 5,000개에서 ogbg-code2 452,741개까지, 그래프 크기도 ZINC 평균 23노드에서 MalNet-Tiny 1,410노드까지다. 원 LRGB(Dwivedi et al., 2022)는 다섯 데이터셋인데 그중 PCQM-Contact은 다운로드 링크가 소실되어 제외됐고, 그 자리를 MalNet-Tiny(원래 LRGB 소속이 아니다)가 채워 이 논문의 LRGB 표기 묶음은 다섯 개다.

**지표·프로토콜(§4, 부록 A).** 각 설정을 5회 독립 실행해 평균±표준편차를 보고하고, 검증셋으로 최적 하이퍼파라미터를 고른다. 하드웨어는 RTX 3090 8장이다.

**비교 대상(§4).** GraphGPS(Rampášek et al., 2022)·Exphormer·GRIT·Graphormer·SAT·EGT·Specformer·TIGT를 비롯한 GT 계열과 Graph-Mamba·GMN·GSSC 같은 상태공간모델(SSM)까지 30여 종이다. 여기서 공정성 장치와 그 빈틈이 함께 나타난다. GNN+는 GraphGPS와 동일한 탐색 공간(학습률 3종, 드롭아웃 5종, 층수 3–20, 다섯 구성요소의 on/off와 드롭아웃 비율)에서 튜닝했고, GT 베이스라인은 원논문·리더보드 값을 가져왔다. 저자들은 GT를 같은 환경에서 재학습해 봤지만 원논문 값을 넘지 못해 (GT에 유리한) 원논문 값을 실었다고 밝힌다(§4). 이는 "GT를 일부러 불리하게 튜닝했다"는 비판을 상당히 막는 방어다. 다만 전수 탐색은 하지 않았고, 소규모 벤치마크는 파라미터 예산(~500K/~100K)을 맞췄지만 OGB에는 그 제약이 없다(6장에서 재론).

## 4. 실험 결과

원논문 §5.1(Tables 2–4)에 해당한다. 아래 순위는 표의 전 셀을 재정렬해 직접 검산한 것으로, 논문의 강조 표시와 일치한다.

**GNN Benchmark(Table 2).** GatedGCN+가 MNIST(98.712)·CIFAR10(77.218)에서 1위다. 그러나 ZINC는 TIGT(0.057)·GRIT(0.059)가 GIN+(0.065)보다 앞서고, PATTERN·CLUSTER에서도 GRIT가 GNN+ 최고치보다 근소하게 높다. 이 합성 데이터군이 GT가 가장 끈질기게 버티는 곳이다.

**LRGB 표기 묶음(Table 3).** GCN+가 Peptides-func(0.7261)에서 전체 1위, Peptides-struct에서는 GNN+ 세 모델이 상위 3위를 독식한다. 반면 슈퍼픽셀 노드 분류인 PascalVOC-SP·COCO-SP에서는 GSSC·GraphGPS·Graph-Mamba가 명확히 앞서고 GatedGCN+만 겨우 3위다. 전역 문맥이 실제로 중요한 과제에서 GT/SSM이 남아 이기는 곳이다.

**OGB(Table 4).** GatedGCN+가 분자 그래프 과제 molhiv·molpcba와 단백질 그래프 ppa에서 1위, ppa는 GatedGCN 원판 대비 +9.7%로 리더보드 1위다. 다만 세 가지 단서가 붙는다. molhiv의 "1위"(0.8040)는 사전학습 모델을 랭킹에서 제외한 규칙 아래서만 성립하고, 절대치로는 사전학습 EGT(0.8060)·Graphormer(0.8051)가 더 높다. code2는 SAT·GECO에 밀려 3위이고 GraphGPS와는 0.0002 차로 사실상 동률이다.

핵심 주장 두 개를 검산하면: "전 데이터셋 상위 3위"는 성립하되 세 GNN+ 모델이 모두 상위 3위인 곳은 Peptides-struct·ppa 두 곳뿐이고, 나머지는 데이터셋에 맞는 한 모델만 든다. "8개에서 1위"도 정확히 성립하며(GatedGCN+ 6 + GCN+ 2), GIN+ 단독 1위는 없다. 즉 정확히 말하면 고전 GNN 전부가 강하다기보다, 세 변형 중 데이터셋에 맞는 하나가 항상 상위 3위에 든다는 것이다.

효율은 GraphGPS와 에폭당 시간을 견줘 보인다. 다만 이 비교는 GCN+ 기준이고, 최다 1위 모델인 GatedGCN+는 더 느려서 일부 데이터셋은 GraphGPS보다도 느리다. "수 배 빠르다"는 GCN+의 속성이지 최상위 모델에 일반화되지 않는다.

## 5. 무엇이 실제로 이겼나 (ablation)

원논문 §5.2와 Tables 5–6이 여섯 기법을 하나씩 제거한 결과다. 논문의 요약 주장은 각 모듈이 불가결하며 어느 하나를 빼도 성능이 저하된다는 것이지만(§5.2, 번역), 표를 뜯어보면 실제 그림은 데이터셋마다 취약한 기법이 다르다는 쪽에 가깝다(해석).

- **엣지 특징**은 단백질 그래프(ppa)에서 파괴적이다. GatedGCN+가 0.8258에서 0.0948로 무너진다. 반면 코드 그래프에서는 영향이 미미해 아예 끄기도 한다.
- **정규화**는 대규모 데이터에서 중요하다(ppa에서 약 15% 하락).
- **드롭아웃**은 대부분 도움이 되지만 매우 낮은 비율이 최적이다(최적값의 97%가 0.2 이하). 이것이 노드 수준(높은 드롭아웃이 최적)과 갈리는 그래프 수준 고유 발견이다.
- **잔차 연결**은 깊은 망에 필수지만 얕은 Peptides(3–5층)에서는 오히려 특징 흐름을 방해해 끈다.
- **FFN**은 GIN+·GCN+에 결정적이다. MNIST에서 GIN+의 FFN을 빼면 98.285에서 11.350(거의 무작위)으로 붕괴한다. GatedGCN+는 게이팅이 그 역할을 일부 흡수해 덜 필요하다.
- **위치 인코딩**은 소규모 데이터에 효과적이고 대규모에서는 미미해 끈다.

여기서 이 논문의 서술 하나가 표와 어긋난다. "모든 모듈이 불가결(indispensable)"이라는 문장과, 하이퍼파라미터 표(Tables 8–13)에서 여러 데이터셋이 엣지·FFN·위치 인코딩·잔차를 애초에 끄는(False) 사실이 충돌한다. 더 정확한 서술은 각 기법이 일부 데이터셋에서 중요하고 최적 조합은 데이터셋마다 다르다는 것이다. 그리고 이 관찰이 5장의 핵심이다. 구성요소의 효과는 데이터셋에 따라 다르며, 고정 설정에 관한 Appendix B.2의 결과도 함께 고려해야 한다.

## 6. 해석의 범위와 한계

### 6.1 "고전 GNN"이라는 이름이 가리는 것

GNN+의 구성요소는 GNN과 Graph Transformer 양쪽에서 사용돼 온 장치다. 본문은 FFN과 위치 인코딩을 GT 설계에서 착안했다고 설명하지만, v3 Appendix C.1은 엣지 특징은 MPNN, FFN은 GIN, 위치 인코딩은 이전 GNN에서도 사용됐음을 명시한다. 따라서 기여는 특정 계열의 부품을 처음 도입한 데 있기보다, 이 구성요소를 고전 메시지 전달 모델에 통합해 강한 기준선으로 평가한 데 있다.

### 6.2 튜닝과 파라미터 예산의 비대칭

비교에서는 제안 모델의 데이터셋별 튜닝 결과와 기준선의 원논문·리더보드 수치를 함께 사용한다. 같은 탐색 공간이라도 실제 탐색 비용까지 같다고 확인할 수는 없다. 다만 Appendix B.2의 고정 all-six 설정 역시 9개 데이터셋에서 튜닝 설정과 대체로 유사해, 개선 전체를 데이터셋별 탐색에만 귀속할 수는 없다. 소규모 벤치마크에는 파라미터 예산 제약이 있지만 OGB 비교에는 동일 파라미터 예산 통제가 보고되지 않아, 파라미터 수를 맞춘 우위인지는 별도로 판단해야 한다.

### 6.3 통계적으로 구분되지 않는 순위

전 표가 5-시드 표준편차를 보고한다는 점에서 평가 위생은 비교된 연구들보다 낫다. 그러나 통계 검정은 없다. 순위가 점추정 평균만으로 매겨지는데, 근소차 순위들은 표준편차 안에 있다. PATTERN 3위 경합(GatedGCN+ 87.029 vs GCN+ 87.021 vs GRPE 87.020)은 0.01 수준 클러스터이고, code2 3위는 GraphGPS와 0.0002 차, molhiv 1위는 0.0005 내 3파전이다. "8개 1위"의 상당수가 이런 노이즈 수준 차이라, 순위를 강하게 받아들이면 안 된다(해석).

## 7. 방법적 한계와 확장

### 7.1 논문이 남긴 것

§7 Limitations가 인정하는 것은 셋이다. 결과가 경험적일 뿐 이론적 설명이 없다는 것, 현 그래프 데이터셋이 실세계의 복잡성을 대표하지 못할 수 있어 더 어려운 벤치마크에서는 고전 GNN의 상대 우위가 바뀔 수 있다는 것(Bechler-Speicher et al., 2025 인용), 그리고 각 모듈이 표현력·over-squashing(먼 정보가 좁은 경로로 압축돼 소실되는 현상)·over-smoothing에 어떻게 작용하는지 이론적 이해가 필요하다는 것이다. 이 두 번째 유보가 다음 절의 핵심이다. 인정하지 않는 것도 있다. 튜닝 비대칭, OGB 파라미터 예산 불일치, "고전 GNN" 명명의 정당성은 한계로 다루지 않는다.

### 7.2 GT 이론을 반박하는가

이 결과가 GT의 이론적 동기(장거리 의존, 표현력)를 반증하지는 못한다. 논문이 측정한 것은 14개 벤치마크의 최종 점수일 뿐, 장거리 능력이나 표현력을 직접 재지 않기 때문이다. 따라서 결론은 GT의 능력이 불필요하다는 데까지 가지 못하고, 현 벤치마크가 그 능력을 성능으로 요구하지 않는다는 데 그친다. 저자 자신이 §7에서 이 해석을 택하고, 선행 재평가(Tönshoff et al., 2023이 LRGB의 GT-GNN 격차가 튜닝만으로 상당히 닫힘을 보였다)와도 정합적이다. 이 논문이 반박하는 대상은 GT 이론이 아니라 "GT가 필수"라는 통념까지다 — v3 초록의 "challenging the notion that complex mechanisms in GTs are essential"이 정확히 그 범위다. GNN+가 명확히 지는 슈퍼픽셀 노드 분류(PascalVOC-SP·COCO-SP)와 code2가 전역 문맥이 실제로 중요한 과제라는 점도, 이 유보를 뒷받침한다.


## 8. 결론

이 논문의 기여는 견고한 재평가다. 전역 어텐션 없는 GNN이 그래프 수준 벤치마크에서 GT와 대등하거나 낫다는 것을, 5-시드·14데이터셋·넓은 베이스라인으로 상당히 뒷받침한다. 그러나 정직하게 읽으면 네 겹의 유보가 붙는다. "classic/simple GNN"이라는 명명은 흡수한 GT 부품을 덮고, 튜닝 노력과 OGB 파라미터 예산은 비대칭이며, ablation은 "전부 불가결"이라는 문장과 달리 데이터셋별 스위치 서치임을 드러내고, 결과는 GT 이론을 반증하지 못한 채 현 벤치마크가 GT 능력을 요구하지 않는다는 것만 보인다. 이 마지막 유보는 저자 자신이 §7에서 인정한다.GIN의 표현력 이론과 실무 성능의 괴리를 데이터로 보여주고, 새 아키텍처의 이득 상당 부분이 아키텍처가 아니라 학습·정규화·튜닝에서 온다는 메타 교훈을 그래프 수준으로 확장한다.

## References

Bechler-Speicher, M., Finkelshtein, B., Frasca, F., Müller, L., Tönshoff, J., Siraudin, A., Zaverkin, V., Bronstein, M. M., Niepert, M., Perozzi, B., Galkin, M., & Morris, C. (2025). *Position: Graph learning will lose relevance due to poor benchmarks* (arXiv:2502.14546). arXiv. https://arxiv.org/abs/2502.14546 ([PDF 보기](/paper-viewer?title=Position%3A+Graph+learning+will+lose+relevance+due+to+poor+benchmarks&authors=Bechler-Speicher+et+al.&year=2025&arxiv_id=2502.14546&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2502.14546.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F2502.14546&source=blog-reference))

Bresson, X., & Laurent, T. (2017). *Residual gated graph ConvNets* (arXiv:1711.07553). arXiv. https://arxiv.org/abs/1711.07553 ([PDF 보기](/paper-viewer?title=Residual+gated+graph+ConvNets&authors=Bresson%3BLaurent&year=2017&arxiv_id=1711.07553&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1711.07553.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F1711.07553&source=blog-reference))

Dacrema, M. F., Cremonesi, P., & Jannach, D. (2019). Are we really making much progress? A worrying analysis of recent neural recommendation approaches. *Proceedings of the 13th ACM Conference on Recommender Systems*, 101–109. https://doi.org/10.1145/3298689.3347058 ([PDF 보기](/paper-viewer?title=Are+we+really+making+much+progress%3F+A+worrying+analysis+of+recent+neural+recommendation+approaches&authors=Dacrema%3BCremonesi%3BJannach&year=2019&doi=10.1145%2F3298689.3347058&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3298689.3347058&source=blog-reference))

Dwivedi, V. P., Joshi, C. K., Luu, A. T., Laurent, T., Bengio, Y., & Bresson, X. (2023). Benchmarking graph neural networks. *Journal of Machine Learning Research*, *24*(43), 1–48. https://arxiv.org/abs/2003.00982 ([PDF 보기](/paper-viewer?title=Benchmarking+graph+neural+networks&authors=Dwivedi+et+al.&year=2023&arxiv_id=2003.00982&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2003.00982.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F2003.00982&source=blog-reference))

Dwivedi, V. P., Rampášek, L., Galkin, M., Parviz, A., Wolf, G., Luu, A. T., & Beaini, D. (2022). Long range graph benchmark. *Advances in Neural Information Processing Systems*, *35*, 22326–22340. https://arxiv.org/abs/2206.08164 ([PDF 보기](/paper-viewer?title=Long+range+graph+benchmark&authors=Dwivedi+et+al.&year=2022&arxiv_id=2206.08164&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2206.08164.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F2206.08164&source=blog-reference))

Errica, F., Podda, M., Bacciu, D., & Micheli, A. (2020). A fair comparison of graph neural networks for graph classification. *International Conference on Learning Representations*. https://arxiv.org/abs/1912.09893 ([PDF 보기](/paper-viewer?title=A+fair+comparison+of+graph+neural+networks+for+graph+classification&authors=Errica%3BPodda%3BBacciu%3BMicheli&year=2020&arxiv_id=1912.09893&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1912.09893.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F1912.09893&source=blog-reference))

Kipf, T. N., & Welling, M. (2017). Semi-supervised classification with graph convolutional networks. *International Conference on Learning Representations*. https://arxiv.org/abs/1609.02907 ([PDF 보기](/paper-viewer?title=Semi-supervised+classification+with+graph+convolutional+networks&authors=Kipf%3BWelling&year=2017&arxiv_id=1609.02907&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1609.02907.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F1609.02907&source=blog-reference))

Luo, Y., Shi, L., & Wu, X.-M. (2024). Classic GNNs are strong baselines: Reassessing GNNs for node classification. *Advances in Neural Information Processing Systems*, *37* (Datasets and Benchmarks Track). https://arxiv.org/abs/2406.08993 ([PDF 보기](/paper-viewer?title=Classic+GNNs+are+strong+baselines%3A+Reassessing+GNNs+for+node+classification&authors=Luo%3BShi%3BWu&year=2024&arxiv_id=2406.08993&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2406.08993.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F2406.08993&source=blog-reference))

Luo, Y., Shi, L., & Wu, X.-M. (2025). Can classic GNNs be strong baselines for graph-level tasks? Simple architectures meet excellence. *Proceedings of the 42nd International Conference on Machine Learning*. https://arxiv.org/abs/2502.09263 ([PDF 보기](/paper-viewer?title=Can+classic+GNNs+be+strong+baselines+for+graph-level+tasks%3F+Simple+architectures+meet+excellence&authors=Luo%3BShi%3BWu&year=2025&arxiv_id=2502.09263&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2502.09263.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F2502.09263&source=blog-reference))

Morris, C., Ritzert, M., Fey, M., Hamilton, W. L., Lenssen, J. E., Rattan, G., & Grohe, M. (2019). Weisfeiler and Leman go neural: Higher-order graph neural networks. *Proceedings of the AAAI Conference on Artificial Intelligence*, *33*, 4602–4609. https://doi.org/10.1609/aaai.v33i01.33014602 ([PDF 보기](/paper-viewer?title=Weisfeiler+and+Leman+go+neural%3A+Higher-order+graph+neural+networks&authors=Morris+et+al.&year=2019&doi=10.1609%2Faaai.v33i01.33014602&url=https%3A%2F%2Fdoi.org%2F10.1609%2Faaai.v33i01.33014602&source=blog-reference))

Rampášek, L., Galkin, M., Dwivedi, V. P., Luu, A. T., Wolf, G., & Beaini, D. (2022). Recipe for a general, powerful, scalable graph transformer. *Advances in Neural Information Processing Systems*, *35*, 14501–14515. https://arxiv.org/abs/2205.12454 ([PDF 보기](/paper-viewer?title=Recipe+for+a+general%2C+powerful%2C+scalable+graph+transformer&authors=Ramp%C3%A1%C5%A1ek+et+al.&year=2022&arxiv_id=2205.12454&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2205.12454.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F2205.12454&source=blog-reference))

Shchur, O., Mumme, M., Bojchevski, A., & Günnemann, S. (2018). Pitfalls of graph neural network evaluation. *Relational Representation Learning Workshop, NeurIPS 2018*. https://arxiv.org/abs/1811.05868 ([PDF 보기](/paper-viewer?title=Pitfalls+of+graph+neural+network+evaluation&authors=Shchur%3BMumme%3BBojchevski%3BG%C3%BCnnemann&year=2018&arxiv_id=1811.05868&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1811.05868.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F1811.05868&source=blog-reference))

Tönshoff, J., Ritzert, M., Rosenbluth, E., & Grohe, M. (2023). *Where did the gap go? Reassessing the long-range graph benchmark* (arXiv:2309.00367). arXiv. https://arxiv.org/abs/2309.00367 ([PDF 보기](/paper-viewer?title=Where+did+the+gap+go%3F+Reassessing+the+long-range+graph+benchmark&authors=T%C3%B6nshoff%3BRitzert%3BRosenbluth%3BGrohe&year=2023&arxiv_id=2309.00367&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2309.00367.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F2309.00367&source=blog-reference))

Xu, K., Hu, W., Leskovec, J., & Jegelka, S. (2019). How powerful are graph neural networks? *International Conference on Learning Representations*. https://arxiv.org/abs/1810.00826 ([PDF 보기](/paper-viewer?title=How+powerful+are+graph+neural+networks%3F&authors=Xu%3BHu%3BLeskovec%3BJegelka&year=2019&arxiv_id=1810.00826&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1810.00826.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F1810.00826&source=blog-reference))
