import { describe, expect, it } from 'vitest';
import {
  blogSeoMeta,
  buildPaperViewerHref,
  extractPrimaryPaperReference,
} from '../utils/blogPaperReference';

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

describe('blogSeoMeta', () => {
  const paperPost = {
    category: 'paper-review',
    title: 'DeepWalk: Online Learning of Social Representations',
    excerpt: '랜덤워크 임베딩을 소개한 DeepWalk 리뷰.',
    content:
      '**Paper:** Perozzi et al. "DeepWalk: Online Learning of Social Representations" ' +
      '(KDD 2014). arXiv:1403.6652\n\n**Abstract:** ...',
  };

  it('enriches a paper review title/description with the arXiv id (H1 untouched)', () => {
    const meta = blogSeoMeta(paperPost);
    expect(meta.title).toBe(
      'DeepWalk: Online Learning of Social Representations — arXiv:1403.6652 논문 리뷰 · 집현전',
    );
    expect(meta.description).toBe('arXiv:1403.6652 · 랜덤워크 임베딩을 소개한 DeepWalk 리뷰.');
    // The raw article title (the <h1>) is never mutated.
    expect(paperPost.title).toBe('DeepWalk: Online Learning of Social Representations');
  });

  it('adds a 논문 리뷰 cue for a paper review without an arXiv id', () => {
    const meta = blogSeoMeta({
      category: 'paper-review',
      title: 'Some DOI-only Paper',
      excerpt: '요약.',
      content: '**Paper:** Author. "Some DOI-only Paper" (2020). DOI: 10.1000/xyz\n\n**Abstract:** ...',
    });
    expect(meta.title).toBe('Some DOI-only Paper 논문 리뷰 · 집현전');
  });

  it('leaves non-paper posts on the plain blog title', () => {
    const meta = blogSeoMeta({
      category: 'engineering',
      title: '집현전 검색 고도화를 에이전트에게 넘겼다',
      excerpt: '엔지니어링 노트.',
      content: 'SkillOpt 로 검색 프롬프트를 최적화한 기록.',
    });
    expect(meta.title).toBe('집현전 검색 고도화를 에이전트에게 넘겼다 | Jiphyeonjeon Blog');
    expect(meta.description).toBe('엔지니어링 노트.');
  });
});
