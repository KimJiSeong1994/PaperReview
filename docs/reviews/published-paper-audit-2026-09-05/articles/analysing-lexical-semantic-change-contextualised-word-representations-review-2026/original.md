# Giulianelli, Del Tredici & Fernández 2020 심층 분석: "Analysing Lexical Semantic Change with Contextualised Word Representations" 해설

**Paper:** Giulianelli, Mario; Del Tredici, Marco; Fernández, Raquel. (2020). "Analysing Lexical Semantic Change with Contextualised Word Representations." *Proceedings of the 58th Annual Meeting of the Association for Computational Linguistics (ACL 2020)*, pp. 3960–3973. arXiv:2004.14118.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 한 단어를 시대별 벡터 하나로 뭉개는 정적 임베딩의 전제를 버리고, 문맥에 따라 다른 벡터를 내주는 문맥화 임베딩으로 단어의 여러 용법을 갈라 의미 변화를 비지도로 추적할 수 있는가? |
| 핵심 기여 | 문맥화 표현(BERT)을 쓴 첫 비지도 의미 변화 접근. 코퍼스에서 대상 단어의 모든 출현을 BERT로 벡터화하고, K-평균으로 군집해 자동으로 정해지는 수의 용법 유형(usage type)을 만든 뒤, 시대별 용법 유형 분포의 변화를 잰다. 3,285개 용법 쌍에 380명의 유사도 판단을 모은 새 평가 데이터셋도 함께 내놓는다. |
| 방법적 결과 | 세 지표를 제안한다. 엔트로피 차이 ED(다의성 폭의 증감: 양이면 광의화, 음이면 협의화), 옌센-섀넌 발산 JSD(어느 유형이 커지고 줄었는지 반영), 평균 쌍별 거리 APD(군집 없이 두 시대 벡터의 쌍별 거리 평균). 파인튜닝 없는 BERT base의 전 층 합산 벡터를 쓰고, 군집 수 K는 실루엣 점수로 [2, 10]에서 자동 선택한다. |
| 실험 결과 | COHA(1910–2009)·GEMS 99단어에서 세 지표 모두 사람 변화 점수와 유의한 양의 스피어만 상관(ED 0.278, JSD 0.276, APD 0.285; 빈도 baseline 0.068만 비유의). 용법 유형은 다의어·동음이의어·문자/은유 용법·통사 역할을 가르고, coach의 협의화·disk의 광의화·curtain의 은유화를 짚는다. |
| 핵심 한계 | 상관값이 같은 스피어만 척도의 선행 두 편(0.386, 0.377)보다 낮고, 셋 중 최고인 APD가 정작 중심 장치인 용법 유형 군집을 쓰지 않는다. 평가가 영어·COHA·99단어에 좁고, 용법 유형은 사전적 의미와 어긋나기도 한다(저자 자인). 임베딩 공간의 이방성도 다뤄지지 않는다. |

**TL;DR** — (1) **Giulianelli et al.**(ACL 2020)은 **BERT** 용법 벡터를 K-평균으로 군집한 **용법 유형(usage type)** 분포로 의미 변화를 재는 첫 비지도 문맥화 접근으로, ED(다의성 폭)·JSD(유형 분포 변화)·APD(군집 없는 쌍별 거리) 세 지표를 제안한다. (2) COHA·GEMS 99단어에서 세 지표 모두 사람 판단과 유의한 양의 상관(약 0.28)을 보이지만 같은 척도의 선행 두 편(0.386·0.377)보다 낮고, 최고 지표 APD는 군집을 쓰지도 않는다. (3) 이 논문의 실제 값어치는 리더보드 숫자보다 해석 도구에 있다 — 용법 유형을 보면 coach의 협의화, disk의 광의화, curtain의 은유화처럼 어느 의미가 어떻게 변했는지가 눈에 짚인다.

---

## 목차

1. 서론
2. 방법: 용법 기반 세 단계
3. 세 지표: ED·JSD·APD
4. 실험과 결과
5. 정성 분석: 용법 유형은 무엇을 잡는가
6. 주의해서 읽을 점
7. 결론

---

## 1. 서론

### 1.1 배경과 문제

통시적 의미 변화 탐지의 오랜 방식은 정적 임베딩이었다. 시대별 코퍼스로 임베딩을 따로 학습하거나(Gulordava & Baroni, Kulkarni), 점진적으로 갱신하거나(Kim), 사후에 공간을 정렬해(Hamilton) 같은 단어의 벡터가 시대 간 얼마나 움직였는지를 거리로 쟀다. 동적 임베딩(Bamler & Mandt, Rudolph & Blei) 계열도 시대를 잇는 벡터 궤적을 학습했다.

저자들이 지목하는 이 계열의 공통 약점은 하나다. 한 단어를 표현하는 벡터가 시대마다 하나뿐이라, 그 단어가 동시에 지닌 여러 용법을 한 점으로 뭉갠다는 것이다. 논문 표현으로 "형태 기반 모델은 한 단어의 서로 다른 용법을 표현하는 데 벡터 하나로 충분하다는 강한 단순화에 기댄다". 의미 기반(sense-based) 계열(SCAN 등)이 이를 의미 분포로 보완하려 했으나, 문맥을 단어 가방으로만 보고 의미 개수를 사람이 고정해 두는 한계가 있었다.

### 1.2 용법 기반 재정의와 위치

이 논문은 문제를 용법 기반으로 다시 짠다. 의미(sense)를 미리 정한 이산적 목록으로 두지 않는다. 저자들은 의미란 "본래 연속적이고 문맥이 조율하는 단어 뜻을 이산화한 것"이라 보고, 고정된 의미 목록 대신 BERT 용법 벡터를 군집해 **자동으로 정해지는 수의 용법 유형**을 만든다. 문맥화 임베딩은 이미 WiC나 WSD 같은 용법 과제에서 성능이 확인됐지만, 그 쓰임은 지도 학습이나 의미 유도에 머물렀다. 비지도 통시 변화 탐지에 문맥화 임베딩을 처음 가져온 것이 이 논문이 주장하는 자리다.

논문은 서론 끝에 다섯 가지 기여를 명시한다. (1) 문맥화 표현을 쓴 첫 비지도 의미 변화 접근, (2) 이 표현으로 변화를 재는 여러 지표, (3) 3천 쌍이 넘는 용법 유사도 사람 판단으로 이뤄진 새 평가 데이터셋, (4) 모델 표현과 탐지된 변화가 모두 사람 직관과 양의 상관을 보인다는 검증, (5) 단어 의미·통사 기능·문자와 비유 용법 같은 공시적 현상과 협의화·광의화 같은 통시적 과정을 함께 잡아낸다는 정성 분석이다. 변화 유형을 다룰 때는 Hamilton식 통계 법칙 대신 전통 언어학의 협의화·광의화(그리고 은유화)를 프레임으로 쓴다.

---

## 2. 방법: 용법 기반 세 단계

방법은 세 단계로 정리된다(원논문 §3). 대상 단어의 출현을 벡터화하고, 그 벡터들을 용법 유형으로 군집하고, 시대 간 변화를 지표로 잰다.

![용법 표현과 용법 유형 분포](/api/blog/figures/giulianelli-fig1-usage-types-atom.png)

*COHA에서 뽑은 단어 atom의 용법 표현과 용법 유형 분포(원논문 Figure 1). (a) 용법 벡터를 2차원으로 투영하면 세 용법 유형이 색으로 갈린다. (b) 시대별 용법 유형 분포에서 파란 유형이 1940~50년대에 급격히 솟는다(원자·핵물리 맥락의 용법으로 읽힌다).*

**출현을 벡터로.** 대상 단어 $w$가 문장 $s$의 위치 $i$에 나오면, BERT의 모든 은닉 층 활성을 그 위치에서 뽑아 차원별로 더한다. 마지막 네 층만 쓰거나 이어 붙이는 대신 전 층을 더하는데, 층을 골라 쓰거나 이어 붙여도 벡터 간 상대 거리에 큰 차이가 없었기 때문이다. 쓰는 모델은 파인튜닝하지 않은 BERT base-uncased(12층, 768차원, 1억 1천만 파라미터)다. 한 단어의 출현 벡터 $N$개가 용법 행렬 $U_w$를 이루고, 각 벡터에는 128토큰 문맥창과 시대 라벨이 붙는다.

**용법 유형으로 군집.** 용법 행렬을 표준화한 뒤 K-평균으로 군집한다. 군집 수 $K$는 단어마다 실루엣 점수가 가장 높은 값으로 자동 선택하며, 범위는 $[2, 10]$이다. 초기값 영향을 줄이려 각 $K$에서 10회 실행해 왜곡(중심까지 제곱거리 합)이 가장 작은 결과를 취한다. $K=1$은 실루엣 점수가 정의되지 않아 제외하는데, 이 때문에 모든 단어가 최소 두 개의 용법 유형으로 갈린다(뒤의 협의점). 각 시대 $t$에서 용법 유형 $k$의 빈도를 세면 빈도 분포 $f^t_w$가, 이를 정규화하면 용법 유형에 대한 확률 분포 $u^t_w$가 나온다.

**시대 간 변화를 측정.** 이 분포와 벡터를 재료로 세 지표를 계산한다(3장). 시대가 둘보다 많으면 이웃한 시대 쌍마다 변화를 재 벡터로 모은 뒤, 그 벡터의 평균과 최댓값을 스칼라 점수로 삼는다. 평균은 기간 전체의 변화를, 최댓값은 가장 강한 변화가 일어난 시대 쌍을 짚는다.

---

## 3. 세 지표: ED·JSD·APD

논문은 변화를 재는 세 지표를 제안한다(§3.4). 앞 둘은 군집한 용법 유형 분포에 기대고, 셋째는 군집을 건너뛴다.

**엔트로피 차이(ED).** 한 시대 용법 분포 $u^t_w$의 정규화 엔트로피 $\eta$를 재고, 두 시대의 차 $\eta(u^{t'}_w) - \eta(u^t_w)$를 본다. 엔트로피는 용법의 불확실성, 곧 다의성의 폭이라 볼 수 있다. ED가 양이면 용법이 늘어난 광의화, 음이면 줄어든 협의화로 해석한다.

**옌센-섀넌 발산(JSD).** 두 시대 용법 유형 분포 사이의 옌센-섀넌 발산이다. 엔트로피 차이가 다의성의 총량 변화만 본다면, JSD는 어느 유형이 커지고 어느 유형이 줄었는지까지 반영한다. 두 분포가 많이 다르면 값이 크고, 유형 비율이 거의 그대로면 작다.

**평균 쌍별 거리(APD).** 앞 두 지표와 달리 군집을 거치지 않는다. 두 시대의 용법 벡터를 모두 짝지어 거리를 잰 평균이다. 거리는 코사인·유클리드·캔버라를 시험했다. 군집에 기대지 않으므로 군집 오류에 휘둘리지 않는다는 것이 APD의 성질이다. 뒤에서 보듯 이 성질이 정성 분석에서 실제로 값을 한다.

세 지표를 논문이 §2에서 정리한 형태 기반 대 의미 기반 구도에 견주면, ED·JSD는 (사전적 의미가 아니라 데이터가 정한 용법 유형이지만) 이산 분포에 기댄다는 점에서 의미 기반의 구조를, APD는 벡터 거리만 본다는 점에서 형태 기반의 구조를 닮았다. 한 논문이 두 계열을 닮은 지표를 함께 내놓고 견준다.

---

## 4. 실험과 결과

### 데이터와 대상 단어

코퍼스는 COHA(Corpus of Historical American English)로, 두 세기(1810~2009)의 영어를 담는다. 저자들은 10년당 최소 2100만 단어가 확보되는 1910~2009년만 쓴다. 대상 단어는 Gulordava와 Baroni(2011)가 의미 변화 점수를 매긴 100단어인데, COHA에 세 시대밖에 안 나오는 extracellular를 빼 99단어로 삼고 이를 'GEMS 데이터셋'이라 부른다. 이 점수는 다섯 명의 평가자가 각 단어의 1960년대와 1990년대 사이 변화 정도를 매긴 값이다. 이 99단어의 출현 약 130만 개를 BERT로 벡터화해 용법 유형으로 군집한다.

### 새 유사도 데이터셋

논문의 세 번째 기여는 크라우드소싱으로 만든 새 평가 데이터셋이다. GEMS 점수 값마다 단어를 하나씩 무작위로 뽑아 16단어를 고르고, 단어마다 용법 유형별로 5개 용법을 시대를 달리해 표집한 뒤, 가능한 모든 쌍을 만들어 총 3,285개 용법 쌍을 얻는다. 각 쌍에 5개씩, 무관에서 동일까지 4점 척도의 유사도 판단을 380명이 매겼다. 평가자 간 일치도(평균 쌍별 스피어만)는 0.59로, 선행 연구(Schlechtweg 등의 0.57~0.68) 범위 안이다.

### 지표는 사람 판단과 맞는가

검증은 두 갈래다. 하나는 용법 유형 군집이 사람의 유사도 판단을 반영하는지다. BERT가 만든 유사도 행렬과 사람 유사도 행렬을 맨텔 검정으로 비교하니, 16단어 중 10단어에서 유의한(p<0.05) 양의 상관이 나왔고 계수는 0.13에서 0.45 사이였다. 다른 하나는 변화 점수가 GEMS 정답과 맞는지다. 결과는 아래와 같다(원논문 Table 1, 스피어만 ρ).

| 방법 | GEMS 정답과의 상관 |
|---|---|
| 빈도 차이(baseline) | 0.068 (유일하게 비유의) |
| 엔트로피 차이 ED (max) | 0.278 |
| 옌센-섀넌 발산 JSD (max) | 0.276 |
| 평균 쌍별 거리 APD (Euclidean, max) | 0.285 |
| Gulordava & Baroni (2011) | 0.386 |
| Frermann & Lapata (2016, SCAN) | 0.377 |

세 지표 모두 유의한 양의 상관을 보였고, 빈도 baseline만 유의하지 않았다. 시대 쌍 집계는 최댓값이, APD 거리는 유클리드가 가장 좋았다. 논문은 이 결과를 문맥화 표현이 의미 변화를 잡을 잠재력이 있다는 고무적 신호로 읽는다.

두 가지를 짚어 둘 만하다. 첫째, 세 지표의 값(약 0.28)은 논문이 참고로 나란히 실은 선행 연구 두 편보다 낮다. 계수 기반 Gulordava & Baroni가 0.386, 의미 기반 SCAN(Frermann & Lapata)이 0.377이다. Table 1 캡션이 밝히듯 두 값은 모두 스피어만 상관이고(G&B의 0.386은 직접 비교를 위해 Frermann & Lapata가 다시 계산한 스피어만 값이다), 이 논문의 지표와 곧바로 비교된다. 같은 척도에서 문맥화 지표가 더 오래된 두 방법에 뒤진다. 둘째, 셋 중 가장 나은 APD가 군집을 전혀 쓰지 않는다. 논문 자신도 "APD가 용법 유형 군집에 기대지 않으면서도 JSD·ED만큼 유용할 수 있다"고 적는다. 정량 수치만 보면 이 논문의 중심 장치인 용법 유형 군집이 값을 못 한다. 저자들의 답은 다음 장에 있다. 용법 유형의 값어치가 숫자보다 분석 도구 쪽에 있다는 것이다.

---

## 5. 정성 분석: 용법 유형은 무엇을 잡는가

논문의 후반(§6)은 용법 유형을 정성적으로 뜯어본다. 각 단어의 용법 유형에서 중심에 가장 가까운 다섯 벡터의 문장을 대표 용법으로 뽑아 읽는 식이다.

### 무엇을 가르는가 (§6.1)

용법 유형은 다의어·동음이의어의 밑뜻을 가른다. curious는 '기이한'과 '탐구적인' 두 유형으로, 동음이의어 coach는 '탈것'과 '지도자'로 갈린다. 문자적 용법과 비유적 용법도 나뉜다. curtain은 천으로서의 문자적 뜻 둘과 정보를 가르는 장벽이라는 은유적 뜻 둘, 네 유형으로 나뉜다. sphere도 구체라는 문자적 뜻과 영역·지구라는 은유·환유적 뜻으로 갈린다. 통사 역할과 논항 구조도 잡는다. refuse는 명사 용법, 자·타동사 용법, 부정사 보어를 취하는 동사 용법으로 나뉜다. 예상 밖의 가름도 있다. doubt는 명사·동사로 갈리지 않고 긍정 문맥('there is still doubt')과 부정 문맥('not a bit of doubt')으로 갈린다. 사전적 품사보다 분포 문맥을 잡는다는 신호다. iron curtain 같은 연어, alexander graham bell 같은 고유명사도 별도 유형으로 떨어진다.

물론 오류도 있다. 최소 군집 수를 2로 둔 탓에 maybe처럼 한 유형이면 될 단어가 억지로 쪼개진다. 반대로 tenure처럼 한 뜻이 독립 유형으로 안 잡히고 여러 군집에 흩어지기도 한다. address는 '예의·태도'라는 명사 뜻과 'network address'를 한 유형에 섞어 담는다(정작 '연설' 뜻은 제대로 갈렸다). 용법 유형이 곧 사전적 의미는 아니라는 신호다.

### 어떤 변화를 잡는가 (§6.2)

시대 축으로 보면 협의화와 광의화가 드러난다.

![네 단어의 용법 유형 진화](/api/blog/figures/giulianelli-fig2-change-kinds.png)

*coach·tenure·curtain·disk의 용법 유형 분포 변화(원논문 Figure 2, 1910~2009). coach는 '탈것' 용법(주황)이 줄고 '지도자' 용법(초록)이 커지는 협의화, disk는 광학·컴퓨터 디스크 용법(주황)이 1950년대부터 새로 솟는 광의화를 보인다.*

**협의화.** 어떤 용법 유형이 시간이 지나며 사라지거나 드물어진다. coach는 '탈것' 용법이 기술 변화로 점차 줄어드는데, 음의 평균 ED가 이를 잘 짚는다(coach의 ED가 GEMS 단어 중 최저권). 다만 ED는 옛 유형이 사라지는 동시에 새 유형이 솟으면 엔트로피가 안 줄어 협의화를 놓친다. tenure가 그 예로, 토지 보유라는 옛 뜻이 낡아 가는데도 새 유형(교수 임용의 tenure)이 생겨 평균 ED가 오히려 양이 된다.

**광의화.** 반대로 새 용법 유형이 생긴다. disk는 1950년대부터 기술 혁신으로 광학·컴퓨터 디스크 용법이 붙는다. 광의화의 특수한 경우가 은유화다. curtain의 은유적 유형(iron curtain, 철의 장막)은 1930~40년대에 생겨 1950년대에 정점을 찍고 1970년대부터 낮게 안정된다. 광의화를 가장 잘 잡는 지표는 JSD와 APD인데, 둘의 순위가 갈리기도 한다. curtain은 새 용법의 상대 빈도가 낮아 APD 점수는 낮지만, JSD는 그 유형을 가려내 변화를 잡는다. 거꾸로 address는 군집 오류 탓에 JSD 점수가 낮지만, 군집을 안 쓰는 APD가 높은 변화 점수를 준다. GEMS 전체 상관으로는 군집 기반 지표가 APD에 군더더기처럼 보였지만, 이런 단어별 탐지에서는 둘이 서로의 약점을 메운다. 평균으로는 겹쳐도 단어 단위로는 상보적이다.

끝으로 논문은 한계를 자인한다. 지표들은 광의화가 일어났다는 것은 잡아도 어떤 종류의 광의화인지는 못 짚는다. 은유화를 가리려면 은유의 출발 유형과 도착 유형을 잇는 유형 간 비교가 필요한데, 이는 후속 과제로 남긴다.

---

## 6. 주의해서 읽을 점

### 6.1 정량 성능이 선행보다 낮다 (논문 외 비판)

논문의 헤드라인은 세 지표가 사람 판단과 유의한 양의 상관을 보인다는 것이다. 사실이지만, 그 값(0.276~0.285)은 논문이 같은 표에 실은 선행 두 편(0.386, 0.377)보다 낮다. 두 값 모두 스피어만이라(G&B의 0.386도 직접 비교를 위해 다시 계산한 스피어만 값이다) 같은 척도의 맞비교이고, 이 논문의 문맥화 지표가 계수 기반 모델과 더 오래된 의미 기반 모델 양쪽에 뒤진다. 무거운 BERT 장치가 더 단순한 방법을 이겼다는 근거는 이 실험에 없다.

### 6.2 최고 지표가 군집을 안 쓴다 (논문 외 비판)

세 지표 중 가장 나은 APD는 용법 유형 군집을 전혀 거치지 않는다. 그런데 이 논문의 중심 기여가 바로 그 군집(용법 유형)이다. 정량 리더보드만 보면 핵심 장치가 값을 못 한다. 논문은 이를 정직하게 인정하고, 용법 유형의 값어치를 정성 해석으로 옮긴다(5장). 이 이동은 설득력이 있으나, 그렇다면 이 논문의 기여는 "변화를 더 잘 재는 지표"가 아니라 "변화를 들여다보는 도구"로 다시 읽혀야 한다. 정량 평가가 뒷받침하지 못하는 기여를 정성 사례로 옹호하는 구조라, 얼마나 일반화되는지는 사례 밖에서 확인되지 않는다.

### 6.3 임베딩 공간의 기하를 다루지 않는다 (논문 외 비판)

APD는 BERT 벡터 사이 거리를, K-평균은 유클리드 거리를 쓴다. 그런데 문맥화 임베딩은 좁은 원뿔에 몰려 무작위 두 벡터도 유사도가 높게 나오는 이방성이 있다고 알려져 있다. 전 층을 합산한 벡터에 거리 기반 지표와 유클리드 군집을 얹으면 이 기하 왜곡이 거리와 군집 양쪽에 스밀 수 있는데, 논문은 이방성을 언급하지 않는다. 거리·군집이 방법의 뼈대인 만큼 짚였어야 할 빈칸이다.

### 6.4 군집 불안정과 좁은 평가 (논문 외 비판)

군집 기반 지표(ED·JSD)는 실루엣으로 고른 K-평균의 잡음을 그대로 물려받는데, 논문은 군집 안정성 분석이나 선택된 $K$의 분포를 보고하지 않는다. 최소 $K=2$ 제약은 5장에서 본 maybe 과분할처럼 단의어를 억지로 쪼갠다. 평가 자체도 좁다. 언어는 영어뿐, 코퍼스는 COHA 하나, 변화 탐지 대상은 99단어, 새 유사도 데이터셋은 16단어에 평가자 일치도 0.59다. 결론의 일반화 여지가 이만큼 제한된다.

### 6.5 용법 유형은 사전적 의미가 아니다 (저자 자인)

저자들이 §6.1에서 스스로 밝히듯, 용법 유형은 사전적 의미와 어긋난다. 같은 뜻을 여러 유형으로 쪼개기도(maybe), 다른 뜻을 한 유형에 뭉치기도(address) 한다. 군집이 담는 것은 사전적 의미보다 용법의 덩어리다. 무엇이 변했는지를 설명하는 해석 도구로 쓰려면 이 간극이 남는다.

---

## 7. 결론

Giulianelli, Del Tredici, Fernández의 이 논문은 문맥화 임베딩으로 의미 변화를 잡은 첫 비지도 연구다. 정적 임베딩이 한 단어를 벡터 하나로 뭉갠다는 전제를 버리고, BERT 용법 벡터를 용법 유형으로 군집해 시대별 분포 변화를 세 지표(ED·JSD·APD)로 쟀다. 사전을 참고하지 않고 코퍼스만으로 여러 용법을 갈라낸다는 점, 의미 개수를 고정하지 않는다는 점이 선행 대비 강점으로 제시된다.

정량 결과는 겸손하다. 세 지표는 사람 판단과 유의하게 상관하지만 같은 스피어만 척도의 선행 두 편보다 낮고, 가장 나은 APD는 군집을 쓰지도 않는다. 이 논문이 실제로 내놓은 것은 더 높은 점수가 아니다. 용법 유형을 보면 **어느 의미가 어떻게 변했는지**가 눈에 짚인다는 해석 도구다. coach의 협의화, disk의 광의화, curtain의 은유화가 그 예다. 지표마다 강점이 갈려(협의화의 ED, 드문 새 용법의 JSD, 군집 오류에 강한 APD) 서로를 보완한다.

동시에 남는 물음도 뚜렷하다. 정량 성능이 선행에 못 미치고, 이방성 같은 임베딩 기하는 다뤄지지 않으며, 용법 유형과 사전적 의미 사이 간극은 저자들도 인정한다. 문맥화 임베딩으로 의미 변화를 처음 들여다본 이 작업은, "잰다"보다 "본다"에서 값을 하는 출발점으로 읽힌다.

---

## References

- Bamler, R., & Mandt, S. (2017). Dynamic word embeddings. In *Proceedings of the 34th International Conference on Machine Learning (ICML 2017)* (pp. 380–389). ([PDF 보기](/paper-viewer?title=Dynamic+Word+Embeddings&source=blog-reference&authors=Robert+Bamler%3BStephan+Mandt&year=2017&arxiv_id=1702.08359&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1702.08359.pdf))
- Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2019). BERT: Pre-training of deep bidirectional transformers for language understanding. In *Proceedings of the 2019 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies (NAACL-HLT 2019)* (pp. 4171–4186). ([PDF 보기](/paper-viewer?title=BERT%3A+Pre-training+of+Deep+Bidirectional+Transformers+for+Language+Understanding&source=blog-reference&authors=Jacob+Devlin%3BMing-Wei+Chang%3BKenton+Lee%3BKristina+Toutanova&year=2019&arxiv_id=1810.04805&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1810.04805.pdf))
- Frermann, L., & Lapata, M. (2016). A Bayesian model of diachronic meaning change. *Transactions of the Association for Computational Linguistics, 4*, 31–45.
- Giulianelli, M., Del Tredici, M., & Fernández, R. (2020). Analysing lexical semantic change with contextualised word representations. In *Proceedings of the 58th Annual Meeting of the Association for Computational Linguistics (ACL 2020)* (pp. 3960–3973). ([PDF 보기](/paper-viewer?title=Analysing+Lexical+Semantic+Change+with+Contextualised+Word+Representations&source=blog-reference&authors=Mario+Giulianelli%3BMarco+Del+Tredici%3BRaquel+Fern%C3%A1ndez&year=2020&arxiv_id=2004.14118&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2004.14118.pdf))
- Gulordava, K., & Baroni, M. (2011). A distributional similarity approach to the detection of semantic change in the Google Books Ngram corpus. In *Proceedings of the GEMS 2011 Workshop on Geometrical Models of Natural Language Semantics* (pp. 67–71).
- Hamilton, W. L., Leskovec, J., & Jurafsky, D. (2016). Diachronic word embeddings reveal statistical laws of semantic change. In *Proceedings of the 54th Annual Meeting of the Association for Computational Linguistics (ACL 2016)* (pp. 1489–1501). ([PDF 보기](/paper-viewer?title=Diachronic+Word+Embeddings+Reveal+Statistical+Laws+of+Semantic+Change&source=blog-reference&authors=William+L.+Hamilton%3BJure+Leskovec%3BDan+Jurafsky&year=2016&doi=10.18653%2Fv1%2FP16-1141&url=https%3A%2F%2Fdoi.org%2F10.18653%2Fv1%2FP16-1141))
- Rousseeuw, P. J. (1987). Silhouettes: A graphical aid to the interpretation and validation of cluster analysis. *Journal of Computational and Applied Mathematics, 20*, 53–65.
- Schlechtweg, D., Schulte im Walde, S., & Eckmann, S. (2018). Diachronic usage relatedness (DURel): A framework for the annotation of lexical semantic change. In *Proceedings of the 2018 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies (NAACL-HLT 2018)* (pp. 169–174).