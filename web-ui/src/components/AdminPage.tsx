import { useState, useEffect, useCallback, useRef, lazy, Suspense } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import './AdminPage.css';

const AdminOverviewTab = lazy(() => import('./AdminOverviewTab'));
const AdminConversationsTab = lazy(() => import('./AdminConversationsTab'));
const AdminVisitsReport = lazy(() => import('./AdminVisitsReport'));
const AdminMembersReport = lazy(() => import('./AdminMembersReport'));
const AdminContentTab = lazy(() => import('./AdminContentTab'));
const AdminSystemTab = lazy(() => import('./AdminSystemTab'));
import { useAdminWindow } from './adminShared';
import { getAdminUsers, updateUserRole, deleteUser } from '../api/client';
import type { AdminUser } from '../api/client';

type Tab = 'overview' | 'conversations' | 'growth' | 'members' | 'content' | 'system';

// Each tab answers one ops question; the order is the order an operator asks them.
const TAB_LABELS: Record<Tab, string> = {
  overview: '대시보드',
  conversations: '대화',
  growth: '성장',
  members: '회원',
  content: '콘텐츠',
  system: '시스템',
};

// Old ?tab= links keep landing somewhere sensible.
const TAB_ALIASES: Record<string, Tab> = { dashboard: 'overview', visits: 'growth', mcp: 'system', members: 'members' };
const tabFromParam = (value: string | null): Tab => {
  if (value && value in TAB_LABELS) return value as Tab;
  return (value && TAB_ALIASES[value]) || 'overview';
};

// Deletion stage keys (routers/deps/user_deletion.py) in the admin's words; unknown keys show as-is.
const DELETION_STAGE_LABELS: Record<string, string> = {
  conversations: '대화',
  souls: '메모리·연구 프로필',
  bookmarks: '북마크',
  events_db: '리뷰 이벤트',
  rubric_db: '루브릭 프로필',
  profile_emb: '임베딩',
  papers_anonymize: '논문 익명화',
  blog_anonymize: '블로그 익명화',
  curriculum_anonymize: '커리큘럼 익명화',
  review_sessions_memory: '진행 중 리뷰',
  mcp_analytics: 'MCP 사용 기록',
  recommendations: '추천 기록',
  account_authority: '계정 권한',
  audit_log: '감사 로그',
  analytics: '방문 분석',
};

export default function AdminPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = tabFromParam(searchParams.get('tab'));
  const setActiveTab = (tab: Tab) => setSearchParams(tab === 'overview' ? {} : { tab }, { replace: true });
  const [days, setDays] = useAdminWindow();

  // Users
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);

  // Confirm dialog
  const [confirm, setConfirm] = useState<{
    title: string;
    message: string;
    onConfirm: () => void | Promise<void>;
  } | null>(null);
  // Prevent duplicate confirmation clicks from submitting the same deletion twice.
  const confirmBusy = useRef(false);
  const confirmDialogRef = useRef<HTMLDivElement>(null);
  // 다이얼로그를 연 버튼. 닫을 때 포커스를 그 자리로 돌려놔야 키보드 사용자가
  // 목록 맨 위로 튕기지 않는다.
  const confirmTriggerRef = useRef<HTMLElement | null>(null);

  const askConfirm = useCallback((next: NonNullable<typeof confirm>) => {
    confirmTriggerRef.current = document.activeElement as HTMLElement | null;
    setConfirm(next);
  }, []);

  const closeConfirm = useCallback(() => {
    setConfirm(null);
    confirmTriggerRef.current?.focus();
  }, []);

  // Escape-to-close and initial focus into the dialog, the same shape as the
  // other dialogs here (RecommendationBell.tsx, BlogPage.tsx, SearchPage.tsx).
  useEffect(() => {
    if (!confirm) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeConfirm();
    };
    document.addEventListener('keydown', handleKeyDown);
    confirmDialogRef.current?.focus();
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [confirm, closeConfirm]);

  // Transient notice (success/error feedback for admin actions).
  const [notice, setNotice] = useState<{
    kind: 'success' | 'warn' | 'error';
    text: string;
  } | null>(null);

  // Auto-dismiss the notice after 5s so it never lingers indefinitely.
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 5000);
    return () => clearTimeout(t);
  }, [notice]);

  const currentUsername = localStorage.getItem('username') || '';

  // ── Data loaders ─────────────────────────────────────────────────

  const loadUsers = useCallback(async () => {
    setUsersLoading(true);
    try {
      const data = await getAdminUsers();
      setUsers(data.users);
    } catch {
      /* ignore */
    } finally {
      setUsersLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'members') loadUsers();
  }, [activeTab, loadUsers]);

  // ── User actions ─────────────────────────────────────────────────

  const handleToggleRole = async (username: string, currentRole: string) => {
    const newRole = currentRole === 'admin' ? 'user' : 'admin';
    try {
      await updateUserRole(username, newRole);
      setUsers((prev) =>
        prev.map((u) => (u.username === username ? { ...u, role: newRole } : u)),
      );
    } catch {
      /* ignore */
    }
  };

  const handleDeleteUser = (username: string) => {
    const target = users.find((u) => u.username === username);
    const owned = target && (target.conversation_count > 0 || target.memory_count > 0)
      ? `대화 ${target.conversation_count}개와 메모리 ${target.memory_count}개를 포함해 `
      : '';
    askConfirm({
      title: '계정 삭제',
      message:
        `${owned}"${username}" 계정을 완전히 삭제합니다. 대화·메모리·연구 프로필·방문 분석 이벤트, 북마크, 리뷰 이벤트, ` +
        `임베딩, 큐레이션 소유권까지 모두 제거되며 되돌릴 수 없습니다.`,
      onConfirm: async () => {
        closeConfirm();
        try {
          const result = await deleteUser(username);
          // Refresh from backend rather than optimistically splicing so
          // partial failures don't produce a stale-but-"gone" row.
          await loadUsers();

          const partials: string[] = Array.isArray(result?.partial_failures)
            ? result.partial_failures
            : [];
          if (result?.success && partials.length === 0) {
            setNotice({ kind: 'success', text: `"${username}" 삭제 완료.` });
          } else {
            setNotice({
              kind: 'warn',
              text:
                `"${username}" 일부 단계 실패: ${partials.map((key) => DELETION_STAGE_LABELS[key] ?? key).join(', ') || '알 수 없음'}. ` +
                `계정 자체는 제거됐지만 로그를 확인하세요.`,
            });
          }
        } catch (err: unknown) {
          // Surface backend HTTPException detail (403 last-admin,
          // 400 self-delete, 429 rate-limit, etc.) instead of silently
          // swallowing — that was the original "삭제해도 반영이 안 된다"
          // symptom: admin clicked delete, backend refused, UI showed
          // nothing.
          const detail =
            (err as { response?: { data?: { detail?: string } } })?.response
              ?.data?.detail ??
            (err instanceof Error ? err.message : '삭제에 실패했습니다');
          setNotice({ kind: 'error', text: `삭제 실패: ${detail}` });
        }
      },
    });
  };

  // ── Render ───────────────────────────────────────────────────────

  return (
    <div className="admin">
      {/* Header */}
      <header className="admin-app-header">
        <nav className="admin-header-nav">
          <div className="admin-logo">
            <picture>
              <source srcSet="/Jiphyeonjeon_llama.webp" type="image/webp" />
              <img src="/Jiphyeonjeon_llama.png" alt="Jiphyeonjeon" className="admin-logo-icon" width={128} height={128} loading="eager" fetchPriority="high" />
            </picture>
            <span className="admin-brand-name">Admin</span>
          </div>
          <div className="admin-header-actions">
            <button className="admin-nav-btn" onClick={() => navigate('/')}>
              Home
            </button>
            <button className="admin-nav-btn" onClick={() => navigate('/mypage')}>
              My Page
            </button>
          </div>
        </nav>
      </header>

      {/* Content */}
      <div className="admin-content">
        {/* Tabs */}
        <div className="admin-tabs">
          {(Object.keys(TAB_LABELS) as Tab[]).map((tab) => (
            <button
              key={tab}
              className={`admin-tab ${activeTab === tab ? 'admin-tab--active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {TAB_LABELS[tab]}
            </button>
          ))}
        </div>

        {activeTab === 'overview' && (
          <Suspense fallback={<div className="admin-loading">개요 로딩 중...</div>}>
            <AdminOverviewTab days={days} onDays={setDays} />
          </Suspense>
        )}
        {activeTab === 'conversations' && (
          <Suspense fallback={<div className="admin-loading">대화 로딩 중...</div>}>
            <AdminConversationsTab days={days} onDays={setDays} />
          </Suspense>
        )}
        {activeTab === 'growth' && (
          <Suspense fallback={<div className="admin-loading">성장 로딩 중...</div>}>
            <AdminVisitsReport days={days} onDays={setDays} />
          </Suspense>
        )}
        {activeTab === 'content' && (
          <Suspense fallback={<div className="admin-loading">콘텐츠 로딩 중...</div>}>
            <AdminContentTab />
          </Suspense>
        )}
        {activeTab === 'system' && (
          <Suspense fallback={<div className="admin-loading">시스템 로딩 중...</div>}>
            <AdminSystemTab days={days} onDays={setDays} />
          </Suspense>
        )}

        {/* Members: accounts and current assistant activity. */}
        {activeTab === 'members' && (
          <Suspense fallback={<div className="admin-loading">회원 정보를 불러오는 중...</div>}>
            <AdminMembersReport
              days={days}
              users={users}
              loading={usersLoading}
              currentUsername={currentUsername}
              onToggleRole={handleToggleRole}
              onDeleteUser={handleDeleteUser}
            />
          </Suspense>
        )}

      </div>

      {/* Transient notice (success / warn / error) */}
      {notice && (
        <div
          className={`admin-notice admin-notice--${notice.kind}`}
          role={notice.kind === 'error' ? 'alert' : 'status'}
          onClick={() => setNotice(null)}
        >
          {notice.text}
          <button
            className="admin-notice-close"
            onClick={(e) => {
              e.stopPropagation();
              setNotice(null);
            }}
            aria-label="알림 닫기"
          >
            ×
          </button>
        </div>
      )}

      {/* Confirm Dialog */}
      {confirm && (
        <div className="admin-confirm-overlay" onClick={closeConfirm}>
          <div
            ref={confirmDialogRef}
            className="admin-confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-confirm-title"
            tabIndex={-1}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="admin-confirm-title" id="admin-confirm-title">{confirm.title}</h3>
            <p className="admin-confirm-message">{confirm.message}</p>
            <div className="admin-confirm-actions">
              <button className="admin-confirm-cancel" onClick={closeConfirm}>
                취소
              </button>
              <button
                className="admin-confirm-delete"
                onClick={async () => {
                  if (confirmBusy.current) return;
                  confirmBusy.current = true;
                  try {
                    await confirm.onConfirm();
                  } finally {
                    confirmBusy.current = false;
                  }
                }}
              >
                삭제
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
