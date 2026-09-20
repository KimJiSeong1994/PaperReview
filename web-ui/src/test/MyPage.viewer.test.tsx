import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import MyPage from '../components/MyPage';

// MyPage is wiring; every panel and hook is replaced so the test sees only the
// wiring: which tab renders, what the URL says, what the report is handed.
const bm = {
  bookmarks: [], filteredBookmarks: [], topicGroups: {}, allTopics: [], chatBookmarkIds: [],
  selectedBookmark: null, bookmarkDetail: null, loadingBookmarks: false, loadingDetail: false,
  selectedIds: new Set<string>(), searchQuery: '', allNotesMode: false, topicAccordionOpen: {},
  loadBookmarks: vi.fn(), setBookmarks: vi.fn(), setBookmarkDetail: vi.fn(), handleSelectBookmark: vi.fn(),
};
const hl = { initFromDetail: vi.fn(), setHighlightPopover: vi.fn(), userHighlights: [], sortedHighlights: [] };
const chat = { highlightTerms: [], setHighlightTerms: vi.fn(), scrollToHighlight: false, setScrollToHighlight: vi.fn(), messages: [] };
const reportSpy = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useBookmarks', () => ({ useBookmarks: () => bm }));
vi.mock('../hooks/useHighlights', () => ({ useHighlights: () => hl }));
vi.mock('../hooks/useExploration', () => ({ useExploration: () => ({}) }));
vi.mock('../hooks/useChat', () => ({ useChat: () => chat }));
vi.mock('../components/mypage/BookmarkSidebar', () => ({ default: () => <div data-testid="sidebar" /> }));
vi.mock('../components/mypage/ReportViewer', () => ({
  default: (props: Record<string, unknown>) => { reportSpy(props); return <div data-testid="report" />; },
}));
vi.mock('../components/mypage/ChatPanel', () => ({ default: () => <div data-testid="chat" /> }));
const viewerMounts = vi.hoisted(() => ({ count: 0 }));
vi.mock('../components/mypage/PaperViewerPanel', async () => {
  const { useEffect } = await import('react');
  function ViewerStub() {
    useEffect(() => { viewerMounts.count += 1; }, []);
    return <div data-testid="viewer" />;
  }
  return { default: ViewerStub };
});
vi.mock('../components/AgentKeyButton', () => ({ default: () => null }));
vi.mock('../components/RecommendationBell', () => ({ default: () => null }));

function Probe() {
  const location = useLocation();
  return <output data-testid="probe">{location.pathname}{location.search}|{location.state === null ? 'null' : 'state'}</output>;
}

const renderAt = (entry: string | { pathname: string; state: unknown }) => render(
  <MemoryRouter initialEntries={[entry]}>
    <MyPage onBack={() => {}} />
    <Probe />
  </MemoryRouter>,
);

beforeEach(() => { vi.clearAllMocks(); viewerMounts.count = 0; });

describe('MyPage tab wiring', () => {
  it('sends the old ?tab=curriculum link on to the curriculum route without fetching first', async () => {
    // Rendered through routes, as in the app: the redirect swaps the page out,
    // so MyPage must not have asked for bookmarks on its way to the exit.
    render(
      <MemoryRouter initialEntries={['/mypage?tab=curriculum']}>
        <Routes>
          <Route path="/mypage" element={<MyPage onBack={() => {}} />} />
          <Route path="/curriculum" element={<div data-testid="curriculum-route" />} />
        </Routes>
        <Probe />
      </MemoryRouter>,
    );
    await screen.findByTestId('curriculum-route');
    expect(screen.getByTestId('probe')).toHaveTextContent('/curriculum|null');
    expect(bm.loadBookmarks).not.toHaveBeenCalled();
  });

  it('keeps the curriculum link beside the tablist, not inside it', async () => {
    renderAt('/mypage');
    await screen.findByTestId('report');
    const link = screen.getByRole('link', { name: '커리큘럼' });
    expect(link.closest('[role="tablist"]')).toBeNull();
    expect(screen.getAllByRole('tab')).toHaveLength(2);
  });

  it('the PDF tab drops the chat row from the content grid; the bookmarks tab keeps it', async () => {
    const { unmount } = renderAt('/mypage?tab=papers');
    await screen.findByTestId('viewer');
    expect(document.querySelector('.mypage-content--viewer')).not.toBeNull();
    unmount();

    renderAt('/mypage');
    await screen.findByTestId('report');
    expect(document.querySelector('.mypage-content--viewer')).toBeNull();
    expect(document.querySelector('.mypage-content')).not.toBeNull();
    expect(screen.getByTestId('chat')).toBeInTheDocument();
  });

  it('is a real tablist: Korean names, the default first, arrows move and open', async () => {
    renderAt('/mypage');
    await screen.findByTestId('report');
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent)).toEqual(['북마크', '논문 PDF']);
    expect(screen.getByRole('link', { name: '커리큘럼' })).toHaveAttribute('href', '/curriculum');
    expect(screen.getByRole('tab', { name: '북마크' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByRole('button', { name: 'My Page' })).not.toBeInTheDocument();
    expect(screen.getByRole('tabpanel', { name: '북마크' })).toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole('tab', { name: '북마크' }), { key: 'ArrowRight' });
    expect(await screen.findByTestId('viewer')).toBeVisible();
    expect(screen.getByTestId('report')).not.toBeVisible();
    expect(screen.getByRole('tab', { name: '논문 PDF' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: '논문 PDF' })).toHaveFocus();
    expect(screen.getByTestId('probe')).toHaveTextContent('/mypage?tab=papers|');

    fireEvent.keyDown(screen.getByRole('tab', { name: '논문 PDF' }), { key: 'End' });
    expect(screen.getByRole('tab', { name: '논문 PDF' })).toHaveAttribute('aria-selected', 'true');
  });

  it('seeds the roving tabindex from the URL and wraps at both ends', async () => {
    renderAt('/mypage?tab=papers');
    await screen.findByTestId('viewer');
    expect(screen.getAllByRole('tab').map((tab) => tab.getAttribute('tabindex'))).toEqual(['-1', '0']);

    fireEvent.keyDown(screen.getByRole('tab', { name: '논문 PDF' }), { key: 'ArrowLeft' });
    await screen.findByTestId('report');
    expect(screen.getByRole('tab', { name: '북마크' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('probe')).toHaveTextContent(/^\/mypage\|/);

    fireEvent.keyDown(screen.getByRole('tab', { name: '북마크' }), { key: 'ArrowLeft' });
    expect(await screen.findByTestId('viewer')).toBeVisible();
    expect(screen.getByRole('tab', { name: '논문 PDF' })).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(screen.getByRole('tab', { name: '논문 PDF' }), { key: 'Home' });
    await screen.findByTestId('report');
    expect(screen.getAllByRole('tab').map((tab) => tab.getAttribute('tabindex'))).toEqual(['0', '-1']);
  });

  it('keeps the PDF viewer mounted across tab switches, and does not mount it for bookmark-only visits', async () => {
    renderAt('/mypage');
    await screen.findByTestId('report');
    expect(screen.queryByTestId('viewer')).toBeNull();
    expect(viewerMounts.count).toBe(0);

    fireEvent.click(screen.getByRole('tab', { name: '논문 PDF' }));
    expect(await screen.findByTestId('viewer')).toBeVisible();
    fireEvent.click(screen.getByRole('tab', { name: '북마크' }));
    expect(await screen.findByTestId('report')).toBeVisible();
    expect(screen.getByTestId('viewer')).not.toBeVisible();
    fireEvent.click(screen.getByRole('tab', { name: '논문 PDF' }));
    expect(await screen.findByTestId('viewer')).toBeVisible();
    // Same instance throughout: a remount would have thrown away the document, zoom and highlights.
    expect(viewerMounts.count).toBe(1);
    expect(screen.getByRole('tabpanel', { name: '논문 PDF' })).toBeInTheDocument();
    expect(screen.queryByRole('tabpanel', { name: '북마크' })).toBeNull();

  });

  it('hands the report the real popover setter instead of a no-op', async () => {
    renderAt('/mypage');
    await screen.findByTestId('report');
    expect(reportSpy.mock.lastCall![0].setHighlightPopover).toBe(hl.setHighlightPopover);
  });
});
