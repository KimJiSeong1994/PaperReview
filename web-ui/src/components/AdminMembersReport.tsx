import { useId, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type {
  AdminUser,
  AdminBookmark,
  AdminCurriculaResponse,
  AdminCurriculumUser,
  AdminPaper,
  AdminPaperUserStats,
} from '../api/client';
import { FolderIcon, ChevronIcon, FileIcon, BookmarkIcon, CurriculumIcon } from './AdminTreeIcons';

const nf = new Intl.NumberFormat('ko-KR');
const fmt = (value: number) => nf.format(value ?? 0);

interface AdminMembersReportProps {
  users: AdminUser[];
  bookmarks: AdminBookmark[];
  curricula: AdminCurriculaResponse | null;
  loading: boolean;
  currentUsername: string;
  onToggleRole: (username: string, currentRole: string) => void;
  onDeleteUser: (username: string) => void;
  onDeleteBookmark: (bookmarkId: string, title: string) => void;
  /* 논문은 유저별 집계만 미리 받고, 폴더를 펼칠 때 비로소 한 페이지씩 로드한다. */
  paperStats: AdminPaperUserStats | null;
  folderPapers: AdminPaper[];
  folderPage: number;
  folderTotalPages: number;
  folderTotal: number;
  folderLoading: boolean;
  selectedPapers: Set<number>;
  onExpandMember: (username: string | null) => void;
  onPaperPageChange: (username: string, page: number) => void;
  onTogglePaperSelect: (index: number) => void;
  onToggleAllPapers: () => void;
  onDeletePapers: () => void;
}

/* 계정 · 북마크 · 커리큘럼 · 논문 수를 username 하나로 접어둔 행. */
interface MemberRow {
  username: string;
  account: AdminUser | null;
  bookmarks: AdminBookmark[];
  curriculum: AdminCurriculumUser | null;
  paperCount: number;
}

/* 500명 목록에서 관리자가 실제로 찾는 축. 정렬은 모두 내림차순(많은 순 /
   최근 순)이고, username 만 사전순이다. */
const SORTS = {
  username: 'username 순',
  bookmarks: '북마크 많은 순',
  papers: '논문 많은 순',
  curricula: '커리큘럼 많은 순',
  joined: '가입 최근순',
} as const;
type SortKey = keyof typeof SORTS;

const SCOPES = {
  all: '전체',
  admin: '관리자만',
  orphan: '계정 없는 잔여 기록만',
} as const;
type ScopeKey = keyof typeof SCOPES;

function InsightCard({ eyebrow, headline, body }: { eyebrow: string; headline: ReactNode; body: string }) {
  return (
    <article className="visits-insight-card">
      <p className="visits-insight-eyebrow">{eyebrow}</p>
      <h3 className="visits-insight-headline">{headline}</h3>
      <p className="visits-insight-body">{body}</p>
    </article>
  );
}

/* 최다 보유자는 그 자체로는 막다른 사실이라, 클릭하면 그 유저만 남기는
   검색 지름길로 쓴다. 기록이 없으면 누를 것도 없으므로 텍스트로 둔다. */
function TopHolder({ label, username, onJump }: { label: string; username: string | null; onJump: (u: string) => void }) {
  return (
    <div>
      <span>{label}</span>
      {username ? (
        <button type="button" className="dashboard-context-jump" onClick={() => onJump(username)}>
          {username}
        </button>
      ) : (
        <strong>기록 없음</strong>
      )}
    </div>
  );
}

export default function AdminMembersReport({
  users,
  bookmarks,
  curricula,
  loading,
  currentUsername,
  onToggleRole,
  onDeleteUser,
  onDeleteBookmark,
  paperStats,
  folderPapers,
  folderPage,
  folderTotalPages,
  folderTotal,
  folderLoading,
  selectedPapers,
  onExpandMember,
  onPaperPageChange,
  onTogglePaperSelect,
  onToggleAllPapers,
  onDeletePapers,
}: AdminMembersReportProps) {
  const [openMember, setOpenMember] = useState<string | null>(null);
  const [openBookmark, setOpenBookmark] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortKey>('username');
  const [scope, setScope] = useState<ScopeKey>('all');
  const panelIdBase = useId();

  // 계정이 사라진 뒤 남은 북마크/커리큘럼/논문도 보이도록 네 소스의 username 합집합으로 행을 만든다.
  const members = useMemo<MemberRow[]>(() => {
    const bookmarksByUser: Record<string, AdminBookmark[]> = {};
    for (const bm of bookmarks) {
      const user = bm.username || '(unknown)';
      if (!bookmarksByUser[user]) bookmarksByUser[user] = [];
      bookmarksByUser[user].push(bm);
    }
    const curriculumByUser = new Map<string, AdminCurriculumUser>(
      (curricula?.users ?? []).map((u) => [u.username, u]),
    );
    const accountByUser = new Map<string, AdminUser>(users.map((u) => [u.username, u]));
    const paperCountByUser = new Map<string, number>(
      (paperStats?.users ?? []).map((u) => [u.username, u.paper_count]),
    );

    const usernames = new Set<string>([
      ...accountByUser.keys(),
      ...Object.keys(bookmarksByUser),
      ...curriculumByUser.keys(),
      ...paperCountByUser.keys(),
    ]);

    return Array.from(usernames)
      .sort((a, b) => a.localeCompare(b))
      .map((username) => ({
        username,
        account: accountByUser.get(username) ?? null,
        bookmarks: bookmarksByUser[username] ?? [],
        curriculum: curriculumByUser.get(username) ?? null,
        paperCount: paperCountByUser.get(username) ?? 0,
      }));
  }, [users, bookmarks, curricula, paperStats]);

  // 500명 렌더는 137ms 라 병목이 아니다. 병목은 "찾기"이므로 서버 왕복 없이
  // 클라이언트에서 거른다.
  const visible = useMemo<MemberRow[]>(() => {
    const needle = search.trim().toLowerCase();
    const rows = members.filter((m) => {
      if (needle && !m.username.toLowerCase().includes(needle)) return false;
      if (scope === 'admin') return m.account?.role === 'admin';
      if (scope === 'orphan') return m.account === null;
      return true;
    });
    if (sort === 'username') return rows;
    // 동점이 흔해서(대부분 0) 2차 키를 username 으로 고정해야 목록이 흔들리지 않는다.
    const rank = (m: MemberRow) =>
      sort === 'bookmarks' ? m.bookmarks.length
        : sort === 'papers' ? m.paperCount
          : sort === 'curricula' ? (m.curriculum?.total_curricula ?? 0)
            : Date.parse(m.account?.created_at ?? '') || 0;
    return [...rows].sort((a, b) => rank(b) - rank(a) || a.username.localeCompare(b.username));
  }, [members, search, sort, scope]);

  const filtered = search.trim() !== '' || scope !== 'all';

  const adminCount = users.filter((u) => u.role === 'admin').length;
  const savedPapers = bookmarks.reduce((sum, bm) => sum + (bm.num_papers ?? 0), 0);
  const curriculaCount = curricula?.total_user_curricula ?? 0;
  const readPapers = (curricula?.users ?? []).reduce((sum, u) => sum + (u.total_read_papers ?? 0), 0);

  const topBookmarker = members.reduce<MemberRow | null>(
    (top, row) => (row.bookmarks.length > 0 && (!top || row.bookmarks.length > top.bookmarks.length) ? row : top),
    null,
  );
  const topLearner = (curricula?.users ?? []).reduce<AdminCurriculumUser | null>(
    (top, user) => (!top || user.total_curricula > top.total_curricula ? user : top),
    null,
  );
  const topCollector = members.reduce<MemberRow | null>(
    (top, row) => (row.paperCount > 0 && (!top || row.paperCount > top.paperCount) ? row : top),
    null,
  );

  // 지름길로 점프할 때 필터가 켜져 있으면 그 유저가 걸러져 사라지므로 함께 푼다.
  const jumpTo = (username: string) => {
    setSearch(username);
    setScope('all');
  };

  const resetFilters = () => {
    setSearch('');
    setScope('all');
  };

  const toggleMember = (username: string, isOpen: boolean) => {
    setOpenMember(isOpen ? null : username);
    setOpenBookmark(null);
    // 논문은 지연 로딩이라 부모가 열림/닫힘을 알아야 한다.
    onExpandMember(isOpen ? null : username);
  };

  if (loading) {
    return <div className="admin-loading">회원 정보를 불러오는 중...</div>;
  }
  if (members.length === 0) {
    return <div className="admin-empty">회원 데이터가 없습니다.</div>;
  }

  return (
    <article className="admin-dashboard visits-report dashboard-report admin-members-report">
      <header className="visits-report-header dashboard-report-header">
        <div className="visits-report-heading">
          <span className="visits-report-kicker">MEMBER OPERATIONS</span>
          <h1>회원 통합 관리</h1>
          <p>계정, 저장한 북마크, 학습 커리큘럼, 수집한 논문을 유저 한 명 단위로 묶어 한 화면에서 확인하고 조치합니다.</p>
        </div>
      </header>

      <section className="visits-summary" aria-labelledby="members-summary-title">
        <span className="visits-summary-kicker">핵심 요약</span>
        {/* 설명 문단 없이 바로 카드로 간다: 세 카드의 eyebrow 가 이미 "무엇을
            세 갈래로 나눴는지"를 말하고, 그 위 h1 부제가 한 번 더 말한다. */}
        <h2 id="members-summary-title">회원 활동을 세 갈래로 나눠 읽어보세요</h2>
        <div className="visits-insight-grid admin-members-insight-grid">
          <InsightCard
            eyebrow="계정 규모"
            headline={<>{fmt(users.length)}명 등록 · {fmt(adminCount)}명 관리자</>}
            body="현재 로그인 가능한 계정 수이며, 아래 목록의 계정 없는 행은 삭제된 유저의 잔여 기록입니다."
          />
          {/* 저장(북마크 안)과 수집(검색으로 적재된 전역 카탈로그)은 서로 다른
              모수다. 한 줄에 나란히 둬야 헷갈리지 않고, 값이 뒤바뀌면 바로 보인다. */}
          <InsightCard
            eyebrow="논문 규모"
            headline={<>{fmt(bookmarks.length)}개 북마크 · {fmt(savedPapers)}편 저장 · {fmt(paperStats?.total ?? 0)}편 수집</>}
            body="저장은 북마크에 담긴 논문의 합계, 수집은 검색으로 적재된 전역 카탈로그 규모입니다."
          />
          <InsightCard
            eyebrow="학습 활동"
            headline={<>{fmt(curriculaCount)}개 커리큘럼 · {fmt(readPapers)}편 읽음</>}
            body="유저가 직접 만들었거나 포크한 커리큘럼과, 그 안에서 읽음 처리한 논문 수입니다."
          />
        </div>
      </section>

      <div className="dashboard-context-strip" aria-label="최다 보유자 바로가기">
        <TopHolder label="최다 북마크 보유자" username={topBookmarker?.username ?? null} onJump={jumpTo} />
        <TopHolder label="최다 커리큘럼 보유자" username={topLearner?.username ?? null} onJump={jumpTo} />
        <TopHolder label="최다 논문 수집자" username={topCollector?.username ?? null} onJump={jumpTo} />
      </div>

      <section className="visits-section dashboard-section">
        <div className="admin-tree-wrapper">
          <div className="admin-tree-header admin-members-toolbar">
            <input
              type="search"
              className="admin-filter-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="username 검색"
              aria-label="username 검색"
            />
            <select
              className="admin-filter-select"
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
              aria-label="정렬 기준"
            >
              {Object.entries(SORTS).map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
            <select
              className="admin-filter-select"
              value={scope}
              onChange={(e) => setScope(e.target.value as ScopeKey)}
              aria-label="목록 범위"
            >
              {Object.entries(SCOPES).map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
            <span className="admin-filter-count" role="status">
              {filtered
                ? `${fmt(members.length)}명 중 ${fmt(visible.length)}명`
                : `전체 ${fmt(members.length)}명`}
            </span>
          </div>

          <div className="admin-tree">
            {visible.length === 0 ? (
              <div className="admin-tree-empty-result">
                <p>조건에 맞는 회원이 없습니다.</p>
                <button type="button" className="admin-action-btn" onClick={resetFilters}>
                  검색·필터 초기화
                </button>
              </div>
            ) : visible.map((member, idx) => {
              const isOpen = openMember === member.username;
              const isLast = idx === visible.length - 1;
              const isSelf = member.username === currentUsername;
              const account = member.account;
              const curriculum = member.curriculum;
              const panelId = `${panelIdBase}-member-${idx}`;
              // 디스클로저 버튼의 접근 이름은 감싼 내용에서 나오므로,
              // 행이 무엇을 담고 있는지 직접 읽어준다.
              const rowLabel = [
                member.username,
                account ? `권한 ${account.role}` : '계정 없음',
                member.bookmarks.length > 0 ? `북마크 ${member.bookmarks.length}` : null,
                (curriculum?.total_curricula ?? 0) > 0 ? `커리큘럼 ${curriculum?.total_curricula}` : null,
                (curriculum?.total_read_papers ?? 0) > 0 ? `읽음 ${curriculum?.total_read_papers}` : null,
                member.paperCount > 0 ? `논문 ${member.paperCount}` : null,
              ].filter(Boolean).join(', ');
              return (
                <div key={member.username} className={`admin-tree-folder ${isLast ? 'last' : ''}`}>
                  {/* 유저 폴더 행. 북마크 행(아래)과 같은 모양이다: 행 자체는
                      평범한 div 이고, 디스클로저와 액션 버튼이 형제로 나란히
                      선다. 행을 통째로 버튼으로 만들면 안에 있는 액션 버튼이
                      중첩 상호작용이 돼, 규범대로 자손을 잘라내는 스크린리더에서
                      아예 사라지고 Chromium 에서도 브라우즈 모드 화살표로 닿지
                      않는다. */}
                  <div className={`admin-tree-folder-row ${isOpen ? 'open' : ''}`}>
                    <button
                      type="button"
                      className="admin-tree-folder-toggle"
                      aria-expanded={isOpen}
                      aria-controls={panelId}
                      aria-label={rowLabel}
                      onClick={() => toggleMember(member.username, isOpen)}
                    >
                      <ChevronIcon />
                      <FolderIcon open={isOpen} />
                      <span className="admin-tree-folder-name">{member.username}</span>
                      {account && (
                        <span className={`admin-role-badge admin-role-badge--${account.role}`}>
                          {account.role}
                        </span>
                      )}
                      <div className="admin-cur-badges">
                        {member.bookmarks.length > 0 && (
                          <span className="admin-cur-badge admin-cur-badge--custom">
                            북마크 {member.bookmarks.length}
                          </span>
                        )}
                        {(curriculum?.total_curricula ?? 0) > 0 && (
                          <span className="admin-cur-badge admin-cur-badge--fork">
                            커리큘럼 {curriculum?.total_curricula}
                          </span>
                        )}
                        {(curriculum?.total_read_papers ?? 0) > 0 && (
                          <span className="admin-cur-badge admin-cur-badge--progress">
                            읽음 {curriculum?.total_read_papers}
                          </span>
                        )}
                        {member.paperCount > 0 && (
                          <span className="admin-cur-badge admin-cur-badge--papers">
                            논문 {member.paperCount}
                          </span>
                        )}
                      </div>
                    </button>
                    {account && (
                      <div className="admin-member-actions">
                        <button
                          className="admin-action-btn"
                          aria-label={`${account.username} ${account.role === 'admin' ? '권한 해제' : '권한 승격'}`}
                          onClick={() => onToggleRole(account.username, account.role)}
                          disabled={isSelf}
                        >
                          {account.role === 'admin' ? '권한 해제' : '권한 승격'}
                        </button>
                        <button
                          className="admin-action-btn admin-action-btn--danger"
                          aria-label={`${account.username} 계정 삭제`}
                          onClick={() => onDeleteUser(account.username)}
                          disabled={isSelf}
                        >
                          삭제
                        </button>
                      </div>
                    )}
                  </div>

                  {/* 펼친 상세: 북마크 + 커리큘럼 */}
                  {isOpen && (
                    <div className="admin-tree-children" id={panelId}>
                      <div className="admin-member-subhead">계정</div>
                      <div className="admin-member-meta">
                        {account ? (
                          <>
                            역할 {account.role}
                            {account.created_at && <> &middot; 가입 {new Date(account.created_at).toLocaleDateString()}</>}
                          </>
                        ) : (
                          '삭제된 계정의 잔여 기록'
                        )}
                        {(curriculum?.fork_count ?? 0) > 0 && <> &middot; 포크 {curriculum?.fork_count}</>}
                        {(curriculum?.custom_count ?? 0) > 0 && <> &middot; 커스텀 {curriculum?.custom_count}</>}
                      </div>

                      <div className="admin-member-subhead">북마크</div>
                      {member.bookmarks.length === 0 ? (
                        <div className="admin-tree-empty-hint">저장한 북마크가 없습니다.</div>
                      ) : (
                        member.bookmarks.map((bm) => {
                          const bmExpanded = openBookmark === bm.id;
                          return (
                            <div key={bm.id} className="admin-tree-bookmark-node">
                              <div className={`admin-tree-file ${bmExpanded ? 'admin-tree-file--open' : ''}`}>
                                <div className="admin-tree-guide-line" />
                                {bm.papers.length > 0 ? (
                                  <button
                                    className={`admin-tree-expand-mini ${bmExpanded ? 'open' : ''}`}
                                    aria-label={`북마크 "${bm.title}" 논문 목록`}
                                    aria-expanded={bmExpanded}
                                    onClick={(e) => { e.stopPropagation(); setOpenBookmark(bmExpanded ? null : bm.id); }}
                                  >
                                    <ChevronIcon />
                                  </button>
                                ) : (
                                  <span style={{ width: 24, flexShrink: 0 }} />
                                )}
                                <BookmarkIcon />
                                <div className="admin-tree-file-info" style={{ flex: 1 }}>
                                  <span className="admin-tree-file-title">{bm.title}</span>
                                  <span className="admin-tree-file-meta">
                                    {bm.topic}{bm.num_papers > 0 && <> &middot; 논문 {bm.num_papers}편</>}
                                    {bm.query && <> &middot; "{bm.query}"</>}
                                    {bm.created_at && <> &middot; {new Date(bm.created_at).toLocaleDateString()}</>}
                                  </span>
                                </div>
                                <button
                                  className="admin-action-btn admin-action-btn--danger"
                                  style={{ flexShrink: 0, marginLeft: 8 }}
                                  aria-label={`북마크 "${bm.title}" 삭제`}
                                  onClick={(e) => { e.stopPropagation(); onDeleteBookmark(bm.id, bm.title); }}
                                >
                                  삭제
                                </button>
                              </div>

                              {/* 북마크 내부 논문 */}
                              {bmExpanded && bm.papers.length > 0 && (
                                <div className="admin-tree-sub-children">
                                  {bm.papers.map((p, pIdx) => (
                                    <div key={pIdx} className="admin-tree-file admin-tree-sub-file">
                                      <div className="admin-tree-guide-line" />
                                      <FileIcon />
                                      <div className="admin-tree-file-info">
                                        <span className="admin-tree-file-title">{p.title}</span>
                                        {p.authors.length > 0 && (
                                          <span className="admin-tree-file-meta">
                                            {p.authors.slice(0, 3).join(', ')}{p.authors.length > 3 ? ' et al.' : ''}
                                          </span>
                                        )}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })
                      )}

                      <div className="admin-member-subhead">커리큘럼</div>
                      {!curriculum || curriculum.curricula.length === 0 ? (
                        <div className="admin-tree-empty-hint">
                          보유한 커리큘럼이 없습니다 (프리셋 진도만 있을 수 있음).
                        </div>
                      ) : (
                        curriculum.curricula.map((cur) => (
                          <div key={cur.id} className="admin-tree-file">
                            <div className="admin-tree-guide-line" />
                            <CurriculumIcon type={cur.type} />
                            <div className="admin-tree-file-info" style={{ flex: 1 }}>
                              <span className="admin-tree-file-title">{cur.name}</span>
                              <span className="admin-tree-file-meta">
                                <span className={`admin-cur-type admin-cur-type--${cur.type}`}>
                                  {cur.type}
                                </span>
                                {cur.forked_from && <> · 원본 {cur.forked_from}</>}
                                {' · '}모듈 {cur.total_modules}개 · 논문 {cur.total_papers}편
                                {' · '}{cur.difficulty}
                              </span>
                            </div>
                          </div>
                        ))
                      )}

                      {(curriculum?.total_read_papers ?? 0) > 0 && (
                        <div className="admin-cur-progress-summary">
                          <span className="admin-cur-progress-label">읽기 진도</span>
                          <span className="admin-cur-progress-value">
                            강의 {curriculum?.courses_with_progress}개에서 논문 {curriculum?.total_read_papers}편 읽음
                          </span>
                        </div>
                      )}

                      <div className="admin-member-subhead">수집 논문</div>

                      {folderLoading ? (
                        <div className="admin-tree-empty-hint">논문을 불러오는 중...</div>
                      ) : folderPapers.length === 0 ? (
                        <div className="admin-tree-empty-hint">수집한 논문이 없습니다.</div>
                      ) : (
                        <>
                          {/* 벌크 바는 이 분기 안에서만 산다: 로딩 중이거나 빈
                              폴더일 때 렌더되면, 화면에 없는(또는 다른 유저의)
                              논문을 가리키는 개수와 삭제 버튼이 눌린다. */}
                          {selectedPapers.size > 0 && (
                            <div className="admin-bulk-bar" style={{ margin: '0 0 8px 0', borderRadius: 8 }}>
                              <span className="admin-bulk-count">{selectedPapers.size}편 선택됨</span>
                              <button className="admin-bulk-delete-btn" onClick={onDeletePapers}>
                                선택 삭제
                              </button>
                            </div>
                          )}

                          <div className="admin-tree-select-all">
                            <label className="admin-checkbox-hit">
                              <input
                                type="checkbox"
                                className="admin-checkbox"
                                aria-label="이 페이지의 논문 전체 선택"
                                checked={folderPapers.length > 0 && selectedPapers.size === folderPapers.length}
                                onChange={onToggleAllPapers}
                              />
                            </label>
                            <span className="admin-tree-select-all-label">이 페이지 전체 선택</span>
                          </div>

                          {folderPapers.map((p) => (
                            <div key={p.index} className="admin-tree-file">
                              <div className="admin-tree-guide-line" />
                              <label className="admin-checkbox-hit">
                                <input
                                  type="checkbox"
                                  className="admin-checkbox"
                                  aria-label={`논문 "${p.title}" 선택`}
                                  checked={selectedPapers.has(p.index)}
                                  onChange={() => onTogglePaperSelect(p.index)}
                                />
                              </label>
                              <FileIcon />
                              <div className="admin-tree-file-info">
                                <span className="admin-tree-file-title">{p.title}</span>
                                <span className="admin-tree-file-meta">
                                  {p.authors.join(', ')}{p.source && <> &middot; {p.source}</>}{p.published_date && <> &middot; {p.published_date}</>}
                                </span>
                              </div>
                            </div>
                          ))}

                          {folderTotalPages > 1 && (
                            <div className="admin-pagination" style={{ padding: '10px 0' }}>
                              <button
                                className="admin-page-btn"
                                disabled={folderPage <= 1}
                                onClick={() => onPaperPageChange(member.username, folderPage - 1)}
                              >
                                이전
                              </button>
                              <span className="admin-page-info">
                                {folderPage} / {folderTotalPages} ({folderTotal})
                              </span>
                              <button
                                className="admin-page-btn"
                                disabled={folderPage >= folderTotalPages}
                                onClick={() => onPaperPageChange(member.username, folderPage + 1)}
                              >
                                다음
                              </button>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </section>
    </article>
  );
}
