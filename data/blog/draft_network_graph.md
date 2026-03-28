# 논문 네트워크 그래프: 흩어진 논문들 사이의 숨겨진 연결

*6개 데이터베이스에서 수집한 논문들 사이의 관계를 자동으로 발견하고,
인터랙티브 네트워크로 시각화한 이야기.*

작성: 집현전 팀 · 10분 읽기
태그: #네트워크그래프 #유사도 #시각화 #GraphRAG

---

## 왜 논문 네트워크가 필요한가

연구를 시작할 때 가장 먼저 맞닥뜨리는 문제는 "지금 내가 읽고 있는 이 논문이 전체 지형에서 어디쯤 있는가?"라는 질문이다.

우리는 arXiv, Google Scholar, OpenAlex, DBLP, Semantic Scholar, Connected Papers 등 6개 소스에서 논문을 수집한다. 각각의 소스는 서로 다른 메타데이터 형식을 사용하고, 같은 논문이 출처마다 다른 이름으로 등장하기도 한다. 검색 결과로 50편을 받아도 그것들이 서로 어떤 관계인지는 여전히 불투명하다.

인용 그래프는 가장 자연스러운 해법처럼 보인다. 그런데 문제가 있다. Semantic Scholar 같은 데이터베이스도 인용 데이터를 완벽하게 보유하고 있지는 않다. 더 심각한 건 최신 논문이다. 지난주에 arXiv에 올라온 논문은 인용이 0이다. 인용 그래프로는 그 논문을 네트워크에 포함시킬 방법이 없다. 우리가 원하는 것은 "아직 인용 관계가 형성되지 않았어도, 같은 주제를 다루는 논문들이 서로 연결되는" 네트워크다.

그래서 우리는 다른 방향을 택했다. 제목과 키워드의 어휘 유사도를 기반으로 엣지를 생성하는 것이다. 인용이 없어도, DOI가 없어도, 같은 개념을 다루는 논문이라면 연결되어야 한다는 생각이었다. 물론 이 아이디어도 처음에는 예상대로 작동하지 않았다.

---



<div style="margin:24px 0;text-align:center;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 220" style="width:100%;max-width:960px;height:auto" role="img" aria-label="네트워크 그래프 생성 파이프라인">
  <defs>
    <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
      <path d="M0,0 L0,6 L8,3 z" fill="#6b7280"/>
    </marker>
  </defs>

  <!-- Background -->
  <rect width="960" height="220" fill="#0f0f0f"/>

  <!-- Title -->
  <text x="480" y="30" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="14" font-weight="600" fill="#f3f4f6">네트워크 그래프 생성 파이프라인</text>

  <!-- Step 1: 논문 수집 -->
  <rect x="30" y="55" width="155" height="130" rx="8" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>
  <text x="107" y="80" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#f3f4f6">논문 수집</text>
  <line x1="47" y1="89" x2="170" y2="89" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="107" y="107" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">6개 소스</text>
  <text x="107" y="122" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">arXiv · Scholar</text>
  <text x="107" y="137" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">Connected Papers</text>
  <text x="107" y="152" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">Semantic Scholar</text>
  <text x="107" y="167" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">PubMed · DBLP</text>

  <!-- Arrow 1→2 -->
  <line x1="186" y1="120" x2="210" y2="120" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arrow)"/>

  <!-- Step 2: 중복 제거 -->
  <rect x="212" y="55" width="155" height="130" rx="8" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>
  <text x="289" y="80" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#f3f4f6">중복 제거</text>
  <line x1="228" y1="89" x2="352" y2="89" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="289" y="107" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">4단계 파이프라인</text>
  <text x="289" y="122" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">① DOI 일치</text>
  <text x="289" y="137" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">② 제목 정규화</text>
  <text x="289" y="152" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">③ Jaccard 유사도</text>
  <text x="289" y="167" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">④ 임베딩 비교</text>

  <!-- Arrow 2→3 -->
  <line x1="368" y1="120" x2="392" y2="120" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arrow)"/>

  <!-- Step 3: 유사도 계산 (핵심 — accent border) -->
  <rect x="394" y="55" width="172" height="130" rx="8" fill="#181818" stroke="#a5b4fc" stroke-width="1.5"/>
  <text x="480" y="80" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#f3f4f6">유사도 계산</text>
  <line x1="410" y1="89" x2="550" y2="89" stroke="rgba(165,180,252,0.25)" stroke-width="1"/>
  <text x="480" y="107" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">하이브리드 스코어</text>
  <text x="480" y="122" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#a5b4fc">제목 70% + 키워드 30%</text>
  <text x="480" y="137" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">Jaccard 토큰 교집합</text>
  <text x="480" y="152" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">임계값 score ≥ 0.06</text>
  <text x="480" y="167" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">엣지 연결 여부 결정</text>

  <!-- Arrow 3→4 -->
  <line x1="567" y1="120" x2="591" y2="120" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arrow)"/>

  <!-- Step 4: 레이아웃 -->
  <rect x="593" y="55" width="155" height="130" rx="8" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>
  <text x="670" y="80" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#f3f4f6">레이아웃</text>
  <line x1="609" y1="89" x2="733" y2="89" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="670" y="107" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">NetworkX</text>
  <text x="670" y="122" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">spring_layout</text>
  <text x="670" y="137" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">seed=42</text>
  <text x="670" y="152" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">k=0.75</text>
  <text x="670" y="167" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">좌표 정규화 적용</text>

  <!-- Arrow 4→5 -->
  <line x1="749" y1="120" x2="773" y2="120" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arrow)"/>

  <!-- Step 5: 시각화 -->
  <rect x="775" y="55" width="155" height="130" rx="8" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>
  <text x="852" y="80" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#f3f4f6">시각화</text>
  <line x1="791" y1="89" x2="915" y2="89" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="852" y="107" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">Plotly.js</text>
  <text x="852" y="122" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">노드 크기: 인용 수</text>
  <text x="852" y="137" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">노드 색상: 출판 연도</text>
  <text x="852" y="152" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">엣지 투명도: 유사도</text>
  <text x="852" y="167" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">WebGL (100+ 노드)</text>

  <!-- Step labels bottom -->
  <text x="107" y="200" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#6b7280">STEP 1</text>
  <text x="289" y="200" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#6b7280">STEP 2</text>
  <text x="480" y="200" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#a5b4fc">STEP 3</text>
  <text x="670" y="200" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#6b7280">STEP 4</text>
  <text x="852" y="200" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#6b7280">STEP 5</text>
</svg>
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 1. 논문 네트워크 그래프 생성 파이프라인 — 수집부터 시각화까지</em></p>
</div>
## 첫 번째 시도: 제목 유사도만으로

처음 구현은 단순했다. 논문 제목을 토큰화하고, 두 논문 사이의 Jaccard similarity를 계산해서 임계값 이상이면 엣지를 추가한다. 토큰화 규칙도 간단하다. 정규표현식으로 영단어를 추출하고, 3글자 이하의 단어(관사, 전치사 등)를 제거하면 `["attention", "transformer", "models"]` 같은 토큰 집합이 남는다.

이 방식으로 임계값 0.12에서 테스트를 돌려봤다. 결과는 나쁘지 않았다. "Attention Is All You Need"와 "Efficient Attention Mechanisms for Transformer Models"는 attention, transformer 같은 토큰을 공유하며 연결됐다. 고전적인 논문들은 서로 잘 묶였다.

그런데 최신 논문들이 고립됐다. 새로운 연구일수록 새로운 용어를 쓰는 경향이 있다. "Flash Attention"은 attention이라는 토큰을 포함하지만, 논문 제목이 짧아서 전체 Jaccard 점수가 0.12 미만으로 떨어지는 경우가 많았다. 더 큰 문제는 같은 개념을 완전히 다른 단어로 표현한 논문들이다. "In-Context Learning"과 "Few-Shot Prompting"은 분명히 같은 연구 영역을 다루지만, 제목 토큰은 전혀 겹치지 않는다. 임계값이 어떻든 간에 이 두 논문은 연결되지 않았다.

레이아웃 알고리즘 문제도 드러났다. 연결이 없는 고립 노드들은 NetworkX의 spring_layout이 그래프 중심에서 멀리 밀어냈다. 당시에는 centroid 보정만 적용했는데, 그것만으로는 부족했다. 일부 고립 노드가 [-1.2, 1.2] 좌표 범위를 벗어나 뷰포트 밖에 배치됐다. 사용자 입장에서는 "방금 검색한 최신 논문이 그래프에 안 보인다"는 불만으로 돌아왔다.

---

## 무엇이 부족했는가

### 최신 논문의 고립

근본적인 문제는 제목 유사도가 어휘적 표면에만 의존한다는 점이었다. arXiv에 올라온 지 3일 된 논문은 자신만의 새로운 단어를 쓴다. "Mamba", "RWKV", "RetNet" 같은 논문들은 제목 자체가 고유명사다. 이런 논문들은 임계값이 낮아도 기존 논문 집합과 제목 토큰을 거의 공유하지 않는다. 결과적으로 이들은 그래프에는 노드로 존재하지만 어떤 엣지도 가지지 않는다.

spring_layout이 이 문제를 악화시켰다. Fruchterman-Reingold 알고리즘은 연결된 노드들은 서로 끌어당기고, 모든 노드들은 서로 밀어내는 힘을 시뮬레이션한다. 고립 노드는 끌어당기는 힘이 없고, 다른 노드들에게 밀리기만 한다. 레이아웃 수렴 후에 이런 노드들은 그래프 외곽에 흩어진다. centroid만 보정하면 평균 위치가 중심으로 오더라도 분산이 크면 여전히 일부 노드가 범위를 벗어난다.

### 좌표 정규화 부재

centroid 보정은 전체 그래프의 무게중심을 (0, 0)으로 옮기는 작업이다. 하지만 최대 절댓값을 제어하지는 않는다. 노드 50개가 [-0.3, 0.3] 범위에 밀집해 있고 고립 노드 2개가 [1.4, 1.8]에 있다면, centroid 보정 후에도 그 두 노드는 여전히 범위를 벗어난다. 프론트엔드 뷰포트는 x축 [-1.2, 1.2], y축 [-1.2, 1.2]로 설정되어 있으니, 이 노드들은 화면에서 잘려나간다.

---

## 하이브리드 유사도: 제목 70% + 키워드 30%

두 가지 문제를 동시에 해결하는 방법을 고민했다. 어휘 유사도의 한계는 제목 이외의 신호를 추가해서 보완하기로 했다. 논문 메타데이터에는 제목 외에도 categories와 keywords 필드가 있다. arXiv 논문이라면 categories 필드에 cs.LG, cs.CL 같은 분류가 들어있다. 같은 카테고리에 속한 논문들은 제목이 전혀 달라도 같은 연구 영역에 있다.



<div style="margin:24px 0;text-align:center;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 280" style="width:100%;max-width:960px;height:auto" role="img" aria-label="하이브리드 유사도 계산">
  <defs>
    <marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
      <path d="M0,0 L0,6 L8,3 z" fill="#6b7280"/>
    </marker>
  </defs>

  <!-- Background -->
  <rect width="960" height="280" fill="#0f0f0f"/>

  <!-- Title -->
  <text x="480" y="28" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="14" font-weight="600" fill="#f3f4f6">하이브리드 유사도 계산</text>

  <!-- ─── Paper A box ─── -->
  <rect x="30" y="42" width="390" height="62" rx="8" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>
  <text x="50" y="62" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#a5b4fc">Paper A</text>
  <text x="50" y="78" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#f3f4f6">"Efficient Attention for Long Sequences"</text>
  <text x="50" y="95" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">categories: cs.LG  cs.CL</text>

  <!-- ─── Paper B box ─── -->
  <rect x="540" y="42" width="390" height="62" rx="8" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>
  <text x="560" y="62" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#6366f1">Paper B</text>
  <text x="560" y="78" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#f3f4f6">"Flash Attention: Fast Transformer Training"</text>
  <text x="560" y="95" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">categories: cs.LG</text>

  <!-- ─── Title tokens section ─── -->
  <!-- Row label -->
  <text x="30" y="135" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="600" fill="#9ca3af">제목 토큰</text>

  <!-- Paper A title tokens -->
  <!-- efficient -->
  <rect x="30" y="142" width="72" height="22" rx="4" fill="#1f2937" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
  <text x="66" y="157" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">efficient</text>
  <!-- attention A — shared -->
  <rect x="108" y="142" width="66" height="22" rx="4" fill="#1f2937" stroke="#a5b4fc" stroke-width="1.5"/>
  <text x="141" y="157" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#a5b4fc">attention</text>
  <!-- long -->
  <rect x="180" y="142" width="46" height="22" rx="4" fill="#1f2937" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
  <text x="203" y="157" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">long</text>
  <!-- sequences -->
  <rect x="232" y="142" width="72" height="22" rx="4" fill="#1f2937" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
  <text x="268" y="157" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">sequences</text>

  <!-- intersection label -->
  <text x="420" y="150" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#9ca3af">∩ {attention}</text>
  <line x1="468" y1="153" x2="498" y2="153" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arr)"/>
  <!-- title_sim result -->
  <text x="560" y="145" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#9ca3af">title_sim =</text>
  <text x="560" y="162" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#a5b4fc">1/8 = 0.125</text>

  <!-- Paper B title tokens -->
  <!-- flash -->
  <rect x="700" y="142" width="42" height="22" rx="4" fill="#1f2937" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
  <text x="721" y="157" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">flash</text>
  <!-- attention B — shared -->
  <rect x="748" y="142" width="66" height="22" rx="4" fill="#1f2937" stroke="#a5b4fc" stroke-width="1.5"/>
  <text x="781" y="157" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#a5b4fc">attention</text>
  <!-- fast -->
  <rect x="820" y="142" width="36" height="22" rx="4" fill="#1f2937" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
  <text x="838" y="157" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">fast</text>
  <!-- transformer -->
  <rect x="700" y="168" width="78" height="22" rx="4" fill="#1f2937" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
  <text x="739" y="183" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">transformer</text>
  <!-- training -->
  <rect x="784" y="168" width="56" height="22" rx="4" fill="#1f2937" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
  <text x="812" y="183" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">training</text>

  <!-- ─── Divider ─── -->
  <line x1="30" y1="205" x2="930" y2="205" stroke="#1f2937" stroke-width="1"/>

  <!-- ─── Keyword tokens section ─── -->
  <text x="30" y="222" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="600" fill="#9ca3af">키워드 토큰</text>

  <!-- Paper A kw tokens -->
  <!-- cs.lg A — shared -->
  <rect x="30" y="229" width="52" height="22" rx="4" fill="#1f2937" stroke="#22c55e" stroke-width="1.5"/>
  <text x="56" y="244" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#22c55e">cs.LG</text>
  <!-- cs.cl A — unique -->
  <rect x="88" y="229" width="46" height="22" rx="4" fill="#1f2937" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
  <text x="111" y="244" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#9ca3af">cs.CL</text>

  <!-- intersection label kw -->
  <text x="420" y="238" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#9ca3af">∩ {cs.LG}</text>
  <line x1="468" y1="241" x2="498" y2="241" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arr)"/>
  <!-- kw_sim result -->
  <text x="560" y="233" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#9ca3af">kw_sim =</text>
  <text x="560" y="250" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#22c55e">1/2 = 0.500</text>

  <!-- Paper B kw token -->
  <!-- cs.lg B — shared -->
  <rect x="700" y="229" width="52" height="22" rx="4" fill="#1f2937" stroke="#22c55e" stroke-width="1.5"/>
  <text x="726" y="244" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#22c55e">cs.LG</text>

  <!-- ─── Final formula ─── -->
  <rect x="30" y="265" width="900" height="1" fill="#1f2937"/>
  <text x="480" y="277" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" fill="#9ca3af">
    종합 스코어:
    <tspan font-weight="700" fill="#f3f4f6">0.7 × 0.125 + 0.3 × 0.500 = </tspan>
    <tspan font-weight="700" fill="#22c55e">0.238</tspan>
    <tspan fill="#9ca3af">  ≥  0.06  →  </tspan>
    <tspan font-weight="700" fill="#22c55e">엣지 연결 ✓</tspan>
  </text>
</svg>
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 2. 하이브리드 유사도 계산 — 제목 토큰(70%) + 키워드(30%) 결합</em></p>
</div>
보조 유사도 계산은 간단하다. 각 논문에서 categories 문자열을 공백으로 나누고, keywords 리스트의 각 항목을 소문자로 변환하여 집합을 만든다. 두 집합 사이의 Jaccard similarity를 kw_score로 사용한다. 최종 점수는 제목 유사도에 70%, 키워드/카테고리 유사도에 30%를 곱해 더한다.

```python
# 종합 점수 (제목 70% + 키워드 30%)
score = 0.7 * title_score + 0.3 * kw_score

if score >= 0.06:
    graph.add_edge(doc_id1, doc_id2, weight=round(score, 3))
```

임계값은 0.12에서 0.06으로 낮췄다. 제목만 사용할 때는 노이즈를 줄이려고 높은 임계값이 필요했지만, 두 신호를 결합하면서 실질적인 연결만 선별할 수 있게 됐다. 같은 arXiv 카테고리에 속한 두 논문이라면 kw_score가 적어도 0.2 이상 나온다. 여기에 30%가 적용되면 0.06을 기여하므로, 제목에서 조금만 겹쳐도 임계값을 넘길 수 있다.

이 변경의 효과는 즉각적이었다. Mamba 논문은 cs.LG 카테고리를 공유하는 다른 시퀀스 모델 논문들과 연결됐다. In-Context Learning과 Few-Shot Prompting 논문들은 공통된 keywords를 통해 같은 클러스터에 포함됐다. 최신 논문의 고립 문제가 상당 부분 해소됐다.

---



<div style="margin:24px 0;text-align:center;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 300" style="width:100%;max-width:960px;height:auto" role="img" aria-label="좌표 정규화 Before/After">
  <defs>
    <marker id="arrnorm" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
      <path d="M0,0 L0,6 L8,3 z" fill="#a5b4fc"/>
    </marker>
  </defs>

  <!-- Background -->
  <rect width="960" height="300" fill="#0f0f0f"/>

  <!-- Title -->
  <text x="480" y="28" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="14" font-weight="600" fill="#f3f4f6">좌표 정규화 Before / After</text>

  <!-- ══════════════ BEFORE panel ══════════════ -->
  <!-- Panel background -->
  <rect x="30" y="42" width="390" height="220" rx="8" fill="#181818" stroke="#1f2937" stroke-width="1.5"/>

  <!-- Label -->
  <text x="225" y="65" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#f3f4f6">Before</text>
  <text x="225" y="82" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#6b7280">centroid 보정만</text>

  <!-- Viewport frame (clipping region) -->
  <rect x="55" y="92" width="340" height="155" rx="4" fill="none" stroke="#1f2937" stroke-width="1.5" stroke-dasharray="4 3"/>

  <!-- Normal nodes inside viewport -->
  <circle cx="110" cy="118" r="5" fill="#a5b4fc"/>
  <circle cx="145" cy="112" r="5" fill="#a5b4fc"/>
  <circle cx="175" cy="130" r="6" fill="#a5b4fc"/>
  <circle cx="210" cy="125" r="4" fill="#a5b4fc"/>
  <circle cx="155" cy="155" r="5" fill="#a5b4fc"/>
  <circle cx="200" cy="165" r="6" fill="#a5b4fc"/>
  <circle cx="130" cy="175" r="4" fill="#a5b4fc"/>
  <circle cx="245" cy="145" r="5" fill="#a5b4fc"/>
  <circle cx="280" cy="138" r="4" fill="#a5b4fc"/>
  <circle cx="230" cy="195" r="5" fill="#a5b4fc"/>
  <circle cx="170" cy="200" r="4" fill="#a5b4fc"/>
  <circle cx="305" cy="160" r="5" fill="#a5b4fc"/>

  <!-- Problem node — outside viewport (bottom-right overflow) -->
  <circle cx="368" cy="232" r="6" fill="#ef4444"/>
  <!-- dashed leader to show it is outside -->
  <line x1="355" y1="224" x2="340" y2="210" stroke="#ef4444" stroke-width="1" stroke-dasharray="3 2"/>
  <!-- Label -->
  <text x="375" y="248" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#ef4444">뷰포트 밖</text>

  <!-- Second problem node — top-left overflow -->
  <circle cx="44" cy="104" r="5" fill="#ef4444"/>
  <line x1="53" y1="107" x2="64" y2="110" stroke="#ef4444" stroke-width="1" stroke-dasharray="3 2"/>

  <!-- Warning label -->
  <text x="225" y="260" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#ef4444">고립 노드가 뷰포트 밖으로 벗어남</text>

  <!-- ══════════════ Center arrow ══════════════ -->
  <line x1="438" y1="152" x2="518" y2="152" stroke="#a5b4fc" stroke-width="2" marker-end="url(#arrnorm)"/>
  <text x="478" y="143" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="600" fill="#a5b4fc">정규화</text>
  <text x="478" y="170" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="9" fill="#6b7280">max-abs</text>
  <text x="478" y="182" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="9" fill="#6b7280">[-1, 1]</text>

  <!-- ══════════════ AFTER panel ══════════════ -->
  <!-- Panel background -->
  <rect x="540" y="42" width="390" height="220" rx="8" fill="#181818" stroke="#1f2937" stroke-width="1.5"/>

  <!-- Label -->
  <text x="735" y="65" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#f3f4f6">After</text>
  <text x="735" y="82" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#6b7280">+ max-abs 정규화</text>

  <!-- Viewport frame -->
  <rect x="565" y="92" width="340" height="155" rx="4" fill="none" stroke="#22c55e" stroke-width="1.5"/>

  <!-- All nodes comfortably inside -->
  <circle cx="615" cy="120" r="5" fill="#a5b4fc"/>
  <circle cx="652" cy="115" r="5" fill="#a5b4fc"/>
  <circle cx="688" cy="132" r="6" fill="#a5b4fc"/>
  <circle cx="720" cy="126" r="4" fill="#a5b4fc"/>
  <circle cx="660" cy="158" r="5" fill="#a5b4fc"/>
  <circle cx="700" cy="168" r="6" fill="#a5b4fc"/>
  <circle cx="635" cy="178" r="4" fill="#a5b4fc"/>
  <circle cx="745" cy="148" r="5" fill="#a5b4fc"/>
  <circle cx="778" cy="140" r="4" fill="#a5b4fc"/>
  <circle cx="730" cy="196" r="5" fill="#a5b4fc"/>
  <circle cx="672" cy="202" r="4" fill="#a5b4fc"/>
  <circle cx="802" cy="162" r="5" fill="#a5b4fc"/>
  <!-- Previously-problematic nodes now inside, shown in green -->
  <circle cx="858" cy="218" r="6" fill="#22c55e"/>
  <circle cx="578" cy="103" r="5" fill="#22c55e"/>

  <!-- Green check mark -->
  <text x="870" y="98" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="22" fill="#22c55e">✓</text>

  <!-- Success label -->
  <text x="735" y="260" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#22c55e">모든 노드 [-1, 1] 범위 내 배치</text>

  <!-- ══════════════ Bottom caption ══════════════ -->
  <text x="480" y="285" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#6b7280">pos[node] = (pos[node] - centroid) / max(abs(pos[node]))</text>
</svg>
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 3. 좌표 정규화 Before/After — 고립 노드의 뷰포트 복귀</em></p>
</div>
## 레이아웃: Force-Directed + 정규화

유사도 기반 그래프가 완성되면 각 노드에 2D 좌표를 부여해야 한다. 우리는 NetworkX의 `spring_layout`을 사용한다. 내부적으로는 Fruchterman-Reingold 알고리즘이 작동한다. 연결된 노드는 인력으로 당기고, 모든 노드 쌍은 척력으로 밀어내는 물리 시뮬레이션을 수렴할 때까지 반복한다.

파라미터 선택도 중요하다. `seed=42`는 결정론적 레이아웃을 보장한다. 같은 논문 집합이면 매번 동일한 배치가 나온다. `k=0.75`는 노드 간 이상적인 간격을 결정하는 값이다. 기본값(1/sqrt(n))보다 크게 설정하면 노드들이 더 넓게 퍼진다. `iterations=50`으로 50회 반복한다. 이 값 이상에서는 배치가 크게 달라지지 않으면서 계산 시간만 늘어났다.

레이아웃 이후 두 단계의 좌표 변환을 적용한다. 첫째, centroid shift다. 모든 노드의 x, y 평균을 계산해서 빼면 그래프의 무게중심이 원점으로 이동한다. 둘째, max-absolute normalization이다. centroid 보정 후 x와 y 전체에서 절댓값의 최댓값을 구하고, 그 값으로 나눈다. 이렇게 하면 모든 노드가 [-1, 1] 범위 안에 들어온다.

```python
if len(layout) > 0:
    centroid_x = sum(pos[0] for pos in layout.values()) / len(layout)
    centroid_y = sum(pos[1] for pos in layout.values()) / len(layout)
    centered = {nid: (x - centroid_x, y - centroid_y) for nid, (x, y) in layout.items()}

    max_abs = max(
        max(abs(x) for x, _ in centered.values()),
        max(abs(y) for _, y in centered.values()),
    ) or 1.0
    layout = {nid: (x / max_abs, y / max_abs) for nid, (x, y) in centered.items()}
```

이 두 단계로 "최신 논문이 안 보인다"는 문제가 해결됐다. 고립 노드가 어디에 있든 간에 정규화 후에는 [-1, 1] 안에 들어오도록 보장된다. 프론트엔드 뷰포트는 양 축에 0.2의 여유를 두어 [-1.2, 1.2]로 설정되어 있으므로, 어떤 노드도 잘리지 않는다.

---

## 프론트엔드: Plotly.js 인터랙티브 시각화

### 노드 디자인

노드의 크기는 인용수를 반영한다. 인용이 0인 논문도 최소 크기가 있어야 하므로 log 스케일을 적용한다. 기본 크기 12에 `6 * log10(citations + 1)`을 더한다. 인용이 1000회인 논문의 크기는 약 30, 인용이 100회인 논문은 약 24가 된다. 선형 스케일이었다면 인용이 적은 대부분의 논문이 너무 작아 클릭조차 어려웠을 것이다.

색상은 출판 연도 기반 그라디언트를 사용한다. 수집된 논문들의 연도 범위를 구하고, 상대적 위치를 [0, 1]로 정규화한다. 이 값으로 초록 채널을 150에서 220까지 선형 변환한다. 빨간 채널은 60, 파란 채널은 150으로 고정이다. 결과적으로 오래된 논문은 어두운 청록색 계열, 최근 논문은 밝은 초록색 계열이 된다. 논문을 클릭하면 해당 노드가 보라색(`rgba(168, 85, 247, 0.95)`)으로 강조된다.

### 엣지 최적화

논문 50편만 있어도 엣지가 수백 개가 될 수 있다. 각 엣지를 별도의 Plotly trace로 만들면 브라우저가 수백 개의 SVG 요소를 개별적으로 렌더링해야 한다. 실제로 초기 구현에서는 그래프 렌더링 시 1-2초의 지연이 발생했다.

해결책은 Trace Grouping이다. 엣지의 가중치를 [0, 1]로 정규화하고, 이를 투명도로 변환한 뒤 0.1 단위로 반올림한다. 같은 투명도를 가진 엣지들의 좌표를 하나의 배열에 모아 단일 trace로 만든다. 경계를 표시하기 위해 각 엣지 사이에 `NaN`을 삽입하면 Plotly가 선을 분리해서 그린다. 이 방식으로 수백 개의 엣지가 약 10개 안팎의 Plotly trace로 압축된다. 렌더링 지연이 200ms 이하로 떨어졌다.

선택된 논문에 연결된 엣지는 별도로 처리한다. 강조 엣지는 두께 2.5, 보라색(`rgba(168, 85, 247, ...)`)으로 그린다. 나머지 엣지는 반투명한 회색(`rgba(156, 163, 175, ...)`)으로 물러선다. 사용자가 노드를 클릭했을 때 어떤 논문들과 연결되어 있는지 즉각적으로 파악할 수 있다.

### 인터랙션

필터 패널에는 최소 인용수와 연도 범위 입력이 있다. 두 필터 모두 실시간으로 반응한다. 값을 바꾸면 `useMemo` 내부에서 필터링 후 그래프가 다시 계산된다. 줌과 팬은 Plotly의 기본 기능을 활용한다. `scrollZoom: true`, `dragmode: 'pan'`으로 설정하면 스크롤로 확대/축소, 드래그로 이동이 된다. 더블클릭은 초기 뷰로 리셋된다. 노드를 클릭하면 `customdata`로 저장된 `doc_id`를 읽어 해당 논문의 상세 패널을 오른쪽에 펼친다.

---

## 중복 제거: 다중 소스의 같은 논문

6개 소스에서 동시에 검색하면 같은 논문이 여러 번 등장한다. "Attention Is All You Need"는 arXiv에서도, Semantic Scholar에서도, Google Scholar에서도 나온다. 그대로 그래프에 넣으면 같은 논문을 나타내는 노드가 3개 생기고, 그 사이에 높은 유사도 엣지가 연결된다. 클러스터가 인위적으로 밀집되어 보이는 문제다.

중복 제거는 4단계로 진행된다. 첫째, DOI 매칭이다. 두 논문이 동일한 정규화된 DOI를 가지면 같은 논문이다. DOI 정규화는 `https://doi.org/` 같은 prefix를 제거하고 소문자로 통일하는 것이다. 둘째, 정규화 제목 매칭이다. 제목을 NFKD 유니코드 정규화로 ASCII로 변환하고, 구두점을 제거하고, 소문자로 통일한다. 정확히 일치하면 같은 논문이다. 셋째, Fuzzy title matching이다. Jaccard similarity가 0.85 이상이고 두 제목의 단어 수 비율이 0.80 이상이면 같은 논문으로 판단한다. 넷째, 임베딩 유사도다. `text-embedding-3-small`로 임베딩한 후 코사인 유사도가 0.90 이상이면 중복으로 본다.

중복이 발견되면 단순히 하나를 삭제하지 않는다. 메타데이터 풍부도 점수가 더 높은 논문을 대표로 삼고, 나머지에서 누락된 필드를 채운다. 풍부도 점수는 abstract(+3), DOI(+2), 저자 수(+1씩), 연도(+1), 인용수(+2), URL(+1), PDF URL(+1)을 합산한다. 여러 소스에서 같은 논문을 찾았다면 `_found_in_sources` 필드에 모든 소스 이름이 남는다.

---

## 아직 남은 과제

### 인용 기반 엣지 추가

현재 네트워크의 모든 엣지는 유사도에서 나온다. 실제 인용 관계는 반영되지 않는다. Semantic Scholar API는 paper ID를 입력하면 피인용 논문 목록을 반환한다. 이 데이터를 활용하면 유사도 엣지와 인용 엣지를 함께 보여주는 이중 레이어 그래프를 만들 수 있다. 두 종류의 엣지를 다른 색상으로 구분하면, 사용자가 "이 논문들은 실제로 서로 인용하는가, 아니면 단지 주제가 비슷한가"를 구분할 수 있다. 현재는 API 응답 속도와 인용 데이터 정합성 문제로 구현을 미루고 있다.

### GraphRAG 통합

그래프 구조를 RAG에 활용하는 것이 다음 단계다. 현재의 GraphRAG 구현은 지식 그래프를 entity-relation 형식으로 구축하고 LightRAG 방식의 이중 레벨 검색(local + global)을 지원한다. 논문 네트워크와 연결하면 "이 논문 주변의 클러스터에서 관련 논문을 검색하라"는 방식으로 컨텍스트를 구성할 수 있다. 검색 쿼리에 응답할 때 단일 논문을 기준으로 retrieval하는 것보다, 네트워크 구조상 밀집된 클러스터 전체를 컨텍스트로 활용하면 더 넓은 시야를 제공할 수 있다.

### 대규모 그래프 성능

현재 구현은 O(n²) 복잡도를 가진다. 모든 논문 쌍에 대해 유사도를 계산하기 때문이다. 논문이 50편이면 1,225쌍, 100편이면 4,950쌍이다. 지금은 문제가 없지만 집현전이 수천 편의 논문을 다루게 되면 이 구현은 병목이 된다. Locality-Sensitive Hashing(LSH)을 적용하면 유사한 문서만 후보로 선별하고 나머지는 비교를 건너뛸 수 있다. 렌더링 측면에서도 1,000개 이상의 노드를 Plotly scatter로 표시하면 SVG 요소가 과도하게 많아진다. WebGL 기반의 그래픽스 엔진(deck.gl 또는 Sigma.js)으로 전환을 검토 중이다.

---

## 열린 질문

지금까지 제목 70% + 키워드 30%라는 가중치 조합을 사용하고 있는데, 이 비율이 최적인지는 모른다. 도메인에 따라 달라질 수 있다. 컴퓨터 과학 논문에서는 arXiv 카테고리가 강력한 신호지만, 생물학이나 물리학에서는 카테고리 체계가 더 세분화되어 키워드 신호가 더 클 수 있다. 사용자의 클릭 데이터와 북마크 패턴을 수집하면 "이 엣지가 실제로 유용했는가"를 평가할 수 있지 않을까.

더 흥미로운 질문은 네트워크 토폴로지 자체가 연구 트렌드를 드러내는가이다. 허브 노드로 점점 더 많은 엣지가 연결되는 논문이 있다면, 그 논문은 신흥 연구 방향의 교차점에 있을 가능성이 있다. 시간 축을 따라 클러스터가 분리되거나 합쳐지는 패턴을 추적하면 연구 분야의 분기와 수렴을 시각화할 수 있지 않을까. 아직 답이 없는 질문들이다. 독자들은 논문 네트워크에서 어떤 구조적 패턴이 가장 유용하다고 생각하는가?

---

## 참고문헌

- Fruchterman, T. M. J., & Reingold, E. M. (1991). Graph drawing by force-directed placement. *Software: Practice and Experience*, 21(11), 1129–1164.
- Hagberg, A. A., Schult, D. A., & Swart, P. J. (2008). Exploring network structure, dynamics, and function using NetworkX. *Proceedings of the 7th Python in Science Conference (SciPy2008)*.
- Guo, Z., Liang, R., et al. (2024). LightRAG: Simple and Fast Retrieval-Augmented Generation. *arXiv preprint arXiv:2410.05779*.
- Plotly Technologies Inc. (2015). *Collaborative data science*. Plotly. https://plot.ly
