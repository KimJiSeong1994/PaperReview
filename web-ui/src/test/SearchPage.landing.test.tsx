import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SearchPage from '../components/SearchPage';
import { searchPapers } from '../api/client';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const authState = vi.hoisted(() => ({
  isAuthenticated: false,
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
    trackSearchClick: vi.fn(),
  };
});

vi.mock('../hooks/useDeepReview', () => ({
  useDeepReview: () => ({
    reviewStatus: 'idle',
    reviewProgress: '',
    reviewReport: null,
    reviewSessionId: null,
    startReview: vi.fn(),
    resetReview: vi.fn(),
  }),
}));

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

function renderHome() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <SearchPage />
    </MemoryRouter>,
  );
}

describe('homepage landing content', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.scrollTo = vi.fn();
    // jsdom implements neither; the results view calls both.
    Element.prototype.scrollIntoView = vi.fn();
    vi.mocked(searchPapers).mockResolvedValue({ results: {}, total: 0 } as never);
  });

  it('offers four example queries under the search box', () => {
    renderHome();
    expect(screen.getAllByRole('button', { name: /./ }).length).toBeGreaterThan(0);
    expect(document.querySelectorAll('.home-chip')).toHaveLength(4);
    expect(screen.getByRole('list', { name: '예시 검색어' })).toBeTruthy();
  });

  // The chips exist to start a search, so the wiring is the whole point: a chip
  // that renders but does not search is worse than no chip. IntroducePage routes
  // the same strings through ?q= because it sits on another route; here we are
  // already on "/", so the call must go straight to handleSearch.
  it('runs the query when a chip is clicked', async () => {
    renderHome();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '그래프 신경망' }));
    });
    // searchPapers takes (payload, abortSignal), so assert on the payload
    // rather than the whole argument list.
    expect(searchPapers).toHaveBeenCalledTimes(1);
    expect(vi.mocked(searchPapers).mock.calls[0][0]).toMatchObject({
      query: '그래프 신경망',
    });
  });

  it('shows one comparison query, not four topic keywords', () => {
    renderHome();
    // Verified against QueryAnalyzer.analyze_query: this one classifies as
    // intent=comparison (conf 0.97) where the bare topic nouns classify as
    // topic_exploration. It is here to show the corpus answers comparisons,
    // not because it is faster — nothing reachable through this analyzer is.
    expect(screen.getByRole('button', { name: 'GraphRAG와 기존 RAG 비교' })).toBeTruthy();
  });

  it('keeps the brand h1 byte-identical to the pre-hydration copy', () => {
    renderHome();
    // web-ui/index.html ships this exact H1 before React mounts. If they drift,
    // JS-rendering and non-JS crawlers see different headings for the same URL.
    expect(document.querySelector('h1.brand-title')?.textContent?.trim()).toBe(
      'Jiphyeonjeon (집현전)',
    );
  });

  it('shows three public reviews under the first h2 on the page', () => {
    renderHome();
    const cards = [...document.querySelectorAll<HTMLAnchorElement>('.home-output')];
    expect(cards).toHaveLength(3);
    for (const card of cards) {
      expect(card.getAttribute('href')?.startsWith('/blog/')).toBe(true);
    }

    // Heading order: the brand h1, then this section's h2, and no h3 skipping
    // in between. The page had exactly one heading before this section existed.
    const headings = [...document.querySelectorAll('h1, h2, h3')].map((h) => h.tagName);
    expect(headings).toEqual(['H1', 'H2']);
    expect(screen.getByRole('heading', { level: 2, name: '공개 리뷰' })).toBeTruthy();
    expect(
      screen.getByRole('link', { name: '공개 리뷰 전체 보기' }).getAttribute('href'),
    ).toBe('/blog/category/paper-review');
  });

  // The section is a sibling of .centered-search rather than a child, so that
  // it does not compete with the hero's ::after artwork for flex space (which
  // collapsed the artwork to 0px at 1280x900). Being a sibling means it needs
  // its own render condition — without it, the reviews sat under live results.
  it('disappears once results are on screen', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: { arxiv: [{ doc_id: 'p1', title: 'A Paper', authors: ['X'], year: 2026, abstract: 'a' }] },
      total: 1,
    } as never);

    renderHome();
    expect(document.querySelectorAll('.home-output')).toHaveLength(3);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '그래프 신경망' }));
    });

    expect(document.querySelector('.home-proof')).toBeNull();
    expect(document.querySelectorAll('.home-output')).toHaveLength(0);
  });

  it('says search needs no login, and offers a way to read more', () => {
    renderHome();
    expect(screen.getByText('검색은 로그인 없이 바로 시작할 수 있습니다.')).toBeTruthy();
    expect(
      screen.getByRole('link', { name: '집현전 사용법 자세히 보기' }).getAttribute('href'),
    ).toBe('/ko/introduce/');
  });
});
