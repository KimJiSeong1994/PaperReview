import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SearchPage from '../components/SearchPage';
import { searchPapers } from '../api/client';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const authState = vi.hoisted(() => ({ isAuthenticated: false, setShowLoginModal: vi.fn() }));

vi.mock('../api/client', async () => {
  const reviewApi = await vi.importActual<typeof import('../api/review')>('../api/review');
  return {
    classifyPosterError: reviewApi.classifyPosterError,
    classifyPosterResponse: reviewApi.classifyPosterResponse,
    fetchBatchReferences: vi.fn(), generatePoster: vi.fn(), generatePosterDirect: vi.fn(),
    getGraphData: vi.fn(), saveBookmark: vi.fn(), searchPapers: vi.fn(),
    startDeepReview: vi.fn(), trackSearchClick: vi.fn(),
  };
});
vi.mock('../hooks/useDeepReview', () => ({
  useDeepReview: () => ({ reviewStatus: 'idle', reviewProgress: '', reviewReport: null,
    reviewSessionId: null, startReview: vi.fn(), resetReview: vi.fn() }),
}));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => authState }));
vi.mock('../analytics/events', () => ({
  trackBookmarkSave: vi.fn(), trackDeepReviewComplete: vi.fn(), trackDeepReviewFail: vi.fn(),
  trackDeepReviewStart: vi.fn(), trackPaperSelect: vi.fn(), trackPosterGenerateComplete: vi.fn(),
  trackPosterGenerateFail: vi.fn(), trackPosterGenerateStart: vi.fn(),
  trackReportDownload: vi.fn(), trackSearchEvent: vi.fn(),
}));

function renderPage() {
  return render(<MemoryRouter initialEntries={['/']}><SearchPage /></MemoryRouter>);
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

async function submit(q: string) {
  await act(async () => {
    fireEvent.change(screen.getByPlaceholderText('논문 검색'), { target: { value: q } });
    fireEvent.click(screen.getByRole('button', { name: '논문 검색' }));
  });
}

const paper = { doc_id: 'p1', title: 'A Paper', authors: ['X'], year: 2026, abstract: 'a' };

describe('SearchPage honest states', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.scrollTo = vi.fn();
    Element.prototype.scrollIntoView = vi.fn();
  });
  afterEach(() => { vi.useRealTimers(); });

  // A search runs for up to 100s. Every branch that renders a field was gated
  // on !loading, so for that whole time there was no way to fix a typo or bail.
  it('keeps a usable search box on screen while the request is in flight', async () => {
    const first = deferred<unknown>();
    vi.mocked(searchPapers).mockReturnValueOnce(first.promise as never);
    renderPage();
    await submit('graph nueral netwroks');
    await act(async () => { vi.advanceTimersByTime(600); });

    const field = screen.getByPlaceholderText('논문 검색') as HTMLInputElement;
    expect(field).not.toBeDisabled();
    expect(field.value).toBe('graph nueral netwroks');

    // and it actually starts a new search, which aborts the one in flight
    vi.mocked(searchPapers).mockReturnValueOnce(deferred<unknown>().promise as never);
    await submit('graph neural networks');
    expect(searchPapers).toHaveBeenCalledTimes(2);
    expect(vi.mocked(searchPapers).mock.calls[1][0]).toMatchObject({
      query: 'graph neural networks',
    });
  });

  // Zero results and "every source timed out" are different facts. The UI read
  // only is_academic, so a backend that never answered was reported to the user
  // as their keywords being wrong.
  it('names the sources that timed out instead of blaming the query', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: {}, total: 0, source_timeouts: { arxiv: true, openalex: true, dblp: false },
    } as never);
    renderPage();
    await submit('graph neural networks');

    expect(screen.queryByText(/다른 키워드로 시도해보세요/)).toBeNull();
    expect(screen.getByText(/2개 출처가 제때 응답하지 않아/)).toBeTruthy();
    expect(screen.getByText(/arxiv, openalex/)).toBeTruthy();
  });

  it('still blames nothing in particular when the sources simply found nothing', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: {}, total: 0, source_timeouts: { arxiv: false },
    } as never);
    renderPage();
    await submit('graph neural networks');
    expect(screen.getByText(/검색 결과가 없습니다/)).toBeTruthy();
  });

  // The loading branch's live region unmounts when loading ends, so without
  // this a screen-reader user who searched and got nothing was told nothing.
  it('announces the empty state', async () => {
    vi.mocked(searchPapers).mockResolvedValue({ results: {}, total: 0 } as never);
    renderPage();
    await submit('graph neural networks');
    const empty = document.querySelector('.empty-state');
    expect(empty?.getAttribute('role')).toBe('status');
    expect(empty?.getAttribute('aria-live')).toBe('polite');
  });

  it('shows what was actually searched when the analyzer rewrote it', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: { arxiv: [paper] }, total: 1,
      query_analysis: { improved_query: 'graph neural network representation learning' },
    } as never);
    renderPage();
    await submit('GNN');
    expect(screen.getByText('graph neural network representation learning')).toBeTruthy();
  });

  it('stays quiet when the rewrite is the query', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: { arxiv: [paper] }, total: 1,
      query_analysis: { improved_query: 'graph neural networks' },
    } as never);
    renderPage();
    await submit('graph neural networks');
    expect(document.querySelector('.results-rewritten-query')).toBeNull();
  });
});
