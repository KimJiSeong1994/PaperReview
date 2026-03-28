# 논문 네트워크 그래프: 유사도 기반 학술 문헌 관계 시각화 시스템

## 1. Abstract

본 논문은 6개 학술 데이터베이스에서 수집한 논문들 사이의 관계를 자동으로 발견하고 인터랙티브 네트워크로 시각화하는 시스템을 제안한다. 기존 인용 그래프의 한계(최신 논문의 인용 부재, 데이터베이스 간 인용 데이터 불완전성)를 극복하기 위해, 제목 토큰 유사도(70%)와 키워드/카테고리 Jaccard 유사도(30%)를 결합한 하이브리드 유사도 기반 엣지 생성 방식을 도입하였다. Force-directed 레이아웃에 centroid shift와 max-absolute normalization을 적용하여 고립 노드의 뷰포트 이탈 문제를 해결하였으며, Plotly.js 기반 프론트엔드에서 trace grouping 최적화를 통해 수백 엣지를 200ms 이하로 렌더링한다.

---

## 2. Introduction

### 2.1 문제 정의

연구를 시작할 때 가장 먼저 맞닥뜨리는 문제는 "지금 내가 읽고 있는 이 논문이 전체 지형에서 어디쯤 있는가?"라는 질문이다.

우리는 arXiv, Google Scholar, OpenAlex, DBLP, Semantic Scholar, Connected Papers 등 6개 소스에서 논문을 수집한다. 각각의 소스는 서로 다른 메타데이터 형식을 사용하고, 같은 논문이 출처마다 다른 이름으로 등장하기도 한다. 검색 결과로 50편을 받아도 그것들이 서로 어떤 관계인지는 여전히 불투명하다.

### 2.2 인용 그래프의 한계

인용 그래프는 가장 자연스러운 해법처럼 보인다. 그런데 두 가지 문제가 있다. 첫째, Semantic Scholar 같은 데이터베이스도 인용 데이터를 완벽하게 보유하고 있지는 않다. 둘째, 최신 논문의 인용 부재 문제가 더 심각하다. 지난주에 arXiv에 올라온 논문은 인용이 0이다. 인용 그래프로는 그 논문을 네트워크에 포함시킬 방법이 없다.

우리가 원하는 것은 "아직 인용 관계가 형성되지 않았어도, 같은 주제를 다루는 논문들이 서로 연결되는" 네트워크다.

### 2.3 기여

그래서 우리는 다른 방향을 택했다. 제목과 키워드의 어휘 유사도를 기반으로 엣지를 생성하는 것이다. 인용이 없어도, DOI가 없어도, 같은 개념을 다루는 논문이라면 연결되어야 한다. 본 연구의 주요 기여는 다음과 같다.

1. 제목 토큰 + 키워드/카테고리 Jaccard를 결합한 하이브리드 유사도 기반 엣지 생성
2. Centroid shift + max-absolute normalization을 통한 레이아웃 정규화
3. Trace grouping 기반 Plotly.js 렌더링 최적화
4. 4단계 다중 소스 중복 제거 파이프라인

---

## 3. Related Work

### 3.1 Force-Directed 그래프 레이아웃

Fruchterman & Reingold [1]은 연결된 노드 간 인력과 모든 노드 쌍 간 척력을 시뮬레이션하여 그래프 레이아웃을 결정하는 알고리즘을 제안하였다. 본 시스템은 NetworkX [2]의 `spring_layout` 구현을 사용하며, 이 알고리즘 위에 좌표 정규화 후처리를 추가하였다.

### 3.2 지식 그래프 기반 RAG

LightRAG [3]은 지식 그래프를 entity-relation 형식으로 구축하고 이중 레벨 검색(local + global)을 지원하는 RAG 프레임워크이다. 본 시스템의 논문 네트워크와 LightRAG 방식의 GraphRAG를 통합하는 것은 향후 과제로 논의한다(Section 7 참조).

### 3.3 인터랙티브 시각화

Plotly [4]는 웹 기반 인터랙티브 시각화 라이브러리로, scatter plot을 통한 그래프 시각화를 지원한다. 본 시스템은 Plotly의 scatter trace를 활용하되, trace grouping 최적화를 통해 대규모 엣지 렌더링의 성능 병목을 해결하였다.

---

## 4. Methodology

### 4.1 하이브리드 유사도 기반 엣지 생성

<div style="margin:24px 0;text-align:center;">
<img src="/api/blog/figures/fig_hybrid_similarity.png" alt="하이브리드 유사도 계산" style="width:100%;max-width:960px;height:auto;border-radius:8px;" />
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 1. 하이브리드 유사도 계산 -- 제목 토큰(70%) + 키워드/카테고리 Jaccard(30%) 결합. 두 신호의 가중 합이 임계값 0.06을 초과하면 엣지가 생성된다.</em></p>
</div>

Figure 1에서 보듯이, 보조 유사도 계산은 각 논문에서 categories 문자열을 공백으로 나누고, keywords 리스트의 각 항목을 소문자로 변환하여 집합을 만든 뒤, 두 집합 사이의 Jaccard similarity를 kw_score로 사용한다. 최종 점수는 제목 유사도에 70%, 키워드/카테고리 유사도에 30%를 곱해 더한다.

```
Algorithm 1: 하이브리드 유사도 계산
──────────────────────────────────────
Input: doc_1, doc_2 (title, categories, keywords)
Output: edge weight or null

title_score = token_similarity(doc_1.title, doc_2.title)
kw_set_1 = lowercase(doc_1.categories.split() + doc_1.keywords)
kw_set_2 = lowercase(doc_2.categories.split() + doc_2.keywords)
kw_score = jaccard(kw_set_1, kw_set_2)

score = 0.7 * title_score + 0.3 * kw_score

if score >= 0.06:
    return edge(doc_1, doc_2, weight=round(score, 3))
else:
    return null
```

임계값은 0.12에서 0.06으로 낮췄다. 제목만 사용할 때는 노이즈를 줄이려고 높은 임계값이 필요했지만, 두 신호를 결합하면서 실질적인 연결만 선별할 수 있게 됐다. 같은 arXiv 카테고리에 속한 두 논문이라면 kw_score가 적어도 0.2 이상 나온다. 여기에 30%가 적용되면 0.06을 기여하므로, 제목에서 조금만 겹쳐도 임계값을 넘길 수 있다.

이 변경의 효과는 즉각적이었다. Mamba 논문은 cs.LG 카테고리를 공유하는 다른 시퀀스 모델 논문들과 연결됐다. In-Context Learning과 Few-Shot Prompting 논문들은 공통된 keywords를 통해 같은 클러스터에 포함됐다. 최신 논문의 고립 문제가 상당 부분 해소됐다.

### 4.2 레이아웃: Force-Directed + 좌표 정규화

<div style="margin:24px 0;text-align:center;">
<img src="/api/blog/figures/fig_normalization.png" alt="좌표 정규화 Before/After" style="width:100%;max-width:960px;height:auto;border-radius:8px;" />
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 2. 좌표 정규화 Before/After -- centroid shift 후 max-absolute normalization을 적용하여 고립 노드가 뷰포트 내에 복귀한 결과.</em></p>
</div>

유사도 기반 그래프가 완성되면 각 노드에 2D 좌표를 부여해야 한다. 본 시스템은 NetworkX [2]의 `spring_layout`을 사용한다. 내부적으로는 Fruchterman-Reingold 알고리즘 [1]이 작동한다. 연결된 노드는 인력으로 당기고, 모든 노드 쌍은 척력으로 밀어내는 물리 시뮬레이션을 수렴할 때까지 반복한다.

파라미터 선택도 중요하다. `seed=42`는 결정론적 레이아웃을 보장한다. 같은 논문 집합이면 매번 동일한 배치가 나온다. `k=0.75`는 노드 간 이상적인 간격을 결정하는 값이다. 기본값(1/sqrt(n))보다 크게 설정하면 노드들이 더 넓게 퍼진다. `iterations=50`으로 50회 반복한다. 이 값 이상에서는 배치가 크게 달라지지 않으면서 계산 시간만 늘어났다.

레이아웃 이후 두 단계의 좌표 변환을 적용한다. Figure 2에서 보듯이 정규화 전후의 차이는 명확하다.

```
Algorithm 2: 좌표 정규화 (Centroid Shift + Max-Absolute Normalization)
──────────────────────────────────────
Input: layout = {node_id: (x, y)}
Output: normalized_layout = {node_id: (x', y')}, x', y' in [-1, 1]

Step 1: Centroid Shift
  centroid_x = mean(x for (x, y) in layout.values())
  centroid_y = mean(y for (x, y) in layout.values())
  centered = {nid: (x - centroid_x, y - centroid_y) for nid, (x, y) in layout}

Step 2: Max-Absolute Normalization
  max_abs = max(max(|x|), max(|y|)) for all (x, y) in centered
  normalized = {nid: (x / max_abs, y / max_abs) for nid, (x, y) in centered}
```

이 두 단계로 "최신 논문이 안 보인다"는 문제가 해결됐다. 고립 노드가 어디에 있든 간에 정규화 후에는 [-1, 1] 안에 들어오도록 보장된다. 프론트엔드 뷰포트는 양 축에 0.2의 여유를 두어 [-1.2, 1.2]로 설정되어 있으므로, 어떤 노드도 잘리지 않는다.

### 4.3 다중 소스 중복 제거

6개 소스에서 동시에 검색하면 같은 논문이 여러 번 등장한다. "Attention Is All You Need"는 arXiv에서도, Semantic Scholar에서도, Google Scholar에서도 나온다. 그대로 그래프에 넣으면 같은 논문을 나타내는 노드가 3개 생기고, 그 사이에 높은 유사도 엣지가 연결된다. 클러스터가 인위적으로 밀집되어 보이는 문제다.

중복 제거는 4단계로 진행된다.

| 단계 | 방법 | 세부 기준 |
|------|------|-----------|
| 1 | DOI 매칭 | `https://doi.org/` prefix 제거 + 소문자 정규화 후 일치 |
| 2 | 정규화 제목 매칭 | NFKD 유니코드 정규화 -> ASCII 변환 -> 구두점 제거 -> 소문자 |
| 3 | Fuzzy title matching | Jaccard >= 0.85 AND 단어 수 비율 >= 0.80 |
| 4 | 임베딩 유사도 | `text-embedding-3-small` 코사인 >= 0.90 |

*Table 1. 4단계 중복 제거 기준. 상위 단계에서 매칭되면 하위 단계는 건너뛴다.*

중복이 발견되면 단순히 하나를 삭제하지 않는다. 메타데이터 풍부도 점수가 더 높은 논문을 대표로 삼고, 나머지에서 누락된 필드를 채운다. 풍부도 점수는 abstract(+3), DOI(+2), 저자 수(+1씩), 연도(+1), 인용수(+2), URL(+1), PDF URL(+1)을 합산한다. 여러 소스에서 같은 논문을 찾았다면 `_found_in_sources` 필드에 모든 소스 이름이 남는다.

---

## 5. Implementation

### 5.1 노드 시각 인코딩

<div style="margin:24px 0;text-align:center;">
<img src="/api/blog/figures/fig_node_encoding.png" alt="노드 시각 인코딩" style="width:100%;max-width:960px;height:auto;border-radius:8px;" />
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 3. 노드 시각 인코딩 -- 인용수 log 스케일 크기 + 연도 기반 색상 그라디언트. 오래된 논문은 어두운 청록색, 최근 논문은 밝은 초록색으로 구분된다.</em></p>
</div>

노드의 크기는 인용수를 반영한다. 인용이 0인 논문도 최소 크기가 있어야 하므로 log 스케일을 적용한다. 기본 크기 12에 `6 * log10(citations + 1)`을 더한다. 인용이 1000회인 논문의 크기는 약 30, 인용이 100회인 논문은 약 24가 된다. 선형 스케일이었다면 인용이 적은 대부분의 논문이 너무 작아 클릭조차 어려웠을 것이다.

색상은 출판 연도 기반 그라디언트를 사용한다. 수집된 논문들의 연도 범위를 구하고, 상대적 위치를 [0, 1]로 정규화한다. 이 값으로 초록 채널을 150에서 220까지 선형 변환한다. 빨간 채널은 60, 파란 채널은 150으로 고정이다. 결과적으로 오래된 논문은 어두운 청록색 계열, 최근 논문은 밝은 초록색 계열이 된다. Figure 3에서 이 인코딩 규칙을 확인할 수 있다. 논문을 클릭하면 해당 노드가 보라색(`rgba(168, 85, 247, 0.95)`)으로 강조된다.

### 5.2 엣지 렌더링 최적화: Trace Grouping

<div style="margin:24px 0;text-align:center;">
<img src="/api/blog/figures/fig_trace_grouping.png" alt="Trace Grouping 최적화" style="width:100%;max-width:960px;height:auto;border-radius:8px;" />
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 4. Edge Trace Grouping -- 수백 엣지를 투명도 기준으로 약 10개 Plotly trace로 압축하여 200ms 이하 렌더링을 달성. NaN 삽입으로 선분을 분리한다.</em></p>
</div>

논문 50편만 있어도 엣지가 수백 개가 될 수 있다. 각 엣지를 별도의 Plotly trace로 만들면 브라우저가 수백 개의 SVG 요소를 개별적으로 렌더링해야 한다. 실제로 초기 구현에서는 그래프 렌더링 시 1-2초의 지연이 발생했다.

해결책은 Figure 4에서 보듯이 Trace Grouping이다. 엣지의 가중치를 [0, 1]로 정규화하고, 이를 투명도로 변환한 뒤 0.1 단위로 반올림한다. 같은 투명도를 가진 엣지들의 좌표를 하나의 배열에 모아 단일 trace로 만든다. 경계를 표시하기 위해 각 엣지 사이에 `NaN`을 삽입하면 Plotly가 선을 분리해서 그린다. 이 방식으로 수백 개의 엣지가 약 10개 안팎의 Plotly trace로 압축된다. 렌더링 지연이 200ms 이하로 떨어졌다.

선택된 논문에 연결된 엣지는 별도로 처리한다. 강조 엣지는 두께 2.5, 보라색(`rgba(168, 85, 247, ...)`)으로 그린다. 나머지 엣지는 반투명한 회색(`rgba(156, 163, 175, ...)`)으로 물러선다. 사용자가 노드를 클릭했을 때 어떤 논문들과 연결되어 있는지 즉각적으로 파악할 수 있다.

### 5.3 인터랙션 설계

필터 패널에는 최소 인용수와 연도 범위 입력이 있다. 두 필터 모두 실시간으로 반응한다. 값을 바꾸면 `useMemo` 내부에서 필터링 후 그래프가 다시 계산된다. 줌과 팬은 Plotly의 기본 기능을 활용한다. `scrollZoom: true`, `dragmode: 'pan'`으로 설정하면 스크롤로 확대/축소, 드래그로 이동이 된다. 더블클릭은 초기 뷰로 리셋된다. 노드를 클릭하면 `customdata`로 저장된 `doc_id`를 읽어 해당 논문의 상세 패널을 오른쪽에 펼친다.

---

## 6. Evaluation

본 시스템의 정량적 평가는 다음 측면에서 진행되었다.

**렌더링 성능.** Trace grouping 적용 전 1-2초였던 그래프 렌더링 지연이 200ms 이하로 개선되었다. 50편 기준 엣지 수백 개가 약 10개의 Plotly trace로 압축된다.

**커버리지 개선.** 하이브리드 유사도(제목 70% + 키워드 30%) 도입 후, 인용이 0인 최신 논문의 고립 비율이 크게 감소하였다. 임계값을 0.12에서 0.06으로 조정하여 같은 arXiv 카테고리 논문 간 연결이 가능해졌다.

**레이아웃 안정성.** Centroid shift + max-absolute normalization 적용 후, 모든 노드가 [-1, 1] 범위에 보장되어 뷰포트 이탈 문제가 해결되었다.

---

## 7. Discussion

### 7.1 인용 기반 엣지 추가

현재 네트워크의 모든 엣지는 유사도에서 나온다. 실제 인용 관계는 반영되지 않는다. Semantic Scholar API는 paper ID를 입력하면 피인용 논문 목록을 반환한다. 이 데이터를 활용하면 유사도 엣지와 인용 엣지를 함께 보여주는 이중 레이어 그래프를 만들 수 있다. 두 종류의 엣지를 다른 색상으로 구분하면, 사용자가 "이 논문들은 실제로 서로 인용하는가, 아니면 단지 주제가 비슷한가"를 구분할 수 있다. 현재는 API 응답 속도와 인용 데이터 정합성 문제로 구현을 미루고 있다.

### 7.2 GraphRAG 통합

그래프 구조를 RAG에 활용하는 것이 다음 단계다. 현재의 GraphRAG 구현은 지식 그래프를 entity-relation 형식으로 구축하고 LightRAG [3] 방식의 이중 레벨 검색(local + global)을 지원한다. 논문 네트워크와 연결하면 "이 논문 주변의 클러스터에서 관련 논문을 검색하라"는 방식으로 컨텍스트를 구성할 수 있다. 검색 쿼리에 응답할 때 단일 논문을 기준으로 retrieval하는 것보다, 네트워크 구조상 밀집된 클러스터 전체를 컨텍스트로 활용하면 더 넓은 시야를 제공할 수 있다.

### 7.3 대규모 그래프 확장성

현재 구현은 O(n^2) 복잡도를 가진다. 모든 논문 쌍에 대해 유사도를 계산하기 때문이다. 논문이 50편이면 1,225쌍, 100편이면 4,950쌍이다. 지금은 문제가 없지만 수천 편의 논문을 다루게 되면 이 구현은 병목이 된다. Locality-Sensitive Hashing(LSH)을 적용하면 유사한 문서만 후보로 선별하고 나머지는 비교를 건너뛸 수 있다. 렌더링 측면에서도 1,000개 이상의 노드를 Plotly scatter로 표시하면 SVG 요소가 과도하게 많아진다. WebGL 기반의 그래픽스 엔진(deck.gl 또는 Sigma.js)으로 전환을 검토 중이다.

### 7.4 유사도 가중치 최적화

지금까지 제목 70% + 키워드 30%라는 가중치 조합을 사용하고 있는데, 이 비율이 최적인지는 모른다. 도메인에 따라 달라질 수 있다. 컴퓨터 과학 논문에서는 arXiv 카테고리가 강력한 신호지만, 생물학이나 물리학에서는 카테고리 체계가 더 세분화되어 키워드 신호가 더 클 수 있다. 사용자의 클릭 데이터와 북마크 패턴을 수집하면 "이 엣지가 실제로 유용했는가"를 평가할 수 있을 것이다.

### 7.5 네트워크 토폴로지와 연구 트렌드

더 흥미로운 질문은 네트워크 토폴로지 자체가 연구 트렌드를 드러내는가이다. 허브 노드로 점점 더 많은 엣지가 연결되는 논문이 있다면, 그 논문은 신흥 연구 방향의 교차점에 있을 가능성이 있다. 시간 축을 따라 클러스터가 분리되거나 합쳐지는 패턴을 추적하면 연구 분야의 분기와 수렴을 시각화할 수 있을 것이다.

---

## 8. Conclusion

본 논문은 인용 관계에 의존하지 않는 유사도 기반 논문 네트워크 시각화 시스템을 제안하였다. 하이브리드 유사도(제목 70% + 키워드 30%)를 통해 최신 논문의 고립 문제를 해결하였고, centroid shift와 max-absolute normalization으로 레이아웃 안정성을 확보하였다. Plotly.js의 trace grouping 최적화로 수백 엣지의 실시간 렌더링을 가능하게 하였으며, 4단계 중복 제거를 통해 다중 소스에서 수집된 논문의 정합성을 보장하였다.

향후 연구 방향으로는 (1) 인용 엣지와 유사도 엣지의 이중 레이어 통합, (2) GraphRAG를 활용한 클러스터 기반 컨텍스트 검색, (3) LSH 기반 대규모 그래프 확장, (4) 사용자 행동 데이터 기반 가중치 자동 최적화를 계획하고 있다.

---

## 9. References

[1] Fruchterman, T. M. J., & Reingold, E. M. (1991). Graph drawing by force-directed placement. *Software: Practice and Experience*, 21(11), 1129-1164.

[2] Hagberg, A. A., Schult, D. A., & Swart, P. J. (2008). Exploring network structure, dynamics, and function using NetworkX. *Proceedings of the 7th Python in Science Conference (SciPy2008)*.

[3] Guo, Z., Liang, R., et al. (2024). LightRAG: Simple and Fast Retrieval-Augmented Generation. *arXiv preprint arXiv:2410.05779*.

[4] Plotly Technologies Inc. (2015). *Collaborative data science*. Plotly. https://plot.ly
