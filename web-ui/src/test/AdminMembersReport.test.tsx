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
    index: 0, fingerprint: 'fp-attention', title: 'Attention Is All You Need',
    authors: ['Vaswani', 'Shazeer'], source: 'arxiv',
    published_date: '2017-06-12', search_query: 'attention', searched_by: 'bob',
  },
  {
    index: 1, fingerprint: 'fp-bert', title: 'BERT',
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

// The disclosure button inside that row — a real <button>, sibling to the
// action buttons rather than their ancestor.
function getFolderToggle(username: string): HTMLElement {
  return getFolderRow(username).querySelector('.admin-tree-folder-toggle') as HTMLElement;
}

// Usernames currently rendered in the tree, in render order.
function visibleUsernames(): string[] {
  return [...document.querySelectorAll('.admin-tree-folder-name')].map(n => n.textContent ?? '');
}

function typeSearch(value: string) {
  fireEvent.change(screen.getByRole('searchbox', { name: 'username 검색' }), { target: { value } });
}

function choose(name: '정렬 기준' | '목록 범위', value: string) {
  fireEvent.change(screen.getByRole('combobox', { name }), { target: { value } });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('AdminMembersReport', () => {
  it('renders report heading and 3 insight cards with ko-KR numbers', () => {
    renderReport();

    expect(screen.getByRole('heading', { name: '회원 통합 관리' })).toBeInTheDocument();
    // 2 users (alice + bob), 1 admin; 3 bookmarks (bm-1 + bm-empty + bm-orphan), 2 papers;
    // 1 curriculum, 3 read
    expect(screen.getByText('2명 등록 · 1명 관리자')).toBeInTheDocument();
    expect(screen.getByText('3개 북마크 · 2편 저장 · 0편 수집')).toBeInTheDocument();
    expect(screen.getByText('1개 커리큘럼 · 3편 읽음')).toBeInTheDocument();
  });

  it('carries no stat tile that merely repeats an insight card number', () => {
    renderReport({ paperStats: PAPER_STATS });

    // The seven-tile row restated all three cards and added only 수집 논문,
    // which now rides along in the 논문 규모 headline. A tile reappearing here
    // means the duplication came back.
    expect(document.querySelectorAll('.admin-stat-card')).toHaveLength(0);
    for (const label of ['사용자', '저장 논문', '수집 논문', '읽은 논문']) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it('shows top bookmarker and top learner in context strip', () => {
    renderReport();

    expect(screen.getByText('최다 북마크 보유자')).toBeInTheDocument();
    expect(screen.getByText('최다 커리큘럼 보유자')).toBeInTheDocument();
    // bob has 2 bookmarks (most) and the only curriculum
    const strip = document.querySelector('.dashboard-context-strip') as HTMLElement;
    // Both shortcuts inside the strip should say 'bob'
    expect(within(strip).getAllByText('bob')).toHaveLength(2);
  });

  it('filters the list down to a top holder when their context-strip shortcut is clicked', () => {
    renderReport();

    const strip = document.querySelector('.dashboard-context-strip') as HTMLElement;
    fireEvent.click(within(strip).getAllByRole('button', { name: 'bob' })[0]);

    expect(visibleUsernames()).toEqual(['bob']);
    expect(screen.getByText('3명 중 1명')).toBeInTheDocument();
  });

  it('renders a top holder with no record as plain text, not a shortcut', () => {
    // No paperStats — nobody has collected a paper, so there is nothing to jump to.
    renderReport();

    const strip = document.querySelector('.dashboard-context-strip') as HTMLElement;
    expect(within(strip).getByText('기록 없음')).toBeInTheDocument();
    expect(within(strip).queryByRole('button', { name: '기록 없음' })).not.toBeInTheDocument();
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

  it('disables the role toggle and delete for current user (alice), enables them for bob', () => {
    renderReport();

    const aliceRow = getFolderRow('alice');
    // alice is admin, so her role-toggle demotes
    expect(within(aliceRow).getByRole('button', { name: 'alice 권한 해제' })).toBeDisabled();
    expect(within(aliceRow).getByRole('button', { name: 'alice 계정 삭제' })).toBeDisabled();

    const bobRow = getFolderRow('bob');
    expect(within(bobRow).getByRole('button', { name: 'bob 권한 승격' })).not.toBeDisabled();
    expect(within(bobRow).getByRole('button', { name: 'bob 계정 삭제' })).not.toBeDisabled();
  });

  it('names every row control after the member it acts on, not just its verb', () => {
    // 500 members used to mean 1,000 tab stops reading only "Promote"/"Delete".
    renderReport();

    expect(getFolderToggle('bob')).toHaveAccessibleName('bob, 권한 user, 북마크 2, 커리큘럼 1, 읽음 3');
    expect(getFolderToggle('orphan')).toHaveAccessibleName('orphan, 계정 없음, 북마크 1');

    fireEvent.click(getFolderToggle('bob'));
    expect(screen.getByRole('button', { name: '북마크 "ML Papers" 논문 목록' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '북마크 "ML Papers" 삭제' })).toBeInTheDocument();
  });

  it('keeps the action buttons as siblings of the disclosure, never nested inside it', () => {
    // A button inside a button is axe `nested-interactive`: screen readers that
    // prune a button's descendants drop the actions entirely, and Chromium's
    // browse mode cannot reach them with arrow keys even though Tab can.
    renderReport();

    const toggle = getFolderToggle('bob');
    expect(toggle.tagName).toBe('BUTTON');
    expect(toggle.querySelectorAll('button, [tabindex]:not([tabindex^="-"])')).toHaveLength(0);

    for (const name of ['bob 권한 승격', 'bob 계정 삭제']) {
      const action = within(getFolderRow('bob')).getByRole('button', { name });
      expect(toggle.contains(action)).toBe(false);
      expect(action.closest('.admin-tree-folder-row')).toBe(getFolderRow('bob'));
    }
  });

  it('calls onToggleRole(username, role) when the role toggle is clicked on another user', () => {
    const onToggleRole = vi.fn();
    renderReport({ onToggleRole });

    fireEvent.click(within(getFolderRow('bob')).getByRole('button', { name: 'bob 권한 승격' }));

    expect(onToggleRole).toHaveBeenCalledWith('bob', 'user');
  });

  it('calls onDeleteUser(username) when delete is clicked on a user folder row', () => {
    const onDeleteUser = vi.fn();
    renderReport({ onDeleteUser });

    fireEvent.click(within(getFolderRow('bob')).getByRole('button', { name: 'bob 계정 삭제' }));

    expect(onDeleteUser).toHaveBeenCalledWith('bob');
  });

  it('does not open user folder when the delete button is clicked', () => {
    // This used to depend on an e.stopPropagation() guard, because the delete
    // button sat inside the row's own click target. It is now structural: the
    // delete button is a sibling of the disclosure, so its click never reaches
    // one. The assertion stays — it is what would catch a regression back to
    // the nested shape.
    renderReport();

    fireEvent.click(within(getFolderRow('bob')).getByRole('button', { name: 'bob 계정 삭제' }));

    // The folder must stay closed — bob's bookmark titles must not appear in the DOM
    expect(screen.queryByText('ML Papers')).not.toBeInTheDocument();
  });

  it('renders no role or delete buttons for orphan row (account is null)', () => {
    renderReport();

    // The disclosure is the only control an accountless row carries.
    const buttons = within(getFolderRow('orphan')).getAllByRole('button');
    expect(buttons).toEqual([getFolderToggle('orphan')]);
  });

  it('shows 계정, 북마크, 커리큘럼 sections with metadata when bob is expanded', () => {
    renderReport();
    fireEvent.click(getFolderToggle('bob'));

    expect(screen.getByText('계정')).toBeInTheDocument();
    expect(screen.getByText('북마크')).toBeInTheDocument();
    expect(screen.getByText('커리큘럼')).toBeInTheDocument();

    // Curriculum entry: name, type badge, fork source, modules, papers, difficulty.
    // 'fork' stays verbatim — it is the API's enum value, not UI chrome.
    expect(screen.getByText('Deep Learning Basics')).toBeInTheDocument();
    expect(screen.getByText('fork')).toBeInTheDocument();
    expect(document.body).toHaveTextContent('원본 preset-dl');
    expect(document.body).toHaveTextContent('모듈 3개');
    expect(document.body).toHaveTextContent('논문 5편');
    expect(document.body).toHaveTextContent('beginner');

    // Reading progress summary
    expect(screen.getByText('읽기 진도')).toBeInTheDocument();
    expect(document.body).toHaveTextContent('강의 1개에서 논문 3편 읽음');
  });

  it('shows "삭제된 계정의 잔여 기록" in Account section for orphan (no account)', () => {
    renderReport();
    fireEvent.click(getFolderToggle('orphan'));

    expect(screen.getByText('삭제된 계정의 잔여 기록')).toBeInTheDocument();
  });

  it('shows paper titles when bookmark mini-toggle is clicked', () => {
    renderReport();
    fireEvent.click(getFolderToggle('bob'));

    // ML Papers has 2 papers — mini expand button must exist
    const expandBtn = document.querySelector('.admin-tree-expand-mini') as HTMLElement;
    expect(expandBtn).toBeInTheDocument();
    fireEvent.click(expandBtn);

    expect(screen.getByText('Paper One')).toBeInTheDocument();
    expect(screen.getByText('Paper Two')).toBeInTheDocument();
  });

  it('renders no mini-toggle button for a zero-paper bookmark', () => {
    renderReport();
    fireEvent.click(getFolderToggle('bob'));

    // Only ML Papers (2 papers) gets the expand button; Empty Bookmark (0 papers) does not
    expect(document.querySelectorAll('.admin-tree-expand-mini')).toHaveLength(1);
  });

  it('calls onDeleteBookmark(id, title) when bookmark delete is clicked', () => {
    const onDeleteBookmark = vi.fn();
    renderReport({ onDeleteBookmark });
    fireEvent.click(getFolderToggle('bob'));

    fireEvent.click(screen.getByRole('button', { name: '북마크 "ML Papers" 삭제' }));

    expect(onDeleteBookmark).toHaveBeenCalledWith('bm-1', 'ML Papers');
  });

  it('shows empty bookmark hint when the expanded user has no bookmarks (alice)', () => {
    renderReport();
    fireEvent.click(getFolderToggle('alice'));

    expect(screen.getByText('저장한 북마크가 없습니다.')).toBeInTheDocument();
  });

  it('shows empty curricula hint when the expanded user has no curricula (alice)', () => {
    renderReport();
    fireEvent.click(getFolderToggle('alice'));

    expect(screen.getByText('보유한 커리큘럼이 없습니다 (프리셋 진도만 있을 수 있음).')).toBeInTheDocument();
  });

  it('shows loading text when loading prop is true', () => {
    render(<AdminMembersReport
      users={[SELF]} bookmarks={[]} curricula={null} loading={true}
      currentUsername="alice"
      onToggleRole={() => {}} onDeleteUser={() => {}} onDeleteBookmark={() => {}}
      {...PAPER_DEFAULTS}
    />);

    expect(screen.getByText('회원 정보를 불러오는 중...')).toBeInTheDocument();
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

    // 2. 저장 vs 수집 — 서로 다른 모수
    it('논문 규모 headline reports 저장 and 수집 from their own sources (regression guard)', () => {
      renderReport({ paperStats: PAPER_STATS });

      // savedPapers (from BOOKMARKS) = 2; paperStats.total = 42 — must not be the
      // same number, and must not be swapped.
      expect(screen.getByText('3개 북마크 · 2편 저장 · 42편 수집')).toBeInTheDocument();
      expect(screen.queryByText('3개 북마크 · 42편 저장 · 2편 수집')).not.toBeInTheDocument();
    });

    // 3. 지연 로딩 배선
    it('calls onExpandMember(username) when folder opens, onExpandMember(null) when same folder is closed', () => {
      const onExpandMember = vi.fn();
      renderReport({ onExpandMember });

      fireEvent.click(getFolderToggle('bob'));
      expect(onExpandMember).toHaveBeenCalledWith('bob');

      fireEvent.click(getFolderToggle('bob'));
      expect(onExpandMember).toHaveBeenLastCalledWith(null);
    });

    // 4. 폴더 직접 전환 — 닫고-열기 2단계로 잘못 구현하면 여기서 터진다
    it('calls onExpandMember(B) directly when switching from folder A to B — no null call in between', () => {
      const onExpandMember = vi.fn();
      renderReport({ onExpandMember });

      fireEvent.click(getFolderToggle('alice'));  // open alice
      fireEvent.click(getFolderToggle('bob'));    // switch to bob

      expect(onExpandMember).toHaveBeenCalledTimes(2);
      expect(onExpandMember).toHaveBeenNthCalledWith(2, 'bob');
      expect(onExpandMember).not.toHaveBeenCalledWith(null);
    });

    // 5. 논문 목록 렌더
    it('renders paper title, authors, source, and published_date when folder is open', () => {
      renderReport({ folderPapers: FOLDER_PAPERS });
      fireEvent.click(getFolderToggle('bob'));

      expect(screen.getByText('Attention Is All You Need')).toBeInTheDocument();
      expect(document.body).toHaveTextContent('Vaswani, Shazeer');
      expect(document.body).toHaveTextContent('arxiv');
      expect(document.body).toHaveTextContent('2017-06-12');
    });

    // 6a. 선택된 인덱스의 체크박스가 checked
    it('marks the checkbox as checked for an index in selectedPapers, unchecked for others', () => {
      renderReport({ folderPapers: FOLDER_PAPERS, selectedPapers: new Set([0]) });
      fireEvent.click(getFolderToggle('bob'));

      // getAllByRole('checkbox'): [0]=select-all, [1]=paper index=0, [2]=paper index=1
      const [, paper0, paper1] = screen.getAllByRole('checkbox');
      expect(paper0).toBeChecked();
      expect(paper1).not.toBeChecked();
    });

    // 6b. 개별 체크박스 클릭 → onTogglePaperSelect(index)
    it('calls onTogglePaperSelect(index) when an individual paper checkbox is changed', () => {
      const onTogglePaperSelect = vi.fn();
      renderReport({ folderPapers: FOLDER_PAPERS, onTogglePaperSelect });
      fireEvent.click(getFolderToggle('bob'));

      const [, , paper1] = screen.getAllByRole('checkbox');
      fireEvent.click(paper1);
      expect(onTogglePaperSelect).toHaveBeenCalledWith(1);  // FOLDER_PAPERS[1].index = 1
    });

    // 6c. 전체선택 체크박스 클릭 → onToggleAllPapers
    it('calls onToggleAllPapers when the select-all checkbox is changed', () => {
      const onToggleAllPapers = vi.fn();
      renderReport({ folderPapers: FOLDER_PAPERS, onToggleAllPapers });
      fireEvent.click(getFolderToggle('bob'));

      const [selectAll] = screen.getAllByRole('checkbox');
      fireEvent.click(selectAll);
      expect(onToggleAllPapers).toHaveBeenCalledTimes(1);
    });

    // 7a. 벌크 바 — 선택 없음
    it('shows no bulk bar when selectedPapers is empty', () => {
      renderReport({ folderPapers: FOLDER_PAPERS, selectedPapers: new Set<number>() });
      fireEvent.click(getFolderToggle('bob'));

      expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
    });

    // 7b. 벌크 바 — 선택 있음
    it('shows N편 선택됨 and 선택 삭제 button when selectedPapers is non-empty, calls onDeletePapers on click', () => {
      const onDeletePapers = vi.fn();
      renderReport({ folderPapers: FOLDER_PAPERS, selectedPapers: new Set([0, 1]), onDeletePapers });
      fireEvent.click(getFolderToggle('bob'));

      expect(screen.getByText('2편 선택됨')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: '선택 삭제' }));
      expect(onDeletePapers).toHaveBeenCalledTimes(1);
    });

    // 7c. 벌크 바 — 다른 유저의 논문을 불러오는 중
    it('renders no bulk bar while a folder is loading, even with a live selection', () => {
      // Switching member A -> B keeps the bar on screen unless it is gated on
      // folderLoading: "2 selected" + Delete Selected would then be clickable
      // over B's folder while A's row indices are still selected.
      renderReport({ folderPapers: [], folderLoading: true, selectedPapers: new Set([0, 1]) });
      fireEvent.click(getFolderToggle('bob'));

      expect(screen.getByText('논문을 불러오는 중...')).toBeInTheDocument();
      expect(screen.queryByText('2편 선택됨')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: '선택 삭제' })).not.toBeInTheDocument();
    });

    // 7d. 벌크 바 — 논문이 없는 폴더
    it('renders no bulk bar for an empty folder, even with a live selection', () => {
      renderReport({ folderPapers: [], folderLoading: false, selectedPapers: new Set([0]) });
      fireEvent.click(getFolderToggle('bob'));

      expect(screen.getByText('수집한 논문이 없습니다.')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: '선택 삭제' })).not.toBeInTheDocument();
    });

    // 8a. 페이지네이션 — folderTotalPages=1 이면 숨김
    it('hides pagination buttons when folderTotalPages is 1', () => {
      renderReport({ folderPapers: FOLDER_PAPERS, folderTotalPages: 1 });
      fireEvent.click(getFolderToggle('bob'));

      expect(screen.queryByRole('button', { name: '이전' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: '다음' })).not.toBeInTheDocument();
    });

    // 8b. 페이지네이션 — 1페이지: Prev disabled, Next → onPaperPageChange 호출
    it('disables 이전 on page 1 and 다음 click calls onPaperPageChange(username, page + 1)', () => {
      const onPaperPageChange = vi.fn();
      renderReport({
        folderPapers: FOLDER_PAPERS,
        folderPage: 1,
        folderTotalPages: 3,
        onPaperPageChange,
      });
      fireEvent.click(getFolderToggle('bob'));

      expect(screen.getByRole('button', { name: '이전' })).toBeDisabled();
      expect(screen.getByRole('button', { name: '다음' })).not.toBeDisabled();

      fireEvent.click(screen.getByRole('button', { name: '다음' }));
      expect(onPaperPageChange).toHaveBeenCalledWith('bob', 2);
    });

    // 8c. 페이지네이션 — 마지막 페이지: Next disabled
    it('disables 다음 on the last page and enables 이전', () => {
      renderReport({ folderPapers: FOLDER_PAPERS, folderPage: 3, folderTotalPages: 3 });
      fireEvent.click(getFolderToggle('bob'));

      expect(screen.getByRole('button', { name: '다음' })).toBeDisabled();
      expect(screen.getByRole('button', { name: '이전' })).not.toBeDisabled();
    });

    // 9a. 로딩 상태
    it('shows 논문을 불러오는 중... when folderLoading is true and folder is open', () => {
      renderReport({ folderLoading: true });
      fireEvent.click(getFolderToggle('bob'));

      expect(screen.getByText('논문을 불러오는 중...')).toBeInTheDocument();
    });

    // 9b. 빈 상태
    it('shows 수집한 논문이 없습니다 hint when folderPapers is empty and not loading', () => {
      renderReport({ folderPapers: [], folderLoading: false });
      fireEvent.click(getFolderToggle('bob'));

      expect(screen.getByText('수집한 논문이 없습니다.')).toBeInTheDocument();
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

  // ── 검색 · 정렬 · 필터 ────────────────────────────────────────────────────────
  // 500명 렌더는 137ms 라 병목이 아니고, 병목은 그 안에서 한 명을 찾는 일이다.

  describe('search, sort and scope', () => {
    it('narrows the list to partial username matches as you type', () => {
      renderReport();
      expect(visibleUsernames()).toEqual(['alice', 'bob', 'orphan']);

      typeSearch('ob');

      expect(visibleUsernames()).toEqual(['bob']);
    });

    it('matches case-insensitively', () => {
      renderReport();

      typeSearch('BOB');

      expect(visibleUsernames()).toEqual(['bob']);
    });

    it('reports how many of the whole roster is showing only while a filter is on', () => {
      renderReport();
      expect(screen.getByText('전체 3명')).toBeInTheDocument();

      typeSearch('o');

      expect(screen.getByText('3명 중 2명')).toBeInTheDocument();
    });

    it('shows an empty-result row with a reset that restores the full list', () => {
      renderReport();

      typeSearch('nobody-here');
      expect(visibleUsernames()).toEqual([]);
      expect(screen.getByText('조건에 맞는 회원이 없습니다.')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: '검색·필터 초기화' }));

      expect(visibleUsernames()).toEqual(['alice', 'bob', 'orphan']);
      expect(screen.getByText('전체 3명')).toBeInTheDocument();
    });

    it('keeps only admins under 관리자만, and only accountless rows under 잔여 기록만', () => {
      renderReport();

      choose('목록 범위', 'admin');
      expect(visibleUsernames()).toEqual(['alice']);

      choose('목록 범위', 'orphan');
      expect(visibleUsernames()).toEqual(['orphan']);
    });

    it('orders by bookmark, paper and curriculum count, and by most recent signup', () => {
      renderReport({ paperStats: PAPER_STATS });

      // bob: 2 bookmarks / 40 papers / 1 curriculum; alice and orphan trail.
      choose('정렬 기준', 'bookmarks');
      expect(visibleUsernames()[0]).toBe('bob');

      choose('정렬 기준', 'papers');
      expect(visibleUsernames()[0]).toBe('bob');

      choose('정렬 기준', 'curricula');
      expect(visibleUsernames()[0]).toBe('bob');

      // bob signed up 2025-03-15, alice 2025-01-01, orphan has no account at all.
      choose('정렬 기준', 'joined');
      expect(visibleUsernames()).toEqual(['bob', 'alice', 'orphan']);

      choose('정렬 기준', 'username');
      expect(visibleUsernames()).toEqual(['alice', 'bob', 'orphan']);
    });

    it('breaks count ties by username so the list does not shuffle between sorts', () => {
      // alice and orphan both hold 0 papers; the tie has to resolve the same way twice.
      renderReport({ paperStats: PAPER_STATS });

      choose('정렬 기준', 'papers');
      expect(visibleUsernames()).toEqual(['bob', 'alice', 'orphan']);

      choose('정렬 기준', 'curricula');
      expect(visibleUsernames()).toEqual(['bob', 'alice', 'orphan']);
    });

    it('never calls onExpandMember while filtering, so a live selection keeps belonging to one member', () => {
      // Search is the one new way an expanded row can leave the screen without
      // being collapsed. If filtering announced an expansion change, the parent
      // would load another member's papers under the current selection — the
      // cross-member index mix-up the delete path guards against.
      const onExpandMember = vi.fn();
      renderReport({ folderPapers: FOLDER_PAPERS, onExpandMember });

      fireEvent.click(getFolderToggle('bob'));
      expect(onExpandMember).toHaveBeenCalledTimes(1);

      typeSearch('alice');
      choose('목록 범위', 'admin');
      typeSearch('');
      choose('목록 범위', 'all');

      expect(onExpandMember).toHaveBeenCalledTimes(1);
      expect(onExpandMember).toHaveBeenLastCalledWith('bob');
    });

    it('renders no bulk bar while the expanded member is filtered out of the list', () => {
      // The bulk bar lives inside that member's panel, so hiding the row has to
      // take the count and the delete button with it.
      renderReport({ folderPapers: FOLDER_PAPERS, selectedPapers: new Set([0, 1]) });

      fireEvent.click(getFolderToggle('bob'));
      expect(screen.getByRole('button', { name: '선택 삭제' })).toBeInTheDocument();

      typeSearch('alice');

      expect(visibleUsernames()).toEqual(['alice']);
      expect(screen.queryByRole('button', { name: '선택 삭제' })).not.toBeInTheDocument();
      expect(screen.queryByText('2편 선택됨')).not.toBeInTheDocument();
    });

    it('clears a scope filter when a context-strip shortcut jumps to someone it excludes', () => {
      renderReport();

      choose('목록 범위', 'admin');   // only alice survives
      const strip = document.querySelector('.dashboard-context-strip') as HTMLElement;
      fireEvent.click(within(strip).getAllByRole('button', { name: 'bob' })[0]);

      // bob is not an admin; without clearing the scope the jump would land on nothing.
      expect(visibleUsernames()).toEqual(['bob']);
    });
  });

  // ── 키보드 ────────────────────────────────────────────────────────────────────

  describe('keyboard operation', () => {
    it('expands and collapses a member through a real button, reporting aria-expanded', () => {
      const onExpandMember = vi.fn();
      renderReport({ onExpandMember });
      const toggle = getFolderToggle('bob');

      // A native <button> is what makes Enter and Space work: the browser
      // activates it, so there is no key handler of our own left to test (and
      // jsdom does not synthesise the click from keyDown either).
      expect(toggle.tagName).toBe('BUTTON');
      expect(toggle).not.toHaveAttribute('role');
      expect(toggle).toHaveAttribute('aria-expanded', 'false');

      toggle.focus();
      expect(document.activeElement).toBe(toggle);

      fireEvent.click(toggle);
      expect(getFolderToggle('bob')).toHaveAttribute('aria-expanded', 'true');
      expect(onExpandMember).toHaveBeenCalledWith('bob');
      expect(screen.getByText('ML Papers')).toBeInTheDocument();

      fireEvent.click(getFolderToggle('bob'));
      expect(getFolderToggle('bob')).toHaveAttribute('aria-expanded', 'false');
      expect(onExpandMember).toHaveBeenLastCalledWith(null);
    });

    it('points aria-controls at the panel the row actually opens', () => {
      renderReport();

      fireEvent.click(getFolderToggle('bob'));

      const panelId = getFolderToggle('bob').getAttribute('aria-controls') as string;
      const panel = document.getElementById(panelId) as HTMLElement;
      expect(panel).toBeInTheDocument();
      expect(within(panel).getByText('ML Papers')).toBeInTheDocument();
    });

    it('reaches role change and deletion by keyboard alone', () => {
      const onToggleRole = vi.fn();
      const onDeleteUser = vi.fn();
      renderReport({ onToggleRole, onDeleteUser });

      const promote = within(getFolderRow('bob')).getByRole('button', { name: 'bob 권한 승격' });
      const remove = within(getFolderRow('bob')).getByRole('button', { name: 'bob 계정 삭제' });
      // Native <button>: focusable and Enter/Space activate it, so proving it takes
      // focus and fires on activation is what "keyboard reachable" means here.
      promote.focus();
      expect(document.activeElement).toBe(promote);
      fireEvent.click(promote);
      expect(onToggleRole).toHaveBeenCalledWith('bob', 'user');

      remove.focus();
      expect(document.activeElement).toBe(remove);
      fireEvent.click(remove);
      expect(onDeleteUser).toHaveBeenCalledWith('bob');
    });

    it('gives every paper checkbox an accessible name, select-all included', () => {
      renderReport({ folderPapers: FOLDER_PAPERS });
      fireEvent.click(getFolderToggle('bob'));

      expect(screen.getByRole('checkbox', { name: '이 페이지의 논문 전체 선택' })).toBeInTheDocument();
      expect(screen.getByRole('checkbox', { name: '논문 "Attention Is All You Need" 선택' })).toBeInTheDocument();
      expect(screen.getByRole('checkbox', { name: '논문 "BERT" 선택' })).toBeInTheDocument();
    });
  });
});
