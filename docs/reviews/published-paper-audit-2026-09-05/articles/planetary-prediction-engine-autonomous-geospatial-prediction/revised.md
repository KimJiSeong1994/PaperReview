# Planetary Prediction Engine: Autonomous Geospatial Prediction via Intelligent Data Selection and Foundation Model Embeddings

**Paper:** Evelyn Ma; Rama Kumar Pasumarthi; Kishwar Shafin; Mandar Sharma; Mimi Sun; Hamed Sadeghi; Dav M. Ebengo; Mbulayi Onesime; Rouslan Solomakhin; John Wamburu; William Ogallo; Aisha Walcott-Bryant; Sanxing Chen; Arbaaz Muslim; Yael Mayer; Ronald Ho; Roy Lee; Ruth Alcantara; Abdoulaye Diack; Monica Bharel; Lambert Rosique; Jeremy Amez-Droz; Christopher Haire; James Manyika; Yossi Matias; Niv Efron; Gautam Prasad; Shravya Shetty (2026). "Planetary Prediction Engine: Autonomous Geospatial Prediction via Intelligent Data Selection and Foundation Model Embeddings". https://arxiv.org/abs/2608.26088v1 · arXiv:2608.26088v1

**Abstract:** 지구 규모 예측 모형을 만드는 일은 데이터 생태계가 흩어져 있어 병목에 걸린다. 자료를 손으로 찾아오고, 다중 모달 자료를 큐레이션해 합치고, 모델을 반복해서 고르는 일이 사람 몫이기 때문이다. 이 논문은 그 전 과정을 자연어 질의 하나에서 끝까지 실행하는 자율 시스템 PPE를 제안한다. 열린 웹과 지구관측 플랫폼에서 시공간적으로 관련 있는 공변량을 끌어와 지리공간 파운데이션 모델 임베딩과 융합하고, 과제에 맞는 모델 계열을 과적합 방어 장치와 함께 탐색한다. 여러 지리 예측 과제에서 종류가 다른 기준선과 비교한 결과를 보고한다.

---

## Executive Summary

| 항목                           | 설명                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 연구 질문                        | 지리공간 예측 모형을 만드는 전 과정(자료 발견 → 다중 모달 융합 → 모델 탐색)을 자연어 질의에서 자동으로 실행할 수 있는가. 그렇게 만든 모형이 전문가가 손으로 맞춘 파이프라인을 이길 수 있는가.                                                                                                                                                                                                                                                                                                                                                                                                                          |
| 핵심 기여                        | ① 자료 발견·큐레이션·모델 탐색의 세 modular stage를 LLM 오케스트레이터가 잇고 보고서 생성으로 연결한다. ② Data Commons·Google Earth Engine·열린 웹에서 공변량을 자동 수집하고 PDFM·AlphaEarth 임베딩과 융합. ③ 타깃 누출 방어를 목표로 하는 Feature Gate와 과적합 방어 프로토콜. ④ 세 예측 패러다임(나우캐스팅·초해상 다운스케일링·공간회귀)에 걸친 여섯 벤치마크 × 두 대륙에 걸친 벤치마크.                                                                                                                                                                                                                                                                                 |
| 실험 결과 (저자 보고, 표에서 확인되는) | 미국 공간회귀에서 CDC 건강 지표 21종 평균 $R^2$ 76.8%, FEMA 위험지수 64.9%, SVI 66.2%. 나이지리아 식량안보 다운스케일링 66.1%. DRC Ebola 나우캐스팅 Recall@10 83.3%(5주간 새로 침범된 18개 보건구역 중 15개 적중).                                                                                                                                                                                                                                                                                                                                                                               |
| 핵심 한계                        | ① **헤드라인 비교쌍 네 개의 기준선이 종류가 제각각**이다. CDC·FEMA는 같은 팀의 직전 논문, SVI는 PPE 자신의 단일 모달 절제(논문 §2.4.3이 명시), 나이지리아는 보간 기준선이다. ② CDC 절제에서는 PDFM+AEF에 자동 수집 공변량을 더할 때 점추정치가 61.8에서 76.8로 증가한다. 다만 부록의 사용 변수에는 Feature Gate가 배제 예시로 든 계수형 센서스 변수도 남아 있어 적용 범위를 확인하기 어렵다. ③ CDC·FEMA는 인구조사 표준지역 단위 **무작위 80:20 분할**을 사용하므로 공간적으로 분리된 역외 일반화 성능은 별도 검증이 필요하다. ④ Ebola의 PPE 구간 [60.8, 94.2]에는 기준선 점추정치 73이 포함되지만 기준선 CI와 차이의 CI는 없다. ⑤ §2.4.1의 "23 percentage point"는 산술 오류(실제 16.8)이고, 부록 F.2의 대상별 값이 본문 Table 6의 두 칸과 5.9·7.7점 어긋난다. |

---

## 목차

1. 서론 — 흩어진 자료 생태계라는 문제
2. 시스템 — 세 단계 파이프라인
3. 무엇이 자동화되었나 — 자료 선택·누출 방어·모델 탐색
4. 실험 설계와 기준선의 정체
5. 공간회귀 결과 — CDC · FEMA · SVI
6. 초해상 다운스케일링 — 나이지리아 · SVI
7. Ebola 나우캐스팅
8. 수치를 어떻게 읽을 것인가
9. 한계와 결론

## 1. 서론 — 흩어진 자료 생태계라는 문제

### 1.1 문제 설정

논문의 출발점은 방법론이 아니라 **작업 부하**다. 식량안보·재난위험·질병발생·사회경제적 취약성 같은 문제에 고품질 지리공간 모형이 필요한데, 그 모형을 만드는 일이 "fragmented data ecosystem"에 막혀 있다는 것이다. 구체적으로는 셋이 사람 몫으로 남는다. 자료를 손으로 찾아 내려받는 일, 여러 모달의 자료를 큐레이션하고 융합하는 일, 그리고 모델을 반복해서 고르는 일이다.

### 1.2 논문의 답

답은 그 세 가지를 하나의 자율 파이프라인에 넣는 것이다. 사용자가 자연어로 질의하면 시스템이 시공간적으로 관련 있는 공변량을 열린 웹과 지구관측 플랫폼(Data Commons, Google Earth Engine)에서 끌어오고, 지리공간 파운데이션 모델 임베딩(PDFM, AlphaEarth)과 융합한 뒤, 과제에 맞는 모델 계열을 과적합 방어 장치와 함께 탐색한다.

![Figure 1: PPE 전체 워크플로](/api/blog/figures/ppe-fig1-workflow.png)

*그림 1. Ma et al. (2026), Figure 1의 원도판. PPE의 자료 선택·다중 모달 큐레이션·모델 탐색·보고서 생성 흐름을 보여준다. 세 modular stage 뒤 보고서 생성으로 이어진다. [arXiv](https://arxiv.org/abs/2608.26088v1) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).*

### 1.3 논문의 지위

| 항목 | 값 |
| --- | --- |
| 발표 형태 | arXiv 프리프린트(2608.26088v1), 심사 통과 학회·저널 표기 없음 |
| 분류 | cs.AI(주), cs.LG |
| 분량 | 본문 5장 + 부록 A–F, 표 17개, 도판 4개 |
| 저자 | 28인. Google 계열 연구진이 중심이며 아프리카 지역 연구자들이 함께 이름을 올린다 |
| 공개물 | 자료 쪽 접근성은 밝힌다(부록 A의 Ebola 자료는 "publicly available through an open-access GitHub repository", Table 9·10이 공변량과 파운데이션 모델마다 Access Class를 명시). 다만 **PPE 시스템 자체의 공개**(코드·프롬프트 전체·벤치마크별 특징 명세·학습 산출물)는 표기를 찾지 못했다 |


---

## 2. 시스템 — 세 단계 파이프라인

### 2.1 단계 구성

파이프라인은 세 modular stage 뒤 보고서 생성으로 이어진다.

**Stage 1 — Intelligent Data Selection.** 자연어 질의를 받아 조인 가능한 다중 모달 DataFrame으로 바꾼다. 여섯 하위 단계로 분해된다. 사용자 학습자료에서 공간 입도·조인 키 형식·시간 범위를 뽑아내는 **지리 제약 발견**, 후보 공변량의 구조화된 Signal Guide를 만드는 **근거 있는 신호 발견**(필수 도메인 변수인 direct signal과 그 밖을 구분), 신호 유형에 따라 경로를 나누는 **기성 저장소 검색**(사회인구·경제·집계 환경통계는 Data Commons로, 픽셀 단위 접근이 필요한 래스터는 Earth Engine으로), 남은 신호에 대한 **즉석 열린 웹 탐색**(CDC·Census·WHO·UN OCHA HDX 등 정부 포털과 학술 저장소), 다섯 축 채점으로 고르는 **출처 우선 우선순위화**, 그리고 좌표계(EPSG:4326)와 날짜(ISO 8601)를 표준화해 하나로 합치는 **DataFrame 조립**이다.

**Stage 2 — Multimodal Dataset Curation.** 표형 공변량에 PDFM과 AlphaEarth 임베딩을 붙이고, 누출 방어(Feature Gate)와 분할 격리 대치를 거쳐 훈련·검증·시험 분할을 만든다.

**Stage 3 — Automated Model Prediction.** 과제 유형에 맞춰 목적을 정렬하고 네 모델 계열을 탐색한다.

단계 사이의 계약이 명시되어 있다는 점은 눈여겨볼 만하다. 1→2 경계에는 Opaque Handles, DataFrames & GeoJSON, No shared state가, 2→3 경계에는 Curated Handles, Train/Val/Test Sets, Opaque to LLM이 적혀 있다. 즉 LLM이 원자료를 직접 들고 다니지 않는다. §4.3은 예측 에이전트가 "자료를 가져오거나 변형하는 것이 금지된다(prohibited from fetching or mutating data)"고 못 박는다.

### 2.2 무엇을 LLM이 정하는가

논문이 명시하는 범위에서 LLM이 정하는 것은 질의 해석, 과제 유형 추론, 신호 가설 생성, 검색 경로 선택, 그리고 모델 탐색 전략이다. 결정적 코드로 규정된 것은 스키마 표준화와 §4.2.3의 특징 변환들이다. 왜도 $|\text{skew}|>1.0$이면 $\log(1+x)$, 1·99분위 클리핑, 피어슨 $|r|>0.95$인 쌍에서 하나 제거, Z-점수 표준화, 그리고 임베딩은 통계 변환 없이 L2 정규화만 한다는 규정이다. 임베딩에 차원별 표준화를 하지 않는 이유를 "semantic topology를 보존하기 위해"라고 적는데, 이 부분은 설계 의도가 분명하다.

다만 한 단계 **안에서** 무엇이 모델 출력이고 무엇이 코드인지는 대부분 규정되지 않는다. 다섯 축 채점 루브릭을 누가 적용하는지, 과적합 위험 휴리스틱을 누가 돌리는지, 자기 교정 루프가 LLM 판단인지 코드 분기인지가 그렇다.

---

## 3. 무엇이 자동화되었나 — 자료 선택·누출 방어·모델 탐색

### 3.1 출처 우선 채점 루브릭

후보 데이터셋을 고르는 기준은 다섯 축이다.

| 축 | 가중 | 배점 |
| --- | --- | --- |
| Provenance & License | 높음 (×5) | 공개 라이선스의 기성 저장소 4점 → 정부·NGO 공개자료 3점 → 출처표시 필요 학술자료 2점 → 제한적·불명 라이선스 0점 |
| Spatio-Temporal Fitness | 중간 (×2) | 대상 지역의 공간 포괄과 예측 창과의 시간 중첩 (배점 없음) |
| Signal Alignment | 높음 (×3) | 정확한 변수 일치 4점 → 변환 필요 3점 → 대리 변수 2점 → 주변적 0점 |
| Format & Quality | 낮음 (×1) | 구조화·파싱 완료 4점 → 표준 상호운용 형식 2점 → 레거시·비정형 0점 |
| Redundancy | 낮음 (×1) | 고유 정보인지 상위 점수 출처의 중복인지 (배점 없음) |

출처와 라이선스에 가장 큰 가중을 둔 것은 자동 수집 시스템의 출처 불명 자료 위험을 우선순위에 반영한 설계다.

다만 루브릭은 절반만 규정되어 있다. 다섯 축 중 **둘(Spatio-Temporal Fitness, Redundancy)에는 배점 자체가 없고**, 축 점수를 어떻게 합치는지(가중합인지 다른 규칙인지)도, 몇 개를 남기는지 또는 어느 점수에서 자르는지도 적혀 있지 않다. 그리고 이 루브릭이 실제로 매긴 점수는 논문 어디에도 나오지 않는다. 서술은 있고 작동 증거는 없다. 가중 라벨도 어긋나는데, "높음"으로 표시된 두 축의 배수가 ×5와 ×3으로 다르다.

### 3.2 Feature Gate — 타깃 누출 방어

자동으로 공변량을 끌어오는 시스템에서 가장 위험한 실패는 타깃과 사실상 같은 변수를 특징으로 넣는 것이다. 자동 수집기가 Data Commons를 뒤지는데 예측 대상이 CDC PLACES 지표라면, 그 지표 자체나 그 재료가 후보에 섞여 들어올 수 있다. 논문은 이를 막는 장치를 §4.2.1에 둔다.

> "**Upon receiving the mathematical definition of the prediction target in the prompt**, the agent evaluates every candidate covariate against four mandatory anti-leakage criteria"

네 기준은 이렇다. ① 타깃 산식의 구성요소·직접 대리·하위지수를 배제한다(중위 임대료로 주거비 부담을 예측하지 말 것). ② 타깃과 똑같은 설문 자료나 대치 모형에 의존하는 변수를 배제한다. ③ 공변량은 인과적으로 **상류**여야 한다(원인·구조적 조건·병행 교란), 하류(결과·증상·반응)이면 안 된다. ④ 공변량은 예측 창 이전이나 그 안의 시점이어야 한다.

기준 자체는 잘 짜여 있고, 특히 ②는 같은 설문에서 파생된 변수를 겨냥한다는 점에서 이 문제를 아는 사람이 쓴 것이다. 그런데 **작동 방식이 LLM의 판단**이다. 상관 스크린도, 상호정보량 점검도, 홀드아웃 프로브도 없다. 코드도 통계도 임계값도 없이 네 개의 서술적 기준을 모델이 공변량마다 적용한다. 논문도 §3.5에서 기준 ③이 미해결임을 인정한다. "formal verification of causal direction filters remains an open challenge, particularly for targets with complex, bidirectional relationships to candidate covariates".

적용 범위를 판단하려면 **입력 조건**을 봐야 한다. 논문은 "프롬프트에서 타깃의 수학적 정의를 받으면" 후보 공변량을 평가한다고 설명한다. 부록 E의 프롬프트를 보면 그 정의가 완전히 주어진 곳은 한 곳뿐이다.

| 프롬프트 | 타깃 정의 |
| --- | --- |
| E.2.2 SVI 초해상 | **완전 제공**. `RPL_THEME1`을 다섯 지표의 백분위 순위 합으로 정의하고 `PercentileRank(x)=(Rank(x)-1)/(N-1)`, 동점 처리, 각 지표의 오름·내림 방향까지 적는다 |
| E.3.3 SVI 공간회귀 | 비공식. "a percentile rank based on **indicators like** poverty, unemployment, income, and education" |
| **E.3.1 CDC Health** | **없음**. "The target Variable: `Percent_Person_WithHighCholesterol`. Report the R-squared score." |
| **E.3.2 FEMA** | **없음**. "The Target Variable is {User_Target}." |

초록의 두 최대 수치(CDC 76.8, FEMA 64.9)를 낸 벤치마크의 프롬프트에는 타깃 산식이 없다. 논문은 수학적 정의가 없는 입력에서 게이트가 같은 기준을 어떻게 적용하는지 보고하지 않는다.

그리고 프롬프트를 보지 않아도 되는 더 직접적인 증거가 논문 안에 있다. 기준 ②는 이렇게 이어진다.

> "when predicting population-related targets, the system restricts covariates to **non-enumerative, intensive socioeconomic rates** (e.g., Median Income) rather than **enumerative counts (e.g., Count HousingUnit)** to guarantee zero census enumeration leakage."

인구 관련 타깃으로 판정된 경우에는 `Count HousingUnit` 류의 계수 변수를 쓰지 않는다는 예시다. 그런데 부록 F.2의 사용 변수 목록(Table 12~14)에는 **`Count_Person`·`Count_Household`·`Count_HousingUnit`·`Count_HousingUnit_Before1939DateBuilt`가 모든 FEMA 대상에 들어가 있다.** 대상 이름이 `Social Vulnerability`인 행도 예외가 아니고, Table 15를 보면 `Count_Person`과 `Count_HousingUnit_Before1939DateBuilt`는 자동 선택 단계를 거친 뒤에도 남는다. 논문은 각 FEMA 타깃이 이 제한의 적용 대상으로 판정됐는지는 밝히지 않는다.

같은 기준 ②의 괄호 예시는 "Exclude Census age/income demographics if predicting a synthetic 'Climate Vulnerability Score' derived from those same Census tables"인데, 그 대상에 실제로 쓰인 변수에는 `HouseholderAge65OrMoreYears`(연령)와 소득 구간 변수들이 들어 있다.

프롬프트에 타깃 정의가 없고 배제 예시와 겹치는 변수가 사용됐다는 사실 사이에는 긴장이 있다. 다만 해당 타깃이 제한의 적용 대상으로 판정됐는지와 실제 필터 로그가 공개되지 않았으므로, 이 기록만으로 게이트 실패나 누출을 확정할 수는 없다. 자동 수집 공변량을 더할 때 점수가 크게 달라지는 5장의 결과와 함께 검증해야 할 항목이다.

### 3.3 모델 탐색과 과적합 방어

모델 계열은 넷으로 소개된다. 정규화 선형, 히스토그램 기반 그래디언트 부스팅, XGBoost, MLP다. 다만 §2.3.1은 나이지리아 탐색이 "Ridge Regression, Lasso Regression, ElasticNet, **Random Forest**, Gradient Boosting, XGBoost"를 훑었다고 적는데, Random Forest는 이 넷에 없고 MLP는 그 목록에 없다. Table 8은 세 행으로 정리하며(부스팅 둘을 한 행에 묶는다) 하이퍼파라미터의 **이름만** 싣고 값·범위·격자는 싣지 않는다. 탐색이 순차인지 병렬 배치인지는 밝히지만, 탐색 알고리즘(격자·무작위·베이즈)도 값의 범위도 시도한 구성의 수도 적혀 있지 않다.

검증 전략은 셋이 제공된다. 무작위 80/20 분할, **Spatial Group Split**("지리 경계를 따라 분할해 **공간 자기상관 누출을 막고** 진짜 역외 일반화를 잰다"), 3-겹 교차검증이다. 두 번째 항목이 이 논문에서 가장 중요한 도구다. 벤치마크의 훈련·시험 분할 자체는 밝혀져 있지만(CDC·FEMA는 무작위 80:20, 나이지리아는 leave-one-state-out), **모델 선택 단계에서 이 세 전략 중 무엇을 썼는지**는 어느 벤치마크에 대해서도 명시되지 않는다.

과적합 방어는 두 층이다. 훈련 전 위험 평가는 표본 수 $n$, 특징 대 표본 비 $p/n$, 공간 그룹핑을 보고 위험을 낮음·중간·높음으로 분류해 중간이면 트리 깊이를 보수적으로, 높음이면 강한 정규화를 걸어 선형 모델 쪽으로 편향시킨다. 훈련 후 자기 교정은 검증 결과가 파국적 일반화 실패(음수 지표나 큰 훈련–검증 격차)를 보이면 모델을 버리고 정규화를 높여 다시 시작하며, **한 번만** 반복한다.

설계 의도는 분명하지만 **임계값이 하나도 주어지지 않는다.** 어떤 $n$과 $p/n$이 어느 위험 등급인지, "보수적 깊이"가 얼마인지, "큰 훈련–검증 격차"가 몇인지가 없다. 그리고 도판 4의 상자는 자기 교정 루프를 "Detect **test** degradation & restart search"라고 적는 반면 §4.3.2 본문은 **검증** 집합 평가가 방아쇠라고 쓴다. 본문이 맞다면 도판의 표기가 느슨한 것이고, 도판이 맞다면 방어 장치가 시험 집합을 읽는 셈이 된다. 논문은 이 차이를 그대로 둔다.

### 3.4 실행 프로파일

§4.4는 Ebola 사례 하나의 실행을 보고한다. 에이전트는 **793 스텝을 3개 세션에 걸쳐** 수행했다. 세션 1(15.8분)은 초기화와 **기준선 재현**, 세션 2(23.8분)는 특징 벡터화와 파이프라인 가속, 세션 3(15.6분)은 절제 평가와 하이퍼파라미터 탐색이다. 합쳐 55.2분이다.

한 시간이 채 안 되는 실행 기록은 신속한 위기 대응 가능성을 보여주는 시연이다. 다만 세션이 셋으로 끊긴 구조와 그 사이에 무엇이 있었는지는 밝히지 않는다.

---

## 4. 실험 설계와 기준선의 정체

### 4.1 벤치마크 매트릭스

세 예측 패러다임 × 두 대륙 × 여러 주제로 짜여 있다.

| 패러다임 | 지역 | 주제 | 벤치마크 | 예측 대상 | 훈련/시험 입도 | 규모 |
| --- | --- | --- | --- | --- | --- | --- |
| 나우캐스팅 | DRC | 인도적 위기·감염병 | DRC Ebola 확산 추적 | 1주 확진 증가 | Admin 3 보건구역 | 7주×519구역 / 5주×519구역 |
| 초해상 다운스케일링 | 나이지리아 | 식량안보 | Nigeria FCG | FCG 점수 | ADM1 → ADM2(LGA) | 30개 주×40개월 / 581 LGA×40개월 |
| 초해상 다운스케일링 | 미국 | 사회취약성 | SVI | 5개 지수 | County → ZCTA | ~3k / ~33k |
| 공간회귀 | 미국 | 공중보건 | CDC Health | 건강 지표 21종 | Census Tract | ~67k / ~17k |
| 공간회귀 | 미국 | 환경위험 | FEMA NRI | 위험 점수 21종 | Census Tract | ~67k / ~17k |
| 공간회귀 | 미국 | 사회취약성 | SVI | 5개 지수 | County | ~2.4k / ~0.6k |

폭은 이 계열에서 드물게 넓다. 자료가 풍부한 미국과 희소한 사하라 이남 아프리카를 함께 다루고, 정적 회귀와 시간에 민감한 나우캐스팅을 함께 넣었다.

표와 본문이 어긋나는 곳이 둘 있다. FEMA 대상 수와 공간 단위가 세 곳 대 두 곳으로 갈린다. Table 1("21 risk scores", Census Tract)·§2.1 본문("the FEMA National Risk Index (21 environmental indices)")·부록 A("Census-tract-level environmental and climate risk indices")가 한쪽이고, §2.4.2("**20** different **county-level** environmental and climate risk indices")와 Table 6의 Target Count 행(4/10/6/**20**)이 다른 쪽이다. SVI 초해상도 이 표는 County → ZCTA(~33k)인데 §2.1 본문은 "tested against high-resolution census tracts ($N\approx 84k$)"라고 적는다. ZCTA와 census tract는 다른 단위다.

### 4.2 절제 계층과 기준선

논문은 네 계층을 세운다.

- **Baseline / SOTA**: "전통적인 수동 전문가 파이프라인(도메인 전문가가 손으로 고른 특징과 격자 탐색 모델) **또는 단일 파운데이션 임베딩 기준선**"
- **PPE (Covariates)**: 임베딩 없이 원시 통계 공변량만
- **PPE (Embeddings)**: 표형 공변량 + PDFM/AEF
- **PPE (Full Stack)**: 공변량 + 임베딩 + Intelligent Data Selection

여기서 짚어야 할 것은 첫 계층의 정의가 **두 가지를 한 칸에 묶는다**는 점이다. 외부 전문가 파이프라인과 PPE 자신의 임베딩 단독 절제가 같은 이름으로 불린다. 그래서 초록의 "state-of-the-art or manually tuned expert baselines"는 항목마다 다른 것을 가리키게 된다. 표별로 풀면 이렇다.

| 헤드라인 | PPE | 비교 대상 | 비교 대상의 정체 |
| --- | --- | --- | --- |
| CDC | 76.8 | 60 | **Bell et al. (2025) "Earth AI"**(arXiv:2510.18318)의 수동 전문가 파이프라인(PDFM+AEF). 같은 팀의 직전 논문이며 저자가 겹친다 |
| FEMA | 64.9 | 59.9 (초록은 60.0) | 같은 [5]의 수동 전문가 파이프라인 |
| SVI 공간회귀 | 66.2 | 58.6 | **PPE 자신의 단일 모달 절제.** §2.4.3이 "we establish the SVI baseline as **the optimal performance attained across all unimodal embedding-only configurations**"라고 명시한다 |
| 나이지리아 | 66.1 | 31.5 | 거시 공변량 + 기본 보간 기준선 |

두 개의 "60.0"이 우연이 아닌 이유가 여기 있다. 같은 선행 파이프라인을 서로 다른 미국 인구조사 자료에 적용한 값이다. 초록은 이 계보를 밝히지 않는다.

SVI 항목은 논문이 본문에서 정직하게 밝힌다는 점을 함께 적어야 공정하다. §2.4.3은 그 기준선이 내부 절제임을 문장으로 쓴다. 다만 초록은 그 사실 없이 다른 세 항목과 같은 줄에 놓는다.

---

## 5. 공간회귀 결과 — CDC · FEMA · SVI

### 5.1 CDC 건강 지표 21종

| System | Feature Configuration | Mean $R^2$ [95% CI] (%) |
| --- | --- | --- |
| Baseline / SOTA | Manual Expert Pipeline (PDFM + AEF) | 60 (소수점·CI 없음) |
| PPE (Embeddings) | PDFM | **59.7** [58.6, 60.9] |
| PPE (Embeddings) | PDFM + AEF | 61.8 [60.6, 62.9] |
| PPE (Full Stack) | PDFM + AEF + Data Commons Covariates | **76.8** [76.1, 77.6] |

이 표는 구성요소별 점추정치가 함께 제시되어 증가 폭의 위치를 읽을 수 있다.

**첫째, 관측 증가 폭은 크다.** 60에서 76.8이면 16.8점이고, PPE 쪽 구간은 [76.1, 77.6]이다. 다만 기준선에는 구간이 없어 두 방법 간 차이의 불확실성을 직접 계산할 수는 없다.

**둘째, 가장 큰 인접 행 차이는 자동 공변량 추가와 함께 나타난다.** PPE가 PDFM만 쓰면 59.7이고 AEF를 더하면 61.8이다. 여기에 Data Commons 공변량을 붙인 전 구성은 76.8이다. 표의 인접 구성 간 점추정치 차이는 임베딩 추가 2.1점, 공변량 추가 15.0점이다. 다만 이 표만으로 각 구성요소의 순수 인과 효과를 확정할 수는 없고, 같은 조건에서 하나씩 제거한 절제가 필요하다.

**셋째, 본문의 산술이 틀렸다.** §2.4.1은 "the previous state-of-the-art (SOTA) manual expert pipeline achieves a mean $R^2$ of 60%, the PPE's ... drive mean $R^2$ to 76.8%, **a 23 percentage point improvement**"라고 적는다. 76.8 − 60 = 16.8이다. 상대 개선으로 읽어도 28%이고, 표의 다른 어떤 행을 기준으로 삼아도 23이 나오지 않는다.

### 5.2 FEMA 환경위험 지수

| 구성 | 사회경제·복합 (4) | 대기·기후 (10) | 지구물리·수문 (6) | 전국 전체 (20) |
| --- | --- | --- | --- | --- |
| PDFM + AEF 수동 전문가 | 61.1 | 64.6 | 51.1 | **59.9** |
| PDFM + AEF + DC | 66.9 [66.2, 67.5] | **64.3** [63.6, 65.0] | 51.7 [49.3, 53.7] | 61.1 [60.2, 61.7] |
| + Intelligent Data Selection | 69.4 [68.8, 70.0] | 68.3 [67.5, 68.9] | 56.2 [54.1, 57.8] | **64.9** [64.1, 65.5] |

여기서는 CDC와 관측 패턴이 다르다. 공변량을 붙일 때 전국 점추정치는 59.9 → 61.1로 1.2점 오르고, **대기·기후 열에서는 64.6 → 64.3으로 내려간다.** 자동 선택을 더한 다음 전국 값은 64.9로 3.8점 증가한다. 벤치마크별 증가 폭이 어느 구성 단계에서 나타나는지가 달라, "multimodal synergy"라는 단일한 설명만으로는 각 구성요소의 기여를 분해하기 어렵다.

부록 F.2는 이 표를 대상별로 펼친다(Table 12~17, 20개 대상 × 두 단계). 거기서 세 가지가 더 보인다.

**첫째, 후퇴하는 대상이 적지 않다.** Data Commons 공변량을 더했을 때 대기·기후 10개 중 6개가 내려가고(Winter Weather −2.02, Cold Wave −0.97, Wildfire −0.81, Ice Storm −0.81, Strong Wind −0.68, Tornado −0.01), 지구물리에서는 Hurricane이 −1.46이다. 자동 선택을 더한 뒤에도 Strong Wind(−4.48), Heat Wave(−3.72), Hurricane(−5.41), Earthquake(−6.14), Resilience Score(−1.00)가 이전 단계보다 낮다. 본문은 이 후퇴들을 지나간다.

**둘째, 부록의 대상별 값이 본문 Table 6과 맞지 않는다.** 자동 선택 단계의 대상별 값을 범주별로 평균 내면 사회경제·복합은 69.4로 Table 6과 일치하지만, 대기·기후는 **74.2**(Table 6은 68.3), 지구물리·수문은 **63.9**(Table 6은 56.2)다. 20개 대상 전체로는 부록 값이 **70.2%**인데 Table 6의 전국 칸은 64.9%다. 방향은 본문 쪽이 더 보수적인데, 어느 쪽이 맞는지는 논문에 없다. 앞 단계(Data Commons 절제)의 세 범주는 모두 일치하므로 파싱 문제로 보기도 어렵다.

**셋째, 범주 이득이 사실상 한 대상에서 나온다.** 사회경제·복합 범주의 61.1 → 66.9는 네 대상 중 Social Vulnerability 하나(48.24 → 67.55, **+19.31**)가 만든다. 나머지 셋은 −0.44, +2.38, +1.96이다. 이 대상이 8.3절에서 다시 나온다.

### 5.3 SVI 공간회귀

| System | Feature Configuration | Mean $R^2$ [95% CI] (%) |
| --- | --- | --- |
| Baseline | Foundation Model Signals | **60.3** [55.2, 64.9] |
| PPE (Covariates) | Geospatial Covariates | 50.2 [44.2, 55.6] |
| PPE (Full Stack) | Covariates + PDFM | **66.2** [61.6, 70.4] |

이 표는 초록과 맞지 않는다. 초록은 "66.2% vs. **58.6%**"로 적고 §2.4.3 본문도 "PDFM embeddings (R² = 58.6%) outperform both explicit covariates (51.6%) and AEF signals (45.1%)"라고 쓰는데, **58.6·51.6·45.1은 이 표의 어떤 행 값과도, 다른 어떤 표의 행 값과도 일치하지 않는다.** 표의 대응 행은 60.3과 50.2다. 전 구성의 이름도 다르다(본문 "Covariates + PDFM + AEF + Intelligent Selection" ↔ 표 "Covariates + PDFM").

숫자를 부르는 이름도 흔들린다. §1.3은 58.6을 "**statistical covariates** baselines"라 부르는데 §2.4.3은 같은 값을 "**PDFM embeddings**"라 한다. 그리고 §1.3의 "6.8 percentage point improvement"는 66.2 − 58.6 = 7.6과 맞지 않고, 같은 절의 "a 12% gain on SVI spatial regression (66.2% vs. 58.57%)"도 실제 13.0%와 다르다.

기준선 60.3 [55.2, 64.9]와 PPE 66.2 [61.6, 70.4]의 개별 신뢰구간은 61.6~64.9에서 겹친다. 주변 신뢰구간의 중첩만으로 차이의 유의성을 판정할 수는 없으므로, 개선을 확정하려면 차이의 신뢰구간이나 짝지은 검정이 필요하다.

---

## 6. 초해상 다운스케일링 — 나이지리아 · SVI

### 6.1 나이지리아 식량안보

주(ADM1) 단위 조사 자료로 학습해 지방정부구역(ADM2/LGA) 단위 예측을 만드는 실험이다. 조사가 닿지 않는 곳의 식량안보를 위성 자료로 보완한다.

![Figure 3: 나이지리아 식량안보 다운스케일링](/api/blog/figures/ppe-fig3-nigeria-foodsec.png)

*그림 2. Ma et al. (2026), Figure 3의 원도판. 나이지리아 식량안보를 ADM1 주 단위에서 ADM2 LGA 단위로 다운스케일링한다. 왼쪽은 조사된 30개 주의 실측, 오른쪽은 전국 LGA 예측이다. [arXiv](https://arxiv.org/abs/2608.26088v1) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).*

| System | Feature Configuration | Overall $R^2$ [95% CI] (%) |
| --- | --- | --- |
| Baseline | Macro-Covariates + Interpolation | **31.5** [19.0, 39.3] |
| PPE (Covariates) | + 야간조도(NTL) | 49.8 [39.8, 57.9] |
| PPE (Covariates) | + 식생 | 60.1 [40.3, 72.8] |
| PPE (Full Stack) | + 식생 + NTL + 자동 선택 | **66.1** [55.9, 72.8] |

기준선 31.5 [19.0, 39.3]와 전 구성 66.1 [55.9, 72.8]의 개별 신뢰구간은 겹치지 않는다. 네 헤드라인 비교쌍 가운데 양쪽 구간이 모두 보고되고 서로 겹치지 않는 유일한 사례지만, 공식 비교에는 차이의 신뢰구간이나 동일 재표집 단위의 검정이 더 적절하다.

동시에 식생만 붙인 구성(60.1 [40.3, 72.8])과 전 구성(66.1 [55.9, 72.8])은 **상한이 72.8로 같고 구간이 크게 겹친다.** 표는 기본 보간과 위성 대리변수를 포함한 구성 사이의 큰 점추정치 차이를 보여주지만, 자동 선택을 추가한 효과는 별도 차이 검정 없이는 판단하기 어렵다.

학습·검증은 **leave-one-state-out 교차검증**이고, 신뢰구간은 주(state)를 재표집 단위로 하는 **공간 군집 부트스트랩**(k=30)이다. ADM2 진리값은 다층회귀 후층화(MRP)로 따로 추정해 학습 중에는 가렸다. 이는 공간 전이를 평가하려는 질문에 맞춘 설계다.

한 가지 단서는 달아야 한다. Table 3의 $R^2$는 표를 소개하는 §2.3.1 본문이 밝히듯 "measured **against ADM1 level ground truth** data", 곧 학습 단위인 거친 해상도에서 잰 값이다(캡션 자체에는 이 단서가 없다). 정작 이 과제의 목적인 ADM2 해상도의 성능은 별도로 보고되며, MAE 10.0%로 기준선 13.6%보다 낫다. 다운스케일링 논문의 대표 수치가 다운스케일된 해상도에서 측정된 값이 아니라는 점은 읽을 때 감안해야 한다.

### 6.2 SVI 초해상 (County → ZIP)

| System | Feature Configuration | Mean $R^2$ [95% CI] |
| --- | --- | --- |
| Baseline | Macro-Covariates + Interpolation | 11.0 [10.0, 12.3] |
| PPE (Covariates) | Geospatial Covariates | 25.6 [24.3, 26.9] |
| PPE (Embeddings) | PDFM | **36.9** [36.0, 37.9] |
| PPE (Full Stack) | Covariates + PDFM | **37.6** [36.7, 38.6] |

여기서는 CDC와 다른 패턴이 나온다. 공변량 구성은 25.6이고 PDFM 구성은 36.9다. 임베딩을 포함한 구성에서 더 높은 점추정치가 관측됐으며, 논문은 이를 PDFM이 행정 경계 풀링에 견디는 교차 스케일 사회경제 표상을 담는다는 가설로 해석한다.

다만 전 구성(37.6)은 PDFM 단독(36.9)보다 0.7점 높을 뿐이고 두 구간이 겹친다. 그리고 절대 수준이 낮다. 카운티에서 우편번호 구역으로 내려가는 과제는 어렵다는 것을 표가 정직하게 보여준다.

캡션과 표가 어긋나는 곳도 있다. Table 4와 Table 7의 제목은 모두 "across Feature Configurations on SVI Benchmark Themes"로 테마를 내걸지만 두 표 모두 테마별 열이 없고 평균 한 열뿐이다. SVI가 5개 지수라는 점을 생각하면 테마별 분해가 있어야 할 자리다.

---

## 7. Ebola 나우캐스팅

2026년 5~7월 DRC의 Bundibugyo 에볼라 발생을 대상으로, 아직 감염되지 않은 보건구역 중 다음 1주 안에 새 환자가 나올 곳을 맞히는 과제다. 519개 보건구역 전체를 대상으로 7주로 학습하고 5주로 평가한다. 지표는 Recall@10이다. 논문의 정의는 "the proportion of newly infected zones successfully captured within our top 10 highest-risk predictions", 곧 **새로 감염된 구역 가운데 상위 10개 예측 안에 들어온 비율**이다. 분모가 예측 목록이 아니라 실제 침범 구역이라는 점이 뒤의 산술(18개 중 15개)과 이어진다.

![Figure 2: Ebola 예측 시각화](/api/blog/figures/ppe-fig2-ebola-5fold.png)

*그림 3. Ma et al. (2026), Figure 2의 두 패널 중 5겹 통합 패널을 크롭했다. 저부하 전선 부분집합(0–20건, 2,546 zone-weeks)의 R² 0.87·RMSE 0.55를 표시하며, 미감염 지역 2,405개와 감염 보건구역 141개를 구분한다. [arXiv](https://arxiv.org/abs/2608.26088v1) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).*

| System | Feature Configuration | Recall@10 (%) [95% CI] |
| --- | --- | --- |
| Baseline / SOTA (Bayesian modeling) | Baseline Signals | **~73** (CI 없음) |
| PPE (Covariates) | Baseline Signals + 지리 공변량 | 77.8 [54.8, 91.0] |
| PPE (Full Stack) | Baseline signals + 자동 전체 자료 선택 | **83.3** [60.8, 94.2] |

한 시간이 채 안 되는 실행 기록은 위기 상황에서 신속한 예측 파이프라인을 구성할 가능성을 보여주는 시연이다. 실제 의사결정 효과는 이 실험에서 평가하지 않았다.

수치는 조심해서 읽어야 한다. PPE 전 구성의 신뢰구간 [60.8, 94.2]에는 기준선 점추정치 73이 포함되고, PPE(Covariates)의 [54.8, 91.0]도 마찬가지다. 다만 기준선 CI와 두 방법 차이의 CI가 없으므로, 이 주변 구간만으로 "+10.3 percentage-point improvement"의 통계적 불확실성을 판정할 수는 없다.

지표의 입자도 함께 봐야 한다. 5주에 걸쳐 새로 침범된 보건구역이 18개이고 그중 15개를 맞혀 83.3%다. **한 건이 5.6점**이므로 10.3점 차이는 대략 두 건이다. Recall@10이 이 설정에서 취할 수 있는 값은 19개뿐이다.

기준선의 출처는 논문 안에서 두 갈래로 적힌다. §2.1은 "We benchmark our model against epidemiological predictions published by INRB **[48]**"이라 하는데, [48]은 Mbulayi 외의 *The Lancet Infectious Diseases* (2026) 논문이다. 반면 73%라는 수치에는 **[19]**가 달리는데(§1.3 "over the published state-of-the-art Bayesian modeling baseline [19] (73%)"), 이쪽은 Epidemiological.org Consortium의 웹 포럼 게시물이다. 무엇을 상대로 비교했는지와 그 수치를 어디서 가져왔는지가 다른 문헌을 가리킨다.

정밀도 문제는 그와 별개로 남는다. Table 2의 기준선 칸은 물결표가 붙은 `~73`이고 신뢰구간이 없다. 근사 기준선에 대해 소수 첫째 자리까지의 개선 폭(+10.3)을 제시하는 것은 자릿수가 맞지 않는다.

본문은 예측 발생 규모가 실측과 "high correlation"을 보인다고 적는다. 도판은 실제로 적합도를 싣는데, 그 조건을 함께 봐야 한다. 5겹 통합 패널에는 **R² = 0.87, RMSE = 0.55 cases**가 찍혀 있지만 대상이 "Low-Caseload Frontier Subset (0–20 Cases, n = 2,546 zone-weeks)"이고, 그중 **2,405개가 미감염 지역**이며 감염 보건구역은 141개다. 즉 점의 94%가 0 부근에 몰린 절단 부분집합 위의 값이다. 최종 겹 패널은 R² = 0.89다. 전체 표본에 대한 적합도는 제시되지 않으므로, 본문의 "high correlation"이 가리키는 범위는 이 부분집합이다.

---

## 8. 수치를 어떻게 읽을 것인가

앞 장들에서 표를 따라가며 짚은 것을 여기서 종류별로 모은다. 이 논문의 결과는 대체로 방향이 옳지만, 각 수치가 **무엇에 대한 우위인지**가 표마다 다르다.

### 8.1 공간 자기상관과 분할 설계

공간 자기상관이 강한 자료에서 인접 지역 단위를 훈련과 시험에 무작위로 나누면, 공간적으로 분리된 역외 평가보다 $R^2$가 낙관적으로 나타날 수 있다. 이웃한 단위가 비슷한 공변량과 결과를 공유하기 때문이다.

논문은 이 문제를 **모른 채로 지나가지 않는다.** 모델 탐색의 검증 전략 목록에 Spatial Group Split이 있고, 설명이 정확하다. "지리 경계를 따라 분할해 공간 자기상관 누출을 막고 진짜 역외 일반화를 잰다." 인용도 정확한 것을 단다. Roberts 외(2017)와 Meyer 외(2019)는 공간 자료에 무작위 분할을 쓰지 말라고 논증한 바로 그 문헌이고, 이 목록에 함께 달려 있다. (Openshaw의 MAUP도 인용되지만 그쪽은 §2.3.1에서 세밀한 추정이 왜 필요한지를 말하는 자리이지 분할 설계 맥락이 아니다.)

그런데 §2.1은 헤드라인 두 벤치마크의 분할을 이렇게 밝힌다.

> CDC와 FEMA는 "both aggregating approximately 84k fine-grained census tracts under a **conventional 80:20 random train/test split**, which aligns with settings of public SOTA [5]."

즉 인구조사 표준지역 단위 **무작위 80:20 분할**이다. 이유는 선행 연구와의 비교 가능성이다. 이 결과는 동일 공간 표본틀의 무작위 tract holdout 성능이며, 공간적으로 분리된 역외 일반화 성능을 직접 추정하지 않는다. 공간 블록 교차검증을 적용했을 때의 차이는 보고되지 않았다.

나이지리아는 leave-one-state-out 교차검증과 주 단위 공간 군집 부트스트랩을 사용한다. CDC·FEMA의 무작위 holdout과 나이지리아의 공간 전이 평가는 서로 다른 일반화 질문에 답하므로, 수치를 같은 의미로 비교해서는 안 된다.

### 8.2 불확실성 보고의 비대칭

| 표 | PPE 쪽 CI | 기준선 쪽 CI |
| --- | --- | --- |
| Table 2 (Ebola) | 있음 [60.8, 94.2] | **없음** (~73) |
| Table 3 (나이지리아) | 있음 | 있음 |
| Table 4 (SVI 초해상) | 있음 | 있음 |
| Table 5 (CDC) | 있음 | **없음** (60, 소수점도 없음) |
| Table 6 (FEMA) | 있음 | **없음** (59.9) |
| Table 7 (SVI 회귀) | 있음 | 있음 (겹침) |

기준선에 구간이 없는 표가 셋이고, 셋 모두 초록의 대표 비교(Ebola·CDC·FEMA)에 쓰인다. 비교의 한쪽만 불확실성을 갖고 있으면 개선의 통계적 불확실성을 판정할 수 없다. Table 7의 두 주변 구간은 겹치고, Table 2의 PPE 구간에는 기준선 점추정치가 들어가지만, 어느 경우든 방법 간 차이의 CI나 짝지은 검정은 제시되지 않는다.

기술적으로는 CDC의 점추정치 차이가 +16.8이고 PPE 구간 폭이 1.5이며, 나이지리아의 차이는 +34.6이고 두 주변 구간이 겹치지 않는다. FEMA의 점추정치 차이는 +5.0이고 PPE 구간 폭은 1.4다. 하지만 기준선 구간이나 차이의 분포가 없는 비교에서는 이 크기만으로 통계적 우위를 확정할 수 없다. SVI 공간회귀와 Ebola도 표의 주변 구간만으로 방법 간 개선을 판정하기 어렵다.

### 8.3 자동 수집과 타깃 누출

CDC·FEMA 표에서 자동 수집 공변량과 선택 단계를 추가할 때 점추정치가 달라진다. 따라서 무엇을 찾아왔는지가 결과 해석의 핵심이다.

위험은 구체적이다. CDC PLACES는 Data Commons가 서빙하는 자료이고 CDC 건강 지표가 예측 대상이다. SVI는 빈곤율·실업률·1인당소득 같은 ACS 센서스 변수로 **정의상 계산되는** 지수이고, Data Commons는 ACS 변수를 서빙한다. Feature Gate의 기준 ①과 ②가 정확히 이 경우를 겨냥해 쓰였다는 점은 설계자들이 문제를 알고 있었다는 증거다.

문제는 그 장치가 어떤 상태로 적용됐는지다. 3.2절에서 본 대로 CDC·FEMA 프롬프트에는 타깃 산식이 없고, **기준 ②가 배제 예시로 든 계수형 변수(`Count HousingUnit` 등)가 부록의 사용 변수 목록에 들어가 있다.** 게이트는 LLM의 판단이고 어떤 후보가 걸러졌는지에 대한 기록은 없다. SVI 공간회귀에서 실제로 어떤 Data Commons 변수가 쓰였는지도 공개되지 않았다.

부록 F.2의 Table 12는 이 물음에 부분적인 답을 준다. 대상별로 **실제 사용된 Data Commons 변수 목록**을 싣기 때문이다. FEMA의 `Social Vulnerability` 대상에 쓰인 목록은 이렇다.

> `Count_Person, BelowPovertyLevelInThePast12Months, Count_Household, HouseholderAge65OrMoreYears, SingleMotherFamilyHousehold, LimitedEnglishSpeakingHousehold, NoComputer, NoInternetAccess, With0AvailableVehicles, WithFoodStampsInThePast12Months, IncomeOfUpto10000USDollar, …, Count_HousingUnit, Count_HousingUnit_Before1939DateBuilt`

빈곤, 65세 이상 가구주, 한부모 가구, 영어 능력 제한 가구, 차량 없음, 소득 구간. 사회취약성 지수를 만들 때 통상 들어가는 재료들이다. 그리고 이 대상의 이득이 표 안에서 압도적으로 크다(48.24 → 67.55, **+19.31**). 같은 범주의 나머지 셋은 −0.44, +2.38, +1.96이다.

무엇을 단정할 수 있고 무엇을 단정할 수 없는지는 나눠 적어야 한다. FEMA NRI의 Social Vulnerability 성분이 정확히 어떤 산식인지는 이 논문에 없으므로, 위 변수들이 그 산식의 **구성요소**라고 단정할 수 없다. 확인되는 것은 사용 변수 목록이 사회취약성 지수의 통상적 재료와 겹치고, 해당 대상의 점추정치 증가가 같은 범주의 다른 대상보다 크며, 프롬프트에 타깃 정의가 없다는 사실이다. 논문은 이 입력에서 Feature Gate가 어떻게 적용됐는지 보고하지 않는다.

이것이 누출이 있었다는 뜻은 아니다. 적용 로그와 타깃 산식이 없어 독립적으로 판정할 수 없다는 뜻이다. 논문이 Table 12에서 변수 목록을 공개한 것은 검증 가능성을 높이며, 같은 공개를 CDC와 SVI 공간회귀에도 했다면 이 물음을 더 직접적으로 평가할 수 있었을 것이다.

### 8.4 숫자와 서술이 어긋나는 곳

- §2.4.1의 "23 percentage point improvement"는 실제 16.8이다.
- SVI 공간회귀의 58.6·51.6·45.1은 본문에만 있고 Table 7에는 60.3·50.2·66.2가 있다. 같은 문단의 "6.8 percentage point"와 "12% gain"도 각각 계산값 7.6과 13.0%에 맞지 않는다.
- FEMA 대상 수는 Table 1에서 21, §2.4.2와 Table 6에서 20이며, 공간 단위도 census tract와 county로 갈린다. 부록 F.2의 대상별 자동 선택 평균(대기·기후 74.2, 지구물리·수문 63.9)도 Table 6의 68.3·56.2와 다르다.
- §3.3의 SVI 초해상 수치 "40.1% vs. 52.0%"는 Table 4(최댓값 37.6)에 없고, 시험 단위도 Table 1의 ZCTA(~33k)와 §2.1의 census tract(~84k)가 다르다.

개별로는 사소한 것들이지만, 대표 결과를 낸 문장의 산술이 틀리고 초록의 기준선이 표에 없는 두 건은 사소하지 않다.

---

## 9. 한계와 결론

### 9.1 논문이 밝힌 한계

§3.5는 네 가지를 적는다.

1. **임베딩을 동결된 특징 추출기로만 쓴다.** 하류 과제에 맞춘 종단 미세조정이 더 나은 결과를 낼 수 있지만 소표본에서 과적합을 피하려면 신중한 정규화가 필요하다.
2. **잡음–해상도 상충.** SVI 초해상에서 고주파 위성 특징이 교차 스케일 일반화를 오히려 떨어뜨렸고, 목표 공간 입도를 고려하는 적응적 특징 선택이 필요하다. (다만 이 한계를 뒷받침하는 §3.3의 수치 "R² of 40.1% vs. 52.0%"는 Table 4에 없다. 그 표의 네 행은 11.0·25.6·36.9·37.6이고 최댓값이 37.6이다. SVI 공간회귀에서 본 것과 같은 종류의 본문–표 불일치가 여기서 한 번 더 나타난다.)
3. **인과 방향 필터의 형식적 검증이 미해결.** 특히 후보 공변량과 양방향 관계를 갖는 타깃에서 그렇다.
4. **감염병 나우캐스팅 평가가 단일 발생 사례에 한정**된다. 여러 병원체·지역·감시 체계에 걸친 검증이 있어야 일반화 주장이 강해진다.

두 번째와 네 번째는 자기 결과를 스스로 좁히는 서술이고, 세 번째는 앞 절에서 설명한 지점을 저자들이 먼저 인정한 것이다.

### 9.2 이 방법이 성립하는 조건


부록 E의 프롬프트는 훈련·평가 컷오프, 시험 집합 정의, 지표, 일부 과제의 타깃 산식까지 담는다. 이런 상세 명세를 비전문가가 독립적으로 작성할 수 있는지는 평가되지 않았다. 이 논문이 직접 보여준 자동화 범위는 자료 발견·융합·모델 탐색이며, 자연어 문제 정의 자체의 자동화는 별도 검증이 필요하다.

### 9.3 남는 기여

- Data Commons·Earth Engine·열린 웹을 하나의 실행 경로로 묶고, 예측 에이전트가 원자료를 직접 변경하지 못하도록 단계 간 계약을 둔다.
- 나이지리아 실험은 leave-one-state-out 교차검증, 공간 군집 부트스트랩, 학습에서 가린 MRP 진리값을 사용해 공간 전이 질문을 명시적으로 평가한다.
- Feature Gate의 네 기준은 자동 자료 발견 시스템이 후보 공변량을 검토할 때 사용할 수 있는 출발점이다. 실제 적용 로그와 형식 검증은 후속 과제로 남는다.
- SVI 초해상에서 고주파 특징이 해가 된 결과, FEMA 일부 대상의 후퇴, CDC에서 PDFM 단독이 기준선 아래인 결과도 표에 함께 보고한다.

### 9.4 결과의 적용 범위

시스템 기여의 중심은 새로운 예측 알고리즘 하나가 아니라 자료 발견·다중 모달 융합·모델 탐색을 실행 가능한 파이프라인으로 연결한 데 있다. 각 벤치마크의 점추정치 증가가 나타나는 단계는 서로 다르므로, 자동 자료 선택과 파운데이션 임베딩의 효과를 하나의 원인으로 묶기보다 과제별 절제로 읽는 편이 정확하다.

실증 결과는 기준선의 종류와 분할 목적에 맞춰 해석해야 한다. 남는 핵심 검증 과제는 공간 블록 평가에서의 성능, Feature Gate의 실제 필터 로그, 그리고 같은 재표집 단위에서 계산한 방법 간 차이의 불확실성이다.

---

## References

Bell, A., Aides, A., Helmy, A., Muslim, A., Barzilai, A., Slobodkin, A., Jaber, B., Schottlander, D., Leifman, G., Paul, J., Sun, M., Sherman, N., Williams, N., Bjornsson, P., Lee, R., Alcantara, R., Turnbull, T., Shekel, T., Silverman, V., … Shetty, S. (2025). *Earth AI: Unlocking geospatial insights with foundation models and cross-modal reasoning* (arXiv:2510.18318v4). arXiv. https://arxiv.org/abs/2510.18318

Epidemiological.org Consortium. (2026). *Real-time spatiotemporal risk modelling of the Bundibugyo ebola virus outbreak 2026*. Epidemiological.org. https://www.epidemiological.org/t/real-time-spatiotemporal-risk-modelling-of-the-bundibugyo-ebola-virus-outbreak-2026/16

Ma, E., Pasumarthi, R. K., Shafin, K., Sharma, M., Sun, M., Sadeghi, H., Ebengo, D. M., Onesime, M., Solomakhin, R., Wamburu, J., Ogallo, W., Walcott-Bryant, A., Chen, S., Muslim, A., Mayer, Y., Ho, R., Lee, R., Alcantara, R., Diack, A., … Shetty, S. (2026). *Planetary Prediction Engine: Autonomous geospatial prediction via intelligent data selection and foundation model embeddings* (arXiv:2608.26088v1). arXiv. https://arxiv.org/abs/2608.26088

Mbulayi, O., Akilimali, P., Judge, C., Gutierrez, B., Mulu, P., Ibolobolo, C. M., Sibo, J.-C., Nkwele wa Nkwele, R., Hermann, M. M., Lawanga Ontshick, L., Mukadi, D., Kanku, B., Katanga, E., Mercy, K., Kosianza, J., Ajong, B., Muteba, M., Bishola Tshitenge, T., Lusamaki, E., … Ebengo, D. M. (2026). Real-time epidemic intelligence in a public health emergency: The 2026 Bundibugyo virus outbreak. *The Lancet Infectious Diseases, 26*(9), e326–e327. https://doi.org/10.1016/S1473-3099(26)00330-0

Meyer, H., Reudenbach, C., Hengl, T., Katurji, M., & Nauss, T. (2019). Importance of spatial predictor variable selection in machine learning applications: Moving from local to spatial cross-validation. *Ecological Modelling, 411*, 108815. https://doi.org/10.1016/j.ecolmodel.2019.108815

Openshaw, S. (1984). *The modifiable areal unit problem*. Geo Books.

Park, D. K., Gelman, A., & Bafumi, J. (2004). Bayesian multilevel estimation with poststratification: State-level estimates from national polls. *Political Analysis, 12*(4), 375–385. https://doi.org/10.1093/pan/mph024

Roberts, D. R., Bahn, V., Ciuti, S., Boyce, M. S., Elith, J., Guillera-Arroita, G., Hauenstein, S., El-Gabbas, A., Raiß, J., & Dormann, C. F. (2017). Cross-validation strategies for data with temporal, spatial, hierarchical, or phylogenetic structure. *Ecography, 40*(8), 913–929. https://doi.org/10.1111/ecog.02881
