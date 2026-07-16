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
      + '(Dynamic Word Embeddings)의 핵심 논문을 시간순으로 깊이 있게 읽는 '
      + '한국어 딥리뷰 시리즈. 공동 행렬 분해로 시간 구간 간 정렬 문제를 '
      + '학습 안에서 푸는 DW2V(WSDM 2018)와, 확률적 생성 모델로 정렬을 '
      + '설계 단계에서 소거한 Dynamic Bernoulli Embeddings(WWW 2018)를 '
      + '다룬다.',
    slugs: [
      'dynamic-word-embeddings-evolving-semantic-discovery-review-2026',
      'dynamic-bernoulli-embeddings-language-evolution-review-2026',
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
