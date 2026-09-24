# DW2V 심층 분석: "Dynamic Word Embeddings for Evolving Semantic Discovery" 논문 해설

**Paper:** Yao, Zijun; Sun, Yifan; Ding, Weicong; Rao, Nikhil; Xiong, Hui. (2018). "Dynamic Word Embeddings for Evolving Semantic Discovery." *Proceedings of the Eleventh ACM International Conference on Web Search and Data Mining (WSDM '18)*, pp. 673–681. https://doi.org/10.1145/3159652.3159703. arXiv:1703.00607. Data & testsets: sites.google.com/site/zijunyaorutgers

**Abstract:** 본 문서는 시간에 따른 단어 임베딩을 행렬 분해로 공동 학습하는 DW2V(Dynamic Word2Vec) 논문을 해설한다. Dynamic Bernoulli Embeddings 리뷰(blog/dbe)에서 본 것과 같은 문제의식이다: 시대별로 임베딩을 따로 학습하면 좌표계가 회전만큼 어긋나 시점 간 비교가 안 되고, 사후 정렬은 데이터가 얇은 시기에서 오차를 전파한다. 이 논문의 해법은 word2vec의 행렬 분해 해석(Levy & Goldberg, 2014) 위에서, 시점별 PPMI 행렬 분해 항에 인접 시점 임베딩의 차이를 벌점화하는 평활 항을 더해 전 시점을 한 번에 최적화하는 것이다. Kulkarni·Hamilton의 2단계(정렬) 방법은 이 목적함수의 준최적 해로 포섭된다. 뉴욕타임스 27년 코퍼스에서 정렬 품질과 데이터 희소 강건성을 보였고, "2016년의 obama에 해당하는 1997년의 단어는?" 같은 등가어 질의라는 평가 프레임을 만들었다. 같은 해에 독립적으로 나온 확률 모델 해법(Rudolph & Blei, 2018; Bamler & Mandt, 2017)과 함께 공동 학습 노선의 창립 논문으로 읽으면 된다. 다만 평가 테스트셋이 전부 저자 구성이고, 데이터가 없는 시기의 벡터가 정칙화만으로 만들어진다는 점은 DBE와 같은 방식으로 조심해서 읽어야 한다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 시대별 임베딩의 정렬 문제(회전 불변성)를 사후 처리 없이, 학습 목적함수 안에서 풀 수 있는가? |
| 핵심 기여 | 시점별 PPMI 행렬 분해 + 인접 시점 평활 벌점의 공동 최적화(식 5). 논문 표현으로 "main novelty는 시점 전체를 공동 학습해 별도의 정렬 문제 자체를 없애는 것". Kulkarni·Hamilton의 2단계 방법은 이 목적함수의 준최적 해로 재해석된다(§2.3). |
| 방법적 결과 | 시점별 PPMI 재구성 오차, 임베딩 크기 정칙화, 인접 시점 차분 평활 벌점을 합친 목적함수(식 5)를 비대칭 완화(식 8)와 block coordinate descent로 푼다. 각 블록 갱신은 릿지 회귀 폐형식이다. |
| 실험 결과 | NYT 27년(1990–2016) 코퍼스. 군집화(Tables 4–5)·정렬 질의(Tables 6–7) 전 칸 1위. 가장 큰 격차는 강건성(Table 8): 3년마다의 연도에서 공기 데이터를 0.1%만 남겨도 MRR 0.4427 유지, 정렬 기반 baseline은 0.0362로 붕괴(약 12배). |
| 핵심 한계 | 정량 평가의 ground truth 3종이 전부 저자 구성(같은 코퍼스의 섹션 라벨 포함). 정렬 질의 Testset 1에서는 시간을 무시한 정적 word2vec이 2위다. 데이터 없는 시기의 벡터는 정칙화 산물이고, 그리드 서치 기준·유의성 검정·확률적 불확실성이 없다. |

## 목차

1. 서론
2. 예비 지식
3. DW2V: 목적함수와 최적화
4. 실험 설정
5. 실험 결과
6. 주의해서 읽을 점
7. 방법적 한계와 확장
8. 결론

---

## 1. 서론

### 1.1 연구 배경

blog/dbe에서 본 문제를 행렬의 언어로 다시 만난다. word2vec 계열 임베딩은 "단어는 시간에 대해 정적"이라고 가정하는데(§1), 실제로는 apple이 과일에서 기업으로, trump가 부동산 개발업자에서 정치인으로 움직인다. 시간 슬라이스별로 임베딩을 따로 학습하는 소박한 해법에는 구조적 문제가 있다: 임베딩 학습의 비용함수 대부분이 회전에 불변이라("most cost functions for training are invariant to rotations", §1), 독립 학습된 두 시점의 임베딩은 같은 잠재 공간에 있을 보장이 없다. 이것이 이 논문이 명명한 **정렬 문제(alignment problem)**다.

이 논문이 고른 코퍼스도 문제의식의 일부다. 선행 연구들이 Google N-Gram·COHA 같은 소설·잡지 모음을 쓴 것과 달리 뉴스(뉴욕타임스)를 쓰는데, 시사 사건이 이끄는 언어 진화를 보기에 유리하고 소셜미디어와 달리 문체가 일관되기 때문이라는 것이 §1의 논거다.

### 1.2 핵심 질문

기존 해법은 전부 2단계다: 시점별로 정적 임베딩을 먼저 학습하고, 나중에 시점 간 변환을 찾아 이어 붙인다(§1). 변환을 국소 이웃의 최소제곱으로 잡거나(Kulkarni et al., 2015), 의미가 안 변한 앵커 단어로 잡거나(Zhang et al., 2016; 전문가 감독 필요), 직교 변환(Procrustes)으로 잡는다(Hamilton et al., 2016). 논문이 짚는 2단계의 약점은 오차 전파다: 어느 한 시점의 데이터가 극도로 희소해 그 시점 임베딩이 부실하면, 인접쌍 순차 정렬은 그 이후·이전 연도 전부를 잘못 정렬한다(§2.2).

그래서 질문은 "정렬을 별도 단계로 두지 않고 학습 안에서 해결할 수 있는가"이고, 답은 전 시점 공동 최적화다. 논문의 표현으로 "main novelty는 시점 전체에 걸쳐 임베딩을 공동 학습해, 별도의 정렬 문제를 풀 필요 자체를 없애는 것"이다(§1).

### 1.3 학술적 위치

방법론의 뿌리는 word2vec 자체가 아니라 **word2vec의 행렬 분해 해석**이다. Levy & Goldberg (2014)는 skip-gram negative sampling(SGNS)이 (상수 shift가 붙은) PMI 행렬의 저계수 분해와 동치임을 보였고, 논문은 "우리 접근은 일차적으로 이 관찰에서 동기를 얻었다"고 명시한다(§2.1). SGNS를 직접 시간화하는 대신 그 동치물인 행렬 분해를 시간화하는 경로다. §7의 관련연구도 같은 구도로 정리된다: 시간 임베딩 문헌을 무평활 계열과 2단계 계열로 이분하고, 평가 관행에 대해서는 "인간이 만든 의미 이동 단어 데이터베이스로 평가하며, 우리 접근도 그러하다"고 스스로 밝힌다(§7; 이 문장이 이 글 6장에서 중요해진다).

같은 2017년 arXiv에 올라온 세 편, 즉 본 논문(1703.00607)과 Rudolph & Blei의 DBE(1703.08052), Bamler & Mandt의 dynamic skip-gram(1702.08359)이 "정렬을 모델 구조로 해결"하는 공동 학습 노선을 독립적으로 열었는데, 인용 관계는 비대칭이다. Rudolph & Blei는 각주에서 본 논문을 동시기 연구로 언급하지만, 본 논문의 참고문헌에는 나머지 두 편이 없다(§7과 참고문헌 전수 확인). 즉 이 논문은 다른 둘을 보지 못한 채 자신을 유일한 공동 학습 접근으로 제시한다. 세 편의 해법 언어도 갈린다: DBE는 확률 모델(random walk 사전분포), Bamler & Mandt는 베이즈 필터링, 본 논문은 정칙화 행렬 분해다. 같은 발상의 세 방언인 셈이다(논문 외 해석).

## 2. 예비 지식

### PMI와 word2vec의 행렬 분해 해석 (원논문 §2.1)

코퍼스 \(\mathcal{D}\)에서 창 크기 \(L\)(이 논문은 전체에서 L=5) 안의 동시출현으로 V×V PMI(pointwise mutual information) 행렬을 만든다:

\[ \mathrm{PMI}(\mathcal{D}, L)_{w,c} = \log\left( \frac{\#(w,c) \cdot |\mathcal{D}|}{\#(w) \cdot \#(c)} \right) \quad \text{(식 1)} \]

\(\#(w,c)\)는 동시출현 횟수, \(\#(w)\)는 단어 출현 횟수다. 두 단어가 우연 대비 얼마나 자주 함께 나오는지의 로그비로, 임베딩 학습의 목표는 내적이 이를 근사하는 것이다: \(u_w^\top u_c \approx \mathrm{PMI}_{w,c}\)(식 2). word2vec과 GloVe(Pennington et al., 2014)는 이를 암묵적으로 수행하며, Levy & Goldberg (2014)가 그 동치성을 보였다(§2.1).

시점별로는 음수 값을 0으로 자른 **PPMI**(positive PMI)를 쓴다: \(Y(t) = \max\{\mathrm{PMI}(\mathcal{D}_t, L), 0\}\)(식 3). 이유는 수치 안정성이다: 분수가 매우 작으면 로그가 큰 음수가 되어 불안정한데, 유의미한 쌍 대부분은 로그 인자가 1보다 크므로 0 절단이 해에 큰 영향을 주지 않는다는 것이 각주 2의 논거다(이 관행 자체도 Levy & Goldberg를 따른다).

### 시대별 임베딩과 정렬 문제 (원논문 §2.2)

시점별 분해 \(U(t)U(t)^\top \approx \mathrm{PPMI}(t, L)\)(식 4)는 해가 유일하지 않다. 임의의 직교행렬 R에 대해 \(U(t)R\)도 같은 근사 오차를 내기 때문이다(\(U(t)RR^\top U(t)^\top = U(t)U(t)^\top\), §2.2). 그래서 독립 학습된 시점들의 좌표계는 서로 임의로 회전되어 있고, "의미가 안 변한 단어는 시점이 달라도 같은 벡터"라는 제약을 어딘가에서 걸어야 한다. 이것을 학습 후에 거는 것이 2단계 방법, 학습 중에 거는 것이 이 논문이다. 표기를 하나 짚어 두면, 식 4는 word 벡터와 context 벡터를 구분하지 않는 대칭 분해라 word2vec의 비대칭(u, v 두 벡터) 구조와 다르다. 이 대칭성이 3장의 최적화 트릭과 연결된다.

## 3. DW2V: 목적함수와 최적화

### 목적함수 (원논문 §2.3)

\[ \min_{U(1), \dots, U(T)} \frac{1}{2}\sum_{t=1}^{T} \|Y(t) - U(t)U(t)^\top\|_F^2 + \frac{\lambda}{2}\sum_{t=1}^{T} \|U(t)\|_F^2 + \frac{\tau}{2}\sum_{t=2}^{T} \|U(t-1) - U(t)\|_F^2 \quad \text{(식 5)} \]

세 항의 역할은 명확하다. 첫 항은 시점별 PPMI 분해(데이터 적합), λ 항은 통상의 Frobenius 정칙화, 그리고 핵심인 **τ 항이 인접 시점 임베딩의 차이를 벌점화**해 정렬을 학습 안으로 가져온다. τ의 양 극한이 이 설계의 범위를 정한다: τ=0이면 정렬 없는 독립 학습, τ→∞이면 모든 시점이 같아지는 정적 임베딩이다(§2.3). 즉 비정렬 시대별 임베딩과 정적 임베딩이 한 축의 두 끝점이 되고, DW2V는 그 사이 어딘가를 τ로 고른다.

이 틀의 가장 강한 문장은 선행 방법의 재해석이다: "Kulkarni et al.과 Hamilton et al.의 방법은 식 (5)의 각 항을 따로따로 최적화하는 **준최적(suboptimal) 해**로 볼 수 있다"(§2.3). 2단계 방법이 정렬을 인접쌍별로 강제하는 것과 달리 식 5는 전 시점에 걸쳐 강제하므로, 특정 시점의 데이터 부실이 정렬 오차로 전파되지 않는다. 극단적 사례까지 명시한다: 단어 w가 \(\mathcal{D}_t\)에 아예 없으면 독립 분해는 \(u_w(t) \approx 0\)을 강제하지만, 적절한 τ에서 식 5의 해는 \(u_w(t-1)\)·\(u_w(t+1)\)에 가까워진다(§2.3). blog/dbe의 독자라면 이 τ 항이 눈에 익을 것이다. DBE의 Gaussian random walk 사전분포가 만드는 벌점 \(-(\lambda/2)\sum\|\rho^{(t)} - \rho^{(t-1)}\|^2\)과 같은 꼴이다(DBE 쪽의 정밀도 λ가 이 논문의 τ에 대응한다 — 기호가 겹치니 주의). 확률의 언어(사전분포)와 최적화의 언어(정칙화)로 쓰였을 뿐 같은 부품이다(논문 외 해석; 본 논문은 확률적 해석을 제시하지 않는다).

### 최적화: 비대칭 완화와 block coordinate descent (원논문 §3)

식 5는 그대로 풀기 어렵다. 데이터 적합 항이 U(t)의 4차식이라 시점 하나를 고정해도 폐형식이 없다(식 6–7). 해법은 보조 행렬 W(t)를 도입해 대칭성을 깨는 것이다:

\[ \min_{U(t), W(t)} \frac{1}{2}\sum_t \|Y(t) - U(t)W(t)^\top\|_F^2 + \frac{\gamma}{2}\sum_t \|U(t) - W(t)\|_F^2 + (\lambda, \tau \text{ 항은 } U, W \text{ 양쪽에 대칭으로}) \quad \text{(식 8)} \]

γ 항이 U ≈ W를 유도해 원 문제와의 연결을 유지한다. 이제 한 시점의 U(t)에 대한 최소화는 릿지 회귀(ℓ₂ 벌점이 붙은 최소제곱)가 되어 한 번에 풀린다: \(U(t)A = B\), 여기서 \(A = W(t)^\top W(t) + (\gamma + \lambda + 2\tau)I\), \(B = Y(t)W(t) + \gamma W(t) + \tau(U(t-1) + U(t+1))\)이다(§3). B의 마지막 항에서 이 모델의 작동 원리를 그대로 읽을 수 있다: 각 시점의 해가 이웃 두 시점 임베딩의 τ-가중 평균 쪽으로 당겨진다. 정렬이 별도 후처리가 아니라 갱신식 안에 들어 있다.

이렇게 블록(시점별 행렬, 더 잘게는 행 블록) 단위로 도는 것이 block coordinate descent(BCD)다. 행 블록으로 쪼개면 A·B 구성 비용이 어휘 크기 V에 독립이 되어 큰 어휘로 확장된다(§3). 논문은 BCD의 약점도 명시한다: 볼록 문제에서조차 수렴 보장이 없다(Powell 인용, §3). 실전에서 잘 작동한다는 문헌으로 방어하고, "최적화 방법의 선택은 모델과 무관하다 — 식 5를 잘 풀기만 하면 된다"고 덧붙인다(§3).

## 4. 실험 설정

원논문 §4에 해당한다. 코퍼스는 저자들이 직접 크롤링한 **뉴욕타임스 기사 99,872건**(1990년 1월–2016년 7월, 59개 섹션 라벨 포함)이고, 연 단위 T=27 슬라이스로 나눈다. 어휘는 전 기간 합산 200회 미만 희귀어와 불용어를 제거한 V=20,936이며, 슬라이스별 공기 행렬(L=5)을 PPMI로 변환해 Y(t)를 만든다. 하이퍼파라미터는 그리드 서치로 λ=10, τ=γ=50, 5 에폭을 골랐는데, 서치의 선택 기준(무엇에 대한 'best'인지)은 기재되어 있지 않다. λ=0으로 두어도 결과는 좋았으나 수렴이 느렸다는 것이 논문이 제공하는 유일한 민감도 정보다(§4). 임베딩 차원은 d=50(§6에서 명시), 유사도는 코사인이다. 데이터와 테스트셋은 공개되어 있다(각주 4·8).

비교 대상은 셋이고 모두 같은 NYT 코퍼스로 학습됐다(§4, §6): **SW2V**(정적 word2vec: 전체 코퍼스 학습, 시간 무시), **TW2V**(Kulkarni et al. 방식: 연도별 PPMI 분해 후 쿼리 단어의 k=30 최근접 이웃 기준 선형 변환 정렬), **AW2V**(Hamilton et al. 방식: 연도별 PPMI 분해 후 인접 시점 직교 변환 정렬). 주의할 점: 원 논문들은 SGNS 계열 임베딩 위에 정렬을 얹지만(논문 외 사실), 여기서는 같은 PPMI 분해 틀 위에 정렬 절차만 달리한 재구현이다. 통제된 비교라는 장점과, 원 구현 그대로의 비교가 아니라는 한계가 같이 있다. 동시기 공동 학습 방법(DBE·Bamler & Mandt)은 비교에 없다.

## 5. 실험 결과

### 정성: 궤적, 등가어, 인기도 (원논문 §5)

**궤적 시각화(§5.1, Figure 1).** 단어별 시간 임베딩의 t-SNE(고차원 벡터의 2차원 시각화 기법) 투영에 연도별 최근접 단어를 함께 그린다. apple은 과일·디저트에서 기술 공간으로 움직이는데 1994년에 잠깐 스파이크가 있고(CEO 교체·IBM 협업 보도), amazon은 열대우림에서 전자상거래로, 2016년에는 Prime Video 인기로 콘텐츠·스트리밍 쪽으로 움직인다. 별도의 정렬 최적화 없이 이 궤적이 나온다는 것이 정성적 논거다.

![DW2V Figure 1: trajectories](/api/blog/figures/dw2v-fig1-trajectories.png)

*그림 1 — 원논문 Figure 1: apple·amazon·obama·trump의 시간 궤적(t-SNE). 파란 점이 대상 단어의 연도별 위치, 검은 단어들이 각 시기의 이웃이다.*

**등가어 탐색(§5.2, Tables 1–3).** 이 논문의 가장 독자적인 프레임이다. 단어-연도 쌍의 벡터를 **다른 연도의 임베딩 집합에 넣어** 최근접 단어를 찾는다. 정렬이 제대로 되어 있어야만 성립하는 질의다. iphone-2012는 1990년대의 desktop·pc·macintosh에 대응하고 telephone은 끝내 등장하지 않으며(저자 해석: iPhone은 통화기기보다 휴대용 컴퓨터로 기능), twitter-2012는 1990년대의 방송(broadcast·cnn)에서 채팅·이메일, 블로그를 거쳐 온다. mp3-2000 질의에서는 napster가 2003년에 튀는데, 실제 서비스 종료(2001년)보다 2년 늦다. 후속 연도에 법적 파장이 집중 보도된 탓이라는 것이 각주 5의 해명이다. obama-2016(대통령 역할)으로 각 연도를 질의하면 bush→clinton→bush→obama가 순서대로 나오고, blasio-2015(NYC 시장 역할) 질의에서는 오답 2건이 별표로 표시되어 있다(Table 2). nadal-2010으로 연도별 ATP 남자 1위를 찾는 Table 3에서는 26칸 중 16칸이 정답으로 볼드 처리되어 있는데, 이 판정은 이 글 6장에서 다시 따진다. 참고로 코퍼스 수집 시점은 2016년 대선 약 반년 전이다(각주 6). trump 관련 서술을 읽을 때 걸리는 시간 단서다.

**norm 기반 인기도(§5.3, Figures 2–3).** PMI 분해 임베딩의 노름이 빈도와 함께 커진다는 기존 관찰(§5.3이 Pennington et al., 2014 등을 인용)을 탐색 도구로 전용한다. 대통령 이름들의 노름이 임기마다 4년 단위 혹을 그리고(Figure 2), enron은 빈도로는 qaeda보다 높이 튀지만 노름으로는 그렇지 않다(Figure 3). 빈도가 낮았던 pippen의 스타덤이 노름으로는 잡히고, isis가 qaeda를 대체하는 조직으로 떠오르는 것도 같은 그림에서 읽힌다. 노름이 빈도보다 "인기"를 안정적으로 추적한다는 논거인데, 전부 그림 기반 정성 관찰이고 정량 지표는 없다.

![DW2V Figure 2: presidents norm vs frequency](/api/blog/figures/dw2v-fig2-presidents.png)

*그림 2 — 원논문 Figure 2: 대통령 이름들(clinton·bush·obama·trump)의 노름(위)과 빈도(아래), 1990–2016. bush·clinton은 동명이인(부자·부부)을 겸한다는 캡션 주의가 붙어 있다.*

![DW2V Figure 3: event keywords norm vs frequency](/api/blog/figures/dw2v-fig3-events.png)

*그림 3 — 원논문 Figure 3: 사건 키워드(pippen·enron·qaeda·isis)의 노름(위)과 빈도(아래). enron은 빈도로는 qaeda 위로 튀지만 노름으로는 그렇지 않다.*

### 정량: 군집화, 정렬 질의, 강건성 (원논문 §6)

**군집화(§6.1, Tables 4–5).** 기사 섹션 라벨(임베딩 학습에는 미사용)에서 ground truth를 유도한다. 단어-연도 쌍의 섹션 점유율이 35% 이상이면 그 섹션을 정답으로 삼고(1,888개 트리플릿, 11개 섹션), spherical k-means(코사인 유사도 기반 k-평균)로 군집화해 NMI(군집-라벨 일치도)와 F-measure(β=5로 재현율을 가중한 F점수)를 잰다. DW2V가 전 칸 1위지만 격차는 근소하다: NMI에서 2위(SW2V) 대비 +0.0439/+0.0295/+0.0193(K=10/15/20). 크게 따돌리는 상대는 TW2V뿐이다. 눈에 띄는 부수 관찰: 시간을 무시한 SW2V가 정렬 기반 AW2V보다 NMI 전 열에서 높다. 2단계 정렬이 정적 baseline조차 못 이기는 구간이 있다는 뜻인데, 논문은 이 역전을 논평하지 않는다.

**정렬 질의(§6.2, Tables 6–7).** §5.2의 등가어 탐색을 대규모 테스트셋으로 승격시킨 것이 이 논문의 평가 기여다. Testset 1(N=11,028)은 공적 기록 기반으로, 미국 대통령·영국 총리·NFL 우승팀처럼 연도별로 역할의 점유자가 바뀌는 목록이다. Testset 2(N=445)는 저자가 만든("human-generated") 장거리 개념 대체로, app-2012의 벡터를 1990년대 초에 넣으면 software가 나와야 한다는 식이다. 지표는 MRR(정답의 역순위 평균, top-10 밖이면 0)과 MP@K(top-K 정답률). Testset 1에서 DW2V MRR 0.4222로 1위인데, 2위는 정렬 방법이 아니라 정적 SW2V(0.3560)다. 논문 스스로 이유를 설명한다: 이 셋은 단거리 정렬이 많아 "정적 임베딩에 유리한 테스트"다(§6.2). 정렬 방법들(AW2V 0.1582, TW2V 0.0920) 상대로는 2.7~4.6배 격차다. 논문이 §6.2에서 쓴 "때로는 한 자릿수(order of magnitude) 차이"는 Tables 6–7의 MRR에서는 10배에 못 미치고, 아래 Table 8에서 문자 그대로 성립한다. 장거리인 Testset 2에서는 전원 상대 우위(MRR 0.1444 vs 최고 baseline 0.0664)지만 절대 수준이 낮다. top-1 정답률 8% 미만으로, 20년 격차 개념 대체는 여전히 어려운 과제로 남는다(논문은 절대 수준을 논평하지 않는다).

**강건성(§6.3, Table 8).** 논문에서 가장 눈에 띄는 표다. 1991–2015 사이 3년마다의 연도에서 공기 행렬을 이항 서브샘플링(각 공기 횟수를 유지 비율 r의 이항분포로 다시 뽑음)으로 r=10%, 1%, 0.1%만 남기고 Testset 1을 재수행한다. 비교는 AW2V 하나뿐인데, "그 외에는 비견할 만한 성능"이라는 §6.3의 근거는 Table 6에서 SW2V가 AW2V보다 높았음을 생각하면 관대한 서술이다. 결과: AW2V는 MRR 0.1582→0.0884→0.0409→0.0362로 붕괴하는데 DW2V는 0.4222→0.4394→0.4418→0.4427로 유지된다(r=0.1%에서 약 12배). §2.3의 이론적 논거(τ 평활이 희소 시점을 이웃 정보로 메움)를 실증하는 실험이고, 2단계 방법의 오차 전파 주장도 여기서 확인된다. 다만 DW2V의 MRR이 데이터를 지울수록 오히려 오른다는 세부는 논문이 설명하지 않는다(이 글 6장에서 재론).

## 6. 주의해서 읽을 점

**평가의 순환 구조.** 정량 평가의 ground truth 3종이 전부 저자 구성이다. §6.1의 섹션 라벨은 학습에 안 쓰였다고 명시되지만 **같은 코퍼스**의 메타데이터이고, 선정 기준이 빈도 집중도(35% 임계)라 테스트 단어들이 고빈도어로 치우친다. Testset 2는 명시적으로 사람이 만든 셋(N=445)이다. 이것이 관행이라는 것은 논문 자신도 §7에서 인정한다: "시간 임베딩은 알려진 의미 이동 단어의 인간 제작 데이터베이스에 대해 평가되며, 우리 접근도 그러하다." 게다가 하이퍼파라미터 그리드 서치의 선택 기준이 미기재라, 튜닝과 평가의 분리 여부를 확인할 수 없다. baseline 쪽 튜닝 여부도 침묵이라 비대칭 튜닝 가능성이 남는다.

**Table 8의 상승은 양날이다.** 서브샘플링한 연도들에서 데이터의 99.9%를 지웠는데 MRR이 오히려 오르는 것은 "견고함"을 넘어선 신호다. 가장 자연스러운 설명은 이렇다(논문 외 해석): 데이터 항이 약해지면 τ 평활이 지배해 그 연도 임베딩이 이웃 연도와 거의 같아지는데, Testset 1은 논문 스스로 인정했듯 정적(단거리) 편향이 있는 테스트라서 평활할수록 점수가 오른다. 즉 이 표는 모델의 강건함과 동시에 평가 지표가 데이터 충실이 아니라 평활을 보상한다는 증거로도 읽히는데, 논문은 전자의 해석만 취한다. blog/dbe 6.3절의 보간 문제와 정확히 같은 구조다: 데이터 없는 시기의 벡터는 정칙화가 만든 것이고, 표면상 데이터 유래 추정과 구별되지 않는다.

**등가어 표의 정답률은 원문 볼드를 직접 세야 한다.** Table 3(ATP 1위)에서 논문이 볼드로 정답 처리한 칸은 26칸 중 16칸이다(원 PDF의 폰트 정보로 복원; 본문 서술은 "놀랄 만큼 많은 수가 정답"이라고만 한다). 외부 ATP 연말 랭킹과 대조하면 그중 1999년 칸(sampras)은 실제 1위가 Agassi라 논문의 정답 판정 자체가 어긋나고, 오답 칸의 2002년 capriati는 여자 선수라 "남자 1위" 질의의 범주 밖이다(논문 외 대조). "오답도 전부 당대 유명 테니스 선수"라는 논문의 서술은 틀린 말은 아니지만 실패를 성공의 언어로 감싼 문장이다.

**norm=인기도 해석은 이 논문 안에서만 성립한다.** 노름은 빈도 외에 다의성·문맥 분포에도 의존하고, 이 모델에서는 λ 수축과 τ 평활이 노름을 직접 변형한다. 특히 데이터 없는 연도의 노름은 순전히 정칙화 산물이다. Figure 2–3 곡선의 부드러움 자체가 τ가 만든 것일 수 있는데, 신호와 평활을 구분할 독립 근거가 없다. 이후 문헌에서도 노름 기반 인기도 지표는 표준으로 자리 잡지 못했다(논문 외 지식).

**재현 관련 자잘한 어긋남.** §4의 블록 변수 표기 "U(t) or V(t)"의 V(t)는 식 8의 W(t)의 오기로 보이고, §6.3의 서브샘플링 서술("missed with probability r")은 r=1이 완전 데이터이므로 유지 확률로 읽어야 정합이다(원문 표현 문제). 통계 검정·복수 시드 반복은 없다 — 비볼록 최적화라 시드에 따라 다른 국소해에 도달할 수 있는 방법인데, 모든 표가 단일 실행 수치다.

## 7. 방법적 한계와 확장

### 7.1 논문이 남긴 것

§8 Conclusion에는 한계 서술도 future work도 없다. 기여 요약("higher interpretability for embeddings, better quality with less data, and more reliable alignment for across-time querying")뿐이다. 본문에 흩어진 자기 인정은 다음과 같다.

| 논문이 인정한 사실 | 위치 |
|---|---|
| BCD는 볼록 문제에서도 수렴 보장이 없다 | §3 |
| Testset 1은 단거리 정렬 위주라 정적 임베딩에 유리하다 | §6.2 |
| Testset 2는 "다소 주관적으로" 구성됐다 | §1, §6.2 |
| 평가는 인간 제작 데이터베이스 대상이며 "우리 접근도 그러하다" | §7 |
| napster 등가어가 실제 사건보다 2년 늦게 잡혔다 | §5.2 각주 5 |
| 시장 질의에 오답 2건(2006 n/a, 2011 cuomo) | Table 2 |

### 7.2 방법 내재적 한계 (논문 외 비판)

- **무가중 PPMI 분해는 0을 데이터로 취급한다.** Frobenius 적합은 Y(t)의 0인 칸도 전부 0으로 근사하라는 관측처럼 다룬다. SGNS의 암묵적 가중이나 GloVe의 빈도 가중과 달리 관측·비관측 쌍을 동일 가중으로 적합하는 것이고, Levy & Goldberg의 등가성(SGNS = *shifted* PMI의 *가중* 분해)에서 한 발 벗어나 있다. PMI의 저빈도 편향(Levy et al., 2015)도 연 단위로 데이터를 쪼갠 이 설정에서 더 심해질 수 있는데 분석이 없다.
- **어휘 구성과 문제 설정의 어긋남.** 어휘가 전 기간 공통이라 iphone은 1990년에도 벡터를 갖고, 그 벡터는 정칙화가 만든 것이다(이 글 6장). 여기에 더해 어휘 선정 기준이 전 기간 합산 200회라서, 특정 해에만 폭발한 진짜 신조어가 걸러질 수 있다. "emerging words"를 다룬다는 §2의 문제 설정과 어휘 구성이 서로 어긋난다.
- **전역 단일 τ.** 의미 변화 속도는 단어마다 다른데("소수 단어만 의미 이동을 겪는다"는 것이 논문 자신의 전제, §2.2) 단일 τ는 빠르게 변하는 단어를 지나치게 평활하고, 안정된 단어에는 제약이 모자란다. γ와 τ가 같은 값(50)으로 보고되는 것도 서치 결과로만 제시될 뿐 논거가 없다. DBE의 전역 단일 정밀도와 같은 구조의 한계다.
- **점추정.** 초록의 "dynamic statistical model"이라는 표현과 달리 확률 모델이 아니고 불확실성 정량화가 없다. 동시기 세 편 중 확률적 해석에서 가장 먼 자리다(Bamler & Mandt는 사후분포까지, DBE는 확률 모델이되 MAP 점추정까지).

### 7.3 이후 계보 (논문 외 지식)

공동 학습 3부작(본 논문·DBE·Bamler & Mandt)은 이후 서베이(Kutuzov et al., 2018)에서 한 갈래로 묶인다. 이 논문의 고유한 유산은 방법보다 **평가 프레임** 쪽이다: 등가어 질의는 같은 해 Szymanski (2017)의 temporal word analogy와 본질적으로 같은 과제로 자리 잡았고, 공개된 NYT 코퍼스·테스트셋은 후속 시간 임베딩 연구의 벤치마크로 재사용됐다. 반면 평가 표준의 관점에서는 DBE 리뷰 7.3절의 이야기가 그대로 적용된다: SemEval-2020 Task 1(Schlechtweg et al., 2020)이 인간 주석 기반 표준을 세운 뒤로 보면 이 논문의 자작 테스트셋 평가는 이전 세대의 것이고, 빈도 혼입 통제(Dubossarsky et al., 2017)도 없다. 특히 SemEval에서 상위권을 차지한 것이 이 논문이 이겼다고 주장한 SGNS+직교 정렬(Hamilton형 2단계) 계열이었다는 점에서, "공동 학습 > 2단계"는 저자 자작 벤치마크 밖에서는 아직 일반적으로 입증된 명제가 아니다. compass 계열(Di Carlo et al., 2019)은 문맥 행렬 고정이라는 제3의 절충으로 뒤따랐다.

### 7.4 위키·사회과학 관점에서 (논문 외 해석)

DWE 트랙에서 이 논문과 DBE의 분담은 명확하다. DBE가 "왜 공동 학습인가"의 확률적 정당화를 맡는다면, 이 논문은 2단계 방법을 목적함수의 준최적 해로 포섭하는 통합 관점, 희소 데이터 강건성의 실증(Table 8), 그리고 등가어 탐색이라는 응용 프레임을 맡는다. 사회과학 측정의 눈으로 보면 등가어 질의는 **역할과 점유자를 분리하는 장치**다: president·mayor 같은 제도적 역할의 임베딩 자리는 유지되고 그 이웃의 인명이 교체된다는 관찰(§6.2)은, 시간 코퍼스에서 제도의 연속성과 행위자 교체를 동시에 추적할 수 있음을 보여준다. 한국어 통시 코퍼스라면 "각 시기의 ○○에 해당하는 인물·기관은 누구였나"류의 질의가 같은 틀로 설계될 수 있다. norm-빈도 분리도 "언급량"과 "의미 구조에서의 비중"을 구분하는 지표 발상으로서 참조 가치가 있다. 단 6장의 경고(노름은 정칙화 산물일 수 있다)를 붙여서. 이 함의들은 논문의 검증 범위(영어 뉴스, 연 단위, 27년)를 넘는 확장이다.

## 8. 결론

DW2V는 정렬 문제를 명명하고, 그것을 목적함수의 평활 항 하나로 녹인 논문이다. 수학적 부품은 소박하다. PPMI 분해에 1차 차분 벌점을 더한 정칙화 행렬 분해이고, 최적화도 릿지 회귀의 반복이다. 그 소박함 덕분에 이 노선의 요점이 가장 투명하게 드러난다: DBE가 사전분포로 말한 것을 이 논문은 벌점 항으로 말하고, 둘은 같은 것이다. 실증의 무게는 정확도보다 강건성에 있다(평시 격차는 근소하고, 데이터를 지웠을 때 12배 벌어진다). 그리고 방법 못지않은 유산이 평가 쪽에 있다 — 등가어 질의라는 과제, 공개 코퍼스와 테스트셋. 다만 그 테스트셋이 저자 구성이라는 순환, 평활이 점수로 보상되는 지표 구조, 검정 없는 단일 실행은 이 세대 논문들의 공통 조건으로 함께 기억해야 한다.

읽는 법을 정리하면:

| 목적 | 어디를 읽나 |
|---|---|
| 정렬 문제의 정식화 | §2.2의 회전 불변성, 이 글 2장 |
| 모델의 핵심 한 줄 | 식 5의 τ 항과 §2.3의 준최적 해 재해석, 이 글 3장 |
| 성능 주장의 실제 강도 | Tables 4–7의 근소한 칸과 Table 8의 12배, 이 글 5장 |
| 강건성 결과의 이면 | Table 8의 단조 상승, 이 글 6장 |
| DBE와의 관계 | 이 글 1.3절·3장(같은 부품, 두 언어), blog/dbe |

시리즈의 다음 연결로는, 셋 중 유일하게 불확실성까지 다룬 Bamler & Mandt (2017), 그리고 이 세대가 이긴 것으로 알려졌다가 SemEval-2020에서 되살아난 Hamilton et al. (2016)의 2단계 정렬이 자연스러운 후속이다.

## References

Bamler, R., & Mandt, S. (2017). Dynamic word embeddings. *Proceedings of the 34th International Conference on Machine Learning*, 380–389. https://arxiv.org/abs/1702.08359 ([PDF 보기](/paper-viewer?title=Dynamic+word+embeddings&source=blog-reference&authors=Robert+Bamler%3BStephan+Mandt&year=2017&arxiv_id=1702.08359&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1702.08359.pdf))

Di Carlo, V., Bianchi, F., & Palmonari, M. (2019). Training temporal word embeddings with a compass. *Proceedings of the AAAI Conference on Artificial Intelligence*, *33*(1), 6326–6334. https://doi.org/10.1609/aaai.v33i01.33016326 ([PDF 보기](/paper-viewer?title=Training+Temporal+Word+Embeddings+with+a+Compass&source=blog-reference&authors=Valerio+Di+Carlo%3BFederico+Bianchi%3BMatteo+Palmonari&year=2019&doi=10.1609%2Faaai.v33i01.33016326&url=https%3A%2F%2Fdoi.org%2F10.1609%2Faaai.v33i01.33016326))

Dubossarsky, H., Weinshall, D., & Grossman, E. (2017). Outta control: Laws of semantic change and inherent biases in word representation models. *Proceedings of the 2017 Conference on Empirical Methods in Natural Language Processing*, 1136–1145. https://doi.org/10.18653/v1/D17-1118 ([PDF 보기](/paper-viewer?title=Outta+Control%3A+Laws+of+Semantic+Change+and+Inherent+Biases+in+Word+Representation+Models&source=blog-reference&authors=Haim+Dubossarsky%3BDaphna+Weinshall%3BEitan+Grossman&year=2017&doi=10.18653%2Fv1%2FD17-1118&url=https%3A%2F%2Fdoi.org%2F10.18653%2Fv1%2FD17-1118))

Hamilton, W. L., Leskovec, J., & Jurafsky, D. (2016). Diachronic word embeddings reveal statistical laws of semantic change. *Proceedings of the 54th Annual Meeting of the Association for Computational Linguistics*, 1489–1501. https://doi.org/10.18653/v1/P16-1141 ([PDF 보기](/paper-viewer?title=Diachronic+Word+Embeddings+Reveal+Statistical+Laws+of+Semantic+Change&source=blog-reference&authors=William+L.+Hamilton%3BJure+Leskovec%3BDan+Jurafsky&year=2016&doi=10.18653%2Fv1%2FP16-1141&url=https%3A%2F%2Fdoi.org%2F10.18653%2Fv1%2FP16-1141))

Kulkarni, V., Al-Rfou, R., Perozzi, B., & Skiena, S. (2015). Statistically significant detection of linguistic change. *Proceedings of the 24th International Conference on World Wide Web*, 625–635. https://doi.org/10.1145/2736277.2741627 ([PDF 보기](/paper-viewer?title=Statistically+Significant+Detection+of+Linguistic+Change&source=blog-reference&authors=Vivek+Kulkarni%3BRami+Al-Rfou%3BBryan+Perozzi%3BSteven+Skiena&year=2015&doi=10.1145%2F2736277.2741627&url=https%3A%2F%2Fdoi.org%2F10.1145%2F2736277.2741627))

Kutuzov, A., Øvrelid, L., Szymanski, T., & Velldal, E. (2018). Diachronic word embeddings and semantic shifts: A survey. *Proceedings of the 27th International Conference on Computational Linguistics*, 1384–1397. https://arxiv.org/abs/1806.03537 ([PDF 보기](/paper-viewer?title=Diachronic+Word+Embeddings+and+Semantic+Shifts%3A+A+Survey&source=blog-reference&authors=Andrey+Kutuzov%3BLilja+%C3%98vrelid%3BTerrence+Szymanski%3BErik+Velldal&year=2018&arxiv_id=1806.03537&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1806.03537.pdf))

Levy, O., & Goldberg, Y. (2014). Neural word embedding as implicit matrix factorization. *Advances in Neural Information Processing Systems*, *27*. ([PDF 보기](/paper-viewer?title=Neural+Word+Embedding+as+Implicit+Matrix+Factorization&source=blog-reference&authors=Omer+Levy%3BYoav+Goldberg&year=2014))

Levy, O., Goldberg, Y., & Dagan, I. (2015). Improving distributional similarity with lessons learned from word embeddings. *Transactions of the Association for Computational Linguistics*, *3*, 211–225. https://doi.org/10.1162/tacl_a_00134 ([PDF 보기](/paper-viewer?title=Improving+Distributional+Similarity+with+Lessons+Learned+from+Word+Embeddings&source=blog-reference&authors=Omer+Levy%3BYoav+Goldberg%3BIdo+Dagan&year=2015&doi=10.1162%2Ftacl_a_00134&url=https%3A%2F%2Fdoi.org%2F10.1162%2Ftacl_a_00134))

Pennington, J., Socher, R., & Manning, C. (2014). GloVe: Global vectors for word representation. *Proceedings of the 2014 Conference on Empirical Methods in Natural Language Processing*, 1532–1543. https://doi.org/10.3115/v1/D14-1162 ([PDF 보기](/paper-viewer?title=GloVe%3A+Global+Vectors+for+Word+Representation&source=blog-reference&authors=Jeffrey+Pennington%3BRichard+Socher%3BChristopher+D.+Manning&year=2014&doi=10.3115%2Fv1%2FD14-1162&url=https%3A%2F%2Fdoi.org%2F10.3115%2Fv1%2FD14-1162))

Rudolph, M., & Blei, D. (2018). Dynamic embeddings for language evolution. *Proceedings of the 2018 World Wide Web Conference*, 1003–1011. https://doi.org/10.1145/3178876.3185999 ([PDF 보기](/paper-viewer?title=Dynamic+Embeddings+for+Language+Evolution&source=blog-reference&authors=Maja+Rudolph%3BDavid+M.+Blei&year=2018&doi=10.1145%2F3178876.3185999&arxiv_id=1703.08052&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1703.08052.pdf&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3178876.3185999))

Schlechtweg, D., McGillivray, B., Hengchen, S., Dubossarsky, H., & Tahmasebi, N. (2020). SemEval-2020 Task 1: Unsupervised lexical semantic change detection. *Proceedings of the Fourteenth Workshop on Semantic Evaluation*, 1–23. https://doi.org/10.18653/v1/2020.semeval-1.1 ([PDF 보기](/paper-viewer?title=SemEval-2020+Task+1%3A+Unsupervised+Lexical+Semantic+Change+Detection&source=blog-reference&authors=Dominik+Schlechtweg%3BBarbara+McGillivray%3BSimon+Hengchen%3BHaim+Dubossarsky%3BNina+Tahmasebi&year=2020&doi=10.18653%2Fv1%2F2020.semeval-1.1&url=https%3A%2F%2Fdoi.org%2F10.18653%2Fv1%2F2020.semeval-1.1))

Szymanski, T. (2017). Temporal word analogies: Identifying lexical replacement with diachronic word embeddings. *Proceedings of the 55th Annual Meeting of the Association for Computational Linguistics (Volume 2: Short Papers)*, 448–453. https://doi.org/10.18653/v1/P17-2071 ([PDF 보기](/paper-viewer?title=Temporal+Word+Analogies%3A+Identifying+Lexical+Replacement+with+Diachronic+Word+Embeddings&source=blog-reference&authors=Terrence+Szymanski&year=2017&doi=10.18653%2Fv1%2FP17-2071&url=https%3A%2F%2Fdoi.org%2F10.18653%2Fv1%2FP17-2071))

Yao, Z., Sun, Y., Ding, W., Rao, N., & Xiong, H. (2018). Dynamic word embeddings for evolving semantic discovery. *Proceedings of the Eleventh ACM International Conference on Web Search and Data Mining*, 673–681. https://doi.org/10.1145/3159652.3159703 ([PDF 보기](/paper-viewer?title=Dynamic+Word+Embeddings+for+Evolving+Semantic+Discovery&source=blog-reference&authors=Zijun+Yao%3BYifan+Sun%3BWeicong+Ding%3BNikhil+Rao%3BHui+Xiong&year=2018&doi=10.1145%2F3159652.3159703&arxiv_id=1703.00607&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1703.00607.pdf&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3159652.3159703))

Zhang, Y., Jatowt, A., Bhowmick, S. S., & Tanaka, K. (2016). The past is not a foreign country: Detecting semantically similar terms across time. *IEEE Transactions on Knowledge and Data Engineering*, *28*(10), 2793–2807. https://doi.org/10.1109/TKDE.2016.2591008 ([PDF 보기](/paper-viewer?title=The+Past+is+Not+a+Foreign+Country%3A+Detecting+Semantically+Similar+Terms+Across+Time&source=blog-reference&authors=Yue+Zhang%3BAdam+Jatowt%3BSourav+S.+Bhowmick%3BKatsumi+Tanaka&year=2016&doi=10.1109%2FTKDE.2016.2591008&url=https%3A%2F%2Fdoi.org%2F10.1109%2FTKDE.2016.2591008))
