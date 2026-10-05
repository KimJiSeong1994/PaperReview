import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { GraphData, Paper } from '../types';
import DetailPanel from '../components/DetailPanel';

const selectedPaper: Paper = {
  doc_id: 'selected-doc',
  result_key: 'doi:selected',
  title: 'Selected paper',
  authors: ['A. Researcher'],
  abstract: 'Selected paper abstract.',
  citations: 12,
};

const relatedPaper: Paper = {
  doc_id: 'related-doc',
  result_key: 'doi:related',
  title: 'Related paper',
  authors: ['B. Researcher'],
  year: 2024,
  abstract: 'Related paper abstract.',
};

const semanticMeta: NonNullable<GraphData['meta']> = {
  edge_method: 'semantic_cosine',
  edge_label: '제목 의미 유사도',
  directed: false,
};

const relatedPapers = [{
  paper: relatedPaper,
  weight: 0.876,
  sharedTerms: ['graph retrieval', 'ranking', 'evidence', 'extra term'],
}];

describe('DetailPanel related papers', () => {
  it('shows graph weight, bounded shared evidence and title-only method explanation before the abstract', () => {
    const { container } = render(
      <DetailPanel
        paper={selectedPaper}
        relatedPapers={relatedPapers}
        edgeMeta={semanticMeta}
      />,
    );

    const section = screen.getByRole('region', { name: '다음에 읽을 논문' });
    expect(section).toHaveTextContent('다음에 읽을 논문 · 그래프 유사도 기준');
    expect(section).toHaveTextContent('Related paper');
    expect(section).toHaveTextContent('2024');
    expect(section).toHaveTextContent('제목 의미 유사도 88%');
    expect(section).toHaveTextContent('공통 단서: graph retrieval · ranking · evidence');
    expect(section).not.toHaveTextContent('extra term');
    expect(section).toHaveTextContent('제목 임베딩 코사인 유사도 · 인용·인과 관계 아님');
    expect(section.textContent).not.toContain('초록');

    const abstract = container.querySelector('.detail-abstract');
    expect(abstract).not.toBeNull();
    expect(section.compareDocumentPosition(abstract!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows explicit unavailable-term copy when an edge has no shared terms', () => {
    render(
      <DetailPanel
        paper={selectedPaper}
        relatedPapers={[{ paper: relatedPaper, weight: 0.5, sharedTerms: [] }]}
        edgeMeta={{ edge_method: 'title_keyword_jaccard', edge_label: '제목·키워드 유사도', directed: false }}
      />,
    );

    const section = screen.getByRole('region', { name: '다음에 읽을 논문' });
    expect(section).toHaveTextContent('제목·키워드 유사도 50%');
    expect(section).toHaveTextContent('공통 용어 정보 없음');
    expect(section).toHaveTextContent('제목·키워드 겹침(Jaccard) · 인용·인과 관계 아님');
  });

  it('omits the next-read section when no graph neighbors resolve', () => {
    render(<DetailPanel paper={selectedPaper} relatedPapers={[]} edgeMeta={semanticMeta} />);

    expect(screen.queryByRole('region', { name: '다음에 읽을 논문' })).not.toBeInTheDocument();
  });

  it('selects the exact related Paper object when its card is activated', () => {
    const onSelectRelated = vi.fn();
    render(
      <DetailPanel
        paper={selectedPaper}
        relatedPapers={relatedPapers}
        edgeMeta={semanticMeta}
        onSelectRelated={onSelectRelated}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Related paper/ }));

    expect(onSelectRelated).toHaveBeenCalledExactlyOnceWith(relatedPaper);
  });
});
