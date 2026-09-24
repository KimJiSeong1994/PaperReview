# Dynamic Word Embeddings

**Paper:** Bamler, Robert; Mandt, Stephan. (2017). "Dynamic Word Embeddings." *Proceedings of the 34th International Conference on Machine Learning (ICML 2017), PMLR 70*, pp. 380–389. arXiv:1702.08359.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 시기별로 임베딩을 따로 학습해 사후에 정렬로 잇는 대신, 모든 시기를 한 번에 공동 학습해 임베딩이 시간에 따라 매끄럽게 흐르게 할 수 있는가? 그러면서 각 시기가 서로의 데이터에서 통계적 강도를 나눠, 데이터가 적은 시기도 안정적으로 세울 수 있는가? |
| 핵심 기여 | 베이지안 skip-gram의 임베딩을 잠재 시계열로 두고 Ornstein-Uhlenbeck 확산 prior로 이어, 시대별 임베딩을 사후 정렬 문제에서 하나의 확률적 상태공간 모델(동적 skip-gram, DSG)의 공동 학습 문제로 옮겼다. 시기별 개별 학습의 세 문제(비볼록 학습의 비재현성, 시기 분할로 인한 데이터 부족, 잡음과 진짜 의미 변화의 혼동)를 공동 학습으로 우회한다. |
| 방법적 결과 | 추론은 두 갈래다. 과거 데이터만 조건으로 쓰는 온라인 필터링(DSG-F, 칼만 필터 방식의 가우시안 폐형 갱신)과, 전 시퀀스를 조건으로 쓰는 배치 스무딩(DSG-S, 삼중대각 정밀도행렬로 인접 시점 상관을 표현). 삼중대각 Λ=BᵀB 촐레스키 분해로 스무딩의 그래디언트 계산이 시퀀스 길이에 선형인 Θ(T)가 된다. |
| 실험 결과 | 시간 규모가 다른 세 코퍼스(Google Books T=209, State of the Union T=230, Twitter 21개 날짜)의 held-out 문서 예측 로그우도에서 순서가 일관되게 DSG-S > DSG-F > SGP ≈ SGI(정적 baseline). 개선폭은 데이터가 적은 SoU·Twitter에서 가장 크고, 궤적도 사후 정렬 방식보다 매끄럽다. |
| 핵심 한계 | 전역 확산 상수 하나가 모든 단어의 변화 속도를 정하고(논문 스스로 인정한 한계), 가우시안 확산 prior가 급변을 완만한 곡선으로 뭉갤 수 있으며, 스무딩은 미래 정보를 과거로 흘려 인공적 조기 변화를 만들 수 있다. 정량 평가는 수치 표 없이 그림으로만 제시된 held-out 예측 로그우도 하나에 의존한다. |

**TL;DR** — (1) **Dynamic Word Embeddings**(Bamler & Mandt, ICML 2017)는 베이지안 **skip-gram** 임베딩을 잠재 시계열로 두고 **Ornstein-Uhlenbeck 확산 prior**로 이어, 시대별 임베딩을 사후 정렬 없이 하나의 확률적 상태공간 모델로 공동 학습하는 동적 skip-gram(**DSG**)이다. (2) 온라인 **필터링**과 삼중대각 정밀도행렬로 시퀀스 길이 선형 비용 Θ(T)를 얻는 배치 **스무딩** 두 추론을 제시하고, 세 코퍼스의 held-out 예측 로그우도에서 DSG-S > DSG-F > 정적 baseline 순서가 일관되며 이득은 데이터가 적을수록 크다. (3) 다만 매끄러운 궤적은 확산 prior가 만든 것이라 진짜 급변을 지우거나 정보를 과거로 흘릴 수 있고, 전역 확산 상수 하나와 단일 지표 의존이라는 한계가 남는다.

---

## 목차

1. 서론
2. 방법: 확률적 상태공간 모델
3. 실험 설정
4. 실험 결과
5. 주의해서 읽을 점
6. 방법적 한계와 확장
7. 결론

---

## 1. 서론

### 1.1 연구 배경

정적 임베딩은 한 단어의 의미가 코퍼스 전체에서 불변이라고 가정한다. 시간에 따른 의미 변화를 보려면 시기별 임베딩이 필요한데, 그 방법의 대다수는 코퍼스를 시기별로 나눠 따로 학습한 뒤 사후에 잇는다. 이 논문은 그런 시기별 개별 학습의 세 가지 문제를 든다. 첫째, skip-gram 학습이 비볼록이라 같은 데이터로 두 번 돌려도 결과가 달라진다. 둘째, 코퍼스를 시기로 쪼개면 각 시기의 학습셋이 너무 작아질 수 있다. 셋째, 유한한 코퍼스에서 오는 통계적 잡음이 체계적인 의미 변화와 구분되지 않는다.

이 세 문제의 공통 뿌리는 시기들이 서로 통계적 강도를 나누지 못한다는 데 있다. 각 시기가 자기 데이터만으로 임베딩을 세우니, 데이터가 적으면 흔들리고 시기 사이의 연속성도 사후에 억지로 맞춰야 한다.

![최다 드리프트 단어 궤적](/api/blog/figures/bamler-fig1-drifting-words.png)

*1850년에서 2008년 사이 코사인 거리가 가장 많이 변한 10개 단어(원논문 Figure 1, Google Books, 필터링). 각 패널에서 붉은 곡선은 시작 시점의 최근접 5개 단어, 파란 곡선은 끝 시점의 최근접 5개 단어와의 코사인 거리다. "computer"·"radio"·"software"처럼 기술 발전으로 뜻이 바뀐 단어와, "peer"·"notably"처럼 변화가 덜 뚜렷한 단어가 함께 잡힌다.*

### 1.2 핵심 질문

논문의 질문은 이렇다. 시기별로 따로 학습해 사후에 잇는 대신, 모든 시기를 한 번에 공동 학습해 임베딩이 시간에 따라 매끄럽게 흐르도록 만들 수 있는가. 그러면서 각 시기가 서로의 데이터에서 통계적 강도를 나눠, 데이터가 적은 시기도 안정적으로 세울 수 있는가.

### 1.3 학술적 위치

논문은 자신을 확률적 상태공간 모델로 규정한다. **Barkan(2017)의 베이지안 skip-gram**을 building block으로 삼되, 그 모델이 임베딩에 가우시안 prior를 두면서도 벡터가 시간에 따라 변하는 것은 허용하지 않는다는 점을 넘어선다. 대비 대상은 두 부류다. 시기별 독립 학습 후, 인접 시점 임베딩이 전역 회전과 작은 의미 드리프트만큼 차이 난다고 보고 그 회전을 근사 계산해 정렬하는 방식(Hamilton 2016), 그리고 직전 시기 벡터로 다음 시기를 초기화하는 방식(Kim 2014)이다. 논문은 앞의 회전이 엄밀히는 존재하지 않아 정렬 인공물을 진짜 변화와 구분하기 어렵고, 뒤의 초기화 연쇄는 궤적이 자기 방법만큼 매끄럽지 않다고 본다.

방법의 재료도 계보가 뚜렷하다. 시간 확산은 **Ornstein-Uhlenbeck 과정**(Uhlenbeck & Ornstein, 1930)에서, 추론은 **black-box 변분추론**(Ranganath 등)과 **reparameterization**(Rezende 등)에서 온다. 잠재 시계열 확률 모델 중 가장 가까운 것으로 동적 토픽 모델(Blei & Lafferty, Wang 등)을 들되, 그것은 bag-of-words라 단어를 의미 관계 없는 기호로 다루므로 목적이 다르다고 선을 긋는다. 논문은 이와 독립적으로 개발된 Rudolph & Blei(2018)의 모델을 든다. 다른 우도를 쓰되 임베딩 궤적을 비베이지안으로 다뤄, 시점당 데이터가 적을 때 잡음에 덜 강건하다고 대비한다.

---

## 2. 방법: 확률적 상태공간 모델

### 베이지안 skip-gram 우도

먼저 한 시점의 모델이다. 임베딩을 점추정하지 않고 잠재변수로 두는 베이지안 skip-gram을 쓴다. 단어-문맥쌍 $(i,j)$의 관측 공기 횟수 $n^+_{ij}$와, 잡음 분포에서 만든 가상의 부정례 횟수 $n^-_{ij}$에 대한 로지스틱 우도다.

$$\log p(n^\pm \mid U, V) = \sum_{i,j} \Big( n^+_{ij} \log \sigma(u_i^\top v_j) + n^-_{ij} \log \sigma(-u_i^\top v_j) \Big) \quad (\text{Eq. 2})$$

$\sigma$는 시그모이드이고, 부정례는 유니그램 분포에서 $n^-_{ij} \propto P(i)P(j)^{3/4}$로 만든다. word2vec의 negative sampling을 베르누이 우도로 재해석한 형태다.

### 시간을 잇는 확산 prior

핵심은 시점 사이를 잇는 prior다. 각 단어의 임베딩 벡터가 시간에 따라 Ornstein-Uhlenbeck 과정으로 흐른다. 전이 분산은 시간 간격에 비례한다.

$$\sigma_t^2 = D(\tau_{t+1} - \tau_t) \quad (\text{Eq. 3})$$

$D$는 전역 확산 상수로, 임베딩이 얼마나 빨리 표류하는지를 정한다. 전이 커널은 다음과 같다.

$$U_{t+1} \mid U_t \sim \mathcal{N}\!\left( \frac{U_t}{1 + \sigma_t^2/\sigma_0^2}, \; \frac{1}{\sigma_t^{-2} + \sigma_0^{-2}} I \right) \quad (\text{Eq. 5})$$

여기서 눈여겨볼 것은 평균이 직전 값 $U_t$ 그대로가 아니라 $1/(1+\sigma_t^2/\sigma_0^2)$만큼 원점 쪽으로 수축된다는 점이다. $\sigma_0$를 무한대로 보내면 순수 Wiener 과정(브라운 운동)이 되는데, Wiener만 쓰면 궤적이 무한대로 발산한다. $\sigma_0$가 유한하면 원점으로 당기는 감쇠가 발산을 막는다. 다만 실험에서는 $\sigma_0^2=1$로 두고 $\sigma_0$가 $\sigma_t$보다 훨씬 커서, 이 감쇠는 실제로는 매우 약하게 작동한다. 전체 생성 모델은 이 전이들의 곱과 각 시점 관측 우도의 곱이다(Eq. 7; 그래프 모델은 원논문 Figure 2로, $T$개의 베이지안 skip-gram을 잠재 시계열 prior로 잇는 구조다). 가우시안 마르코프 사슬 prior에 로지스틱 관측을 얹은 상태공간 모델이라, 정확 추론은 불가능하고 근사가 필요하다.

### 필터링과 스무딩

논문은 근사 추론을 두 갈래로 제시한다.

**필터링**(§4.1)은 온라인이다. 변분분포를 시점별로 완전히 분해하고($q = \prod_t q(U_t, V_t)$), 과거 데이터 $n_{1:t}$만 조건으로 쓴다. 직전 시점의 사후분포를 전이 커널로 밀어 다음 시점의 prior로 삼는 칼만 필터(Kalman, 1960) 방식의 가우시안 폐형 갱신이다. 정보가 오직 앞으로만 흐른다.

**스무딩**(§4.2)은 배치다. 각 단어의 궤적에 대해 시간 영역의 다변량 가우시안 $q(u_{1:T}) = \mathcal{N}(\mu, \Lambda^{-1})$을 쓰는데, 정밀도행렬 $\Lambda$가 삼중대각이다. 인접 시점끼리만 직접 연결하는 구조라 마르코프 시간 상관을 담으면서도 계산이 가볍다. 전 시퀀스 $n_{1:T}$를 조건으로 써서 정보가 앞뒤 양방향으로 흐른다. 로지스틱 우도라 켤레가 아니어서 black-box 변분추론과 reparameterization으로 최적화한다. 삼중대각 $\Lambda$를 $\Lambda = B^\top B$로 이중대각 촐레스키 인수 $B$로 두면 그래디언트 계산이 시퀀스 길이에 선형인 $\Theta(T)$가 된다. 이중대각 $B$는 인접 시점만 잇는 비영 원소가 $O(T)$개뿐이라, 표본을 뽑는 후진대입도 엔트로피의 로그 행렬식 항도 모두 $O(T)$에 풀린다. 밀집 $T\times T$ 행렬로 다루면 촐레스키·역행렬이 $\Theta(T^2)$ 이상인데, 삼중대각 구조가 이를 선형으로 낮춘다.

스무딩이 필터링보다 나은 이유를 논문은 두 가지로 든다. 과거와 미래 양방향으로 정보를 나누고, 더 유연한 변분분포를 쓴다는 것이다. 필터링의 시점별 분해된 $q$는 인접 시점 사이의 사후 상관을 표현하지 못하지만, 스무딩의 삼중대각 $\Lambda$는 그 상관을 담는다.

---

## 3. 실험 설정

시간 규모가 크게 다른 세 코퍼스를 쓴다.

| 코퍼스 | 시점 수 | 규모 | 차원 | 성격 |
|---|---|---|---|---|
| Google Books | T=209 (1800–2008) | ~10¹⁰ 단어(약 5백만 권) | d=200 | 대(연 단위) |
| State of the Union | T=230 | ~10⁶ 단어 | d=100 | 중(연설) |
| Twitter 뉴스 | 21개 날짜(2010–2016) | 하루 중앙값 722 트윗 | d=100 | 소 |

세 코퍼스 모두 어휘 상위 1만 단어, 문맥창 4, 부정례 대 정례 비율 1로 통일한다. Google Books는 5-gram 카운트를 쓰되 현대어가 어휘를 지배하지 않도록 연도별 빈도를 정규화해 합산한다. State of the Union은 일부 대통령이 같은 해에 서면·구두 연설을 모두 남겨, 두 연설이 한 주 이내면 병합해 평균 날짜로 묶은 결과가 T=230 시점이다. 비교 대상은 넷이다. 제안 방법 두 가지(필터링 DSG-F, 스무딩 DSG-S)와 정적 baseline 두 가지다. baseline SGI는 시기별로 독립 학습한 뒤 직교 회전으로 정렬하는 방식(Hamilton 2016), SGP는 SGI를 직전 해 벡터로 초기화한 방식(Kim 2014)이다.

평가는 held-out 문서에 대한 예측 로그우도다(Eq. 16). 각 시점에서 문서의 일부(Google Books·SoU 10%, Twitter 20%)를 떼어 두고, 그 문서의 단어-문맥 통계를 얼마나 잘 예측하는지를 쌍당 로그우도로 잰다. 정규화 분모 $|n^\pm_t|$는 시점 $t$의 총 단어-문맥 쌍 수 $\sum_{ij}(n^+_{ij,t}+n^-_{ij,t})$이라, 시점마다 데이터량이 달라도 값을 견줄 수 있다. 요령은 평가 시점 $t$의 임베딩을 그 시점 자신이 아니라 이웃 시점에서 가져오는 데 있다. 필터링은 직전 시점 $t{-}1$의 사후 최빈값을 앞으로 옮겨 쓰고, 스무딩은 $t{-}1$과 $t{+}1$을 선형 보간해 쓴다. 시간 prior가 이웃 시점만으로 그 시점의 통계를 얼마나 재현하는지를 시험하는 셈이다.

---

## 4. 실험 결과

### 예측 로그우도: 스무딩 > 필터링 > 정적

held-out 예측 로그우도를 네 방법에 걸쳐 비교한다. 논문은 수치 표 없이 그림으로만 제시한다.

![예측 로그우도](/api/blog/figures/bamler-fig6-predictive-likelihood.png)

*세 코퍼스에서 시점별 예측 로그우도(원논문 Figure 6, 높을수록 좋음). 제안 방법 DSG-S(스무딩)·DSG-F(필터링)와 정적 baseline SGI·SGP. 큰 Google Books에서는 네 방법이 거의 겹치지만, 작은 State of the Union과 Twitter에서는 두 제안 방법이 정적 baseline을 뚜렷이 앞선다.*

순서는 일관되게 DSG-S > DSG-F > SGP ≈ SGI다. 필터링(DSG-F)의 우도는 초기 몇 시점에서 필터가 데이터를 더 볼수록 오르다가 이후 포화된다(저자 보고). 그리고 정적 baseline 대비 개선은 데이터가 적은 SoU와 Twitter에서 가장 크다. 시기마다 데이터가 적을수록 개별 시점 임베딩이 불안정해, 시간축을 가로지르는 정보 공유의 이득이 커지기 때문이다. 큰 Google Books에서는 네 방법의 차이가 작다. baseline 둘 사이(SGI와 SGP)의 차이도 작은데, 직전 시기 벡터로 초기화하면 연속성은 나아지지만 예측력에는 별 영향이 없다고 논문은 본다.

### 정성: 매끄러운 궤적

정성적으로는 제안 방법의 궤적이 사후 정렬 방식보다 매끄럽다. 시간에 따른 임베딩을 t-SNE로 그리면 DSG 방법의 궤적이 이어지는 반면 baseline은 튀고(Figure 3), 두 단어 사이 코사인 거리를 시간축으로 그리면 DSG 방법이 잡음을 덜 탄다(Figure 5). 논문은 이 잡음 감소가 시간 prior 덕분이라고 본다.

---

## 5. 주의해서 읽을 점

### 5.1 확산 상수 하나가 모든 단어의 변화 속도를 정한다 (논문 외 비판)

시간 동역학을 지배하는 확산 상수 $D$는 코퍼스마다 손으로 정하는 전역 스칼라 하나다(Google Books·SoU는 연 $10^{-3}$, Twitter는 연 $1$). 이 값에 대한 민감도 분석이나 절제 실험은 없다. 더 근본적으로, 확산 상수가 하나뿐이라 모든 단어가 같은 변화 시간 척도를 따른다. 단어마다 다른 시간 척도로 의미가 이동할 수 있고 최적 $D$가 관심 척도에 달렸다는 것은 논문 자신도 인정한 한계다. 리뷰어의 몫은 그 한계에 대한 민감도 분석이 없다는 점과, 급변하는 단어와 완만히 변하는 단어를 같은 prior로 묶어 단어별로 다른 변화 속도를 표현하지 못한다는 함의다.

### 5.2 매끄러움이 데이터가 아니라 prior의 산물일 수 있다 (논문 외 비판)

제안 방법의 강점으로 내세우는 매끄러운 궤적은 양날이다. 확산 prior가 인접 시점을 묶어 잡음을 줄이지만, 같은 힘이 진짜 급변을 지울 수 있다. 의미가 특정 시점에 급격히 도약한 단어라면, 가우시안 확산 prior는 그 도약을 완만한 곡선으로 뭉갠다. 더 미묘하게, 스무딩은 미래 정보를 과거로 흘려보낸다. 논문 자신이 "presidential"이 "clinton-trump"와 가까워지는 변화가 실제 시점보다 이르게 나타나는 예를 들며, 정보가 과거로 확산될 수 있음을 인정한다. 그렇다면 관찰된 매끄러움과 조기 변화를 데이터의 사실로 볼지 양방향 prior가 만든 인공물로 볼지 가리기 어렵고, 이는 잘못된 조기 경보로 읽힐 위험이 있다.

### 5.3 단일 지표와 선별된 궤적 (논문 외 비판)

정량 평가가 held-out 예측 로그우도 하나에 의존한다. 이 지표는 복원된 궤적이 실제 의미 변화를 타당하게 잰 것인지를 직접 확인하지 않는다. 의미 변화 정답 벤치마크가 없으니, 로그우도 우세는 동역학의 정확성이 아니라 공기 통계를 더 잘 평활한 결과일 수도 있다. 해석가능성 주장도 소수의 선별된 궤적에 기댄다. Figure 1은 코사인 거리가 가장 많이 변한 단어를 모델 자신의 코사인 지표로 골라 보이는 것이라 순환적이고, 체계적인 해석가능성 지표는 없다. 정량 결과도 수치 표가 아니라 그림으로만 제시돼, 상대 개선폭은 그림 판독 수준에 머문다.

---

## 6. 방법적 한계와 확장

### 6.1 논문이 남긴 것

이 논문의 기여는 시대별 임베딩을 사후 정렬 문제에서 공동 학습 문제로 옮긴 데 있다. 시기별로 따로 학습해 억지로 잇는 대신, 임베딩을 잠재 시계열로 두고 확산 prior로 이어 모든 시기가 통계적 강도를 나누게 했다. 필터링과 스무딩이라는 두 추론을 상태공간 모델 전통 위에 세우고, 삼중대각 정밀도행렬로 스무딩을 시퀀스 길이에 선형인 비용으로 계산한 것도 실용적 성과다. 사후 정렬 방식과의 격차가 가장 벌어지는 소규모 코퍼스에서 이 접근의 값이 특히 분명하다.

### 6.2 가우시안 확산이라는 가정 (논문 외 해석)

이 방법의 표현력과 한계는 모두 확산 prior에서 나온다. Ornstein-Uhlenbeck는 연속적이고 매끄러운 변화를 가정하는 가우시안 과정이다. 실제 의미 변화가 급격한 도약을 포함하거나 단어마다 속도가 다르면, 이 prior는 맞지 않는다. 단어별로 다른 확산 상수, 급변을 허용하는 두꺼운 꼬리 전이, 변화점을 명시적으로 모델링하는 확장이 열린 길이다. 모두 상태공간 골격을 그대로 두고 전이 prior만 바꾸는 방향이다.

### 6.3 재현성과 baseline (논문 외 비판)

최적화는 두 단계를 거친다. 미니배치로 사전 학습한 뒤 전체 배치로 전환하는데, 이는 black-box 변분추론 목적함수의 직접 최적화가 쉽지 않음을 시사한다. 시드나 초기화, 차원 선택에 따른 변동이 보고되지 않아 정량·정성 결과의 재현성이 불확실하다. baseline 쪽에도 물음이 있다. SGI는 독립 학습 후 직교 정렬이라 재정렬 잡음이 큰 기준선이다. 제안 방법의 우세 일부는 이 약한 baseline이 만든 여유일 수 있다. Google Books의 알려진 코퍼스 인공물(장서 구성 변화, OCR 오류, 과학 문헌 급증)도 다뤄지지 않아, 검출된 드리프트의 일부가 언어 변화가 아니라 코퍼스 변화일 수 있다.

---

## 7. 결론

Bamler & Mandt의 이 논문은 시대별 임베딩을 하나의 확률 모델로 묶는다. 베이지안 skip-gram의 임베딩을 잠재 시계열로 두고 확산 prior로 이어, 시기별 개별 학습의 세 문제를 공동 학습으로 우회했다. 필터링과 스무딩이라는 두 추론, 그리고 삼중대각 구조로 얻은 선형 비용의 스무딩이 그 골격이다. held-out 예측에서 스무딩이 필터링을 이기고 둘 다 정적 방식을 이기며, 그 이득은 데이터가 적을수록 커진다.

동시에 그 강점은 확산 prior라는 가정 위에 서 있다. 전역 상수 하나가 모든 단어의 변화 속도를 정하고, 가우시안 확산은 급변을 뭉개며, 스무딩은 정보를 과거로 흘린다. 매끄러운 궤적이 데이터의 사실인지 prior의 산물인지는 단일 지표와 선별된 예시만으로는 가리기 어렵다. 방법을 이해하려는 독자에게 이 논문은 "시대별 임베딩을 어떻게 한 모델로 묶는가"는 명료한 상태공간 설계로, "그 매끄러움을 얼마나 믿을 수 있는가"는 열어 둔 물음으로 남긴다.

---

## References

- Bamler, R., & Mandt, S. (2017). Dynamic word embeddings. In *Proceedings of the 34th International Conference on Machine Learning (ICML 2017)* (pp. 380–389). PMLR. ([PDF 보기](/paper-viewer?title=Dynamic+Word+Embeddings&source=blog-reference&authors=Robert+Bamler%3BStephan+Mandt&year=2017&arxiv_id=1702.08359&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1702.08359.pdf))
- Barkan, O. (2017). Bayesian neural word embedding. In *Proceedings of the Thirty-First AAAI Conference on Artificial Intelligence* (pp. 3135–3143).
- Blei, D. M., & Lafferty, J. D. (2006). Dynamic topic models. In *Proceedings of the 23rd International Conference on Machine Learning* (pp. 113–120).
- Hamilton, W. L., Leskovec, J., & Jurafsky, D. (2016). Diachronic word embeddings reveal statistical laws of semantic change. In *Proceedings of the 54th Annual Meeting of the Association for Computational Linguistics (Vol. 1: Long Papers)* (pp. 1489–1501). ([PDF 보기](/paper-viewer?title=Diachronic+Word+Embeddings+Reveal+Statistical+Laws+of+Semantic+Change&source=blog-reference&authors=William+L.+Hamilton%3BJure+Leskovec%3BDan+Jurafsky&year=2016&doi=10.18653%2Fv1%2FP16-1141&url=https%3A%2F%2Fdoi.org%2F10.18653%2Fv1%2FP16-1141))
- Kalman, R. E. (1960). A new approach to linear filtering and prediction problems. *Journal of Basic Engineering, 82*(1), 35–45.
- Kim, Y., Chiu, Y.-I., Hanaki, K., Hegde, D., & Petrov, S. (2014). Temporal analysis of language through neural language models. In *Proceedings of the ACL 2014 Workshop on Language Technologies and Computational Social Science* (pp. 61–65). ([PDF 보기](/paper-viewer?title=Temporal+analysis+of+language+through+neural+language+models&source=blog-reference&authors=Yoon+Kim%3BYi-I+Chiu%3BKentaro+Hanaki%3BDarshan+Hegde%3BSlav+Petrov&year=2014&arxiv_id=1405.3515&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1405.3515.pdf))
- Mikolov, T., Sutskever, I., Chen, K., Corrado, G. S., & Dean, J. (2013). Distributed representations of words and phrases and their compositionality. In *Advances in Neural Information Processing Systems 26 (NIPS 2013)* (pp. 3111–3119). ([PDF 보기](/paper-viewer?title=Distributed+representations+of+words+and+phrases+and+their+compositionality&source=blog-reference&authors=Tomas+Mikolov%3BIlya+Sutskever%3BKai+Chen%3BGreg+Corrado%3BJeffrey+Dean&year=2013&arxiv_id=1310.4546&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1310.4546.pdf))
- Ranganath, R., Gerrish, S., & Blei, D. (2014). Black box variational inference. In *Proceedings of the 17th International Conference on Artificial Intelligence and Statistics (AISTATS)* (pp. 814–822). ([PDF 보기](/paper-viewer?title=Black+box+variational+inference&source=blog-reference&authors=Rajesh+Ranganath%3BSean+Gerrish%3BDavid+Blei&year=2014&arxiv_id=1401.0118&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1401.0118.pdf))
- Rezende, D. J., Mohamed, S., & Wierstra, D. (2014). Stochastic backpropagation and approximate inference in deep generative models. In *Proceedings of the 31st International Conference on Machine Learning (ICML 2014)* (pp. 1278–1286). ([PDF 보기](/paper-viewer?title=Stochastic+backpropagation+and+approximate+inference+in+deep+generative+models&source=blog-reference&authors=Danilo+Jimenez+Rezende%3BShakir+Mohamed%3BDaan+Wierstra&year=2014&arxiv_id=1401.4082&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1401.4082.pdf))
- Rudolph, M., & Blei, D. (2018). Dynamic embeddings for language evolution. In *Proceedings of the 2018 World Wide Web Conference (WWW 2018)* (pp. 1003–1011). ([PDF 보기](/paper-viewer?title=Dynamic+Embeddings+for+Language+Evolution&source=blog-reference&authors=Maja+Rudolph%3BDavid+M.+Blei&year=2018&doi=10.1145%2F3178876.3185999&arxiv_id=1703.08052&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1703.08052.pdf&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3178876.3185999))
- Uhlenbeck, G. E., & Ornstein, L. S. (1930). On the theory of the Brownian motion. *Physical Review, 36*(5), 823–841.
