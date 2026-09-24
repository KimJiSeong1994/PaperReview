# How Contextual are Contextualized Word Representations? Comparing the Geometry of BERT, ELMo, and GPT-2 Embeddings

**Paper:** Kawin Ethayarajh (2019). "How Contextual are Contextualized Word Representations? Comparing the Geometry of BERT, ELMo, and GPT-2 Embeddings". https://aclanthology.org/D19-1006/ · https://doi.org/10.18653/v1/D19-1006 · arXiv:1909.00512

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | BERT·ELMo·GPT-2 같은 문맥화 모델은 각 단어에 무한히 많은 문맥특화 표현을 주는가, 아니면 유한한 몇 개의 단어 의미 표현 중 하나를 배정할 뿐인가? 후자라면 문맥화 임베딩은 "정적 임베딩 + 의미 선택"으로 환원된다. |
| 핵심 기여 | 문맥화 임베딩의 기하를 처음으로 정량화하는 세 측도(self-similarity, intra-sentence similarity, maximum explainable variance)를 정의하고, 이방성 보정으로 코사인 오판을 교정해 "문맥화 임베딩은 단일 정적 벡터가 설명하는 문맥별 분산이 제한적이다"를 보인다. |
| 방법적 결과 | self-similarity는 한 단어가 서로 다른 문맥에서 받는 벡터 간 평균 코사인(Eq. 1), intra-sentence similarity는 문장 안 단어 벡터와 문장 평균 벡터의 평균 코사인, MEV는 문맥별 벡터 첫 주성분의 분산 비율(Eq. 3, 정적 벡터 대체의 상한)이다. 층별 이방성 기준선(코사인 측도는 무작위 단어쌍 평균 코사인, MEV는 무작위 벡터 첫 주성분 분산)을 빼서 보정하며(Eq. 4), 기준선·측도 모두 층마다 무작위 표본 1,000개로 추정한다. ELMo(2층)·BERT-base(12층)·GPT-2(12층)를 입력층(layer 0) 포함 층별로 비교한다. |
| 실험 결과 | 이방성 보정 후 세 모델 모두 상위층일수록 self-similarity가 낮아져 문맥특화가 커지고, 어떤 모델의 어떤 층에서도 정적 벡터 하나가 문맥별 분산의 5%를 넘게 설명하지 못한다. self-similarity 최저(문맥 최민감) 단어는 다의어가 아니라 불용어다(ELMo에서 "and"·"of"·"'s"·"the"·"to"). intra-sentence similarity는 모델마다 갈린다(ELMo 상위층 수렴, BERT 발산하되 무작위보다 가까움, GPT-2 무작위 수준). |
| 핵심 한계 | 코사인에 기대는 두 측도(self-/intra-sentence similarity)의 대상 공간이 극단적으로 이방적인데 보정은 스칼라 하나를 빼는 데 그쳐 공간 왜곡을 원리적으로 되돌리지 못한다(특히 GPT-2 마지막 층은 기준선이 거의 1). MEV 5%는 상한일 뿐 정적 임베딩의 무용 증명이 아니다(하위층에서 뽑은 정적 임베딩이 일부 벤치마크에서 GloVe·fastText를 이긴다). 구조가 다른 세 모델과 SemEval 한 종류 데이터라 아키텍처 영향 분리와 일반화가 열려 있다. |

**TL;DR** — (1) **Ethayarajh (2019)**는 BERT·ELMo·GPT-2의 문맥화 임베딩을 self-similarity·intra-sentence similarity·MEV 세 가지 기하 측도로 해부해, 문맥화 임베딩이 문맥마다 실제로 다른 표현이며 단일 정적 벡터가 설명하는 문맥별 분산이 5% 미만임을 보인 논문이다. (2) 문맥화 벡터가 좁은 원뿔에 몰린 이방성 탓에 무작위 두 단어의 코사인도 높게(GPT-2 마지막 층은 거의 1) 나오므로 층별 기준선을 빼서 보정하며, 보정 후 상위층일수록 문맥특화가 커지고 어떤 층에서도 정적 벡터 하나가 문맥별 분산의 5%를 넘게 설명하지 못한다. (3) 변이를 이끄는 것은 단어의 다의성이 아니라 문맥의 다양성이어서 다의어가 아닌 불용어가 가장 문맥에 민감하지만, 코사인 두 측도의 스칼라 보정과 MEV 상한 해석, 구조가 다른 세 모델·SemEval 한 종류 데이터라는 한계는 감수해야 한다.

---

## 목차

1. 서론
2. 방법: 세 측도와 이방성 보정
3. 실험 설정
4. 실험 결과
5. 결과의 해석 범위
6. 방법적 한계와 확장
7. 결론

## 1. 서론

### 1.1 연구 배경

word2vec·GloVe 같은 정적 임베딩은 한 단어에 벡터 하나를 고정 배정한다. ELMo·BERT·GPT-2 같은 문맥화 임베딩은 같은 단어라도 문장이 다르면 다른 벡터를 내준다. 이 전환이 여러 과제의 성능을 크게 끌어올렸다. 그런데 그 벡터가 실제로 어떻게 생겼는지, 문맥화가 기하학적으로 무엇을 하는지는 덜 밝혀져 있었다.

### 1.2 핵심 질문

논문이 던지는 질문은 이렇다. 문맥화 모델은 각 단어에 무한히 많은 문맥특화 표현을 주는가, 아니면 유한한 몇 개의 단어 의미 표현 중 하나를 배정하는가. 후자라면 문맥화 임베딩은 결국 "정적 임베딩에 의미 선택을 더한 것"으로 환원된다. 전자라면 환원되지 않는다. 논문은 이 질문을 벡터 공간의 기하로 판정하려 한다.

### 1.3 학술적 위치

논문은 정적 임베딩(word2vec·GloVe·fastText)을 대립항으로 세우고, 세 문맥화 모델(ELMo·BERT·GPT-2)을 층별로 해부한다. 임베딩 공간의 기하를 다룬 선행 연구, 특히 정적 임베딩의 이방성과 그 보정이 성능을 올린다는 연구(Mu 등, Arora 등)를 딛고, 문맥화 임베딩에서는 그 이방성이 훨씬 극단적임을 보인다. probing 계열 연구(Tenney, Hewitt & Manning 등)가 문맥화 표현이 무엇을 담는지를 물었다면, 이 논문은 그 표현이 공간에서 어떻게 배치되는지를 묻는다.

---

## 2. 방법: 세 측도와 이방성 보정

### 세 개의 측도

문맥화 함수를 $f_\ell(s, i)$로 쓴다. 문장 $s$의 $i$번째 토큰을 모델 $f$의 $\ell$번째 층 벡터로 보내는 함수다. 한 단어 $w$는 여러 문장의 여러 위치에 나타난다. 이 위에서 세 측도를 정의한다.

**Self-Similarity**(Def. 1)는 한 단어가 서로 다른 문맥에서 받는 벡터들 사이의 평균 코사인 유사도다.

$$\text{SelfSim}_\ell(w) = \frac{1}{n^2 - n} \sum_j \sum_{k \neq j} \cos\!\big(f_\ell(s_j, i_j),\, f_\ell(s_k, i_k)\big) \quad (\text{Eq. 1})$$

여기서 $n$은 단어 $w$가 나타나는 문맥의 수이고, 분모 $n^2-n$은 자기 자신과의 쌍을 뺀 개수다. 값이 1이면 단어가 모든 문맥에서 같은 벡터를 받는다는 뜻으로 문맥화가 전혀 없는 것이고, 낮을수록 문맥에 따라 벡터가 갈린다는 뜻이다.

**Intra-Sentence Similarity**(Def. 2)는 한 문장 안 각 단어 벡터와 그 문장의 평균 벡터 사이의 평균 코사인 유사도다. 한 문장의 단어들이 벡터 공간에서 서로 얼마나 뭉치는지를 잰다. Self-Similarity가 단어 수준 측도라면 이것은 문장 수준 측도다.

**Maximum Explainable Variance**(Def. 3)는 한 단어의 문맥별 벡터들에서 첫 주성분이 설명하는 분산의 비율이다.

$$\text{MEV}_\ell(w) = \frac{\sigma_1^2}{\sum_i \sigma_i^2} \quad (\text{Eq. 3})$$

한 단어의 문맥별 벡터 전체를 정적 벡터 하나로 대체한다면, 그 하나는 분산을 가장 많이 담는 첫 주성분 방향이 최선이다. 그래서 MEV는 정적 임베딩이 문맥별 표현을 대체할 수 있는 정도의 상한이 된다.

### 이방성이라는 함정

세 측도 중 둘, Self-Similarity와 Intra-Sentence Similarity는 코사인 유사도에 기댄다. 그런데 코사인을 그대로 믿기 어려운 사정이 있다. 문맥화 벡터들이 방향적으로 균일하게 퍼져 있지 않고 좁은 원뿔 안에 몰려 있다. 이것을 이방성이라 한다. 벡터들이 한 방향으로 쏠려 있으면, 아무 관계 없는 두 단어를 무작위로 뽑아도 코사인 유사도가 높게 나온다.

![층별 이방성](/api/blog/figures/ethayarajh-fig1-anisotropy.png)

*무작위로 뽑은 두 단어 벡터의 평균 코사인 유사도를 층별로 그린 것(원논문 Figure 1). 값이 0에서 멀수록 이방적이다. 세 모델 모두 대체로 상위층일수록 이방적이고(BERT는 마지막 층에서 오히려 조금 낮아지는 예외가 있다), GPT-2 마지막 층은 무작위 두 단어의 코사인이 거의 1에 이른다. ELMo 입력층(layer 0)만 예외로 등방에 가까운데, 문맥을 안 쓰는 문자 단위 임베딩이기 때문이다.*

논문은 이 이방성을 기준선으로 정량화한다. Self-Similarity와 Intra-Sentence Similarity는 서로 다른 문맥에서 무작위로 뽑은 두 단어 벡터의 평균 코사인 유사도를 그 층의 기준선으로 쓴다(§3.4). MEV는 코사인이 아니라 분산 비율이라, 무작위 단어 벡터들의 첫 주성분이 설명하는 분산 비율을 따로 기준선으로 쓴다. 각 측도에서 자기 기준선을 빼서 보정한다(Eq. 4). 왜 빼야 하는지는 예로 분명해진다. 공간이 완전히 등방이라면 Self-Similarity 0.95는 문맥화가 약하다는 뜻이지만, 무작위 두 단어의 코사인이 0.99일 만큼 이방적인 공간에서라면 같은 0.95가 오히려 문맥화가 강하다는 뜻이다. 절대값이 아니라 기준선 대비 상대값으로 봐야 한다. 기준선과 측도 모두 층마다 무작위 표본 1,000개로 추정하고, 이후 논문의 측도는 별도 표시가 없으면 전부 이 보정판을 가리킨다.

---

## 3. 실험 설정

세 모델을 층별로 비교한다. ELMo(은닉 2층), BERT-base cased(12층), GPT-2(12층)다. 세 모델 모두 문맥화 이전의 입력층을 layer 0으로 함께 넣는다. 입력층은 문맥을 반영하지 않으니 문맥화 이전과 이후를 대조하는 내부 기준선이 된다.

데이터는 SemEval의 의미 문장 유사도 과제(2012–2016)에서 온 문장들이다(§3.2). 같은 단어가 여러 문맥에 나타나는 문장을 골라야 측도가 성립하므로, 고유 문맥이 5개 미만인 단어는 분석에서 뺀다.

---

## 4. 실험 결과

### 층이 높을수록 문맥에 민감해진다

Self-Similarity를 층별로 보면, 세 모델 모두 층이 높을수록 값이 낮아진다(§4.2). 상위층으로 갈수록 같은 단어가 문맥에 따라 더 다른 벡터를 받는다는 뜻이다.

![층별 self-similarity](/api/blog/figures/ethayarajh-fig2-self-similarity.png)

*이방성을 보정한 평균 self-similarity를 층별로 그린 것(원논문 Figure 2). 세 모델 모두 상위층으로 갈수록 낮아진다. 낮을수록 같은 단어의 문맥별 벡터가 서로 갈린다는 뜻이라, 상위층일수록 문맥특화가 크다.* 이미지 분류에서 하위층이 일반적 특징을, 상위층이 범주 특화 특징을 잡는 것과 결이 비슷하다. 상위층이 각 모델의 언어모델 목적(다음 단어 또는 마스킹 토큰 예측)에 맞춰 문맥에 특화된 표현을 학습한 결과로 볼 수 있다.

### 정적 벡터로는 5%도 못 담는다

가장 강한 결과는 MEV에서 나온다(원논문 Figure 4). 세 모델의 어떤 층에서도, 정적 벡터 하나가 한 단어의 문맥별 벡터 분산의 5%를 넘게 설명하지 못한다(§4.3). 이방성을 보정한 뒤의 값이다. 문맥별 표현을 정적 벡터 하나로 대체하려는 시도의 상한이 5% 미만이라는 것이니, 문맥화 임베딩은 "정적 벡터에 잡음을 더한 것"이 아니다. 서론의 질문에 대한 답이다. MEV는 첫 주성분 하나가 설명하는 분산을 측정하므로, 이 결과가 여러 의미 벡터의 유한한 집합으로 표현하는 모든 가능성까지 배제하는 것은 아니다.

한 가지 짚어 둘 것이 있다. GPT-2만은 보정 전 MEV가 층 2에서 11까지 평균 30% 정도로 무시할 수 없이 크다. 극단적 이방성 때문이다. 이 30%가 보정 후 5% 미만으로 떨어지므로, 적어도 GPT-2에서는 이 결론이 이방성 보정에 크게 기댄다. BERT와 ELMo는 보정 전에도 MEV가 이미 5% 미만이라 보정 의존도가 작다.

### 불용어가 가장 문맥에 민감하다

Self-Similarity가 가장 낮은 단어들, 즉 문맥에 가장 민감한 단어들은 불용어다. ELMo에서 self-similarity가 최저인 단어는 "and", "of", "'s", "the", "to"다(§4.2). 이들은 뜻이 여러 개인 다의어가 아니다. 그런데도 문맥화가 가장 심하다. 논문은 여기서 변이의 원인을 다시 읽는다. 단어의 내재적 다의성이 아니라 그 단어가 등장하는 문맥의 다양성이 표현 변이를 이끈다는 것이다.

### 문장 안에서의 행동은 모델마다 다르다

Intra-Sentence Similarity는 모델마다 갈린다(§4.2). ELMo에서는 상위층으로 갈수록 한 문장의 단어들이 서로 더 비슷해진다. 같은 문장을 공유하는 단어들이 같은 방향으로 특화되는 것이다. BERT에서는 반대로 상위층에서 서로 멀어지지만, 그래도 무작위 두 단어보다는 가깝다. 한 문장이 단어 의미에 정보를 주되, 같은 문장에 있다고 두 단어가 꼭 비슷한 뜻이 되지는 않는다는, 더 미묘한 문맥화다. GPT-2에서는 문장 안 유사도가 무작위 수준과 구분되지 않는다.

### 정적 임베딩을 문맥화 모델에서 뽑아 쓰기

논문은 문맥화 모델의 하위층에서 정적 임베딩을 뽑아 표준 유사도 벤치마크에 붙여 본다(Table 1). BERT 첫 층의 주성분 기반 정적 임베딩이 SimLex999와 RW에서는 GloVe·fastText를 모두 앞선다. MEN에서는 둘 다에 뒤지고, WS353에서는 GloVe는 앞서지만 fastText에는 뒤진다. 정적 임베딩을 문맥화 모델에서 값싸게 뽑아 쓸 여지는 있으나 전면적 우위는 아니다.

---

## 5. 결과의 해석 범위

### 5.1 코사인이라는 도구와 이방적 공간이라는 대상

세 측도 중 코사인에 기대는 두 측도, Self-Similarity와 Intra-Sentence Similarity에는 도구와 대상의 충돌이 있다. 이 논문의 핵심 발견 자체가 그 코사인을 신뢰하기 어려운 공간이라는 것이기 때문이다. 저자의 보정은 무작위 단어쌍의 평균 코사인이라는 스칼라 하나를 빼는 것이라, 공간 전체가 뒤틀린 방식을 되돌리지는 못한다. 특히 GPT-2 마지막 층처럼 기준선이 거의 1인 경우, 모든 코사인이 1 근처로 압축돼 있어 기준선을 빼고 남는 미세한 차이의 신호 대 잡음비가 낮다. 다만 헤드라인 결과인 MEV는 코사인이 아니라 분산 비율이고 자기 기준선으로 보정되므로 이 비판의 사거리 밖이다. 스칼라 감산이 원리적 보정은 아니라는 점은 코사인 두 측도에 한정된 주의다.

### 5.2 MEV는 상한이지 정적 임베딩의 무용 증명이 아니다

MEV 5%는 정적 임베딩이 도달할 수 있는 최선의 상한이다. 실제로 쓰는 GloVe 같은 벡터가 그 상한을 실현하는 최적 벡터와 비슷하다는 보장은 없다고 저자도 인정한다. 더 중요한 것은, 이 5%가 분산 설명량에 대한 기하학적 진술이지 정적 임베딩이 쓸모없다는 뜻은 아니라는 점이다. 논문 자신이 문맥화 모델 하위층에서 뽑은 정적 임베딩이 일부 벤치마크에서 GloVe·fastText를 이긴다고 보고한다. "분산을 못 담는다"와 "쓸모없다"는 다른 이야기다.

### 5.3 모델 세 개, 데이터 한 종류

층별 결론은 구조가 서로 다른 세 모델에서 나온다. ELMo는 2층 LSTM이고 BERT·GPT-2는 12층 트랜스포머라, "층 인덱스"를 세 모델에 걸쳐 같은 축으로 비교하기 어렵다. 표본이 세 모델뿐이라 아키텍처의 영향을 분리할 수도 없다. 저자 자신도 문장 안 유사도의 모델 간 차이를 아키텍처로 귀속할 수 없다며 후속 과제로 남긴다. 데이터도 SemEval 문장 유사도라는 한 종류에 국한되고 고유 문맥 5개 미만 단어를 빼서, 결론이 다른 코퍼스로 얼마나 일반화될지는 열려 있다. 불용어가 문맥 다양성 때문에 변이가 크다는 해석도 다의성을 따로 통제해 잰 것이 아니라, 불용어 관찰에 기댄 정성적 추론이다.

---

## 6. 방법적 한계와 확장

### 6.1 논문이 남긴 것

이 논문의 기여는 문맥화 임베딩의 기하를 처음으로 정량화한 데 있다. 세 개의 단순한 측도와 이방성 보정만으로 "문맥화 임베딩은 정적 벡터로 환원되지 않는다"를 보였고, 상위층일수록 문맥특화가 커진다는 층별 구조를 드러냈다. 특히 문맥화 벡터가 극단적으로 이방적이라는 발견은, 문맥화 표현으로 코사인 유사도를 잴 때 기준선 보정이 필요함을 보인 실용적 경고다.

### 6.2 스칼라 보정의 한계와 이방성의 정체

논문은 이방성이 문맥화의 내재적 성질이거나 적어도 부산물이라고 본다. 왜 문맥화가 벡터를 좁은 원뿔로 밀어 넣는지, 그 이방성이 표현의 유용성에 도움이 되는지 해가 되는지는 이 논문이 답하지 않는다. 저자는 언어모델 목적함수에 이방성 페널티를 더하는 것을 후속 방향으로 제안한다. 스칼라 기준선 감산 대신 화이트닝 같은 공간 수준 보정을 쓰면 측도가 어떻게 달라지는지도 열린 질문이다.

### 6.3 서브워드 집계와 재현성

BERT나 GPT-2에서 한 단어가 여러 서브워드로 쪼개질 때 그 조각들을 어떻게 한 단어 벡터로 합치는지가 본문에 명시되지 않는다. 첫 토큰을 쓰는지 평균하는지에 따라 self-similarity와 MEV 값이 달라질 수 있어, 재현과 모델 간 비교에 빈칸이 남는다. 기준선과 측도를 모두 무작위 1,000개 표본으로 추정하는 것도, 기준선이 거의 1인 상위층에서는 표본 잡음이 보정값에 크게 실릴 수 있다.

---

## 7. 결론

Ethayarajh의 이 논문은 문맥화 임베딩을 기하로 열어 본다. 세 개의 기하 측도와 이방성 보정으로, 문맥화 임베딩이 문맥마다 실제로 다른 표현임을 보였다. 상위층일수록 문맥특화가 커지고, 정적 벡터 하나로는 문맥별 분산의 5%도 못 담으며, 변이를 이끄는 것은 다의성이 아니라 문맥의 다양성이었다. 문맥화가 왜 성능을 올렸는지에 대한 기하학적 설명이다.

동시에 이 결론들은 자기 도구의 한계 위에 서 있다. 세 측도 중 둘이 코사인인데 그 공간이 극단적으로 이방적이고, 그 두 측도의 보정은 스칼라 하나를 빼는 데 그친다. MEV는 상한일 뿐이라 정적 임베딩의 무용을 증명하지 않고, 층별 결론은 구조가 다른 세 모델에서 나온다. 방법을 이해하려는 독자에게 이 논문은 "문맥화 임베딩이 어떻게 생겼는가"는 선명한 그림으로, "그 기하를 코사인으로 얼마나 믿을 수 있는가"는 스스로 열어 둔 물음으로 남긴다.

---

## References

- Arora, S., Li, Y., Liang, Y., Ma, T., & Risteski, A. (2016). A latent variable model approach to PMI-based word embeddings. *Transactions of the Association for Computational Linguistics, 4*, 385–399. ([PDF 보기](/paper-viewer?title=A+latent+variable+model+approach+to+PMI-based+word+embeddings&source=blog-reference&authors=Sanjeev+Arora%3BYuanzhi+Li%3BYingyu+Liang%3BTengyu+Ma%3BAndrej+Risteski&year=2016&arxiv_id=1502.03520&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1502.03520.pdf))
- Bojanowski, P., Grave, E., Joulin, A., & Mikolov, T. (2017). Enriching word vectors with subword information. *Transactions of the Association for Computational Linguistics, 5*, 135–146. ([PDF 보기](/paper-viewer?title=Enriching+word+vectors+with+subword+information&source=blog-reference&authors=Piotr+Bojanowski%3BEdouard+Grave%3BArmand+Joulin%3BTomas+Mikolov&year=2017&arxiv_id=1607.04606&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1607.04606.pdf))
- Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2019). BERT: Pre-training of deep bidirectional transformers for language understanding. In *Proceedings of NAACL-HLT 2019* (pp. 4171–4186). ([PDF 보기](/paper-viewer?title=BERT%3A+Pre-training+of+deep+bidirectional+transformers+for+language+understanding&source=blog-reference&authors=Jacob+Devlin%3BMing-Wei+Chang%3BKenton+Lee%3BKristina+Toutanova&year=2019&arxiv_id=1810.04805&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1810.04805.pdf))
- Ethayarajh, K. (2019). How contextual are contextualized word representations? Comparing the geometry of BERT, ELMo, and GPT-2 embeddings. In *Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th International Joint Conference on Natural Language Processing (EMNLP-IJCNLP)* (pp. 55–65). https://aclanthology.org/D19-1006/ ([PDF 보기](/paper-viewer?title=How+contextual+are+contextualized+word+representations%3F+Comparing+the+geometry+of+BERT%2C+ELMo%2C+and+GPT-2+embeddings&source=blog-reference&authors=Kawin+Ethayarajh&year=2019&arxiv_id=1909.00512&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1909.00512.pdf))
- Hewitt, J., & Manning, C. D. (2019). A structural probe for finding syntax in word representations. In *Proceedings of NAACL-HLT 2019* (pp. 4129–4138). ([PDF 보기](/paper-viewer?title=A+structural+probe+for+finding+syntax+in+word+representations&source=blog-reference&authors=John+Hewitt%3BChristopher+D.+Manning&year=2019&doi=10.18653%2Fv1%2FN19-1419&url=https%3A%2F%2Fdoi.org%2F10.18653%2Fv1%2FN19-1419))
- Mikolov, T., Chen, K., Corrado, G., & Dean, J. (2013). Efficient estimation of word representations in vector space. In *Workshop Track Proceedings of ICLR 2013*. ([PDF 보기](/paper-viewer?title=Efficient+estimation+of+word+representations+in+vector+space&source=blog-reference&authors=Tomas+Mikolov%3BKai+Chen%3BGreg+Corrado%3BJeffrey+Dean&year=2013&arxiv_id=1301.3781&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1301.3781.pdf))
- Mu, J., & Viswanath, P. (2018). All-but-the-top: Simple and effective postprocessing for word representations. In *International Conference on Learning Representations (ICLR 2018)*. ([PDF 보기](/paper-viewer?title=All-but-the-top%3A+Simple+and+effective+postprocessing+for+word+representations&source=blog-reference&authors=Jiaqi+Mu%3BPramod+Viswanath&year=2018&arxiv_id=1702.01417&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1702.01417.pdf))
- Pennington, J., Socher, R., & Manning, C. D. (2014). GloVe: Global vectors for word representation. In *Proceedings of the 2014 Conference on Empirical Methods in Natural Language Processing (EMNLP)* (pp. 1532–1543). ([PDF 보기](/paper-viewer?title=GloVe%3A+Global+Vectors+for+Word+Representation&source=blog-reference&authors=Jeffrey+Pennington%3BRichard+Socher%3BChristopher+D.+Manning&year=2014&doi=10.3115%2Fv1%2FD14-1162&url=https%3A%2F%2Fdoi.org%2F10.3115%2Fv1%2FD14-1162))
- Peters, M. E., Neumann, M., Iyyer, M., Gardner, M., Clark, C., Lee, K., & Zettlemoyer, L. (2018). Deep contextualized word representations. In *Proceedings of NAACL-HLT 2018* (pp. 2227–2237). ([PDF 보기](/paper-viewer?title=Deep+contextualized+word+representations&source=blog-reference&authors=Matthew+E.+Peters%3BMark+Neumann%3BMohit+Iyyer%3BMatt+Gardner%3BChristopher+Clark%3BKenton+Lee%3BLuke+Zettlemoyer&year=2018&arxiv_id=1802.05365&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1802.05365.pdf))
- Radford, A., Wu, J., Child, R., Luan, D., Amodei, D., & Sutskever, I. (2019). Language models are unsupervised multitask learners. *OpenAI Technical Report*.
- Tenney, I., Das, D., & Pavlick, E. (2019). BERT rediscovers the classical NLP pipeline. In *Proceedings of the 57th Annual Meeting of the Association for Computational Linguistics* (pp. 4593–4601). ([PDF 보기](/paper-viewer?title=BERT+rediscovers+the+classical+NLP+pipeline&source=blog-reference&authors=Ian+Tenney%3BDipanjan+Das%3BEllie+Pavlick&year=2019&arxiv_id=1905.05950&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1905.05950.pdf))
