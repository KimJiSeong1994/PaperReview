# Population-Aligned Persona Generation for LLM-based Social Simulation

**Paper:** Zhengyu Hu; Jianxun Lian; Zheyuan Xiao; Max Xiong; Yuxuan Lei; Tianfu Wang; Kaize Ding; Ziang Xiao; Nicholas Jing Yuan; Xing Xie (2025). "Population-Aligned Persona Generation for LLM-based Social Simulation". https://arxiv.org/abs/2509.10127 · arXiv:2509.10127v2

**Abstract:** PAPG는 LLM 사회시뮬레이션에 사용할 페르소나 집합을 인간의 관측 분포에 맞추는 방법이다. 블로그에서 서사형 시드를 채굴한 뒤, 시드별 성격 설문 응답을 importance sampling과 entropic optimal transport로 재표집한다. 그룹별 질의에는 임베딩 검색과 LLM 재작성으로 대응한다. 실험은 성격 분포, 다른 심리측정 지표, 특질 간 상관과 그룹별 설문을 비교하며, 정렬된 페르소나가 기존 비교 집합보다 낮은 분포 오차를 보였다고 보고한다. 다만 관측 설문의 대표성과 시드 규모·일부 성능 수치의 보고 불일치는 결과의 해석 범위를 제한한다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | LLM 사회시뮬레이션의 페르소나 집합을, 그것이 유도하는 설문 응답의 분포가 실제 인간 모집단 분포와 일치하도록 만들 수 있는가? |
| 핵심 기여 | 페르소나 셋 구성을 분포 정렬 문제로 정식화. 시드 채굴(블로그 코퍼스 + LLM 요약·품질 필터) → 전역 정렬(KDE importance sampling + entropic OT 재표집) → 그룹 특화(대조학습 임베딩 검색 + LLM 재작성)의 3모듈. |
| 방법적 결과 | 문항별 응답 \(x_{ik} = \mathrm{LLM}(\mathrm{concat}(p_i, q_k))\)(식 1)을 모은 응답 벡터의 경험분포를 IPIP 인간 응답 분포에 맞추는 부분집합 \(\mathcal{P}'\)을 뽑는다(식 1–12). 수렴 정리 2개(Appendix G)가 붙어 있으나, 하나는 실제 차원 정의가 불명확해 수치적 유효성을 확정하기 어렵고 하나는 실제 방법과 가정이 다르다(5장). |
| 실험 결과 | in-domain(Table 1) 12열·OOD(Table 2) 12열·상관 구조(Table 3) 4열·그룹(Table 4) 16열 전부에서 1위. 미정렬 시드 풀(Raw)조차 Table 1 전 열에서 기존 셋을 이기고, 정렬(Resample)이 평균 오차를 0.2580→0.1715로 줄인다. |
| 핵심 한계 | 논문이 인정한 한계는 긍정성 편향과 온라인 인구 편중 둘뿐(Appendix E). 실제로는 LLM 순환 구조(모델이 도달 가능한 응답 범위의 상한), 자기 목표에 대한 in-domain 평가, WVS 지역 정렬의 낮은 절대 수준, 반복·유의성 부재, 본문-표 수치 불일치 다수가 얹힌다. |

## 목차

1. 서론
2. 방법: 시드 채굴, 전역 정렬, 그룹 특화
3. 실험 설정
4. 실험 결과
5. 결과의 해석 범위
6. 방법적 한계와 확장
7. 결론

## 1. 서론

### 1.1 연구 배경

LLM 사회시뮬레이션 연구는 에이전트 프레임워크(기억·상호작용·환경)에 공을 들여 왔지만, 정작 시뮬레이션에 투입되는 **페르소나 집합**은 대충 만들어졌다는 것이 이 논문의 출발 진단이다. §1이 드는 실례: Weibo 사용자 1,000명 무작위 선택(TrendSim), 인구속성 3개짜리 프로파일(S3), LLM 생성·무작위 표집 프로파일(YuLan-OneSim), 15개 고정 속성 스키마에 목표 분포가 사전에 주어진다는 가정(SocioVerse — 이 가정은 "실제로는 거의 성립하지 않는다"는 것이 논문의 논평).

동기 실험이 Figure 1이다. Qwen2.5-72B에게 IPIP Big Five 자기보고 설문을 시키면, 페르소나 없이 temperature 1.0으로 돌려도 분포가 좁은 봉우리로 붕괴하고, 공개 페르소나 셋 6종(Tulu-3-Persona, Bavard, Google Synthetic, AlignX, Nvidia Nemotron, PersonalHub — 마지막은 논문 표기이고 실제 데이터셋명은 PersonaHub다)이나 GPT-4o 생성 셋을 붙여도 실제 인간(224개국 101만 명)의 분포와 크게 어긋난다. 이 논문은 모델 가중치가 아니라 **페르소나 집합을 교정 대상**으로 삼는다.

![PAPG Figure 1: Big Five distributions of human vs persona sets](/api/blog/figures/papg-fig1-distributions.png)

*그림 1 — 원논문 Figure 1(일부): (a) 실제 인간의 Big Five 응답 분포 대비, (b) 무페르소나 LLM, (c)–(h) 기존 페르소나 셋 6종과 (i) GPT-4o 생성 셋의 분포. 어느 쪽도 인간 분포의 폭을 재현하지 못한다.*

### 1.2 핵심 질문

질문은 이렇게 정식화된다: 대규모 페르소나 풀 \(\mathcal{P}\)가 있을 때, LLM이 각 페르소나를 조건으로 낸 문항별 응답 \(x_{ik} = \mathrm{LLM}(\mathrm{concat}(p_i, q_k))\)(식 1)을 모은 응답 벡터 \(x_i\)의 경험분포가 인간 응답 분포 \(r_{human}\)을 회복하는 부분집합 \(\mathcal{P}' \subseteq \mathcal{P}\)를 어떻게 고르는가(§3.2). 즉 "population-aligned persona set"은 집합이 유도하는 응답 분포의 통계적 일치로 정의된다. 개별 페르소나의 그럴듯함은 기준이 아니다. 정렬 기준은 IPIP Big Five 응답 101만 건이고, 페르소나는 고정 인구속성 스키마 대신 서사형(narrative)이다. 소스에 없는 속성 칸을 억지로 채우다 생기는 부정확성을 피한다는 것이 명시된 이유다(§1).

## 2. 방법: 시드 채굴, 전역 정렬, 그룹 특화

원논문 §3에 해당한다. 3모듈 파이프라인이다(Figure 2).

![PAPG Figure 2: framework](/api/blog/figures/papg-fig2-framework.png)

*그림 2 — 원논문 Figure 2: (1) 시드 페르소나 채굴 → (2) 분포 정렬(importance sampling + optimal transport) → (3) 그룹 특화 페르소나 선택.*

### 시드 페르소나 채굴 (원논문 §3.1, Appendix F)

원천은 Blog Authorship Corpus(Schler et al., 2006)의 블로그 포스트 68.1만 건이다. 4단계로 거른다: (1) 전처리: 30토큰 미만·1인칭 부재 항목 폐기, LLM 재작성으로 노이즈 제거(약 50만 건); (2) 원문 품질 관리: LLM이 품질 3단계와 유해성 여부를 태깅, high+harmless만 유지(36.8만 건); (3) 페르소나 생성: 저자별로 포스트를 모아(6편 미만 폐기) LLM이 근거 기반 3인칭 서사 페르소나로 요약, 소스가 뒷받침하지 않는 속성은 쓰지 않도록 프롬프트로 지시(4.16만 건); (4) 페르소나 품질 관리: critic LLM(Qwen2.5-72B)이 환각·포괄성·간결성·관련성·종합 5차원을 채점해 종합 8 초과·나머지 전부 7 초과만 유지. Table 10 기준 최종 시드 풀은 **30,738개**다.

여기서 첫 번째 주의점이 나온다. 시드 풀 규모가 §3.1 본문에는 "over 160,000", Appendix F에는 "over 100,000", 단계별 통계표(Table 10)에는 30,738로 적혀 있다. 본문과 부록의 복수형 잔재(§3.1 "from each source", B.1 "three open-source datasets")로 보아 원래 복수 코퍼스 설계였다가 블로그 단일 코퍼스로 줄이면서 서술이 갱신되지 않은 것으로 보인다. 채굴에 쓴 모델 표기도 Llama-3-70B와 Llama-3.3-70B 사이를 오간다. 수치를 인용할 때는 표(Table 10) 기준이 안전하다.

### 전역 분포 정렬: 2단계 재표집 (원논문 §3.2)

각 시드 페르소나에게 LLM으로 IPIP 50문항을 답하게 해 응답 벡터를 만들고, 이 벡터들의 분포를 인간 분포에 맞추는 부분집합을 뽑는다. 두 단계의 역할 분담이 명시되어 있다: 1단계가 거친 필터, 2단계가 정밀 정렬이다.

- **Stage 1 — KDE importance sampling(식 2–4):** 인간·페르소나 응답 각각에 가우시안 커널 밀도 추정(KDE; 대역폭 0.20)을 하고, 밀도비 \(w_i = \hat{r}_{human}(x_i)/\hat{r}_{persona}(x_i)\)를 가중치로 후보를 표집한다. 인간 분포 아래에서 상대적으로 그럴듯한 페르소나에 표집을 집중시켜, 분포 간극이 클 때 OT가 퇴화할 위험을 줄인다는 논리다.
- **Stage 2 — entropic optimal transport(식 5–12):** 후보 응답과 인간 응답 사이의 (문항 가중) 제곱 거리 비용으로 엔트로피 정칙화 OT를 풀고(엔트로피 OT의 표준 해법인 Sinkhorn 반복 250회; ε=0.08을 중앙값 비용으로 스케일, 배치 10,000), 수송 계획의 행 합을 가중치로 최종 페르소나를 표집한다.

부록에 수렴 정리 2개가 붙어 있다(Appendix G): IS 후의 Wasserstein 오차 상계(Theorem 1)와 엔트로피 OT의 O(ε) 편향(Theorem 2). 이 보증들은 5장에서 따져 본다. 구현과 본문 서술의 어긋남도 하나 있다. 본문(식 4)은 다항 확률 표집인데, 구현 서술(Appendix B.1)은 "중요도 가중치 상위 70% 유지"라는 결정적 절단이다. 프라이버시 처리로는 GPT-4o가 PII(개인식별정보)를 탐지(99.31%가 무PII)하고 해당 건은 재작성 후 주석자 5명이 검증한다(Appendix C).

### 그룹 특화 페르소나 구성 (원논문 §3.3)

실제 시뮬레이션은 전 지구 인구가 아니라 특정 집단(미국 고교생, 홍콩 주민)을 다루는 경우가 많다. 이 모듈은 자연어 질의로 전역 정렬된 풀에서 관련 페르소나를 임베딩 검색으로 모으고, LLM(이 절의 모든 LLM은 Qwen2.5-72B)이 과제에 맞게 소폭 재작성한다(식 15). 검색용 임베딩(Qwen3-Embedding-0.6B)은 페르소나당 상세·광역 질의 2개(식 13)를 양성 예로, 유사도 상위 N개와 무작위 N개(N=10)에서 LLM이 거짓 음성을 걸러낸 hard negative(무관한데 유사해 보이는 대조 예)를 음성 예로 삼는 대조 손실(식 14)로 파인튜닝한다(Table 8).

## 3. 실험 설정

원논문 §4와 Appendix B에 해당한다.

**데이터(Table 7).** 정렬 참조이자 in-domain 평가는 IPIP Big Five(50문항, 1,015,341명, 224개국; 본문은 223으로 표기해 1 어긋난다). out-of-domain 평가는 자기보고 심리측정 3종: CFCS(미래결과 고려 척도; Strathman et al., 1994), FBPS(첫째 성격 척도), Duckworth Grit(끈기; Duckworth et al., 2007). 그룹 평가는 YRBSS(미국 고교생 건강위험행동, CDC)와 WVS(세계가치관조사) 3개 지역 — 동아시아(중·일·한국·홍콩·몽골·대만·마카오), 북미, 유럽(독일·네덜란드·영국)이다. 문항 수·국가 수 표기가 본문과 표 사이에서 여러 건 어긋난다(5장).

**지표(Appendix D, 식 16–20).** 분포 수준 4종은 AMW(특질별 1차원 Wasserstein 거리의 평균), FD(가우시안 근사 Fréchet 거리), SW(무작위 사영 후 1차원 Wasserstein 평균), MMD(커널 평균 임베딩 차이)다. 개인 수준 1종은 MAEcorr(특질쌍 Pearson 상관 행렬의 평균절대오차)다. 전부 낮을수록 좋다. 본문 두 곳에서 MMD를 "MED"로 오기한다.

**비교 대상(§4).** 페르소나 없음(DAns; 온도 0/0.7/1.0, 온도당 5,000회 생성), 모델 직접 생성 페르소나(SyncP; GPT-4o 포함 4종), 공개 페르소나 셋 6종(무작위 5,000개씩), 그리고 자기 변형 3종인 **Raw**(시드 풀 전체), **RandomSelect**(크기 통제 무작위 추출), **Resample**(2단계 정렬 적용)이다. 이 3종이 "정렬 효과 vs 시드 품질 효과"를 분리하는 ablation이다. 평가 base model은 Qwen2.5-72B·Llama-3-70B·Phi-4 셋이다.

## 4. 실험 결과

### in-domain: 정렬은 효과가 있고, 시드 품질도 이미 좋다 (Table 1)

3개 base model × 4지표의 12열 전부에서 Resample이 최저다(평균 0.1715). 무페르소나 쪽에서는 온도를 올리면 정렬이 나아지지만(Qwen2.5-72B FD 1.4256→1.0947) 페르소나 조건화에는 크게 못 미친다는 것이 논문의 첫 관찰이다. 그 위에서 두 가지 부수 관찰이 표의 실질 내용이다. 첫째, 미정렬 시드 풀(Raw, 평균 0.2580)이 기존 공개 셋을 이긴다. 본문 표현은 "most"지만 표 기준으로는 전 열에서 이긴다. baseline 대비 우위의 큰 몫이 블로그 유래 서사 페르소나의 품질 자체에서 나온다는 뜻이다. 둘째, Raw와 RandomSelect(0.2577)가 사실상 같으므로 크기 효과는 배제되고, 정렬의 순수 기여는 0.2580→0.1715 구간이다. 다만 이 평가의 검사(IPIP)는 정렬 파이프라인의 참조 분포와 같다는 것을 논문도 명시한다. 자기 목표에 대한 평가라는 뜻이고, 실질적 검증대는 다음의 OOD다.

### out-of-domain과 상관 구조 (Tables 2–3)

CFCS·FBPS·Duckworth 12열 전부에서 Resample이 최저(평균 0.2085; 최강 baseline Bavard 0.3344). 특질쌍 상관 구조를 재는 MAEcorr(Table 3)에서도 4개 검사 전부 최저(평균 0.3560)다. 주의할 점 둘. (1) 본문이 인용하는 수치가 표와 어긋난다(본문 "0.2279"/"0.4220"/"0.3651" 대 표의 0.2085/0.4004/0.3560; 5장). (2) Table 2·3에는 Raw·RandomSelect 행이 없어서, OOD 우위가 정렬 덕인지 시드 품질 덕인지 표만으로는 분리되지 않는다. Table 1에서 Raw가 이미 전부 이긴 것을 생각하면 상당 부분이 시드 품질일 수 있다.

### 특질 공간 시각화 (Figure 3)

EXT×EST 2차원 산점도(설정당 1,000 샘플)가 이 논문에서 가장 시사적인 그림이다. 온도 0은 한 점으로 붕괴하고, 온도 1도 좁은 군집이며("sampling alone is insufficient"), 기존 페르소나 셋들은 퍼지긴 해도 저-외향·저-정서안정 영역을 덮지 못한다. Resample은 과소대표 영역까지 도달하지만, 논문 스스로 "생성된 분포는 여전히 실제 인간 데이터와 완전히 일치하지 못하며, 이는 모델과 데이터에 내재된 편향 때문"(§4.3, 번역)이라고 잔여 격차를 시인한다. 저자들의 자기평가 가운데 가장 직접적인 문장이다.

![PAPG Figure 3: EXT x EST scatter](/api/blog/figures/papg-fig3-scatter.png)

*그림 3 — 원논문 Figure 3: EXT×EST 산점도 9개 설정. 파랑이 인간, 주황이 LLM 출력. 온도 0(우하단)은 한 점으로 붕괴하고, 기존 셋들은 저-EXT·저-EST 영역을 덮지 못하며, Ours(좌상단)가 가장 넓게 덮는다.*

### 그룹 특화: YRBSS는 되고, WVS는 덜 된다 (Table 4)

지역별 자연어 질의로 검색·재작성해 설정당 1,000개의 그룹 페르소나를 만들고(§4.4), 16열 전부에서 학습된 임베딩 변형(EM w train)이 최저다. 그러나 양상이 갈린다. YRBSS(미국 고교생)에서는 격차가 크다: FD 2.4790 vs 외부 최선 9.0103. 반면 WVS 3개 지역에서는 모든 방법의 절대 오차가 크게 남는다. 동아시아 FD 19.4662, AMW 0.7713 수준으로, in-domain 정렬 후(AMW 0.1527)와 비교하면 자릿수가 다르다. 외부 최강 baseline과의 격차도 AMW 0.04~0.07 수준으로 근소하다. 즉 좁고 문서화가 잘 된 미국 타깃에서는 검색+재작성이 작동하지만, 지역 가치관 분포 정렬은 상대 개선에도 불구하고 미해결에 가깝다. §5의 "high-fidelity group-specific simulation"이라는 요약과 표 사이에는 거리가 있다.

## 5. 결과의 해석 범위

### 5.1 수치 인용은 표 기준으로 — 본문-표 불일치가 많다

논문 본문과 표에 나타난 내부 불일치를 묶어 보면 이렇다. 규모·메타데이터: 시드 풀(§3.1 "160,000+" / Appendix F "100,000+" / Table 10 30,738 — 각 표기의 모집 범위가 일치하는지는 명확하지 않음), 국가 수(223 vs 224; 143/168/110 vs 144/169/111), 문항 수(FBPS 25 vs 76, Duckworth 12 vs 50). 성능 수치: OOD 평균(본문 0.2279 / Table 2 0.2085), FBPS FD(본문 0.4220 / 표 0.4004), MAEcorr 평균(본문 0.3651 / Table 3 0.3560). 명칭: 채굴 모델(Llama-3 vs 3.3), 지표명(MED vs MMD), PersonalHub(실제 명칭 PersonaHub). Table 1의 본문 감소율(49.8/37.9/45.1%)도 표에서 재계산되지 않는다(재계산 시 약 54–57/40/53%). §4.4의 "Resample 대비 8.9% 개선" 주장은 Table 4에 Resample 행이 없어 표만으로는 확인할 수 없다. 승패의 방향은 어느 수치를 취해도 바뀌지 않지만, 보고된 수치는 해당 표와 본문의 차이를 함께 고려해야 한다.

### 5.2 "population"의 실체는 영어 온라인 설문 응답자다

정렬 참조는 온라인 성격 테스트 사이트의 자발적 응답자(자기선택 표본)이고, 시드는 비영어 콘텐츠를 제거한 2000년대 초 영어 블로그다. 논문 스스로 Appendix E에서 "인터넷 접근 가능 인구" 편중을 밝히지만, "223개국"(본문)·"224개국"(Table 7)이라는 수사가 시사하는 글로벌 대표성과 실체 사이의 거리는 그보다 크다. 국가별 표본 크기·언어·연령 구성이 충분히 보고되지 않아 글로벌 대표성을 평가하기 어렵다. 정렬이 잘 될수록 바로 그 특수 모집단에 더 맞춰진다.

### 5.3 이론 상계와 실제 차원의 관계

Theorem 1의 오차 상계에는 $\sqrt{\log(1/\delta)/(Nh^d)}$ 항이 들어 있다. 문항별 공간의 $d=50$과 다섯 성격 특질 공간의 $d=5$는 이 항에 매우 다른 값을 준다. 논문이 실제 상계에 어느 차원을 적용하는지를 충분히 명시하지 않으므로, 한쪽을 가정해 보증이 공허하거나 충분히 작다고 확정할 수 없다.

### 5.4 반복도, 불확실성도 없다

IS와 최종 선발 모두 확률적 표집인데 표마다 반복 횟수와 불확실성이 보고되지 않은 점추정치다. 오차막대·표준편차·유의성 검정이 전혀 없어서, Table 4 WVS의 0.04~0.07 격차 같은 곳은 샘플링 잡음과 구분할 수 없다. Raw와 RandomSelect의 차이(0.2580 vs 0.2577)가 소수 4째 자리라는 사실이 역설적으로 그 잡음 규모의 힌트다.

## 6. 방법적 한계와 확장

### 6.1 논문이 남긴 것

Appendix E(Limitations)에 적힌 한계는 정확히 둘이다: 유해 콘텐츠 필터링이 만드는 가벼운 긍정성 편향(역경·사회적 긴장의 과소대표), 그리고 시드·참조 데이터 모두 인터넷 접근 가능 인구 유래라는 것(농촌·고령·자원 부족 공동체 과소대표). §4.3의 잔여 격차 시인(4장)이 본문 쪽의 자기평가다. §5는 한계 언급 없이 성과 요약과 "고차(high-order) 시뮬레이션"이라는 future work로 닫는다.

### 6.2 방법 내재적 한계

- **LLM으로 LLM을 교정하는 순환과 support 상한.** 시드 요약·품질 채점·응답 생성·그룹 재작성 전 단계에 LLM이 개입하고, 정렬되는 것은 엄밀히 "특정 LLM이 그 페르소나로 산출하는 응답"의 분포다. 재표집은 LLM 응답 함수의 support(도달 가능한 출력 범위) 안에서만 분포를 재배치할 수 있다. RLHF로 눌려 어떤 페르소나로도 유도되지 않는 응답 영역은 복구 불가능하며, §4.3의 잔여 격차가 그 구조적 증거로 읽힌다. 품질 필터의 LLM 선호(정돈된 서사, 무해함)가 인구학적 선택 편향을 새로 주입할 가능성도 분석되지 않았다.
- **정렬 기준이 자기보고 심리측정 하나다.** OOD 3종도 Big Five와 상관이 알려진 인접 구성개념들이라, 검증된 일반화는 "자기보고 설문 도메인 내부"다. Big Five 분포가 맞는다고 소비·정치 행동이나 상호작용 동학까지 맞으리라는 근거는 없다. "behavioral consistency"(§4.2)라는 절 제목이 재는 것도 상관 행렬의 재현까지다. 행동 데이터는 논문에 없다.
- **서사형 페르소나의 대가는 인구학적 블랙박스.** 최종 셋의 연령·성별·직업 구성은 한 번도 보고되지 않는다. 그룹 재작성 단계에서는 문제가 더 커진다. "홍콩의 일반 대중을 대표하는" 페르소나를 만들라는 지시는 결국 LLM이 가진 그 지역 표상(고정관념)을 대표성의 대체물로 쓰는 것이고, Table 9의 사례들(독일 페르소나 = 복지정책 지지·집단 웰빙 선호)에서 그 흔적이 보인다.
- **모델 이식성 미확인.** 정렬용 응답을 어느 LLM으로 수집했는지 명시가 없고, 평가된 세 모델은 모두 비슷한 세대의 오픈 instruct 모델이다. 모델 세대가 바뀌면(정렬 방식이 바뀌면) 응답 함수가 바뀌어 재정렬이 필요할 텐데, 이 유지비용은 논의되지 않는다.

## 7. 결론

이 논문의 기여는 처방보다 문제의 정식화에 있다. "페르소나 셋은 통계적 정렬 대상"이라는 관점, 그리고 그것을 재는 지표·프로토콜(응답 벡터 분포 거리, in/out-of-domain 구분, 그룹 질의)은 이후 연구가 딛고 설 만한 틀이다. 처방 쪽도 정직하게 읽으면 두 겹이다. 표에서 가장 큰 효과는 좋은 시드 풀 쪽이고(Raw가 이미 전부 이긴다), 정렬은 그 위의 개선분이다. 반면 보고의 정밀도(본문-표 불일치, 규모 불일치, 검증 불가 주장)는 프리프린트 상태의 거친 면을 그대로 노출하며, WVS 지역 정렬의 낮은 절대 수준은 이 접근의 현재 한계선을 긋는다.

## References

Argyle, L. P., Busby, E. C., Fulda, N., Gubler, J. R., Rytting, C., & Wingate, D. (2023). Out of one, many: Using language models to simulate human samples. *Political Analysis*, *31*(3), 337–351. https://doi.org/10.1017/pan.2023.2 ([PDF 보기](/paper-viewer?title=Out+of+one%2C+many%3A+Using+language+models+to+simulate+human+samples&source=blog-reference&authors=Lisa+P.+Argyle%3BEthan+C.+Busby%3BNancy+Fulda%3BJoshua+R.+Gubler%3BChristopher+Rytting%3BDavid+Wingate&year=2023&doi=10.1017%2Fpan.2023.2&url=https%3A%2F%2Fdoi.org%2F10.1017%2Fpan.2023.2))

Duckworth, A. L., Peterson, C., Matthews, M. D., & Kelly, D. R. (2007). Grit: Perseverance and passion for long-term goals. *Journal of Personality and Social Psychology*, *92*(6), 1087–1101. https://doi.org/10.1037/0022-3514.92.6.1087 ([PDF 보기](/paper-viewer?title=Grit%3A+Perseverance+and+passion+for+long-term+goals&source=blog-reference&authors=Angela+L.+Duckworth%3BChristopher+Peterson%3BMichael+D.+Matthews%3BDennis+R.+Kelly&year=2007&doi=10.1037%2F0022-3514.92.6.1087&url=https%3A%2F%2Fdoi.org%2F10.1037%2F0022-3514.92.6.1087))

Hu, Z., Lian, J., Xiao, Z., Xiong, M., Lei, Y., Wang, T., Ding, K., Xiao, Z., Yuan, N. J., & Xie, X. (2025). *Population-aligned persona generation for LLM-based social simulation* (arXiv:2509.10127). arXiv. https://arxiv.org/abs/2509.10127 ([PDF 보기](/paper-viewer?title=Population-aligned+persona+generation+for+LLM-based+social+simulation&source=blog-reference&authors=Zhengyu+Hu%3BJianxun+Lian%3BZheyuan+Xiao%3BMax+Xiong%3BYuxuan+Lei%3BTianfu+Wang%3BKaize+Ding%3BZiang+Xiao%3BNicholas+Jing+Yuan%3BXing+Xie&year=2025&arxiv_id=2509.10127&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2509.10127.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F2509.10127))

Santurkar, S., Durmus, E., Ladhak, F., Lee, C., Liang, P., & Hashimoto, T. (2023). Whose opinions do language models reflect? *Proceedings of the 40th International Conference on Machine Learning*, 29971–30004. https://arxiv.org/abs/2303.17548 ([PDF 보기](/paper-viewer?title=Whose+opinions+do+language+models+reflect%3F&source=blog-reference&authors=Shibani+Santurkar%3BEsin+Durmus%3BFaisal+Ladhak%3BCinoo+Lee%3BPercy+Liang%3BTatsunori+Hashimoto&year=2023&arxiv_id=2303.17548&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2303.17548.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F2303.17548))

Schler, J., Koppel, M., Argamon, S., & Pennebaker, J. W. (2006). Effects of age and gender on blogging. *AAAI Spring Symposium: Computational Approaches to Analyzing Weblogs*, 199–205. ([PDF 보기](/paper-viewer?title=Effects+of+age+and+gender+on+blogging&source=blog-reference))

Strathman, A., Gleicher, F., Boninger, D. S., & Edwards, C. S. (1994). The consideration of future consequences: Weighing immediate and distant outcomes of behavior. *Journal of Personality and Social Psychology*, *66*(4), 742–752. https://doi.org/10.1037/0022-3514.66.4.742 ([PDF 보기](/paper-viewer?title=The+consideration+of+future+consequences%3A+Weighing+immediate+and+distant+outcomes+of+behavior&source=blog-reference&authors=Alan+Strathman%3BFaith+Gleicher%3BDavid+S.+Boninger%3BC.+Scott+Edwards&year=1994&doi=10.1037%2F0022-3514.66.4.742&url=https%3A%2F%2Fdoi.org%2F10.1037%2F0022-3514.66.4.742))
