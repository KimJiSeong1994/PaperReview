# SEED: Self-Evolving On-Policy Distillation for Agentic Reinforcement Learning

**Paper:** Wu, J., Yang, S., Lu, Z., Zhang, F., Shen, Y., Feng, L., Luo, H., Lian, Z., Zhang, S., Wen, Z., & Tao, J. (2026). *SEED: Self-evolving on-policy distillation for agentic reinforcement learning* (arXiv:2607.14777v1, submitted July 16, 2026). Code: https://github.com/jinyangwu/SEED

**Abstract:** Long-horizon agent의 terminal reward는 episode의 성공 여부는 알려 주지만, 어떤 검색어·도구 호출·상태 확인이 유익했는지는 말해 주지 않는다. SEED는 완료된 on-policy trajectory를 자연어 hindsight skill로 요약한다. 이어 이미 실행된 같은 action token을 일반 문맥과 skill-augmented 문맥에서 각각 다시 평가해 token 수준의 distillation signal을 만든다. 저자 보고 기준 SEED는 세 text backbone의 모든 GRPO 집계 비교를 개선했고, ALFWorld에서는 Stage 2 학습 data 60%만으로 full-data GRPO를 넘어섰다. 다만 Stage 1은 외부 GLM-5.2 analyzer에 의존한다. Actor와 analyzer가 같은 blind spot을 가질 수 있으며, 이론도 skill의 정확성을 보장하지 않는다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 희소한 trajectory reward만으로 학습하는 long-horizon agent에 token 단위의 supervision을 어떻게 보탤 것인가? |
| 핵심 기여 | 현재 policy의 완료 trajectory에서 hindsight skill을 생성하고, 같은 sampled action을 ordinary/skill context에서 쌍으로 재채점해 dense on-policy distillation signal을 만든다. |
| 방법적 결과 | Stage 1에서 trajectory→skill 분석 능력을 SFT로 심은 뒤, Stage 2에서 최신 frozen checkpoint를 actor와 analyzer로 함께 사용한다. RL loss와 confidence-gated OPD loss를 공동 최적화하며, inference에서는 skill·analyzer·retrieval이 필요 없다. |
| 실험 결과 | GRPO 대비 Qwen2.5-3B의 ALFWorld 75.0→91.8, Search 36.4→45.7, WebShop success 63.3→78.9. 세 backbone의 모든 aggregate GRPO 비교에서 개선했지만, 모든 baseline·metric에서 1위인 것은 아니다. |
| 핵심 한계 | 초기 skill annotation은 외부 GLM-5.2가 필요하다. Skill support가 실제 action value와 양의 상관이어야 하며, 동일 actor/analyzer가 공유 오류를 self-reinforce할 수 있다. Multi-seed 분산과 총 학습 비용도 충분히 보고되지 않았다. |

## 목차

1. 왜 terminal reward만으로 부족한가
2. SEED의 두 단계 학습 구조
3. 같은 행동을 두 문맥에서 재채점하기
4. OPD와 GRPO의 공동 목적함수
5. 이론이 보장하는 것과 보장하지 않는 것
6. 실험 결과
7. 기존 접근과의 차이
8. 한계와 재현성
9. 결론

---

## 1. 왜 terminal reward만으로 부족한가

Agentic RL의 한 episode에는 observation과 action이 수십 차례 이어진다. ALFWorld agent라면 물건을 찾고, 집고, 상태를 바꾸고, 목표 위치에 놓아야 한다. Search agent라면 질의를 만들고, 문서를 읽고, 근거를 연결해 답을 내야 한다. 마지막 성공 점수 하나만으로는 어느 중간 판단을 강화해야 하는지 알기 어렵다.

논문은 이 문제를 POMDP로 정식화한다. 시점 $t$의 interaction history와 policy는 다음과 같다.

$$
h_t=(o_0,a_0,o_1,a_1,\ldots,o_t),
\qquad
a_t\sim\pi_\theta(\cdot\mid h_t).
$$

완료된 trajectory와 표준 RL 목적은

$$
\tau=\{(o_t,a_t,r_t)\}_{t=0}^{T-1},
\qquad
J(\theta)=\mathbb{E}_{\tau\sim\pi_\theta}[R(\tau)]
$$

이다. $R(\tau)$가 trajectory 전체에 한 번만 주어지면, GRPO 같은 outcome-based method는 그 안의 모든 유효 token에 같은 group-relative advantage를 부여한다. 성공 trajectory 안의 불필요한 우회와 실패 trajectory 안의 좋은 부분 행동을 구별하기 어려운 구조다.

SEED는 의사결정 중에는 알 수 없던 정보가 episode가 끝난 뒤 드러난다는 데서 출발한다. 전체 trajectory를 보면 어떤 observation이 결정적이었는지, 어디서 잘못된 대상에 집착했는지, 어떤 workflow를 다음 시도에 재사용할 수 있는지 설명할 수 있다. SEED는 이 사후 정보를 자연어 **hindsight skill**로 압축해 policy 학습에 다시 사용한다.

---

## 2. SEED의 두 단계 학습 구조

![SEED 전체 파이프라인](/api/blog/figures/seed-pipeline.png)

*그림 1. Hindsight Skill SFT와 Self-Evolving On-Policy Distillation의 두 단계를 연결한 SEED 파이프라인. 공식 SEED 코드 저장소의 `figs/pipeline.png`를 복사했으며, 논문 Figure 2의 방법 구조를 설명한다. 원 도식은 수정하지 않았다.*

### 2.1 Stage 1 — trajectory를 읽는 능력부터 학습한다

첫 단계의 목적은 강한 actor를 만드는 것이 아니다. 모델이 완료된 trajectory를 읽고 재사용 가능한 skill을 작성하도록 초기화하는 단계다.

1. 각 benchmark에서 180개 task를 뽑는다.
2. Base policy가 task마다 8개 rollout을 생성해 1,440개 completed trajectory를 만든다.
3. 외부 GLM-5.2 analyzer가 성공 trajectory에서는 workflow를, 실패 trajectory에서는 correction·avoidance rule을 작성한다.
4. 형식 검사를 통과한 trajectory–skill pair로 backbone을 3 epoch SFT한다.

외부 analyzer의 annotation은

$$
s_\tau=A_{\mathrm{ext}}(\tau)
$$

로 쓸 수 있다. SFT objective는 trajectory input $x_\tau$에서 skill token을 생성하는 표준 negative log-likelihood다.

$$
\mathcal{L}_{\mathrm{sft}}(\theta)
=
-\mathbb{E}_{(x_\tau,s_\tau)\sim D_{\mathrm{sft}}}
\left[
\sum_{\ell=1}^{|s_\tau|}
\log\pi_\theta(s_{\tau,\ell}\mid x_\tau,s_{\tau,<\ell})
\right].
$$

논문의 validity gate는 생성된 skill의 **형식**만 검사하며, 행동적 타당성을 확인하는 semantic verifier는 없다. 따라서 외부 analyzer의 오류가 Stage 1을 통해 초기 policy에 들어갈 수 있다.

### 2.2 Stage 2 — 최신 checkpoint가 actor와 analyzer를 겸한다

각 outer update가 시작되면 현재 policy를 $\pi_{\theta_{\mathrm{old}}}$로 복사해 고정한다. 이 checkpoint가 두 역할을 맡는다.

| 역할 | 입력 | 출력 |
| --- | --- | --- |
| Actor | task와 현재 interaction history | on-policy trajectory group |
| Analyzer | task, 완료 trajectory, terminal outcome | episode-level hindsight skill |

Task $q$마다 $N$개의 trajectory를 모은다.

$$
G_q=\{\tau_q^{(1)},\ldots,\tau_q^{(N)}\},
\qquad
\tau_q^{(n)}\sim\pi_{\theta_{\mathrm{old}}}(\cdot\mid q).
$$

같은 frozen checkpoint의 analyzer role이 각 trajectory를 skill로 바꾼다.

$$
s_q^{(n)}=A_{\theta_{\mathrm{old}}}\!\left(x_{\tau_q^{(n)}}\right).
$$

Update가 끝나면 학습된 $\pi_\theta$가 다음 iteration의 actor와 analyzer가 된다. 여기서 “self-evolving”은 별도의 analyzer population이 진화한다는 뜻이 아니다. 하나의 checkpoint가 행동 능력과 trajectory 분석 능력을 함께 갱신한다는 의미다.

---

## 3. 같은 행동을 두 문맥에서 재채점하기

SEED는 hindsight skill을 이용해 trajectory를 새로 생성하지 않는다. Frozen policy가 이미 만든 action token을 고정한 뒤, 학습 중인 $\pi_\theta$에서 두 문맥의 확률을 teacher forcing으로 다시 계산한다.

Ordinary history $h_{q,n,t}$에 trajectory skill을 삽입한 문맥을

$$
\widetilde h_{q,n,t}
=
H\!\left(h_{q,n,t},s_q^{(n)}\right)
$$

라고 하자. 같은 sampled action token $a_{q,n,t,\ell}$에 대해 두 log-probability를 계산한다.

$$
\ell^{\mathrm{skill}}_{q,n,t,\ell}
=
\log\pi_\theta
\left(
a_{q,n,t,\ell}
\mid
\widetilde h_{q,n,t},a_{q,n,t,<\ell}
\right),
$$

$$
\ell^\theta_{q,n,t,\ell}
=
\log\pi_\theta
\left(
a_{q,n,t,\ell}
\mid
h_{q,n,t},a_{q,n,t,<\ell}
\right).
$$

논문은 첫 번째 branch를 teacher라고 부르지만, 더 크거나 별도로 고정된 teacher model을 뜻하지는 않는다. Algorithm 1에서 두 값은 모두 현재의 $\pi_\theta$로 계산되며, 입력 context만 다르다. Skill branch의 값과 gate에는 stop-gradient가 적용되고, gradient는 ordinary branch로만 흐른다.

Skill이 해당 token을 얼마나 지지하는지는 detached log-probability shift로 측정한다.

$$
\Delta_{q,n,t,\ell}
=
\operatorname{sg}
\left[
\ell^{\mathrm{skill}}_{q,n,t,\ell}
-
\ell^\theta_{q,n,t,\ell}
\right].
$$

이를 sigmoid gate로 바꾼다.

$$
g_{q,n,t,\ell}
=
\sigma\!\left(\beta_{\mathrm{opd}}\Delta_{q,n,t,\ell}\right).
$$

Skill context에서 확률이 더 높아진 token은 큰 weight를 받는다. 반대로 skill이 지지하지 않는 token은 auxiliary supervision이 약해진다. Gate는 항상 0과 1 사이이므로 sampled token에 직접 음의 weight를 주는 장치는 아니다. 후보 사이의 상대적 억제는 softmax normalization과 재가중 target에서 발생한다.

---

## 4. OPD와 GRPO의 공동 목적함수

Valid-token mask $m_{q,n,t,\ell}$을 포함한 OPD loss는 다음과 같다.

$$
\mathcal{L}_{\mathrm{opd}}(\theta)
=
\mathbb{E}_{q,n,t,\ell}
\left[
m_{q,n,t,\ell}g_{q,n,t,\ell}
\left(
\operatorname{sg}[\ell^{\mathrm{skill}}_{q,n,t,\ell}]
-
\ell^\theta_{q,n,t,\ell}
\right)
\right].
$$

Teacher term과 gate가 모두 detached이므로 gradient는

$$
\nabla_\theta\mathcal{L}_{\mathrm{opd}}
=
-\mathbb{E}
\left[
m_{q,n,t,\ell}g_{q,n,t,\ell}
\nabla_\theta\ell^\theta_{q,n,t,\ell}
\right]
$$

가 된다. 즉 OPD는 **skill이 지지한 on-policy token에 더 큰 weight를 주는 negative log-likelihood**와 gradient가 같다. Terminal reward가 trajectory 전체의 방향을 정한다면, OPD는 같은 trajectory 안에서 어떤 token을 더 강하게 보존할지 조절한다.

환경 결과는 별도의 group-relative RL loss로 학습한다. Task $q$의 rollout group에서

$$
A^{\mathrm{rl}}_{q,n}
=
\frac{R(\tau_q^{(n)})-\mu_q}{\sigma_q+\epsilon}
$$

를 계산하고 action token에 broadcast한다. 최종 목적함수는

$$
\mathcal{L}_{\mathrm{SEED}}(\theta)
=
\mathcal{L}_{\mathrm{rl}}(\theta)
+
\lambda_{\mathrm{opd}}\mathcal{L}_{\mathrm{opd}}(\theta)
$$

다. 실험의 기본값은 rollout group 8, 150 policy update, $\beta_{\mathrm{opd}}=5.0$, $\lambda_{\mathrm{opd}}=0.01$, KL coefficient 0.01이다(Table 5). 학습이 끝난 뒤에는 ordinary history만 사용한다.

$$
a_t\sim\pi_\theta(\cdot\mid h_t).
$$

배포에는 analyzer, skill bank, retrieval module, skill-augmented prompt가 필요 없다. 추가 비용은 training의 trajectory analysis와 paired scoring에서 발생한다.

---

## 5. 이론이 보장하는 것과 보장하지 않는 것

Appendix A의 세 proposition은 SEED의 세 형용사—on-policy, dense, self-evolving—를 수학적으로 해석한다.

| Proposition | 보이는 것 | 보이지 않는 것 |
| --- | --- | --- |
| Occupancy-matched target | 현재 policy가 방문한 token-context 분포 위에서 skill-reweighted target을 학습한다. 과거 trajectory를 쓰면 distribution divergence에 비례한 mismatch가 생길 수 있다. | Reweighted target이 원 policy보다 좋은 행동을 선호한다는 보장은 없다. |
| Signal under reward ties | Rollout group reward가 모두 같아 GRPO advantage가 0이어도, hindsight gate가 token마다 다르면 OPD gradient는 남는다. | Gate가 모든 후보에서 같으면 기대 OPD gradient가 사라지고, 비슷할수록 신호가 약해진다. |
| Analyzer-staleness bound | 현재 checkpoint의 analyzer를 쓰면 cross-iteration analyzer mismatch를 data generation 시점마다 초기화한다. | 최신 analyzer가 더 정확하다는 보장과 inner update 동안의 lag 제거는 아니다. |

첫 proposition의 adaptive target은 개념적으로

$$
r_k(v\mid c)
\propto
\pi_k(v\mid c)w_k(c,v)
$$

처럼 현재 policy를 hindsight support $w_k$로 재가중한다. 이 target의 local value가 더 높으려면

$$
\operatorname{Cov}_{v\sim\pi_k}
\left(Q_k(c,v),w_k(c,v)\right)>0
$$

이어야 한다. 쉽게 말해 skill이 실제로 더 좋은 action을 더 강하게 지지해야 한다. Analyzer가 최신이고 gate의 확신도가 높다고 해서 skill이 옳다는 보장은 없다.

Reward tie에서 OPD signal의 크기는 expected gate의 token 간 분산과 연결된다.

$$
\left\|\nabla_z\mathcal{L}_{\mathrm{opd},k,c}\right\|^2_{\pi_k^{-1}}
=
\operatorname{Var}_{v\sim\pi_k}[w_k(c,v)].
$$

Reward가 tied여도 $w_k(c,v)$가 token별로 다르면 OPD gradient가 남는다. 다만 이 식은 신호의 존재만 보일 뿐, 방향의 정확성이나 return의 단조 개선을 보장하지 않는다.

---

## 6. 실험 결과

### 6.1 설정

| 축 | 설정 |
| --- | --- |
| Text backbone | Qwen2.5-3B-Instruct, Qwen2.5-7B-Instruct, Qwen3-1.7B-Instruct |
| Vision backbone | Qwen2.5-VL-3B-Instruct |
| Text environment | ALFWorld, Search-based QA 7종, WebShop |
| Vision environment | Sokoban, EZPoints |
| Stage 1 | Benchmark별 180 task × 8 rollout = 1,440 trajectory, GLM-5.2 annotation, 3 epoch SFT |
| Stage 2 | 150 update, group size 8, batch 16(ALFWorld/WebShop)·128(Search) |
| Compute | NVIDIA A800 80GB 8장 |

### 6.2 GRPO 대비 aggregate 결과

![SEED main results](/api/blog/figures/seed-results.png)

*그림 2. 세 text backbone에서 ALFWorld, Search-based QA, WebShop을 비교한 전체 결과표. 공식 SEED 코드 저장소의 `figs/results.png`를 복사했으며, 논문 Table 1과 같은 결과를 담는다. 원 표는 수정하지 않았다.*

| Backbone | ALFWorld Avg | Search Avg | WebShop Score | WebShop Success |
| --- | ---: | ---: | ---: | ---: |
| Qwen2.5-3B | 75.0→91.8 | 36.4→45.7 | 79.8→88.5 | 63.3→78.9 |
| Qwen2.5-7B | 81.2→96.1 | 42.0→48.6 | 80.9→89.7 | 72.6→78.1 |
| Qwen3-1.7B | 46.1→92.0 | 40.8→42.2 | 67.3→87.1 | 38.3→77.3 |

표의 화살표는 GRPO→SEED다(Table 1, 저자 보고). 세 backbone의 모든 aggregate GRPO 비교에서 SEED가 높다. 특히 Qwen3-1.7B의 ALFWorld는 46.1에서 92.0으로 45.9점 상승했다. 다만 작은 backbone에서의 큰 격차가 곧 더 큰 모델에서도 같은 상대 개선이 난다는 뜻은 아니다.

모든 baseline을 포함하면 평가는 조금 달라진다. 저자들이 static distillation 계열로 묶은 평가 구현들과의 12개 aggregate 비교 중 SEED는 10개에서 best 또는 tied-best다. Qwen2.5-7B의 Search 평균 48.6은 RLSD·SDAR의 49.0보다 낮고, WebShop success 78.1도 SDAR 82.8보다 낮다. SEED가 강한 결과를 보였다는 평가와 모든 셀을 지배했다는 평가는 구분해야 한다.

### 6.3 Sample efficiency와 unseen split

ALFWorld에서 SEED는 Stage 2 학습 data 60%만으로 80.7을 기록해, 전체 data를 쓴 GRPO의 75.0을 넘었다(Table 6). WebShop에서도 모든 data fraction에서 GRPO보다 높았다. 다만 이는 Stage 2의 data efficiency에 관한 결과다. SEED에는 Stage 1 annotation·SFT, trajectory별 skill 생성, ordinary context와 skill-augmented context에서의 paired re-scoring이 추가되지만, 논문은 wall-clock·token count·energy·전체 forward-pass 비용을 비교하지 않았다. 따라서 end-to-end compute efficiency까지 입증했다고 보기는 어렵다.

ALFWorld unseen에서는 GRPO 70.9에서 SEED 86.2로 15.3점 올랐다(Table 7). 여섯 task family 가운데 다섯 개가 개선됐지만 Clean은 82.4에서 79.5로 2.9점 낮아졌다. 따라서 “unseen에 일반화했다”는 주장은 ALFWorld의 특정 unseen split과 한 3B checkpoint에 관한 결과로 읽는 편이 정확하다.

### 6.4 Ablation과 vision extension

| Variant | ALFWorld Avg | Full 대비 변화 |
| --- | ---: | ---: |
| Full SEED | 91.8 | — |
| w/o Hindsight Skill SFT | 86.0 | −5.8 |
| w/o Self-Evolving OPD | 87.0 | −4.8 |
| w/o On-Policy Skill | 84.4 | −7.4 |

가장 큰 하락은 current-policy trajectory에서 만든 skill을 offline library skill로 바꿨을 때 나타났다(Table 2). 이는 단순히 skill text가 있다는 사실보다, 현재 policy가 실제로 만드는 상태와 실패에 맞춰 skill을 갱신하는 것이 중요하다는 해석을 지지한다. 다만 ablation은 Qwen2.5-3B의 ALFWorld 한 설정에 집중되어 있다.

Vision extension에서는 Sokoban 67.1→82.0, EZPoints 86.9→100.0으로 평균이 77.0에서 91.0으로 올랐다(Table 8). Text-only를 넘어선 가능성을 보여 주지만, 두 benchmark만으로 일반적인 multimodal agentic RL까지 입증했다고 보기는 어렵다. Vision Stage 1의 annotation model과 정확한 data 규모도 본문에서 충분히 명시되지 않았다.

---

## 7. 기존 접근과의 차이

| 접근 | Hindsight의 위치 | Token-level signal | Policy 변화와 동기화 | Inference 추가 문맥 |
| --- | --- | --- | --- | --- |
| GRPO | Terminal reward | 없음: trajectory advantage broadcast | On-policy rollout | 없음 |
| Skill prompting | 외부 skill text | 학습 신호가 아니라 입력 context | 보통 고정 | 필요 |
| Reflection·memory | 경험 요약을 저장·검색 | 보통 없음 | memory update 방식에 의존 | 대체로 필요 |
| Retrieved/privileged skill distillation | Skill bank 또는 privileged teacher context | 있음 | 구현에 따라 fixed 또는 dynamic | 대체로 학습 전용 |
| SEED | 현재 policy의 completed trajectory | Skill-induced probability shift로 gated OPD | Outer update마다 actor/analyzer refresh | 없음 |

관련 축은 hindsight learning, verbal reflection, on-policy distillation, skill-conditioned self-distillation이다. SEED는 이 요소들을 “current policy가 만든 trajectory → current checkpoint가 분석한 skill → 같은 on-policy token의 paired re-scoring”이라는 task-local·bank-free 동기화 루프로 묶는다.

다만 Skill-SD 자체를 단순한 static distillation으로 분류하면 선행연구의 범위를 줄여 말하게 된다. Skill-SD 원 방법도 student on-policy rollout, dynamic teacher synchronization, trajectory-derived skill과 retrieval을 사용한다. SEED와의 더 정확한 차이는 **prior-task skill bank·retrieval·auxiliary summarizer** 대신 **현재 trajectory를 같은 policy checkpoint가 즉시 분석하고 바로 증류한다**는 데 있다. 목적함수도 다르다. Skill-SD는 dynamic teacher와 student 사이의 importance-weighted reverse-KL SDL을 사용하지만, SEED는 detached token log-probability gap을 sigmoid gate로 바꿔 sampled-token NLL을 가중한다. 따라서 Table 1은 논문이 재현한 baseline 구현 사이의 비교이지, 각 선행 시스템의 가능한 모든 동적 설정을 통제한 최종 비교는 아니다.

SkillOpt와도 구분된다. SkillOpt는 model weight를 고정하고 외부 skill document를 개선한다. SEED는 skill을 training-time privileged context로만 사용해 그 행동 효과를 policy weight에 internalize한다. 전자는 배포 가능한 문서를 얻고, 후자는 추가 문서 없이 작동하는 policy를 얻는다.

---

## 8. 적용 범위와 한계

### 8.1 논문이 인정한 한계

- 더 긴 workflow, 더 풍부한 state space, 매우 드문 terminal success에서는 검증되지 않았다.
- 같은 model이 actor와 analyzer를 겸하므로 blind spot도 공유한다. 잘못된 trajectory 해석이 reusable rule로 강화될 수 있다.
- Confidence와 self-judgment는 semantic correctness를 보장하지 않는다.
- Inference overhead는 없지만 training에서는 trajectory analysis와 paired contextual scoring 비용이 추가된다.
- Appendix의 이론은 local update structure와 freshness를 설명하며 return improvement를 보장하지 않는다.

### 8.2 실험에서 직접 드러나는 경계

결과표는 여러 domain과 backbone을 포함하지만 multi-seed variance나 confidence interval이 없다. 공개 설정도 기본 seed 하나를 사용한다. Point estimate 차이가 작은 셀, 예를 들어 Search 48.6과 49.0을 안정적인 순위 차이로 읽기 어렵다. Sample efficiency 역시 data fraction 기준이며, 추가 analyzer generation과 두 번의 scoring을 포함한 전체 compute 기준은 아니다.

GRPO를 비롯한 reproduced post-training baseline은 backbone, rollout budget, schedule을 맞췄다고 논문이 설명한다. 그러나 outcome-only GRPO와의 비교에는 GRPO에 없는 1,440개 trajectory, GLM-5.2 annotation, 3-epoch SFT가 SEED에 선행된다. 다른 skill-distillation baseline까지 포함해 skill 생성 비용과 총 data·compute가 동일하게 맞춰졌는지는 보고만으로 확인하기 어렵다. `w/o Hindsight Skill SFT`가 86.0으로 GRPO 75.0보다 높다는 결과는 Stage 2 loop 자체의 이점을 일부 지지하지만, main result 전체를 완전히 budget-matched comparison으로 만들지는 않는다.

Stage 1의 “self”도 제한해서 읽어야 한다. 초기 1,440개 trajectory의 skill annotation에는 외부 GLM-5.2가 필요하다. Stage 2부터 shared checkpoint가 스스로 analyzer 역할을 하지만, 시스템 전체가 외부 teacher 없이 시작하는 것은 아니다.

## 9. 결론

SEED를 구별하는 설계는 자연어 skill 자체보다 **paired contextual re-scoring**이다. 완료 trajectory에서 얻은 skill로 같은 action token의 확률 변화를 측정하고, 그 차이를 stop-gradient한 뒤 sigmoid gate로 변환해 ordinary policy의 학습 가중치로 사용한다.

평가된 세 text domain과 두 vision benchmark에서 SEED는 GRPO보다 높은 점수를 기록했다. Qwen2.5-3B/ALFWorld ablation에서는 online skill을 offline library skill로 바꾸자 평균이 7.4점 낮아졌다.

다만 SEED가 작동하려면 hindsight가 실제 action value와 정렬되고, gate가 token별 차이를 포착하며, actor와 analyzer가 공유하는 오류가 닫힌 loop 안에서 증폭되지 않아야 한다. SEED는 sparse reward를 대체하지 않는다. Episode outcome은 여전히 RL objective의 방향을 정한다. 이 방법의 기여는 완료된 경험을 다시 읽어, 결과만으로는 보이지 않던 중간 decision을 보조 학습한다는 데 있다.

## References

- Agarwal, R., Vieillard, N., Zhou, Y., Stanczyk, P., Ramos, S., Geist, M., & Bachem, O. (2024). On-policy distillation of language models: Learning from self-generated mistakes. In *The Twelfth International Conference on Learning Representations*. https://arxiv.org/abs/2306.13649

- Andrychowicz, M., Wolski, F., Ray, A., Schneider, J., Fong, R., Welinder, P., McGrew, B., Tobin, J., Abbeel, P., & Zaremba, W. (2017). Hindsight experience replay. *Advances in Neural Information Processing Systems, 30*. https://arxiv.org/abs/1707.01495

- Lu, Z., Yao, Z., Han, Z., Wang, Z.-H., Wu, J., Gu, Q., Cai, X., Lu, W., Xiao, J., Zhuang, Y., & Shen, Y. (2026). *Self-distilled agentic reinforcement learning* [Preprint]. arXiv. https://arxiv.org/abs/2605.15155

- Shao, Z., Wang, P., Zhu, Q., Xu, R., Song, J., Bi, X., Zhang, H., Zhang, M., Li, Y. K., Wu, Y., & Guo, D. (2024). *DeepSeekMath: Pushing the limits of mathematical reasoning in open language models* [Preprint]. arXiv. https://arxiv.org/abs/2402.03300

- Shinn, N., Cassano, F., Berman, E., Gopinath, A., Narasimhan, K., & Yao, S. (2023). Reflexion: Language agents with verbal reinforcement learning. *Advances in Neural Information Processing Systems, 36*. https://arxiv.org/abs/2303.11366

- Wang, H., Wang, G., Xiao, H., Zhou, Y., Pan, Y., Wang, J., Xu, K., Wen, Y., Ruan, X., Chen, X., & Qi, H. (2026). *Skill-SD: Skill-conditioned self-distillation for multi-turn LLM agents* [Preprint]. arXiv. https://arxiv.org/abs/2604.10674

- Wu, J., Yang, S., Lu, Z., Zhang, F., Shen, Y., Feng, L., Luo, H., Lian, Z., Zhang, S., Wen, Z., & Tao, J. (2026). *SEED: Self-evolving on-policy distillation for agentic reinforcement learning* [Preprint]. arXiv. https://arxiv.org/abs/2607.14777
