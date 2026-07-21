import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type {
  AdminUser,
  AdminBookmark,
  AdminCurriculaResponse,
  AdminCurriculumUser,
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
}

/* 계정 · 북마크 · 커리큘럼을 username 하나로 접어둔 행. */
interface MemberRow {
  username: string;
  account: AdminUser | null;
  bookmarks: AdminBookmark[];
  curriculum: AdminCurriculumUser | null;
}

function InsightCard({ eyebrow, headline, body }: { eyebrow: string; headline: ReactNode; body: string }) {
  return (
    <article className="visits-insight-card">
      <p className="visits-insight-eyebrow">{eyebrow}</p>
      <h3 className="visits-insight-headline">{headline}</h3>
      <p className="visits-insight-body">{body}</p>
    </article>
  );
}

function Band({ label, title, description }: { label: string; title: string; description: string }) {
  return (
    <header className="visits-band" aria-label={label}>
      <span className="visits-band-eyebrow">{label}</span>
      <h2>{title}</h2>
      <p>{description}</p>
    </header>
  );
}

function StatTile({ label, value, hint }: { label: string; value: ReactNode; hint: string }) {
  return (
    <article className="admin-stat-card">
      <p className="admin-stat-label">{label}</p>
      <p className="admin-stat-value">{value}</p>
      <p className="visits-stat-hint">{hint}</p>
    </article>
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
}: AdminMembersReportProps) {
  const [openMember, setOpenMember] = useState<string | null>(null);
  const [openBookmark, setOpenBookmark] = useState<string | null>(null);

  // 계정이 사라진 뒤 남은 북마크/커리큘럼도 보이도록 세 소스의 username 합집합으로 행을 만든다.
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

    const usernames = new Set<string>([
      ...accountByUser.keys(),
      ...Object.keys(bookmarksByUser),
      ...curriculumByUser.keys(),
    ]);

    return Array.from(usernames)
      .sort((a, b) => a.localeCompare(b))
      .map((username) => ({
        username,
        account: accountByUser.get(username) ?? null,
        bookmarks: bookmarksByUser[username] ?? [],
        curriculum: curriculumByUser.get(username) ?? null,
      }));
  }, [users, bookmarks, curricula]);

  const adminCount = users.filter((u) => u.role === 'admin').length;
  const savedPapers = bookmarks.reduce((sum, bm) => sum + (bm.num_papers ?? 0), 0);
  const curriculaCount = curricula?.total_user_curricula ?? 0;
  const usersWithCurricula = curricula?.total_users_with_curricula ?? 0;
  const readPapers = (curricula?.users ?? []).reduce((sum, u) => sum + (u.total_read_papers ?? 0), 0);

  const topBookmarker = members.reduce<MemberRow | null>(
    (top, row) => (row.bookmarks.length > 0 && (!top || row.bookmarks.length > top.bookmarks.length) ? row : top),
    null,
  );
  const topLearner = (curricula?.users ?? []).reduce<AdminCurriculumUser | null>(
    (top, user) => (!top || user.total_curricula > top.total_curricula ? user : top),
    null,
  );

  if (loading) {
    return <div className="admin-loading">Loading members...</div>;
  }
  if (members.length === 0) {
    return <div className="admin-empty">회원 데이터가 없습니다.</div>;
  }

  return (
    <article className="admin-dashboard visits-report dashboard-report">
      <header className="visits-report-header dashboard-report-header">
        <div className="visits-report-heading">
          <span className="visits-report-kicker">MEMBER OPERATIONS</span>
          <h1>회원 통합 관리</h1>
          <p>계정, 저장한 북마크, 학습 커리큘럼을 유저 한 명 단위로 묶어 한 화면에서 확인하고 조치합니다.</p>
        </div>
      </header>

      <section className="visits-summary" aria-labelledby="members-summary-title">
        <span className="visits-summary-kicker">핵심 요약</span>
        <h2 id="members-summary-title">회원 활동을 세 갈래로 나눠 읽어보세요</h2>
        <p className="visits-summary-copy">
          누가 등록돼 있는지, 무엇을 저장했는지, 얼마나 학습을 이어가고 있는지를 순서대로 보여줍니다.
        </p>
        <div className="visits-insight-grid">
          <InsightCard
            eyebrow="계정 규모"
            headline={<>{fmt(users.length)}명 등록 · {fmt(adminCount)}명 관리자</>}
            body="현재 로그인 가능한 계정 수이며, 아래 목록의 계정 없는 행은 삭제된 유저의 잔여 기록입니다."
          />
          <InsightCard
            eyebrow="저장 활동"
            headline={<>{fmt(bookmarks.length)}개 북마크 · {fmt(savedPapers)}편 논문</>}
            body="북마크에 담긴 논문 수의 합계로, 전역 논문 카탈로그 규모와는 다릅니다."
          />
          <InsightCard
            eyebrow="학습 활동"
            headline={<>{fmt(curriculaCount)}개 커리큘럼 · {fmt(readPapers)}편 읽음</>}
            body="유저가 직접 만들었거나 포크한 커리큘럼과, 그 안에서 읽음 처리한 논문 수입니다."
          />
        </div>
      </section>

      <div className="dashboard-context-strip" aria-label="리포트 기준">
        <div><span>집계 기준</span><strong>유저 단위 통합</strong></div>
        <div><span>최다 북마크 보유자</span><strong>{topBookmarker?.username ?? '기록 없음'}</strong></div>
        <div><span>최다 커리큘럼 보유자</span><strong>{topLearner?.username ?? '기록 없음'}</strong></div>
      </div>

      <Band
        label="회원 기반"
        title="계정과 활동 규모"
        description="계정 수와 저장·학습 활동이 각각 어느 정도 쌓여 있는지 봅니다."
      />

      <section className="visits-section dashboard-section">
        <div className="dashboard-section-heading">
          <div>
            <span>01 · MEMBERS</span>
            <h3>회원 규모</h3>
          </div>
          <p>계정과 유저 활동의 누적 규모</p>
        </div>
        <div className="admin-stats-grid dashboard-stat-grid">
          <StatTile label="사용자" value={fmt(users.length)} hint="등록 계정" />
          <StatTile label="관리자" value={fmt(adminCount)} hint="admin 권한" />
          <StatTile label="북마크" value={fmt(bookmarks.length)} hint="저장 행동" />
          <StatTile label="저장 논문" value={fmt(savedPapers)} hint="북마크 내 논문" />
          <StatTile label="커리큘럼" value={fmt(curriculaCount)} hint={`${fmt(usersWithCurricula)}명 보유`} />
          <StatTile label="읽은 논문" value={fmt(readPapers)} hint="진도 기록" />
        </div>
      </section>

      <Band
        label="회원 상세"
        title="유저별 계정 · 북마크 · 커리큘럼"
        description="유저를 펼치면 그 사람이 저장한 북마크와 진행 중인 커리큘럼을 한 번에 확인할 수 있습니다."
      />

      <section className="visits-section dashboard-section">
        <div className="admin-tree-wrapper">
          <div className="admin-tree-header">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#6b7280" strokeWidth="1.5">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            <span className="admin-tree-header-title">Members</span>
            <span className="admin-tree-header-count">{members.length} users</span>
          </div>

          <div className="admin-tree">
            {members.map((member, idx) => {
              const isOpen = openMember === member.username;
              const isLast = idx === members.length - 1;
              const isSelf = member.username === currentUsername;
              const account = member.account;
              const curriculum = member.curriculum;
              return (
                <div key={member.username} className={`admin-tree-folder ${isLast ? 'last' : ''}`}>
                  {/* 유저 폴더 행 */}
                  <div
                    className={`admin-tree-folder-row ${isOpen ? 'open' : ''}`}
                    onClick={() => {
                      setOpenMember(isOpen ? null : member.username);
                      setOpenBookmark(null);
                    }}
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
                    </div>
                    {account && (
                      <div className="admin-member-actions">
                        <button
                          className="admin-action-btn"
                          onClick={(e) => { e.stopPropagation(); onToggleRole(account.username, account.role); }}
                          disabled={isSelf}
                        >
                          {account.role === 'admin' ? 'Demote' : 'Promote'}
                        </button>
                        <button
                          className="admin-action-btn admin-action-btn--danger"
                          onClick={(e) => { e.stopPropagation(); onDeleteUser(account.username); }}
                          disabled={isSelf}
                        >
                          Delete
                        </button>
                      </div>
                    )}
                  </div>

                  {/* 펼친 상세: 북마크 + 커리큘럼 */}
                  {isOpen && (
                    <div className="admin-tree-children">
                      <div className="admin-member-subhead">Account</div>
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

                      <div className="admin-member-subhead">Bookmarks</div>
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
                                    onClick={(e) => { e.stopPropagation(); setOpenBookmark(bmExpanded ? null : bm.id); }}
                                  >
                                    <ChevronIcon />
                                  </button>
                                ) : (
                                  <span style={{ width: 16, flexShrink: 0 }} />
                                )}
                                <BookmarkIcon />
                                <div className="admin-tree-file-info" style={{ flex: 1 }}>
                                  <span className="admin-tree-file-title">{bm.title}</span>
                                  <span className="admin-tree-file-meta">
                                    {bm.topic}{bm.num_papers > 0 && <> &middot; {bm.num_papers} papers</>}
                                    {bm.query && <> &middot; "{bm.query}"</>}
                                    {bm.created_at && <> &middot; {new Date(bm.created_at).toLocaleDateString()}</>}
                                  </span>
                                </div>
                                <button
                                  className="admin-action-btn admin-action-btn--danger"
                                  style={{ flexShrink: 0, marginLeft: 8 }}
                                  onClick={(e) => { e.stopPropagation(); onDeleteBookmark(bm.id, bm.title); }}
                                >
                                  Delete
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

                      <div className="admin-member-subhead">Curricula</div>
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
                                {cur.forked_from && <> · from {cur.forked_from}</>}
                                {' · '}{cur.total_modules} modules · {cur.total_papers} papers
                                {' · '}{cur.difficulty}
                              </span>
                            </div>
                          </div>
                        ))
                      )}

                      {(curriculum?.total_read_papers ?? 0) > 0 && (
                        <div className="admin-cur-progress-summary">
                          <span className="admin-cur-progress-label">Reading Progress</span>
                          <span className="admin-cur-progress-value">
                            {curriculum?.total_read_papers} papers read across {curriculum?.courses_with_progress} course{curriculum?.courses_with_progress !== 1 ? 's' : ''}
                          </span>
                        </div>
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
