# Training Temporal Word Embeddings with a Compass

**Paper:** Di Carlo, Valerio; Bianchi, Federico; Palmonari, Matteo. (2019). "Training Temporal Word Embeddings with a Compass." *Proceedings of the AAAI Conference on Artificial Intelligence, 33(01)*, pp. 6326–6334. arXiv:1906.02376.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 사후 정렬 단계를 아예 없애고, 학습하는 순간부터 모든 시대의 임베딩이 같은 좌표계에 태어나게 할 수 있는가? 그것을 word2vec을 크게 바꾸지 않고 작은 코퍼스에서도 안정적으로 할 수 있는가? |
| 핵심 기여 | 정렬을 사후 단계로 두지 않고 학습 안으로 넣는다. 시대 구분을 무시한 전체 코퍼스로 CBOW를 한 번 학습해 얻은 무시대 target 행렬 U를 나침반으로 고정하고, 각 시대 슬라이스에서는 U를 동결한 채 문맥 행렬만 재학습해 모든 시대 임베딩을 사후 정렬 없이 한 좌표계에 놓는다. |
| 방법적 결과 | 1단계에서 전체 코퍼스에 표준 CBOW를 돌려 무시대 target 행렬 U를 얻어 나침반으로 삼고, 2단계에서 각 시대 슬라이스마다 U를 초기화·동결한 채 시대별 문맥 행렬만 최적화한다(Eq. 1, 소프트맥스는 negative sampling으로 근사). 최종 시대별 단어 벡터로 반환되는 것은 나침반 U가 아니라 시대별 문맥 행렬이며, Skip-gram이 아닌 CBOW 위에 구현된다. |
| 실험 결과 | 작은 코퍼스 NAC-S(T1)에서 전 지표 최고(MRR 0.481, MP@10 0.636)로 당시 최강 경쟁자 DW2V(0.422/0.619)를 앞서고, 사후 정렬 계열(TW2V 0.143·OW2V 0.135)은 데이터 희소로 붕괴한다. 큰 코퍼스 NAC-L(T2)에서는 집계 최고(0.484)지만 OW2V(0.449)·TW2V(0.444)가 바짝 따라붙어 우위가 정적 유추에 국한된다(정적 0.948 대 동적 0.367). |
| 핵심 한계 | 집계 우위가 좌표계 공유로 쉽게 풀리는 정적 유추에 편중돼, 동적 유추에서는 사후 정렬 방법에 밀리기도 한다(대통령 범주 TW2V·OW2V 0.9905 대 TWEC 0.8833). held-out 로그가능도로는 시대를 무시한 정적 SW2V와 사실상 동률(MLPC -2.68 대 -2.67)이라 우위가 저자가 새로 도입한 posterior 지표에서 주로 나오고, 작은 코퍼스 강건성이라는 강점은 큰 코퍼스에서 거의 사라진다. |

**TL;DR** — (1) **TWEC**(Di Carlo et al., AAAI 2019)는 시대 구분을 무시한 전체 코퍼스로 학습한 무시대 target 행렬 U를 나침반으로 고정하고, 각 시대 슬라이스에서 U를 동결한 채 문맥 행렬만 재학습해 사후 정렬 없이 모든 시대 임베딩을 한 좌표계에 놓는 방법이다. (2) 작은 코퍼스 NAC-S에서 시대 유추 MRR 0.481로 당시 최강 경쟁자 DW2V(0.422)를 앞서고 사후 정렬 계열은 데이터 희소로 붕괴하지만, 큰 코퍼스 NAC-L에서는 OW2V·TW2V가 바짝 따라붙어 우위가 좁아진다. (3) 그 우위조차 좌표계 공유로 쉽게 풀리는 정적 유추에 편중되고, held-out 로그가능도로는 정적 모델과 동률이라 이득은 저자가 새로 도입한 posterior 지표에서 주로 드러난다.

---

## 목차

1. 서론
2. 방법: 나침반으로 좌표계를 공유한다
3. 실험 설정
4. 실험 결과
5. 주의해서 읽을 점
6. 방법적 한계와 확장
7. 결론

---

## 1. 서론

### 1.1 연구 배경

한 단어의 의미가 수십 년에 걸쳐 어떻게 변했는지 보려면, 시대별로 그 단어의 벡터를 구해 궤적을 그려야 한다. 문제는 벡터를 시대마다 따로 학습하면 좌표계가 어긋난다는 데 있다. word2vec의 목적함수는 벡터를 통째로 회전시켜도 값이 변하지 않아서, 학습을 돌릴 때마다 축이 임의의 각도로 돌아간다. 1990년의 "apple" 벡터와 2010년의 "apple" 벡터가 다른 좌표계에 있으면, 둘의 거리는 의미 차이가 아니라 좌표축의 회전을 재고 있을 뿐이다.

그래서 시대별 임베딩 연구의 절반은 정렬 문제였다. 대다수 방법은 시대별로 임베딩을 학습한 뒤, 사후에 직교 변환이나 선형 변환으로 좌표계를 맞췄다. 다른 갈래는 모든 시대를 한꺼번에 공동 학습하며 인접 시대의 벡터가 비슷하도록 제약을 걸었다.

### 1.2 핵심 질문

TWEC가 던지는 질문은 이렇다. 사후 정렬을 아예 없앨 수 있는가. 학습을 마친 다음 좌표계를 맞추는 대신, 학습하는 순간부터 모든 시대의 임베딩이 같은 좌표계에 태어나게 할 수 있는가. 그것을 word2vec을 크게 바꾸지 않고, 작은 코퍼스에서도 안정적으로 할 수 있는가.

### 1.3 학술적 위치

논문은 시대별 임베딩 정렬 연구를 두 범주로 정리한다. pairwise 정렬은 시대 쌍의 좌표계를 맞추는 방식으로, 사후 선형 변환(Szymanski)이나 직교 변환(Hamilton), 신경망 초기화 연쇄(Kim)가 여기 든다. joint 정렬은 전 시대 벡터를 동시에 학습하며 공통 기준에 묶는 방식으로, 전역 벡터 결속(Bamman), PPMI 행렬분해 제약(Yao), 확률모형의 평활 강제(Rudolph & Blei)가 여기 든다.

TWEC는 스스로를 제3의 자리에 놓는다. 명시적 정렬을 pairwise로도 joint로도 요구하지 않고, 공유 좌표계로 암묵 정렬한다는 것이다. 논문은 자신을 독립된 새 방법이라기보다 계보 위에 놓는다. 명시적 정렬 없이 공유 기준을 쓰는 발상이 선행 연구에 이미 있었고, 자신은 그것을 신경망 학습으로 부호화하고 선행 확률·결합 모형(예: Rudolph & Blei, Bamman)을 단순화한 것이라 적는다. 나침반과 지도 제작자 비유는 저자 자신이 붙인 이름이다.

---

## 2. 방법: 나침반으로 좌표계를 공유한다

### compass라는 발상

TWEC가 딛는 가정은 두 겹이다. 첫째, 대부분의 단어는 시간이 흘러도 의미가 변하지 않는다. 둘째, 의미가 변한 단어조차 거의 변하지 않는 단어들의 문맥에 등장한다. 논문의 예시로, "clinton"은 시기에 따라 다른 인물을 가리키지만 언제나 "president", "administration" 같은 안정적인 단어들의 곁에 나타난다.

이 가정에서 방법이 나온다. 안정적인 단어들이 만드는 기준 좌표계를 하나 고정해 두면, 그 기준에 대고 각 시대의 임베딩을 따로 학습해도 전부 같은 좌표계에 놓인다. 이 고정 기준이 나침반이다.

![TWEC 모델 구조](/api/blog/figures/twec-fig1-compass.png)

*TWEC 모델(원논문 Figure 1). 전체 코퍼스 $D$로 학습한 무시대 target 행렬 $U$가 나침반이다. 각 시대 슬라이스 $D^{t}$에서는 이 $U$를 초기값으로 넣고 동결한 채 문맥 행렬 $C^{t}$만 학습한다. 모든 $C^{t}$가 같은 $U$를 기준으로 학습되므로 자동 정렬된다.*

### 2단계 학습

word2vec에는 두 개의 행렬이 있다. 단어를 예측 대상으로 쓸 때의 target 행렬과 문맥으로 쓸 때의 context 행렬이다. TWEC는 이 둘을 갈라 쓴다.

1단계에서 시대 구분을 무시하고 전체 통시 코퍼스에 표준 CBOW를 돌려 무시대 target 행렬 $U$와 문맥 행렬 $C$를 얻는다. 여기서 $U$가 나침반이 된다.

2단계에서 각 시대 슬라이스마다 CBOW를 다시 돌리는데, 이번에는 target 행렬을 $U$로 초기화하고 **동결**한다. 그 시대 데이터로 갱신되는 것은 문맥 행렬 $C^{t}$뿐이다. 목적함수는 표준 CBOW와 같되 최적화 변수만 다르다.

$$\max_{C^{t}} \; \log P(w_k \mid \gamma(w_k)) = \sigma\!\left(\vec{u}_k \cdot \vec{c}^{\,t}_{\gamma(w_k)}\right) \quad (\text{Eq. 1})$$

$\vec{u}_k$는 동결된 무시대 target이고, $\vec{c}^{\,t}_{\gamma(w_k)}$는 문맥 단어들의 시대별 문맥 벡터 평균이다. $U$가 상수이고 $C^{t}$만 최적화되는 것이 고전 CBOW와의 유일한 차이다. 소프트맥스는 negative sampling으로 근사한다.

여기 반직관적인 점이 하나 있다. 최종 시대별 단어 임베딩으로 반환되는 것은 나침반인 $U$가 아니라 시대별 문맥 행렬 $C^{t}$다. 이유는 단순하다. $U$는 시대와 무관하게 고정돼 시간 정보를 담지 못하고, 시대에 따라 움직이는 것은 $C^{t}$뿐이라, 시대별 단어 의미는 문맥 행렬에서 읽을 수밖에 없다. 보통 word2vec에서 단어 벡터로 쓰는 것은 target 쪽인데, TWEC에서는 문맥 임베딩이 단어 표현이 된다.

### 왜 자동으로 정렬되나

핵심은 모든 시대의 $C^{t}$가 하나의 같은 고정 $U$에 대해 학습된다는 데 있다. 각 시대의 학습은 문맥 벡터를, 그 문맥에서 예측되는 단어의 고정 target 쪽으로 끌어당긴다. 서론에서 본 좌표축의 임의 회전은 target과 문맥을 함께 돌려도 내적 값이 변하지 않아 생기는데, $U$를 고정하면 $C^{t}$가 함께 회전할 자유가 사라진다. 기준점인 $U$가 시대 사이에 공유되므로, 서로 다른 시대에 독립적으로 학습된 문맥 임베딩도 처음부터 같은 좌표계 안에 놓인다. 사후에 좌표축을 맞추는 변환이 필요 없어진다.

방법은 반대 방향으로도 가능하다. 문맥을 동결하고 target을 움직여 target을 시대 임베딩으로 반환하는 거울 변형이다. 논문은 이 변형을 언급만 하고 본 논문의 범위 밖으로 둔다. 전체 복잡도는 전체 코퍼스 CBOW 한 번에 시대 슬라이스별 CBOW $n$번을 더한 것이다. TWEC는 Skip-gram이 아니라 CBOW 위에 구현되는데, 작은 데이터에서 CBOW가 더 낫더라는 경험적 관찰이 이유로 제시된다.

---

## 3. 실험 설정

세 개의 데이터셋을 쓴다.

| 데이터셋 | 규모 | 시대 | 구성 |
|---|---|---|---|
| NAC-S | 5천만 단어 | 1990–2016, 27개 연 슬라이스 | 뉴스 기사(소) |
| NAC-L | 6억 6800만 단어 | 1987–2007, 21개 슬라이스 | 뉴욕타임스(대) |
| MLPC | 650만 단어 | 2007–2015, 9개 슬라이스 | 머신러닝 논문, 어휘 5,000, 80/10/10 분할 |

평가는 두 축, 세 과제다.

첫째는 시대 유추다. "$w_1$은 $t_1$에서 무엇인가, $x$는 $t_2$에서 그에 대응한다" 꼴의 문제를 풀어 MRR과 MP@K로 채점한다. MRR은 정답 순위의 역수를 평균한 값이고, MP@K는 정답이 상위 K 안에 든 질의 비율이다. 집계 표는 @10을, 범주별 표와 시간 깊이 그림은 @1을 쓴다. 유추에는 두 종류가 있다. 정적 유추는 지시 대상이 시대에 걸쳐 안정적인 같은 단어를 인접 시대에서 다시 찾는 것으로("2000년의 apple"에 대응하는 "2001년의 apple"), 좌표계만 공유되면 거의 자명하게 풀린다. 동적 유추는 시대에 따라 역할의 담당자가 바뀌는 경우로("2008년의 대통령"에 대응하는 "2016년의 대통령"), 훨씬 어렵다. 유추 문제집은 두 벌이다. T1은 25개 범주 11,028문항(Yao 설정), T2는 10개 범주 4,200문항(Szymanski 설정)이다.

둘째는 held-out 평가다. 남겨 둔 데이터에 대한 정규화 로그가능도 $\mathcal{L}$과, 문서가 어느 시대 것인지 맞히는 posterior 확률 $\mathcal{P}$로 잰다. 로그가능도가 벡터 크기에 민감하다는 점 때문에 저자는 크기에 불변인 posterior를 새로 도입한다.

비교 대상은 일곱이다. 정적 baseline인 SW2V, 사후 정렬 계열인 TW2V(선형 변환, Szymanski 2017)와 OW2V(직교 변환, Hamilton 등 2016), 공동 학습 계열인 DW2V(행렬분해, Yao 등 2018)와 GW2V(전역 벡터 결속, Bamman 등 2014), 베르누이 임베딩 계열인 DBE(Rudolph & Blei 2018)와 SBE(Rudolph 등 2016)다. 이 중 DW2V의 수치는 원논문 값을 그대로 인용한 것이고, TW2V와 OW2V는 저자가 공통 CBOW 위에 정렬 기법만 재구현한 것이다.

---

## 4. 실험 결과

### 작은 코퍼스에서 앞선다

작은 코퍼스 NAC-S(T1)에서 TWEC가 전 지표 최고다. 집계 MRR 0.481, MP@10 0.636으로, 시대 유추에서 당시 가장 앞선 경쟁자였던 DW2V(0.422 / 0.619)를 앞선다. 논문은 정답 비율 기준으로 DW2V보다 7% 더 맞힌다고 적는다. 정적 baseline SW2V는 0.375다. 눈에 띄는 것은 사후 정렬 계열의 붕괴다. TW2V(0.143)와 OW2V(0.135)가 정적 baseline보다도 낮다. 슬라이스 하나가 3,500건 남짓의 기사로 성긴 탓에, 시대마다 따로 학습해 사후 정렬하는 방식이 데이터 부족으로 무너진 것이다. TWEC는 나침반을 전체 코퍼스로 한 번 학습하므로 이 희소성에 덜 휘둘린다.

### 큰 코퍼스에서 우위가 좁아진다

큰 코퍼스 NAC-L(T2)에서도 TWEC가 집계 최고(0.484)이지만 격차가 줄어든다. OW2V(0.449)와 TW2V(0.444)가 바짝 따라붙는다. 슬라이스마다 데이터가 넉넉해지자 사후 정렬 방식이 제 성능을 낸 것이다. 저자는 TWEC의 우위가 이제 정적 유추에 국한된다고 스스로 적는다. 실제로 TWEC의 정적 유추 정확도는 0.948인데 동적 유추는 0.367이다.

![시간 깊이에 따른 정확도](/api/blog/figures/twec-fig3-accuracy-over-time.png)

*NAC-L에서 유추의 시간 깊이 $\delta_t = |t_1 - t_2|$에 따른 정확도(원논문 Figure 3, MP@1). 세 시대 모델(OW2V·TW2V·TWEC)은 시간 깊이가 커져도 비슷하게 유지되지만, 정적 SW2V(주황 점선)는 시간 간격이 벌어질수록 0 근처로 무너진다.*

시간 깊이가 커질수록, 즉 비교하는 두 시대의 간격이 벌어질수록 정적 임베딩은 무력해진다. 위 그림에서 SW2V는 간격이 커지면 정확도가 0 근처로 떨어지는 반면, 세 시대 모델은 서로 비슷하게 버틴다. 큰 코퍼스에서 세 시대 모델이 거의 겹친다는 사실은, 데이터가 충분하면 정렬 방식의 차이가 별로 남지 않는다는 뜻이기도 하다.

### 범주별로 갈린다

범주별로 보면 성능의 출처가 드러난다(Table 4, MP@1). 대통령·시장·주지사처럼 직함이 이름을 끌어 주는 범주에서 점수가 높고(주지사 TWEC 0.9786), 오스카 배우상이나 NFL MVP 같은 범주에서는 대부분의 모델이 0에 가깝다. 동적 성격이 강한 대통령·슈퍼볼 범주에서는 오히려 TW2V·OW2V가 TWEC를 앞선다. 대통령 범주에서 TW2V·OW2V는 0.9905인데 TWEC는 0.8833이다. TWEC가 동적 유추에 정적인 답을 내놓는 경향 때문이다. 반대로 논문은 WTA 선수·영국 총리 범주에서는 TWEC가 유의하게 앞선다고 적는다(각각 0.2857·0.4595).

### held-out: 우도는 동률, 우위는 새 지표에서

held-out 평가로 오면 그림이 달라진다. 정규화 로그가능도 $\mathcal{L}$에서 TWEC는 시대를 무시한 정적 SW2V와 사실상 동률이고(MLPC에서 각각 -2.68과 -2.67), DBE(-1.86)나 SBE(-2.02)보다 낮다. 순수 우도만 보면 시대 모델링이 정적 모델보다 나을 게 없는 셈이다. 저자는 로그가능도가 벡터 크기에 민감하다는 점을 지적하며, 크기에 불변인 posterior $\mathcal{P}$를 도입한다. 이 지표에서는 TWEC가 두 데이터셋 모두 최고다(MLPC에서 -1.75 대 DBE -2.18, SW2V -2.20). 논문은 이를 두고 일반화 능력과 시대 판별 특징 추출 능력이 서로 다른 축임을 시사한다고 해석한다.

---

## 5. 주의해서 읽을 점

### 5.1 집계 점수가 평가셋 구성에 부풀려진다 (논문 외 비판)

시대 유추의 집계 MRR은 문제집이 어떻게 짜였는지에 크게 좌우된다. 논문 자신이 밝히듯 성능은 직함이 이름을 끌어 주는 소수 범주에 몰려 있고("obama"는 20,088회 등장하지만 "dicaprio"는 260회뿐이다), 다수 범주에서는 TWEC조차 0에 가깝다. 집계 숫자 하나로 방법을 비교하면 이 편중이 가려진다. 범주별 표를 함께 봐야 어디서 점수가 나오는지 알 수 있다.

### 5.2 집계 우위가 쉬운 문제에 편중된다 (논문 외 비판)

더 근본적인 문제가 있다. TWEC의 집계 우위는 상당 부분 정적 유추에서 나온다. 정적 유추는 좌표계만 공유되면 거의 자동으로 풀리고, TWEC의 설계는 바로 그 좌표계 공유를 잘하므로 정적 유추에 강할 수밖에 없다. 주력 코퍼스 NAC-S에서 TWEC의 정적 유추 정확도는 0.720인데 동적 유추는 0.394다(큰 코퍼스 NAC-L에서는 0.948 대 0.367로 격차가 더 벌어진다). 정작 어려운 동적 유추에서는 사후 정렬 방법에 밀리기도 한다. 동적 성격이 강한 대통령 범주에서 TW2V·OW2V(0.9905)가 TWEC(0.8833)를 앞선 것이 그 예다. 집계 MRR이 방법의 강점을 정직하게 요약하는지는 따져 봐야 한다. 다만 주력인 NAC-S 집계에서 DW2V 대비 우위는 DW2V 수치를 정적·동적으로 분해할 수 없어(5.3절) 같은 방식으로 못 박기는 어렵다.

### 5.3 held-out 최강 경쟁자와의 비교가 반쪽이다 (논문 외 비판)

held-out 우도에서 TWEC를 앞서는 유일한 모델이자 계산이 가장 무거운 DBE는, 그 비용 때문에 held-out에서만, 그것도 작은 데이터에서만 비교된다(DBE는 NAC-S 학습에 16코어로 여섯 시간이 걸린다). 주력 과제인 시대 유추 표에는 DBE가 없다. 저자는 DBE를 유추에서도 돌려 봤으나 정적 baseline과 비슷해 보고하지 않았다고 적는다. 그 진술을 받아들이면 TWEC(0.481)가 정적 baseline(0.375)과 비슷한 DBE도 앞선다는 것이 함의되지만, 수치가 공개되지 않아 저자 진술에만 기대야 한다. DW2V와의 비교도 원논문 수치를 인용한 것이라 정적·동적 유추로 분해할 수 없어, 정답 비율 +7%는 집계에서만 성립한다.

---

## 6. 방법적 한계와 확장

### 6.1 논문이 남긴 것

TWEC의 기여는 명료하다. 사후 정렬이라는 별도 단계를 없애고, 고정된 나침반 하나로 모든 시대의 임베딩이 같은 좌표계에 태어나게 했다. word2vec 위에 그대로 얹히고 구현이 쉬우며, 특히 슬라이스가 성긴 작은 코퍼스에서 사후 정렬 방식이 무너질 때 안정적으로 버틴다. 시대 유추에서 당시 가장 앞선 경쟁자이던 DW2V를 앞선 것도 사실이다. 정렬을 학습 안으로 넣는다는 발상은 단순하지만 효과가 분명하다.

### 6.2 큰 코퍼스에서 사라지는 우위와 빌려 온 설정 (논문 외 비판)

내세우는 강점은 작은 코퍼스의 강건성인데, 이 이점은 큰 코퍼스에서 거의 사라진다(4장의 NAC-L 결과). 데이터가 충분하면 굳이 나침반이 아니어도 된다는 뜻이다. 게다가 하이퍼파라미터가 대체로 baseline(Yao·Rudolph)에서 빌려 온 것이라 TWEC 전용 튜닝이나 민감도 분석이 없다. 문맥 창 크기가 과제에 따라 5와 1로 크게 다르고, 유추 실험에는 학습률·에폭·시드가 보고되지 않는다. 정적 반복과 동적 반복을 어떻게 배분하는지 같은 compass 고유의 조절 손잡이가 성능에 어떤 영향을 주는지도 탐구되지 않는다.

### 6.3 나침반이 평균이라는 점, 그리고 미탐구한 변형 (논문 외 비판)

나침반 $U$는 전체 코퍼스로 한 번만 학습한 시대 평균 의미다. 대부분의 단어가 안정적이라면 좋은 기준이지만, 의미가 크게 이동한 단어는 어느 시대도 잘 대표하지 못하는 흐릿한 평균이 되어, 그 단어의 시대별 임베딩을 평균 쪽으로 당길 소지가 있다. 다만 이건 설계에서 짚이는 우려일 뿐 논문이 직접 측정하지는 않았고, 오히려 논문의 PCA 궤적 그림은 대통령들의 임베딩이 재임 중 서로 교차하는 등 동역학이 보존됨을 예시로 든다. 검증되지 않은 채 남았다.

held-out 실험에서 저자는 문맥 행렬까지 정적 값으로 초기화하면 held-out 성능이 오르지만 유추 성능은 떨어진다고 인정한다. 과제마다 유리한 설정을 달리 쓴 것이라, 두 축의 성능을 한 설정에서 함께 보기 어렵다. 분산이나 시드도 보고되지 않아, 각 시대 모델이 독립된 확률적 학습으로 얻어지고 평활을 강제하지 않는다는 점을 생각하면 실행 간 변동이 얼마인지 알 수 없다. 문맥 대신 target을 움직이는 거울 변형은 범위 밖으로 남겼는데, 정작 논문 스스로 DBE를 바로 그 거울 배치로 서술한다. 어느 방향으로 동결하는 게 나은지에 대한 비교가 없다.

이 빈칸들은 방법의 골격을 그대로 두고도 채울 수 있는 것들이다. 큰 코퍼스에서 우위가 왜 사라지는지, 나침반 평균이 고드리프트 단어를 얼마나 당기는지, 동결 방향과 반복 배분이 결과를 어떻게 바꾸는지, 실행 간 분산은 얼마인지가 그것이다.

---

## 7. 결론

TWEC는 시대별 임베딩의 정렬 문제를 사후 단계에서 학습 단계로 옮긴 방법이다. 전체 코퍼스로 만든 고정 나침반에 각 시대를 정렬해 학습하니, 좌표계를 맞추는 별도 변환이 필요 없다. 단순하고, word2vec 위에 바로 얹히고, 작은 코퍼스에서 사후 정렬 방식이 무너질 때 안정적으로 버틴다. 이것이 이 논문의 분명한 값이다.

동시에 그 값의 크기는 조건을 탄다. 큰 코퍼스에서는 사후 정렬 방법이 따라잡아 우위가 좁아지고, 그 우위조차 좌표계 공유로 쉽게 풀리는 정적 유추에 편중된다. held-out 우도로는 정적 모델과 동률이라, 우위는 저자가 새로 도입한 지표에서 주로 드러난다. 방법의 발상은 깔끔하지만, 그것이 실제로 언제 얼마나 이득인지는 조건에 따라 갈린다. 방법을 이해하려는 독자에게 이 논문은 "어떻게 정렬을 없앴나"는 선명하게, "그 이득이 어디까지 가나"는 조건부로 남긴다.

---

## References

- Bamman, D., Dyer, C., & Smith, N. A. (2014). Distributed representations of geographically situated language. In *Proceedings of the 52nd Annual Meeting of the Association for Computational Linguistics (Vol. 2: Short Papers)* (pp. 828–834). ([PDF 보기](/paper-viewer?title=Distributed+representations+of+geographically+situated+language&source=blog-reference&authors=David+Bamman%3BChris+Dyer%3BNoah+A.+Smith&year=2014&doi=10.3115%2Fv1%2FP14-2134&url=https%3A%2F%2Fdoi.org%2F10.3115%2Fv1%2FP14-2134))
- Di Carlo, V., Bianchi, F., & Palmonari, M. (2019). Training temporal word embeddings with a compass. In *Proceedings of the AAAI Conference on Artificial Intelligence, 33*(01), 6326–6334. https://doi.org/10.1609/aaai.v33i01.33016326 ([PDF 보기](/paper-viewer?title=Training+Temporal+Word+Embeddings+with+a+Compass&source=blog-reference&authors=Valerio+Di+Carlo%3BFederico+Bianchi%3BMatteo+Palmonari&year=2019&doi=10.1609%2Faaai.v33i01.33016326&url=https%3A%2F%2Fdoi.org%2F10.1609%2Faaai.v33i01.33016326))
- Gulordava, K., & Baroni, M. (2011). A distributional similarity approach to the detection of semantic change in the Google Books Ngram corpus. In *Proceedings of the GEMS 2011 Workshop on Geometrical Models of Natural Language Semantics* (pp. 67–71).
- Hamilton, W. L., Leskovec, J., & Jurafsky, D. (2016). Diachronic word embeddings reveal statistical laws of semantic change. In *Proceedings of the 54th Annual Meeting of the Association for Computational Linguistics (Vol. 1: Long Papers)* (pp. 1489–1501). ([PDF 보기](/paper-viewer?title=Diachronic+Word+Embeddings+Reveal+Statistical+Laws+of+Semantic+Change&source=blog-reference&authors=William+L.+Hamilton%3BJure+Leskovec%3BDan+Jurafsky&year=2016&doi=10.18653%2Fv1%2FP16-1141&url=https%3A%2F%2Fdoi.org%2F10.18653%2Fv1%2FP16-1141))
- Kim, Y., Chiu, Y.-I., Hanaki, K., Hegde, D., & Petrov, S. (2014). Temporal analysis of language through neural language models. In *Proceedings of the ACL 2014 Workshop on Language Technologies and Computational Social Science* (pp. 61–65). ([PDF 보기](/paper-viewer?title=Temporal+analysis+of+language+through+neural+language+models&source=blog-reference&authors=Yoon+Kim%3BYi-I+Chiu%3BKentaro+Hanaki%3BDarshan+Hegde%3BSlav+Petrov&year=2014&arxiv_id=1405.3515&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1405.3515.pdf))
- Kulkarni, V., Al-Rfou, R., Perozzi, B., & Skiena, S. (2015). Statistically significant detection of linguistic change. In *Proceedings of the 24th International Conference on World Wide Web (WWW 2015)* (pp. 625–635). ([PDF 보기](/paper-viewer?title=Statistically+Significant+Detection+of+Linguistic+Change&source=blog-reference&authors=Vivek+Kulkarni%3BRami+Al-Rfou%3BBryan+Perozzi%3BSteven+Skiena&year=2015&doi=10.1145%2F2736277.2741627&url=https%3A%2F%2Fdoi.org%2F10.1145%2F2736277.2741627))
- Mikolov, T., Chen, K., Corrado, G., & Dean, J. (2013). Efficient estimation of word representations in vector space. In *Workshop Track Proceedings of ICLR 2013*. ([PDF 보기](/paper-viewer?title=Efficient+estimation+of+word+representations+in+vector+space&source=blog-reference&authors=Tomas+Mikolov%3BKai+Chen%3BGreg+Corrado%3BJeffrey+Dean&year=2013&arxiv_id=1301.3781&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1301.3781.pdf))
- Rudolph, M., & Blei, D. (2018). Dynamic embeddings for language evolution. In *Proceedings of the 2018 World Wide Web Conference (WWW 2018)* (pp. 1003–1011). ([PDF 보기](/paper-viewer?title=Dynamic+Embeddings+for+Language+Evolution&source=blog-reference&authors=Maja+Rudolph%3BDavid+M.+Blei&year=2018&doi=10.1145%2F3178876.3185999&arxiv_id=1703.08052&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1703.08052.pdf&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3178876.3185999))
- Rudolph, M., Ruiz, F., Mandt, S., & Blei, D. (2016). Exponential family embeddings. In *Advances in Neural Information Processing Systems 29 (NIPS 2016)* (pp. 478–486). ([PDF 보기](/paper-viewer?title=Exponential+family+embeddings&source=blog-reference&authors=Maja+Rudolph%3BFrancisco+Ruiz%3BStephan+Mandt%3BDavid+Blei&year=2016&arxiv_id=1608.00778&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1608.00778.pdf))
- Smith, S. L., Turban, D. H. P., Hamblin, S., & Hammerla, N. Y. (2017). Offline bilingual word vectors, orthogonal transformations and the inverted softmax. In *International Conference on Learning Representations (ICLR 2017)*. ([PDF 보기](/paper-viewer?title=Offline+bilingual+word+vectors%2C+orthogonal+transformations+and+the+inverted+softmax&source=blog-reference&authors=Samuel+L.+Smith%3BDavid+H.+P.+Turban%3BSteven+Hamblin%3BNils+Y.+Hammerla&year=2017&arxiv_id=1702.03859&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1702.03859.pdf))
- Szymanski, T. (2017). Temporal word analogies: Identifying lexical replacement with diachronic word embeddings. In *Proceedings of the 55th Annual Meeting of the Association for Computational Linguistics (Vol. 2: Short Papers)* (pp. 448–453). ([PDF 보기](/paper-viewer?title=Temporal+Word+Analogies%3A+Identifying+Lexical+Replacement+with+Diachronic+Word+Embeddings&source=blog-reference&authors=Terrence+Szymanski&year=2017&doi=10.18653%2Fv1%2FP17-2071&url=https%3A%2F%2Fdoi.org%2F10.18653%2Fv1%2FP17-2071))
- Yao, Z., Sun, Y., Ding, W., Rao, N., & Xiong, H. (2018). Dynamic word embeddings for evolving semantic discovery. In *Proceedings of the Eleventh ACM International Conference on Web Search and Data Mining (WSDM 2018)* (pp. 673–681). ([PDF 보기](/paper-viewer?title=Dynamic+Word+Embeddings+for+Evolving+Semantic+Discovery&source=blog-reference&authors=Zijun+Yao%3BYifan+Sun%3BWeicong+Ding%3BNikhil+Rao%3BHui+Xiong&year=2018&doi=10.1145%2F3159652.3159703&arxiv_id=1703.00607&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1703.00607.pdf&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3159652.3159703))
