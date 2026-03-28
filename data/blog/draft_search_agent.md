# 집현전 검색 에이전트: 단일 쿼리의 한계를 넘어서

*6개 학술 데이터베이스를 병렬로 검색하고, 결과를 분석해 부족한 부분을 스스로 보완하는 멀티턴 검색 에이전트를 구축한 이야기.*

작성: 집현전 팀 · 13분 읽기
태그: #검색에이전트 #ReAct #HybridRanking #RaR

---

## 논문 검색이 어려운 이유

논문을 쓰거나 리뷰할 때, 관련 문헌을 빠짐없이 찾는 일은 생각보다 어렵다. "transformer attention mechanism"을 검색하면 핵심 논문은 나온다. 하지만 비슷한 문제를 다른 용어로 접근한 논문, 최근 후속 연구, 관련 벤치마크 논문은 첫 검색에 거의 잡히지 않는다.

원인은 세 가지로 압축된다.

- **용어 불일치**: 같은 개념이 `self-attention`과 `scaled dot-product attention`처럼 다르게 표현된다. 한국어 검색에서는 상황이 더 심각하다.
- **데이터베이스 편향**: arXiv는 CS/ML에 강하지만 생의학은 약하고, Google Scholar는 고인용 논문에 강하지만 최신 프리프린트에 느리다. 한 곳만 보면 반드시 빠뜨린다.
- **단일 검색의 커버리지 한계**: 아무리 좋은 쿼리라도 한 번으로 주제 공간 전체를 커버하기 어렵다. 서베이 논문과 방법론 논문은 다른 키워드로 찾아야 한다.

우리는 [집현전(jiphyeonjeon.kr)](https://jiphyeonjeon.kr) 서비스의 검색 인프라를 점진적으로 발전시키며 이 문제를 풀어왔다. 이 글은 그 과정에서 무엇이 실패했고, 무엇이 작동했는지 솔직하게 정리한 기록이다.

---

## 첫 번째 파이프라인: 6소스 병렬 검색



<div style="margin:24px 0;text-align:center;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 280" style="width:100%;max-width:960px;height:auto" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif">
  <defs>
    <marker id="arch_arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#6b7280"/>
    </marker>
  </defs>

  <rect width="960" height="280" fill="#0f0f0f" rx="12"/>

  <text x="480" y="30" text-anchor="middle" fill="#f3f4f6" font-size="14" font-weight="700" letter-spacing="0.3">검색 에이전트 파이프라인 아키텍처</text>

  <!-- ===== ROW 1: User Query → QueryAnalyzer → 6소스 병렬 검색 → 중복 제거 ===== -->

  <rect x="20" y="50" width="170" height="62" rx="8" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>
  <text x="105" y="76" text-anchor="middle" fill="#f3f4f6" font-size="13" font-weight="700">User Query</text>
  <text x="105" y="95" text-anchor="middle" fill="#9ca3af" font-size="11">자연어 입력</text>

  <line x1="190" y1="81" x2="218" y2="81" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arch_arrow)"/>

  <rect x="220" y="50" width="210" height="62" rx="8" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>
  <text x="325" y="76" text-anchor="middle" fill="#f3f4f6" font-size="13" font-weight="700">QueryAnalyzer</text>
  <text x="325" y="95" text-anchor="middle" fill="#9ca3af" font-size="11">Intent 분류 + 쿼리 개선</text>

  <line x1="430" y1="81" x2="458" y2="81" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arch_arrow)"/>

  <rect x="460" y="50" width="230" height="62" rx="8" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>
  <text x="575" y="76" text-anchor="middle" fill="#f3f4f6" font-size="13" font-weight="700">6소스 병렬 검색</text>
  <text x="575" y="95" text-anchor="middle" fill="#9ca3af" font-size="11">arXiv · Scholar · OpenAlex · DBLP</text>

  <line x1="690" y1="81" x2="718" y2="81" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arch_arrow)"/>

  <rect x="720" y="50" width="220" height="62" rx="8" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>
  <text x="830" y="76" text-anchor="middle" fill="#f3f4f6" font-size="13" font-weight="700">중복 제거</text>
  <text x="830" y="95" text-anchor="middle" fill="#9ca3af" font-size="11">DOI · 제목 · Jaccard · 임베딩</text>

  <!-- Vertical arrow row1→row2 -->
  <line x1="920" y1="112" x2="920" y2="148" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arch_arrow)"/>

  <!-- Divider -->
  <line x1="20" y1="140" x2="940" y2="140" stroke="#1f2937" stroke-width="1"/>

  <!-- ===== ROW 2: HybridRanker ← ReAct Agent ← Rubric 평가 ← Results ===== -->

  <rect x="720" y="150" width="220" height="62" rx="8" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>
  <text x="830" y="176" text-anchor="middle" fill="#f3f4f6" font-size="13" font-weight="700">HybridRanker</text>
  <text x="830" y="195" text-anchor="middle" fill="#9ca3af" font-size="11">BM25 + Semantic + RRF</text>

  <line x1="720" y1="181" x2="692" y2="181" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arch_arrow)"/>

  <rect x="460" y="150" width="230" height="62" rx="8" fill="#181818" stroke="#a5b4fc" stroke-width="2"/>
  <text x="575" y="176" text-anchor="middle" fill="#a5b4fc" font-size="13" font-weight="700">ReAct Agent</text>
  <text x="575" y="195" text-anchor="middle" fill="#9ca3af" font-size="11">멀티턴 반복 검색 (예산 기반)</text>

  <line x1="460" y1="181" x2="432" y2="181" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arch_arrow)"/>

  <rect x="220" y="150" width="210" height="62" rx="8" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>
  <text x="325" y="176" text-anchor="middle" fill="#f3f4f6" font-size="13" font-weight="700">Rubric 평가</text>
  <text x="325" y="195" text-anchor="middle" fill="#9ca3af" font-size="11">Diversity · Thoroughness · 등</text>

  <line x1="220" y1="181" x2="192" y2="181" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arch_arrow)"/>

  <rect x="20" y="150" width="170" height="62" rx="8" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>
  <text x="105" y="176" text-anchor="middle" fill="#f3f4f6" font-size="13" font-weight="700">Results</text>
  <text x="105" y="195" text-anchor="middle" fill="#9ca3af" font-size="11">최종 순위 논문</text>

  <!-- Row labels -->
  <text x="480" y="44" text-anchor="middle" fill="#6b7280" font-size="9" letter-spacing="1">FORWARD PASS (좌 → 우)</text>
  <text x="480" y="248" text-anchor="middle" fill="#6b7280" font-size="9" letter-spacing="1">EVALUATION (우 → 좌)</text>

  <text x="480" y="268" text-anchor="middle" fill="#6b7280" font-size="9.5">ReAct Agent 강조 = 핵심 처리 단계 · 집현전 Search Agent v2.0</text>
</svg>
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 1. 집현전 검색 에이전트 전체 아키텍처 — QueryAnalyzer부터 RubricEvaluator까지의 파이프라인 흐름</em></p>
</div>
출발 아이디어는 단순했다. "여러 소스를 동시에 검색하면 커버리지가 올라갈 것이다." arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers, OpenAlex Korean -- 6개 데이터베이스를 동시에 호출하고, 결과를 모아 랭킹한다.

### QueryAnalyzer: 쿼리를 이해하는 첫 번째 레이어

<div style="margin:24px 0;text-align:center;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 260" style="width:100%;max-width:960px;height:auto" role="img" aria-label="QueryAnalyzer 쿼리 분석">
  <defs>
    <marker id="analyzer_arr" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#6b7280"/>
    </marker>
    <marker id="analyzer_arr_down" markerWidth="8" markerHeight="6" refX="3" refY="7" orient="auto">
      <polygon points="0 0, 6 0, 3 8" fill="#6b7280"/>
    </marker>
  </defs>

  <!-- Background -->
  <rect id="analyzer_bg" width="960" height="260" fill="#0f0f0f"/>

  <!-- Title -->
  <text id="analyzer_title" x="480" y="26" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="14" font-weight="700" fill="#f3f4f6">QueryAnalyzer — 쿼리 분석 흐름</text>

  <!-- ─── Input Query box  x=30..219, y=42..112 ─── -->
  <rect id="analyzer_input" x="30" y="42" width="190" height="70" rx="8"
    fill="#181818" stroke="#1f2937" stroke-width="1.5"/>
  <text x="125" y="63" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="12" font-weight="700" fill="#f3f4f6">입력 쿼리</text>
  <text x="125" y="81" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#9ca3af">"transformer attention</text>
  <text x="125" y="95" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#9ca3af">mechanism survey"</text>

  <!-- Arrow: Input → Analyzer -->
  <line id="analyzer_arr_in" x1="220" y1="77" x2="285" y2="77"
    stroke="#6b7280" stroke-width="1.5" marker-end="url(#analyzer_arr)"/>

  <!-- ─── QueryAnalyzer box  x=287..672, y=28..148 ─── -->
  <rect id="analyzer_main" x="287" y="28" width="386" height="120" rx="10"
    fill="#181818" stroke="#a5b4fc" stroke-width="2"/>
  <text x="480" y="50" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="14" font-weight="700" fill="#a5b4fc">QueryAnalyzer</text>

  <!-- Three internal field rows -->
  <!-- Intent row -->
  <rect id="analyzer_intent_bg" x="305" y="58" width="350" height="24" rx="5"
    fill="#1f2937" stroke="none"/>
  <text x="321" y="74"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" font-weight="700" fill="#9ca3af">intent</text>
  <text x="380" y="74"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#f3f4f6">"find_survey"</text>
  <text x="540" y="74"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#6b7280">( find_survey | find_paper | compare | explain )</text>

  <!-- Keywords row -->
  <rect id="analyzer_kw_bg" x="305" y="87" width="350" height="24" rx="5"
    fill="#1f2937" stroke="none"/>
  <text x="321" y="103"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" font-weight="700" fill="#9ca3af">keywords</text>
  <text x="390" y="103"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#f3f4f6">["transformer", "attention", "survey"]</text>

  <!-- Confidence row -->
  <rect id="analyzer_conf_bg" x="305" y="116" width="350" height="24" rx="5"
    fill="#1f2937" stroke="none"/>
  <text x="321" y="132"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" font-weight="700" fill="#9ca3af">confidence</text>
  <text x="399" y="132"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="12" font-weight="700" fill="#22c55e">0.92</text>
  <text x="432" y="132"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#6b7280">&#x2265; 0.8 threshold</text>

  <!-- ─── Arrow: Analyzer bottom → decision diamond ─── -->
  <!-- Analyzer bottom center: x=480, y=148 -->
  <line id="analyzer_arr_down" x1="480" y1="148" x2="480" y2="172"
    stroke="#6b7280" stroke-width="1.5" marker-end="url(#analyzer_arr_down)"/>

  <!-- ─── Decision diamond  center: 480,183 ─── -->
  <polygon id="analyzer_diamond" points="480,165 520,183 480,201 440,183"
    fill="#181818" stroke="#1f2937" stroke-width="1.5"/>
  <text x="480" y="187" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="9" font-weight="700" fill="#9ca3af">conf &#x2265; 0.8?</text>

  <!-- ─── Branch left: improved_query  x=30..249 ─── -->
  <!-- Arrow: diamond left → improved box -->
  <line id="analyzer_arr_yes" x1="440" y1="183" x2="252" y2="183"
    stroke="#22c55e" stroke-width="1.5" marker-end="url(#analyzer_arr)"/>
  <text x="380" y="177"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" font-weight="700" fill="#22c55e">YES</text>

  <rect id="analyzer_improved" x="30" y="158" width="220" height="50" rx="8"
    fill="#181818" stroke="#22c55e" stroke-width="1.5"/>
  <text x="140" y="178" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="12" font-weight="700" fill="#22c55e">improved_query</text>
  <text x="140" y="196" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#9ca3af">LLM 개선 쿼리 사용</text>

  <!-- ─── Branch right: 원본 유지  x=710..929 ─── -->
  <!-- Arrow: diamond right → original box -->
  <line id="analyzer_arr_no" x1="520" y1="183" x2="708" y2="183"
    stroke="#9ca3af" stroke-width="1.5" marker-end="url(#analyzer_arr)"/>
  <text x="578" y="177"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" font-weight="700" fill="#9ca3af">NO</text>

  <rect id="analyzer_original" x="710" y="158" width="218" height="50" rx="8"
    fill="#181818" stroke="#6b7280" stroke-width="1.5"/>
  <text x="819" y="178" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="12" font-weight="700" fill="#9ca3af">원본 유지</text>
  <text x="819" y="196" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#6b7280">입력 쿼리 그대로 전달</text>

  <!-- ─── Both branches merge → Search Engine ─── -->
  <!-- Left branch down arrow -->
  <line x1="140" y1="208" x2="140" y2="230" stroke="#6b7280" stroke-width="1.5" marker-end="url(#analyzer_arr_down)"/>
  <!-- Right branch down arrow -->
  <line x1="819" y1="208" x2="819" y2="230" stroke="#6b7280" stroke-width="1.5" marker-end="url(#analyzer_arr_down)"/>

  <!-- Merge line -->
  <line x1="140" y1="238" x2="819" y2="238" stroke="#6b7280" stroke-width="1" stroke-dasharray="4 3"/>
  <line x1="480" y1="238" x2="480" y2="251" stroke="#6b7280" stroke-width="1.5" marker-end="url(#analyzer_arr_down)"/>

  <!-- Final output label -->
  <rect id="analyzer_search" x="355" y="246" width="250" height="0" rx="6" fill="none"/>
  <text x="480" y="258" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#6b7280">&#x2192; 6소스 병렬 검색으로 전달</text>

  <!-- ─── Bottom caption ─── -->
  <line x1="30" y1="250" x2="928" y2="250" stroke="#1f2937" stroke-width="1"/>
  <text x="480" y="257" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="9" fill="#6b7280">Figure B — QueryAnalyzer: Intent · Keywords · Confidence 분석 후 confidence &#x2265; 0.8 기준으로 쿼리 개선 여부 결정</text>
</svg>
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 5. QueryAnalyzer — 쿼리 분석 및 confidence 기반 개선 과정</em></p>
</div>


검색에 앞서 `QueryAnalyzer`가 사용자의 의도를 파악한다. `paper_search`, `topic_exploration`, `method_search`, `survey` 등 8가지 intent로 분류하며, 분류는 `gpt-4o-mini`에 위임하고 결과를 캐싱해 반복 호출 비용을 줄인다. LLM을 쓸 수 없을 때는 키워드 규칙 기반 fallback이 동작한다.

분석 결과에는 `improved_query`도 포함되는데, 여기서 원칙은 보수적이다. 오타 수정, 약어 확장 정도만 허용한다. LLM이 원래 의도에 없던 컨텍스트를 추가해 검색 품질이 오히려 떨어지는 상황을 여러 번 경험했기 때문이다.

그래서 이중 guardrail을 유지한다. 프롬프트 수준에서 쿼리 길이를 원본의 1.5배 이내로 제한하고, 코드 수준에서는 confidence가 낮거나 원본과 어간 겹침이 50% 미만이면 개선 쿼리를 폐기한다.

### 하이브리드 랭킹: BM25 + Semantic + Citations + Recency

<div style="margin:24px 0;text-align:center;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 320" style="width:100%;max-width:960px;height:auto" role="img" aria-label="HybridRanker 4신호 결합">
  <defs>
    <marker id="ranker_arr" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#6b7280"/>
    </marker>
  </defs>

  <!-- Background -->
  <rect id="ranker_bg" width="960" height="320" fill="#0f0f0f"/>

  <!-- Title -->
  <text id="ranker_title" x="480" y="28" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="14" font-weight="700" fill="#f3f4f6">HybridRanker — 4신호 결합</text>

  <!-- ─── Signal 1: BM25  y=44..100 ─── -->
  <rect id="ranker_sig_bm25" x="30" y="44" width="230" height="56" rx="8"
    fill="#181818" stroke="#1f2937" stroke-width="1.5"/>
  <text x="50" y="65"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="13" font-weight="700" fill="#f3f4f6">BM25</text>
  <text x="50" y="82"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#9ca3af">키워드 기반 희소 검색</text>
  <text x="50" y="96"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#6b7280">term freq · IDF · field norm</text>

  <!-- ─── Signal 2: Semantic / HyDE  y=111..167 ─── -->
  <rect id="ranker_sig_semantic" x="30" y="111" width="230" height="56" rx="8"
    fill="#181818" stroke="#1f2937" stroke-width="1.5"/>
  <text x="50" y="132"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="13" font-weight="700" fill="#f3f4f6">Semantic / HyDE</text>
  <text x="50" y="149"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#9ca3af">밀집 벡터 코사인 유사도</text>
  <text x="50" y="163"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#6b7280">가상 문서 생성 후 임베딩</text>

  <!-- ─── Signal 3: Citations  y=178..234 ─── -->
  <rect id="ranker_sig_citations" x="30" y="178" width="230" height="56" rx="8"
    fill="#181818" stroke="#1f2937" stroke-width="1.5"/>
  <text x="50" y="199"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="13" font-weight="700" fill="#f3f4f6">Citations</text>
  <text x="50" y="216"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#9ca3af">인용 수 기반 중요도</text>
  <text x="50" y="230"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#6b7280">log(1 + citations) 정규화</text>

  <!-- ─── Signal 4: Recency  y=245..301 ─── -->
  <rect id="ranker_sig_recency" x="30" y="245" width="230" height="56" rx="8"
    fill="#181818" stroke="#1f2937" stroke-width="1.5"/>
  <text x="50" y="266"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="13" font-weight="700" fill="#f3f4f6">Recency</text>
  <text x="50" y="283"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#9ca3af">출판 연도 최신성 가중치</text>
  <text x="50" y="297"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#6b7280">exp(−λ · age_years)</text>

  <!-- ─── Converging arrows: signal centers → RRF left ─── -->
  <!-- BM25 center-y = 44+28 = 72 -->
  <line id="ranker_arr_bm25"      x1="260" y1="72"  x2="353" y2="152" stroke="#6b7280" stroke-width="1.5" marker-end="url(#ranker_arr)"/>
  <!-- Semantic center-y = 111+28 = 139 -->
  <line id="ranker_arr_semantic"  x1="260" y1="139" x2="353" y2="163" stroke="#6b7280" stroke-width="1.5" marker-end="url(#ranker_arr)"/>
  <!-- Citations center-y = 178+28 = 206 -->
  <line id="ranker_arr_citations" x1="260" y1="206" x2="353" y2="178" stroke="#6b7280" stroke-width="1.5" marker-end="url(#ranker_arr)"/>
  <!-- Recency center-y = 245+28 = 273 -->
  <line id="ranker_arr_recency"   x1="260" y1="273" x2="353" y2="187" stroke="#6b7280" stroke-width="1.5" marker-end="url(#ranker_arr)"/>

  <!-- ─── RRF box  x=355..604, y=118..234 ─── -->
  <rect id="ranker_rrf" x="355" y="118" width="250" height="116" rx="10"
    fill="#181818" stroke="#a5b4fc" stroke-width="2"/>
  <text x="480" y="142" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="14" font-weight="700" fill="#a5b4fc">RRF</text>
  <text x="480" y="159" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="11" fill="#9ca3af">Reciprocal Rank Fusion</text>
  <text x="480" y="185" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="13" font-weight="700" fill="#f3f4f6">score(d) = &#x2211;&#x1D456; 1/(k+rank&#x1D456;)</text>
  <text x="480" y="203" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#6b7280">k = 60  (기본값)</text>
  <text x="480" y="222" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="10" fill="#6b7280">순위만 사용 → 점수 스케일 무관</text>

  <!-- ─── Arrow RRF → Final Rank ─── -->
  <line id="ranker_arr_out" x1="605" y1="176" x2="670" y2="176"
    stroke="#6b7280" stroke-width="1.5" marker-end="url(#ranker_arr)"/>

  <!-- ─── Final Rank box  x=672..927, y=118..234 ─── -->
  <rect id="ranker_output" x="672" y="118" width="256" height="116" rx="10"
    fill="#181818" stroke="#1f2937" stroke-width="1.5"/>
  <text x="800" y="142" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="14" font-weight="700" fill="#f3f4f6">최종 순위</text>
  <text x="800" y="159" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="11" fill="#9ca3af">상위 N개 논문 반환</text>
  <!-- Rank list items -->
  <text x="692" y="182"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="11" font-weight="700" fill="#22c55e">#1</text>
  <text x="716" y="182"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="11" fill="#f3f4f6">Attention Is All You Need</text>
  <text x="692" y="200"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="11" font-weight="700" fill="#a5b4fc">#2</text>
  <text x="716" y="200"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="11" fill="#f3f4f6">FlashAttention-2</text>
  <text x="692" y="218"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="11" fill="#6b7280">#3</text>
  <text x="716" y="218"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="11" fill="#6b7280">Efficient Transformers</text>

  <!-- ─── Bottom caption ─── -->
  <line x1="30" y1="311" x2="928" y2="311" stroke="#1f2937" stroke-width="1"/>
  <text x="480" y="317" text-anchor="middle"
    font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font-size="9" fill="#6b7280">Figure A — BM25 · Semantic/HyDE · Citations · Recency 4신호를 Reciprocal Rank Fusion으로 결합</text>
</svg>
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 4. HybridRanker — 4가지 신호를 RRF로 결합하여 최종 순위 산출</em></p>
</div>


6개 소스에서 수집된 논문은 중복 제거를 거쳐 `HybridRanker`로 넘어간다. 랭킹은 4가지 신호를 조합한다.

- **BM25 (sparse)**: 키워드 매칭. 제목에 가중을 둔다.
- **Semantic (dense)**: 코사인 유사도. **HyDE**가 활성화되면 LLM이 가상 초록을 생성해 쿼리 벡터를 보강한다.
- **Citations**: log 정규화로 고인용 논문의 지배를 억제한다.
- **Recency**: 연도 기반 계단식 점수 (1년 이내 1.0 ~ 10년 초과 0.1).

이 신호를 통합하는 기본 방식은 **RRF (Reciprocal Rank Fusion)** 다. 각 신호로 독립 정렬한 뒤 순위 역수를 합산하므로, 특정 신호에 점수가 몰리지 않고 여러 관점에서 고르게 높은 논문이 우선된다.

Intent별로 가중치를 달리하는 weighted-sum 방식도 지원한다. 예를 들어 `latest_research`는 최신성(0.50)을, `survey`는 인용 수(0.40)를, `method_search`는 의미 유사도(0.50)를 최우선한다.

### 4단계 중복 제거

다중 소스 검색에서 중복은 불가피하다. 같은 논문이 arXiv에도, OpenAlex에도 있다. 이를 4단계로 제거한다: DOI 완전 일치 -> 정규화 제목 완전 일치 -> 퍼지 제목 매칭(Jaccard 0.85) -> 임베딩 코사인 유사도(0.90). 중복으로 판정되면 메타데이터가 풍부한 쪽을 대표로 삼고 나머지 필드를 병합한다.

이 파이프라인으로 커버리지는 확실히 올라갔다. 하지만 프로덕션에 올린 뒤, 예상 못한 한계가 드러나기 시작했다.

---

## 무엇이 부족했는가

### 한 번의 검색으로는 충분하지 않다

"transformer 효율화 방법"을 검색하면 Attention 관련 논문은 잘 나왔다. 하지만 같은 주제를 "computational efficiency neural network"이나 "low-rank approximation attention"으로 검색하면 결과가 상당히 달랐다. 단일 쿼리는 자신의 관점에 갇혀 있었다.

연구자가 실제로 하는 행동을 떠올려 보자. 첫 검색 결과를 훑고 "이 방향은 많이 나왔는데, 저 방향이 빠졌군" 판단한 후 다시 검색한다. 우리 시스템에는 이 **반성적 재검색**이 없었다.

### 타임아웃 구조의 문제

초기 파이프라인은 120초 타임아웃을 전체 파이프라인이 공유했다. 6개 소스 병렬 검색에 40-50초, LLM 관련성 필터에 최대 45초 -- 이 둘이 겹치면 타임아웃이 빈번했다.

해결책은 검색 단계(60초)와 필터 단계(45초)의 타임아웃을 분리하는 것이었다. 필터가 타임아웃되더라도 필터링 없는 원본 결과를 반환하도록 graceful degradation을 적용했고, 타임아웃 발생 빈도가 크게 줄었다.

### Recall 측정 부재

가장 불안한 점은 얼마나 많은 논문을 빠뜨리고 있는지 모른다는 것이었다. 정밀도(precision)는 "찾은 논문이 관련 있는가"를 보여주지만, 재현율(recall)은 "관련 논문 중 얼마나 찾았는가"를 본다. 못 찾은 논문은 존재 자체를 모르기 때문에, recall 문제는 사용자에게 보이지 않는다.

---

## ArxivQA에서 배운 것

이 세 가지 한계를 어떻게 극복할까 고민하던 중, ArxivQA 논문(arxiv.org/abs/2309.01536)이 관점 전환을 제공했다. 핵심 질문은 이것이었다: 검색 에이전트를 강화학습으로 학습시킬 때, 어떤 reward를 주어야 하는가?

**outcome reward는 불안정했다.** "최종 답이 맞으면 +1, 틀리면 0"이라는 단순한 보상은 멀티턴 검색에서 문제가 됐다. 올바른 과정을 거쳤어도 마지막 답이 살짝 다르면 보상을 받지 못하고, 엉뚱한 방법으로 우연히 맞아도 보상을 받았다.

**RaR (Rubric-as-Reward)는 달랐다.** 결과가 아니라 과정을 평가하는 루브릭 기반 reward를 도입하자, 에이전트가 체계적인 검색 전략을 학습하기 시작했다. 검색 결과 세트를 다양성, 포괄성, 사려깊음, 관련성의 4차원으로 평가하는 것이 핵심이다.

교훈은 명확했다: **결과만 보지 말고, 검색 과정을 평가하라.** 그리고 RL fine-tuning 없이도 프롬프트 엔지니어링으로 멀티턴 루프를 구현하고, RaR rubric을 inference-time 평가에 사용할 수 있다는 것을 깨달았다.

---

## 우리의 접근: ReAct 멀티턴 검색 에이전트

그래서 만든 것이 `ReActSearchAgent`다. Search-R1의 `search → result → think → search` 루프를 RL fine-tuning 없이 프롬프트 엔지니어링으로 재현했다.

### 도구 설계

에이전트가 사용하는 도구는 `keyword_search`(arXiv), `semantic_search`(OpenAlex), `dblp_search`(DBLP), `read_abstract`(arXiv ID 직접 조회)의 4가지다. 새로운 인프라가 아니라 기존 `SearchAgent`의 검색기를 async executor로 래핑한 것이므로, 기존 자산 위에 에이전트 레이어만 얹은 셈이다.

### 멀티턴 루프



<div style="margin:24px 0;text-align:center;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 520" style="width:100%;max-width:960px;height:auto" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif">
  <defs>
    <marker id="react_arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#6b7280"/>
    </marker>
  </defs>

  <!-- Background -->
  <rect width="600" height="520" fill="#0f0f0f" rx="12"/>

  <!-- Title -->
  <text x="300" y="30" text-anchor="middle" fill="#f3f4f6" font-size="14" font-weight="700">멀티턴 ReAct 검색 루프</text>
  <text x="300" y="50" text-anchor="middle" fill="#9ca3af" font-size="11">예산 기반 반복 검색 · LLM Gap 분석 · 누적 결과 관리</text>

  <!-- ===== CARD 1: Turn 1 ===== -->
  <rect x="24" y="64" width="552" height="118" rx="10" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>

  <!-- Turn label + time badge -->
  <text x="44" y="90" fill="#a5b4fc" font-size="13" font-weight="700">Turn 1</text>
  <rect x="108" y="76" width="58" height="22" rx="6" fill="#181818" stroke="#6b7280" stroke-width="1"/>
  <text x="137" y="91" text-anchor="middle" fill="#6b7280" font-size="11">40s</text>
  <!-- time badge right side -->
  <rect x="490" y="76" width="66" height="22" rx="6" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="523" y="91" text-anchor="middle" fill="#6b7280" font-size="10">예산 40s</text>

  <!-- Search results -->
  <text x="44" y="116" fill="#9ca3af" font-size="11">arXiv:</text>
  <text x="90" y="116" fill="#f3f4f6" font-size="11" font-weight="600">8편</text>
  <text x="130" y="116" fill="#6b7280" font-size="11">+</text>
  <text x="146" y="116" fill="#9ca3af" font-size="11">OpenAlex:</text>
  <text x="216" y="116" fill="#f3f4f6" font-size="11" font-weight="600">7편</text>
  <text x="254" y="116" fill="#6b7280" font-size="11">=</text>

  <!-- Result badge -->
  <rect x="270" y="104" width="68" height="22" rx="6" fill="#181818" stroke="#a5b4fc" stroke-width="1.5"/>
  <text x="304" y="119" text-anchor="middle" fill="#a5b4fc" font-size="11" font-weight="700">15편 수집</text>

  <!-- Sub-description -->
  <text x="44" y="154" fill="#6b7280" font-size="10.5">keyword_search (arXiv) · semantic_search (OpenAlex) 병렬 실행</text>

  <!-- ===== Arrow 1 ===== -->
  <line x1="300" y1="182" x2="300" y2="208" stroke="#6b7280" stroke-width="1.5" marker-end="url(#react_arrow)"/>

  <!-- ===== CARD 2: Gap Analysis ===== -->
  <rect x="24" y="212" width="552" height="100" rx="10" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>

  <!-- Gap label + time badge -->
  <text x="44" y="238" fill="#f3f4f6" font-size="13" font-weight="700">Gap Analysis</text>
  <rect x="158" y="224" width="58" height="22" rx="6" fill="#181818" stroke="#6b7280" stroke-width="1"/>
  <text x="187" y="239" text-anchor="middle" fill="#6b7280" font-size="11">20s</text>
  <!-- LLM tag -->
  <rect x="490" y="224" width="42" height="22" rx="6" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="511" y="239" text-anchor="middle" fill="#9ca3af" font-size="10">LLM</text>

  <!-- Gap content -->
  <text x="44" y="264" fill="#9ca3af" font-size="11">발견:</text>
  <text x="82" y="264" fill="#f3f4f6" font-size="11">"linear attention 관련 방법론이 부족합니다"</text>

  <!-- next_query -->
  <text x="44" y="286" fill="#9ca3af" font-size="11">next_query:</text>
  <rect x="120" y="274" width="300" height="22" rx="5" fill="#181818" stroke="#a5b4fc" stroke-width="1"/>
  <text x="130" y="289" fill="#a5b4fc" font-size="11">"linear attention FlashAttn efficient"</text>

  <!-- ===== Arrow 2 ===== -->
  <line x1="300" y1="312" x2="300" y2="338" stroke="#6b7280" stroke-width="1.5" marker-end="url(#react_arrow)"/>

  <!-- ===== CARD 3: Turn 2 ===== -->
  <rect x="24" y="342" width="552" height="128" rx="10" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>

  <!-- Turn label + time badge -->
  <text x="44" y="368" fill="#a5b4fc" font-size="13" font-weight="700">Turn 2</text>
  <rect x="108" y="354" width="58" height="22" rx="6" fill="#181818" stroke="#6b7280" stroke-width="1"/>
  <text x="137" y="369" text-anchor="middle" fill="#6b7280" font-size="11">30s</text>
  <!-- time badge right side -->
  <rect x="490" y="354" width="66" height="22" rx="6" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="523" y="369" text-anchor="middle" fill="#6b7280" font-size="10">예산 30s</text>

  <!-- Search results -->
  <text x="44" y="394" fill="#9ca3af" font-size="11">OpenAlex:</text>
  <text x="114" y="394" fill="#f3f4f6" font-size="11" font-weight="600">6편</text>
  <text x="148" y="394" fill="#6b7280" font-size="11">+</text>
  <text x="164" y="394" fill="#9ca3af" font-size="11">DBLP:</text>
  <text x="204" y="394" fill="#f3f4f6" font-size="11" font-weight="600">4편</text>

  <!-- Dedup arrow -->
  <text x="244" y="394" fill="#6b7280" font-size="11">→ 중복 제거 →</text>

  <!-- Result badge -->
  <rect x="344" y="382" width="68" height="22" rx="6" fill="#181818" stroke="#a5b4fc" stroke-width="1.5"/>
  <text x="378" y="397" text-anchor="middle" fill="#a5b4fc" font-size="11" font-weight="700">18편 확정</text>

  <!-- Accumulation line -->
  <line x1="44" y1="410" x2="556" y2="410" stroke="#1f2937" stroke-width="1"/>

  <!-- Final result row -->
  <text x="44" y="432" fill="#9ca3af" font-size="11">누적 총계:</text>
  <text x="114" y="432" fill="#f3f4f6" font-size="11" font-weight="700">18편</text>
  <text x="156" y="432" fill="#6b7280" font-size="11">(Turn 1: 15편 → 중복 포함 25편 → Jaccard + 임베딩 제거)</text>

  <!-- Time badges row -->
  <rect x="44" y="444" width="80" height="20" rx="5" fill="#181818" stroke="#1f2937" stroke-width="1"/>
  <text x="84" y="458" text-anchor="middle" fill="#9ca3af" font-size="10">총 71초</text>
  <rect x="134" y="444" width="80" height="20" rx="5" fill="#181818" stroke="#1f2937" stroke-width="1"/>
  <text x="174" y="458" text-anchor="middle" fill="#9ca3af" font-size="10">2턴 완료</text>
  <!-- Pass badge -->
  <rect x="460" y="444" width="96" height="20" rx="5" fill="#181818" stroke="#22c55e" stroke-width="1"/>
  <text x="508" y="458" text-anchor="middle" fill="#22c55e" font-size="10" font-weight="700">PASS (0.78 &gt;= 0.70)</text>

  <!-- Footer note -->
  <text x="300" y="508" text-anchor="middle" fill="#6b7280" font-size="9.5">* coverage_score &lt; 0.70 이면 Turn 3 (20s) 추가 실행</text>
</svg>
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 2. ReAct 멀티턴 검색 루프 — Turn 1 초기 탐색 → Gap Analysis → Turn 2 보완 검색</em></p>
</div>
전체 타임아웃은 `_TOTAL_TIMEOUT_SECONDS = 120`초. 최대 3턴이 기본값이다.

**Turn 1 — 다양화 쿼리로 초기 탐색**

먼저 `_build_initial_queries`가 `QueryAnalyzer`의 분석 결과를 조합해 3~5개의 초기 쿼리 후보를 만든다. 그리고 단어 수준 Jaccard 유사도로 중복을 걸러낸다 -- 유사도 0.5 이상이면 제거한다. "transformer attention mechanism"과 "attention mechanism transformer"는 하나만 남고, "transformer attention"과 "self-supervised pre-training"은 둘 다 살아남는 식이다.

Turn 1에서는 원본 쿼리로 arXiv 키워드 검색(rate limit 때문에 1회만)과 두 번째 다양화 쿼리로 OpenAlex 시맨틱 검색을 병렬 실행한다. 타임아웃은 40초.

**갭 분석 — LLM이 무엇이 부족한지 분석한다**

Turn 1이 끝나면, 수집된 논문 목록(제목 + 연도)을 gpt-4o-mini에 제공하고 묻는다: "어떤 유형의 논문이 빠져 있는가? 그 gap을 채울 쿼리를 제안하라." LLM은 부족한 영역(`missing`)과 보완 쿼리(`next_query`)를 JSON으로 반환한다.

타임아웃(20초) 내에 응답이 오지 않으면 fallback이 동작한다 -- 초기 쿼리 중 아직 사용하지 않은 것을 다음 쿼리로 사용한다.

**Turn 2 — 보완 검색, arXiv 제외**

갭 분석이 제안한 쿼리로 OpenAlex + DBLP를 병렬 검색한다. arXiv는 rate limit(3.5초 간격) 때문에 Turn 1에서만 호출하고, Turn 2부터는 제외한다. Turn 2+ 타임아웃은 30초.

**조기 종료 조건**

- 누적 논문 수가 `max_results * 1.5`를 초과하면 "충분하다" 판단
- LLM 갭 분석이 `is_sufficient: true` 반환
- 전체 120초 타임아웃 도달
- LLM 갭 분석 시간이 10초 미만 남은 경우

### 난이도 기반 전략 분기

모든 쿼리에 3턴을 돌리면 불필요하게 느리다. `classify_difficulty`가 confidence, intent, 키워드 수를 보고 난이도를 3단계로 분류한다.

- **Easy** (confidence 높고 단순 intent): 단일 검색으로 충분
- **Medium** (일반적 경우): 다양화 쿼리 3개, 2턴
- **Hard** (탐색형/서베이/비교 intent): 3턴 전체 실행

현재 `/api/deep-search`는 난이도와 무관하게 항상 3턴을 실행하고, 난이도는 메타데이터로 기록만 한다. 난이도별 전략 분기는 향후 과제다.

---

## Rubric 기반 결과 평가 (RaR-Implicit)

검색이 끝나면 `RubricEvaluator`가 결과 세트 전체를 평가한다. 개별 논문이 아니라, **집합으로서의 품질**을 본다.

### 4차원 루브릭



<div style="margin:24px 0;text-align:center;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 260" style="width:100%;max-width:960px;height:auto" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif">

  <!-- Background -->
  <rect width="600" height="260" fill="#0f0f0f" rx="12"/>

  <!-- Title -->
  <text x="300" y="28" text-anchor="middle" fill="#f3f4f6" font-size="14" font-weight="700">RaR Rubric 평가 — 4차원 품질 검증</text>
  <text x="300" y="46" text-anchor="middle" fill="#9ca3af" font-size="11">Reflection-after-Retrieval · 검색 결과 자가 평가</text>

  <!-- ===== Bar chart area ===== -->
  <!-- Labels: x=24~174, bars: x=178, bar max-width=330, score: x after bar, total row: y step 38 -->

  <!-- Row 1: Diversity 3/5 = 60% = 198px -->
  <text x="170" y="78" text-anchor="end" fill="#f3f4f6" font-size="12.5" font-weight="600">Diversity</text>
  <text x="170" y="93" text-anchor="end" fill="#9ca3af" font-size="10">다양성</text>
  <!-- bar track -->
  <rect x="178" y="66" width="330" height="26" rx="5" fill="#1f2937"/>
  <!-- bar fill: 3/5 = 60% = 198px -->
  <rect x="178" y="66" width="198" height="26" rx="5" fill="#a5b4fc"/>
  <!-- score label -->
  <text x="384" y="84" fill="#f3f4f6" font-size="12" font-weight="700">3 / 5</text>

  <!-- Row 2: Thoroughness 4/5 = 80% = 264px -->
  <text x="170" y="120" text-anchor="end" fill="#f3f4f6" font-size="12.5" font-weight="600">Thoroughness</text>
  <text x="170" y="135" text-anchor="end" fill="#9ca3af" font-size="10">철저함</text>
  <rect x="178" y="108" width="330" height="26" rx="5" fill="#1f2937"/>
  <rect x="178" y="108" width="264" height="26" rx="5" fill="#a5b4fc"/>
  <text x="450" y="126" fill="#f3f4f6" font-size="12" font-weight="700">4 / 5</text>

  <!-- Row 3: Thoughtfulness 4/5 = 80% = 264px -->
  <text x="170" y="162" text-anchor="end" fill="#f3f4f6" font-size="12.5" font-weight="600">Thoughtfulness</text>
  <text x="170" y="177" text-anchor="end" fill="#9ca3af" font-size="10">사려깊음</text>
  <rect x="178" y="150" width="330" height="26" rx="5" fill="#1f2937"/>
  <rect x="178" y="150" width="264" height="26" rx="5" fill="#a5b4fc"/>
  <text x="450" y="168" fill="#f3f4f6" font-size="12" font-weight="700">4 / 5</text>

  <!-- Row 4: Relevance 5/5 = 100% = 330px -->
  <text x="170" y="204" text-anchor="end" fill="#f3f4f6" font-size="12.5" font-weight="600">Relevance</text>
  <text x="170" y="219" text-anchor="end" fill="#9ca3af" font-size="10">관련성</text>
  <rect x="178" y="192" width="330" height="26" rx="5" fill="#1f2937"/>
  <rect x="178" y="192" width="330" height="26" rx="5" fill="#a5b4fc"/>
  <text x="516" y="210" fill="#f3f4f6" font-size="12" font-weight="700">5 / 5</text>

  <!-- ===== Overall score section ===== -->
  <rect x="24" y="230" width="552" height="20" rx="5" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>

  <!-- Overall score track -->
  <rect x="178" y="234" width="330" height="12" rx="4" fill="#1f2937"/>
  <!-- 72.8% of 330 = 240px -->
  <rect x="178" y="234" width="240" height="12" rx="4" fill="#6366f1"/>
  <!-- Threshold marker: 60% of 330 = 198px, x = 178+198 = 376 -->
  <line x1="376" y1="230" x2="376" y2="250" stroke="#9ca3af" stroke-width="1.5"/>
  <text x="376" y="228" text-anchor="middle" fill="#9ca3af" font-size="8">0.60</text>

  <!-- Score label -->
  <text x="44" y="244" fill="#9ca3af" font-size="11">Overall:</text>
  <text x="94" y="244" fill="#a5b4fc" font-size="13" font-weight="700">0.728</text>

  <!-- Pass badge -->
  <rect x="516" y="232" width="48" height="16" rx="4" fill="#181818" stroke="#22c55e" stroke-width="1.5"/>
  <text x="540" y="244" text-anchor="middle" fill="#22c55e" font-size="10" font-weight="700">PASS</text>
</svg>
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 3. RaR-Implicit Rubric 4차원 평가 결과 — method_search intent 기준</em></p>
</div>
- **Diversity (다양성)**: 서로 다른 하위 주제와 방법론을 커버하는가
- **Thoroughness (포괄성)**: 기대되는 주요 측면이 빠짐없이 포함되어 있는가
- **Thoughtfulness (사려깊음)**: 기반 논문, 고임팩트 논문, 미래지향적 논문이 있는가
- **Relevance (관련성)**: 실제로 쿼리 주제를 다루는가

LLM에 최대 15편(제목 + 초록 앞 200자)을 제공하고, 4차원 각 점수(0-5)와 전체 홀리스틱 점수(1-10)를 요청한다.

### 최종 점수 계산

ArxivQA RaR-Implicit에서 영감을 받아, 최종 점수는 홀리스틱 점수(LLM의 전체 직관)에 60%, 가중 차원 합산에 40%를 배분해 산출한다. `overall = 0.6 * holistic_norm + 0.4 * weighted_dim_score` 형태다.

### Intent별 차원 가중치

차원 가중치는 intent에 따라 달라진다. `latest_research`는 관련성(0.5)과 사려깊음(0.3)을, `comparison`은 다양성(0.4)을, `survey`는 포괄성(0.4)을 최우선한다. 검색 의도에 맞는 평가가 가능해진다.

### 충분성 판정

Intent별로 충분성 임계값이 다르다. `survey`는 0.70으로 가장 엄격하고(포괄성이 중요하므로), `paper_search`는 0.55로 비교적 관대하다.

기준에 미달하면 가장 약한 차원(`weakest_dimension`)에 맞춰 보완 쿼리를 자동 생성한다. 예를 들어 다양성이 약하면 "alternative methods approaches"를, 포괄성이 약하면 "survey overview"를 쿼리에 덧붙인다.

---

## 타임아웃 아키텍처

`/api/deep-search`의 실행 흐름과 각 단계의 타임아웃 버짓은 다음과 같다.

```
QueryAnalyzer (10s) -> ReActSearchAgent (120s) -> RubricEvaluator (15s)
                         ├─ Turn 1: arXiv+OpenAlex (40s)
                         ├─ Gap Analysis (20s)
                         ├─ Turn 2: OpenAlex+DBLP (30s)
                         └─ Turn 3 (필요 시, 20s)
```

기본 검색(`/api/search`)도 검색 단계(60초)와 관련성 필터 단계(45초)를 독립 버짓으로 운영한다. 필터가 타임아웃되면 필터링 없는 원본 결과를 반환한다 -- 에러 페이지보다 품질이 약간 낮은 결과가 낫다는 판단이다.

---

## 결과

프로덕션에서 실행한 구체적인 사례를 보자.

### 실행 예시: "efficient transformer attention mechanisms for long sequences"

**Turn 1** (39초): arXiv 키워드 검색 8편 + OpenAlex 시맨틱 검색 7편 = 15편 수집.

**Gap Analysis** (8초): LLM이 "linear attention 방법론"과 "하드웨어 최적화 논문"이 빠져 있다고 판단. 보완 쿼리 `"linear attention approximation FlashAttention hardware"` 제안.

**Turn 2** (22초): OpenAlex 6편 + DBLP 4편 추가 수집. 중복 제거 후 최종 **18편**, 총 71초 소요.

여기서 두 가지 점수가 등장한다. ReAct 루프 내부에서는 **coverage_score**(0.78)로 "다음 턴이 필요한가"를 판단하고, 전체 검색이 끝난 뒤에는 **Rubric 품질 점수**(0.728)로 결과 세트의 학술적 완성도를 평가한다. 전자는 양적 커버리지, 후자는 질적 평가다.

Rubric 평가에서 Relevance 5/5, Thoroughness 4/5, Thoughtfulness 4/5, Diversity 3/5를 받았다. 최종 점수 0.728로 `method_search` 충분성 임계값(0.60)을 초과해 검색을 종료했다. 가장 약한 차원은 Diversity -- 필요하다면 "alternative methods" 방향으로 보완 검색할 수 있다.

단일 검색이었다면 Turn 1의 15편에서 멈췄을 것이다. 멀티턴 덕분에 linear attention과 FlashAttention 계열 논문을 추가로 발굴했다.

---

## 아직 남은 과제

### 검색 에이전트 RL Fine-tuning

지금의 `ReActSearchAgent`는 프롬프트 엔지니어링으로 ArxivQA의 패턴을 모방한 것이지, RL로 학습된 것이 아니다. 다음 단계는 강화학습으로 에이전트를 직접 학습시키는 것이다.

구상 중인 스택은 **Qwen3-8B + GRPO + RaR**이다. Rubric 점수를 process reward로, GRPO로 정책을 업데이트한다. 8B급 모델로 전문 검색 에이전트를 만들 수 있다면 gpt-4o-mini 의존성을 낮출 수 있다.

핵심 난제는 **credit assignment**다. 마지막 Turn에만 rubric을 적용하면 Turn 1, 2의 좋은 결정에 reward가 전달되지 않는다.

### 사용자 피드백 기반 학습

사용자가 특정 논문을 클릭하거나 북마크하면 positive signal이 생긴다. 현재는 수집만 하고 랭킹에 반영하지 않지만, 이를 implicit reward로 활용해 가중치를 온라인 업데이트하는 것이 가능한 방향이다.

다만 클릭 데이터는 노이즈가 크다. 제목이 매력적이어서, 상위에 노출되어서 등 관련성과 무관한 이유로 클릭이 발생한다. 신호를 그대로 쓰면 오히려 품질이 하락할 수 있다.

### 초록 기반 정밀 재랭킹

현재 semantic 점수는 임베딩 유사도 기반이다. Top-20 논문의 초록을 LLM이 직접 읽고 관련성을 판단하는 **Cross-Encoder 재랭킹**을 추가하면 정밀도가 크게 높아질 것으로 예상한다.

비용이 걸림돌이다. 매 검색마다 약 8,000 토큰을 LLM에 입력해야 하므로, 캐싱이나 경량 reranker 모델의 활용이 필요하다.

---

## 열린 질문

시스템을 만들면서 계속 마음에 걸리는 질문들이 있다.

**멀티턴 검색은 언제 수렴하는가?** 현재 종료 조건은 "충분한 논문 수 확보"와 "LLM이 sufficient 판단" 두 가지인데, 둘 다 실질적 커버리지를 보장하지 않는다. 새로 찾은 논문이 기존 결과와 임베딩 공간에서 충분히 멀어질 때까지 탐색하는 novelty-driven 종료 조건을 실험 중이다.

**언어 간 검색 불균형은?** 한국어와 영어 논문이 같은 주제를 다뤄도 임베딩 공간에서 거리가 멀다. 다국어 임베딩 모델이나 번역 기반 쿼리 확장이 필요하다.

**LLM이 LLM을 평가하는 구조는 괜찮은가?** RaR rubric은 유용하지만, 결국 자기 평가다. 사람이 직접 평가한 gold standard 없이는 자기충족적 편향에 빠질 수 있다. 사용자 검색 세션을 분석해 gold standard를 만드는 작업을 시작했지만, 아직 갈 길이 멀다.

---

## 참고문헌

- Yao, S. et al. (2023). *ReAct: Synergizing Reasoning and Acting in Language Models*. ICLR 2023.
- Jin, Z. et al. (2025). *Search-R1: Training LLMs to Reason and Leverage Search Engines with Reinforcement Learning*. arxiv.org/abs/2503.09516.
- Peng, B. et al. (2023). *ArxivQA: Long-form Question Answering on arXiv Papers*. arxiv.org/abs/2309.01536.
- Gao, L. et al. (2023). *Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE)*. ACL 2023.
- Cormack, G.V. et al. (2009). *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*. SIGIR 2009.
