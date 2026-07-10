import { describe, expect, it } from 'vitest';
import { buildPaperViewerHref, extractPrimaryPaperReference } from '../utils/blogPaperReference';

describe('blog paper reference extraction', () => {
  it('extracts the primary GraphSAGE arXiv paper from the Paper block only', () => {
    const ref = extractPrimaryPaperReference({
      category: 'paper-review',
      title: 'Inductive Representation Learning on Large Graphs',
      content:
        '# Inductive Representation Learning on Large Graphs\n\n' +
        '**Paper:** Hamilton, William L.; Ying, Rex; Leskovec, Jure. (2017). "Inductive Representation Learning on Large Graphs." *NIPS 2017*, arXiv:1706.02216. DOI: https://doi.org/10.48550/arXiv.1706.02216.\n\n' +
        '**Abstract:** Later references include arXiv:1609.02907 and DOI: https://doi.org/10.1145/2623330.2623732.',
    });

    expect(ref).toMatchObject({
      title: 'Inductive Representation Learning on Large Graphs',
      authors: ['Hamilton, William L.', 'Ying, Rex', 'Leskovec, Jure.'],
      year: 2017,
      arxiv_id: '1706.02216',
      pdf_url: 'https://arxiv.org/pdf/1706.02216.pdf',
      doi: '10.48550/arXiv.1706.02216',
    });
  });

  it('builds a stable Paper Viewer href with PDF metadata', () => {
    const href = buildPaperViewerHref({
      title: 'GNNExplainer: Generating Explanations for Graph Neural Networks',
      authors: ['Ying, Rex', 'Leskovec, Jure'],
      year: 2019,
      arxiv_id: '1903.03894v4',
      pdf_url: 'https://arxiv.org/pdf/1903.03894.pdf',
      url: 'https://arxiv.org/abs/1903.03894v4',
    });

    expect(href).toContain('/paper-viewer?');
    expect(href).toContain('title=GNNExplainer');
    expect(href).toContain('pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1903.03894.pdf');
    expect(href).toContain('source=blog-reference');
  });
});
