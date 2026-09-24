# Locating and Editing Factual Associations in GPT

**Paper:** Kevin Meng; David Bau; Alex Andonian; Yonatan Belinkov (2022). "Locating and Editing Factual Associations in GPT". https://proceedings.neurips.cc/paper_files/paper/2022/hash/6f1d43d5a82a37e89b0665b33bf3a182-Abstract-Conference.html · arXiv:2202.05262

**Abstract:** 이 논문은 autoregressive transformer가 사실 연상(subject–relation–object)을 어디에 저장하고 어떻게 회상하는지를 두 축으로 다룬다. 첫째, causal tracing은 입력의 subject token embedding을 잡음으로 손상시킨 뒤 특정 hidden state만 깨끗한 값으로 되돌리는 개입으로, 어느 위치의 activation이 사실 예측을 매개하는지 indirect effect로 측정한다. 이 분석은 마지막 subject token의 중간 층 MLP 출력에 인과 효과가 집중되는 "early site"를 발견한다. 둘째, ROME(Rank-One Model Editing)은 그 MLP의 down-projection 가중치를 선형 연상기억으로 보고 rank-one 업데이트로 새 (key, value) 쌍을 삽입해 하나의 사실을 바꾼다. GPT-2 XL과 GPT-J에서 ROME은 편집한 사실의 일반화와 무관한 사실의 보존을 동시에 높게 유지했다. 다만 결과는 논문이 정의한 잡음 손상, subject token 개입, counterfactual 편집 설정에 조건부인 모델 내부 인과 효과다.

---

## Executive Summary

- **연구 질문:** GPT가 "Space Needle is located in ___" 같은 사실을 예측할 때, 어느 hidden state가 그 예측을 인과적으로 매개하며 그 위치를 편집하면 사실을 바꿀 수 있는가?
- **분석 도구:** causal tracing. 깨끗한 실행, subject token embedding을 손상시킨 실행, 손상 상태에서 특정 state만 복원한 실행 세 가지를 비교해 indirect effect를 계산한다.
- **핵심 발견:** 마지막 subject token 위치의 중간 층 MLP 출력이 사실 회상을 매개하는 "early site"다. 개별 state의 평균 간접 효과(AIE)는 15층 부근에서 8.7%로 정점을 찍고, 이 효과의 대부분은 attention이 아니라 MLP가 담당한다(MLP 기여 정점 6.6% 대 attention 1.6%).
- **편집 방법:** ROME은 지목된 MLP의 down-projection 행렬 $W_{proj}$를 key–value 저장소로 보고 rank-one 업데이트로 새 연상을 삽입한다.
- **주요 결과:** CounterFact에서 ROME(GPT-2 XL) 종합 점수 89.2로, 일반화(96.4)와 특이성(75.4)을 동시에 확보한다. fine-tuning 계열은 둘 중 하나를 희생한다.
- **핵심 한계:** 인과 효과는 잡음 손상 방식, subject token 개입, 단일 사실 편집 설정에 조건부다. localization은 "어디서 회상이 매개되는가"이지 "사실이 오직 그곳에만 저장된다"는 뜻이 아니다.

**TL;DR**

- ROME(Rank-One Model Editing)은 causal tracing으로 지목한 중간 층 MLP의 down-projection 가중치를 rank-one으로 갱신해 GPT의 단일 사실 연상을 편집하는 방법이다.
- ROME은 CounterFact에서 GPT-2 XL 종합 점수 89.2(efficacy 100.0·generalization 96.4·specificity 75.4)와 GPT-J 91.5를 기록해, fine-tuning 계열이 일반화와 특이성 중 하나를 희생하는 절충을 피한다.
- ROME은 하나의 (subject, relation, object) 사실을 정밀하게 바꿀 때 유리하지만, 그 인과 지목과 수치는 잡음 손상·subject token 개입·단일 반사실 편집 설정에 조건부이며 매개 지점을 찾은 것이 저장의 국소성을 증명하지는 않는다.

## 목차

1. 왜 상관이 아니라 개입인가
2. Causal tracing의 정의와 수식
3. ROME: MLP를 선형 연상기억으로 편집하기
4. 실험 설계
5. 결과
6. 논문의 주장과 근거 범위
7. 한계와 해석 범위
8. 결론

## 1. 왜 상관이 아니라 개입인가

어떤 뉴런이 "Seattle"을 예측할 때 강하게 활성화된다는 관찰은 그 뉴런이 예측을 **일으킨다**는 뜻이 아니다. 그 activation은 다른 계산의 부산물일 수도 있다. Meng et al.은 이 문제를 Pearl의 인과매개 분석과 Vig et al. (2020)의 언어모델 개입 계보 위에서 다룬다. 상관 관찰 대신, 내부 state에 직접 개입해 예측이 얼마나 바뀌는지를 본다.

논문은 사실 연상을 (subject $s$, relation $r$, object $o$) 삼중항으로 놓는다. 예를 들어 "The Space Needle is located in the city of"라는 프롬프트에서 모델이 "Seattle"을 예측하는 사건이다. 질문은 두 단계다. 첫째, 이 예측을 매개하는 hidden state는 어디에 있는가(causal tracing). 둘째, 그 위치의 가중치를 바꾸면 예측을 원하는 대로 바꿀 수 있는가(ROME). 첫 질문은 activation에 대한 개입이고, 둘째 질문은 weight에 대한 개입이다.

## 2. Causal tracing의 정의와 수식

![Causal tracing의 세 실행: 정상 실행, subject token 손상 실행, 특정 state 복원 실행](/api/blog/figures/rome-fig1-causal-trace.png)

*그림 1. causal tracing은 네트워크를 세 번 실행한다. (a) 정상 실행으로 모든 hidden state를 수집하고, (b) subject token의 embedding을 잡음으로 손상시켜 예측을 무너뜨린 뒤, (c) 손상 상태에서 특정 위치의 state만 깨끗한 값으로 복원해 예측이 회복되는 정도를 잰다. Meng et al. (2022)의 원 논문 Figure 1, PDF p. 1을 여백만 크롭했다. 내용은 수정하지 않았다. 이 프리프린트는 arXiv 비독점 배포 라이선스(nonexclusive-distrib/1.0/, CC BY 아님)로 배포되며, 학술 비평을 위한 제한적 원 도판 인용이다. 공식 링크: https://arxiv.org/abs/2202.05262.*

causal tracing은 세 실행을 비교한다.

**깨끗한 실행(clean run).** 사실 프롬프트를 그대로 통과시켜 모든 hidden state $\{h_i^{(l)}\}$를 저장한다. 여기서 $i$는 token 위치, $l$은 층이다. 이때 정답 object의 확률을 $\mathbb{P}[o]$라 한다.

**손상 실행(corrupted run).** embedding 직후 subject token들에 잡음을 더한다.

$$
h_i^{(0)} := h_i^{(0)} + \varepsilon, \qquad \varepsilon \sim \mathcal{N}(0,\ \nu),\quad \nu = 3\sigma.
$$

$\sigma$는 embedding 성분의 표준편차이고 잡음 크기는 그 3배다. subject를 알아볼 수 없게 만든 뒤 모델을 계속 진행시키면 사실 예측이 무너진다. 이때 확률을 $\mathbb{P}_*[o]$라 한다.

**손상-복원 실행(corrupted-with-restoration run).** 손상 상태에서 진행하되 특정 $(i,l)$의 hidden state 하나만 깨끗한 실행에서 저장한 값으로 강제 복원하고 나머지 계산은 손상 상태로 둔다. 그 한 state가 사실 예측을 얼마나 되살리는지가 그 위치의 인과적 몫이다.

이로부터 두 양을 정의한다. total effect는 손상이 예측을 무너뜨린 총량이고, indirect effect는 특정 state 복원이 되살린 양이다.

$$
\mathrm{TE} = \mathbb{P}[o] - \mathbb{P}_*[o], \qquad
\mathrm{IE} = \mathbb{P}_{*,\,\mathrm{clean}\ h_i^{(l)}}[o] - \mathbb{P}_*[o].
$$

여러 사실 표본에 대해 IE를 평균한 것이 average indirect effect(AIE)다. 1000개 사실 문장에 대한 평균 total effect는 18.6%였다. 즉 잡음 손상은 정답 확률을 평균 18.6%포인트가량 떨어뜨렸고, 이 무너진 예측을 어느 state가 얼마나 복구하는지를 AIE가 위치별로 보여준다.

![층·토큰별 average indirect effect가 두 site를 드러낸다](/api/blog/figures/rome-fig2-aie-two-sites.png)

*그림 2. 1000개 사실 문장에 대한 개별 model component의 average indirect effect. 마지막 층 마지막 token의 강한 인과성("late site")은 예상된 것이지만, 마지막 subject token의 중간 층에 있는 강한 인과 state("early site")가 새 발견이다. Meng et al. (2022)의 원 논문 Figure 2, PDF p. 4를 크롭했다. 내용 수정 없음. 출처는 위와 동일한 arXiv 비독점 라이선스 프리프린트이며 학술 비평용 제한적 인용이다.*

AIE 지도는 두 곳에서 정점을 보인다. 하나는 마지막 층 마지막 token 부근의 **late site**로, 예측 직전에 정보가 모이는 것이므로 놀랍지 않다. 다른 하나는 마지막 subject token 위치의 중간 층에 있는 **early site**로, 이것이 논문의 발견이다. 개별 hidden state의 AIE는 15층 부근에서 8.7%로 정점을 찍는다.

이어 논문은 이 early site의 정체를 MLP와 attention으로 분해한다. 특정 층·token에서 MLP 출력만 복원하거나 attention 출력만 복원해 각각의 AIE를 잰다. early site에서 MLP 기여가 6.6%로 정점을 찍는 반면 같은 위치의 attention 기여는 1.6%에 그친다. 반대로 late site에서는 attention이 32층에서 16.5%로 지배적이다. 즉 사실 회상은 중간 층 MLP가 매개하고, 마지막 예측으로의 전달은 후반 attention이 담당한다.

![MLP를 끊었을 때 하위 층 인과 효과가 사라지는 severed 분석](/api/blog/figures/rome-fig3-mlp-attention-severed.png)

*그림 3. 계산 그래프를 변형해 MLP 모듈의 기여를 분리한 causal trace. MLP 출력을 손상 baseline 상태로 고정("severed")하면 하위 층의 인과 효과가 사라지지만(그 효과가 하류 MLP에 의존한다는 뜻), 상위 층은 효과를 유지한다. attention을 끊었을 때는 이런 전환이 나타나지 않아, 중간 층 MLP 계산이 사실 회상에 본질적 역할을 함을 확인한다. Meng et al. (2022)의 원 논문 Figure 3, PDF p. 5를 크롭했다. 내용 수정 없음. 위와 동일한 arXiv 비독점 라이선스 프리프린트의 학술 비평용 제한적 인용이다.*

MLP severed 실험은 방향을 더 굳힌다. 복원할 때 MLP 출력을 손상 baseline 값으로 얼려두면, 하위 층 state의 인과 효과가 사라진다. 그 효과가 하류 MLP를 거쳐야만 발현된다는 뜻이다. 반면 상위 층은 MLP를 얼려도 효과가 남는다. attention을 대신 얼렸을 때는 이런 층별 전환이 관찰되지 않는다. 이 비대칭이 "중간 층 MLP가 사실 회상에 본질적"이라는 주장의 근거다.

## 3. ROME: MLP를 선형 연상기억으로 편집하기

localization이 MLP를 지목했으니, ROME은 그 MLP의 가중치를 직접 바꾼다. 핵심 관점은 Geva et al. (2021)을 잇는다. transformer MLP의 두 번째 행렬(down-projection) $W_{proj}$를 **선형 연상기억**으로 본다. 즉 여러 key $k$를 대응하는 value $v$로 사상하는 저장소이며, 근사적으로 $W_{proj} K \approx V$를 푼다. 여기서 key는 MLP 비선형 이후의 내부 activation이고 value는 MLP가 residual stream에 더하는 출력이다.

새 사실 하나를 넣는 것은 특정 key $k_*$(subject를 인코딩)가 특정 value $v_*$(새 object를 유도)로 사상되도록 만드는 일이다. ROME은 나머지 저장 내용을 최소한만 건드리며 이 한 쌍을 삽입하는 제약 최소자승 문제를 풀고, 그 닫힌 해가 rank-one 업데이트다.

$$
\hat{W} = W + \Lambda\,(C^{-1}k_*)^{\top},
\qquad
\Lambda = \frac{v_* - W k_*}{(C^{-1}k_*)^{\top} k_*}.
$$

여기서 $C = K K^{\top}$는 기존 key들의 이차 통계(공분산에 비례)로, 위키피디아 텍스트에서 활성화를 수집해 미리 추정한다. $C^{-1}$은 새 key를 삽입할 때 기존 key와의 간섭을 억제하는 역할을 한다. 이 업데이트는 $\hat{W}k_* = v_*$를 정확히 만족시키면서 다른 key들에 대한 출력 변화를 최소화한다.

$k_*$는 subject의 마지막 token 위치, 지목된 층 $l^*$에서 MLP 비선형 직후의 activation이다. 프롬프트 앞에 여러 무작위 접두를 붙여 $N=50$개 실행의 평균을 취해 문맥 편차를 줄인다.

$$
k_* = \frac{1}{N}\sum_{j=1}^{N} k(x_j + s),
\qquad
k(x) = \sigma\!\Big(W_{fc}^{(l^*)}\,\gamma\big(a^{(l^*)}_{[x],i} + h^{(l^*-1)}_{[x],i}\big)\Big).
$$

$v_*$는 최적화로 찾는다. 지목된 MLP 출력을 벡터 $z$로 대체했을 때 모델이 새 object $o^*$를 예측하도록 하되, subject의 다른 속성이 뭉개지는 "essence drift"를 억제하는 KL 항을 더한다.

$$
\mathcal{L}(z) = \frac{1}{N}\sum_{j=1}^{N}
\Big[-\log \mathbb{P}_{G(m^{(l^*)}_i := z)}\big[o^* \mid x_j + p\big]\Big]
+ D_{\mathrm{KL}}\!\Big(\mathbb{P}_{G(m^{(l^*)}_{i'} := z)}[x \mid p'] \,\big\|\, \mathbb{P}_{G}[x \mid p']\Big).
$$

첫 항은 여러 접두 $x_j$에서 목표 object의 확률을 높이고, 둘째 항은 "{subject} is a" 같은 프롬프트 $p'$에서 원래 예측 분포를 유지시킨다. 최적화된 $z$가 $v_*$가 되고, 이를 위 rank-one 식에 넣어 $W_{proj}^{(l^*)}$ 하나만 수정한다. 학습되는 것은 이 벡터 $v_*$뿐이며, 모델 전체를 재학습하지 않는다.

## 4. 실험 설계

편집 평가에는 두 데이터셋을 쓴다. **zsRE**는 질의응답 기반 관계 추출 벤치마크에서 가져온 10,000개 레코드로, 기존 편집 문헌이 쓰던 표준 세트다. **CounterFact**는 이 논문이 새로 만든 21,919개 레코드로, 반사실적(counterfactual) object를 주입한다. 즉 편집 전에는 확률이 낮았던 틀린 답을 새 사실로 넣는다. 각 레코드에는 같은 사실의 패러프레이즈 프롬프트와, 주제가 다르지만 관계가 비슷한 이웃(neighborhood) 프롬프트가 딸려 있어 일반화와 특이성을 분리 측정할 수 있다.

비교 대상은 편집 방법 다섯 계열이다. Adam으로 미세조정하는 **FT**, $L_\infty$ 제약을 건 미세조정 **FT+L**(Zhu et al., 2020), hypernetwork로 편집을 예측하는 **KE**(De Cao et al., 2021)와 **MEND**(Mitchell et al., 2021), gradient 귀속으로 뉴런을 지목해 조정하는 **KN**(Dai et al., 2022)이다.

측정 지표는 세 축을 정량화한다. 편집한 사실 자체에 대한 **efficacy**(ES는 새 object 확률이 옛 object보다 높은 비율, EM은 그 확률차), 패러프레이즈에 대한 **generalization**(PS/PM), 무관한 이웃 사실 보존에 대한 **specificity**(NS/NM)다. 여기에 생성 품질로 **fluency**(생성 텍스트의 bi/tri-gram 엔트로피)와 **consistency**(같은 object를 공유하는 참조 텍스트와의 TF-IDF 코사인 유사도)를 본다. 종합 점수 $S$는 efficacy·generalization·specificity의 조화평균이라 세 축 중 하나만 낮아도 크게 깎인다. 편집 모델은 GPT-2 XL(1.5B, 48층)과 GPT-J(6B, 28층)이며, ROME이 수정하는 층은 causal tracing이 지목한 중간 층(GPT-2 XL에서 대략 17층)이다.

## 5. 결과

CounterFact 시험 세트(GPT-2 XL 7,500개, GPT-J 2,000개)에서 ROME(GPT-2 XL)의 종합 점수는 89.2다. efficacy 100.0, generalization 96.4, specificity 75.4로 세 축이 모두 높다. 대조군은 축 사이의 절충을 드러낸다. FT는 generalization 87.9는 얻지만 specificity가 40.4로 무너지고, 반대로 FT+L은 specificity 70.3을 지키는 대신 generalization이 48.7로 낮다. KE(52.2)와 MEND(57.9)는 종합 점수 자체가 ROME에 크게 못 미친다. 즉 미세조정 계열은 편집을 일반화시키면 무관한 사실을 오염시키고, 오염을 막으면 일반화를 잃는데, ROME은 rank-one 삽입으로 두 축을 동시에 유지한다. 더 큰 GPT-J에서도 같은 패턴이 이어져 ROME 종합 점수는 91.5(efficacy 99.9, generalization 99.1, specificity 78.9)다.

생성 품질에서는 절충이 보인다. ROME의 fluency(621.9)와 consistency(41.9)는 FT+L 등과 대체로 비슷하지만, 저자들의 사람 평가에서 ROME은 FT+L보다 1.8배 일관적이라고 평가되는 대신 1.3배 덜 유창하다고 평가됐다. 두 지표가 반대로 움직인다는 점을 논문 스스로 기록한다.

편집 층을 바꿔가며 성능을 훑은 결과(Figure 5)는 causal tracing과 맞물린다. 마지막 subject token에서 중간 층 MLP를 편집할 때 성능이 정점을 찍고, late site나 다른 token을 편집하면 떨어진다. 개입 두 종류(activation을 손상·복원한 tracing, weight를 수정한 편집)가 같은 위치를 지목한다는 점이 논문의 내적 정합성 근거다.

## 6. 논문의 주장과 근거 범위

논문의 주장은 신중히 읽어야 한다. causal tracing이 말하는 것은 "마지막 subject token의 중간 층 MLP가 사실 회상을 **매개한다**"는 것이지, "사실이 오직 그 가중치에만 저장돼 있다"는 것이 아니다. AIE는 그 위치의 state를 복원하면 예측이 되살아난다는 개입 효과이며, 같은 정보가 다른 경로에도 중복될 가능성을 배제하지 않는다.

ROME의 편집 성공은 이 매개 주장의 충분조건 쪽 증거다. 지목된 MLP 하나를 rank-one으로 바꿨더니 사실이 일반화되며 바뀌었다는 것은, 그 위치가 회상 경로의 실효적 지점임을 뒷받침한다. 그러나 편집이 작동한다는 사실이 "저장이 국소적"임을 증명하지는 않는다. 편집은 예측을 바꾸는 데 충분한 한 지점을 찾은 것이지, 그 지점이 유일한 저장소임을 보인 것이 아니다. 논문의 수치도 이 조건성 위에 있다. total effect 18.6%, AIE 8.7%, MLP 6.6% 같은 값은 모두 잡음 크기 $\nu = 3\sigma$, subject token 손상, CounterFact 반사실 편집이라는 특정 설정에서 얻은 값이다.

## 7. 한계와 해석 범위

- **잡음 손상 방식 의존성.** early site와 그 AIE 크기는 embedding에 Gaussian 잡음을 더하는 특정 손상에 의존한다. 손상 분포나 잡음 크기 $\nu$를 바꾸면 복원 효과의 절대값이 달라질 수 있어, AIE는 절대 척도라기보다 이 개입 설정에 대한 상대 지표로 읽어야 한다.
- **Hybrid state의 비자연성.** 손상된 실행에 깨끗한 state 하나를 이식한 상태는 실제 문장 처리에서 자연히 생기지 않는 조합이다. 개입 결과는 관찰적 상관보다 강하지만, 정의한 내부 개입에 대한 모델 인과성으로 제한해 해석해야 한다.
- **단일 사실·단일 편집 범위.** ROME은 한 번에 하나의 (s,r,o) 사실을 편집한다. 대량 편집이나 순차 편집에서의 누적 간섭은 이 논문의 범위 밖이며, 이후 후속 연구(예: 대량 편집)가 다루는 별도 문제다.
- **counterfactual 편집의 특수성.** CounterFact는 원래 확률이 낮던 반사실 object를 주입한다. 이는 편집 성공을 민감하게 재는 장점이 있지만, 편집 대상이 이미 그럴듯한 참 사실인 경우의 동역학과는 다를 수 있다.
- **essence drift의 부분적 통제.** $v_*$ 최적화의 KL 항은 subject의 다른 속성 붕괴를 억제하려는 장치이지만, "{subject} is a" 형태의 프롬프트로 근사한 통제라 모든 속성 보존을 보장하지 않는다. specificity 75.4가 100이 아니라는 사실이 이 잔여 오염을 반영한다.
- **localization과 저장의 구분.** 앞서 적었듯 매개 지점과 저장 위치는 다른 개념이다. causal tracing은 전자를 측정하며, 논문의 강한 표현("factual associations correspond to localized computations")은 이 구분을 흐릴 여지가 있다.

## 8. 결론

Meng et al.은 "어느 뉴런이 사실을 볼 때 켜지는가"라는 질문을, 손상-복원 개입으로 "어느 state를 되돌리면 사실 예측이 살아나는가"로 바꾼다. 이 causal tracing은 마지막 subject token의 중간 층 MLP를 사실 회상의 매개 지점으로 지목하고, ROME은 그 MLP의 down-projection을 선형 연상기억으로 보아 rank-one 업데이트로 하나의 사실을 바꾼다. 두 개입이 같은 위치를 가리킨다는 정합성, 그리고 편집이 일반화와 특이성을 동시에 유지한다는 결과가 논문의 핵심 근거다. 다만 이 모든 수치와 지목은 잡음 손상 방식, subject token 개입, 단일 반사실 편집이라는 설정에 조건부이며, 매개 지점을 찾은 것과 저장이 국소적임을 증명한 것은 구분해야 한다.

## References

Dai, D., Dong, L., Hao, Y., Sui, Z., Chang, B., & Wei, F. (2022). Knowledge neurons in pretrained transformers. In *Proceedings of the 60th Annual Meeting of the Association for Computational Linguistics* (pp. 8493–8502). Association for Computational Linguistics. https://doi.org/10.18653/v1/2022.acl-long.581

De Cao, N., Aziz, W., & Titov, I. (2021). Editing factual knowledge in language models. In *Proceedings of the 2021 Conference on Empirical Methods in Natural Language Processing* (pp. 6491–6506). Association for Computational Linguistics. https://doi.org/10.18653/v1/2021.emnlp-main.522

Geva, M., Schuster, R., Berant, J., & Levy, O. (2021). Transformer feed-forward layers are key-value memories. In *Proceedings of the 2021 Conference on Empirical Methods in Natural Language Processing* (pp. 5484–5495). Association for Computational Linguistics. https://doi.org/10.18653/v1/2021.emnlp-main.446

Meng, K., Bau, D., Andonian, A., & Belinkov, Y. (2022). Locating and editing factual associations in GPT. *Advances in Neural Information Processing Systems, 35*, 17359–17372. https://arxiv.org/abs/2202.05262

Mitchell, E., Lin, C., Bosselut, A., Finn, C., & Manning, C. D. (2022). Fast model editing at scale. In *International Conference on Learning Representations*. https://arxiv.org/abs/2110.11309

Vig, J., Gehrmann, S., Belinkov, Y., Qian, S., Nevo, D., Singer, Y., & Shieber, S. (2020). Investigating gender bias in language models using causal mediation analysis. *Advances in Neural Information Processing Systems, 33*, 12388–12401. https://proceedings.neurips.cc/paper_files/paper/2020/hash/92650b2e92217715fe312e6fa7b90d82-Abstract.html

Zhu, C., Rawat, A. S., Zaheer, M., Bhojanapalli, S., Li, D., Yu, F., & Kumar, S. (2020). *Modifying memories in transformer models* (arXiv:2012.00363). arXiv. https://arxiv.org/abs/2012.00363
