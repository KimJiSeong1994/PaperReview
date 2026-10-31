import { describe, expect, it } from 'vitest';
import { degradedLabels, linkCitations, normalizeEmphasis } from '../components/conversation/conversationBlocks';

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
    expect(linkCitations(normalizeEmphasis('**"A"**가 [1][2] 참고'))).toBe('**A**가 [1](#cite-1)[2](#cite-2) 참고');
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
