import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import AdminMembersReport from '../components/AdminMembersReport';
import type { AdminUser, AdminBookmark, AdminCurriculaResponse, AdminPaper, AdminPaperUserStats } from '../api/client';

// ── Fixtures ─────────────────────────────────────────────────────────────────

const SELF: AdminUser = {
  username: 'alice', role: 'admin', created_at: '2025-01-01T00:00:00Z', bookmark_count: 0,
};
const OTHER: AdminUser = {
  username: 'bob', role: 'user', created_at: '2025-03-15T00:00:00Z', bookmark_count: 2,
};

// Three users in the union: alice (account only), bob (account + bookmarks + curriculum),
// orphan (bookmark only — simulates a deleted account with leftover records).
const BOOKMARKS: AdminBookmark[] = [
  {
    id: 'bm-1', title: 'ML Papers', username: 'bob',
    query: 'machine learning', topic: 'ML', num_papers: 2,
    papers: [
      { title: 'Paper One', authors: ['Author A'] },
      { title: 'Paper Two', authors: ['Author B', 'Author C'] },
    ],
    created_at: '2025-04-01T00:00:00Z',
  },
  {
    id: 'bm-empty', title: 'Empty Bookmark', username: 'bob',
    query: '', topic: 'Empty', num_papers: 0, papers: [],
    created_at: '2025-05-01T00:00:00Z',
  },
  {
    id: 'bm-orphan', title: 'Orphan Bookmark', username: 'orphan',
    query: '', topic: 'DL', num_papers: 0, papers: [],
    created_at: '2025-05-15T00:00:00Z',
  },
];

const CURRICULA: AdminCurriculaResponse = {
  total_user_curricula: 1,
  total_users_with_curricula: 1,
  users: [{
    username: 'bob',
    curricula: [{
      id: 'cur-1', name: 'Deep Learning Basics', difficulty: 'beginner',
      total_papers: 5, total_modules: 3, is_preset: false,
      forked_from: 'preset-dl', type: 'fork',
    }],
    total_curricula: 1, fork_count: 1, custom_count: 0,
    total_read_papers: 3, courses_with_progress: 1,
  }],
};

// ── Paper fixtures ────────────────────────────────────────────────────────────

// total=42 is deliberately different from savedPapers (= 2 from BOOKMARKS) to
// catch any tile that accidentally reads the wrong source.
const PAPER_STATS: AdminPaperUserStats = {
  total: 42,
  users: [{ username: 'bob', paper_count: 40 }],
};

const FOLDER_PAPERS: AdminPaper[] = [
  {
    index: 0, title: 'Attention Is All You Need',
    authors: ['Vaswani', 'Shazeer'], source: 'arxiv',
    published_date: '2017-06-12', search_query: 'attention', searched_by: 'bob',
  },
  {
    index: 1, title: 'BERT',
    authors: ['Devlin'], source: 'semantic_scholar',
    published_date: '2018-10-11', search_query: 'bert', searched_by: 'bob',
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

// Papers are lazily loaded per user, so the defaults model "nothing loaded yet".
const PAPER_DEFAULTS = {
  paperStats: null,
  folderPapers: [],
  folderPage: 1,
  folderTotalPages: 1,
  folderTotal: 0,
  folderLoading: false,
  selectedPapers: new Set<number>(),
  onExpandMember: () => {},
  onPaperPageChange: () => {},
  onTogglePaperSelect: () => {},
  onToggleAllPapers: () => {},
  onDeletePapers: () => {},
} satisfies Partial<Parameters<typeof AdminMembersReport>[0]>;

function renderReport(overrides: Partial<Parameters<typeof AdminMembersReport>[0]> = {}) {
  return render(<AdminMembersReport
    users={[SELF, OTHER]}
    bookmarks={BOOKMARKS}
    curricula={CURRICULA}
    loading={false}
    currentUsername="alice"
    onToggleRole={() => {}}
    onDeleteUser={() => {}}
    onDeleteBookmark={() => {}}
    {...PAPER_DEFAULTS}
    {...overrides}
  />);
}

// Find the .admin-tree-folder-row element that contains the given username folder.
function getFolderRow(username: string): HTMLElement {
  const el = screen.getAllByText(username)
    .find(n => n.classList.contains('admin-tree-folder-name'));
  if (!el) throw new Error(`No folder row found for "${username}"`);
  return el.closest('.admin-tree-folder-row') as HTMLElement;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('AdminMembersReport', () => {
  it('renders report heading, 3 insight cards with ko-KR numbers, and 6 stat tiles', () => {
    renderReport();

    expect(screen.getByRole('heading', { name: '회원 통합 관리' })).toBeInTheDocument();
    // 2 users (alice + bob), 1 admin; 3 bookmarks (bm-1 + bm-empty + bm-orphan), 2 papers;
    // 1 curriculum, 3 read
    expect(screen.getByText('2명 등록 · 1명 관리자')).toBeInTheDocument();
    expect(screen.getByText('3개 북마크 · 2편 논문')).toBeInTheDocument();
    expect(screen.getByText('1개 커리큘럼 · 3편 읽음')).toBeInTheDocument();

    for (const label of ['사용자', '관리자', '북마크', '저장 논문', '커리큘럼', '읽은 논문']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('shows top bookmarker and top learner in context strip', () => {
    renderReport();

    expect(screen.getByText('최다 북마크 보유자')).toBeInTheDocument();
    expect(screen.getByText('최다 커리큘럼 보유자')).toBeInTheDocument();
    // bob has 2 bookmarks (most) and the only curriculum
    const strip = document.querySelector('.dashboard-context-strip') as HTMLElement;
    // Both strong elements inside the strip should say 'bob'
    expect(within(strip).getAllByText('bob')).toHaveLength(2);
  });

  it('renders role badge and activity badges on user folder rows', () => {
    renderReport();

    const aliceRow = getFolderRow('alice');
    expect(within(aliceRow).getByText('admin')).toBeInTheDocument();

    const bobRow = getFolderRow('bob');
    expect(within(bobRow).getByText('user')).toBeInTheDocument();
    expect(within(bobRow).getByText('북마크 2')).toBeInTheDocument();
    expect(within(bobRow).getByText('커리큘럼 1')).toBeInTheDocument();
    expect(within(bobRow).getByText('읽음 3')).toBeInTheDocument();
  });

  it('disables Promote and Delete for current user (alice), enables them for bob', () => {
    renderReport();

    const aliceRow = getFolderRow('alice');
    // alice is admin, so the role-toggle button reads "Demote"
    expect(within(aliceRow).getByRole('button', { name: 'Demote' })).toBeDisabled();
    expect(within(aliceRow).getByRole('button', { name: 'Delete' })).toBeDisabled();

    const bobRow = getFolderRow('bob');
    expect(within(bobRow).getByRole('button', { name: 'Promote' })).not.toBeDisabled();
    expect(within(bobRow).getByRole('button', { name: 'Delete' })).not.toBeDisabled();
  });

  it('calls onToggleRole(username, role) when Promote is clicked on another user', () => {
    const onToggleRole = vi.fn();
    renderReport({ onToggleRole });

    fireEvent.click(within(getFolderRow('bob')).getByRole('button', { name: 'Promote' }));

    expect(onToggleRole).toHaveBeenCalledWith('bob', 'user');
  });

  it('calls onDeleteUser(username) when Delete is clicked on a user folder row', () => {
    const onDeleteUser = vi.fn();
    renderReport({ onDeleteUser });

    fireEvent.click(within(getFolderRow('bob')).getByRole('button', { name: 'Delete' }));

    expect(onDeleteUser).toHaveBeenCalledWith('bob');
  });

  it('does not open user folder when Delete button is clicked (stopPropagation guard)', () => {
    renderReport();

    fireEvent.click(within(getFolderRow('bob')).getByRole('button', { name: 'Delete' }));

    // The folder must stay closed — bob's bookmark titles must not appear in the DOM
    expect(screen.queryByText('ML Papers')).not.toBeInTheDocument();
  });

  it('renders no Promote or Delete buttons for orphan row (account is null)', () => {
    renderReport();

    const orphanRow = getFolderRow('orphan');
    expect(within(orphanRow).queryByRole('button', { name: 'Promote' })).not.toBeInTheDocument();
    expect(within(orphanRow).queryByRole('button', { name: 'Demote' })).not.toBeInTheDocument();
    expect(within(orphanRow).queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  });

  it('shows Account, Bookmarks, Curricula sections with metadata when bob is expanded', () => {
    renderReport();
    fireEvent.click(getFolderRow('bob'));

    expect(screen.getByText('Account')).toBeInTheDocument();
    expect(screen.getByText('Bookmarks')).toBeInTheDocument();
    expect(screen.getByText('Curricula')).toBeInTheDocument();

    // Curriculum entry: name, type badge, fork source, modules, papers, difficulty
    expect(screen.getByText('Deep Learning Basics')).toBeInTheDocument();
    expect(screen.getByText('fork')).toBeInTheDocument();
    expect(document.body).toHaveTextContent('from preset-dl');
    expect(document.body).toHaveTextContent('3 modules');
    expect(document.body).toHaveTextContent('5 papers');
    expect(document.body).toHaveTextContent('beginner');

    // Reading Progress summary
    expect(screen.getByText('Reading Progress')).toBeInTheDocument();
    expect(document.body).toHaveTextContent('3 papers read across 1 course');
  });

  it('shows "삭제된 계정의 잔여 기록" in Account section for orphan (no account)', () => {
    renderReport();
    fireEvent.click(getFolderRow('orphan'));

    expect(screen.getByText('삭제된 계정의 잔여 기록')).toBeInTheDocument();
  });

  it('shows paper titles when bookmark mini-toggle is clicked', () => {
    renderReport();
    fireEvent.click(getFolderRow('bob'));

    // ML Papers has 2 papers — mini expand button must exist
    const expandBtn = document.querySelector('.admin-tree-expand-mini') as HTMLElement;
    expect(expandBtn).toBeInTheDocument();
    fireEvent.click(expandBtn);

    expect(screen.getByText('Paper One')).toBeInTheDocument();
    expect(screen.getByText('Paper Two')).toBeInTheDocument();
  });

  it('renders no mini-toggle button for a zero-paper bookmark', () => {
    renderReport();
    fireEvent.click(getFolderRow('bob'));

    // Only ML Papers (2 papers) gets the expand button; Empty Bookmark (0 papers) does not
    expect(document.querySelectorAll('.admin-tree-expand-mini')).toHaveLength(1);
  });

  it('calls onDeleteBookmark(id, title) when bookmark Delete is clicked', () => {
    const onDeleteBookmark = vi.fn();
    renderReport({ onDeleteBookmark });
    fireEvent.click(getFolderRow('bob'));

    const mlSection = screen.getByText('ML Papers').closest('.admin-tree-file') as HTMLElement;
    fireEvent.click(within(mlSection).getByRole('button', { name: 'Delete' }));

    expect(onDeleteBookmark).toHaveBeenCalledWith('bm-1', 'ML Papers');
  });

  it('shows empty bookmark hint when the expanded user has no bookmarks (alice)', () => {
    renderReport();
    fireEvent.click(getFolderRow('alice'));

    expect(screen.getByText('저장한 북마크가 없습니다.')).toBeInTheDocument();
  });

  it('shows empty curricula hint when the expanded user has no curricula (alice)', () => {
    renderReport();
    fireEvent.click(getFolderRow('alice'));

    expect(screen.getByText('보유한 커리큘럼이 없습니다 (프리셋 진도만 있을 수 있음).')).toBeInTheDocument();
  });

  it('shows loading text when loading prop is true', () => {
    render(<AdminMembersReport
      users={[SELF]} bookmarks={[]} curricula={null} loading={true}
      currentUsername="alice"
      onToggleRole={() => {}} onDeleteUser={() => {}} onDeleteBookmark={() => {}}
      {...PAPER_DEFAULTS}
    />);

    expect(screen.getByText('Loading members...')).toBeInTheDocument();
  });

  it('shows empty state when there are no members at all', () => {
    render(<AdminMembersReport
      users={[]} bookmarks={[]} curricula={null} loading={false}
      currentUsername="alice"
      onToggleRole={() => {}} onDeleteUser={() => {}} onDeleteBookmark={() => {}}
      {...PAPER_DEFAULTS}
    />);

    expect(screen.getByText('회원 데이터가 없습니다.')).toBeInTheDocument();
  });

  // ── Papers section ───────────────────────────────────────────────────────────

  describe('Papers section', () => {
    // 1. 논문 배지
    it('shows 논문 N badge on folder row for user with paper_count > 0, no badge when count is 0', () => {
      renderReport({ paperStats: PAPER_STATS });

      expect(within(getFolderRow('bob')).getByText('논문 40')).toBeInTheDocument();
      expect(within(getFolderRow('alice')).queryByText(/^논문 /)).not.toBeInTheDocument();
    });

    // 2. stat tile — 수집 논문 vs 저장 논문
    it('수집 논문 tile shows paperStats.total and differs from 저장 논문 tile (regression guard)', () => {
      renderReport({ paperStats: PAPER_STATS });

      // savedPapers (from BOOKMARKS) = 2; paperStats.total = 42 — must not be the same
      const collectedCard = screen.getByText('수집 논문').closest('.admin-stat-card') as HTMLElement;
      const savedCard = screen.getByText('저장 논문').closest('.admin-stat-card') as HTMLElement;

      expect(within(collectedCard).getByText('42')).toBeInTheDocument();
      expect(within(savedCard).getByText('2')).toBeInTheDocument();
      // If either tile accidentally reads the other's source, one of these fails.
      expect(within(collectedCard).queryByText('2')).not.toBeInTheDocument();
      expect(within(savedCard).queryByText('42')).not.toBeInTheDocument();
    });

    // 3. 지연 로딩 배선
    it('calls onExpandMember(username) when folder opens, onExpandMember(null) when same folder is closed', () => {
      const onExpandMember = vi.fn();
      renderReport({ onExpandMember });

      fireEvent.click(getFolderRow('bob'));
      expect(onExpandMember).toHaveBeenCalledWith('bob');

      fireEvent.click(getFolderRow('bob'));
      expect(onExpandMember).toHaveBeenLastCalledWith(null);
    });

    // 4. 폴더 직접 전환 — 닫고-열기 2단계로 잘못 구현하면 여기서 터진다
    it('calls onExpandMember(B) directly when switching from folder A to B — no null call in between', () => {
      const onExpandMember = vi.fn();
      renderReport({ onExpandMember });

      fireEvent.click(getFolderRow('alice'));  // open alice
      fireEvent.click(getFolderRow('bob'));    // switch to bob

      expect(onExpandMember).toHaveBeenCalledTimes(2);
      expect(onExpandMember).toHaveBeenNthCalledWith(2, 'bob');
      expect(onExpandMember).not.toHaveBeenCalledWith(null);
    });

    // 5. 논문 목록 렌더
    it('renders paper title, authors, source, and published_date when folder is open', () => {
      renderReport({ folderPapers: FOLDER_PAPERS });
      fireEvent.click(getFolderRow('bob'));

      expect(screen.getByText('Attention Is All You Need')).toBeInTheDocument();
      expect(document.body).toHaveTextContent('Vaswani, Shazeer');
      expect(document.body).toHaveTextContent('arxiv');
      expect(document.body).toHaveTextContent('2017-06-12');
    });

    // 6a. 선택된 인덱스의 체크박스가 checked
    it('marks the checkbox as checked for an index in selectedPapers, unchecked for others', () => {
      renderReport({ folderPapers: FOLDER_PAPERS, selectedPapers: new Set([0]) });
      fireEvent.click(getFolderRow('bob'));

      // getAllByRole('checkbox'): [0]=select-all, [1]=paper index=0, [2]=paper index=1
      const [, paper0, paper1] = screen.getAllByRole('checkbox');
      expect(paper0).toBeChecked();
      expect(paper1).not.toBeChecked();
    });

    // 6b. 개별 체크박스 클릭 → onTogglePaperSelect(index)
    it('calls onTogglePaperSelect(index) when an individual paper checkbox is changed', () => {
      const onTogglePaperSelect = vi.fn();
      renderReport({ folderPapers: FOLDER_PAPERS, onTogglePaperSelect });
      fireEvent.click(getFolderRow('bob'));

      const [, , paper1] = screen.getAllByRole('checkbox');
      fireEvent.click(paper1);
      expect(onTogglePaperSelect).toHaveBeenCalledWith(1);  // FOLDER_PAPERS[1].index = 1
    });

    // 6c. 전체선택 체크박스 클릭 → onToggleAllPapers
    it('calls onToggleAllPapers when the select-all checkbox is changed', () => {
      const onToggleAllPapers = vi.fn();
      renderReport({ folderPapers: FOLDER_PAPERS, onToggleAllPapers });
      fireEvent.click(getFolderRow('bob'));

      const [selectAll] = screen.getAllByRole('checkbox');
      fireEvent.click(selectAll);
      expect(onToggleAllPapers).toHaveBeenCalledTimes(1);
    });

    // 7a. 벌크 바 — 선택 없음
    it('shows no bulk bar when selectedPapers is empty', () => {
      renderReport({ folderPapers: FOLDER_PAPERS, selectedPapers: new Set<number>() });
      fireEvent.click(getFolderRow('bob'));

      expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
    });

    // 7b. 벌크 바 — 선택 있음
    it('shows N selected and Delete Selected button when selectedPapers is non-empty, calls onDeletePapers on click', () => {
      const onDeletePapers = vi.fn();
      renderReport({ selectedPapers: new Set([0, 1]), onDeletePapers });
      fireEvent.click(getFolderRow('bob'));

      expect(screen.getByText('2 selected')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Delete Selected' }));
      expect(onDeletePapers).toHaveBeenCalledTimes(1);
    });

    // 8a. 페이지네이션 — folderTotalPages=1 이면 숨김
    it('hides pagination buttons when folderTotalPages is 1', () => {
      renderReport({ folderPapers: FOLDER_PAPERS, folderTotalPages: 1 });
      fireEvent.click(getFolderRow('bob'));

      expect(screen.queryByRole('button', { name: 'Prev' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument();
    });

    // 8b. 페이지네이션 — 1페이지: Prev disabled, Next → onPaperPageChange 호출
    it('disables Prev on page 1 and Next click calls onPaperPageChange(username, page + 1)', () => {
      const onPaperPageChange = vi.fn();
      renderReport({
        folderPapers: FOLDER_PAPERS,
        folderPage: 1,
        folderTotalPages: 3,
        onPaperPageChange,
      });
      fireEvent.click(getFolderRow('bob'));

      expect(screen.getByRole('button', { name: 'Prev' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Next' })).not.toBeDisabled();

      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
      expect(onPaperPageChange).toHaveBeenCalledWith('bob', 2);
    });

    // 8c. 페이지네이션 — 마지막 페이지: Next disabled
    it('disables Next on the last page and enables Prev', () => {
      renderReport({ folderPapers: FOLDER_PAPERS, folderPage: 3, folderTotalPages: 3 });
      fireEvent.click(getFolderRow('bob'));

      expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Prev' })).not.toBeDisabled();
    });

    // 9a. 로딩 상태
    it('shows Loading papers... when folderLoading is true and folder is open', () => {
      renderReport({ folderLoading: true });
      fireEvent.click(getFolderRow('bob'));

      expect(screen.getByText('Loading papers...')).toBeInTheDocument();
    });

    // 9b. 빈 상태
    it('shows No papers hint when folderPapers is empty and not loading', () => {
      renderReport({ folderPapers: [], folderLoading: false });
      fireEvent.click(getFolderRow('bob'));

      expect(screen.getByText('No papers')).toBeInTheDocument();
    });

    // 10. 논문만 있고 계정·북마크·커리큘럼이 없는 유저도 행으로 나온다 (합집합 회귀 가드)
    it('includes a folder row for a username that exists only in paperStats.users', () => {
      renderReport({
        paperStats: { total: 5, users: [{ username: 'charlie', paper_count: 5 }] },
      });

      // charlie has no account, no bookmarks, no curricula — only a paperStats entry
      expect(getFolderRow('charlie')).toBeInTheDocument();
      expect(within(getFolderRow('charlie')).getByText('논문 5')).toBeInTheDocument();
    });
  });
});
