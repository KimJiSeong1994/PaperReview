import { describe, expect, it } from 'vitest';
import {
  authorList, citationLabel, citationOrder, degradedLabels, linkCitations, normalizeEmphasis, reviewProgressLabel,
} from '../components/conversation/conversationBlocks';

describe('normalizeEmphasis', () => {
  it('unwraps quoted and triple bold so CommonMark can close it before Hangul', () => {
    expect(normalizeEmphasis('**"GraphRAG Survey"**가 대표적이에요.')).toBe('**GraphRAG Survey**가 대표적이에요.');
    expect(normalizeEmphasis('***"HippoRAG"***는')).toBe('**HippoRAG**는');
    expect(normalizeEmphasis('***LightRAG***와 비교하면')).toBe('**LightRAG**와 비교하면');
  });

  it('moves punctuation before a closing ** out of the bold span', () => {
    expect(normalizeEmphasis('**구조 유형별(세그먼트형/반성형/인지형/다중메모리형)**를 나눠요.'))
      .toBe('**구조 유형별(세그먼트형/반성형/인지형/다중메모리형**)를 나눠요.');
    expect(normalizeEmphasis('**핵심 기여.**는')).toBe('**핵심 기여**.는');
    // Never starts a match at a closing ** and swallows the text between two bold spans.
    const spans = '**A** 그리고 (B)**C**';
    expect(normalizeEmphasis(spans)).toBe(spans);
  });

  it('leaves ordinary bold, italics and unbalanced text alone', () => {
    const plain = '**굵게** 그리고 *기울임*, "따옴표"와 **"열린 따옴표';
    expect(normalizeEmphasis(plain)).toBe(plain);
  });

  it('keeps citations linkable after normalising', () => {
    expect(linkCitations(normalizeEmphasis('**"A"**가 [1][2] 참고'))).toBe('**A**가 [1,2](#cite-1,2) 참고');
  });
});

describe('degradedLabels', () => {
  it('names missing sources, folds ranker and stage fallbacks into one line, drops unknown markers', () => {
    expect(degradedLabels(['source_incomplete', 'ranker_unavailable', 'rerank:fallback', 'mystery'])).toEqual([
      '일부 출처가 응답하지 않았어요.',
      '순위 계산은 대체 방식으로 했어요.',
    ]);
    expect(degradedLabels([])).toEqual([]);
  });
});

describe('reviewProgressLabel', () => {
  it('maps the review service\'s progress strings and hides anything unknown', () => {
    expect(reviewProgressLabel('')).toBe('심층 리뷰를 시작하는 중…');
    expect(reviewProgressLabel('Starting deep research...')).toBe('심층 리뷰를 시작하는 중…');
    expect(reviewProgressLabel('Analysing papers...')).toBe('논문을 분석하는 중…');
    expect(reviewProgressLabel('AI is analysing the papers...')).toBe('논문을 분석하는 중…');
    expect(reviewProgressLabel('Researchers analyzing papers with deepagents...')).toBe('논문을 분석하는 중…');
    expect(reviewProgressLabel('Retrying analysis (attempt 2)...')).toBe('논문을 다시 분석하는 중…');
    expect(reviewProgressLabel('Fetching paper abstracts...')).toBe('논문 정보를 모으는 중…');
    expect(reviewProgressLabel('Verifying...')).toBe('주장을 검증하는 중…');
    expect(reviewProgressLabel('Generating report...')).toBe('리포트를 쓰는 중…');
    expect(reviewProgressLabel('검증 2/3')).toBe('검증 2/3');
    expect(reviewProgressLabel('Traceback (most recent call last)')).toBe('진행 중…');
  });
});

describe('citation labels', () => {
  it('uses the first author\'s surname and the year', () => {
    expect(citationLabel({ title: 't', authors: ['Jiseong Han', 'Minji Lee'], year: 2026 })).toBe('Han 2026');
    expect(citationLabel({ title: 't', authors: ['Han, Jiseong'], year: '2025-03-01' })).toBe('Han 2025');
    expect(citationLabel({ title: 't', authors: ['B. Gutiérrez Jr.'], year: 2024 })).toBe('Jr 2024');
  });

  it('keeps a Korean name whole', () => {
    expect(citationLabel({ title: 't', authors: ['한지성'], year: 2025 })).toBe('한지성 2025');
  });

  it('falls back to the title without authors, and drops a missing year', () => {
    expect(citationLabel({ title: 'Graph Retrieval Augmented Generation', authors: [], year: 2024 })).toBe('Graph Retrieval Augm… 2024');
    expect(citationLabel({ title: 'HippoRAG', authors: ['Bernal Gutiérrez'] })).toBe('Gutiérrez');
    expect(citationLabel({ title: 'Short', year: null })).toBe('Short');
  });

  it('skips venue, affiliation and dated entries in the author list', () => {
    const authors = ['Association for Computational Linguistics 2026', 'Long Chen', 'Seoul National University', 'Mina Park'];
    expect(citationLabel({ title: 'Graph memory', authors, year: 2026 })).toBe('Chen 2026');
    expect(authorList(authors)).toBe('Long Chen, Mina Park');
    expect(authorList(['Proceedings of the Workshop', 'IEEE Press', 'Journal of AI'])).toBe('');
    expect(citationLabel({ title: 'Graph memory', authors: ['Conference on NLP'], year: 2026 })).toBe('Graph memory 2026');
    // Name words that merely contain a keyword are still names.
    expect(authorList(['Jordan Pressman'])).toBe('Jordan Pressman');
  });

  it('treats an author string without letters as no author', () => {
    expect(citationLabel({ title: 'Graph Retrieval Augmented Generation', authors: ['2026'], year: 2026 })).toBe('Graph Retrieval Augm… 2026');
    expect(authorList(['2026', 'Jiseong Han'])).toBe('Jiseong Han');
    expect(authorList(['—'])).toBe('');
  });
});

describe('citation runs', () => {
  it('groups consecutive citations into one link and keeps real links', () => {
    expect(linkCitations('보면 [3][7][8] 이렇고 [2], [4] 와 [5] [6]')).toBe(
      '보면 [3,7,8](#cite-3,7,8) 이렇고 [2,4](#cite-2,4) 와 [5,6](#cite-5,6)',
    );
    expect(linkCitations('[원문](https://x.org) 그리고 [1](https://y.org)')).toBe('[원문](https://x.org) 그리고 [1](https://y.org)');
    expect(linkCitations('[B1][B2]')).toBe('[B1,2](#bm-1,2)');
  });

  it('orders cited papers by first citation, once each', () => {
    expect(citationOrder('[7] 다음 [3][7][8], 다시 [3]')).toEqual([7, 3, 8]);
    expect(citationOrder('인용 없음')).toEqual([]);
  });

  it('leaves author–year text alone and moves citations out of a bold head', () => {
    const prose = '앞선 연구 (Han 2026; Lee 2025) 에서 보듯이';
    expect(linkCitations(normalizeEmphasis(prose))).toBe(prose);
    expect(normalizeEmphasis('**핵심 기여 [1][2]**는 다음과 같아요')).toBe('**핵심 기여** [1][2]는 다음과 같아요');
    expect(linkCitations(normalizeEmphasis('**핵심 기여 [1]**는'))).toBe('**핵심 기여** [1](#cite-1)는');
  });
});
