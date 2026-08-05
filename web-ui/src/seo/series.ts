// Ordered blog series (pillar pages). Shared contract with the Python SSR
// builder — keep ids, titles, descriptions, and slug order in byte-sync with
// routers/seo.py::BLOG_SERIES.

export interface BlogSeries {
  title: string;
  description: string;
  slugs: string[];
}

export const BLOG_SERIES: Record<string, BlogSeries> = {
  gnn: {
    title: 'GNN 논문 리뷰 시리즈',
    description:
      '그래프 신경망(GNN)의 핵심 논문 11편을 랜덤워크 임베딩부터 '
      + '메시지 패싱, 어텐션, 표현력, 이종 그래프, 설명가능성, 강한 베이스라인 재평가까지 '
      + '권장 순서로 깊이 있게 읽는 한국어 딥리뷰 시리즈. 스탠퍼드 '
      + 'CS224W(Machine Learning with Graphs) 커리큘럼과 나란히 읽을 '
      + '수 있도록 구성했다.',
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
      '단어 의미의 시간적 변화를 임베딩으로 추적하는 동적 단어 임베딩'
      + '(Dynamic Word Embeddings)의 핵심 논문 12편을 변화점 통계 검정부터 '
      + '의미 변화의 통계 법칙, 베이지안 상태공간 모델, 공동 행렬 분해, '
      + '확률적 생성 모델, 컴퍼스 정렬, 문맥화 이전 연구의 조망, 문맥화 '
      + '표현의 기하 분석, 용법 유형 군집, 문맥화 임베딩과의 결합, '
      + '문맥화 탐지 연구의 조망, 그리고 문맥화 표현의 체계 비교까지 '
      + '시간순으로 깊이 있게 읽는 '
      + '한국어 딥리뷰 시리즈. 시간 구간별로 따로 학습한 임베딩을 사후에 '
      + '맞추던 정렬 문제가 학습 안으로, 다시 모델 설계 안으로 흡수되는 '
      + '흐름을 계보로 따라간다.',
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
      'LLM 검색증강생성에 지식 그래프를 결합하는 GraphRAG 계열의 핵심 '
      + '논문 11편을 LLM 기반 문서 그래프 탐색(KGP), 전역 커뮤니티 '
      + '요약(MS GraphRAG), 그래프 연상 기억(HippoRAG), 경량 이중 '
      + '검색(LightRAG), 비모수적 장기 기억(HippoRAG 2), 인과 경로 '
      + '검색(CausalRAG), 계층 집약과 LCA 검색(LeanRAG), 관계 추출 없는 '
      + '선형 그래프 검색(LinearRAG), 계층 검색과 '
      + '적응적 통합(Deep GraphRAG), 계층형 인과 게이트(CausalRAG2), '
      + '다단계 파이프라인과 컴팩트 추출 모델(RAGU)까지 기초 연구부터 '
      + '최초 공개 순서로 깊이 있게 읽는 한국어 딥리뷰 '
      + '시리즈. 문서 간 연관 구조를 어떻게 색인하고, 무엇을 검색 단위로 '
      + '삼으며, 그 근거를 어디까지 믿어야 하는지를 계보로 따라간다.',
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
  'urban-spatial-sociology': {
    title: '도시공간 사회학 논문 리뷰 시리즈',
    description:
      '도시의 공간 구조와 인간 이동을 그래프와 공간 상호작용 이론으로 '
      + '읽는 핵심 논문 2편을 이동 네트워크의 부분 관측 복원과 도시 간 '
      + '전이를 다룬 neuroGravity, 통근 흐름의 생산·흡인 비대칭과 거리 '
      + '감쇠를 학습 제약으로 결합한 PIG-GNN까지 원논문의 최초 공개 '
      + '순서로 읽는 '
      + '한국어 딥리뷰 시리즈. 도시 이동을 단순 예측 문제가 아니라 공간 '
      + '분리, 통근 구조, 지역 간 관계를 함께 설명하는 사회학적 대상으로 '
      + '살펴본다.',
    slugs: [
      'transferable-human-mobility-network-reconstruction-with-neurogravity',
      'theory-informed-interpretable-graph-learning-urban-commuting-flows',
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
