import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SearchPage from '../components/SearchPage';
import { fetchBatchReferences, getGraphData, searchPapers } from '../api/client';
import { useDeepReview } from '../hooks/useDeepReview';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('../api/client', async () => {
  const reviewApi = await vi.importActual<typeof import('../api/review')>('../api/review');
  return {
    classifyPosterError: reviewApi.classifyPosterError,
    classifyPosterResponse: reviewApi.classifyPosterResponse,
    fetchBatchReferences: vi.fn(),
    generatePoster: vi.fn(),
    generatePosterDirect: vi.fn(),
    getGraphData: vi.fn(),
    saveBookmark: vi.fn(),
    searchPapers: vi.fn(),
    startDeepReview: vi.fn(),
    trackSearchClick: vi.fn(),
  };
});

vi.mock('../hooks/useDeepReview', () => ({ useDeepReview: vi.fn() }));
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, setShowLoginModal: vi.fn() }),
}));
vi.mock('../analytics/events', () => ({
  trackBookmarkSave: vi.fn(),
  trackDeepReviewComplete: vi.fn(),
  trackDeepReviewStart: vi.fn(),
  trackPaperSelect: vi.fn(),
  trackPosterGenerateComplete: vi.fn(),
  trackPosterGenerateFail: vi.fn(),
  trackPosterGenerateStart: vi.fn(),
  trackReportDownload: vi.fn(),
  trackSearchEvent: vi.fn(),
}));

function paper(docId: string, title: string, rank?: number) {
  return { doc_id: docId, title, authors: ['A. Researcher'], year: 2026, abstract: 'a', _rank: rank };
}

async function submitSearch(query: string) {
  await act(async () => {
    fireEvent.change(screen.getByPlaceholderText('논문 검색'), { target: { value: query } });
    fireEvent.click(screen.getByRole('button', { name: '논문 검색' }));
  });
}

function renderedTitles(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('.paper-title')).map(
    (node) => node.textContent ?? '',
  );
}

describe('SearchPage result ordering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    vi.mocked(useDeepReview).mockReturnValue({
      reviewSessionId: null,
      reviewStatus: 'idle',
      reviewProgress: '',
      reviewReport: '',
      verificationStats: null,
      startReview: vi.fn(),
      resetReview: vi.fn(),
    } as never);
    vi.mocked(getGraphData).mockResolvedValue({ nodes: [], edges: [] });
    vi.mocked(fetchBatchReferences).mockResolvedValue({ references: [] });
  });

  it('renders the backend ranking order, not the per-source bucket order', async () => {
    // The API groups papers by source. Walking the buckets yields
    // [arxiv-1, arxiv-2, openalex-1]; the ranker put the openalex paper first.
    vi.mocked(searchPapers).mockResolvedValue({
      results: {
        arxiv: [paper('a1', 'Arxiv Second', 1), paper('a2', 'Arxiv Third', 2)],
        openalex: [paper('o1', 'OpenAlex First', 0)],
      },
      total: 3,
    } as never);

    const { container } = render(
      <MemoryRouter initialEntries={['/']}>
        <SearchPage />
      </MemoryRouter>,
    );
    await submitSearch('attention');

    await waitFor(() => expect(renderedTitles(container)).toHaveLength(3));
    expect(renderedTitles(container)).toEqual([
      'OpenAlex First',
      'Arxiv Second',
      'Arxiv Third',
    ]);
  });

  it('keeps papers without a rank, sorted after the ranked ones', async () => {
    // Partial/timed-out responses and papers beyond the ranking cap arrive
    // without _rank. They must still render rather than disappear.
    vi.mocked(searchPapers).mockResolvedValue({
      results: {
        arxiv: [paper('a1', 'Unranked Tail'), paper('a2', 'Ranked Head', 0)],
      },
      total: 2,
    } as never);

    const { container } = render(
      <MemoryRouter initialEntries={['/']}>
        <SearchPage />
      </MemoryRouter>,
    );
    await submitSearch('attention');

    await waitFor(() => expect(renderedTitles(container)).toHaveLength(2));
    expect(renderedTitles(container)).toEqual(['Ranked Head', 'Unranked Tail']);
  });
});
