import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import CurriculumPage from '../components/CurriculumPage';
import { paramsWithSelection } from '../components/curriculum/params';

// The hook is the data layer; this tests the page's wiring: what the URL seeds,
// what a selection writes back, and where "View Paper" goes.
const cur = {
  presetCourses: [], myCourses: [], loadingCourses: false, loadingCourse: false,
  courseDetail: null as null | { id: string; modules: { id: string }[] },
  selectedCourseId: null as string | null, selectedModuleId: null as string | null, selectedPaperId: null as string | null,
  selectedModule: null, selectedPaper: null, readPapers: new Set<string>(), progressStats: null,
  generating: false, forking: false, generateProgress: null, reviewStatus: 'idle', reviewProgress: null,
  reviewingPaperIds: new Set<string>(), reviewingModuleId: null, shareMessage: null,
  handleSelectCourse: vi.fn(), setSelectedModuleId: vi.fn(), setSelectedPaperId: vi.fn(),
  handleToggleRead: vi.fn(), handleSearchPaper: vi.fn(), handleGenerate: vi.fn(), handleFork: vi.fn(),
  handleDelete: vi.fn(), handleShare: vi.fn(), handleRevokeShare: vi.fn(),
  handleDeepReviewPaper: vi.fn(), handleDeepReviewModule: vi.fn(), getModuleProgress: () => ({ read: 0, total: 0 }),
};
vi.mock('../hooks/useCurriculum', () => ({ useCurriculum: () => cur }));
vi.mock('../components/curriculum/CourseSidebar', () => ({
  default: ({ onSelectCourse, onSelectModule }: { onSelectCourse: (id: string) => void; onSelectModule: (id: string) => void }) => (
    <div>
      <button type="button" onClick={() => onSelectCourse('c2')}>pick course</button>
      <button type="button" onClick={() => onSelectCourse('c1')}>pick course c1</button>
      <button type="button" onClick={() => onSelectModule('m9')}>pick module</button>
    </div>
  ),
}));
vi.mock('../components/curriculum/ModuleView', () => ({
  default: ({ onSelectPaper }: { onSelectPaper: (id: string) => void }) => (
    <button type="button" onClick={() => onSelectPaper('p7')}>pick paper</button>
  ),
}));
vi.mock('../components/curriculum/CurriculumDetailPanel', () => ({
  default: ({ onViewPaper }: { onViewPaper: (paper: { title: string; authors: string[] }) => void }) => (
    <button type="button" onClick={() => onViewPaper({ title: 'Attention Is All You Need', authors: ['Vaswani'] })}>View Paper</button>
  ),
}));

function Probe() {
  const location = useLocation();
  return <output data-testid="probe">{location.pathname}{location.search}</output>;
}
const renderAt = (entry: string) => render(
  <MemoryRouter initialEntries={[entry]}><CurriculumPage /><Probe /></MemoryRouter>,
);

beforeEach(() => {
  vi.clearAllMocks();
  cur.courseDetail = null; cur.selectedCourseId = null; cur.selectedModuleId = null;
});

describe('paramsWithSelection', () => {
  it('writes only the keys it owns and drops the ones that are null', () => {
    const next = paramsWithSelection(new URLSearchParams('q=graph&course=c1&paper=p1'), { course: 'c2', module: 'm1', paper: null });
    expect(next.get('q')).toBe('graph');
    expect(next.get('course')).toBe('c2');
    expect(next.get('module')).toBe('m1');
    expect(next.has('paper')).toBe(false);
  });
});

describe('CurriculumPage', () => {
  it("seeds the course from the URL once, and its module and paper after the hook's own auto-select", async () => {
    // The real hook loads the detail and then selects the first module; the
    // URL's module must land after that, or it would be overwritten.
    // Once: clearAllMocks() keeps implementations, and the next test wants the bare spy.
    cur.handleSelectCourse.mockImplementationOnce((id: string) => {
      cur.courseDetail = { id, modules: [{ id: 'm1' }, { id: 'm2' }] };
      cur.selectedCourseId = id;
      cur.setSelectedModuleId('m1');
    });
    const tree = () => <MemoryRouter initialEntries={['/curriculum?course=c1&module=m2&paper=p3']}><CurriculumPage /><Probe /></MemoryRouter>;
    const { rerender } = render(tree());
    expect(cur.handleSelectCourse).toHaveBeenCalledWith('c1');
    rerender(tree());
    await waitFor(() => expect(cur.setSelectedModuleId).toHaveBeenLastCalledWith('m2'));
    expect(cur.setSelectedModuleId.mock.calls.map((call) => call[0])).toEqual(['m1', 'm2']);
    expect(cur.setSelectedPaperId).toHaveBeenCalledWith('p3');
    expect(cur.handleSelectCourse).toHaveBeenCalledTimes(1);

    // Clicking the open course row again (it is the module tree's handle) is a
    // no-op in the hook and must not empty the URL either.
    cur.selectedModuleId = 'm2';
    rerender(tree());
    fireEvent.click(screen.getByRole('button', { name: 'pick course c1' }));
    expect(cur.handleSelectCourse).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('probe')).toHaveTextContent('/curriculum?course=c1&module=m2&paper=p3');
  });

  it('writes the selection to the URL so a reload lands on the same paper', async () => {
    // A fresh element each time: React bails out of re-rendering an identical one.
    const tree = () => <MemoryRouter initialEntries={['/curriculum']}><CurriculumPage /><Probe /></MemoryRouter>;
    const { rerender } = render(tree());
    expect(cur.handleSelectCourse).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'pick course' }));
    expect(cur.handleSelectCourse).toHaveBeenCalledWith('c2');
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('/curriculum?course=c2'));

    // The real hook re-renders the page when its selection changes; the mock is
    // a plain object, so the re-render is asked for by hand.
    cur.selectedCourseId = 'c2';
    cur.courseDetail = { id: 'c2', modules: [{ id: 'm8' }, { id: 'm9' }] };
    rerender(tree());
    // The detail arriving must not re-seed anything: the URL has no module or paper yet.
    expect(cur.setSelectedModuleId).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'pick module' }));
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('/curriculum?course=c2&module=m9'));
    expect(cur.setSelectedPaperId).toHaveBeenCalledWith(null);
    cur.selectedModuleId = 'm9';
    rerender(tree());
    fireEvent.click(screen.getByRole('button', { name: 'pick paper' }));
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('/curriculum?course=c2&module=m9&paper=p7'));
    // The page's own writes changed the URL twice; the seed latch held both times.
    expect(cur.setSelectedModuleId.mock.calls).toEqual([['m9']]);
    expect(cur.setSelectedPaperId.mock.calls).toEqual([[null], ['p7']]);
  });

  it('opens a paper in the viewer route in its own tab and links back to MyPage', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    renderAt('/curriculum');
    fireEvent.click(screen.getByRole('button', { name: 'View Paper' }));
    expect(open).toHaveBeenCalledWith('/paper-viewer?title=Attention+Is+All+You+Need&authors=Vaswani&source=curriculum', '_blank', 'noopener,noreferrer');
    expect(screen.getByRole('link', { name: '마이페이지' })).toHaveAttribute('href', '/mypage');
    expect(screen.getByRole('heading', { name: '학습 커리큘럼' })).toBeInTheDocument();
    open.mockRestore();
  });
});
