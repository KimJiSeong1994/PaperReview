# Statistically Significant Detection of Linguistic Change

**Paper:** Kulkarni, Vivek; Al-Rfou, Rami; Perozzi, Bryan; Skiena, Steven. (2015). "Statistically Significant Detection of Linguistic Change." *Proceedings of the 24th International Conference on World Wide Web (WWW 2015)*, pp. 625–635. arXiv:1411.3315.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 단어의 의미가 시간에 따라 변했다는 것을 어떻게 자동으로, 그리고 우연이 아니라 통계적으로 유의하게 말할 수 있는가? 어떤 단어가 언제 변했는지를 p-value와 함께 짚을 수 있는가? |
| 핵심 기여 | 의미 변화 탐지를 통계 검정의 문제로 세웠다. 단어마다 사용 변화를 담은 시계열을 세 방식(빈도, 품사 분포의 Jensen-Shannon 발산, 임베딩 변위)으로 만들고, 그 시계열에 변화점 탐지와 유의성 검정을 붙여 변화 시점과 p-value를 함께 낸다. |
| 방법적 결과 | 시계열을 전체 어휘 기준 Z-score로 정규화하고, 각 후보 시점 앞뒤 평균의 차이(평균 이동, Eq. 10)를 계산한 뒤, 시점 순서를 무작위로 섞은 순열 부트스트랩(보통 1,000개)으로 귀무분포를 세워 p-value를 얻는다(Algorithm 1). 임베딩 시계열은 시기별 skip-gram을 단어별 최근접 이웃 앵커의 조각별 선형 회귀로 정렬해(Eq. 7) 초기 시점 대비 코사인 거리(Eq. 8)로 만든다. |
| 실험 결과 | 세 코퍼스(Google Books·Amazon 리뷰·Twitter)에서 임베딩 방법이 오탐과 미탐의 균형이 가장 좋고 언어 자원 없이 가장 폭넓은 변화를 잡는다. 빈도는 오탐이 많고(인기 상승이 의미 변화로 오인), 품사는 미탐이 많다. 합성 코퍼스 MRR 평가에서 치환 확률이 0.4를 넘으면 임베딩이 다른 방법을 능가한다. |
| 핵심 한계 | p-value가 재는 것은 구성한 대리 시계열의 시간 구조이지 의미 변화 자체가 아니고(구성 타당도 간극), 5만~10만 어휘에 다중검정 보정이 없으며, 임베딩 변위에는 정렬 잔차와 학습 잡음이 섞인다. 실제 변화의 정답이 없어 정량 평가는 합성 코퍼스 하나에 기댄다. |

**TL;DR** — (1) **Kulkarni et al.**(WWW 2015)은 의미 변화 탐지를 **통계 검정**의 문제로 세워, 단어별 시계열(빈도·품사 JSD·**임베딩 변위**)에 평균 이동 통계량과 **순열 부트스트랩**을 붙여 변화 시점과 p-value를 함께 내는 **변화점 탐지** 절차를 제시한다. (2) 세 코퍼스 비교에서 임베딩 방법이 오탐·미탐 균형이 가장 좋아 gay·tape·sandy 같은 의미 이동을 잡고, 허리케인 샌디 사례로 빈도 급증(hurricane)이 의미 변화가 아님을 가른다. (3) 다만 그 유의성은 대리 시계열에 대한 것이라 의미 변화 자체의 검정이 아니고, 다중검정 보정 부재와 정렬 잔차 혼입이라는 한계가 남는다.

---

## 목차

1. 서론
2. 방법: 세 시계열과 변화점 검정
3. 실험 설정
4. 실험 결과
5. 주의해서 읽을 점
6. 방법적 한계와 확장
7. 결론

---

## 1. 서론

### 1.1 연구 배경

언어는 계속 변한다. "gay"는 20세기 초 "쾌활한"에서 후반의 "동성애의"로, "tape"는 "빨간 끈(red tape)"의 함의에서 자기 테이프로 옮겨 갔다. 인터넷에서는 이 변화가 더 빠르다. 문제는 그 변화를 어떻게 자동으로, 그리고 우연이 아니라고 말할 수 있게 잡느냐다.

![의미 공간의 gay 궤적](/api/blog/figures/kulkarni-fig1-semantic-space.png)

*임베딩 공간을 2차원으로 사영한 "gay"의 의미 궤적(원논문 Figure 1). 1900년의 "gay"는 cheerful·dapper·courteous 이웃에 있다가, 1950·1975·1990년을 거쳐 2005년에는 lesbian·homosexual·transgender 이웃으로 이동한다.*

### 1.2 핵심 질문

이 논문의 목표는 단순한 탐지를 넘어선다. 어떤 단어가 언제 변했는가를 짚되, 그 변화가 통계적으로 유의한지, 즉 유한한 코퍼스의 잡음이 아니라 진짜 신호인지를 함께 말하려 한다. 그러려면 단어의 사용을 시계열로 바꾸고, 그 시계열에 변화점 탐지와 유의성 검정을 붙여야 한다.

### 1.3 학술적 위치

논문은 자신을 유의한 언어 변화 탐지의 첫 계산적 접근으로 규정한다. 서론에서 "통계적으로 건전한 첫 방법(우리가 아는 한)"이라 밝힌다. 다만 초록은 같은 기여를 "a new computational approach"로 낮춰 써서, 논문 안에서도 표현의 수위가 갈린다. 선행 연구와의 차별점은 세 갈래로 든다. 전체 언어를 집계한 Michel의 culturomics나 Juola는 개별 단어의 변화를 짚지 못했고, 통시 임베딩 초기 연구(Gulordava & Baroni 등)는 두 시점만 비교하며 변화점 알고리즘이 없었고, Kim(2014)은 직전 시기 임베딩으로 순차 학습해 병렬화가 어렵다는 것이다. 변화점 탐지 통계량 자체는 평균 이동 모델(Taylor)과 CUSUM 계열의 문헌에서 빌려 온다.

세 표현은 복잡도가 커지는 세 단계로 배치된다. 빈도는 의미의 획득·상실을 반영하지만 장르 편향에 취약하고, 품사는 새 품사의 획득을 잡지만(apple이 보통명사에서 고유명사로) 품사가 그대로인 변화는 놓치며, 임베딩은 품사가 불변이어도 문맥으로 미묘한 변화를 잡는다. 논문은 임베딩 방법을 이 세 단계의 마지막, 가장 정교한 방법으로 둔다.

---

## 2. 방법: 세 시계열과 변화점 검정

### 세 가지 시계열

단어 $w$의 사용 변화를 시점 $t$의 값 $T_t(w)$로 담는 시계열을 세 방식으로 만든다.

**빈도**(Eq. 1)는 유니그램 로그 확률이다. $T_t(w) = \log(\#(w \in C_t)/|C_t|)$로, 시점 $t$ 코퍼스에서 $w$가 얼마나 자주 나오는지다.

**품사**(Eq. 2)는 품사 분포의 변화다. 시점 $t$에서 $w$의 품사 태그 분포 $Q_t$를 구하고, 초기 분포 $Q_0$와의 Jensen-Shannon 발산 $T_t(w) = \text{JSD}(Q_0, Q_t)$를 값으로 쓴다. apple이 보통명사에서 고유명사로 바뀌면 이 발산이 커진다.

**분포**는 임베딩 변위다. 시기별로 skip-gram 임베딩을 따로 학습하고(차원 200, 문맥창 10, 단 Google Books는 5-gram이라 창 5), L2 정규화한다. 문제는 시기별 공간의 좌표축이 서로 어긋난다는 것이다. 논문은 시대 간 공간을 선형 변환으로 정렬한다(Eq. 7). 각 단어마다 그 단어의 최근접 이웃을 앵커로 삼아 최소제곱으로 사상 $W_{t \to 0}$을 적합하는 조각별 선형 회귀다. 정렬한 뒤 초기 시점 대비 코사인 거리를 변위로 삼는다.

$$T_t(w) = 1 - \cos\!\big(\phi_t(w) W_{t \to 0},\; \phi_0(w)\big) \quad (\text{Eq. 8})$$

정렬은 두 가정 위에 선다. 두 공간이 선형 변환으로 동치이고, 대부분의 단어가 변하지 않아 국소 구조가 보존된다는 것이다. 논문 스스로 정렬이 잘 안 되면 그것이 오히려 언어 변화의 징후일 수 있고, 같은 데이터로 다시 학습해도 좌표가 달라진다고 밝힌다.

### 변화점과 유의성

이 논문의 중심은 시계열에서 변화점을 찾고 그 유의성을 매기는 절차다(Algorithm 1).

![변화점 탐지 알고리즘](/api/blog/figures/kulkarni-fig6-change-point.png)

*변화점 탐지의 다섯 단계(원논문 Figure 6, $t=1985$ 예시). ① 시계열 $\mathcal{T}(w)$를 정규화해 $\mathcal{Z}(w)$를 얻고, ② 시점 순서를 무작위로 섞어 순열 표본을 만들고, ③ 원본과 순열본 모두에 평균 이동 $\mathcal{K}$를 적용하고, ④ 관심 시점에서 순열 표본들의 평균 이동 분포를 만들고, ⑤ 관측값이 그 분포를 넘어설 확률을 p-value로 삼는다.*

먼저 시계열을 Z-score로 정규화한다(Eq. 9). 이때 평균과 분산은 그 시점의 모든 단어에 걸쳐 계산한다(논문은 분모를 표준편차라 부르지만 수식은 분산이라, 명칭과 표기가 어긋난다. 순열 검정의 순위에는 영향이 없다). 한 단어의 값이 그 시점 어휘 분포에서 얼마나 이상치인지를 보는 것이다. 다음으로 각 후보 시점 $j$를 기준으로 앞뒤 두 구간의 평균 차이를 평균 이동으로 계산한다.

$$\mathcal{K}(S) = \frac{1}{l-j}\sum_{k=j+1}^{l} S_k - \frac{1}{j}\sum_{k=1}^{j} S_k \quad (\text{Eq. 10})$$

유의성은 순열 부트스트랩으로 잰다. 시계열의 시점 순서를 무작위로 섞은 표본을 여럿(보통 1,000개) 만들고, 각 표본의 평균 이동으로 귀무분포를 세운다. 관측된 평균 이동이 이 분포를 넘어설 경험적 비율이 p-value다. 마지막으로 Z-score가 임계값 $\gamma$(보통 1.75) 이상인 후보 시점 중 p-value가 가장 작은 시점을 추정 변화점으로 반환한다. 이 절차가 세 시계열 어디에나 붙는다는 것이 이 방법의 일반성이다.

---

## 3. 실험 설정

시간 규모가 크게 다른 세 코퍼스를 쓴다(Table 1).

| 코퍼스 | 기간·주기 | 단어 수 | 어휘 | 문서 수 |
|---|---|---|---|---|
| Google Books Ngram | 1900–2005, 5년(21시점) | ~10⁹ | ~5만 | ~7.5×10⁸ |
| Amazon 영화 리뷰 | 1997–2012, 1년(13시점) | ~9.9×10⁸ | ~5만 | 8×10⁶ |
| Twitter | 2011–2013, 1개월(24개월) | ~10⁹ | ~10만 | ~10⁸ |

세 코퍼스 모두 단어 수가 수십억 규모다. Google Books는 5-gram을 써서 문맥창이 5로 제한되고 품사 분포는 Google Syntactic Ngrams에서 취한다. Amazon은 초기 리뷰가 적어 2000년부터 쓴다. 분석 대상 어휘는 모든 시점에 공통으로 나타나는 단어의 교집합이다. 그래서 어휘가 5만~10만으로 줄고, 앞서 본 Z-score 정규화의 모집단도 이 어휘다. 새로 생긴 단어는 대상에서 빠지고, 전 기간 존속한 단어의 의미 이동만 검정한다. sandy·candy·shades가 모두 기존 단어의 새 의미인 것도 이 제약 때문이다.

평가는 두 갈래다. 하나는 세 방법의 탐지 특성 비교로, 이미 의미 변화가 알려진 단어들에 대해 어느 방법이 무엇을 잡는지 본다. 다른 하나는 정량 평가인데, 실제 변화에는 정답이 없으므로 합성 코퍼스를 만든다. 위키피디아 text8을 20번 복제해 스냅샷으로 삼고, 마지막 10개 스냅샷에서 단어를 확률 $p_{\text{replacement}}$로 다른 단어로 치환해 인위적 변화를 심은 뒤, 각 방법이 변화한 단어를 얼마나 잘 순위 매기는지를 MRR로 잰다.

---

## 4. 실험 결과

### 세 방법은 서로를 보완한다

Google Books에서 세 방법을 비교하면 성격이 갈린다(Table 2). 빈도는 오탐이 많다. "her"의 사용이 1960년대에 급증하는데, 이것은 의미가 변해서가 아니라 여성 운동으로 그 단어가 자주 쓰인 부산물이다. 품사는 오탐이 적지만 미탐이 많고 좋은 태거에 의존한다. 임베딩은 오탐과 미탐의 균형이 가장 좋고, 별도의 언어 자원 없이 작동한다.

검출 시점을 보면 두 방법의 보완 관계가 뚜렷하다(Table 3). 임베딩 방법은 "gay"(1985), "tape"(1970), "sex"(1965), "bitch"(1955, 암캐에서 속어로), "plastic"(1950) 같은 의미 이동을 잡는다. 품사 방법은 "apple"(1984, 보통명사에서 고유명사로), "bush"(1989, 조지 H. W. 부시 취임), "windows"(1992, 마이크로소프트)처럼 품사가 바뀐 변화를 잡는다. 임베딩이 놓친 apple·windows·bush를 품사가, 품사가 놓친 sex·tape·bitch를 임베딩이 잡는다.

웹 코퍼스에서는 더 빠른 변화를 짚는다(Table 4). Amazon에서 "rays"·"ray"는 2006~2008년 블루레이의 등장과 맞물리고, "twilight"의 변화점(2009)은 2008년 11월 개봉한 영화 Twilight와 이어진다. Twitter에서 "shades"는 2012년 6월 소설 출간과, "sandy"는 2012년 9월 허리케인 상륙 몇 주 전과, "candy"는 2013년 4월 게임 유행과 이어진다.

### 빈도 급증은 의미 변화가 아니다

빈도와 의미가 갈리는 대표 사례가 허리케인 샌디다(Figure 2). 허리케인 샌디 때 "sandy"와 "hurricane"은 둘 다 검색·사용 빈도가 급증한다. 그러나 임베딩 방법의 Z-score는 "sandy"만 오른다. "hurricane"은 원래 뜻 그대로 더 자주 쓰였을 뿐이고, "sandy"는 형용사(sandy beaches)에서 재난의 고유명사로 뜻이 옮겨 갔다. 빈도가 오른 것은 인기의 표시일 뿐이다. 다만 이 비교는 정성적 대조이고, 상관계수 같은 정량 수치는 제시되지 않는다.

### 합성 코퍼스의 정량 평가

유일한 정량 평가는 합성 코퍼스의 MRR이다(Figure 7). 인위적 치환 확률 $p_{\text{replacement}}$를 키워 가며 각 방법의 순위 성능을 본다. 같은 품사 쌍으로 바꾸는 설정에서는 임베딩이 모든 확률에서 빈도를 앞선다. 품사 제약을 풀면 품사 방법은 변화가 작을 때만 앞서고, 변화가 커지면 태거 품질이 떨어져 성능이 내려간다. 논문은 치환 확률이 0.4를 넘으면 임베딩이 언어 자원 없이 다른 방법을 능가한다고 정리한다.

---

## 5. 주의해서 읽을 점

### 5.1 유의성의 대상이 의미 변화가 아니다 (논문 외 비판)

제목은 "통계적으로 유의한 언어 변화 탐지"인데, 실제로 검정하는 대상은 언어 변화 자체가 아니다. p-value는 구성한 대리 시계열(변위·JSD·빈도)의 평균 이동이, 시점 순서를 섞은 순열 귀무분포보다 큰지를 잰다. 즉 이 시계열에 시간 구조가 있다는 것을 검정할 뿐, 그 시계열이 진짜 의미 변화를 타당하게 담고 있는지는 검정하지 않는다. 시계열이 잡음이나 코퍼스 인공물에서 왔더라도 시간 구조만 있으면 유의하게 나온다. 제목의 "언어 변화"와 검정 대상 사이에 구성 타당도의 간극이 있다.

### 5.2 다중검정 보정이 없고 p-value가 분해능을 넘는다 (논문 외 비판)

어휘가 5만에서 10만인데 다중검정 보정이 전혀 없다. 각 단어를 검정하되 Z-score가 임계값을 넘은 후보 시점 중 p-value가 가장 작은 시점을 고르는데(Algorithm 1), 단어 사이의 보정도, 시점을 훑는 데 대한 보정도 없다. 임계값 사전 필터와 최소값 선택이 겹쳐 낙관적 편향을 낳는다. 더 구체적인 문제도 있다. 부트스트랩 표본이 기본 1,000개면 경험적 p-value의 최소 분해능은 1/1,000인데, 표에는 "gay" 0.0001, "tape" 0.0001 미만 같은 값이 보고된다. 1,000개 순열로는 나올 수 없는 값이라, 특정 결과에 미보고된 더 큰 부트스트랩을 썼거나 아니면 명시된 기본 규모와 일관되지 않는다.

### 5.3 정렬 잔차가 변위에 섞인다 (논문 외 비판)

임베딩 변위는 순수한 의미 변화가 아니다. 시대 간 정렬(Eq. 7)이 완벽하지 않으면 그 잔차가 변위에 더해진다. 논문 자신이 정렬 실패가 언어 변화의 징후일 수 있다고 인정하고, 같은 데이터로 다시 학습해도 좌표가 달라진다고 밝힌다. 그렇다면 관측된 변위는 진짜 변화, 정렬 잔차, 학습 잡음이 뒤섞인 값이다. 게다가 정렬을 단어별 최근접 이웃으로 국소 적합하는데, 의미가 이동한 단어는 이웃이 이미 새 의미 쪽이라 정렬 기준 자체가 오염된다. 이웃 수 $k$가 논문에 명시되지 않아 재현도 어렵다.

---

## 6. 방법적 한계와 확장

### 6.1 논문이 남긴 것

이 논문의 기여는 의미 변화 탐지에 통계적 절차를 붙인 데 있다. 변화의 유무만이 아니라 변화 시점과 p-value를 함께 내는 틀을 세웠고, 그 틀이 빈도·품사·임베딩 세 시계열 어디에나 붙는다. 세 방법을 나란히 비교해 각자의 오탐·미탐 성향과 보완 관계를 드러낸 것도 실용적이다. 빈도 급증과 의미 변화를 가른 샌디·허리케인 사례를 보면, 문화 계량 연구가 빈도를 의미로 오독하기 쉽다는 점이 드러난다.

### 6.2 단일 변화점과 평균 이동 가정 (논문 외 해석)

방법은 한 시계열에 변화점이 하나라고 가정한다. 평균 이동(Eq. 10)은 한 시점을 기준으로 앞뒤를 가르고, 알고리즘은 p-value가 가장 작은 단일 변화점만 반환한다. 그래서 여러 번에 걸쳐 변한 단어나 서서히 변한 단어를 잡기 어렵다. 논문 자신도 이 방법이 변화의 크기를 고려하지 않는다고 인정하며 임계값을 덧댄다. 다중 변화점 모델이나 점진 변화를 담는 추세 모델은 같은 순열 검정 틀을 그대로 두고 평균 이동 통계량만 바꾸는 방향으로 열린다.

### 6.3 정답의 부재와 재현성 (논문 외 비판)

실제 언어 변화에 대한 정답이 없다. 정량 평가는 위키피디아를 복제해 인위적으로 단어를 바꿔 심은 합성 코퍼스 하나뿐이고, 실제 사례는 이미 변화가 알려진 단어를 손으로 고른 일화들이다. 손으로 고른 예시가 잘 맞는 것과 방법이 미지의 변화를 정확히 잡는 것은 다르다. 재현성 쪽에도 빈칸이 있다. 임베딩이 확률적이라고 인정하면서 시드나 정렬 이웃 수가 보고되지 않고, Z-score를 그 시점 전체 단어 기준으로 재는 탓에 많은 단어가 동시에 이동하는 시기에는 개별 변화가 가려진다. Google Books의 알려진 코퍼스 인공물이 임베딩 문맥을 흔들어 변위를 만들 가능성도 통제되지 않는다.

---

## 7. 결론

Kulkarni et al.의 이 논문은 의미 변화 탐지를 통계 검정의 문제로 옮긴다. 단어의 사용을 세 가지 시계열로 담고, 평균 이동과 순열 부트스트랩으로 변화 시점과 p-value를 함께 낸다. 세 방법의 비교에서 임베딩이 가장 폭넓고 균형 잡힌 탐지를 보이고, 빈도 급증이 의미 변화가 아님을 샌디 사례로 분명히 한 것이 이 작업의 값이다.

동시에 그 "유의성"은 자기 대리 시계열에 대한 것이라, 검정하는 대상과 제목의 언어 변화 사이에 간극이 있다. 다중검정 보정이 없고, 보고된 p-value가 부트스트랩 규모를 넘어서며, 임베딩 변위에는 정렬 잔차가 섞인다. 정답 없는 과제를 합성 코퍼스와 손으로 고른 예시로 검증한 한계도 남는다. 방법을 이해하려는 독자에게 이 논문은 "의미 변화에 어떻게 유의성을 붙이는가"는 명료한 절차로, "그 유의성이 무엇의 유의성인가"는 열어 둔 물음으로 남긴다.

---

## References

- Gulordava, K., & Baroni, M. (2011). A distributional similarity approach to the detection of semantic change in the Google Books Ngram corpus. In *Proceedings of the GEMS 2011 Workshop on Geometrical Models of Natural Language Semantics* (pp. 67–71).
- Kim, Y., Chiu, Y.-I., Hanaki, K., Hegde, D., & Petrov, S. (2014). Temporal analysis of language through neural language models. In *Proceedings of the ACL 2014 Workshop on Language Technologies and Computational Social Science* (pp. 61–65). ([PDF 보기](/paper-viewer?title=Temporal+analysis+of+language+through+neural+language+models&source=blog-reference&authors=Yoon+Kim%3BYi-I+Chiu%3BKentaro+Hanaki%3BDarshan+Hegde%3BSlav+Petrov&year=2014&arxiv_id=1405.3515&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1405.3515.pdf))
- Kulkarni, V., Al-Rfou, R., Perozzi, B., & Skiena, S. (2015). Statistically significant detection of linguistic change. In *Proceedings of the 24th International Conference on World Wide Web (WWW 2015)* (pp. 625–635). https://doi.org/10.1145/2736277.2741627 ([PDF 보기](/paper-viewer?title=Statistically+Significant+Detection+of+Linguistic+Change&source=blog-reference&authors=Vivek+Kulkarni%3BRami+Al-Rfou%3BBryan+Perozzi%3BSteven+Skiena&year=2015&doi=10.1145%2F2736277.2741627&arxiv_id=1411.3315&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1411.3315.pdf&url=https%3A%2F%2Fdoi.org%2F10.1145%2F2736277.2741627))
- Michel, J.-B., Shen, Y. K., Aiden, A. P., Veres, A., Gray, M. K., The Google Books Team, ... Aiden, E. L. (2011). Quantitative analysis of culture using millions of digitized books. *Science, 331*(6014), 176–182.
- Mikolov, T., Sutskever, I., Chen, K., Corrado, G. S., & Dean, J. (2013). Distributed representations of words and phrases and their compositionality. In *Advances in Neural Information Processing Systems 26 (NIPS 2013)* (pp. 3111–3119). ([PDF 보기](/paper-viewer?title=Distributed+representations+of+words+and+phrases+and+their+compositionality&source=blog-reference&authors=Tomas+Mikolov%3BIlya+Sutskever%3BKai+Chen%3BGreg+Corrado%3BJeffrey+Dean&year=2013&arxiv_id=1310.4546&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1310.4546.pdf))
- Řehůřek, R., & Sojka, P. (2010). Software framework for topic modelling with large corpora. In *Proceedings of the LREC 2010 Workshop on New Challenges for NLP Frameworks* (pp. 45–50).
- Taylor, W. A. (2000). *Change-point analysis: A powerful new tool for detecting changes*. Taylor Enterprises.
