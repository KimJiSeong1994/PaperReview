import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  trackPosterGenerateFail,
  trackPosterGenerateStart,
  trackSearchEvent,
} from '../analytics/events';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const authState = vi.hoisted(() => ({
  isAuthenticated: true,
  setShowLoginModal: vi.fn(),
}));

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
  };
});

vi.mock('../hooks/useDeepReview', () => ({
  useDeepReview: vi.fn(),
}));

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => authState,
}));

vi.mock('../analytics/events', () => ({
  trackBookmarkSave: vi.fn(),
  trackDeepReviewComplete: vi.fn(),
  trackDeepReviewStart: vi.fn(),
  trackPosterGenerateComplete: vi.fn(),
  trackPosterGenerateFail: vi.fn(),
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


function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function submitSearch(query: string) {
  await act(async () => {
    fireEvent.change(screen.getByPlaceholderText('Search papers...'), {
      target: { value: query },
    });
    fireEvent.click(screen.getByTitle('Search'));
  });
}

async function renderPosterReadySearch() {
  vi.mocked(searchPapers).mockResolvedValue({
    results: {
      arxiv: [{
        doc_id: 'paper-1',
        title: 'Poster Paper',
        authors: ['A. Researcher'],
        year: 2026,
        abstract: 'abstract',
      }],
    },
    total: 1,
  });

  renderSearchPage();
  await submitSearch('poster analytics');

  expect(await screen.findAllByText('Poster Paper')).toHaveLength(2);
  await waitFor(() => expect(getGraphData).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(fetchBatchReferences).toHaveBeenCalledTimes(1));

  await act(async () => {
    fireEvent.click(await screen.findByRole('button', { name: /tools/i }));
  });
  await act(async () => {
    fireEvent.click(await screen.findByRole('button', { name: /generate poster/i }));
  });
}

async function expectPosterMenuReady() {
  const posterPreview = screen.queryByTitle('Poster Preview');
  if (posterPreview) {
    await act(async () => {
      fireEvent.click(screen.getByText('✕'));
    });
    await waitFor(() => expect(screen.queryByTitle('Poster Preview')).not.toBeInTheDocument());
  }

  await act(async () => {
    fireEvent.click(await screen.findByRole('button', { name: /tools/i }));
  });
  const generateButton = await screen.findByRole('button', { name: /generate poster/i });
  expect(generateButton).toBeEnabled();
  expect(generateButton).toHaveTextContent('Generate Poster');
}

describe('SearchPage analytics instrumentation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.isAuthenticated = true;
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
      expect(trackSearchEvent).toHaveBeenCalledWith(
        'private raw paper title',
        'non_academic',
        0,
        'home',
        expect.objectContaining({ searchId: expect.any(String) }),
      );
    });

    // The wrapper is what keeps the query out of analytics: the raw text is an
    // argument to it, never a field it forwards. The impression id must be
    // random rather than derived from the query, or it would smuggle the text
    // back in as a reversible hash.
    const impression = vi.mocked(trackSearchEvent).mock.calls[0][4];
    expect(JSON.stringify(impression)).not.toContain('private raw paper title');
    expect(impression?.searchId).not.toContain('private');
  });

  it('shows an accessible library-search status for a search that takes longer than the flash threshold', async () => {
    const searchDeferred = createDeferred<{
      query_analysis: { is_academic: false };
      results: Record<string, never>;
    }>();
    vi.mocked(searchPapers).mockReturnValue(searchDeferred.promise as never);

    renderSearchPage();
    await submitSearch('slow academic search');

    const status = await screen.findByRole('status', {}, { timeout: 1200 });
    expect(status).toHaveTextContent('집현전 서고 탐색 중');
    expect(status).toHaveTextContent('질문과 맞닿은 논문을 찾고 있습니다');
    expect(status.querySelector('.search-loading-illustration')).toHaveAttribute('aria-hidden', 'true');

    searchDeferred.resolve({
      query_analysis: { is_academic: false },
      results: {},
    });
  });


  it('renders primary search results before graph and reference enrichment finish', async () => {
    const graphDeferred = createDeferred<{ nodes: []; edges: [] }>();
    const refsDeferred = createDeferred<{ references: [] }>();

    vi.mocked(searchPapers).mockResolvedValue({
      results: {
        arxiv: [{
          doc_id: 'paper-1',
          title: 'Fast Primary Result',
          authors: ['A. Researcher'],
          year: 2026,
          abstract: 'abstract',
        }],
      },
      total: 1,
    });
    vi.mocked(getGraphData).mockReturnValue(graphDeferred.promise);
    vi.mocked(fetchBatchReferences).mockReturnValue(refsDeferred.promise);

    renderSearchPage();
    await submitSearch('fast result rendering');

    expect(vi.mocked(searchPapers).mock.calls[0][0]).not.toHaveProperty('fast_mode');
    expect(await screen.findAllByText('Fast Primary Result')).toHaveLength(2);
    expect(screen.getByPlaceholderText('Search papers...')).not.toBeDisabled();
    expect(getGraphData).toHaveBeenCalledTimes(1);
    expect(fetchBatchReferences).toHaveBeenCalledTimes(1);

    graphDeferred.resolve({ nodes: [], edges: [] });
    refsDeferred.resolve({ references: [] });
  });

  it('keeps anonymous graph search public without protected reference enrichment', async () => {
    authState.isAuthenticated = false;
    vi.mocked(searchPapers).mockResolvedValue({
      results: {
        arxiv: [{
          doc_id: 'paper-public',
          title: 'Public Graph Result',
          authors: ['A. Researcher'],
          year: 2026,
          abstract: 'abstract',
        }],
      },
      total: 1,
    });

    renderSearchPage();
    await submitSearch('public graph search');

    await waitFor(() => expect(getGraphData).toHaveBeenCalledTimes(1));
    expect(fetchBatchReferences).not.toHaveBeenCalled();
    expect(authState.setShowLoginModal).not.toHaveBeenCalled();
  });

  it('tracks poster completion for a succeeded V2 session poster', async () => {
    vi.mocked(generatePoster).mockResolvedValue({
      success: true,
      session_id: 'review-session-1',
      poster_status: 'succeeded',
      poster_html: '<html>poster</html>',
      poster_path: '/poster.html',
    });

    await renderPosterReadySearch();

    expect(await screen.findByTitle('Poster Preview')).toHaveAttribute('sandbox', '');
    expect(generatePosterDirect).not.toHaveBeenCalled();
    expect(trackPosterGenerateStart).toHaveBeenCalledTimes(1);
    expect(trackPosterGenerateComplete).toHaveBeenCalledWith('succeeded');
    expect(trackPosterGenerateFail).not.toHaveBeenCalled();
    await expectPosterMenuReady();
  });

  it('previews degraded posters with a visible warning without complete analytics', async () => {
    vi.mocked(generatePoster).mockResolvedValue({
      success: true,
      session_id: 'review-session-1',
      poster_status: 'degraded',
      poster_html: '<html>poster</html>',
      poster_path: '/poster.html',
      warnings: ['Some source figures were omitted.'],
    });

    await renderPosterReadySearch();

    expect(await screen.findByTitle('Poster Preview')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Some source figures were omitted.');
    expect(generatePosterDirect).not.toHaveBeenCalled();
    expect(trackPosterGenerateComplete).not.toHaveBeenCalled();
    expect(trackPosterGenerateFail).toHaveBeenCalledWith('degraded');
    await expectPosterMenuReady();
  }, 10_000);

  it('tracks failed poster statuses without falling back to direct generation', async () => {
    vi.mocked(generatePoster).mockResolvedValue({
      success: false,
      session_id: 'review-session-1',
      poster_status: 'failed',
      error: 'Poster render failed',
    });

    await renderPosterReadySearch();

    await waitFor(() => {
      expect(trackPosterGenerateFail).toHaveBeenCalledWith('failed');
    });
    expect(generatePosterDirect).not.toHaveBeenCalled();
    expect(trackPosterGenerateComplete).not.toHaveBeenCalled();
    expect(screen.queryByTitle('Poster Preview')).not.toBeInTheDocument();
    await expectPosterMenuReady();
  });

  it.each(['timeout', 'active', 'rate_limited', 'unknown'] as const)(
    'does not use direct fallback for %s poster error_code',
    async (errorCode) => {
      vi.mocked(generatePoster).mockRejectedValue({
        response: {
          data: {
            detail: {
              error_code: errorCode,
              message: `${errorCode} status`,
              poster_status: errorCode,
            },
          },
        },
      });

      await renderPosterReadySearch();

      await waitFor(() => {
        expect(trackPosterGenerateFail).toHaveBeenCalledWith(errorCode);
      });
      expect(generatePosterDirect).not.toHaveBeenCalled();
      expect(trackPosterGenerateComplete).not.toHaveBeenCalled();
    },
  );

  it('maps structured poster_rate_limited errors to rate_limited without fallback and clears spinner', async () => {
    vi.mocked(generatePoster).mockRejectedValue({
      response: {
        status: 429,
        data: {
          detail: {
            error_code: 'poster_rate_limited',
            message: 'Poster generation rate limited',
            retryable: true,
          },
        },
      },
    });

    await renderPosterReadySearch();

    await waitFor(() => {
      expect(trackPosterGenerateFail).toHaveBeenCalledWith('rate_limited');
    });
    expect(generatePosterDirect).not.toHaveBeenCalled();
    expect(trackPosterGenerateComplete).not.toHaveBeenCalled();
    await expectPosterMenuReady();
  });

  it('uses direct fallback only for a structured poster_session_unavailable error_code', async () => {
    vi.mocked(generatePoster).mockRejectedValue({
      response: {
        status: 404,
        data: {
          detail: {
            error_code: 'poster_session_unavailable',
            generation_id: 'poster-generation-1',
            message: 'Poster session unavailable',
            poster_status: 'failed',
            retryable: false,
          },
        },
      },
    });
    vi.mocked(generatePosterDirect).mockResolvedValue({
      success: true,
      session_id: 'review-session-1',
      poster_status: 'succeeded',
      poster_html: '<html>poster</html>',
      poster_path: '/poster.html',
    });

    await renderPosterReadySearch();

    await waitFor(() => {
      expect(generatePosterDirect).toHaveBeenCalledWith('review report markdown', 0);
    });
    expect(trackPosterGenerateStart).toHaveBeenCalledTimes(1);
    expect(trackPosterGenerateComplete).toHaveBeenCalledWith('succeeded');
  });

  it('does not use direct fallback for a plain ownership-like 404 without explicit error_code', async () => {
    vi.mocked(generatePoster).mockRejectedValue({
      response: {
        status: 404,
        data: { detail: 'Session not found' },
      },
    });

    await renderPosterReadySearch();

    await waitFor(() => {
      expect(trackPosterGenerateFail).toHaveBeenCalledWith('unknown');
    });
    expect(generatePosterDirect).not.toHaveBeenCalled();
    expect(trackPosterGenerateComplete).not.toHaveBeenCalled();
    await expectPosterMenuReady();
  });
});
