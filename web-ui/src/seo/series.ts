// Ordered blog series (pillar pages). Shared contract with the Python SSR
// builder — keep ids, titles, descriptions, and slug order in byte-sync with
// routers/seo.py::BLOG_SERIES.

export interface BlogSeries {
  title: string;
  description: string;
  slugs: string[];
}

export const BLOG_SERIES: Record<string, BlogSeries> = {
  'jiphyeonjeon-build': {
    title: '집현전 개발 시리즈',
    description:
      '집현전을 만들며 남긴 개발 기록을 시간순으로 읽습니다. '
      + '검색 에이전트에서 출발해 논문 관계 그래프, 자동 하이라이트, 읽기 커리큘럼으로 '
      + '이어집니다. 이어 MCP 도구 확장, 연구자 페르소나 기반 추천, 검색 프롬프트 선택을 '
      + '다루며 논문을 찾는 기능이 읽기와 개인화로 넓어지는 흐름을 살펴봅니다.',
    slugs: [
      'search-agent-beyond-single-query-65bcbe5c30fd',
      'paper-network-graph-hidden-connections-f954b2866fb4',
      'auto-highlight-ai-scholarly-annotation-f6a5ccb4ce6b',
      'curriculum-generator-jiphyeonjeon-9fdf6c688749',
      'jiphyeonjeon-agent-mcp-tool-surface-a7c9e3d4b821',
      'daily-recommendations-research-persona-dailyrec2026',
      'skillopt-search-policy-training-90c0bb4ee568',
    ],
  },
  gnn: {
    title: 'GNN 논문 리뷰 시리즈',
    description:
      '그래프 표현 학습과 그래프 신경망(GNN)의 핵심 논문을 읽는 시리즈입니다. '
      + '노드를 벡터로 표현하는 기초에서 이웃 정보 집계와 새 노드로의 일반화, '
      + '이종 그래프와 예측 설명, 정규화와 공정한 기준선 비교로 이어집니다. '
      + '성능 순위가 아니라 개념을 연결하는 읽기 순서입니다.',
    slugs: [
      'deepwalk-online-learning-social-representations-review-2026',
      'structural-deep-network-embedding-sdne-review-2026',
      'semi-supervised-classification-graph-convolutional-networks-review-2026',
      'graphsage-inductive-representation-learning-large-graphs-review-2026',
      'graph-attention-networks-gat-review-2026',
      'how-powerful-are-graph-neural-networks-gin-review-2026',
      'heterogeneous-graph-neural-network-hetgnn-review-2026',
      'heterogeneous-graph-attention-network-han-review-2026',
      'gnnexplainer-gnn-subgraph-feature-mask-review-2026',
      'explaining-temporal-graph-neural-networks-feature-induced-information-flow-review-2026',
      'graphnorm',
      'classic-gnns-strong-baselines-graph-level-tasks-gnnplus-review-2026',
    ],
  },
  dwe: {
    title: 'DWE 논문 리뷰 시리즈',
    description:
      '단어 의미의 시간적 변화를 추적하는 동적 단어 임베딩의 핵심 논문을 읽습니다. '
      + '변화의 통계적 탐지에서 출발해 시간 구간 사이의 임베딩 정렬과 동적 모델을 살펴보고, '
      + '문맥화 표현과 용법 분석, 체계 비교로 이어집니다. 각 단계에서 무엇을 의미 변화로 '
      + '측정하고 서로 다른 시점의 표현을 어떻게 비교하는지에 초점을 맞춥니다.',
    slugs: [
      'statistically-significant-detection-linguistic-change-review-2026',
      'diachronic-word-embeddings-statistical-laws-semantic-change-review-2026',
      'dynamic-word-embeddings-dsg-review-2026',
      'dynamic-word-embeddings-evolving-semantic-discovery-review-2026',
      'dynamic-bernoulli-embeddings-language-evolution-review-2026',
      'training-temporal-word-embeddings-compass-twec-review-2026',
      'survey-computational-approaches-lexical-semantic-change-review-2026',
      'how-contextual-are-contextualized-word-representations-review-2026',
      'analysing-lexical-semantic-change-contextualised-word-representations-review-2026',
      'dynamic-contextualized-word-embeddings-dcwe-review-2026',
      'contextualised-semantic-shift-detection-survey-review-2026',
      'a-systematic-comparison-contextualized-word-embeddings-lexical-semantic-change',
    ],
  },
  graphrag: {
    title: 'GraphRAG 논문 리뷰 시리즈',
    description:
      'LLM 검색증강생성에 그래프를 결합하는 GraphRAG 계열의 방법론을 '
      + '기초 연구부터 최초 공개 순서로 읽고, 마지막에 종합 평가를 살펴봅니다. '
      + '문서 그래프 탐색과 전역 요약에서 '
      + '연상 기억, 이중 검색, 인과·계층 검색과 다단계 파이프라인으로 이어집니다. '
      + '문서 간 관계를 어떻게 색인하고 무엇을 검색하며, 답변의 근거를 어디까지 '
      + '확인할 수 있는지 비교합니다.',
    slugs: [
      'knowledge-graph-prompting-multi-document-qa',
      'ms-graphrag-global-query-focused-summarization',
      'hipporag-neurobiologically-inspired-long-term-memory',
      'lightrag-dual-level-graph-rag',
      'hipporag2-from-rag-to-memory',
      'causalrag-causal-graph-retrieval',
      'leanrag-semantic-aggregation-hierarchical-retrieval',
      'linearrag-linear-graph-retrieval-augmented-generation',
      'deep-graphrag',
      'causalrag2-hugrag-hierarchical-causal-gating',
      'ragu',
      'rag-vs-graphrag-systematic-evaluation',
    ],
  },
  'graph-causality': {
    title: 'Graph causality 논문 리뷰 시리즈',
    description:
      '그래프와 동역학 시계열에서 인과 구조를 복원하려는 핵심 논문을 '
      + '공개·기초 흐름 순서로 읽습니다. PCM의 간접 인과 구분에서 CIC의 잠재 교란자 '
      + '분해, IC2의 개입 동역학 인과 추정으로 이어집니다. 직접 인과, 간접 인과, '
      + '잠재 교란자를 각 방법이 어떻게 구분하려는지 살펴봅니다.',
    slugs: [
      'pcm-partial-cross-mapping-eliminates-indirect-causal-influences',
      'cic-dynamical-causality-under-invisible-confounders',
      'ic2-interventional-dynamical-causality-under-latent-confounders',
    ],
  },
  'agent-skills': {
    title: '가중치를 바꾸지 않는 에이전트 개선',
    description:
      '모델 가중치 대신 경험·스킬·도구를 개선해 다음 작업에 재사용하는 방법을 읽습니다. '
      + '교사의 실행 경험을 외부 자산으로 표현하는 데서 출발해 스킬 문서 수정, '
      + '실패 근거의 축적, 절차 그래프, 스킬 선택과 재사용 평가로 이어집니다. '
      + '서로 다른 자산과 평가 조건을 구분하며 모델 가중치 학습과 혼동하지 않습니다.',
    slugs: [
      'agent-memory-distillation',
      'skillopt-executive-strategy-self-evolving-agent-skills-deep-review-2026',
      'wikiskill-compiling-agent-experience-persistent-knowledge-skill-evolution',
      'procedural-graphs',
      'skill-plus-plus',
      'agent-plasticity',
    ],
  },
  'agent-harness': {
    title: '에이전트 실행 하네스',
    description:
      '에이전트의 실행 구조와 검증 절차를 설계하고 개선하는 방법을 읽습니다. '
      + '추론의 전체 지도에서 실행 의존성, 행동 직전 선택, 완료 산출물 검증을 거쳐 '
      + '실행 구성 개선과 기능·보안의 다목적 평가로 이어집니다. '
      + '설계 제안과 실험 결과, 검증 시점과 비용의 차이를 구분합니다.',
    slugs: [
      'agentic-reasoning-survey',
      'from-agent-loops-to-structured-graphs-scheduler-theoretic-framework',
      'mid-harness',
      'veriharness',
      'harness-squared',
      'harmony-harness',
    ],
  },
  'agent-memory': {
    title: '에이전트 기억과 문맥 설계',
    description:
      '과거 기록에서 근거를 찾고, 다음 실행에 필요한 문맥을 유지·편집하는 방법을 읽습니다. '
      + '원문 보존과 검색에서 능동적인 기억 재구성, 실행 상태 압축, 직접 문맥 편집으로 '
      + '이어집니다. 외부 기록과 활성 문맥, 선택적 읽기와 압축을 구분하며 '
      + '서로 다른 평가 조건을 하나의 성능 순위로 합치지 않습니다.',
    slugs: [
      'raw-rag',
      'memory-is-reconstructed-not-retrieved-graph-memory-llm-agents',
      'you-dont-need-long-context',
      'context-language-models',
    ],
  },
  'efficient-attention': {
    title: '효율적 어텐션: 공유·압축·상태 표현',
    description:
      '어텐션의 K/V 공유, 잠재 압축, 하이브리드 상태 표현을 비교합니다. '
      + 'GQA의 head 공유에서 DeepSeek-V2의 MLA, Kimi Linear의 상태 기반 계산과 '
      + '전체 어텐션 결합으로 이어집니다. 캐시 저장량과 활성 연산량, 처리량과 지연을 '
      + '구분하며 서로 다른 장비·문맥·배치 조건의 수치를 속도 순위로 비교하지 않습니다.',
    slugs: [
      'gqa',
      'deepseek-v2',
      'kimi-linear',
    ],
  },
};

/** Return the series id containing a slug, else null. */
export function seriesOf(slug: string): string | null {
  for (const [id, series] of Object.entries(BLOG_SERIES)) {
    if (series.slugs.includes(slug)) return id;
  }
  return null;
}
