# DeepWalk 심층 분석: "DeepWalk: Online Learning of Social Representations" 논문 해설

**Paper:** Perozzi, Bryan; Al-Rfou, Rami; Skiena, Steven. (2014). "DeepWalk: Online Learning of Social Representations." *Proceedings of the 20th ACM SIGKDD International Conference on Knowledge Discovery and Data Mining (KDD 2014)*, arXiv:1403.6652. https://doi.org/10.1145/2623330.2623732

**DeepWalk**는 그래프의 짧은 random walk를 '문장', 정점을 '단어'로 취급해 SkipGram으로 정점 임베딩을 비지도 학습하는 방법이다(Perozzi et al., KDD 2014). 라벨이 1%뿐인 희소 조건에서 기존 기법 대비 Micro-F1을 최대 10%p 이상 앞선다.

**Abstract:** 본 문서는 random walk 기반 node embedding의 출발점인 DeepWalk 논문을 해설한다. 논문의 아이디어는 하나의 유비다: scale-free 그래프 위 짧은 random walk에서 정점이 등장하는 빈도는 자연어의 단어 빈도와 같은 power law를 따르므로, walk를 문장으로, 정점을 단어로 취급하면 언어 모델(SkipGram)을 그대로 그래프에 이식할 수 있다. 학습된 표현은 라벨과 독립적인 비지도 산출물이라 여러 분류 과제에 재사용되고, 라벨이 희소한 구간에서 당시 baseline을 앞섰으며, spectral 방법이 실행되지 않는 규모(YouTube, 114만 정점)까지 확장됐다. 한계는 7장에서 정리한다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 라벨이 희소한 소셜 네트워크에서, 라벨과 독립적인 정점 표현을 비지도로 학습해 분류에 쓸 수 있는가? |
| 핵심 기여 | random walk의 정점 빈도가 단어 빈도와 같은 power law라는 관찰을 근거로, walk를 문장으로 취급해 SkipGram + hierarchical softmax를 그래프에 이식한다(§3.2, Algorithm 1·2). |
| 방법적 결과 | 정점당 γ개, 길이 t의 uniform random walk를 코퍼스로 삼아 V×d 크기의 표현 행렬 \(\Phi\)를 학습. hierarchical softmax로 갱신 비용 \(O(V) \to O(\log V)\). |
| 실험 결과 | 저자 보고 기준 라벨 희소 구간에서 우위: Flickr에서 3% 라벨로 baseline의 10% 성능을 상회(micro-F1 35.9 vs 35.41), YouTube 1%에서 EdgeCluster 대비 micro +14.05%p(Table 3·4). |
| 핵심 한계 | 라벨이 충분하면 SpectralClustering에 뒤진다(BlogCatalog micro \(T_R\ge70\%\); macro는 \(T_R>20\%\)부터). transductive이고 node feature를 쓰지 않으며, streaming 변형은 미실험 스케치다. |

**TL;DR** — (1) DeepWalk는 random walk 경로를 문장으로, 정점을 단어로 취급해 SkipGram으로 비지도 정점 임베딩을 학습하는 그래프 표현 학습 방법이다. (2) YouTube 1% 라벨 조건에서 EdgeCluster 대비 micro-F1 +14.05%p(37.95 vs 23.90)를 기록하며, 라벨이 희소한 구간에서 두드러진 우위를 보인다. (3) 라벨이 충분한 구간에서는 SpectralClustering에 역전되며, transductive 방식으로 node feature를 활용하지 못하는 구조적 한계가 있다.

## 목차

1. 서론
2. 예비 지식
3. 핵심 관찰: random walk는 문장이다
4. DeepWalk 알고리즘
5. 실험 설정
6. 실험 결과 및 분석
7. 해석의 범위와 한계
8. 방법적 한계와 확장
9. 결론

---

## 1. 서론

### 1.1 연구 배경

문제는 부분적으로만 라벨된 소셜 네트워크에서의 multi-label 정점 분류다. 논문의 형식화로는 \(G_L = (V, E, X, Y)\), 즉 그래프에 속성 행렬 \(X \in \mathbb R^{|V|\times S}\)와 라벨 행렬 \(Y \in \mathbb R^{|V|\times|\mathcal Y|}\)가 붙어 있는 설정이다(§2). 2014년 당시의 표준 접근인 relational classification은 이 문제를 무방향 Markov network의 추론으로 놓고, Gibbs sampling이나 iterative classification 같은 반복 근사 추론으로 라벨의 사후분포를 계산했다(§2). 이 방식에서는 라벨 정보가 특징 공간에 섞여 들어간다.

DeepWalk는 여기서 라벨과 구조를 분리한다. 라벨 분포와 무관하게 그래프 구조만으로 표현 \(X_E \in \mathbb R^{|V|\times d}\)를 비지도로 학습하고, 분류는 그 위에 얹는다. 반복 추론의 cascading error를 피하고, 같은 표현을 그 네트워크의 여러 분류 과제에 재사용할 수 있다는 것이 분리의 이점이다(§2). 논문은 이 구조적 표현으로 "속성 공간 X를 증강(augment)하겠다"고까지 예고하는데, 이 예고가 실제로 지켜지는지는 7.4절에서 본다.

논문이 표현에 요구하는 성질은 네 가지다(§3). 그래프가 변해도 전체 재학습이 필요 없을 것(adaptability), 잠재 공간의 거리가 사회적 유사성의 척도일 것(community aware), 저차원일 것(라벨 희소 시 일반화와 속도), 연속적일 것(부분적 커뮤니티 소속과 매끄러운 결정 경계). community aware 요건은 homophily 네트워크에서의 일반화를 명시적 전제로 삼는다.

![DeepWalk Figure 1: karate network](/api/blog/figures/deepwalk-fig1-karate.png)
*그림 1. Zachary's Karate 네트워크(왼쪽 입력)와 DeepWalk가 학습한 2차원 표현(오른쪽). 정점 색은 입력 그래프의 modularity 기반 클러스터링인데, 잠재 공간에서 선형 분리 가능한 영역들과 대응한다. — Perozzi et al. (2014), Figure 1에서 연구·학습 목적상 발췌.*

### 1.2 핵심 질문

| 질문 | 내용 |
| --- | --- |
| Q1 | 언어 모델링 기법을 그래프에 이식할 수 있는 구조적 근거가 있는가? |
| Q2 | 그렇게 학습한 라벨 독립적 표현이, 라벨이 희소할 때 relational classification·spectral 계열보다 나은가? |
| Q3 | 그 방법이 spectral 분해가 불가능한 규모의 그래프까지 확장되는가? |

### 1.3 학술적 위치

논문이 §1에서 밝히는 기여는 세 가지다: (1) deep learning(비지도 표현 학습)을 네트워크 분석에 도입(논문 스스로 "for the first time"이라고 쓴다), (2) 다중 라벨 분류에서의 광범위한 평가 — 가장 희소한 문제들에서 micro-F1 5–10% 개선, 일부 경우 60% 적은 학습 데이터로 우위, (3) 웹 규모 그래프(YouTube)에서의 병렬 구현 시연과 streaming 변형의 스케치.

이 위키의 GNN 4부작(gcn·graphsage·gin·gat)에서 DeepWalk는 "feature를 쓰지 않는 transductive embedding baseline"으로 반복 등장했다. GCN 실험표에서 큰 격차로 밀리는 하한선이었고, GraphSAGE는 이 논문의 재학습 필요성을 inductive 설정의 대조군으로 삼았다. 그 기준점이 된 논문을 원문으로 읽는 것이 이 글의 목적이다.

---

## 2. 예비 지식

**Relational classification(= collective inference).** 그래프의 링크는 관측치 간 독립(i.i.d.) 가정을 깨뜨린다. collective inference 계열은 이 의존성을 근사 추론으로 직접 활용하지만, 정확한 추론은 NP-hard이고 근사는 수렴 보장이 없을 수 있다(§7.1).

**Social dimensions 계열.** DeepWalk 이전의 표현 학습 대안은 Tang & Liu의 세 방법이었다(§5.2). SpectralClustering(Tang & Liu, 2011)은 정규화 Laplacian의 최소 고유벡터를 쓰며 "graph cut이 분류에 유용하다"는 가정을 깔고, Modularity(Tang & Liu, 2009a)는 modularity 행렬의 상위 고유벡터로 "modular한 분할이 유용하다"고 가정한다. EdgeCluster(Tang & Liu, 2009b)는 인접행렬의 k-means로, spectral 분해가 불가능한 규모까지 확장된다는 점이 특징으로 소개된다. 이 성질이 6.2절 YouTube 비교의 구도를 만든다. 셋 모두 전역 행렬 계산이 필요한 오프라인 방법이다(§7).

**SkipGram과 hierarchical softmax.** word2vec의 SkipGram은 중심 단어의 표현으로 window 안 주변 단어들을 예측하도록 학습한다. 어휘 크기만큼의 softmax가 병목인데, hierarchical softmax는 단어들을 이진 트리의 잎에 배정하고 예측을 루트→잎 경로의 이진 분류 곱으로 분해해 비용을 \(O(\log|V|)\)로 낮춘다. DeepWalk는 이 두 부품을 그대로 가져온다. negative sampling은 이 논문에 등장하지 않는다. softmax 근사는 hierarchical softmax뿐이다(§4.2).

---

## 3. 핵심 관찰: random walk는 문장이다

power law(scale-free) 분포란 소수의 원소가 매우 자주, 대부분의 원소는 드물게 등장하는 긴 꼬리 분포다. 자연어의 단어 빈도가 그렇고(Zipf 법칙), 소셜 네트워크의 차수 분포가 그렇다. 논문의 관찰은 이 둘을 잇는다: 연결 그래프의 차수 분포가 power law이면, 그 위의 짧은 random walk에 정점이 등장하는 빈도도 power law를 따른다(§3.2). Figure 2가 YouTube 그래프의 walk와 영어 위키백과 10만 문서의 단어 빈도를 나란히 놓는다.

![DeepWalk Figure 2: power law](/api/blog/figures/deepwalk-fig2-powerlaw.png)
*그림 2. 짧은 random walk의 정점 등장 빈도(왼쪽, YouTube 소셜 그래프)와 자연어 단어 빈도(오른쪽, 영어 위키백과 10만 문서)가 같은 power law를 따른다. — Perozzi et al. (2014), Figure 2에서 연구·학습 목적상 발췌.*

논문이 core contribution의 하나로 꼽는 것은 이 관찰을 근거로 한 재목적화 아이디어다: 심볼 빈도가 power law를 따르는 자연어를 모델링하던 기법을, 같은 분포를 따르는 네트워크의 커뮤니티 구조 모델링에 옮겨 쓸 수 있다(§3.2). 유비는 이렇게 구성된다. random walk의 스트림은 특수한 언어의 짧은 문장이고, 그래프 정점이 그 언어의 어휘다(§3.3, §4.1).

언어 모델링의 목표 \(\Pr(w_n \mid w_0, \dots, w_{n-1})\)를 정점으로 옮기면 \(\Pr(v_i \mid v_1, \dots, v_{i-1})\)이 되는데, 표현 학습이 목적이므로 매핑 \(\Phi: v \mapsto \mathbb R^d\)(실체는 \(|V| \times d\) 자유 파라미터 행렬)를 끼워 넣는다(Eq 1). walk가 길어지면 이 조건부 확률 계산이 불가능해지므로 SkipGram식 완화를 쓴다. 완화는 세 가지 변경이다(§3.3): (1) 문맥으로 중심 단어를 예측하는 대신 중심 하나로 문맥을 예측하고, (2) 문맥에 오른쪽뿐 아니라 왼쪽 단어들을 포함하며, (3) 순서 제약을 제거한다:

$$
\underset{\Phi}{\text{minimize}}\; -\log \Pr\big(\{v_{i-w}, \dots, v_{i-1}, v_{i+1}, \dots, v_{i+w}\} \mid \Phi(v_i)\big) \tag{Eq 2}
$$

논문은 이 완화가 그래프에서는 오히려 자연스럽다고 주장한다. random walk가 주는 것은 어순이 아니라 "가까움(nearness)"의 감각이고, 한 번에 정점 하나만 다루는 작은 모델이라 학습도 빨라진다(§3.3). 이 목적을 최적화하면 이웃 구성이 비슷한 정점들이 비슷한 표현을 얻는다. 논문의 표현으로는 co-citation similarity의 인코딩이다.

random walk를 재료로 고른 이유도 세 가지로 정리돼 있다(§3.1): 지역 커뮤니티 구조를 그래프 크기보다 작은(sublinear) 시간에 포착하는 output-sensitive 알고리즘들의 기반이라는 점, 여러 walker로 병렬화가 쉽다는 점, 그래프가 조금 변하면 변한 영역에서 새 walk를 뽑아 전역 재계산 없이 모델을 갱신할 수 있다는 점. 뒤의 둘이 각각 확장성과 adaptability 요건에 대응한다.

---

## 4. DeepWalk 알고리즘

### 4.1 본체 (Algorithm 1·2)

DeepWalk(G, w, d, γ, t)는 다섯 개의 입력을 받는다: 그래프, window 크기 w, 표현 차원 d, 정점당 walk 수 γ, walk 길이 t.

1. \(\Phi\)를 균등분포에서 초기화하고, 전체 정점 집합 V로 hierarchical softmax용 이진 트리를 만든다(Algorithm 1, 1–2행).
2. γ번의 pass를 돈다. 매 pass마다 정점 순서를 셔플하고(SGD 수렴 가속), 각 정점에서 길이 t의 walk를 하나 생성한 뒤 SkipGram으로 \(\Phi\)를 갱신한다(3–9행).
3. walk는 마지막 방문 정점의 이웃에서 균등 샘플링으로 이어 간다. 시작점으로 되돌아가는 restart 옵션은 예비 실험에서 이점이 없어 쓰지 않았다(§4.2).
4. SkipGram(Algorithm 2)은 walk 안에서 window w 이내의 모든 정점 쌍 \((v_j, u_k)\)를 순회하며 \(J(\Phi) = -\log \Pr(u_k \mid \Phi(v_j))\)의 gradient로 갱신한다. 학습률은 2.5%에서 시작해 지금까지 본 정점 수에 따라 선형 감소한다(§4.2.3).

![DeepWalk Figure 3: overview](/api/blog/figures/deepwalk-fig3-overview.png)
*그림 3. DeepWalk 개관. (a) random walk 생성, (b) 중심 정점을 표현 \(\Phi(v_1)\)에 매핑, (c) hierarchical softmax가 \(\Pr(v_3 \mid \Phi(v_1))\)과 \(\Pr(v_5 \mid \Phi(v_1))\)을 각각 루트→잎 경로의 이진 분류 곱으로 분해. \(\Phi\)는 \(v_1\)이 문맥 \(\{v_3, v_5\}\)와 동시 등장할 확률을 최대화하도록 갱신된다. — Perozzi et al. (2014), Figure 3에서 연구·학습 목적상 발췌.*

### 4.2 Hierarchical softmax와 병렬화

\(\Pr(u_k \mid \Phi(v_j))\)를 그대로 계산하면 클래스 수가 \(|V|\)인 분류라 분배함수가 병목이다. 정점들을 이진 트리의 잎에 배정하면 예측이 경로 확률의 곱 \(\prod_l \Pr(b_l \mid \Phi(v_j))\)로 바뀌고, 각 인자는 트리 내부 노드의 이진 분류기다. 비용이 \(O(|V|)\)에서 \(O(\log|V|)\)로 내려가고, Huffman coding으로 빈발 정점에 짧은 경로를 배정해 더 줄인다(§4.2.2). 파라미터는 표현 \(\Phi\)와 트리 분류기 T, 각각 \(O(d|V|)\)다.

병렬화의 근거도 3장의 power law 관찰에서 나온다. walk 안 정점 빈도의 긴 꼬리 때문에 \(\Phi\) 갱신이 sparse하고, 그래서 lock 없는 비동기 SGD(Hogwild 스타일)를 쓸 수 있다. 갱신이 sparse하면 lock 없이도 ASGD가 최적 수렴률을 달성한다는 보장은 Hogwild 논문에서 온다(§4.3). Figure 4는 worker 8개까지 일관된 속도 향상과, 직렬 실행 대비 예측 성능 손실이 없음을 보인다.

### 4.3 변형: streaming과 non-random walk (§4.4)

streaming 변형은 전체 그래프를 모른 채 walk 스트림을 바로 학습기에 흘려 넣는 구상이다. 감쇠 학습률을 상수로 바꿔야 하고(학습이 느려짐을 논문도 인정), 트리는 \(|V|\)의 상한을 알 때만 미리 만들 수 있다(§4.4.1). non-random walk 변형은 사용자의 웹 탐색처럼 실제 순회의 스트림을 그대로 쓰는 구상으로, 구조뿐 아니라 경로의 통행 빈도까지 담긴다. 논문은 둘을 결합하면 전체 그래프를 아예 구성하지 않고 진화하는 네트워크에서 웹 규모 분류가 가능하리라는 전망도 적는다(§4.4.2). 셋 다 실험 없는 스케치라는 점은 7.5절에서 다시 본다.

---

## 5. 실험 설정

### 5.1 데이터셋 3종 (Table 1)

| Dataset | 정점 수 (V) | 간선 수 (E) | 라벨 수 | 라벨 종류 |
| --- | ---: | ---: | ---: | --- |
| BlogCatalog | 10,312 | 333,983 | 39 | Interests |
| Flickr | 80,513 | 5,899,882 | 195 | Groups |
| YouTube | 1,138,499 | 2,990,443 | 47 | Groups |

셋 모두 node feature가 없는 소셜 네트워크이고, 과제는 multi-label 정점 분류다.

### 5.2 비교 대상과 프로토콜

baseline은 다섯이다(§5.2): 2장에서 본 Tang–Liu 계열 3종(SpectralClustering, Modularity, EdgeCluster)과 wvRN(이웃 라벨의 가중 평균 관계 분류기), Majority(최빈 라벨).

평가는 Tang & Liu의 절차를 그대로 따른다(§6.1). 라벨된 정점의 비율 \(T_R\)만큼 무작위 샘플해 학습하고 나머지로 테스트하며, 10회 반복 평균의 micro/macro-F1을 보고한다. 분류기는 LibLinear의 one-vs-rest 로지스틱 회귀다. DeepWalk 설정은 γ=80, w=10, d=128 단일 조합이고, Tang–Liu 계열 3종은 그들이 선호한 d=500을 쓴다(§6.1). 차원이 다른 비교다. 표준편차나 유의성 검정은 보고되지 않는다.

---

## 6. 실험 결과 및 분석

### 6.1 BlogCatalog: 우위와 열세가 갈리는 표 (Table 2 발췌, micro-F1 %)

| Method | 10% | 50% | 90% |
| --- | ---: | ---: | ---: |
| DeepWalk | **36.00** | **41.00** | 42.00 |
| SpectralClustering | 31.06 | 39.97 | **42.62** |
| EdgeCluster | 27.94 | 34.12 | 36.29 |
| Modularity | 27.35 | 34.09 | 38.18 |
| wvRN | 19.51 | 30.37 | 34.28 |
| Majority | 16.51 | 16.91 | 17.26 |

DeepWalk는 BlogCatalog 10% 라벨에서 micro-F1 36.00으로 최고를 기록했으나, 90% 라벨에서는 SpectralClustering 42.62에 역전된다.

(원 표는 \(T_R\) 10–90% 9개 열의 micro/macro 두 블록이다. 여기서는 micro 3개 열만 발췌했고 굵게는 열별 최고치 기준으로 재구성했다. 본문의 macro 수치는 원 표에서 직접 인용한다.)

논문이 강조하는 것은 희소 구간이다. 20% 라벨로 학습한 DeepWalk(38.20)가 EdgeCluster·Modularity·wvRN에 90%를 줘도 이긴다(36.29/38.18/34.28). 다만 이 문장은 micro-F1로만 성립한다. macro-F1로는 DW@20%가 23.80으로 Modularity@90%(24.97)에 뒤진다. 논문 문장 자체는 지표를 특정하지 않았다(§6.1.1; 지표 구분은 이 글의 검증이다). SpectralClustering과의 관계는 논문이 명시한다: DeepWalk의 우위는 macro-F1 \(T_R\le20\%\), micro-F1 \(T_R\le60\%\)까지이고, 그 위로는 SpectralClustering이 앞선다(§6.1.1).

### 6.2 Flickr와 YouTube: 희소 라벨과 확장성 (Table 3·4 발췌, micro-F1 %)

| Method | Flickr 1% | Flickr 5% | Flickr 10% | YouTube 1% | YouTube 5% | YouTube 10% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DeepWalk | **32.4** | **37.2** | **38.7** | **37.95** | **41.32** | **43.05** |
| SpectralClustering | 27.43 | 33.31 | 35.41 | — | — | — |
| EdgeCluster | 25.75 | 30.85 | 32.84 | 23.90 | 37.81 | 40.07 |
| Modularity | 22.75 | 28.05 | 29.2 | — | — | — |
| wvRN | 17.7 | 19.83 | 22.73 | 26.79 | 35.76 | 39.42 |
| Majority | 16.34 | 16.65 | 16.71 | 24.90 | 25.22 | 25.38 |

(원 표는 각각 \(T_R\) 1–10% 10개 열의 micro/macro 두 블록이다. 여기서는 micro 3개 열만 발췌했고 굵게는 열별 최고치 기준이다.)

Flickr에서 DeepWalk는 전 구간 micro-F1이 모든 baseline을 최소 3% 이상 앞선다(최소 격차는 10% 열의 +3.29%p, §6.1.2). Abstract의 "60% 적은 데이터" 주장도 여기서 나온다. 3% 라벨의 DeepWalk(35.9)가 모든 baseline의 10% 성능 최고치(SpectralClustering 35.41)를 넘는다(§6.1.2). 산술로는 3%→10%가 70% 감소라서 "60%"는 오히려 보수적인 수사다(4% 기준으로 읽으면 정확히 60%이고 그때도 36.7 > 35.41로 성립한다).

YouTube에서는 비교의 성격이 바뀐다. SpectralClustering과 Modularity는 그래프 크기 때문에 아예 실행되지 못했다(전 구간 "—", §6.1.3). 이 표가 입증하는 것은 그 둘에 대한 확장성 우위이고, 정확도 비교는 EdgeCluster·wvRN·Majority에 대해서만 성립한다. 그 안에서의 격차는 크다: \(T_R=1\%\)에서 EdgeCluster 대비 micro +14.05%p(37.95 vs 23.90), macro +9.74%p(29.22 vs 19.48)다(§6.1.3).

### 6.3 파라미터 민감도 (Figure 5)

w=10, t=40을 고정하고 d, γ, \(T_R\)을 바꾼 실험에서 두 경향이 일관된다(§6.2). 최적 차원 d는 가용 라벨 수에 의존하고(논문이 붙인 주석: Flickr 1%의 라벨 수가 BlogCatalog 10%와 비슷하다), walk 수 γ의 효과는 γ>10부터 빠르게 둔화되어 γ=30 부근에서 이득 대부분이 달성된다. γ 값 사이의 상대적 격차는 엣지 수가 한 자릿수 다른 두 그래프(BlogCatalog, Flickr)에서 일관됐다 — 논문이 흥미롭다고 짚는 관찰이다. 적은 수의 walk로도 의미 있는 표현이 학습된다는 것이 결론이다.

---

## 7. 해석의 범위와 한계

### 7.1 우위는 희소 구간의 이야기다

이 논문의 성능 주장을 "DeepWalk가 spectral 방법보다 낫다"로 요약하면 표와 어긋난다. BlogCatalog에서 라벨이 충분하면(micro \(T_R\ge70\%\)) 2009년의 SpectralClustering이 이기고, 논문도 이를 명시한다(§6.1.1). 정확히 요약하면 "라벨이 희소할 때, 그리고 spectral 분해가 불가능한 규모에서 낫다"가 된다.

Abstract의 "up to 10%"도 희소 구간 한정 주장인데, 대응하는 표 셀을 논문은 특정하지 않는다. §1의 기여 문장은 같은 주장을 "micro-F1 5–10%"로 쓰지만, micro의 최대 격차는 YouTube 1%의 +14.05%p로 10%를 넘고, 10%에 가장 가까운 셀은 같은 열의 macro +9.74%p다(대응 추적은 이 글의 검증이다). YouTube 10% macro의 "5% improvement"도 표로는 +4.13%p다(§6.1.3 vs Table 4). 인용의 기준은 본문 수사가 아니라 표의 원값이다.

### 7.2 평가 프로토콜의 유산

Tang & Liu 절차의 계승은 비교 가능성을 위한 합리적 선택이지만, 물려받는 것들이 있다. baseline 수치 일부는 원 논문 값의 전재이고, Tang–Liu 계열은 d=500·DeepWalk는 d=128로 차원이 다르며, 반복 10회의 평균만 있고 분산·검정이 없다. multi-label 예측에서 상위 몇 개 라벨을 취하는지 같은 세부도 원 절차에 위임돼 있다. 테스트 정점의 라벨 개수를 아는 관행(후속 구현·문헌에서 TopKRanker로 불리게 된)이라는 지적이 이후 제기됐는데, 그 명칭 자체는 이 논문에 없다(후속 연구 맥락). 이 프로토콜은 이후 node embedding 평가의 표준이 되어 같은 한계도 함께 물려줬다.

### 7.3 homophily가 전제이자 한계다

"community aware" 요건은 homophily 네트워크에서의 일반화를 명시적으로 전제한다(§3). walk 동시 등장 = 유사라는 등식이 방법의 전제이므로, 학습되는 유사성은 근접성 기반이다. 서로 다른 커뮤니티에서 같은 역할을 하는 정점들(구조적 등가)은 같은 walk에 등장하지 않아 묶이지 않는다. 실험 3종이 모두 소셜 네트워크의 관심사·그룹 라벨(homophily가 성립하기 좋은 환경)이라는 점도 같은 방향이다. 역할 기반 embedding(struc2vec 등)이 여기서 갈라져 나왔다(후속 연구 맥락).

### 7.4 GNN 계열이 넘어선 두 한계의 원점 (해석상 한계)

\(\Phi\)는 \(|V| \times d\) look-up table이라 학습에 없던 정점은 표현이 없다. §3의 adaptability는 "변한 영역에서 새 walk를 뽑아 이어서 학습"하는 것이지 재학습 없는 즉시 embedding이 아니고, 동적 그래프 실험도 없다. 이것이 GraphSAGE가 문제 삼은 transductive 한계다. 또 SkipGram 목적함수는 embedding 공간의 직교변환에 불변이라 실행 간·그래프 간 좌표가 정렬되지 않는다(GraphSAGE 논문 Appendix D의 지적; blog/graphsage 2.2절). Figure 4(b)의 "병렬화해도 성능 손실 없음"은 분류 성능이 회전 불변이라 이 문제를 건드리지 못한다. 그리고 1.1절에서 봤듯 §2가 속성 행렬 X를 정의하고 증강까지 예고했지만, 방법과 실험 어디에서도 X는 쓰이지 않는다. node feature 결합은 GCN 계열의 몫으로 남았다.

### 7.5 제목의 "online learning"

논문이 online이라 부르는 실체는 SGD의 순차 갱신(§4.2.3), 부분 재학습 가능성(§3.1), 그리고 지역 정보만 쓰는 설계(§7의 차별점)다. 그러나 본 실험의 학습은 배치다: 시작 전에 전체 V로 트리를 만들고, 전체 정점을 셔플해 γ=80회 pass를 돌며, 학습률 스케줄도 전체 규모를 안다. 진짜 streaming은 §4.4.1의 조건부 스케치("if"가 두 번 들어간다)로만 존재하고 실험되지 않았다. 제목이 약속하는 것과 검증된 것 사이에 거리가 있다.

---

## 8. 방법적 한계와 확장

### 8.1 논문이 명시한 한계·제약

| 한계·제약 | 키워드 | 출처 | 상세 |
| --- | --- | --- | --- |
| Streaming 미완 | 상수 학습률(느린 수렴), 트리 사전 구성, 빈도 사전 추정 — 미실험 | §4.4.1 | 7.5절 |
| 열세 구간 | 라벨 충분 시 SpectralClustering 우위 | §6.1.1, Table 2 | 7.1절 |
| Future work | 언어–그래프 쌍대성 탐구, 언어모델링 개선, 이론적 정당화 강화 | §8 | 8.2절 |
| Homophily 전제 | community aware 요건에 명시(한계로의 독해는 7.3절의 해석) | §3 | 7.3절 |
| YouTube 비교 범위 | spectral 2종 실행 불가 — 확장성 증거 | §6.1.3, Table 4 | 6.2절 |

§8의 future work 첫 항목은 이 논문의 유비를 뒤집는 구상이다. 언어 모델링이란 사실 관측 불가능한 언어 그래프에서의 샘플링이라는 쌍대성인데, 관측 가능한 그래프에서 얻은 통찰로 언어 쪽을 개선할 수 있으리라는 방향이다.

### 8.2 이후 연구 계보 (후속 연구 맥락)

- **walk의 일반화**: node2vec(Grover & Leskovec, 2016)은 uniform walk를 파라미터 p, q로 편향시켜 BFS적·DFS적 탐색을 보간했다. DeepWalk는 그 스펙트럼의 한 고정점이 됐다. LINE(Tang et al., 2015)은 walk 없이 1차·2차 근접성을 직접 최적화하는 병행 노선이고, 셋이 묶여 "shallow embedding" 계열을 이룬다.
- **행렬분해 등가성**: NetMF(Qiu et al., 2018) 계열은 DeepWalk가 암묵적으로 특정 PMI형 행렬을 분해하는 것과 등가임을 보였다. "신경망 embedding vs spectral 방법"이라는 이 논문의 대립 구도가 사실 같은 스펙트럼 위에 있음이 사후에 밝혀졌고, §8이 자인한 이론적 정당화 부족을 후속 연구가 메운 사례다.
- **GNN 4부작에서의 위치**: 이 위키의 GCN·GraphSAGE·GIN·GAT 리뷰에서 DeepWalk는 "무엇을 넘어섰는가"를 정의하는 기준점이었다. feature 결합(GCN), 귀납성(GraphSAGE), 판별력(GIN), 학습형 가중(GAT)이 각각 이 논문이 다루지 않은 문제를 하나씩 해결했다.

### 8.3 사회연결망 분석에서의 의미 (해석)

DeepWalk의 역사적 의의는 손으로 설계한 구조 지표(중심성, 파티션 소속)를 학습된 잠재 표현으로 대체하는 노선을 열었다는 데 있다(§7의 차별점 서술과 정합). 사회학의 관점에서 주의할 것은 이 표현이 포착하는 유사성의 종류다. walk 동시 등장 기반이므로 응집적 하위집단 소속(cohesion)의 조작화에 가깝고, Lorrain-White식 구조적 등가(서로 연결되지 않아도 같은 위치)의 조작화가 아니다. "잠재 공간의 거리 = 사회적 유사성"이라는 논문의 등식을 연구 설계에 옮길 때 갈리는 부분이다.

---

## 9. 결론

DeepWalk는 "그래프 위의 random walk는 문장처럼 행동한다"는 power law 관찰을 근거로, SkipGram과 hierarchical softmax를 그래프로 옮겼다. 라벨 독립적 표현이라는 문제 설정과 평가 프로토콜은 Tang & Liu 계열에서 물려받았지만, walk를 코퍼스로 삼는 유비는 이 논문에서 시작됐고, 그 유비가 node2vec 이후의 shallow embedding 계열 전체를 열었다.

이 논문을 읽을 때 잡아야 할 균형은 이렇다.

| 기여 | 읽는 법 |
| --- | --- |
| 언어 모델 이식 | 논문이 core contribution으로 꼽는 것은 재목적화 아이디어이고, power law 관찰이 그 근거다. 알고리즘 자체는 word2vec의 재조립에 가깝다. |
| 희소 라벨 성능 | 우위는 희소 구간 한정이다. 라벨이 충분하면 SpectralClustering이 이긴다는 것을 논문 표가 직접 보여준다. |
| 확장성 | YouTube 결과는 spectral 분해 불가 규모에서의 실행 가능성 증거다. 정확도 비교는 EdgeCluster 계열에 대해서만 성립한다. |
| "Online learning" | 실증된 것은 배치 학습이고, streaming은 조건부 스케치다. |

표현 학습과 분류기의 분업 구조 자체는 social dimensions 계열이 먼저 만들었다. DeepWalk가 한 일은 그 자리에 신경망 표현 학습을 앉혀 주류로 만든 것이고, 이 분업은 GNN 시대에도 그대로 유지되고 있다.

## References

Grover, A., & Leskovec, J. (2016). node2vec: Scalable feature learning for networks. *Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 855–864. https://doi.org/10.1145/2939672.2939754 ([PDF 보기](/paper-viewer?title=node2vec%3A+Scalable+feature+learning+for+networks&authors=Aditya+Grover%3BJure+Leskovec&year=2016&doi=10.1145%2F2939672.2939754&url=https%3A%2F%2Fdoi.org%2F10.1145%2F2939672.2939754&source=blog-reference))

Hamilton, W. L., Ying, R., & Leskovec, J. (2017). Inductive representation learning on large graphs. *Advances in Neural Information Processing Systems*, *30*. https://arxiv.org/abs/1706.02216 ([PDF 보기](/paper-viewer?title=Inductive+representation+learning+on+large+graphs&authors=William+L.+Hamilton%3BRex+Ying%3BJure+Leskovec&year=2017&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1706.02216.pdf&arxiv_id=1706.02216&url=https%3A%2F%2Farxiv.org%2Fabs%2F1706.02216&source=blog-reference))

Kipf, T. N., & Welling, M. (2017). Semi-supervised classification with graph convolutional networks. *International Conference on Learning Representations*. https://arxiv.org/abs/1609.02907 ([PDF 보기](/paper-viewer?title=Semi-supervised+classification+with+graph+convolutional+networks&authors=Thomas+N.+Kipf%3BMax+Welling&year=2017&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1609.02907.pdf&arxiv_id=1609.02907&url=https%3A%2F%2Farxiv.org%2Fabs%2F1609.02907&source=blog-reference))

Mikolov, T., Chen, K., Corrado, G., & Dean, J. (2013). *Efficient estimation of word representations in vector space*. arXiv. https://arxiv.org/abs/1301.3781 ([PDF 보기](/paper-viewer?title=Efficient+estimation+of+word+representations+in+vector+space&authors=Tomas+Mikolov%3BKai+Chen%3BGreg+Corrado%3BJeffrey+Dean&year=2013&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1301.3781.pdf&arxiv_id=1301.3781&url=https%3A%2F%2Farxiv.org%2Fabs%2F1301.3781&source=blog-reference))

Mikolov, T., Sutskever, I., Chen, K., Corrado, G. S., & Dean, J. (2013). Distributed representations of words and phrases and their compositionality. *Advances in Neural Information Processing Systems*, *26*. https://arxiv.org/abs/1310.4546 ([PDF 보기](/paper-viewer?title=Distributed+representations+of+words+and+phrases+and+their+compositionality&authors=Tomas+Mikolov%3BIlya+Sutskever%3BKai+Chen%3BGreg+Corrado%3BJeffrey+Dean&year=2013&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1310.4546.pdf&arxiv_id=1310.4546&url=https%3A%2F%2Farxiv.org%2Fabs%2F1310.4546&source=blog-reference))

Perozzi, B., Al-Rfou, R., & Skiena, S. (2014). DeepWalk: Online learning of social representations. *Proceedings of the 20th ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 701–710. https://doi.org/10.1145/2623330.2623732 ([PDF 보기](/paper-viewer?title=DeepWalk%3A+Online+learning+of+social+representations&authors=Bryan+Perozzi%3BRami+Al-Rfou%3BSteven+Skiena&year=2014&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1403.6652.pdf&arxiv_id=1403.6652&url=https%3A%2F%2Farxiv.org%2Fabs%2F1403.6652&doi=10.1145%2F2623330.2623732&source=blog-reference))

Qiu, J., Dong, Y., Ma, H., Li, J., Wang, K., & Tang, J. (2018). Network embedding as matrix factorization: Unifying DeepWalk, LINE, PTE, and node2vec. *Proceedings of the Eleventh ACM International Conference on Web Search and Data Mining*, 459–467. https://doi.org/10.1145/3159652.3159706 ([PDF 보기](/paper-viewer?title=Network+embedding+as+matrix+factorization%3A+Unifying+DeepWalk%2C+LINE%2C+PTE%2C+and+node2vec&authors=Jiezhong+Qiu%3BYuxiao+Dong%3BHao+Ma%3BJian+Li%3BKuansan+Wang%3BJie+Tang&year=2018&doi=10.1145%2F3159652.3159706&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3159652.3159706&source=blog-reference))

Recht, B., Re, C., Wright, S., & Niu, F. (2011). Hogwild!: A lock-free approach to parallelizing stochastic gradient descent. *Advances in Neural Information Processing Systems*, *24*. https://arxiv.org/abs/1106.5730 ([PDF 보기](/paper-viewer?title=Hogwild%21%3A+A+lock-free+approach+to+parallelizing+stochastic+gradient+descent&authors=Benjamin+Recht%3BChristopher+Re%3BStephen+Wright%3BFeng+Niu&year=2011&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1106.5730.pdf&arxiv_id=1106.5730&url=https%3A%2F%2Farxiv.org%2Fabs%2F1106.5730&source=blog-reference))

Ribeiro, L. F. R., Saverese, P. H. P., & Figueiredo, D. R. (2017). struc2vec: Learning node representations from structural identity. *Proceedings of the 23rd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 385–394. https://doi.org/10.1145/3097983.3098061 ([PDF 보기](/paper-viewer?title=struc2vec%3A+Learning+node+representations+from+structural+identity&authors=Leonardo+F.+R.+Ribeiro%3BPedro+H.+P.+Saverese%3BDaniel+R.+Figueiredo&year=2017&doi=10.1145%2F3097983.3098061&url=https%3A%2F%2Fdoi.org%2F10.1145%2F3097983.3098061&source=blog-reference))

Tang, J., Qu, M., Wang, M., Zhang, M., Yan, J., & Mei, Q. (2015). LINE: Large-scale information network embedding. *Proceedings of the 24th International Conference on World Wide Web*, 1067–1077. https://doi.org/10.1145/2736277.2741093 ([PDF 보기](/paper-viewer?title=LINE%3A+Large-scale+information+network+embedding&authors=Jian+Tang%3BMeng+Qu%3BMingzhe+Wang%3BMing+Zhang%3BJun+Yan%3BQiaozhu+Mei&year=2015&doi=10.1145%2F2736277.2741093&url=https%3A%2F%2Fdoi.org%2F10.1145%2F2736277.2741093&source=blog-reference))

Tang, L., & Liu, H. (2009a). Relational learning via latent social dimensions. *Proceedings of the 15th ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 817–826. https://doi.org/10.1145/1557019.1557109 ([PDF 보기](/paper-viewer?title=Relational+learning+via+latent+social+dimensions&authors=Lei+Tang%3BHuan+Liu&year=2009&doi=10.1145%2F1557019.1557109&url=https%3A%2F%2Fdoi.org%2F10.1145%2F1557019.1557109&source=blog-reference))

Tang, L., & Liu, H. (2009b). Scalable learning of collective behavior based on sparse social dimensions. *Proceedings of the 18th ACM Conference on Information and Knowledge Management*, 1107–1116. https://doi.org/10.1145/1645953.1646094 ([PDF 보기](/paper-viewer?title=Scalable+learning+of+collective+behavior+based+on+sparse+social+dimensions&authors=Lei+Tang%3BHuan+Liu&year=2009&doi=10.1145%2F1645953.1646094&url=https%3A%2F%2Fdoi.org%2F10.1145%2F1645953.1646094&source=blog-reference))

Tang, L., & Liu, H. (2011). Leveraging social media networks for classification. *Data Mining and Knowledge Discovery*, *23*(3), 447–478. https://doi.org/10.1007/s10618-010-0210-x ([PDF 보기](/paper-viewer?title=Leveraging+social+media+networks+for+classification&authors=Lei+Tang%3BHuan+Liu&year=2011&doi=10.1007%2Fs10618-010-0210-x&url=https%3A%2F%2Fdoi.org%2F10.1007%2Fs10618-010-0210-x&source=blog-reference))

Veličković, P., Cucurull, G., Casanova, A., Romero, A., Liò, P., & Bengio, Y. (2018). Graph attention networks. *International Conference on Learning Representations*. https://arxiv.org/abs/1710.10903 ([PDF 보기](/paper-viewer?title=Graph+attention+networks&authors=Petar+Veli%C4%8Dkovi%C4%87%3BGuillem+Cucurull%3BArantxa+Casanova%3BAdriana+Romero%3BPietro+Li%C3%B2%3BYoshua+Bengio&year=2018&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1710.10903.pdf&arxiv_id=1710.10903&url=https%3A%2F%2Farxiv.org%2Fabs%2F1710.10903&source=blog-reference))

Xu, K., Hu, W., Leskovec, J., & Jegelka, S. (2019). How powerful are graph neural networks? *International Conference on Learning Representations*. https://arxiv.org/abs/1810.00826 ([PDF 보기](/paper-viewer?title=How+powerful+are+graph+neural+networks%3F&authors=Keyulu+Xu%3BWeihua+Hu%3BJure+Leskovec%3BStefanie+Jegelka&year=2019&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1810.00826.pdf&arxiv_id=1810.00826&url=https%3A%2F%2Farxiv.org%2Fabs%2F1810.00826&source=blog-reference))