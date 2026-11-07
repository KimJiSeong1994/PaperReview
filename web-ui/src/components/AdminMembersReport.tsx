import { useId, useMemo, useState } from 'react';
import { fetchAdminSoulStats } from '../api/client';
import type { AdminWindowDays, AdminUser } from '../api/client';
import { FolderIcon, ChevronIcon } from './AdminTreeIcons';
import { MEMORY_KIND_LABELS, useBlock } from './adminShared';
import { AdminTabHeader, BlockBody } from './AdminUi';

const nf = new Intl.NumberFormat('ko-KR');
const fmt = (value: number) => nf.format(value ?? 0);
const day = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString() : '없음');
// Table cells: a dash reads faster than '없음' in a column of dates.
const cellDay = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString() : '—');

interface AdminMembersReportProps {
  /** Window for the memory aggregates; the strip shows totals, so it only affects freshness. */
  days?: AdminWindowDays;
  users: AdminUser[];
  loading: boolean;
  currentUsername: string;
  onToggleRole: (username: string, currentRole: string) => void;
  onDeleteUser: (username: string) => void;
}

const SORTS = {
  username: 'username 순',
  joined: '가입 최근순',
  conversation: '최근 대화',
} as const;
type SortKey = keyof typeof SORTS;

const SCOPES = {
  all: '전체',
  admin: '관리자만',
} as const;
type ScopeKey = keyof typeof SCOPES;


export default function AdminMembersReport({
  days = 7,
  users,
  loading,
  currentUsername,
  onToggleRole,
  onDeleteUser,
}: AdminMembersReportProps) {
  const [openMember, setOpenMember] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortKey>('username');
  const [scope, setScope] = useState<ScopeKey>('all');
  const panelIdBase = useId();
  const souls = useBlock(fetchAdminSoulStats, days);

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const rows = users.filter((user) =>
      (!needle || user.username.toLowerCase().includes(needle)) &&
      (scope !== 'admin' || user.role === 'admin'),
    );
    const rank = (user: AdminUser) => Date.parse(
      (sort === 'conversation' ? user.last_conversation_at : user.created_at) ?? '',
    ) || 0;
    return [...rows].sort((a, b) =>
      (sort === 'username' ? 0 : rank(b) - rank(a)) || a.username.localeCompare(b.username),
    );
  }, [users, search, sort, scope]);

  const filtered = search.trim() !== '' || scope !== 'all';

  const resetFilters = () => {
    setSearch('');
    setScope('all');
  };

  const toggleMember = (username: string, isOpen: boolean) => {
    setOpenMember(isOpen ? null : username);
  };

  if (loading) {
    return <div className="admin-loading">회원 정보를 불러오는 중...</div>;
  }
  if (users.length === 0) {
    return <div className="admin-empty">회원 데이터가 없습니다.</div>;
  }

  return (
    <article className="admin-dashboard visits-report dashboard-report admin-members-report admin-tabview" aria-labelledby="admin-members-title">
      <AdminTabHeader id="admin-members-title" title="회원" range={`${fmt(users.length)}명 등록`} />

      <div className="admin-strip" role="group" aria-label="회원 집계">
        <span>회원 <strong>{fmt(users.length)}</strong></span>
        <BlockBody block={souls} label="메모리 집계">
          {(stats) => (
            <>
              <span>메모리 보유 계정 <strong>{fmt(stats.accounts.with_memories)}</strong></span>
              <span>프로필 <strong>{fmt(stats.profiles.total)}</strong> · 24h 지남 {fmt(stats.profiles.stale_over_24h)}</span>
              <span className="admin-strip-kinds">
                종류별 메모리
                {stats.memories.by_kind.map((k) => (
                  <span key={k.kind}>{MEMORY_KIND_LABELS[k.kind] ?? k.kind} {fmt(k.count)}</span>
                ))}
              </span>
            </>
          )}
        </BlockBody>
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
                ? `${fmt(users.length)}명 중 ${fmt(visible.length)}명`
                : `전체 ${fmt(users.length)}명`}
            </span>
          </div>

          <div className="admin-members-head" aria-hidden="true">
            <span>username</span>
            <span>가입일</span><span>대화</span><span>마지막 대화</span><span>메모리</span>
            <span>프로필 갱신</span><span>역할</span>
            <span />
          </div>
          <div className="admin-tree">
            {visible.length === 0 ? (
              <div className="admin-tree-empty-result">
                <p>조건에 맞는 회원이 없습니다.</p>
                <button type="button" className="admin-action-btn" onClick={resetFilters}>
                  검색·필터 초기화
                </button>
              </div>
            ) : visible.map((account, idx) => {
              const isOpen = openMember === account.username;
              const isLast = idx === visible.length - 1;
              const isSelf = account.username === currentUsername;
              const panelId = `${panelIdBase}-member-${idx}`;
              // 디스클로저 버튼의 접근 이름은 감싼 내용에서 나오므로,
              // 행이 무엇을 담고 있는지 직접 읽어준다.
              const rowLabel = [
                account.username,
                `권한 ${account.role}`,
                (account.conversation_count ?? 0) > 0 ? `대화 ${account.conversation_count}` : null,
                (account.memory_count ?? 0) > 0 ? `메모리 ${account.memory_count}` : null,
              ].filter(Boolean).join(', ');
              return (
                <div key={account.username} className={`admin-tree-folder ${isLast ? 'last' : ''}`}>
                  <div className={`admin-tree-folder-row ${isOpen ? 'open' : ''}`}>
                    <button
                      type="button"
                      className="admin-tree-folder-toggle"
                      aria-expanded={isOpen}
                      aria-controls={panelId}
                      aria-label={rowLabel}
                      onClick={() => toggleMember(account.username, isOpen)}
                    >
                      <ChevronIcon />
                      <FolderIcon open={isOpen} />
                      <span className="admin-tree-folder-name">{account.username}</span>
                      <span className="admin-member-cells">
                        <span>{cellDay(account.created_at)}</span>
                        <span>{fmt(account.conversation_count)}</span>
                        <span>{cellDay(account.last_conversation_at)}</span>
                        <span>{fmt(account.memory_count)}</span>
                        <span>{cellDay(account.profile_updated_at)}</span>
                        <span>
                          <span className={`admin-role-badge admin-role-badge--${account.role}`}>{account.role}</span>
                        </span>
                      </span>
                    </button>
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
                  </div>

                  {isOpen && (
                    <div className="admin-tree-children" id={panelId}>
                      <div className="admin-member-subhead">계정</div>
                      <div className="admin-member-meta">
                        역할 {account.role} &middot; 가입 {day(account.created_at)}
                      </div>
                      <div className="admin-member-meta">
                        대화 {fmt(account.conversation_count)}개 &middot; 최근 대화 {day(account.last_conversation_at)}
                        {' '}&middot; 메모리 {fmt(account.memory_count)}개 &middot; 연구 프로필 갱신 {day(account.profile_updated_at)}
                      </div>
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
