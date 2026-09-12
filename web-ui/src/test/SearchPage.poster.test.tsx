import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SearchPage from '../components/SearchPage';
import { fetchBatchReferences, generatePoster, getGraphData, searchPapers } from '../api/client';
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
const authState = vi.hoisted(() => ({ isAuthenticated: true, setShowLoginModal: vi.fn() }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => authState }));
vi.mock('../analytics/events', () => ({
  trackBookmarkSave: vi.fn(),
  trackDeepReviewComplete: vi.fn(),
  trackDeepReviewFail: vi.fn(),
  trackDeepReviewStart: vi.fn(),
  trackPaperSelect: vi.fn(),
  trackPosterGenerateComplete: vi.fn(),
  trackPosterGenerateFail: vi.fn(),
  trackPosterGenerateStart: vi.fn(),
  trackReportDownload: vi.fn(),
  trackSearchEvent: vi.fn(),
}));

async function submitSearch(query: string) {
  await act(async () => {
    fireEvent.change(screen.getByPlaceholderText('Search papers...'), { target: { value: query } });
    fireEvent.click(screen.getByTitle('Search'));
  });
}

/** Search, then open the poster through the tools menu — the trigger the menu hands focus back to. */
async function openPoster() {
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

  const view = render(
    <MemoryRouter initialEntries={['/']}>
      <SearchPage />
    </MemoryRouter>,
  );
  await submitSearch('poster accessibility');
  await waitFor(() => expect(getGraphData).toHaveBeenCalledTimes(1));

  await act(async () => {
    fireEvent.click(await screen.findByRole('button', { name: /tools/i }));
  });
  await act(async () => {
    fireEvent.click(await screen.findByRole('button', { name: /generate poster/i }));
  });
  await screen.findByTitle('Poster Preview');
  return view;
}

describe('Poster modal accessibility', () => {
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
    } as never);
    vi.mocked(getGraphData).mockResolvedValue({ nodes: [], edges: [] });
    vi.mocked(fetchBatchReferences).mockResolvedValue({ references: [] });
    vi.mocked(generatePoster).mockResolvedValue({
      success: true,
      session_id: 'review-session-1',
      poster_status: 'succeeded',
      poster_html: '<html>poster</html>',
      poster_path: '/poster.html',
    });
  });

  it('names the dialog and its close button, and focuses into the dialog when it opens', async () => {
    await openPoster();

    const dialog = screen.getByRole('dialog', { name: 'Conference Poster' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(document.activeElement).toBe(dialog);
    // The × glyph alone announces nothing.
    expect(screen.getByRole('button', { name: 'Close poster' })).toBeInTheDocument();
  });

  it('closes on Escape and returns focus to the trigger', async () => {
    await openPoster();

    await act(async () => {
      fireEvent.keyDown(document, { key: 'Escape' });
    });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /tools/i }));
  });

  it('returns focus to the trigger when closed with the close button', async () => {
    await openPoster();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Close poster' }));
    });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /tools/i }));
  });
});

// The response HTML is the only copy: nothing persists it server-side, so a
// discarded poster costs another run of up to POSTER_TIMEOUT_SECONDS (240s).
describe('Poster survives closing the modal', () => {
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
    } as never);
    vi.mocked(getGraphData).mockResolvedValue({ nodes: [], edges: [] });
    vi.mocked(fetchBatchReferences).mockResolvedValue({ references: [] });
    vi.mocked(generatePoster).mockResolvedValue({
      success: true,
      session_id: 'review-session-1',
      poster_status: 'succeeded',
      poster_html: '<html>poster</html>',
      poster_path: '/poster.html',
    });
  });

  it.each([
    ['the close button', () => fireEvent.click(screen.getByRole('button', { name: 'Close poster' }))],
    ['the overlay', () => fireEvent.click(document.querySelector('.poster-modal-overlay') as HTMLElement)],
    ['Escape', () => fireEvent.keyDown(document, { key: 'Escape' })],
  ])('reopens the same poster after closing with %s', async (_label, close) => {
    await openPoster();

    await act(async () => {
      close();
    });
    expect(screen.queryByTitle('Poster Preview')).not.toBeInTheDocument();

    // Reopening must not pay for a second run.
    await act(async () => {
      fireEvent.click(await screen.findByRole('button', { name: /tools/i }));
    });
    await act(async () => {
      fireEvent.click(await screen.findByRole('button', { name: 'View Poster' }));
    });

    expect(await screen.findByTitle('Poster Preview')).toHaveAttribute(
      'srcdoc',
      '<html>poster</html>',
    );
    expect(generatePoster).toHaveBeenCalledTimes(1);
  });

  it('still returns focus to the trigger when a reopened poster is closed', async () => {
    await openPoster();
    await act(async () => {
      fireEvent.keyDown(document, { key: 'Escape' });
    });

    await act(async () => {
      fireEvent.click(await screen.findByRole('button', { name: /tools/i }));
    });
    await act(async () => {
      fireEvent.click(await screen.findByRole('button', { name: 'View Poster' }));
    });
    expect(document.activeElement).toBe(screen.getByRole('dialog', { name: 'Conference Poster' }));

    await act(async () => {
      fireEvent.keyDown(document, { key: 'Escape' });
    });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /tools/i }));
  });

  it('drops the poster on logout so the next user cannot reopen it', async () => {
    // logout() never unmounts a SearchPage already sitting on '/', so a poster
    // that now outlives its modal would otherwise still be one click away for
    // whoever logs in next on this device.
    const { rerender } = await openPoster();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Close poster' }));
    });

    authState.isAuthenticated = false;
    rerender(
      <MemoryRouter initialEntries={['/']}>
        <SearchPage />
      </MemoryRouter>,
    );

    await act(async () => {
      fireEvent.click(await screen.findByRole('button', { name: /tools/i }));
    });
    expect(screen.queryByRole('button', { name: 'View Poster' })).not.toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Generate Poster' })).toBeInTheDocument();
    expect(screen.queryByTitle('Poster Preview')).not.toBeInTheDocument();
  });
});
