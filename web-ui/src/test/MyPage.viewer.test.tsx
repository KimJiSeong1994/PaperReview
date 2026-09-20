import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
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
const cur = { loadingCourse: false, presetCourses: [], myCourses: [], readPapers: new Set<string>() };
const reportSpy = vi.hoisted(() => vi.fn());
const viewerSpy = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useBookmarks', () => ({ useBookmarks: () => bm }));
vi.mock('../hooks/useHighlights', () => ({ useHighlights: () => hl }));
vi.mock('../hooks/useExploration', () => ({ useExploration: () => ({}) }));
vi.mock('../hooks/useChat', () => ({ useChat: () => chat }));
vi.mock('../hooks/useCurriculum', () => ({ useCurriculum: () => cur }));
vi.mock('../components/mypage/BookmarkSidebar', () => ({ default: () => <div data-testid="sidebar" /> }));
vi.mock('../components/mypage/ReportViewer', () => ({
  default: (props: Record<string, unknown>) => { reportSpy(props); return <div data-testid="report" />; },
}));
vi.mock('../components/mypage/ChatPanel', () => ({ default: () => <div data-testid="chat" /> }));
vi.mock('../components/mypage/PaperViewerPanel', () => ({
  default: (props: Record<string, unknown>) => { viewerSpy(props); return <div data-testid="viewer" />; },
}));
vi.mock('../components/curriculum/CourseSidebar', () => ({ default: () => <div data-testid="courses" /> }));
vi.mock('../components/curriculum/ModuleView', () => ({ default: () => null }));
vi.mock('../components/curriculum/CurriculumDetailPanel', () => ({
  default: ({ onViewPaper }: { onViewPaper: (paper: { title: string; authors: string[] }) => void }) => (
    <button type="button" onClick={() => onViewPaper({ title: 'Attention Is All You Need', authors: ['Vaswani'] })}>View Paper</button>
  ),
}));
vi.mock('../components/AgentKeyButton', () => ({ default: () => null }));
vi.mock('../components/RecommendationBell', () => ({ default: () => null }));

function Probe() {
  const location = useLocation();
  return <output data-testid="probe">{location.search}|{location.state === null ? 'null' : 'state'}</output>;
}

const renderAt = (entry: string | { pathname: string; state: unknown }) => render(
  <MemoryRouter initialEntries={[entry]}>
    <MyPage onBack={() => {}} />
    <Probe />
  </MemoryRouter>,
);

beforeEach(() => vi.clearAllMocks());

describe('MyPage tab wiring', () => {
  it('arriving with a paper in router state lands on the PDF tab, records it in the URL and drops the state', async () => {
    renderAt({ pathname: '/mypage', state: { viewPaper: { title: 'T', authors: [] } } });
    await screen.findByTestId('viewer');
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('?tab=papers|null'));
    expect(screen.getByText('T')).toBeInTheDocument();
    // Opened once: the effect re-runs after it writes the URL, and must not build a second paper.
    const details = new Set(viewerSpy.mock.calls.map((call) => (call[0] as { bookmarkDetail: unknown }).bookmarkDetail));
    expect(details.size).toBe(1);
  });

  it("the curriculum's View Paper goes through the URL too", async () => {
    renderAt('/mypage?tab=curriculum');
    fireEvent.click(await screen.findByRole('button', { name: 'View Paper' }));
    await screen.findByTestId('viewer');
    expect(screen.getByTestId('probe')).toHaveTextContent('?tab=papers|null');
    expect(screen.getByText('Attention Is All You Need')).toBeInTheDocument();
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
    expect(tabs.map((tab) => tab.textContent)).toEqual(['북마크', '논문 PDF', '커리큘럼']);
    expect(screen.getByRole('tab', { name: '북마크' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByRole('button', { name: 'My Page' })).not.toBeInTheDocument();
    expect(screen.getByRole('tabpanel', { name: '북마크' })).toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole('tab', { name: '북마크' }), { key: 'ArrowRight' });
    await screen.findByTestId('viewer');
    expect(screen.getByRole('tab', { name: '논문 PDF' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: '논문 PDF' })).toHaveFocus();
    expect(screen.getByTestId('probe')).toHaveTextContent('?tab=papers|');

    fireEvent.keyDown(screen.getByRole('tab', { name: '논문 PDF' }), { key: 'End' });
    await screen.findByTestId('courses');
    expect(screen.getByRole('tabpanel', { name: '커리큘럼' })).toBeInTheDocument();
  });

  it('seeds the roving tabindex from the URL and wraps at both ends', async () => {
    renderAt('/mypage?tab=papers');
    await screen.findByTestId('viewer');
    expect(screen.getAllByRole('tab').map((tab) => tab.getAttribute('tabindex'))).toEqual(['-1', '0', '-1']);

    fireEvent.keyDown(screen.getByRole('tab', { name: '논문 PDF' }), { key: 'ArrowLeft' });
    await screen.findByTestId('report');
    expect(screen.getByRole('tab', { name: '북마크' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('probe')).toHaveTextContent(/^\|/);

    fireEvent.keyDown(screen.getByRole('tab', { name: '북마크' }), { key: 'ArrowLeft' });
    await screen.findByTestId('courses');
    expect(screen.getByRole('tab', { name: '커리큘럼' })).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(screen.getByRole('tab', { name: '커리큘럼' }), { key: 'Home' });
    await screen.findByTestId('report');
    expect(screen.getAllByRole('tab').map((tab) => tab.getAttribute('tabindex'))).toEqual(['0', '-1', '-1']);
  });

  it('hands the report the real popover setter instead of a no-op', async () => {
    renderAt('/mypage');
    await screen.findByTestId('report');
    expect(reportSpy.mock.lastCall![0].setHighlightPopover).toBe(hl.setHighlightPopover);
  });
});
