/**
 * Tests for usePaperReview hook.
 *
 * Mocks all API calls. Validates:
 * - Initial state
 * - startReview: success, error, loading state
 * - deleteReview: clears state
 * - runAutoHighlight: updates highlights, handles errors
 * - removeHighlight: filters by id
 * - setReviewFromCache: restores cached review
 * - clearReview: resets everything
 * - toggleReviewPanel: flips open state
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { usePaperReview } from '../hooks/usePaperReview';
import type { PaperReview, HighlightItem } from '../api/client';

// Mock the API client module
vi.mock('../api/client', () => ({
  startPaperReview: vi.fn(),
  deletePaperReview: vi.fn(),
  autoHighlightPaperReview: vi.fn(),
}));

import * as apiClient from '../api/client';

// ── Fixtures ──────────────────────────────────────────────────────────────

const mockReview: PaperReview = {
  summary: 'A strong paper.',
  strengths: [
    { point: 'Clear writing', evidence: 'Introduction', significance: 'high' },
  ],
  weaknesses: [
    { point: 'Limited scope', evidence: 'Section 4', severity: 'minor' },
  ],
  methodology_assessment: {
    rigor: 4,
    novelty: 3,
    reproducibility: 3,
    commentary: 'Solid approach.',
  },
  key_contributions: ['New method'],
  questions_for_authors: ['Why not X?'],
  overall_score: 7,
  confidence: 4,
  detailed_review_markdown: '## Summary\nA strong paper.',
  created_at: '2024-01-01T00:00:00',
  model: 'gpt-4.1',
  input_type: 'abstract',
};

const mockHighlights: HighlightItem[] = [
  {
    id: 'rhl_001',
    text: 'Clear writing',
    color: '#a5b4fc',
    memo: '[핵심 발견] Good',
    created_at: '2024-01-01T00:00:00',
    category: 'finding',
    significance: 4,
  },
  {
    id: 'rhl_002',
    text: 'Limited scope',
    color: '#fda4af',
    memo: '[연구 한계] Concern',
    created_at: '2024-01-01T00:00:00',
    category: 'limitation',
    significance: 3,
  },
];

// ── Tests ─────────────────────────────────────────────────────────────────

describe('usePaperReview', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Initial state ───────────────────────────────────────────────────────

  it('initialises with correct default state', () => {
    const { result } = renderHook(() => usePaperReview());
    expect(result.current.review).toBeNull();
    expect(result.current.reviewLoading).toBe(false);
    expect(result.current.reviewError).toBeNull();
    expect(result.current.reviewHighlights).toEqual([]);
    expect(result.current.reviewPanelOpen).toBe(false);
    expect(result.current.activeReviewTab).toBe('review');
    expect(result.current.highlightFilter).toBeNull();
    expect(result.current.autoHighlighting).toBe(false);
  });

  // ── startReview ─────────────────────────────────────────────────────────

  it('startReview: sets loading, opens panel, sets review on success', async () => {
    vi.mocked(apiClient.startPaperReview).mockResolvedValueOnce({
      success: true,
      review: mockReview,
      highlights: mockHighlights,
      highlight_count: mockHighlights.length,
    });

    const { result } = renderHook(() => usePaperReview());

    await act(async () => {
      await result.current.startReview('bm1', 0);
    });

    expect(result.current.review).toEqual(mockReview);
    expect(result.current.reviewHighlights).toEqual(mockHighlights);
    expect(result.current.reviewLoading).toBe(false);
    expect(result.current.reviewPanelOpen).toBe(true);
    expect(result.current.activeReviewTab).toBe('review');
    expect(result.current.reviewError).toBeNull();
  });

  it('startReview: passes fullText to API when provided', async () => {
    vi.mocked(apiClient.startPaperReview).mockResolvedValueOnce({
      success: true,
      review: mockReview,
      highlights: [],
      highlight_count: 0,
    });

    const { result } = renderHook(() => usePaperReview());

    await act(async () => {
      await result.current.startReview('bm1', 2, 'extracted pdf text here');
    });

    expect(apiClient.startPaperReview).toHaveBeenCalledWith('bm1', 2, 'extracted pdf text here');
  });

  it('startReview: sets error on API failure', async () => {
    const err = Object.assign(new Error('Review failed'), {
      response: { data: { detail: 'LLM timed out' } },
    });
    vi.mocked(apiClient.startPaperReview).mockRejectedValueOnce(err);

    const { result } = renderHook(() => usePaperReview());

    await act(async () => {
      await result.current.startReview('bm1', 0);
    });

    expect(result.current.reviewError).toBe('LLM timed out');
    expect(result.current.review).toBeNull();
    expect(result.current.reviewLoading).toBe(false);
    expect(result.current.reviewPanelOpen).toBe(true); // panel stays open to show error
  });

  it('startReview: falls back to err.message when no response.data.detail', async () => {
    const err = new Error('Network error');
    vi.mocked(apiClient.startPaperReview).mockRejectedValueOnce(err);

    const { result } = renderHook(() => usePaperReview());

    await act(async () => {
      await result.current.startReview('bm1', 0);
    });

    expect(result.current.reviewError).toBe('Network error');
  });

  it('startReview: falls back to "Review failed" when error has no message', async () => {
    vi.mocked(apiClient.startPaperReview).mockRejectedValueOnce({});

    const { result } = renderHook(() => usePaperReview());

    await act(async () => {
      await result.current.startReview('bm1', 0);
    });

    expect(result.current.reviewError).toBe('Review failed');
  });

  it('startReview: resets error from prior failed attempt', async () => {
    vi.mocked(apiClient.startPaperReview)
      .mockRejectedValueOnce(new Error('fail'))
      .mockResolvedValueOnce({
        success: true,
        review: mockReview,
        highlights: [],
        highlight_count: 0,
      });

    const { result } = renderHook(() => usePaperReview());

    await act(async () => {
      await result.current.startReview('bm1', 0);
    });
    expect(result.current.reviewError).toBe('fail');

    await act(async () => {
      await result.current.startReview('bm1', 0);
    });
    expect(result.current.reviewError).toBeNull();
    expect(result.current.review).toEqual(mockReview);
  });

  // ── deleteReview ────────────────────────────────────────────────────────

  it('deleteReview: clears review, highlights, closes panel', async () => {
    vi.mocked(apiClient.startPaperReview).mockResolvedValueOnce({
      success: true,
      review: mockReview,
      highlights: mockHighlights,
      highlight_count: 2,
    });
    vi.mocked(apiClient.deletePaperReview).mockResolvedValueOnce({ success: true });

    const { result } = renderHook(() => usePaperReview());

    await act(async () => {
      await result.current.startReview('bm1', 0);
    });
    expect(result.current.reviewPanelOpen).toBe(true);

    await act(async () => {
      await result.current.deleteReview('bm1', 0);
    });

    expect(result.current.review).toBeNull();
    expect(result.current.reviewHighlights).toEqual([]);
    expect(result.current.reviewPanelOpen).toBe(false);
  });

  it('deleteReview: does not throw on API error (silently logs)', async () => {
    vi.mocked(apiClient.deletePaperReview).mockRejectedValueOnce(new Error('server error'));

    const { result } = renderHook(() => usePaperReview());

    // Should not throw
    await act(async () => {
      await result.current.deleteReview('bm1', 0);
    });
    // State unchanged (was already null)
    expect(result.current.review).toBeNull();
  });

  // ── runAutoHighlight ────────────────────────────────────────────────────

  it('runAutoHighlight: sets autoHighlighting during call, updates highlights', async () => {
    const newHighlights: HighlightItem[] = [
      {
        id: 'rhl_003',
        text: 'novel contribution',
        color: '#a5b4fc',
        memo: '[핵심 기여]',
        created_at: '2024-01-01T00:00:00',
      },
    ];
    vi.mocked(apiClient.autoHighlightPaperReview).mockResolvedValueOnce({
      highlights: newHighlights,
      added_count: 1,
      enriched_count: 0,
    });

    const { result } = renderHook(() => usePaperReview());

    await act(async () => {
      await result.current.runAutoHighlight('bm1', 0);
    });

    expect(result.current.reviewHighlights).toEqual(newHighlights);
    expect(result.current.autoHighlighting).toBe(false);
  });

  it('runAutoHighlight: resets autoHighlighting even on error', async () => {
    vi.mocked(apiClient.autoHighlightPaperReview).mockRejectedValueOnce(new Error('fail'));

    const { result } = renderHook(() => usePaperReview());

    await act(async () => {
      await result.current.runAutoHighlight('bm1', 0);
    });

    expect(result.current.autoHighlighting).toBe(false);
    // Highlights remain unchanged (empty)
    expect(result.current.reviewHighlights).toEqual([]);
  });

  // ── removeHighlight ─────────────────────────────────────────────────────

  it('removeHighlight: filters out highlight by id', async () => {
    vi.mocked(apiClient.startPaperReview).mockResolvedValueOnce({
      success: true,
      review: mockReview,
      highlights: mockHighlights,
      highlight_count: 2,
    });

    const { result } = renderHook(() => usePaperReview());

    await act(async () => {
      await result.current.startReview('bm1', 0);
    });
    expect(result.current.reviewHighlights).toHaveLength(2);

    act(() => {
      result.current.removeHighlight('rhl_001');
    });

    expect(result.current.reviewHighlights).toHaveLength(1);
    expect(result.current.reviewHighlights[0].id).toBe('rhl_002');
  });

  it('removeHighlight: no-op for non-existent id', async () => {
    vi.mocked(apiClient.startPaperReview).mockResolvedValueOnce({
      success: true,
      review: mockReview,
      highlights: mockHighlights,
      highlight_count: 2,
    });

    const { result } = renderHook(() => usePaperReview());
    await act(async () => {
      await result.current.startReview('bm1', 0);
    });

    act(() => {
      result.current.removeHighlight('rhl_nonexistent');
    });

    expect(result.current.reviewHighlights).toHaveLength(2);
  });

  // ── setReviewFromCache ──────────────────────────────────────────────────

  it('setReviewFromCache: restores review and opens panel when review is non-null', () => {
    const { result } = renderHook(() => usePaperReview());

    act(() => {
      result.current.setReviewFromCache(mockReview, mockHighlights);
    });

    expect(result.current.review).toEqual(mockReview);
    expect(result.current.reviewHighlights).toEqual(mockHighlights);
    expect(result.current.reviewPanelOpen).toBe(true);
    expect(result.current.reviewError).toBeNull();
  });

  it('setReviewFromCache: does NOT open panel when review is null', () => {
    const { result } = renderHook(() => usePaperReview());

    act(() => {
      result.current.setReviewFromCache(null, []);
    });

    expect(result.current.review).toBeNull();
    expect(result.current.reviewPanelOpen).toBe(false);
  });

  it('setReviewFromCache: clears previous error state', async () => {
    vi.mocked(apiClient.startPaperReview).mockRejectedValueOnce(new Error('prior error'));

    const { result } = renderHook(() => usePaperReview());

    await act(async () => {
      await result.current.startReview('bm1', 0);
    });
    expect(result.current.reviewError).toBe('prior error');

    act(() => {
      result.current.setReviewFromCache(mockReview, []);
    });

    expect(result.current.reviewError).toBeNull();
  });

  // ── clearReview ─────────────────────────────────────────────────────────

  it('clearReview: resets all state to defaults', async () => {
    vi.mocked(apiClient.startPaperReview).mockResolvedValueOnce({
      success: true,
      review: mockReview,
      highlights: mockHighlights,
      highlight_count: 2,
    });

    const { result } = renderHook(() => usePaperReview());

    await act(async () => {
      await result.current.startReview('bm1', 0);
    });
    act(() => {
      result.current.setActiveReviewTab('highlights');
      result.current.setHighlightFilter('finding');
    });

    act(() => {
      result.current.clearReview();
    });

    expect(result.current.review).toBeNull();
    expect(result.current.reviewHighlights).toEqual([]);
    expect(result.current.reviewError).toBeNull();
    expect(result.current.reviewLoading).toBe(false);
    expect(result.current.reviewPanelOpen).toBe(false);
    expect(result.current.activeReviewTab).toBe('review');
    expect(result.current.highlightFilter).toBeNull();
  });

  // ── toggleReviewPanel ───────────────────────────────────────────────────

  it('toggleReviewPanel: flips open state', () => {
    const { result } = renderHook(() => usePaperReview());

    expect(result.current.reviewPanelOpen).toBe(false);

    act(() => { result.current.toggleReviewPanel(); });
    expect(result.current.reviewPanelOpen).toBe(true);

    act(() => { result.current.toggleReviewPanel(); });
    expect(result.current.reviewPanelOpen).toBe(false);
  });

  // ── setActiveReviewTab ──────────────────────────────────────────────────

  it('setActiveReviewTab: switches tab', () => {
    const { result } = renderHook(() => usePaperReview());

    act(() => { result.current.setActiveReviewTab('highlights'); });
    expect(result.current.activeReviewTab).toBe('highlights');

    act(() => { result.current.setActiveReviewTab('review'); });
    expect(result.current.activeReviewTab).toBe('review');
  });

  // ── setHighlightFilter ──────────────────────────────────────────────────

  it('setHighlightFilter: sets and clears category filter', () => {
    const { result } = renderHook(() => usePaperReview());

    act(() => { result.current.setHighlightFilter('limitation'); });
    expect(result.current.highlightFilter).toBe('limitation');

    act(() => { result.current.setHighlightFilter(null); });
    expect(result.current.highlightFilter).toBeNull();
  });
});
