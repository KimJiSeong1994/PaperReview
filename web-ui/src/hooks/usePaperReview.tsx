import { useState, useCallback } from 'react';
import { startPaperReview, deletePaperReview, autoHighlightPaperReview } from '../api/client';
import type { PaperReview, HighlightItem } from '../api/client';

export interface UsePaperReviewReturn {
  review: PaperReview | null;
  reviewLoading: boolean;
  reviewError: string | null;
  reviewHighlights: HighlightItem[];
  reviewPanelOpen: boolean;
  activeReviewTab: 'review' | 'highlights';
  highlightFilter: string | null;
  autoHighlighting: boolean;

  startReview: (bookmarkId: string, paperIndex: number, fullText?: string) => Promise<{ review: PaperReview; highlights: HighlightItem[] } | null>;
  deleteReview: (bookmarkId: string, paperIndex: number) => Promise<void>;
  runAutoHighlight: (bookmarkId: string, paperIndex: number) => Promise<void>;
  setReviewFromCache: (review: PaperReview | null, highlights: HighlightItem[]) => void;
  toggleReviewPanel: () => void;
  setActiveReviewTab: (tab: 'review' | 'highlights') => void;
  setHighlightFilter: (category: string | null) => void;
  clearReview: () => void;
  removeHighlight: (hlId: string) => void;
}

export function usePaperReview(): UsePaperReviewReturn {
  const [review, setReview] = useState<PaperReview | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [reviewHighlights, setReviewHighlights] = useState<HighlightItem[]>([]);
  const [reviewPanelOpen, setReviewPanelOpen] = useState(false);
  const [activeReviewTab, setActiveReviewTab] = useState<'review' | 'highlights'>('review');
  const [highlightFilter, setHighlightFilter] = useState<string | null>(null);
  const [autoHighlighting, setAutoHighlighting] = useState<boolean>(false);

  const startReviewHandler = useCallback(async (bookmarkId: string, paperIndex: number, fullText?: string): Promise<{ review: PaperReview; highlights: HighlightItem[] } | null> => {
    setReviewLoading(true);
    setReviewError(null);
    setReviewPanelOpen(true);
    setActiveReviewTab('review');
    try {
      const result = await startPaperReview(bookmarkId, paperIndex, fullText);
      setReview(result.review);
      setReviewHighlights(result.highlights);
      return { review: result.review, highlights: result.highlights };
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || 'Review failed';
      setReviewError(msg);
      return null;
    } finally {
      setReviewLoading(false);
    }
  }, []);

  const deleteReviewHandler = useCallback(async (bookmarkId: string, paperIndex: number) => {
    try {
      await deletePaperReview(bookmarkId, paperIndex);
      setReview(null);
      setReviewHighlights([]);
      setReviewPanelOpen(false);
    } catch (err: any) {
      console.error('Failed to delete review:', err);
    }
  }, []);

  const runAutoHighlightHandler = useCallback(async (bookmarkId: string, paperIndex: number) => {
    setAutoHighlighting(true);
    try {
      const result = await autoHighlightPaperReview(bookmarkId, paperIndex);
      setReviewHighlights(result.highlights);
    } catch (err: any) {
      console.error('Auto-highlight failed:', err);
    } finally {
      setAutoHighlighting(false);
    }
  }, []);

  const removeHighlight = useCallback((hlId: string) => {
    setReviewHighlights(prev => prev.filter(h => h.id !== hlId));
  }, []);

  const setReviewFromCache = useCallback((cachedReview: PaperReview | null, highlights: HighlightItem[]) => {
    setReview(cachedReview);
    setReviewHighlights(highlights);
    setReviewError(null);
    if (cachedReview) {
      setReviewPanelOpen(true);
    }
  }, []);

  const toggleReviewPanel = useCallback(() => {
    setReviewPanelOpen(prev => !prev);
  }, []);

  const clearReview = useCallback(() => {
    setReview(null);
    setReviewHighlights([]);
    setReviewError(null);
    setReviewLoading(false);
    setReviewPanelOpen(false);
    setActiveReviewTab('review');
    setHighlightFilter(null);
  }, []);

  return {
    review,
    reviewLoading,
    reviewError,
    reviewHighlights,
    reviewPanelOpen,
    activeReviewTab,
    highlightFilter,
    autoHighlighting,
    startReview: startReviewHandler,
    deleteReview: deleteReviewHandler,
    runAutoHighlight: runAutoHighlightHandler,
    setReviewFromCache,
    toggleReviewPanel,
    setActiveReviewTab,
    setHighlightFilter,
    clearReview,
    removeHighlight,
  };
}
