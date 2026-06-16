import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import SearchPage from '../components/SearchPage';
import {
  fetchBatchReferences,
  generatePoster,
  generatePosterDirect,
  getGraphData,
  searchPapers,
} from '../api/client';
import { useDeepReview } from '../hooks/useDeepReview';
import {
  trackPosterGenerateComplete,
  trackPosterGenerateStart,
  trackSearchEvent,
} from '../analytics/events';

vi.mock('../api/client', () => ({
  fetchBatchReferences: vi.fn(),
  generatePoster: vi.fn(),
  generatePosterDirect: vi.fn(),
  getGraphData: vi.fn(),
  saveBookmark: vi.fn(),
  searchPapers: vi.fn(),
  startDeepReview: vi.fn(),
}));

vi.mock('../hooks/useDeepReview', () => ({
  useDeepReview: vi.fn(),
}));

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    setShowLoginModal: vi.fn(),
  }),
}));

vi.mock('../analytics/events', () => ({
  trackBookmarkSave: vi.fn(),
  trackDeepReviewComplete: vi.fn(),
  trackDeepReviewStart: vi.fn(),
  trackPosterGenerateComplete: vi.fn(),
  trackPosterGenerateStart: vi.fn(),
  trackReportDownload: vi.fn(),
  trackSearchEvent: vi.fn(),
}));

function renderSearchPage() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <SearchPage />
    </MemoryRouter>,
  );
}

async function submitSearch(query: string) {
  const user = userEvent.setup();

  await user.type(screen.getByPlaceholderText('Search papers...'), query);
  await user.click(screen.getByTitle('Search'));
}

describe('SearchPage analytics instrumentation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    vi.mocked(useDeepReview).mockReturnValue({
      reviewSessionId: 'review-session-1',
      reviewStatus: 'completed',
      reviewProgress: '',
      reviewReport: 'review report markdown',
      verificationStats: null,
      startReview: vi.fn(),
      resetReview: vi.fn(),
    });
    vi.mocked(getGraphData).mockResolvedValue({ nodes: [], edges: [] });
    vi.mocked(fetchBatchReferences).mockResolvedValue({ references: [] });
  });

  it('reports SearchPage search results through the privacy-safe search event wrapper', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      query_analysis: { is_academic: false },
      results: {},
    } as never);

    renderSearchPage();
    await submitSearch('private raw paper title');

    await waitFor(() => {
      expect(trackSearchEvent).toHaveBeenCalledWith('private raw paper title', 'non_academic', 0, 'home');
    });
  });

  it('tracks poster completion when session poster generation falls back to direct generation', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: {
        arxiv: [{
          doc_id: 'paper-1',
          title: 'Privacy Paper',
          authors: ['A. Researcher'],
          year: 2026,
          abstract: 'abstract',
        }],
      },
      total: 1,
    });
    vi.mocked(generatePoster).mockRejectedValue(new Error('session poster failed'));
    vi.mocked(generatePosterDirect).mockResolvedValue({
      success: true,
      session_id: 'review-session-1',
      poster_html: '<html>poster</html>',
      poster_path: '/poster.html',
    });

    renderSearchPage();
    await submitSearch('privacy preserving analytics');

    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /tools/i }));
    await user.click(await screen.findByRole('button', { name: /generate poster/i }));

    await waitFor(() => {
      expect(generatePosterDirect).toHaveBeenCalledWith('review report markdown', 0);
    });
    expect(trackPosterGenerateStart).toHaveBeenCalledTimes(1);
    expect(trackPosterGenerateComplete).toHaveBeenCalledTimes(1);
  });
});
