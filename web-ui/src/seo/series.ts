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
      '집현전을 만들며 남긴 개발 기록 7편을 시간순으로 읽습니다. '
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
      '그래프 표현 학습과 그래프 신경망(GNN)을 11편으로 읽는 시리즈입니다. '
      + '노드를 벡터로 표현하는 기초에서 이웃 정보 집계와 새 노드로의 일반화, '
      + '이종 그래프와 예측 설명, 공정한 기준선 비교로 이어집니다. '
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
      'classic-gnns-strong-baselines-graph-level-tasks-gnnplus-review-2026',
    ],
  },
  dwe: {
    title: 'DWE 논문 리뷰 시리즈',
    description:
      '단어 의미의 시간적 변화를 추적하는 동적 단어 임베딩의 핵심 논문 12편을 읽습니다. '
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
      'LLM 검색증강생성에 그래프를 결합하는 GraphRAG 계열의 핵심 논문 11편을 '
      + '기초 연구부터 최초 공개 순서로 읽습니다. 문서 그래프 탐색과 전역 요약에서 '
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
    ],
  },
  'graph-causality': {
    title: 'Graph causality 논문 리뷰 시리즈',
    description:
      '그래프와 동역학 시계열에서 인과 구조를 복원하려는 핵심 논문 3편을 '
      + '공개·기초 흐름 순서로 읽습니다. PCM의 간접 인과 구분에서 CIC의 잠재 교란자 '
      + '분해, IC2의 개입 동역학 인과 추정으로 이어집니다. 직접 인과, 간접 인과, '
      + '잠재 교란자를 각 방법이 어떻게 구분하려는지 살펴봅니다.',
    slugs: [
      'pcm-partial-cross-mapping-eliminates-indirect-causal-influences',
      'cic-dynamical-causality-under-invisible-confounders',
      'ic2-interventional-dynamical-causality-under-latent-confounders',
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
