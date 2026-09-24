# Dynamic Bernoulli Embeddings 심층 분석: "Dynamic Embeddings for Language Evolution" 논문 해설

**Paper:** Rudolph, Maja; Blei, David. (2018). "Dynamic Embeddings for Language Evolution." *Proceedings of the 2018 World Wide Web Conference (WWW '18)*, pp. 1003–1011. https://doi.org/10.1145/3178876.3185999. arXiv:1703.08052 (arXiv 판 제목: "Dynamic Bernoulli Embeddings for Language Evolution"). Code: github.com/mariru/dynamic_bernoulli_embeddings

**Abstract:** 본 문서는 단어 임베딩에 시간 축을 넣은 초기 확률 모델인 dynamic Bernoulli embeddings 논문을 해설한다. 출발점은 단어 임베딩의 정적 가정이다: 한 단어의 벡터가 코퍼스 전체에서 하나로 고정되면, intelligence가 정부 첩보의 용어에서 인공지능의 용어로(ACM 초록), 심리적 능력에서 정보기관의 용어로(상원 연설) 옮겨 가는 식의 의미 변화를 볼 수 없다. 이 논문은 exponential family embeddings의 Bernoulli 임베딩에서 임베딩 벡터만 시간 슬라이스별 잠재변수 \(\rho_v^{(t)}\)로 풀고, 그 위에 Gaussian random walk 사전분포를 걸어 인접 시점의 벡터가 매끄럽게 이어지게 만든다. 시대별로 임베딩을 따로 학습하던 기존 접근의 두 난점(슬라이스마다 충분한 데이터가 필요하고, 독립 학습된 공간들을 사후 정렬해야 한다는 것)이 모델 구조 안에서 함께 풀린다는 것이 핵심 주장이다. 미 상원 연설 151년, ACM 초록 64년, arXiv 머신러닝 논문 9년 코퍼스에서 held-out 예측력으로 정적·시대별 임베딩을 이겼고, iraq·values·computer 같은 단어의 의미 궤적을 보였다. 다만 평가는 자기 계열 지표(held-out pseudo-likelihood)에 갇혀 있어 의미 변화 탐지 자체는 검증되지 않았고, 데이터가 없는 시기의 궤적은 사전분포가 만든 보간이다. 이 두 가지를 함께 읽어야 한다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 단어 임베딩으로 언어의 시간적 변화를 측정하려 할 때, 시대별 독립 학습이 요구하는 "슬라이스마다 충분한 데이터"와 "사후 정렬" 없이 임베딩의 시계열을 얻을 수 있는가? |
| 핵심 기여 | Bernoulli 임베딩(exponential family embeddings)의 임베딩 벡터를 시간 슬라이스별 잠재변수로 풀고 Gaussian random walk 사전분포로 묶은 dynamic embeddings. 문맥 벡터는 전 기간 공유되어 시점 간 좌표가 처음부터 연결된다. |
| 방법적 결과 | \(\rho_v^{(t)} \sim \mathcal{N}(\rho_v^{(t-1)}, \lambda^{-1}I)\)(Eq. 5)를 사전분포로 하는 pseudo MAP 목적함수(Eq. 6)를 negative sampling(Eq. 7)과 확률적 경사법으로 최적화한다. |
| 실험 결과 | 세 코퍼스 × 문맥 크기 2종의 6개 조건 전부에서 held-out \(\mathcal{L}_{pos}\) 최고(Table 2). 이득은 작은 코퍼스·작은 문맥(Arxiv ML, cs 2: 정적 대비 +0.171)에서 크고 큰 코퍼스·큰 문맥(ACM, cs 8: +0.003)에서 근소하다. |
| 핵심 한계 | 평가가 held-out likelihood 하나뿐이라 "의미 변화를 올바르게 잡는가"는 검증되지 않았다. 문맥 벡터는 시간 불변으로 고정(future work)이고, 결과는 점추정이라 불확실성이 없다. 희소 시기의 궤적 해석에는 별도의 주의가 필요하다(6.3절). |

## 목차

1. 서론
2. 예비 지식
3. 동적 임베딩: 모델과 추론
4. 실험 설정
5. 실험 결과
6. 주의해서 읽을 점
7. 방법적 한계와 확장
8. 결론

---

## 1. 서론

### 1.1 연구 배경

이 시리즈에서 지금까지 다룬 임베딩들(DeepWalk·node2vec의 그래프 임베딩, word2vec 계열의 단어 임베딩)은 모두 정적이다. 한 단어의 벡터는 코퍼스 전체에서 하나다. 그런데 언어는 움직인다. 논문의 첫 예시가 intelligence다: ACM 초록에서 이 단어는 정부·첩보 맥락에서 인지과학을 거쳐 인공지능의 용어가 되고, 미 상원 연설에서는 심리적 능력에서 정보기관(CIA·FBI)의 언어가 된다(§1, Figure 1). 정적 임베딩은 이 궤적을 정의상 볼 수 없다.

논문의 발판은 word2vec 자체가 아니라 **exponential family embeddings**(EFE; Rudolph et al., 2016)다. EFE는 임베딩 학습을 확률 모델(조건부 분포, 파라미터 공유, 사전분포)로 다시 쓴 틀이고, 이 논문은 그 확률적 관점 덕분에 동적 확장이 자연스러워진다고 명시한다(§2). 사전분포 자리에 시간 구조를 꽂으면 되기 때문이다.

![DBE Figure 1: trajectory of intelligence](/api/blog/figures/dbe-fig1-intelligence.png)

*그림 1 — 원논문 Figure 1: intelligence의 동적 임베딩 궤적. (a) ACM 초록(1951–2014)에서는 정부 첩보 → 인지 → 인공지능으로, (b) 상원 연설(1858–2009)에서는 심리적 능력 → 정보기관으로 이동한다. y축 "meaning"은 임베딩의 1차원 사영이다.*

### 1.2 핵심 질문

시간에 따른 임베딩을 얻는 소박한 방법은 이미 있었다: 코퍼스를 시간 슬라이스로 나누고 슬라이스마다 임베딩을 따로 학습하는 것이다(Kim et al., 2014; Kulkarni et al., 2015; Hamilton et al., 2016). 논문은 이 계열의 난점을 정확히 두 개 짚는다(§1 Related work).

- **슬라이스별 데이터 요구량.** 슬라이스마다 "고품질 임베딩을 학습할 만큼의 데이터"가 있어야 한다. 시간 해상도를 높일수록 슬라이스는 얇아진다.
- **좌표 비정렬.** 독립 학습된 임베딩 공간들은 차원이 서로 비교되지 않아서, 이전 시기 벡터로 초기화하거나(Kim et al., 2014) 사후 정렬 기법으로(Kulkarni et al., 2015; Hamilton et al., 2016) 이어 붙여야 한다.

이 논문의 답은 임베딩 벡터를 **순차적 잠재변수**로 두는 것이다. 그러면 "희소한 슬라이스를 자연스럽게 수용하고, 잠재 차원이 시간축에서 처음부터 연결된다"(§1). 두 난점이 각각 사전분포의 정보 공유와 문맥 벡터 공유로 해소된다. 이것이 3장의 뼈대다.

### 1.3 학술적 위치

§1의 관련연구 지형은 세 갈래다: 자질 기반 의미 변화 탐지, LSA·시간적 의미 색인, 그리고 "가장 가깝다"고 명시한 시대별 임베딩 계열(Kim/Kulkarni/Hamilton). 여기에 논문이 잇는 또 하나의 전통이 **동적 토픽 모델**이다(Blei & Lafferty, 2006 등). 일부 동적 토픽 모델이 자신과 같은 부품(Gaussian random walk)으로 언어 모델의 드리프트를 잡는다고 §1이 짚고, "동적 토픽 모델과 동적 임베딩의 결합은 future study"로 남긴다. 공저자 Blei가 동적 토픽 모델(2006)과 EFE(2016)의 저자이기도 하다는 점에서, 이 논문은 상태공간 모델링(잠재 상태의 시계열로 관측을 설명하는 모델군) 전통을 토픽에서 임베딩으로 옮긴 것으로 읽을 수 있다(논문 외 해석).

각주 1은 동시 독립 연구 두 편을 명시한다: Bamler & Mandt(ICML 2017 출판)는 임베딩·문맥 벡터 양쪽을 Ornstein–Uhlenbeck 과정(평균으로 되돌아가는 성질이 있는 확률과정; 원문 표기는 Uhlenbeck-Ornstein)으로 모델링했고, Yao et al.(WSDM 2018 출판)은 시점별 PMI(두 단어의 공출현이 우연 대비 얼마나 잦은지의 로그비) 행렬을 공동 분해한다. 즉 "시간을 사후 정렬이 아니라 모델 구조로 해결한다"는 아이디어가 2017년 전후 최소 세 그룹에서 동시에 나왔고, 이 세 편이 이후 문헌에서 한 묶음으로 인용된다(논문 외 지식).

## 2. 예비 지식

### 2.1 Bernoulli 임베딩 (원논문 §2 전반부)

EFE의 텍스트 버전이다. 코퍼스의 각 위치 \(i\)의 단어를 어휘 크기 \(V\)의 지시벡터 \(x_i \in \{0,1\}^V\)로 보고, 성분별 조건부 분포를 둔다:

\[ x_{iv} \mid \mathbf{x}_{c_i} \sim \mathrm{Bern}(p_{iv}) \quad \text{(Eq. 1)} \]

\(c_i\)는 위치 \(i\)의 문맥(앞뒤 단어들, 통상 2–10개)이다. Bernoulli 확률의 로그 오즈(자연 파라미터)가 임베딩이 들어가는 자리다:

\[ \eta_{iv} = \rho_v^\top \Big( \sum_{j \in c_i} \sum_{v'} \alpha_{v'} x_{jv'} \Big) \quad \text{(Eq. 2)} \]

단어 \(v\)마다 **임베딩 벡터** \(\rho_v \in \mathbb{R}^K\)와 **문맥 벡터** \(\alpha_v \in \mathbb{R}^K\)가 있고, \(\eta_{iv}\)는 \(\rho_v\)와 주변 단어 문맥 벡터 합의 내적이다. one-hot 제약을 성분별 Bernoulli로 완화한 덕에 softmax 정규화가 필요 없고, 정규화(사전분포) 없이 적합하면 CBOW(Mikolov, Chen, et al., 2013)·negative sampling(Mikolov, Sutskever, et al., 2013)과 밀접하게 관련된다고 논문이 명시한다(§2).

### 2.2 파라미터 공유와 사전분포

EFE의 세 번째 재료가 파라미터 공유 구조다: \(\rho_v\)·\(\alpha_v\)의 인덱스는 위치 \(i\)가 아니라 어휘 항목 \(v\)다. intelligence의 벡터는 코퍼스 어디에 나타나든 같다. 동적 임베딩은 "이 제약을 부분적으로 완화한다"(§2) — 어디를 완화하고 어디를 유지하는지가 3장의 설계 그 자체다. EFE는 또한 임베딩에 Gaussian 사전분포(ℓ₂ 정규화)를 두는데, 이 사전분포 자리가 시간 구조가 들어올 입구다.

### 2.3 Gaussian random walk

시점 \(t\)의 상태가 직전 상태를 평균으로 하는 Gaussian에서 나오는 확률과정이다: \(z^{(t)} \sim \mathcal{N}(z^{(t-1)}, \sigma^2 I)\). 연속한 상태가 크게 벌어지면 확률이 급감하므로, 잠재변수의 시계열을 매끄럽게 묶는 표준 장치다. 동적 토픽 모델이 토픽-단어 분포의 드리프트에 쓴 것과 같은 부품이다(§1).

## 3. 동적 임베딩: 모델과 추론

원논문 §2의 후반부에 해당한다.

### 무엇이 움직이고 무엇이 공유되는가

각 관측에 시간 슬라이스 \(t_i\)(예: 연도)를 붙이고, 파라미터를 둘로 가른다.

- **임베딩 벡터 \(\rho_v^{(t)}\):** 슬라이스 안에서만 공유. 단어마다 벡터의 시퀀스가 생긴다.
- **문맥 벡터 \(\alpha_v\):** 전 기간 공유("The context vectors are shared across all time slices", Figure 2 캡션).

자연 파라미터는 Eq. 2에서 \(\rho_v\)를 \(\rho_v^{(t_i)}\)로 바꾼 것이다(Eq. 3). 문맥 벡터까지 움직이지 않는 이유는 각주 3에 있다: \(\alpha\)와 \(\rho\)는 내적으로만 등장하므로 양쪽에 동역학을 두는 것은 "다소 중복"이고, \(\alpha\)의 동역학은 future study로 남긴다. 이 공유가 좌표 비정렬 문제를 원천에서 없앤다 — 모든 시점의 \(\rho_v^{(t)}\)가 같은 문맥 벡터 기저에 대해 정의되므로, 시점 간 비교에 사후 정렬이 필요 없다.

![DBE Figure 2: graphical model](/api/blog/figures/dbe-fig2-graphical-model.png)

*그림 2 — 원논문 Figure 2: T개 시간 슬라이스 \(X^{(1)}, \dots, X^{(T)}\)의 그래피컬 모델. 임베딩 벡터 \(\rho_v\)는 시간에 따라 진화하고(위쪽 사슬), 문맥 벡터 \(\alpha_v\)는 모든 슬라이스가 공유한다(아래).*

### 사전분포: random walk로 시간을 묶는다

\[ \alpha_v,\ \rho_v^{(0)} \sim \mathcal{N}(0, \lambda_0^{-1} I) \quad \text{(Eq. 4)} \]
\[ \rho_v^{(t)} \sim \mathcal{N}(\rho_v^{(t-1)}, \lambda^{-1} I) \quad \text{(Eq. 5)} \]

정밀도 \(\lambda\)가 허용하는 보폭 안에서 임베딩이 시점마다 조금씩 움직인다. 논문의 표현으로 이 사전분포는 "연속한 단어 벡터가 너무 멀리 드리프트하는 것을 벌점화"하고, 데이터가 주어지면 "매끄럽게 변하는 추정치"로 이어진다(§2). 슬라이스가 얇은 문제도 여기서 풀린다: 어떤 시기에 단어가 거의 안 나와도, 이웃 시점의 추정이 사전분포를 타고 흘러들어 온다. 극단적으로 데이터가 전혀 없는 시기의 임베딩은 앞뒤 시점 임베딩의 평균이 된다(Appendix C — 이 성질의 양면은 6.3절에서 본다).

### 추론: pseudo MAP과 negative sampling

성분별 조건부로 명세한 모델이라 결합분포 계산은 불가능하다(이진 데이터라 결합의 존재 자체는 보장된다, §2). 그래서 조건부 로그우도의 합인 **pseudo log-likelihood**를 로그 사전분포로 정규화해 최대화한다 — pseudo MAP 점추정이다:

\[ \mathcal{L}(\rho, \alpha) = \mathcal{L}_{pos} + \mathcal{L}_{neg} + \mathcal{L}_{prior} \quad \text{(Eq. 6)} \]

\(\mathcal{L}_{pos}\)는 관측된 단어(1인 성분), \(\mathcal{L}_{neg}\)는 나머지 전부(0인 성분)의 기여이고, \(\mathcal{L}_{prior}\)에 random walk 벌점 \(-(\lambda/2)\sum_{v,t}\|\rho_v^{(t)}-\rho_v^{(t-1)}\|^2\)이 들어 있다. 가장 비싼 \(\mathcal{L}_{neg}\)는 negative sampling으로 근사한다(Eq. 7; unigram 분포의 0.75제곱에서 표집). 논문은 이 근사가 "어떤 의미에서 편향을 초래한다 — negative sample에 대한 기대값이 원래 목적함수와 같지 않다"고 인정하되, '0의 가중치 낮추기'가 예측 정확도에는 도움이 될 수 있다는 문헌으로 방어한다(§2).

구현은 Edward(TensorFlow 기반 자동미분) 위에서 확률적 경사법으로 했고, 실험에서는 Adagrad를 썼다(§2, Appendix B). Algorithm 1의 세부 중 눈에 띄는 것 둘: 미니배치는 **모든 슬라이스에서 연속한 단어 구간을 슬라이스 크기에 비례해 함께** 뽑고(한 스텝이 전 시대를 건드린다), 파라미터는 표준편차 0.01의 Gaussian으로 초기화한다.

### 분석 도구: 이웃과 드리프트

정성 분석에 쓰는 도구는 둘이다. **임베딩 이웃**(Eq. 8)은 시점 \(t\)에서 쿼리 단어와 가까운 상위 10개 단어다(분자에 \(\mathrm{sign}(\rho_v^{(t)})\)가 들어간 코사인 유사도의 변형). **절대 드리프트**(Eq. 9)는 \(\mathrm{drift}(v) = \|\rho_v^{(T)} - \rho_v^{(0)}\|\), 즉 마지막과 첫 슬라이스 벡터의 거리로, 가장 많이 움직인 단어를 고르는 기준이다.

## 4. 실험 설정

원논문 §3.1–3.2와 Appendix A에 해당한다.

### 데이터셋 (Table 1)

| 코퍼스 | 기간 | 슬라이스 | 폭 | 어휘 | 규모 |
|---|---|---|---|---|---|
| Arxiv ML (stat.ML 전문) | 2007–2015 | 9 | 1년 | 50k | 6.5M 단어 |
| ACM 초록 | 1951–2014 | 64 | 1년 | 25k | 21.6M 단어 |
| 미 상원 연설 | 1858–2009 | 76 | 2년 | 25k | 13.7M 단어 |

두 문어 코퍼스는 시기별 데이터량이 크게 비대칭이다: Arxiv ML은 2007년 101편에서 2014년 1,573편으로, ACM은 1953년 초록 약 10개(합계 471단어)에서 2009년 2M 단어 이상으로 늘어난다(§3.1). 상원 연설은 유일한 구어 전사본이다. 전처리는 최빈 25,000 단어로 어휘를 고정하고 어휘 밖 단어를 제거한 뒤, word2vec식 고빈도 서브샘플링을 적용한다(Appendix A). 분할은 슬라이스 안에서 80/10/10(훈련/검증/테스트)이다(§3.1). 한 가지 주의: Appendix A의 "25,000 최빈 단어"와 Table 1의 Arxiv ML 어휘 50k가 서로 맞지 않는데 원논문은 이를 조정하지 않는다. 재현하려면 직접 확인해야 한다.

### 비교 대상과 하이퍼파라미터 (원논문 §3.2)

baseline은 둘이다. **s-emb**: 전 기간을 하나로 학습한 정적 Bernoulli 임베딩(Rudolph et al., 2016; negative sampling CBOW와 유사하다고 논문이 명시). **t-emb**: 슬라이스마다 독립 학습하는 시대별 임베딩(Hamilton et al., 2016 방식). 단, 원 논문의 SGNS+Procrustes 파이프라인이 아니라 저자들의 Bernoulli 프레임워크 안의 재구현이다(6.2절에서 재론).

공통 설정: 차원 K=100, negative sample 20, 문맥 크기 2와 8, 최대 10 pass. s-emb는 무작위 초기화, **d-emb와 t-emb는 1 pass 학습한 s-emb로 초기화한 뒤 9 pass 추가 학습**한다. 학습률(η ∈ {0.01, 0.1, 1, 10})과 미니배치 크기(m ∈ {0.001N, 0.0001N, 0.00001N})는 검증오차로 고르고, d-emb 고유 하이퍼파라미터인 random walk 정밀도는 λ ∈ {1, 10}에서 검증 선택, 나머지 정밀도는 λ₀ = λ/1000으로 고정한다("튜닝할 하이퍼파라미터를 하나 줄이기 위해", §3.2).

### 평가 지표

held-out 위치에 모델이 부여하는 Bernoulli 조건부 로그우도 중 **관측 단어 항만 모은 \(\mathcal{L}_{pos}\)**를 보고한다. 세 방법 모두 Eq. 1 형태의 조건부 우도를 내놓으므로 직접 비교가 가능하다는 것이 선택 이유다(§3.2). held-out은 연속 단어 청크 단위라 문맥 단어가 함께 빠지는데, 평가 시에는 모든 방법이 문맥 단어를 사용한다(각주 5).

## 5. 실험 결과

### 5.1 정량: held-out \(\mathcal{L}_{pos}\) (Table 2)

원문 수치 그대로(높을수록 좋음):

| 코퍼스 | 문맥 | s-emb | t-emb | d-emb |
|---|---|---|---|---|
| Arxiv ML | 2 | −2.706 ± 0.002 | −2.646 ± 0.002 | **−2.535 ± 0.001** |
| Arxiv ML | 8 | −2.491 ± 0.002 | −2.454 ± 0.002 | **−2.400 ± 0.002** |
| Senate | 2 | −2.366 ± 0.001 | −2.295 ± 0.001 | **−2.263 ± 0.001** |
| Senate | 8 | −2.244 ± 0.001 | −2.212 ± 0.001 | **−2.204 ± 0.001** |
| ACM | 2 | −2.427 ± 0.001 | −2.420 ± 0.001 | **−2.396 ± 0.001** |
| ACM | 8 | −2.231 ± 0.001 | −2.242 ± 0.001 | **−2.228 ± 0.001** |

d-emb가 6개 조건 전부에서 최고다("consistently achieve highest held-out \(\mathcal{L}_{pos}\)", Table 2 캡션). 격차의 결은 고르지 않다(아래 마진은 표 원값의 뺄셈으로, 논문에 없는 계산이다). 가장 크게 이기는 곳은 Arxiv ML의 문맥 2(정적 대비 +0.171, 시대별 대비 +0.111)이고, 가장 근소한 곳은 ACM의 문맥 8(정적 대비 +0.003)이다. 작은 코퍼스·작은 문맥일수록 이득이 크다는 패턴은 "사전분포의 정보 공유가 희소한 조건에서 힘을 쓴다"는 §1의 논지와 방향이 맞다. 부수 관찰 하나: ACM 문맥 8에서는 t-emb(−2.242)가 s-emb(−2.231)보다 나쁘다. 시간 분할 자체가 항상 이득은 아니고 시점 간 정보 공유가 필요하다는 논지의 정량적 각주다.

### 5.2 정성: 단어의 궤적 (원논문 §3.3, §4)

논문의 실질적인 매력은 이쪽이다. 도구는 3장의 이웃(Eq. 8)과 드리프트(Eq. 9)다.

- **computer (상원):** 1858년 이웃은 draftsman·copyist·bookkeeper(계산을 직업으로 하는 사람)이고, 1986년에는 software·hardware(전자기기)다. 두 의미가 상호 배타적으로 교체된 사례(Table 3).
- **bush (상원):** 1858년 barberry·bushes(식물) → 1990년 cheney·nixon·reagan(정치인). 두 의미가 공존하며 시기별로 어느 쪽이 지배적인지가 드러나는 사례(Table 3).
- **드리프트 상위(상원, Table 4):** iraq가 3.09로 1위. tax cuts 2.84, health care 2.62, energy 2.55, medicare 2.55가 뒤따른다. 상위 5개는 정치 어휘지만, 16위 안에는 text·coin·signal 같은 비정치 어휘도 섞여 있다.
- **iraq (상원, Figure 3·Table 7):** 이웃이 국가·지역명 → 아랍 국가들 → 1980년(이란-이라크 전쟁기) aggressors·troops·invasion → 2008년 terror·terrorism·saddam으로 이동한다. 단어의 정의는 그대로인데 관련 주제가 변한 사례다.
- **values (상원, Table 5):** 1858년 fluctuations·currencies(화폐 가치) → 2000년 sacred·principles(도덕적 가치). 같은 표의 discipline(군기·징벌 → 재정 규율)과 fine(고운/훌륭한 → 벌금)도 같은 유형이고, unemployment는 곤궁의 언어(destitution·deplorable)에서 경제 지표의 언어(jobless·rate·forecasts)로 옮겨 간다.
- **data (ACM, Table 3):** 1961년 directories·files·retrieval에서 이후 raw data·data streams·warehouses·data mining으로. 정성 분석이 상원 코퍼스 전용이 아님을 보여주는 ACM 쪽 사례다.
- **jobs (상원, Table 6):** unemployment 분석의 보완 용례다. 관심 단어의 관련어 이웃으로 조사를 넓히는 "텍스트 연구 도구" 용법을 논문이 직접 시연한다(2008년 이웃에 create·opportunities가 들어온다).
- **prostitution (상원, Table 6):** immoral·vile → indecent → servitude·harassment·trafficking. 논문이 희소성을 강조하는 사례다. 슬라이스당 평균 1회 사용되고 슬라이스의 2/3에서 아예 등장하지 않는데도 궤적이 학습된다(§3.3).

§4는 이 사례들을 세 유형으로 분류한다: 의미 자체의 교체(computer), 지배적 의미의 변화(values), 정의는 불변이되 관련 주제의 변화(iraq). 논문 스스로 이 분석의 위상을 낮춰 잡는다는 점도 기록해 둔다: "dynamic embeddings가 언어 변화를 이해하는 **시사적(suggestive) 도구**가 되기를 바란다"(§3.3).

![DBE Figure 3: trajectory of iraq](/api/blog/figures/dbe-fig3-iraq.png)

*그림 3 — 원논문 Figure 3: iraq의 궤적(y축은 PCA(주성분분석) 1차원 사영)과 시점별 이웃. 캡션의 연도(1954)와 원논문 본문(1950)이 어긋나는 것은 원문 자체의 불일치다.*

## 6. 주의해서 읽을 점

### 6.1 "consistently"의 실제 강도

6개 조건 전승은 사실이다. 그러나 Table 2의 ± 값이 무엇인지(반복 표준편차인지 표준오차인지, 반복 횟수는 몇인지) 본문·캡션 어디에도 정의가 없고, 유의성 검정도 없다. ACM 문맥 8의 +0.003(± 0.001의 3배)까지 "consistently"에 포함하는 것은 격차의 이질성을 뭉개는 서술이다. Abstract의 "better fits than classical embeddings"는 허위는 아니지만, 이득이 조건에 따라 두 자릿수 배율로 출렁인다는 것은 표를 직접 봐야 보인다.

### 6.2 평가의 범위: 예측력 ≠ 의미 변화 탐지

논문의 핵심 주장은 "언어 변화를 포착한다"인데, 정량 평가는 held-out 예측력 하나다. 시간 가변 파라미터를 두면 다음 단어를 더 잘 맞힌다는 것과, 그 파라미터의 변화가 의미 변화를 올바르게 반영한다는 것은 별개의 명제다. 후자를 검증할 정답 벤치마크·인간 평가·합성 변화 실험은 없다. 지표 자체도 학습 목적함수의 한 항(\(\mathcal{L}_{pos}\))이라 자기 계열 평가에 가깝고, 비교 대상인 t-emb 역시 같은 Bernoulli 프레임워크 안의 재구현이므로(4장), 비교 전체가 저자 프레임워크 내부에서 이루어진다. 또한 d-emb는 정적 모델보다 임베딩 파라미터가 슬라이스 수만큼(상원이면 76배; Table 1에서 유도한 논문 외 계산) 많은데, held-out likelihood는 이를 자동으로 벌점하지 않는다.

### 6.3 사전분포 보간의 양면

희소 슬라이스 수용은 이 모델이 내세우는 강점이자 함정이다. Appendix C가 스스로 보여준다: iraq는 76개 슬라이스 중 64개에서 아예 등장하지 않고(슬라이스당 평균 10.6회), 등장하지 않는 시기의 임베딩은 앞뒤 시점의 평균으로 채워진다. 그 결과 Table 7의 1858년 iraq 이웃(poland·syria·yugoslavia 등)은 데이터가 만든 추정이 아니라 사전분포가 역방향으로 흘려보낸 보간이다. 국가 이라크는 20세기에 성립했으므로(논문 외 상식) 1858년의 "의미"는 후대 데이터의 인공물이다. 그런데 드리프트(Eq. 9)는 정확히 \(\rho^{(0)}\)(1858)과 \(\rho^{(T)}\)의 거리이고, iraq가 그 1위다. 즉 논문의 대표 사례 자체가 보간에 크게 의존한다. 표면상 데이터 기반 추정과 보간이 구별되지 않는다는 것이 동적 임베딩의 산출물을 읽을 때 가장 조심해야 할 성질이다. 덧붙여, 임베딩이 두 슬라이스 사이에 변하지 않아도 이웃 목록은 변할 수 있다. Eq. 8이 어휘의 다른 단어들 임베딩에도 의존하기 때문이다(Appendix C).

### 6.4 재현 관점의 공백

코드는 공개되어 있지만(각주 4), 최종 선택된 학습률·미니배치·λ 값은 코퍼스별로 보고되지 않고(탐색 범위만 제시), \(\mathcal{L}_{pos}\)의 정규화 단위(합인지 위치당 평균인지)도 명시가 없다. 어휘 크기의 내부 불일치(4장), 원논문 본문(§1·Table 1)과 §4 Summary의 연도 셈 차이(9년/64년 vs 8년/63년) 같은 자잘한 어긋남도 있다. 정성 결과(Tables 3–7)는 단일 적합에서 뽑은 것으로, 시드에 따른 이웃의 안정성은 다루지 않는다.

## 7. 방법적 한계와 확장

### 7.1 논문이 남긴 것

한계를 모아 둔 절은 없다(§4 Summary는 요약 세 문단이 전부다). 본문에 흩어진 자기 인정은 셋이다.

| 논문이 인정한 사실 | 위치 |
|---|---|
| 문맥 벡터 α의 동역학은 두지 않았다 — "내적으로만 등장하므로 다소 중복"; future study | §2 각주 3 |
| negative sampling 근사는 원 목적함수의 불편추정이 아니다(편향 인정) | §2 |
| 동적 토픽 모델과의 결합은 future study | §1 |

### 7.2 방법 내재적 한계 (논문 외 비판)

- **α 고정의 비대칭.** 의미 변화가 임베딩 벡터 쪽으로만 기록되고, 단어가 문맥으로 쓰일 때의 역할 변화는 주변 단어들의 ρ 변화로 흡수된다. 고정된 α는 전 기간 데이터로 학습되므로, 데이터가 압도적인 후반 시기의 통계가 좌표계를 지배할 수 있다. 초기 시기의 임베딩이 "후반기 기준의 좌표"에서 추정되는 셈이다. 동시대의 Bamler & Mandt (2017)는 양쪽 모두에 동역학을 두었으니, 이 선택의 영향은 검증 가능한 질문이었지만 이 논문에는 없다.
- **평활화가 급변을 문지른다.** 단일 전역 정밀도 λ가 모든 단어에 같은 "기대 변화 속도"를 부과하고, Gaussian 증분은 큰 도약에 이차 벌점을 매긴다. 전쟁·기술 도입 같은 급격한 의미 단절은 여러 슬라이스에 걸친 점진 변화로 늘어져 기록될 수 있다. 변화 시점 추정이 체계적으로 흐려진다는 뜻으로, 변화점 탐지를 명시적으로 다룬 Kulkarni et al. (2015)과 대비된다.
- **어휘가 고정된다.** 전 기간 빈도 상위 25k로 어휘를 한 번 고정하므로, 신조어도 초기 슬라이스에 사전분포로 채워진 벡터를 갖고 사어도 끝까지 벡터를 유지한다. 어휘의 진입·퇴출 자체가 언어 진화의 큰 축인데, 이 모델은 정의상 "이미 어휘에 있는 단어의 용법 변화"만 본다.
- **점추정이라 불확실성이 없다.** 확률 모델 프레이밍에도 불구하고 산출물은 pseudo MAP 점추정이다. 드리프트 순위나 이웃 목록에 신뢰구간이 없어 "이 변화가 노이즈 이상인가"에 답할 수 없다. λ 후보가 {1, 10} 두 값뿐이고 λ₀ = λ/1000이라는 배수에도 근거가 없다. λ는 궤적의 모양(정성 결과)을 직접 좌우하는 하이퍼파라미터라서 더 아쉬운 공백이다.

### 7.3 평가 관행은 그 후 어떻게 바뀌었나 (논문 외 지식)

이 논문의 평가 공백은 개별 논문의 태만이라기보다 당시 분야 전체의 상태였다: 통시적 의미 변화에는 합의된 정답이 없었고, 다들 held-out 예측력과 일화적 사례를 반복했다. 이후 이 문제의식이 축적되어 SemEval-2020 Task 1(Schlechtweg et al., 2020)에서 인간 주석 기반 의미 변화 벤치마크가 처음 표준화됐다. 합성 변화를 심어 탐지율을 재는 통제 실험(Shoemark et al., 2019)도 관행이 됐다. 또 하나의 굵직한 비판이 빈도 혼입이다: Dubossarsky et al. (2017)은 시간 순서를 섞은 통제 코퍼스 실험으로, 보고된 "의미 변화 법칙"의 상당 부분이 단어 빈도와 표집 노이즈의 인공물임을 보였다. 이 논문의 드리프트 순위(Table 4)도 그런 통제 실험이 없으므로 같은 사정권에 있다 — 다만 random walk 사전분포가 저빈도 단어를 강하게 평활화하므로 노이즈성 드리프트에는 시대별 학습보다 강할 수 있고, 대신 반대 방향(진짜 변화의 과소평가·보간 지배, 6.3절)의 혼입을 만든다. 어느 쪽이든 검증되지 않았다. 임베딩 이웃이 시드에 따라 불안정하다는 보고(Hellrich & Hahn, 2016)까지 겹치면, 이 논문의 정성 표들은 단일 적합의 일화로 읽는 편이 맞다.

### 7.4 이후 계보 (논문 외 지식)

공동 학습 노선의 창립 삼각(본 논문, Bamler & Mandt (2017)의 베이즈 필터링, Yao et al. (2018)의 PMI 행렬 공동 분해)은 "정렬을 모델 구조로 해결한다"는 설계 철학을 공유하며 이후 서베이(Kutuzov et al., 2018)에서 한 갈래로 묶인다. 문맥 행렬을 고정해 시기 비교 가능성을 얻는 compass 계열(Di Carlo et al., 2019)은 이 논문의 α 공유와 발상이 닿아 있는 후속 절충이다. 2020년대 들어 분야의 무게중심은 문맥화 임베딩(BERT 계열) 기반 의미 변화 탐지로 이동했지만, 단어 단위 벡터의 시계열이 필요한 응용에서는 여전히 이 세대가 참조점이다. 같은 저자의 후속작(Rudolph et al., 2017)은 동일한 EFE 틀을 시간 대신 집단 축(예: 상원의원 정당별)으로 변주한 자매편이다.

### 7.5 위키·사회과학 관점에서 (논문 외 해석)

이 위키의 DWE(동적 단어 임베딩) 트랙에서 이 논문은 출발 문헌이다. "임베딩으로 사회·문화 변화를 측정"하는 프로그램의 방법 계보를 (1) 정적 word2vec → (2) 시대별 학습 + Procrustes 정렬(Hamilton 계열) → (3) 시간을 모델 안에 넣은 공동 학습으로 놓으면, 이 논문은 세 번째 단계의 원점 중 하나다. 흥미로운 사실이 하나 있다. 이 분야의 대표적 사회과학 응용들, 즉 100년치 젠더·인종 고정관념을 잰 Garg et al. (2018)과 계급 의미의 세기 단위 변화를 잰 Kozlowski et al. (2019)는 실제로는 (2)의 시대별 독립 학습 계열을 썼다(Garg는 Procrustes 정렬 벡터를, Kozlowski는 시기별 공간 안의 축 사영을 사용). 공동 학습 계열의 이점("얇은 슬라이스 수용 + 정렬 불요")은 대형 영어 코퍼스에서는 절실하지 않았지만, 시기별로 쪼개면 금방 얇아지는 한국어 통시 코퍼스(국회 회의록, 신문 아카이브)에는 정확히 필요한 성질이다. prostitution(슬라이스당 1회)과 iraq(76개 중 64개 슬라이스 미등장)의 궤적 학습은 저빈도 사회 어휘 측정 가능성의 앵커로 인용할 만하다. 단 6.3절의 교훈(보간과 추정의 비구별)을 반드시 함께 가져가야 한다. 상원 연설이라는 정치 텍스트에서 iraq·values·unemployment의 궤적을 보인 §3.3은 이후 의회 발언 코퍼스 임베딩 연구들이 이 논문을 인용하는 접점이기도 하다.

## 8. 결론

이 논문은 새 임베딩 알고리즘이라기보다 "임베딩을 확률 모델로 본 대가로 무엇을 얻는가"의 시범 사례다. EFE의 사전분포 자리에 동적 토픽 모델 전통의 random walk를 꽂는 것만으로, 당시 시대별 임베딩의 두 실무 난점(슬라이스 데이터 부족, 사후 정렬)이 모델 구조 안에서 함께 풀린다. 정량 근거는 held-out 예측력 6전 전승이지만 격차는 조건에 따라 크게 벌어지고 좁혀지며, "의미 변화를 올바르게 잡는가"라는 본질적 질문은 당시 분야의 평가 인프라 부재 속에 미검증으로 남았다. 그럼에도 사전분포로 정렬을 대체한 설계는 공동 학습 계열의 기본형이 됐고, 정성 사례들(computer·values·iraq)은 이 장르의 표준 전시물이 됐다.

읽는 법을 정리하면:

| 목적 | 어디를 읽나 |
|---|---|
| 모델의 핵심 설계 | §2의 Eq. 3–5와 Figure 2, 이 글 3장 |
| 시대별 학습 대비 무엇이 다른가 | §1 Related work의 두 난점, 이 글 1.2절 |
| 성능 주장의 실제 강도 | Table 2를 ± 정의 부재와 함께, 이 글 5.1절·6.1절 |
| 궤적 해석의 함정 | Appendix C와 Table 7의 iraq, 이 글 6.3절 |
| 이후 평가 관행과의 거리 | 이 글 7.3절(논문 외) |

시리즈의 다음 연결로는, 같은 문제의 베이즈 필터링 해법인 Bamler & Mandt (2017), 정렬 계열의 대표 Hamilton et al. (2016), 그리고 평가 표준을 세운 SemEval-2020 Task 1이 자연스러운 후속이다.

## References

Bamler, R., & Mandt, S. (2017). Dynamic word embeddings. *Proceedings of the 34th International Conference on Machine Learning*, 380–389. https://arxiv.org/abs/1702.08359 ([PDF 보기](/paper-viewer?title=Dynamic+word+embeddings&authors=Bamler%2C+Robert%3BMandt%2C+Stephan&year=2017&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1702.08359.pdf&arxiv_id=1702.08359&url=https%3A%2F%2Farxiv.org%2Fabs%2F1702.08359&source=blog-reference))

Blei, D. M., & Lafferty, J. D. (2006). Dynamic topic models. *Proceedings of the 23rd International Conference on Machine Learning*, 113–120. https://doi.org/10.1145/1143844.1143859 ([PDF 보기](/paper-viewer?title=Dynamic+topic+models&authors=Blei%2C+David+M.%3BLafferty%2C+John+D.&year=2006&doi=10.1145%2F1143844.1143859&url=https%3A%2F%2Fdoi.org%2F10.1145%2F1143844.1143859&source=blog-reference))

Di Carlo, V., Bianchi, F., & Palmonari, M. (2019). Training temporal word embeddings with a compass. *Proceedings of the AAAI Conference on Artificial Intelligence*, *33*(1), 6326–6334. https://doi.org/10.1609/aaai.v33i01.33016326 ([PDF 보기](/paper-viewer?title=Training+temporal+word+embeddings+with+a+compass&authors=Di+Carlo%2C+Valerio%3BBianchi%2C+Federico%3BPalmonari%2C+Matteo&year=2019&doi=10.1609%2Faaai.v33i01.33016326&url=https%3A%2F%2Fdoi.org%2F10.1609%2Faaai.v33i01.33016326&source=blog-reference))

Dubossarsky, H., Weinshall, D., & Grossman, E. (2017). Outta control: Laws of semantic change and inherent biases in word representation models. *Proceedings of the 2017 Conference on Empirical Methods in Natural Language Processing*, 1136–1145. https://doi.org/10.18653/v1/D17-1118 ([PDF 보기](/paper-viewer?title=Outta+control%3A+Laws+of+semantic+change+and+inherent+biases+in+word+representation+models&authors=Dubossarsky%2C+Haim%3BWeinshall%2C+Daphna%3BGrossman%2C+Eitan&year=2017&doi=10.18653%2Fv1%2FD17-1118&url=https%3A%2F%2Fdoi.org%2F10.18653%2Fv1%2FD17-1118&source=blog-reference))

Garg, N., Schiebinger, L., Jurafsky, D., & Zou, J. (2018). Word embeddings quantify 100 years of gender and ethnic stereotypes. *Proceedings of the National Academy of Sciences*, *115*(16), E3635–E3644. https://doi.org/10.1073/pnas.1720347115 ([PDF 보기](/paper-viewer?title=Word+embeddings+quantify+100+years+of+gender+and+ethnic+stereotypes&authors=Garg%2C+Nikhil%3BSchiebinger%2C+Londa%3BJurafsky%2C+Dan%3BZou%2C+James&year=2018&doi=10.1073%2Fpnas.1720347115&url=https%3A%2F%2Fdoi.org%2F10.1073%2Fpnas.1720347115&source=blog-reference))

Hamilton, W. L., Leskovec, J., & Jurafsky, D. (2016). Diachronic word embeddings reveal statistical laws of semantic change. *Proceedings of the 54th Annual Meeting of the Association for Computational Linguistics*, 1489–1501. https://doi.org/10.18653/v1/P16-1141 ([PDF 보기](/paper-viewer?title=Diachronic+word+embeddings+reveal+statistical+laws+of+semantic+change&authors=Hamilton%2C+William+L.%3BLeskovec%2C+Jure%3BJurafsky%2C+Dan&year=2016&doi=10.18653%2Fv1%2FP16-1141&url=https%3A%2F%2Fdoi.org%2F10.18653%2Fv1%2FP16-1141&source=blog-reference))

Hellrich, J., & Hahn, U. (2016). Bad company—Neighborhoods in neural embedding spaces considered harmful. *Proceedings of COLING 2016, the 26th International Conference on Computational Linguistics*, 2785–2796. https://aclanthology.org/C16-1262/ ([PDF 보기](/paper-viewer?title=Bad+company%E2%80%94Neighborhoods+in+neural+embedding+spaces+considered+harmful&authors=Hellrich%2C+Johannes%3BHahn%2C+Udo&year=2016&pdf_url=https%3A%2F%2Faclanthology.org%2FC16-1262.pdf&url=https%3A%2F%2Faclanthology.org%2FC16-1262%2F&source=blog-reference))

Kim, Y., Chiu, Y.-I., Hanaki, K., Hegde, D., & Petrov, S. (2014). Temporal analysis of language through neural language models. *Proceedings of the ACL 2014 Workshop on Language Technologies and Computational Social Science*, 61–65. https://doi.org/10.3115/v1/W14-2517 ([PDF 보기](/paper-viewer?title=Temporal+analysis+of+language+through+neural+language+models&authors=Kim%2C+Yoon%3BChiu%2C+Yi-I%3BHanaki%2C+Kentaro%3BHegde%2C+Darshan%3BPetrov%2C+Slav&year=2014&doi=10.3115%2Fv1%2FW14-2517&url=https%3A%2F%2Fdoi.org%2F10.3115%2Fv1%2FW14-2517&source=blog-reference))

Kozlowski, A. C., Taddy, M., & Evans, J. A. (2019). The geometry of culture: Analyzing the meanings of class through word embeddings. *American Sociological Review*, *84*(5), 905–949. https://doi.org/10.1177/0003122419877135 ([PDF 보기](/paper-viewer?title=The+geometry+of+culture%3A+Analyzing+the+meanings+of+class+through+word+embeddings&authors=Kozlowski%2C+Austin+C.%3BTaddy%2C+Matt%3BEvans%2C+James+A.&year=2019&doi=10.1177%2F0003122419877135&url=https%3A%2F%2Fdoi.org%2F10.1177%2F0003122419877135&source=blog-reference))

Kulkarni, V., Al-Rfou, R., Perozzi, B., & Skiena, S. (2015). Statistically significant detection of linguistic change. *Proceedings of the 24th International Conference on World Wide Web*, 625–635. https://doi.org/10.1145/2736277.2741627 ([PDF 보기](/paper-viewer?title=Statistically+significant+detection+of+linguistic+change&authors=Kulkarni%2C+Vivek%3BAl-Rfou%2C+Rami%3BPerozzi%2C+Bryan%3BSkiena%2C+Steven&year=2015&doi=10.1145%2F2736277.2741627&url=https%3A%2F%2Fdoi.org%2F10.1145%2F2736277.2741627&source=blog-reference))

Kutuzov, A., Øvrelid, L., Szymanski, T., & Velldal, E. (2018). Diachronic word embeddings and semantic shifts: A survey. *Proceedings of the 27th International Conference on Computational Linguistics*, 1384–1397. https://arxiv.org/abs/1806.03537 ([PDF 보기](/paper-viewer?title=Diachronic+word+embeddings+and+semantic+shifts%3A+A+survey&authors=Kutuzov%2C+Andrey%3B%C3%98vrelid%2C+Lilja%3BSzymanski%2C+Terrence%3BVelldal%2C+Erik&year=2018&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1806.03537.pdf&arxiv_id=1806.03537&url=https%3A%2F%2Farxiv.org%2Fabs%2F1806.03537&source=blog-reference))

Mikolov, T., Chen, K., Corrado, G., & Dean, J. (2013). *Efficient estimation of word representations in vector space*. arXiv. https://arxiv.org/abs/1301.3781 ([PDF 보기](/paper-viewer?title=Efficient+estimation+of+word+representations+in+vector+space&authors=Mikolov%2C+Tomas%3BChen%2C+Kai%3BCorrado%2C+Greg%3BDean%2C+Jeffrey&year=2013&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1301.3781.pdf&arxiv_id=1301.3781&url=https%3A%2F%2Farxiv.org%2Fabs%2F1301.3781&source=blog-reference))

Mikolov, T., Sutskever, I., Chen, K., Corrado, G. S., & Dean, J. (2013). Distributed representations of words and phrases and their compositionality. *Advances in Neural Information Processing Systems*, *26*. https://arxiv.org/abs/1310.4546 ([PDF 보기](/paper-viewer?title=Distributed+representations+of+words+and+phrases+and+their+compositionality&authors=Mikolov%2C+Tomas%3BSutskever%2C+Ilya%3BChen%2C+Kai%3BCorrado%2C+Greg+S.%3BDean%2C+Jeffrey&year=2013&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1310.4546.pdf&arxiv_id=1310.4546&url=https%3A%2F%2Farxiv.org%2Fabs%2F1310.4546&source=blog-reference))

Rudolph, M., & Blei, D. (2018). Dynamic embeddings for language evolution. *Proceedings of the 2018 World Wide Web Conference*, 1003–1011. https://doi.org/10.1145/3178876.3185999 ([PDF 보기](/paper-viewer?title=Dynamic+embeddings+for+language+evolution&authors=Rudolph%2C+Maja%3BBlei%2C+David&year=2018&doi=10.1145%2F3178876.3185999&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1703.08052.pdf&arxiv_id=1703.08052&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3178876.3185999&source=blog-reference))

Rudolph, M., Ruiz, F., Athey, S., & Blei, D. (2017). Structured embedding models for grouped data. *Advances in Neural Information Processing Systems*, *30*. https://arxiv.org/abs/1709.10367 ([PDF 보기](/paper-viewer?title=Structured+embedding+models+for+grouped+data&authors=Rudolph%2C+Maja%3BRuiz%2C+Francisco+J.+R.%3BAthey%2C+Susan%3BBlei%2C+David+M.&year=2017&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1709.10367.pdf&arxiv_id=1709.10367&url=https%3A%2F%2Farxiv.org%2Fabs%2F1709.10367&source=blog-reference))

Rudolph, M., Ruiz, F., Mandt, S., & Blei, D. (2016). Exponential family embeddings. *Advances in Neural Information Processing Systems*, *29*. https://arxiv.org/abs/1608.00778 ([PDF 보기](/paper-viewer?title=Exponential+family+embeddings&authors=Rudolph%2C+Maja%3BRuiz%2C+Francisco+J.+R.%3BMandt%2C+Stephan%3BBlei%2C+David+M.&year=2016&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1608.00778.pdf&arxiv_id=1608.00778&url=https%3A%2F%2Farxiv.org%2Fabs%2F1608.00778&source=blog-reference))

Schlechtweg, D., McGillivray, B., Hengchen, S., Dubossarsky, H., & Tahmasebi, N. (2020). SemEval-2020 Task 1: Unsupervised lexical semantic change detection. *Proceedings of the Fourteenth Workshop on Semantic Evaluation*, 1–23. https://doi.org/10.18653/v1/2020.semeval-1.1 ([PDF 보기](/paper-viewer?title=SemEval-2020+Task+1%3A+Unsupervised+lexical+semantic+change+detection&authors=Schlechtweg%2C+Dominik%3BMcGillivray%2C+Barbara%3BHengchen%2C+Simon%3BDubossarsky%2C+Haim%3BTahmasebi%2C+Nina&year=2020&doi=10.18653%2Fv1%2F2020.semeval-1.1&url=https%3A%2F%2Fdoi.org%2F10.18653%2Fv1%2F2020.semeval-1.1&source=blog-reference))

Shoemark, P., Liza, F. F., Nguyen, D., Hale, S., & McGillivray, B. (2019). Room to Glo: A systematic comparison of semantic change detection approaches with word embeddings. *Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th International Joint Conference on Natural Language Processing*, 66–76. https://doi.org/10.18653/v1/D19-1007 ([PDF 보기](/paper-viewer?title=Room+to+Glo%3A+A+systematic+comparison+of+semantic+change+detection+approaches+with+word+embeddings&authors=Shoemark%2C+Philippa%3BLiza%2C+Farhana+Ferdousi%3BNguyen%2C+Dong%3BHale%2C+Scott%3BMcGillivray%2C+Barbara&year=2019&doi=10.18653%2Fv1%2FD19-1007&url=https%3A%2F%2Fdoi.org%2F10.18653%2Fv1%2FD19-1007&source=blog-reference))

Yao, Z., Sun, Y., Ding, W., Rao, N., & Xiong, H. (2018). Dynamic word embeddings for evolving semantic discovery. *Proceedings of the Eleventh ACM International Conference on Web Search and Data Mining*, 673–681. https://doi.org/10.1145/3159652.3159703 ([PDF 보기](/paper-viewer?title=Dynamic+word+embeddings+for+evolving+semantic+discovery&authors=Yao%2C+Zijun%3BSun%2C+Yifan%3BDing%2C+Weicong%3BRao%2C+Nikhil%3BXiong%2C+Hui&year=2018&doi=10.1145%2F3159652.3159703&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3159652.3159703&source=blog-reference))
