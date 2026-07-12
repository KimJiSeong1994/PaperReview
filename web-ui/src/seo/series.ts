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
      '그래프 신경망(GNN)의 핵심 논문 9편을 랜덤워크 임베딩부터 '
      + '메시지 패싱, 어텐션, 표현력, 이종 그래프, 설명가능성까지 '
      + '권장 순서로 깊이 있게 읽는 한국어 딥리뷰 시리즈. 스탠퍼드 '
      + 'CS224W(Machine Learning with Graphs) 커리큘럼과 나란히 읽을 '
      + '수 있도록 구성했다.',
    slugs: [
      'deepwalk-online-learning-social-representations-review-2026',
      'semi-supervised-classification-graph-convolutional-networks-review-2026',
      'graphsage-inductive-representation-learning-large-graphs-review-2026',
      'graph-attention-networks-gat-review-2026',
      'how-powerful-are-graph-neural-networks-gin-review-2026',
      'heterogeneous-graph-neural-network-hetgnn-review-2026',
      'heterogeneous-graph-attention-network-han-review-2026',
      'gnnexplainer-gnn-subgraph-feature-mask-review-2026',
      'explaining-temporal-graph-neural-networks-feature-induced-information-flow-review-2026',
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
