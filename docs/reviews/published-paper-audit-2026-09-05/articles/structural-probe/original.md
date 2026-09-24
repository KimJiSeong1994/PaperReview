## Paper

> Hewitt, J., & Manning, C. D. (2019). *A structural probe for finding syntax in word representations*. In Proceedings of the 2019 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies (NAACL-HLT 2019), Volume 1 (Long and Short Papers), 4129–4138. https://doi.org/10.18653/v1/N19-1419

## Abstract

기존 probing은 품사나 형태 같은 개별 언어 속성이 표현에 담겼는지 검사했지만, 구문 트리가 "전체로서" 표현에 담겼는지는 검사하지 않았다. 이 논문은 신경망의 단어 표현 공간에 선형 변환 하나를 학습해, 그 변환 공간에서 두 단어 벡터의 제곱 L2 거리가 parse tree에서 두 단어 사이의 거리(간선 수)를, 제곱 L2 노름이 트리에서의 깊이를 인코딩하는지를 검사하는 structural probe를 제안한다. 저자들은 ELMo와 BERT에서는 이런 변환이 존재하지만 여러 베이스라인에서는 존재하지 않음을 보이며, 깊은 모델의 벡터 기하 안에 구문 트리 전체가 암묵적으로 인코딩되어 있다는 증거로 제시한다.

## Executive Summary

- 개별 속성의 존재가 아니라 구문 트리 전체를 하나의 검사 대상으로 삼는다. 트리를 벡터 공간의 전역(global) 기하 성질로 정식화한다.
- 단어 표현에 선형 변환 $B$ 하나를 학습해, 변환 공간의 제곱 거리가 트리 경로 거리를, 제곱 노름이 트리 깊이를 근사하도록 맞춘다.
- 프로브는 선형(저용량)이고 트리를 입력·감독 신호로 받지 않는다. 표현이 이미 트리 거리를 선형으로 담고 있어야만 높은 점수가 나온다.
- ELMo와 BERT에서 그런 변환이 존재한다(UUAS 최대 82.5, 거리 Spearman 최대 0.87). 위치·문맥 정보가 없거나 무작위인 베이스라인은 크게 뒤진다.
- 구문을 인코딩하는 데 필요한 선형 변환의 rank는 낮다. $k \approx 64$–$128$ 이후로는 이득이 사라지고, 세 모델이 대략 같은 rank를 요구한다.
- 프로브는 표현에서 트리가 선형으로 "읽힌다"는 사실만 보인다. 모델이 그 정보를 실제로 계산·사용한다는 것까지 보이지는 않으며, 라벨·방향까지 복원하지도 않는다.

**TL;DR**

- Structural probe는 단어 표현에 선형 변환 $B$ 하나만 학습해, 변환 공간의 제곱 거리가 구문 트리의 단어 간 거리를, 제곱 노름이 트리 깊이를 근사하는지 검사하는 방법이다.
- Structural probe는 PTB WSJ에서 BERT-large가 UUAS 82.5·거리 Spearman 0.87을 기록해 위치·문맥이 없는 베이스라인(ELMo0 UUAS 26.8)을 크게 앞서며, 구문 트리가 저차원(rank 약 64–128) 선형 부분공간에 인코딩됨을 보인다.
- Structural probe는 표현이 구문 트리를 선형으로 담는지 엄격히 검사할 때 유리하지만, 이는 정보가 "읽힌다"는 존재·가독성 주장일 뿐 모델이 그 구문을 실제로 계산·사용하거나 라벨·방향까지 복원함을 보이지는 않는다.

## Table of Contents

1. 문제의식: 구문 트리 전체를 검사한다
2. 방법: 구조적 프로브의 정의
3. 실험 설계
4. 결과
5. 논문의 주장과 근거 범위
6. 학술적 한계와 비평
7. 연구적 위치와 후속
결론

## 1. 문제의식: 구문 트리 전체를 검사한다

Probing은 고정된 표현에서 관심 있는 언어 지식을 얼마나 읽어낼 수 있는지 검사하는 방법이다. 품사(Belinkov et al., 2017), 형태(Peters et al., 2018a) 같은 개별 속성에 대해서는 지도학습 프로브가 높은 정확도를 보였다. 그러나 이런 검사는 각 속성이 "있는가"만 묻는다. 깊은 문맥 모델이 문장의 의존 구조를 트리 전체로서 벡터 공간에 담고 있는지는 열려 있는 질문이었다.

이 논문은 그 질문을 엄격한 형태로 다시 세운다. 그래프를 벡터 공간에 임베딩한다는 것은, 각 노드에 벡터를 배정해 벡터 공간의 기하(거리와 노름)가 그래프의 기하를 근사하도록 하는 일이다(Hamilton et al., 2017). parse tree $T$에서 두 단어 $u, v$의 거리 $d_T(u,v)$는 둘을 잇는 경로의 간선 수다. 거리가 트리 구조를 복원한다. 거리 1인 노드가 이웃이고, 노름(깊이)이 큰 쪽이 자식이다. 거리는 위계적 행동도 설명한다. 예를 들어 attractor가 있는 주어–동사 수 일치(Linzen et al., 2016)에서 동사 V는 트리상 주어 S에 가깝고, 사이에 낀 명사들과는 멀다. 저자들은 구문을 uncontextualized 임베딩에서 유추가 벡터 오프셋으로 인코딩되는 것(Mikolov et al., 2013)과 비슷한, 표현 공간의 전역 기하 성질로 본다.

핵심 가설은 이렇다. 신경망이 parse tree를 임베딩한다면, 표현 공간 전체를 쓰지는 않을 것이다(다른 정보도 담아야 하므로). 따라서 표현 공간의 어떤 선형 변환된 부분에 트리 거리가 인코딩되어 있으리라는 것이다.

## 2. 방법: 구조적 프로브의 정의

### 2.1 거리 프로브

모델 $\mathcal{M}$이 문장 $\ell$의 단어열 $w_{1:n}^\ell$을 받아 표현열 $\mathbf{h}_{1:n}^\ell$을 낸다. 내적 $\mathbf{h}^T A \mathbf{h}$는 대칭 양의 준정부호(positive semi-definite) 행렬 $A \in \mathbb{S}_+^{m \times m}$로 매개된다. 동치로, $A = B^T B$를 만족하는 선형 변환 $B \in \mathbb{R}^{k \times m}$을 지정하는 것과 같다. 프로브의 매개변수는 정확히 이 행렬 $B$다. 이렇게 정의되는 제곱 거리족은 다음과 같다.

$$
d_B\bigl(\mathbf{h}_i^\ell, \mathbf{h}_j^\ell\bigr)^2
= \bigl(B(\mathbf{h}_i^\ell - \mathbf{h}_j^\ell)\bigr)^T \bigl(B(\mathbf{h}_i^\ell - \mathbf{h}_j^\ell)\bigr).
$$

$B$를 학습해, 학습 말뭉치의 모든 문장에서 모든 단어 쌍 $(w_i^\ell, w_j^\ell)$의 트리 거리를 재현하도록 한다. 경사하강으로 근사하는 목적함수는 다음과 같다.

$$
\min_B \sum_\ell \frac{1}{|s^\ell|^2}
\sum_{i,j} \bigl| d_{T^\ell}(w_i^\ell, w_j^\ell) - d_B(\mathbf{h}_i^\ell, \mathbf{h}_j^\ell)^2 \bigr|.
$$

$|s^\ell|$은 문장 길이다. 각 문장에 단어 쌍이 $|s^\ell|^2$개 있으므로 제곱으로 정규화해 문장 길이에 따른 편중을 없앤다. 손실은 예측 제곱 거리와 참 거리 사이의 절대값(L1)이다.

이 프로브는 트리 거리가 표현 공간의 전역 성질임을 검사한다. 어느 단어가 어느 단어의 head인지만이 아니라, 모든 단어 쌍이 서로의 구문 거리를 알아야 한다. 저자들은 head 대신 거리를 프로브 대상으로 삼으면 전치사 부착이나 조동사 처리 같은 임의적 결정을 피할 수 있고, 표현이 그런 세부에서는 "의견이 갈려도" 대체로 같은 전역 구조를 인코딩하게 둘 수 있다고 본다.

### 2.2 깊이(노름) 프로브

두 번째 성질은 parse depth다. 단어 $w_i$의 깊이 $\|w_i\|$는 트리에서 $w_i$와 root 사이의 간선 수다. 깊이는 단어들에 전순서를 부여하므로 노름으로 자연스럽게 표현된다. 거리 함수를 제곱 노름 $\|\mathbf{h}_i\|_B^2$로 바꾸어, 식 (1)의 자리에

$$
\|\mathbf{h}_i\|_A^2 = (B\mathbf{h}_i)^T (B\mathbf{h}_i)
$$

를 놓고 $B$가 $\|w_i\|$를 재현하도록 학습한다. 깊이가 복원되면 root(가장 얕은 단어)를 식별할 수 있고, 이웃한 두 단어 중 더 깊은 쪽이 자식이므로 간선의 방향도 얻는다. 즉 거리 프로브는 무방향 트리 위상을, 깊이 프로브는 방향을 담당한다.

### 2.3 학습과 제곱 거리 선택

모든 프로브는 예측 제곱 거리(또는 제곱 노름)와 참 거리(또는 노름) 사이의 L1 손실을 Adam으로 최소화한다. 학습률 0.001, $\beta_1 = .9$, $\beta_2 = .999$, $\epsilon = 10^{-8}$로 시작해 최대 40 epoch, 배치 크기 20으로 수렴까지 학습한다. 깊이 프로브의 손실은 문장 내 모든 예측을 합해 문장 길이로 정규화하고, 거리 프로브는 문장 길이의 제곱으로 정규화한다. 매 epoch dev 손실이 새 최솟값을 내지 못하면 optimizer를 리셋(모멘텀 폐기)하고 학습률을 0.1배로 줄인다.

저자들은 거리 프로브가 거리 척도를 정의하지만 재현은 제곱 거리로, 노름 프로브도 재현은 제곱 노름으로 한다고 밝힌다. 제곱을 쓰는 편이 참 트리 거리·노름의 정확한 스칼라 값을 맞추는 데 일관되게 유리했기 때문이다. 다만 제곱 거리는 삼각부등식을 만족하지 않으므로 유효한 거리 척도가 아니다. 인코딩되는 그래프 구조 자체는 거리와 제곱 거리가 동일하며, 학습 뒤 제곱근을 취하면 거리 척도를 회복할 수 있다.

## 3. 실험 설계

### 3.1 표현 모델과 베이스라인

표현 모델은 5.5B 단어로 사전학습된 ELMo, cased BERT-base, cased BERT-large다. 각각 $\textsc{ELMo}_K$, $\textsc{BERT}_{\textsc{base}K}$, $\textsc{BERT}_{\textsc{large}K}$로 쓰며 $K$는 은닉층 색인이다. ELMo와 BERT-large의 층은 차원 1024, BERT-base는 768이다. BERT는 subword를 쓰므로, subword 벡터를 gold Penn Treebank 토큰에 정렬해 각 토큰에 subword 표현의 평균을 배정한다. 저자들은 이 평균화가 BERT 성능의 하한을 나타낸다고 명시한다.

데이터는 Stanford Dependencies 형식(de Marneffe et al., 2006)으로 변환한 Penn Treebank WSJ(Marcus et al., 1993)의 표준 분할이며 전처리는 하지 않는다.

베이스라인은 유용한 자질을 담되 스스로 파싱하지는 못해야 하며, ELMo·BERT와의 비교 기준을 준다.

- $\textsc{Linear}$: 영어 parse tree가 좌→우 사슬을 이룬다는 가정에서 나오는 트리. 단어 위치를 인코딩하는 모델이라면 이 수준은 넘어야 한다.
- $\textsc{ELMo0}$: 문맥 정보가 없는 문자 수준 임베딩. 위치 정보조차 없으므로 트리를 전혀 찾지 못해야 한다.
- $\textsc{Decay0}$: 각 단어에 문장 내 모든 $\textsc{ELMo0}$ 임베딩의 가중 평균을 배정한다. 가중치는 선형 거리 $d$에 따라 $\tfrac{1}{2^d}$로 지수 감쇠한다.
- $\textsc{Proj0}$: $\textsc{ELMo0}$ 임베딩을 ELMo와 같은 차원(1024)의 무작위 초기화 BiLSTM 한 층으로 문맥화한다. 문맥화만으로도 강한 베이스라인이다(Conneau et al., 2018).

### 3.2 평가 지표

거리 프로브는 예측한 단어 쌍 거리로 최소 신장 트리(MST)를 만들어 gold 트리와 비교한다. UUAS(undirected unlabeled attachment score)는 무방향 간선을 맞게 놓은 비율이고, 문장부호는 표준대로 무시한다. DSpr.(distance Spearman)은 각 단어에서 참 거리와 예측 거리의 Spearman 상관을 구해 같은 길이 문장끼리 평균한 뒤, 길이 5–50에 걸쳐 매크로 평균한 값이다.

깊이 프로브는 NSpr.(norm Spearman)로 참 깊이 순서와 예측 순서의 Spearman 상관을 같은 방식으로 평균하고, root%로 root(가장 얕은 단어) 식별 정확도를 잰다. root% 역시 문장부호를 무시한다.

## 4. 결과

![구조적 프로브의 PTB WSJ 테스트셋 결과. 베이스라인(위)과 모델(아래)의 UUAS·DSpr·Root%·NSpr.](/api/blog/figures/structural-probe-tab1-results.png)

*원 논문 Table 1(p.4131)에서 crop. 출처: Hewitt & Manning (2019), ACL material, CC BY 4.0.*

수치는 test set 기준이다. 베이스라인은 $\textsc{Linear}$ 48.9 / 0.58 / 2.9 / 0.27, $\textsc{ELMo0}$ 26.8 / 0.44 / 54.3 / 0.56, $\textsc{Decay0}$ 51.7 / 0.61 / 54.3 / 0.56, $\textsc{Proj0}$ 59.8 / 0.73 / 64.4 / 0.75다(UUAS / DSpr / Root% / NSpr 순). 모델은 $\textsc{ELMo}_1$ 77.0 / 0.83 / 86.5 / 0.87, $\textsc{BERT}_{\textsc{base}7}$ 79.8 / 0.85 / 88.0 / 0.87, $\textsc{BERT}_{\textsc{large}15}$ 82.5 / 0.86 / 89.4 / 0.88, $\textsc{BERT}_{\textsc{large}16}$ 81.7 / 0.87 / 90.1 / 0.89다.

먼저 프로브가 스스로 파싱하지 못한다는 것이 확인된다. $\textsc{ELMo0}$과 $\textsc{Decay0}$은 단어의 선형 순서만 담은 우분지 트리 oracle($\textsc{Linear}$)을 실질적으로 넘지 못한다. $\textsc{Proj0}$은 $\textsc{ELMo}_1$의 표현 용량은 전부 갖되 학습은 전혀 하지 않은 무작위 문맥화인데도 베이스라인 중 가장 강하다(UUAS 59.8, DSpr 0.73). 문맥화 자체가 어느 정도 구조를 만들지만, 학습된 모델은 이를 뚜렷이 넘어선다.

![$\textsc{BERT}_{\textsc{large}16}$·$\textsc{ELMo}_1$의 예측 제곱 거리에서 얻은 최소 신장 트리와 최강 베이스라인 $\textsc{Proj0}$의 비교. 검은 간선은 gold, 파랑은 $\textsc{BERT}_{\textsc{large}16}$, 빨강은 $\textsc{ELMo}_1$, 보라는 $\textsc{Proj0}$.](/api/blog/figures/structural-probe-fig2-min-spanning-trees.png)

*원 논문 Figure 2(p.4132)에서 crop. 출처: Hewitt & Manning (2019), ACL material, CC BY 4.0.*

Figure 2는 예측 거리로 만든 MST가 ELMo와 BERT에서 의존 구조를 상당히 복원함을 보인다. 트리 오차는 대체로 선형성에서의 단순한 이탈이다. 거리 척도는 전역 개념이어서, 모든 단어 쌍이 자기 head만이 아니라 서로의 거리를 알도록 학습된다.

모델 사이에서는 $\textsc{BERT}_{\textsc{large}} > \textsc{BERT}_{\textsc{base}} > \textsc{ELMo}$가 일관되게 나타난다. 층 사이에도 뚜렷한 차이가 있어, 구문 정보는 중간 층들에서 가장 강하다. 저자들은 이 가설이 ELMo 같은 LSTM을 분석하며 세워졌는데도 self-attention 기반 BERT에 수정 없이 적용된다는 점을 짚는다.

![선형 변환의 최대 차원을 제한했을 때의 트리 복원 정확도. rank $k$가 64–128을 넘으면 이득이 사라진다.](/api/blog/figures/structural-probe-fig5-rank.png)

*원 논문 Figure 5(p.4133)에서 crop. 출처: Hewitt & Manning (2019), ACL material, CC BY 4.0.*

### 4.1 선형 변환의 rank

두 모델 모두에서 구문을 인코딩하는 데 필요한 선형 변환의 실효 rank는 놀랄 만큼 낮다. 변환 벡터 $B\mathbf{h}$가 $\mathbb{R}^k$에 놓이도록 $B \in \mathbb{R}^{k \times m}$의 $k$를 바꿔 프로브를 학습하면, $k$를 64 또는 128 이상으로 키워도 파싱 정확도는 더 오르지 않는다(Figure 5). $k$가 클수록 표현 용량 중 더 큰 몫을 구문에 쓸 수 있다는 뜻인데, 세 모델이 모두 대략 같은 rank를 요구한다. 구문이 표현 공간의 저차원 선형 부분공간에 담겨 있다는 관찰이다.

## 5. 논문의 주장과 근거 범위

논문의 주장은 존재 주장이다. 제곱 거리가 트리 거리를, 제곱 노름이 트리 깊이를 인코딩하는 선형 변환이 ELMo와 BERT에는 존재하고 베이스라인에는 존재하지 않는다. 따라서 구문 트리 전체가 깊은 모델의 벡터 기하 안에 암묵적으로, 그것도 전역 구조 성질로서 인코딩되어 있다는 것이다. 모델은 트리를 입력으로 받지도, 트리 재구성을 지도받지도 않았으므로 이는 표현 공간의 구조적 성질이며, 저자들은 이를 유추가 벡터 오프셋으로 인코딩되는 것에 비유한다.

주장의 경계도 분명하다. 첫째, 프로브는 gold 트리로 $B$를 학습하는 지도학습 프로브이므로, 정보가 "읽힌다"는 것을 보일 뿐 모델이 그 정보를 계산하거나 downstream에서 사용한다는 것을 보이지 않는다. 둘째, 거리 프로브는 무방향·무라벨 트리 위상만을, 깊이 프로브는 방향만을 복원한다. 의존 라벨은 대상이 아니며, 이는 gold 구조가 주어졌을 때 라벨을 학습하는 Tenney et al.(2019)의 과제와 상보적이다. 셋째, 저자들은 이 검사가 넓은 의미의 "구문 지식"이 아니라, 모든 단어 쌍이 서로의 구문 거리를 알고 그 정보가 벡터 공간의 전역 구조 성질이라는 매우 엄격한 개념을 겨냥한다고 명시한다.

## 6. 학술적 한계와 비평

프로브가 선형(저용량)이라는 점과 베이스라인이 크게 뒤진다는 점은 "프로브가 스스로 파싱해 높은 점수를 낸 것 아니냐"는 우려를 상당 부분 막는다. 그러나 완전히 해소하지는 않는다. $\textsc{Proj0}$은 무작위 문맥화인데도 DSpr 0.73을 내는데, 학습된 모델은 0.83–0.87이다. 거리 상관 지표에서 무작위 문맥화와 학습 모델의 간극은 크지 않다(UUAS 간극이 더 크다). 즉 어떤 지표에서는 문맥화 자체가 이미 구조 대부분을 만든다.

방법 정의에도 미세한 긴장이 있다. §2.2는 프로브가 표현 공간 위에 유효한 거리 척도(내적)를 정의한다고 제시하지만, 실제로 적합·평가하는 양은 제곱 거리이며 이는 삼각부등식을 어겨 유효한 거리 척도가 아니다. 저자들은 부록에서 이를 인정하고 그래프 구조는 동일하다고 설명하지만, "내적/거리 척도" 프레이밍과 실제 적합 대상 사이의 간극은 남는다.

측정에도 한계가 있다. BERT는 subword를 평균해 토큰에 배정하므로 보고 수치가 BERT 성능의 하한이라고 저자 스스로 밝힌다. UUAS와 root%는 문장부호를 무시하고, rank 주장은 "세 모델이 대략 같은 rank"라는 느슨한 형태로 정확한 추정치 없이 후속 과제로 남는다. Table 1은 셀마다 단일 실행으로 보이며 시드에 따른 분산은 보고되지 않는다.

저자들은 리뷰어의 지적도 옮긴다. bilinear 그래프 기반 의존 파서처럼 headedness만 프로브할 수도 있고, 어떤 종류든 깊은 신경 프로브라면 이 방법보다 높은 파싱 정확도를 낼 것이 거의 확실하다. 따라서 낮아 보이는 수치는 리더보드 경쟁의 산물이 아니라, 엄격한 가설을 약한 프로브로 검사한 결과로 읽어야 한다.

## 7. 연구적 위치와 후속

이 연구는 probing 문헌(Belinkov et al., 2017; Peters et al., 2018b; Hupkes et al., 2018)의 연장선에 있으면서, 개별 라벨의 존재가 아니라 트리 전체를 전역 기하 성질로 검사한다는 점에서 구별된다. 상당한 복잡도의 프로브로 구성 트리를 추출할 수 있는지 보는 Peters et al.(2018b)와 달리, 여기서는 선형이라는 낮은 복잡도로 더 구체적인 가설을 검사한다. gold 구조 위에서 라벨을 학습하는 Tenney et al.(2019), 문장 표현의 최대 깊이를 분류하는 Conneau et al.(2018)과도 상보적이다. 저자들이 남긴 후속은 왜 제곱 거리가 일반 거리보다 잘 맞는가, 그리고 임의의 언어 표현 위에서 다른 종류의 그래프 구조를 검사하는 프로브다.

## 결론

이 논문은 "모델이 품사를 아는가"라는 질문을, "구문 트리 전체가 하나의 선형 변환으로 읽히는 벡터 공간의 전역 기하 성질인가"라는 질문으로 다시 세운다. 답은 ELMo와 BERT에 대해 그렇다는 것이며, 그것도 의도적으로 약한 선형 프로브로, 저차원 부분공간에서 성립한다. 동시에 저자들은 이것이 존재·가독성(decodability) 주장이지 모델이 구문을 계산하거나 완전한 라벨 부착 파스를 복원한다는 주장이 아님을 분명히 한다.

## References

Belinkov, Y., Durrani, N., Dalvi, F., Sajjad, H., & Glass, J. (2017). What do neural machine translation models learn about morphology? In *Proceedings of the 55th Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)* (pp. 861–872). Association for Computational Linguistics. https://doi.org/10.18653/v1/P17-1080

Conneau, A., Kruszewski, G., Lample, G., Barrault, L., & Baroni, M. (2018). What you can cram into a single \$&!#\* vector: Probing sentence embeddings for linguistic properties. In *Proceedings of the 56th Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)* (pp. 2126–2136). Association for Computational Linguistics. https://doi.org/10.18653/v1/P18-1198

Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2019). BERT: Pre-training of deep bidirectional transformers for language understanding. In *Proceedings of the 2019 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies, Volume 1* (pp. 4171–4186). Association for Computational Linguistics. https://doi.org/10.18653/v1/N19-1423

Hamilton, W. L., Ying, R., & Leskovec, J. (2017). Representation learning on graphs: Methods and applications. *IEEE Data Engineering Bulletin, 40*(3), 52–74. https://arxiv.org/abs/1709.05584

Hewitt, J., & Manning, C. D. (2019). A structural probe for finding syntax in word representations. In *Proceedings of the 2019 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies, Volume 1 (Long and Short Papers)* (pp. 4129–4138). Association for Computational Linguistics. https://doi.org/10.18653/v1/N19-1419

Linzen, T., Dupoux, E., & Goldberg, Y. (2016). Assessing the ability of LSTMs to learn syntax-sensitive dependencies. *Transactions of the Association for Computational Linguistics, 4*, 521–535. https://doi.org/10.1162/tacl_a_00115

Marcus, M. P., Marcinkiewicz, M. A., & Santorini, B. (1993). Building a large annotated corpus of English: The Penn Treebank. *Computational Linguistics, 19*(2), 313–330.

de Marneffe, M.-C., MacCartney, B., & Manning, C. D. (2006). Generating typed dependency parses from phrase structure parses. In *Proceedings of the Fifth International Conference on Language Resources and Evaluation (LREC 2006)* (pp. 449–454). European Language Resources Association.

Mikolov, T., Sutskever, I., Chen, K., Corrado, G. S., & Dean, J. (2013). Distributed representations of words and phrases and their compositionality. In *Advances in Neural Information Processing Systems 26* (pp. 3111–3119). Curran Associates.

Peters, M. E., Neumann, M., Iyyer, M., Gardner, M., Clark, C., Lee, K., & Zettlemoyer, L. (2018a). Deep contextualized word representations. In *Proceedings of the 2018 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies, Volume 1 (Long Papers)* (pp. 2227–2237). Association for Computational Linguistics. https://doi.org/10.18653/v1/N18-1202

Peters, M. E., Neumann, M., Zettlemoyer, L., & Yih, W. (2018b). Dissecting contextual word embeddings: Architecture and representation. In *Proceedings of the 2018 Conference on Empirical Methods in Natural Language Processing* (pp. 1499–1509). Association for Computational Linguistics. https://doi.org/10.18653/v1/D18-1179

Tenney, I., Xia, P., Chen, B., Wang, A., Poliak, A., McCoy, R. T., Kim, N., Van Durme, B., Bowman, S. R., Das, D., & Pavlick, E. (2019). What do you learn from context? Probing for sentence structure in contextualized word representations. In *International Conference on Learning Representations*. https://openreview.net/forum?id=SJzSgnRcKX
