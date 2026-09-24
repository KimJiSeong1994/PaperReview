# Theory-informed and interpretable graph learning for urban commuting flows

# Theory-informed and interpretable graph learning for urban commuting flows

**Paper:** Minwei Zhao; Dailuo Zhang; Zhecheng Shi; Cai Wu (2026). "Theory-informed and interpretable graph learning for urban commuting flows". https://doi.org/10.1016/j.scs.2026.107575

**Abstract:** 도시의 통근 흐름은 유연한 예측 모델만으로 설명하기 어렵다. 출발지는 통근자를 내보내는 생산 역할을, 도착지는 일자리를 끌어들이는 흡인 역할을 하며, 두 지역 사이의 흐름은 거리가 멀어질수록 감소하는 경향을 보인다. PIG-GNN은 이 비대칭을 두 개의 graph encoder로 분리하고, 거리 감쇠·Zipf scaling·흐름 분포를 soft constraint로 학습 목적에 넣는다. England MSOA 수준의 Home-to-Work 자료에서 저자 보고 기준 RMSE 0.297, CPC 0.791, $R^2$ 0.394를 기록했다. 중요한 점은 이 논문이 중력 모형을 신경망으로 대체했다는 데 있지 않다. **지리 이론을 입력 feature에만 머물게 하지 않고 architecture와 loss의 제약으로도 반영하면서, 고정된 함수형을 강요하지 않는 절충안**을 제시했다는 데 있다. 다만 여기서 “physics-informed”는 보존 법칙이나 미분방정식을 만족시킨다는 뜻이 아니라, 여러 이동 자료에서 관찰된 통계적 scaling 범위를 정규화 항으로 사용한다는 뜻이다.

---

## 핵심 요약

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | GNN의 비선형 표현력을 유지하면서 origin–destination의 역할 비대칭과 이동의 거시적 scaling law를 어떻게 보존할 것인가? |
| 구조적 해법 | 같은 공간 인접 graph를 사용하되 production tower와 attraction tower의 parameter를 분리하고, directed OD graph에서 거리 인지 message passing을 수행한다. |
| 학습 해법 | Data loss에 거리 감쇠 기울기, Zipf exponent, 예측·이론 분포의 KL divergence를 soft penalty로 더한다. |
| 대표 결과 | 저자 보고 기준 RMSE $0.297\pm0.002$, MAE $0.187\pm0.009$, $R^2$ $0.394\pm0.014$, CPC $0.791\pm0.004$다. |
| 해석의 경계 | 단일 주 사례의 정적 통근 OD 예측이며, feature perturbation과 regime 분석은 모델 행동의 해석이지 정책 개입의 인과효과가 아니다. |

## 목차

1. 왜 통근 OD는 일반적인 edge prediction과 다른가
2. 중력 모형에서 PIG-GNN으로
3. 두 종류의 graph와 production–attraction dual tower
4. 거리 인지 OD interaction GNN
5. Scaling law를 soft constraint로 넣는 방법
6. Empirical prior는 어떻게 정해졌는가
7. 실험 설정과 결과
8. Bimodal regime이 의미하는 것
9. “Interpretable”과 “physics-informed”의 범위
10. 한계와 후속 과제
11. 결론

## 1. 왜 통근 OD는 일반적인 edge prediction과 다른가

통근 OD matrix의 원소 $Y_{ij}$는 지역 $i$에 거주하면서 지역 $j$로 출근하는 사람의 흐름을 나타낸다. 이를 graph의 directed edge weight로 보면 문제는 단순해 보인다. 각 지역의 속성을 node feature로 넣고, 두 node embedding을 결합해 edge weight를 회귀하면 된다.

하지만 공간 상호작용 이론의 관점에서 $i$와 $j$는 교환 가능한 두 node가 아니다.

- Origin $i$의 핵심은 거주 인구와 노동 공급처럼 **얼마나 많은 이동을 생산하는가**다.
- Destination $j$의 핵심은 고용·시설·접근성처럼 **얼마나 많은 이동을 끌어들이는가**다.
- 같은 지역도 origin으로 사용될 때와 destination으로 사용될 때 다른 표현이 필요하다.
- 두 지역의 mass가 같아도 거리와 주변 대체 목적지에 따라 $Y_{ij}$는 달라진다.

일반적인 shared-encoder GNN이 모든 지역에 하나의 embedding $z_i$만 부여하면 이러한 역할 차이는 최종 edge MLP가 뒤늦게 복원해야 한다. 모델이 충분히 크면 fitting은 가능하지만, embedding의 어떤 축이 생산이고 어떤 축이 흡인인지 분명하지 않다. PIG-GNN은 이 문제를 output head의 문제가 아니라 **representation 단계의 구조적 오류**로 본다.

![PIG-GNN 전체 연구 파이프라인](/api/blog/figures/pig-gnn-fig1-pipeline.jpg)

*원논문 Figure 1. 입력 자료에서 spatial adjacency graph와 directed OD graph를 만들고, theory-informed structure와 physics-informed loss를 거쳐 예측·평가·regime 분석으로 이어지는 전체 절차다. 출처: Zhao et al. (2026), Figure 1.*

## 2. 중력 모형에서 PIG-GNN으로

고전적 중력 모형은 OD 흐름을 다음과 같은 형태로 설명한다.

$$
T_{ij}
=
K\,O_i^{\mu}D_j^{\nu}d_{ij}^{-\beta}
$$

- $O_i$: origin의 production mass
- $D_j$: destination의 attraction mass
- $d_{ij}$: 두 지역 사이의 거리 또는 일반화된 이동 비용
- $\beta$: 거리 감쇠 강도
- $K,\mu,\nu$: scale과 mass elasticity를 조절하는 parameter

Log를 취하면 거리와 흐름의 관계는 대략 선형으로 드러난다.

$$
\log T_{ij}
=
\log K
+\mu\log O_i
+\nu\log D_j
-\beta\log d_{ij}
$$

이 식의 장점은 각 항의 역할이 분명하다는 점이다. 단점은 도시권 내부의 포화, 다핵 구조, 지역별 이질성, 주변 목적지와의 경쟁을 하나의 전역 함수로 표현하기 어렵다는 점이다.

PIG-GNN은 이 식을 그대로 neural network로 구현하지 않는다. 대신 중력 모형이 제공하는 두 가지 inductive bias를 분리해서 사용한다.

1. **구조적 prior:** production과 attraction을 서로 다른 encoder로 학습한다.
2. **통계적 prior:** 거리 감쇠와 flow-rank scaling이 경험적으로 타당한 범위를 벗어날 때만 penalty를 준다.

따라서 PIG-GNN은 “gravity equation + residual network”가 아니다. 고정된 $T_{ij}$ 함수형을 포기하는 대신, 중력 이론이 말하는 역할과 거시 패턴을 architecture와 objective에 남긴다.

## 3. 두 종류의 graph와 production–attraction dual tower

논문은 서로 다른 관계를 하나의 adjacency matrix에 섞지 않는다.

![PIG-GNN의 spatial adjacency graph와 directed OD graph](/api/blog/figures/pig-gnn-fig5-dual-graph.jpg)

*원논문 Figure 5. 왼쪽은 지리적으로 인접한 지역을 연결한 spatial adjacency graph, 오른쪽은 실제 이동 방향을 가진 OD flow graph다. 두 graph는 같은 지역 집합을 공유하지만 edge의 의미가 다르다. 출처: Zhao et al. (2026), Figure 5.*

### 3.1 Spatial adjacency graph

$$
G_S=(V,E_S,W)
$$

$E_S$는 지리적 이웃 관계를, $W$는 공간 인접 weight를 나타낸다. 이 graph는 Tobler의 제1법칙처럼 가까운 지역의 사회경제적 조건이 서로 관련된다는 가정을 표현한다. PIG-GNN은 같은 $G_S$ 위에 두 개의 tower를 둔다.

$$
z_i^{P}=f_P(X^{P},W)_i,
\qquad
z_i^{A}=f_A(X^{A},W)_i
$$

$f_P$와 $f_A$는 같은 공간 인접 그래프에서 작동하는 서로 독립된 $L$-layer GATv2 encoder이며, parameter를 공유하지 않는다. GCN은 누적 구조 절제의 중간 비교 단계다(§3.2.1, Eq. 4; Table A.8). $z_i^P$는 지역 $i$의 production embedding, $z_i^A$는 attraction embedding이다. 같은 지역 $i$도 두 역할에 따라 서로 다른 vector를 갖는다.

### 3.2 Directed OD graph

$$
G_{OD}=(V,E_{OD},D)
$$

$E_{OD}$는 $i\rightarrow j$ 방향의 상호작용을 표현하고, $D_{ij}$는 거리 impedance를 제공한다. Spatial graph가 “주변 지역과 어떤 맥락을 공유하는가”를 학습한다면, OD graph는 “어떤 origin–destination 관계가 서로 경쟁하거나 대체하는가”를 학습한다.

이 분리가 중요하다. 지리적으로 인접하다는 것과 실제 통근 흐름이 존재한다는 것은 같은 관계가 아니다. 인접 지역끼리 socio-economic context를 공유할 수 있지만, 장거리 중심지 통근은 adjacency edge를 넘어 발생한다. 반대로 OD 흐름만으로 지역 문맥을 만들면 관측된 이동이 적은 지역의 표현이 빈약해질 수 있다.

## 4. 거리 인지 OD interaction GNN

![PIG-GNN의 상세 architecture](/api/blog/figures/pig-gnn-fig6-architecture.jpg)

*원논문 Figure 6. Production·attraction dual tower, distance-aware GATv2 기반 OD interaction GNN, directed edge MLP, physics-informed loss가 연결된 상세 구조다. 출처: Zhao et al. (2026), Figure 6.*

Figure 6의 흐름을 식으로 재구성하면 예측기는 다음과 같이 이해할 수 있다.

$$
\hat Y_{i\rightarrow j}
=
g_{\theta}\!\left(
z_i^P,
z_j^A,
h_{ij}^{OD},
\psi(D_{ij})
\right)
$$

여기서 $\psi(D_{ij})$는 distance encoder, $h_{ij}^{OD}$는 directed OD graph에서 GATv2 message passing으로 얻은 impedance-aware interaction representation, $g_\theta$는 BatchNorm·ReLU·Dropout을 포함한 edge MLP다. 이 식은 Figure 6을 설명하기 위한 표기 재구성이며 원논문의 번호가 붙은 식을 그대로 옮긴 것은 아니다.

구조를 단계별로 읽으면 다음과 같다.

1. P-GNN은 origin 주변의 공간 문맥을 모아 $z_i^P$를 만든다.
2. A-GNN은 destination 주변의 공간 문맥을 모아 $z_j^A$를 만든다.
3. Directed OD graph의 GATv2는 $D_{ij}$를 edge 정보로 사용해 interaction을 갱신한다.
4. Source의 production representation과 target의 attraction representation을 방향에 맞춰 concatenate한다.
5. Edge MLP가 $\hat Y_{i\rightarrow j}$를 예측한다.
6. 최종 prediction은 data error뿐 아니라 scaling constraint의 gradient도 받는다.

단순 dual tower만으로는 주변 OD edge 간 dependence를 표현하기 어렵고, OD GNN만으로는 production과 attraction이 다시 섞일 수 있다. PIG-GNN은 두 구조를 직렬로 결합한다.

## 5. Scaling law를 soft constraint로 넣는 방법

PIG-GNN의 핵심은 architecture보다 loss에서 더 분명하게 드러난다.

![PIG-GNN의 physics-informed loss](/api/blog/figures/pig-gnn-fig8-physics-loss.jpg)

*원논문 Figure 8. Data fidelity, distance-decay slope, Zipf prior, KL divergence를 결합하고 empirical interval 밖의 값에 quadratic penalty를 적용한다. 각 $\lambda_k$는 loss ratio에 따라 조정된다. 출처: Zhao et al. (2026), Figure 8.*

전체 목적함수는 다음과 같다.

$$
\mathcal{L}
=
\mathcal{L}_{data}
+\lambda_1\mathcal{L}_{slope}
+\lambda_2\mathcal{L}_{KL}
+\lambda_3\mathcal{L}_{zipf}
$$

### 5.1 Data fidelity

$$
\mathcal{L}_{data}
=
\operatorname{MSE}(\hat Y_{ij},Y_{ij})
$$

이 항은 개별 OD edge의 예측 오차를 줄인다. Physics prior가 있더라도 실제 관측값을 맞추는 주 목적은 유지된다.

### 5.2 Distance-decay slope prior

거리와 예측 flow의 log–log 관계에서 추정한 감쇠 exponent $\beta$가 경험적 구간 안에 머물도록 한다.

$$
\beta\in[0.2,3.0]
$$

Hard clipping 대신 구간 밖의 위반만 제곱 penalty로 처리한다. 일반화하면 다음과 같다.

$$
\phi(x;a,b)
=
\max(0,a-x)^2
+\max(0,x-b)^2
$$

따라서 $\mathcal{L}_{slope}=\phi(\beta;0.2,3.0)$로 이해할 수 있다. 구간 안에서는 특정 값을 강요하지 않으므로 England data가 유효한 $\beta$를 선택할 여지가 남는다.

### 5.3 Zipf prior

Flow를 큰 순서로 정렬했을 때 순위 $r$의 흐름 $y_r$가 다음 rank-frequency 관계를 따른다는 prior다.

$$
y_r\propto r^{-\alpha},
\qquad
\alpha\in[0.5,3.0]
$$

$\mathcal{L}_{zipf}$는 학습된 $\alpha$가 이 구간을 벗어날 때 penalty를 준다. 이는 개별 edge가 아니라 전체 flow distribution의 꼬리 구조를 조절한다.

### 5.4 Distributional prior

분포 제약은 예측 로그 흐름의 분포 $\hat p$를, 학습된 거리 감쇠 지수 $\beta$와 Zipf 지수 $\alpha$가 각각 정하는 두 이론 분포와 비교한다(Appendix A.1.2).

$$
D_{KL}=\lambda_{KL,\beta}D_{KL}(\hat p\|p_{\mathrm{theory}}(\beta))
+\lambda_{KL,\alpha}D_{KL}(\hat p\|p_{\mathrm{theory}}(\alpha)).
$$

다만 본문과 부록은 벌점의 방향을 다르게 설명한다. 본문 §3.2.3–3.2.4는 이론 분포에서 크게 벗어나는 경우를 벌한다고 설명하지만, 부록 Eq. A.4는 $D_{KL}<D_{KL,\min}$일 때

$$
\mathcal L_{KL}=(D_{KL,\min}-D_{KL})^2
$$

를 부여하는 것으로 적혀 있다. 인쇄된 식대로라면 KL이 너무 작을 때 벌점이 생긴다. 따라서 이 항을 일반적인 KL 최소화로 단정할 수 없으며, 본문 설명과 부록의 조건식 사이에 방향 불일치가 남는다. [원문 §3.2.3–3.2.4, Appendix A.1.2](https://urbanmorphology.studio/pdfs/zhao-et-al-2026-pig-gnn-commuting-flows.pdf)

## 6. Empirical prior는 어떻게 정해졌는가

Physics-informed model의 가장 어려운 질문은 “어떤 law를 얼마나 강하게 믿을 것인가”다. 논문은 $\beta$와 $\alpha$를 한 도시에서 임의로 고정하지 않는다. 서로 다른 이동 목적과 공간 규모를 가진 8개 OD dataset을 분석해 넓은 interval을 정한다.

![여덟 OD dataset에서 추정한 scaling prior](/api/blog/figures/pig-gnn-fig7-prior-calibration.jpg)

*원논문 Figure 7. Intra-city, urban-regional, macro scale 자료에서 distance-decay exponent, KL divergence, Zipf exponent, monotonicity strength를 비교한다. 점선 구간 $\beta\in[0.2,3.0]$, $\alpha\in[0.5,3.0]$이 PIG-GNN의 soft prior가 된다. 출처: Zhao et al. (2026), Figure 7.*

Figure 7은 두 가지를 동시에 보여 준다.

1. Distance decay와 heavy-tail flow distribution은 여러 scale에서 반복된다.
2. Exponent는 하나의 보편 상수가 아니라 이동 scale에 따라 상당히 달라진다.

따라서 interval prior는 이론을 약화한 것이 아니라 자료의 이질성을 인정한 선택이다. 다만 구간이 넓을수록 regularization은 약해진다. $\beta=0.21$과 $\beta=2.99$가 모두 무벌점이라면, 이 항이 제공하는 것은 정밀한 mechanism identification보다 **명백히 비현실적인 해를 배제하는 guardrail**에 가깝다.

또한 경험적으로 반복되는 scaling이 곧 원인 법칙을 뜻하지는 않는다. 거리 감쇠는 이동 비용, 토지 이용, 소득, 교통망, 행정구역 설정이 함께 만든 결과일 수 있다. PIG-GNN은 이 regularity를 잘 보존하지만 그 발생 원인을 분리해 식별하지는 않는다.

## 7. 실험 설정과 결과

주 실험은 England의 MSOA 수준 Home-to-Work commuting flow를 대상으로 한다. 노드는 6,856개 MSOA이며, 기본 production 입력은 working-age population, attraction 입력은 POI density 하나씩이다. Count feature와 flow는 $\log(1+x)$ 변환 후 표준화한다. 관측된 positive OD edge를 대상으로 흐름의 세기를 회귀하므로, 임의의 미관측 지역쌍에서 링크 존재까지 예측하는 과제와는 다르다. 비교군에는 unconstrained·doubly constrained·hurdle·PPML gravity, radiation model, Random Forest, XGBoost, MLP, mixture density network, 여러 graph·deep mobility model이 포함된다.

| Model | RMSE ↓ | MAE ↓ | $R^2$ ↑ | CPC ↑ |
| --- | ---: | ---: | ---: | ---: |
| PIG-GNN | **$0.297\pm0.002$** | **$0.187\pm0.009$** | **$0.394\pm0.014$** | **$0.791\pm0.004$** |
| Unconstrained gravity | 0.343 | 0.233 | $0.284\pm0.002$ | 0.754 |
| GravityGNN | 0.319 | 0.209 | $0.351\pm0.056$ | 0.778 |

*원논문 Table 3의 저자 보고 값이다.*

![PIG-GNN 대비 전체 baseline의 상대 성능](/api/blog/figures/pig-gnn-fig9-performance.jpg)

*원논문 Figure 9. PIG-GNN을 1.0으로 정규화한 상대 성능이다. RMSE·MAE는 작을수록 좋고 $R^2$·CPC는 클수록 좋으므로, 방향을 통일한 상대 비교로 읽어야 한다. 출처: Zhao et al. (2026), Figure 9.*

학습은 distance decile과 출발·도착 strength quantile을 유지한 5-fold stratified CV를 사용한다. 각 outer training fold 안에서는 3-fold CV와 20회 random search, early stopping으로 설정을 선택한다. 최종 graph model 학습은 AdamW, cosine schedule, 800 epochs로 설명된다(§3.3, Appendices A.2·A.6–A.9).

### 7.1 개선은 accuracy 하나에 한정되지 않는다

RMSE와 MAE는 edge별 오차를, $R^2$는 분산 설명력을, CPC(Common Part of Commuters)는 관측·예측 flow volume의 겹침을 본다.

$$
\operatorname{CPC}
=
\frac{2\sum_{ij}\min(Y_{ij},\hat Y_{ij})}
{\sum_{ij}Y_{ij}+\sum_{ij}\hat Y_{ij}}
$$

CPC가 1에 가까울수록 전체 통근량의 분배가 관측치와 비슷하다. PIG-GNN이 error metric과 CPC에서 함께 강하다는 것은 edge별 오차와 별도로 관측·예측 흐름의 aggregate volume overlap도 높았음을 뜻한다. 다만 CPC는 flow volume으로 가중되므로 큰 흐름의 영향을 강하게 받는다.

### 7.2 $R^2$는 개선됐지만 절대적으로 높지는 않다

$R^2=0.394$는 unconstrained gravity의 0.284와 GravityGNN의 0.351보다 높다. 그러나 관측 변동의 상당 부분은 여전히 설명되지 않는다. 통근 흐름의 heavy tail, zero inflation, 행정구역 aggregation, 미관측 교통 비용을 고려하면 어려운 문제지만, 이 결과를 “도시 통근을 충분히 설명했다”고 읽을 수는 없다.

### 7.3 관측 주변합을 사용하는 기준선과의 구분

주 Table 3에서 PIG-GNN은 관측된 row/column marginal을 입력으로 요구하지 않는 deployable 기준선 중 전반적으로 가장 높은 성능을 보인다. 그러나 oracle marginal을 사용하는 doubly constrained gravity는 $R^2=0.435$, CPC 0.792로 PIG-GNN의 0.394, 0.791보다 높다. 따라서 모든 중력 모형보다 우수하다는 결론보다, 예측 시 사용할 정보 조건을 맞춘 비교로 해석해야 한다.

### 7.4 다목적 이동과 다른 도시에서의 재학습

출판본 부록은 England all-purpose 이동과 Xi’an·Guangzhou에서도 프레임워크를 다시 학습해 평가한다.

| 자료 | RMSE | $R^2$ | CPC | 결과의 범위 |
| --- | ---: | ---: | ---: | --- |
| ALLOD England | 0.6006 | 0.7431 | 0.6076 | RMSE·MAE·$R^2$는 최선이지만 CPC는 Random Forest 0.6748, XGBoost 0.6717보다 낮음 |
| Xi’an 500m grid | 0.4744 | 0.4019 | 0.4597 | 비교한 다섯 기준선보다 높은 성능 |
| Guangzhou 500m grid | 0.9089 | 0.4004 | 0.6511 | 비교한 다섯 기준선보다 높은 성능 |

ALLOD는 6,856개 MSOA와 2,383,725개의 edge를 사용한다. 이 실험들은 각 자료에서 모델을 다시 학습하는 framework-level 검증이다. England에서 학습한 가중치를 그대로 다른 도시에 적용하는 zero-shot transfer 결과는 아니다(Appendices A.6·A.12·A.13, Tables A.10–A.11·A.17–A.18).

### 7.5 구조 절제와 입력 특징의 영향

Table 4는 독립적인 제거 실험이 아니라 구성요소를 차례로 더하는 build-up이다. RMSE와 $R^2$는 개선되지만 MAE·CPC는 단조롭게 좋아지지 않는다. GATv2의 MAE 0.169·CPC 0.790은 dual tower 추가 시 0.199·0.783, OD message passing 추가 시 0.202·0.784가 되고, physics loss까지 추가한 뒤 0.187·0.791이 된다. 따라서 각 모듈이 모든 지표를 독립적으로 개선했다고 읽을 수는 없다.

입력 특징도 영향을 준다. Table A.12의 통제 실험에서 기본 1+1 feature의 RMSE 0.2941·CPC 0.7966은 rich_simple 5+5 feature에서 0.2812·0.8080으로 개선된다. 이는 동일 구조 안에서도 입력 정보의 품질이 성능을 바꾼다는 결과다. 이 통제 실험의 수치는 주 Table 3과 다른 실행 조건이므로 두 표의 절대값을 섞어 순위를 만들면 안 된다.

### 7.6 관측된 흐름 회귀와 zero-flow 예측

주 실험은 non-zero OD edge의 존재를 알고 그 가중치를 예측하는 transductive 설정이다. Appendix A.8은 zero-flow pair 10%를 추가한 보완 실험을 제공하며, PIG-GNN RMSE는 전체 0.3169, non-zero 0.3131, zero-only 0.3519다(Table A.13). 완전한 OD 행렬에서 링크 형성과 흐름의 세기를 함께 예측하는 문제까지 검증한 것은 아니다.

## 8. Bimodal regime이 의미하는 것

논문은 예측 성능 외에 test prediction의 분포를 분석한다. Predicted log flow에는 평균 약 6.05의 작은 고유량 cluster와 평균 약 1.32의 큰 저유량 cluster가 나타난다.

![PIG-GNN이 보존한 intra-city와 inter-city flow regime](/api/blog/figures/pig-gnn-fig12-regimes.jpg)

*원논문 Figure 12. Test set의 predicted log flow를 두 cluster로 분리한다. Figure 표기 기준 intra-city cluster는 11,697개, inter-city cluster는 703,418개이며, threshold 5.0을 사용한다. 고유량 cluster는 거리에 둔감한 포화 구간, 저유량 cluster는 거리 증가에 따라 감소하는 구간으로 나타난다. 출처: Zhao et al. (2026), Figure 12.*

저자들은 이를 다음과 같이 해석한다.

- **Intra-city regime:** 비교적 짧은 거리와 높은 빈도의 통근이 포화된 cluster를 이룬다.
- **Inter-city regime:** 거리가 멀어질수록 flow가 감소하는 gravity-dominated pattern이 나타난다.

이 결과의 의미는 하나의 $\beta$가 모든 OD pair를 동일하게 설명하지 못한다는 데 있다. 도시 내부의 고빈도 이동과 도시 간 장거리 이동은 서로 다른 생성 regime을 가질 수 있다. Soft prior는 전역 scaling을 보존하면서도 GNN이 이 국소적 편차를 표현하게 한다.

그러나 Figure 12의 cluster는 예측값 분포에서 사후적으로 확인한 구조다. 다음 가능성을 구분해야 한다.

1. 실제 intra/inter-city mechanism이 두 개 존재한다.
2. Log transform과 zero-heavy distribution이 두 mode를 강조했다.
3. Region boundary와 intra-zonal aggregation이 고유량 cluster를 만들었다.
4. Prediction head의 saturation이 상단 mode를 좁게 만들었다.

따라서 bimodality는 흥미로운 진단 결과지만, 독립적인 mechanism test 없이 두 개의 인과적 이동 법칙이 입증됐다고 보기는 어렵다.

Figure 12의 두 군집 표본 수 11,697과 703,418은 합계 715,115다. 이는 본문의 OD edge 305,107개 및 Tables 2·A.10의 H2W 298,681개보다 크다. Fold나 반복 예측을 합산했는지가 명시되지 않아, 군집 크기를 고유한 테스트 edge 수로 해석할 수는 없다.

## 9. “Interpretable”과 “physics-informed”의 범위

### 9.1 해석 가능성은 세 층으로 구성된다

| 층 | 무엇이 보이는가 | 무엇까지는 말할 수 없는가 |
| --- | --- | --- |
| Role-aware representation | Production과 attraction을 별도 embedding으로 표현한다. | 각 latent dimension이 특정 사회경제 변수와 일대일 대응한다는 보장은 없다. |
| Scaling consistency | $\beta$, $\alpha$, flow distribution이 경험적 범위와 얼마나 맞는지 확인할 수 있다. | 그 scaling을 만든 원인 mechanism을 식별하지 않는다. |
| Perturbation·regime analysis | Feature나 distance 변화에 대한 model response, intra/inter-city pattern을 볼 수 있다. | 관측자료 기반 반응을 정책 개입의 causal effect로 해석할 수 없다. |

이 논문의 interpretability는 post-hoc explanation 하나에 의존하지 않는다. 역할을 architecture로 분리하고, 학습 중에 거시 지표를 노출하며, 예측 후 regime을 분석하는 조합이다. 이는 일반 black-box edge predictor보다 설명 표면을 넓힌다.

### 9.2 여기서 physics는 경험적 지리 regularity다

PIG-GNN은 mass conservation PDE, 교통 유체 방정식, 에너지 보존식을 직접 만족시키지 않는다. 논문이 physics-informed라고 부르는 대상은 다음과 같다.

- Flow가 거리에 따라 감소한다.
- Flow 크기 분포가 Zipf-like scaling을 보인다.
- 예측 분포가 이러한 prior와 크게 어긋나지 않는다.

이는 지리학·복잡계의 경험 법칙을 learning constraint로 사용한 것이다. 따라서 더 정확한 표현은 **theory-regularized spatial graph learning**이다. 이 구분은 모델의 신뢰도를 평가할 때 중요하다. Constraint를 만족해도 교통망의 물리적 수용량이나 정책 시나리오의 실행 가능성이 자동으로 보장되지는 않는다.

## 10. 한계와 후속 과제

### 10.1 논문 근거에서 확인되는 경계

- 주 실험은 England H2W이며, ALLOD·Xi’an·Guangzhou의 재학습 실험도 제공된다. 가중치를 그대로 옮기는 전이와 시간적 분포 변화는 검증하지 않는다.
- $\beta$와 $\alpha$ 범위는 여러 OD 자료에서 보정되며, 각 도시에서 다시 학습한 결과와 zero-shot weight transfer는 구분해야 한다.
- Static aggregate OD prediction이므로 시간대별 변동, network disruption, 장기 land-use change를 직접 모델링하지 않는다.
- Figure 12의 regime label은 model prediction을 해석한 결과이며 사전에 관측된 causal class가 아니다.

### 10.2 실험 설정에서 직접 도출되는 한계

거리 정의도 본문 안에서 일치하지 않는다. §3.1.1은 centroid 사이의 Haversine geodesic distance를 설명하지만, §5.5와 Table A.14는 Euclidean distance라고 적는다. 주 실험에서 어느 구현을 사용했는지가 명확하지 않다.

다음 항목은 논문이 명시적으로 입증한 결론이 아니라, 공개된 설정과 분석 범위에서 직접 도출되는 해석상의 경계다.

**첫째, zoning sensitivity가 남는다.** MSOA 경계가 바뀌면 adjacency, intra-zone flow, 평균 거리, production·attraction feature가 함께 달라진다. 이는 Modifiable Areal Unit Problem으로 이어진다. 다른 공간 해상도에서도 동일한 prior interval과 bimodal pattern이 유지되는지 확인할 필요가 있다.

**둘째, 구조와 loss의 기여를 더 분리해야 한다.** Dual tower, OD interaction GNN, slope prior, Zipf prior, KL prior, adaptive weighting이 모두 들어간다. 각 요소를 제거한 ablation이 있더라도, 서로의 interaction과 seed별 불확실성을 충분히 보여 주려면 더 체계적인 factorial evaluation이 필요하다.

**셋째, counterfactual이라는 용어를 제한해서 써야 한다.** Input feature를 바꾸고 prediction 변화를 보는 것은 model counterfactual 또는 sensitivity analysis다. 실제 도시에서 고용이나 인구를 바꿨을 때 통근이 같은 크기로 변한다는 정책 효과 추정은 아니다. Confounder, equilibrium response, transport capacity가 모델에 명시돼 있지 않기 때문이다.

**넷째, broad prior의 이점과 약점이 함께 있다.** 넓은 interval은 domain variation을 허용하고 neural flexibility를 보존한다. 반대로 대부분의 solution이 구간 안에 들어오면 regularization이 거의 작동하지 않을 수 있다. Constraint 활성 빈도, 학습 중 $\lambda_k$ 변화, out-of-domain에서의 위반률을 함께 보고해야 prior의 실제 기여를 평가할 수 있다.

**다섯째, uncertainty가 필요하다.** 도시 계획에서는 point prediction뿐 아니라 어떤 OD pair에서 model이 불확실한지가 중요하다. PIG-GNN의 theory consistency와 predictive uncertainty를 결합하면, scaling law는 맞지만 지역별 오차가 큰 경우를 구분할 수 있다.

## 11. 결론

PIG-GNN은 통근 OD 예측에서 지리 이론을 사용하는 위치를 바꾼다. 중력 모형을 baseline으로만 두거나, 거리와 인구를 단순 feature로 추가하는 대신, production–attraction 비대칭은 dual tower로, OD 경쟁은 directed interaction graph로, distance decay와 Zipf scaling은 soft loss로 구현한다.

이 설계가 제공하는 핵심 이점은 제약과 유연성의 분리다. Model은 고정된 중력 함수에 갇히지 않지만, 학습된 거리·Zipf 지수가 경험적 구간을 벗어나면 penalty를 받는다. KL 분포 항에는 본문 설명과 부록 조건식의 방향 불일치가 남는다. 저자 보고 결과에서 H2W의 deployable 기준선 중 전반적으로 가장 좋은 오차와 CPC를 보였다. ALLOD에서는 오차와 $R^2$가 가장 좋았지만 CPC는 Random Forest·XGBoost보다 낮았다.

다만 “이론에 부합한다”와 “현실의 원인을 설명한다”는 같은 말이 아니다. PIG-GNN의 constraint는 경험적 scaling을 보존하고 representation의 역할을 분리하지만, 정책 개입의 인과효과나 다른 도시의 transfer를 자동으로 보장하지 않는다. Bimodal regime도 유용한 가설을 제공하지만 독립 검증이 필요하다.

따라서 이 논문의 가장 설득력 있는 결론은 다음과 같다.

1. OD graph learning에서는 origin과 destination을 대칭 node로 처리하지 않는 편이 이론적으로 자연스럽다.
2. Spatial adjacency와 directed mobility relation은 별도의 graph로 표현할 가치가 있다.
3. 경험 법칙은 hard-coded prediction formula보다 soft interval constraint로 사용할 수 있다.
4. Edge-level accuracy와 distribution-level plausibility를 같은 objective에서 함께 관리할 수 있다.
5. 해석 가능성은 latent attribution 하나보다 architecture, training constraint, regime analysis를 함께 설계할 때 더 강해진다.

PIG-GNN은 중력 모형과 GNN 중 하나를 선택하지 않는다. 어느 부분을 이론에 맡기고 어느 부분을 data에 맡길지를 architecture와 loss 수준에서 분해한다. 이 분해가 이 논문의 주된 방법적 기여다.

## References

Barbosa, H., Barthelemy, M., Ghoshal, G., James, C. R., Lenormand, M., Louail, T., Menezes, R., Ramasco, J. J., Simini, F., & Tomasini, M. (2018). Human mobility: Models and applications. *Physics Reports, 734*, 1–74. https://doi.org/10.1016/j.physrep.2018.01.001

Brody, S., Alon, U., & Yahav, E. (2022). How attentive are graph attention networks? In *International Conference on Learning Representations*. https://openreview.net/forum?id=F72ximsx7C1

González, M. C., Hidalgo, C. A., & Barabási, A.-L. (2008). Understanding individual human mobility patterns. *Nature, 453*(7196), 779–782. https://doi.org/10.1038/nature06958

Simini, F., González, M. C., Maritan, A., & Barabási, A.-L. (2012). A universal model for mobility and migration patterns. *Nature, 484*(7392), 96–100. https://doi.org/10.1038/nature10856

Tobler, W. R. (1970). A computer movie simulating urban growth in the Detroit region. *Economic Geography, 46*(sup1), 234–240. https://doi.org/10.2307/143141

Wilson, A. G. (1971). A family of spatial interaction models, and associated developments. *Environment and Planning A, 3*(1), 1–32. https://doi.org/10.1068/a030001

Zhao, M., Zhang, D., Shi, Z., & Wu, C. (2026). Theory-informed and interpretable graph learning for urban commuting flows. *Sustainable Cities and Society, 148*, 107575. https://doi.org/10.1016/j.scs.2026.107575

Zipf, G. K. (1946). The $P_1P_2/D$ hypothesis: On the intercity movement of persons. *American Sociological Review, 11*(6), 677–686. https://doi.org/10.2307/2087063
