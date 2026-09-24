# Dynamic Contextualized Word Embeddings

**Paper:** Hofmann, Valentin; Pierrehumbert, Janet B.; Schütze, Hinrich. (2021). "Dynamic Contextualized Word Embeddings." *Proceedings of the 59th Annual Meeting of the Association for Computational Linguistics and the 11th International Joint Conference on Natural Language Processing (ACL-IJCNLP 2021, Long Papers)*, pp. 6970–6984. arXiv:2010.12684. https://aclanthology.org/2021.acl-long.542/

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 문맥은 보지만 시간·사회에는 고정된 문맥화 임베딩(BERT)과, 시간·사회에 따라 달라지지만 문맥은 못 보는 동적 워드 임베딩을, BERT의 문맥화 능력을 해치지 않으면서 하나의 표현으로 결합할 수 있는가? |
| 핵심 기여 | BERT에 단어를 넣기 전, 그 단어의 정적 입력 임베딩에 (누가·언제 썼는가)에 따른 오프셋 벡터를 더해 문맥화와 동적성을 하나의 통합 표현으로 봉합하고, 거기에 사회 축까지 결합한다(§1.3). |
| 방법적 결과 | 오프셋은 단어 타입·사회·시간만의 함수(type-level)이고, 문맥화는 그 뒤 BERT 층이 맡는다(token-level). 오프셋 생성기는 시간대마다 별도 파라미터를 갖는 그래프 어텐션 신경망(GAT)과 순방향 신경망(FFN)이며, 두 개의 가우시안 prior가 오프셋을 각각 0쪽(anchoring)과 직전 시점 쪽(random-walk)으로 당겨 안정성과 시간 평활을 부여한다. |
| 실험 결과 | 마스크 언어모델 perplexity에서 DCWE가 비동적 BERT를 유의하게 이긴 것은 8개 열 중 2개(ArXiv-Test 3.513, Reddit-Dev 9.480)뿐이고 개선폭도 각각 0.017·0.10이며, 두 열(Reddit-Test·YELP-Dev)에서는 오히려 진다. 반면 감정 분류에서는 Ciao·YELP의 Dev/Test 네 셀 모두 유의하게 앞선다(Test F1 .896/.968). |
| 핵심 한계 | 동적화가 상위 10만 빈발어에 제한돼 신조어·희귀어의 변화를 놓치고, 차별적 신규 요소인 사회 성분은 성긴 그래프(Ciao)에서 적합을 전혀 개선하지 못한다. 평활 prior가 관찰하려는 급변과 상충하며, 주 결과는 대부분 단일 실행 점추정치로 오차막대가 없다. |

**TL;DR** — (1) DCWE(Hofmann et al., ACL 2021)는 BERT에 넣기 전 단어의 정적 입력 임베딩에 시간·사회 의존 오프셋을 더해, 문맥화 임베딩과 동적 단어 임베딩을 하나의 표현으로 결합한 모델이다. (2) 마스크 언어모델 perplexity 개선은 8개 열 중 2개(ArXiv-Test 3.513, Reddit-Dev 9.480)만 유의하고 개선폭도 0.017·0.10에 그치지만, 감정 분류에서는 Ciao·YELP 네 셀 모두에서 유의하게 앞선다(Test F1 .896/.968). (3) 성능보다 "어떤 단어가 어느 집단에서 언제 흔들렸는가"를 재는 표현·분석 도구로서 가치가 있으며, 동적화가 상위 10만 빈발어에 갇히고 사회 성분이 성긴 그래프에서 무력해지는 한계는 감수해야 한다.

---

## 목차

1. 서론
2. 방법: 정적 임베딩을 문맥화 전에 흔든다
3. 실험 설정
4. 실험 결과
5. 주의해서 읽을 점
6. 방법적 한계와 확장
7. 결론

---

## 1. 서론

### 1.1 연구 배경

단어 임베딩의 역사에는 두 개의 독립된 개선 축이 있었다. 첫째 축은 문맥화다. word2vec·GloVe·fastText 같은 정적 임베딩은 한 단어에 벡터 하나를 고정 배정해 "bank(강둑/은행)"의 두 뜻을 구분하지 못했다. ELMo·BERT는 같은 단어라도 문장 안 위치와 이웃에 따라 다른 벡터를 내주어 이 문제를 풀었다. 둘째 축은 동적화다. 정적 임베딩은 시간이나 화자 집단에 대해서도 고정이라, "gay"의 의미 변화나 커뮤니티마다 다른 은어를 담지 못했다. Bamler & Mandt, Rudolph & Blei, Yao 등의 동적 워드 임베딩은 시대별로 벡터가 달라지게 만들어 시간 축을 풀었고, 화자 집단에 따른 변이는 또 다른 계보가 다뤘다.

문제는 두 축이 서로를 보지 못했다는 점이다. 문맥화 임베딩은 동적이지 않고, 동적 임베딩은 문맥화되지 않았다. DCWE는 이 빈칸을 다룬다. 게다가 동적 임베딩 대부분이 시간 아니면 사회 한 축만 다룬 것과 달리, 시간과 사회 공간을 함께 모델링하겠다고 한다.

### 1.2 핵심 질문

논문이 답하려는 질문은 이렇게 정리된다. 문맥화 임베딩에 시간·사회 의존성을 어떻게 주입할 수 있는가. 그것을 BERT의 문맥화 능력을 해치지 않으면서 할 수 있는가. 그리고 그렇게 얻은 표현으로 "어떤 단어가 어느 집단에서 언제 의미가 흔들렸는가"를 읽어낼 수 있는가.

### 1.3 학술적 위치

논문은 자신을 정확히 두 결핍의 교차점에 놓는다. §1의 이 문장이 그 자리매김을 못박는다: "dynamic contextualized word embeddings mark a departure from existing contextualized word embeddings (which are not dynamic) as well as existing dynamic word embeddings (which are not contextualized)." 정적 임베딩에는 문맥 불변과 시간·사회 불변이라는 두 결함이 있는데, 문맥화 임베딩이 앞을, 동적 임베딩이 뒤를 각각 풀었고, 본 모델이 둘을 동시에 푼다는 구도다.

시간과 사회를 함께 봐야 하는 이유는 공학이 아니라 사회언어학에서 끌어온다. 언어 혁신은 사회적 유대를 따라 공동체로 퍼진다는 Milroy·Labov·Pierrehumbert의 전통이 근거다. 시간 변화와 사회 변이가 원래 얽혀 있으니 한 모델에서 함께 다루는 게 자연스럽다는 것이다. 시간 평활을 담당하는 prior는 동적 워드 임베딩 전통(Bamler & Mandt, Rudolph & Blei)에서 물려받았다고 스스로 밝힌다.

한 가지 분명히 해둘 점이 있다. 논문은 "우리가 최초"라고 쓰지 않는다. 문맥화 임베딩을 의미 변화 탐지에 쓴 선행 계보(Giulianelli 등)가 이미 있음을 §2에서 인정한다. 신규성의 실질은 두 가지에 있다. 학습된 오프셋으로 문맥화와 동적성을 하나의 통합 표현으로 봉합한 것, 그리고 거기에 사회 축을 결합한 것이다.

---

## 2. 방법: 정적 임베딩을 문맥화 전에 흔든다

### 두 단계 설계

정적 임베딩은 문맥도 시간·사회도 못 본다. BERT는 문맥을 보지만 시간·사회를 못 본다. DCWE의 발상은 두 성질을 서로 다른 층에 분담시키는 것이다.

먼저 단어 타입 $x^{(k)}$에 대해 동적 타입-레벨 임베딩을 만든다.

$$e_{ij}^{(k)} = \tilde{e}^{(k)} + o_{ij}^{(k)} \quad (\text{Eq. 4})$$

$\tilde{e}^{(k)}$는 BERT의 사전학습 입력 임베딩으로 초기화되는 비동적 표현이고, $o_{ij}^{(k)}$는 사회 $s_i$·시간 $t_j$에 의존하는 오프셋 벡터다. 이 오프셋은 단어 타입과 (사회, 시간)에만 의존할 뿐 주변 토큰과는 무관하다. 그래서 "타입-레벨"이다.

다음으로 이 동적 임베딩을 BERT에 넣어 문맥화한다.

$$h_{ij}^{(k)} = \text{BERT}(e_{ij}^{(k)}, E_{ij}^{(<k)}, E_{ij}^{(>k)}) \quad (\text{Eq. 6})$$

정리하면 오프셋이 "누가 언제 썼는가"를 담고, BERT의 자기어텐션이 "이 문장에서 어떻게 쓰였는가"를 담는다. 어휘의미론의 핵심 의미 대 문맥 의미 구분(논문은 Paul, Geeraerts를 인용한다)을 표현 구조에 그대로 옮긴 셈이다.

![DCWE 모델 구조](/api/blog/figures/dcwe-fig2-architecture.png)

*DCWE 모델 구조(원논문 Figure 2). 아래쪽 붉은 성분이 동적 성분이다. 단어 $x^{(k)}$와 사회 그래프 노드 $s_i$·시간 $t_j$로 오프셋 $o_{ij}$를 만들어 정적 임베딩 $\tilde{e}$에 더한다. 그렇게 만든 동적 임베딩 $\tilde{e}+o$를 위쪽 BERT(파란 상자)가 문맥화해 과제 손실 $\mathcal{L}_{\text{task}}$를 계산한다.*

### 오프셋은 어떻게 만들어지나

오프셋 생성은 사회 정보를 거쳐 나온다. 사회 커뮤니티를 노드로 갖는 그래프 $G=(S,E)$를 두고, 각 노드의 초기 벡터 $\tilde{s}_i$를 node2vec으로 초기화한 뒤 시간대별 그래프 어텐션 신경망으로 인코딩한다.

$$s_{ij} = \text{GAT}_j(\tilde{s}_i, G) \quad (\text{Eq. 8})$$

그렇게 얻은 사회 벡터를 단어의 정적 임베딩과 이어붙여 시간대별 순방향 신경망에 통과시키면 오프셋이 나온다.

$$o_{ij}^{(k)} = \text{FFN}_j(\tilde{e}^{(k)} \, \| \, s_{ij}) \quad (\text{Eq. 7})$$

여기서 "시간대별"의 의미가 중요하다. 시간은 입력 특징으로 집어넣는 것이 아니라, 시간 bin $j$마다 별개의 $\text{GAT}_j$·$\text{FFN}_j$를 두는 방식으로 반영된다. 데이터의 시간 구간이 곧 별도 네트워크의 개수가 된다. ArXiv(2001–2020)는 GAT와 FFN을 20세트, Reddit(8개월)은 8세트 두는 식이라, 시간대가 많을수록 파라미터 비용도 그만큼 커진다.

### 두 개의 prior가 오프셋을 붙잡는다

시간대마다 네트워크가 따로면 오프셋이 시점 사이에서 제멋대로 튈 수 있다. 논문은 두 개의 가우시안 prior로 이를 통제한다.

**anchoring prior**는 오프셋을 0으로 당긴다.

$$o_{ij}^{(k)} \sim \mathcal{N}(0, \lambda_a^{-1} I) \quad (\text{Eq. 5})$$

핵심 어휘 상당수는 의미가 안정적이라는 가정 위에서, 동적 임베딩이 정적 임베딩으로부터 크게 벗어나지 않게 붙잡는 역할이다. 학습에서는 오프셋 크기의 제곱합 정규화 항(Eq. 11)으로 들어간다.

**random-walk prior**는 오프셋을 직전 시점 값으로 당긴다.

$$o_{ij}^{(k)} \sim \mathcal{N}(o_{i,j-1}^{(k)}, \lambda_w^{-1} I) \quad (\text{Eq. 9})$$

Ornstein-Uhlenbeck 과정으로, 연속한 시점의 오프셋을 서로 묶어 시간축을 따라 매끄럽게 변하도록 강제한다. 학습에서는 인접 오프셋 차의 제곱합(Eq. 12)이 된다. 두 prior의 차이는 목표점이다. 하나는 0으로, 다른 하나는 직전 시점 값으로 당긴다.

두 prior의 세기는 크게 다르게 설정된다. 논문은 $\lambda_a = 10^{-3} \cdot \lambda_w$로 두어 시간 평활을 앵커링보다 훨씬 강하게 건다. 결과적으로 오프셋은 0으로는 약하게, 인접 시점끼리는 강하게 묶여, 시간에 따라 부드럽게 누적 드리프트할 수 있다.

### 목적함수

전체 손실은 마스크 언어모델 손실에 두 prior 정규화 항을 더한 것이다.

$$\mathcal{L}_{\text{total}} = \mathcal{L}_{\text{task}} + \mathcal{L}_{\text{prior}_a} + \mathcal{L}_{\text{prior}_w} \quad (\text{Eq. 10})$$

$\mathcal{L}_{\text{task}}$는 BERT 위에 언어모델 헤드를 얹어 계산하는 마스크 토큰 예측 교차엔트로피다. 백본은 BERT-BASE(uncased, 768차원)이고, 오프셋 FFN은 tanh 2층(둘 다 768차원), 사회 GAT는 2층 4헤드, 사회 벡터는 50차원이다. 학습된 표현으로 의미 변동을 재는 장치는 논문 §5.3의 정성 분석에서 쓰이고, 이 리뷰에서는 4장에서 다룬다. 정적 임베딩과 동적 임베딩 사이 각의 코사인(Eq. 14)으로 오프셋 크기를 정량화하고, 여러 (사회, 시간) 맥락에 걸친 그 값의 표준편차(Eq. 15)로 "추가언어적으로 크게 흔들리는 단어"를 골라낸다.

---

## 3. 실험 설정

논문은 네 개의 데이터셋을 쓴다. 각각 언어 단위, 사회 단위, 시간 단위가 다르게 짜여 있어 방법의 일반성을 보이려는 구성이다.

| 데이터셋 | 문서 수 | 언어 단위 | 사회 단위(노드 수) | 시간 | 밀도 ρ / 평균차수 |
|---|---|---|---|---|---|
| ArXiv | 972,369 | abstract | subject class (535) | 연, 2001–2020 | .036 / 19.34 |
| Ciao | 269,807 | review | user (10,880) | 연, 2000–2011 | .002 / 18.20 |
| Reddit | 915,663 | comment | subreddit (5,728) | 월, 2019.09–2020.04 | .005 / 23.99 |
| YELP | 795,661 | review | user (5,203) | 연, 2010–2019 | .009 / 45.17 |

ArXiv에서는 사회 그래프를 저자 공유로 짠다. 두 subject class의 저자 집합 Jaccard 유사도에 임계값 0.01을 적용해 엣지를 만든다(Eq. 13). Ciao는 네 데이터셋 중 밀도(0.002)와 평균 노드 차수(18.20)가 모두 가장 낮다. 논문은 이 성긴 사회 구조를 Ciao에서 사회 성분이 무력해지는 원인으로 지목한다(4장).

평가는 세 갈래다. 첫째, 마스크 언어모델 perplexity로 동적 성분이 데이터 적합을 개선하는지 본다. 비교 대상인 CWE(contextualized word embeddings)는 DCWE에서 동적 오프셋만 제거하고 BERT-BASE 파인튜닝·MLM 헤드·학습 데이터를 똑같이 둔 절제 베이스라인이다. 두 모델 모두 BERT를 파인튜닝하므로, 표의 차이는 동적 성분만의 기여를 분리한다. 둘째, 별점 리뷰가 있는 Ciao·YELP에서 감정 분류 F1로 하류 성능을 본다(별점 3점은 버리고 4·5점을 긍정, 1·2점을 부정으로 이진화한다). 셋째, 오프셋 크기 기반으로 의미가 크게 흔들린 단어를 정성적으로 살펴본다.

---

## 4. 실험 결과

### 언어모델링: 이득은 매우 작다

마스크 언어모델 perplexity(낮을수록 좋음)를 비동적 BERT(CWE)와 비교한다. 데이터셋마다 Dev/Test 두 열이 있어 총 8개 열이다.

| | ArXiv | Ciao | Reddit | YELP |
|---|---|---|---|---|
| DCWE (Dev/Test) | 3.521 / **3.513** | 5.920 / 5.902 | **9.480** / 9.596 | 4.717 / 4.720 |
| CWE (Dev/Test) | 3.523 / 3.530 | 5.922 / 5.910 | 9.580 / 9.555 | 4.714 / 4.723 |

굵게 표시한 두 값(ArXiv-Test 3.513, Reddit-Dev 9.480)만 Wilcoxon 부호순위 검정으로 유의하다(p<.01). 나머지 여섯 열은 비유의다. (이 글은 유의한 값을 굵게 표시했다. 원논문은 유의값을 밑줄로, 열 내 최선값을 볼드로 구분하니 대조할 때 주의한다.) 유의한 경우조차 개선폭이 0.017과 0.10에 그친다(논문 외 환산으로 각각 약 0.5%·1%). 그리고 두 열에서는 DCWE가 오히려 진다. Reddit-Test(9.596 > 9.555)와 YELP-Dev(4.717 > 4.714)에서 비동적 BERT가 더 낮다. 특히 Reddit에서는 Dev의 우세가 Test에서 뒤집힌다.

### Ablation: 시간 성분이 사회보다 중요하고, 사회는 데이터가 성기면 효과가 사라진다

성분을 하나씩 빼 본다. 사회 제거(SA)는 오프셋이 단어·시간에만 의존하게 만들고, 시간 제거(TA)는 한 사회 성분을 모든 시점에 공유시킨다.

| Test perplexity | ArXiv | Ciao | Reddit | YELP |
|---|---|---|---|---|
| DCWE(전체) | 3.513 | 5.902 | 9.596 | 4.720 |
| SA(사회 제거) | 3.515 | 5.899 | 9.631 | 4.723 |
| TA(시간 제거) | 3.541 | 5.931 | 9.612 | 4.734 |

저자 요약은 "시간 제거가 사회 제거보다 손해가 크다"이다. ArXiv·Ciao·YELP에서는 TA가 SA보다 나쁘게 나와 이 진술이 성립한다. 다만 Reddit은 반대로 SA(9.631)가 TA(9.612)보다 나빠 사회 성분이 더 중요한 예외다. 더 눈에 띄는 것은 Ciao다. 사회를 뺀 SA(5.899)가 전체 모델(5.902)보다 오히려 근소하게 낫다. 논문도 "Ciao에서는 사회 성분이 데이터 적합을 전혀 개선하지 못한다"고 인정하며, 그 이유를 최저 밀도와 최저 평균 차수, 그리고 리뷰가 하나뿐인 사용자가 많다는 데서 찾는다.

반대 방향의 일관된 신호도 있다. 시간 성분을 뺀 TA는 네 데이터셋 모두에서 전체 모델보다 나쁘다(예: YELP 4.734 vs 4.720). 동적 성분이 방향으로는 일관되게 적합을 개선한다. 이 논문 안에서 동적 성분을 뒷받침하는 가장 일관된 내부 근거다. 다만 이 델타들 역시 유의성 검정 없는 단일 실행 값이다(5.3절).

### 감정 분류: 작지만 일관된 우위

여기서는 결과가 더 깔끔하다. Ciao·YELP의 Dev/Test 네 셀 모두에서 DCWE가 비동적 BERT를 McNemar 검정으로 유의하게 이긴다(p<.01).

| F1 (Dev/Test) | Ciao | YELP |
|---|---|---|
| DCWE | .894 / .896 | .969 / .968 |
| CWE | .889 / .890 | .967 / .966 |

네 셀 모두 유의하다는 점은 perplexity보다 강한 신호다. 다만 절대 마진은 0.002~0.006으로 작다. 시간·사회 정보가 감정 분류에 도움이 되지만 그 크기는 제한적이라고 읽는 게 정확하다.

### 의미 동역학: 정성 삽화에 그친다

논문은 오프셋이 큰 단어를 찾아 의미 변동의 사례로 보여준다. Reddit의 코로나 시기에서 "isolating"은 육아 서브레딧(2019.12)의 맥락과 천식 서브레딧(2020.03)의 자가격리 맥락 사이에서 크게 흔들리고, "testing"은 DIY 조명 제작 맥락(2020.04)과 코로나 검사 맥락(2020.03) 사이에서 흔들린다(Table 4). 인상적인 예시지만 단어 두 개에 그치고, 복원된 동역학이 실제 의미 변화 정답과 맞는지에 대한 정량 평가는 없다. 저자도 이 부분을 탐색적 실험으로 명시한다.

논문은 여기서 한 걸음 더 나아가, 학습된 표현으로 의미 변화가 사회 네트워크를 따라 어떻게 퍼지는지도 그려 보인다(Figure 4). ArXiv에서 "network"·"learning"의 딥러닝 의미는 컴퓨터과학·물리 커뮤니티에서 점차 번지고, Reddit에서 "mask"의 의료 의미는 2020년 3월 이후 급격히 짙어진다. 이것이 이 표현이 여는 분석 도구의 모습이다. 다만 이 역시 특정 단어를 고른 관찰적 예시이고, 복원된 확산이 실제 의미 변화와 맞는지에 대한 정량 검증은 아니다.

![사회 네트워크를 통한 의미 변화 확산](/api/blog/figures/dcwe-fig4-social-spread.png)

*학습된 오프셋으로 의미 변화가 사회 네트워크를 따라 퍼지는 과정(원논문 Figure 4). $\hat{r}$는 두 노드의 지배적 의미가 얼마나 비슷한지를 0~100으로 잰 점수다. (a) ArXiv의 "network"·"learning"(2013–2020), (b) Reddit의 "mask"·"vaccine"(2020.01–04). 노드 모양은 ArXiv의 세 subject class(컴퓨터과학=사각형·수학=삼각형·물리=원)를 나타낸다.*

---

## 5. 주의해서 읽을 점

### 5.1 perplexity가 거의 안 움직이는 데는 구조적 이유가 있다 (논문 외 비판)

동적 오프셋은 입력 어휘 중 상위 10만 빈발어에만 적용된다. perplexity의 토큰 범위를 논문이 명시하지는 않지만, 마스크 언어모델 관행상 마스크된 토큰 전체로 보는 게 자연스럽다. 그렇다면 오프셋이 직접 적용되지 않는 다수 토큰(문맥을 통한 간접 영향은 있으나 작다)이 평균을 지배하니, 전체 perplexity의 델타가 작아지기 쉽다. 논문은 영향받는 단어에 한정한 별도 perplexity를 제시하지 않아, 동적 성분의 진짜 기여가 이 지표에서 희석된다. 개선폭이 대부분 소수 셋째 자리에 머문다는 사실은 방법이 무력하다는 증거일 수도, 지표가 둔감하다는 증거일 수도 있다. 논문의 수치만으로는 둘을 가를 수 없다.

### 5.2 Dev에서 이기고 Test에서 지는 역전 (논문 외 비판)

Reddit은 논문이 코로나기 의미 변동 사례를 뽑은 바로 그 데이터인데, perplexity에서 Dev(유의 승)와 Test(패배)가 뒤집힌다. YELP-Dev에서도 비동적 모델이 근소하게 낫다. 개선폭이 워낙 작아(0.002~0.017) 실행 간 변동과 구분하기 어려운 데다 이런 역전까지 겹치면, Dev에서 얻은 유의성을 그대로 신뢰하기 어렵다. 동적 성분이 개발셋에 다소 과적합했을 가능성을 배제할 근거가 논문 안에 없다.

### 5.3 대부분 단일 실행이고 오차막대가 없다 (논문 외 비판)

Table 2와 Table 5의 주 결과는 단일 실행 점추정치로 보고된다. 시드를 바꾼 재실행 평균이나 신뢰구간이 없다. 부록의 평균·표준편차는 하이퍼파라미터 그리드 탐색의 통계일 뿐 최종 성능의 실행 간 분산이 아니다. 보고된 유의성은 인스턴스 단위 검정(Wilcoxon·McNemar)이라 실행 간 안정성을 담보하지 않는다. 게다가 사회 벡터는 node2vec이라는 확률적 초기화를 거치는데, 이 초기화가 오프셋과 하류 전체에 영향을 주면서도 초기화 민감도 점검이 보고되지 않는다. 델타가 작을수록 이런 공백은 결론의 무게를 덜어낸다.

---

## 6. 방법적 한계와 확장

### 6.1 논문이 남긴 것

DCWE의 기여는 성능표보다 표현의 형태에 있다. 문맥화와 동적성을 학습된 오프셋 하나로 봉합하고, 거기에 사회 축까지 결합한 설계는 그 자체로 명료하다. 오프셋을 정적·동적 임베딩 사이 각도로 읽어 "어느 단어가 어느 집단에서 언제 흔들렸는가"를 정량화하는 분석 장치도 이 표현이 있어야 나온다. 저자 스스로 기여를 성능이 아니라 방법과 분석 도구로 규정하고, perplexity 서술을 "때때로 유의하게"로 눌러 쓴 것은 정직한 태도다.

### 6.2 상위 10만 어휘 제한과 약한 사회 성분 (논문 외 비판)

두 가지 내재적 한계가 방법의 주장을 좁힌다. 첫째, 동적화가 상위 10만 빈발어로 제한되고 나머지는 정적 임베딩을 쓴다. 그래서 그 밖의 신조어·희귀 도메인어에서 의미가 변하더라도 이 방법은 포착하지 못하는 사각지대가 생긴다. 대표 사례로 든 코로나 단어가 전부 빈발어("testing"·"isolating")라는 사실이 이 커버리지 한계를 방증한다.

둘째, 모델의 차별적 신규 요소인 사회 성분이 실증적으로 가장 약하다. Ablation에서 사회를 빼도 손해가 대체로 시간을 뺄 때보다 작고(Reddit은 예외), Ciao에서는 사회 성분이 적합을 전혀 개선하지 못한다. 그런데 모델은 명시적 소셜 그래프와 시간 메타데이터를 모두 요구해 적용 대상을 좁힌다. 적용 범위를 좁혀가며 넣은 사회 절반의 효익이 데이터 밀도에 따라 0까지 떨어진다.

### 6.3 평활 prior와 급변 관찰의 상충 (논문 외 해석)

설계 안에 미묘한 상충이 있다. random-walk prior는 오프셋이 시간에 걸쳐 매끄럽게 변하도록 강제한다. 급변을 벌하되 완만한 드리프트는 허용하는 정규화다. 그런데 논문의 대표 사례는 코로나기의 급격한 변동이다. 급변을 억누르는 prior와, 관찰하고 싶은 급변이 서로 당긴다. 여기에 성격이 다른 편향이 하나 더 겹친다. anchoring prior는 오프셋 크기를 0으로 수축시켜, 맥락별 코사인(Eq. 14)을 "변화 없음" 쪽으로 민다. 두 prior는 크기 수축(anchoring)과 급변 억제(random-walk)라는 서로 다른 방향으로 작동한다. 특히 시간 급변을 담아야 할 표준편차 $\sigma_{\text{sim}}$(Eq. 15)이 random-walk에 눌리면, 코로나 같은 사례의 변동이 과소추정될 수 있다. $\lambda_a$·$\lambda_w$가 측정된 동역학에 얼마나 영향을 주는지 민감도 분석이 있었다면 이 상충의 크기를 가늠할 수 있었을 텐데, 논문은 이를 다루지 않는다.

여기서 방법을 개선하려는 사람에게 열린 길이 보인다. 영향받는 어휘에 한정한 perplexity, 시드 재실행과 신뢰구간, prior 세기에 대한 민감도 분석, 그리고 정성 삽화 대신 표준 의미 변화 벤치마크와의 정량 대조가 그것이다. 이들은 모두 이 논문이 세운 표현 구조를 그대로 두고도 채울 수 있는 검증의 빈칸이다.

---

## 7. 결론

DCWE는 큰 성능 향상을 주장하는 논문이 아니다. 마스크 언어모델 perplexity의 이득은 대부분 유의하지 않고, 일부에서는 역전까지 난다. 감정 분류에서 일관된 우위가 있으나 마진은 작다. 이 논문의 값은 다른 데 있다. 문맥화 임베딩과 동적 임베딩이라는 서로를 못 보던 두 계열을, 문맥화 이전에 정적 임베딩을 시간·사회 오프셋으로 흔든다는 한 가지 설계로 합친 것이다. 시간과 사회를 함께 넣은 것도 이 계열에서 드문 선택이다.

동시에 그 설계는 자기 한계를 안고 있다. 동적화가 빈발어에 갇혀 정작 급변하는 어휘를 놓치고, 차별적 요소인 사회 성분은 데이터가 성기면 무력해지며, 평활 prior는 관찰하려는 급변과 당긴다. 표현의 골격은 명료하지만, 그 골격이 실제로 무엇을 얼마나 재는지에 대한 검증은 얇다. 방법을 이해하려는 독자에게 이 논문은 "어떻게 합쳤나"는 분명히, "그래서 얼마나 잘 재나"는 열어둔 채로 남긴다.

---

## References

- Bamler, R., & Mandt, S. (2017). Dynamic word embeddings. In *Proceedings of the 34th International Conference on Machine Learning (ICML 2017)* (pp. 380–389). ([PDF 보기](/paper-viewer?title=Dynamic+word+embeddings&source=blog-reference&authors=Robert+Bamler%3BStephan+Mandt&year=2017&arxiv_id=1702.08359&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1702.08359.pdf))
- Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2019). BERT: Pre-training of deep bidirectional transformers for language understanding. In *Proceedings of NAACL-HLT 2019* (pp. 4171–4186). ([PDF 보기](/paper-viewer?title=BERT%3A+Pre-training+of+deep+bidirectional+transformers+for+language+understanding&source=blog-reference&authors=Jacob+Devlin%3BMing-Wei+Chang%3BKenton+Lee%3BKristina+Toutanova&year=2019&arxiv_id=1810.04805&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1810.04805.pdf))
- Geeraerts, D. (2010). *Theories of lexical semantics*. Oxford University Press.
- Grover, A., & Leskovec, J. (2016). node2vec: Scalable feature learning for networks. In *Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining* (pp. 855–864). ([PDF 보기](/paper-viewer?title=node2vec%3A+Scalable+feature+learning+for+networks&source=blog-reference&authors=Aditya+Grover%3BJure+Leskovec&year=2016&doi=10.1145%2F2939672.2939754&url=https%3A%2F%2Fdoi.org%2F10.1145%2F2939672.2939754))
- Hofmann, V., Pierrehumbert, J. B., & Schütze, H. (2021). Dynamic contextualized word embeddings. In *Proceedings of the 59th Annual Meeting of the Association for Computational Linguistics and the 11th International Joint Conference on Natural Language Processing (Vol. 1: Long Papers)* (pp. 6970–6984). https://aclanthology.org/2021.acl-long.542/ ([PDF 보기](/paper-viewer?title=Dynamic+contextualized+word+embeddings&source=blog-reference&authors=Valentin+Hofmann%3BJanet+B.+Pierrehumbert%3BHinrich+Sch%C3%BCtze&year=2021&arxiv_id=2010.12684&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2010.12684.pdf))
- Labov, W. (2001). *Principles of linguistic change, Vol. 2: Social factors*. Blackwell.
- Milroy, L. (1980). *Language and social networks*. Blackwell.
- Peters, M. E., Neumann, M., Iyyer, M., Gardner, M., Clark, C., Lee, K., & Zettlemoyer, L. (2018). Deep contextualized word representations. In *Proceedings of NAACL-HLT 2018* (pp. 2227–2237). ([PDF 보기](/paper-viewer?title=Deep+contextualized+word+representations&source=blog-reference&authors=Matthew+E.+Peters%3BMark+Neumann%3BMohit+Iyyer%3BMatt+Gardner%3BChristopher+Clark%3BKenton+Lee%3BLuke+Zettlemoyer&year=2018&arxiv_id=1802.05365&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1802.05365.pdf))
- Pierrehumbert, J. B. (2012). The dynamic lexicon. In A. C. Cohn, C. Fougeron, & M. K. Huffman (Eds.), *The Oxford handbook of laboratory phonology* (pp. 173–183). Oxford University Press.
- Rudolph, M., & Blei, D. (2018). Dynamic embeddings for language evolution. In *Proceedings of the 2018 World Wide Web Conference (WWW 2018)* (pp. 1003–1011). ([PDF 보기](/paper-viewer?title=Dynamic+Embeddings+for+Language+Evolution&source=blog-reference&authors=Maja+Rudolph%3BDavid+M.+Blei&year=2018&doi=10.1145%2F3178876.3185999&arxiv_id=1703.08052&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1703.08052.pdf&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3178876.3185999))
- Veličković, P., Cucurull, G., Casanova, A., Romero, A., Liò, P., & Bengio, Y. (2018). Graph attention networks. In *International Conference on Learning Representations (ICLR 2018)*. ([PDF 보기](/paper-viewer?title=Graph+attention+networks&source=blog-reference&authors=Petar+Veli%C4%8Dkovi%C4%87%3BGuillem+Cucurull%3BArantxa+Casanova%3BAdriana+Romero%3BPietro+Li%C3%B2%3BYoshua+Bengio&year=2018&arxiv_id=1710.10903&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1710.10903.pdf))
- Yao, Z., Sun, Y., Ding, W., Rao, N., & Xiong, H. (2018). Dynamic word embeddings for evolving semantic discovery. In *Proceedings of the Eleventh ACM International Conference on Web Search and Data Mining (WSDM 2018)* (pp. 673–681). ([PDF 보기](/paper-viewer?title=Dynamic+Word+Embeddings+for+Evolving+Semantic+Discovery&source=blog-reference&authors=Zijun+Yao%3BYifan+Sun%3BWeicong+Ding%3BNikhil+Rao%3BHui+Xiong&year=2018&doi=10.1145%2F3159652.3159703&arxiv_id=1703.00607&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1703.00607.pdf&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3159652.3159703))
