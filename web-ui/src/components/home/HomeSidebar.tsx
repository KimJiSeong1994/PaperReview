import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { fetchMyConversations } from '../../api/conversations';
import { fetchCurricula } from '../../api/curriculum';
import { fetchMyReviewSessions, type ReviewSessionSummary } from '../../api/me';
import type { ConversationSummary } from '../../types';
import type { CurriculumSummary } from '../curriculum/types';
import { Icon, Row, type IconName } from './HomeRow';
import { groupOf, HISTORY_GROUPS, relativeLabel, type HistoryGroup } from './homeTime';
import { readRecentSearches } from './recentSearches';
import { userInitials } from './userInitials';

interface HomeSidebarProps {
  /** "새 대화": the home resets its composer, other pages go home. */
  onNew: () => void;
  /** Runs a remembered search again (fallback rows, before any conversation exists). */
  onAsk: (query: string) => void;
  /** Conversation shown beside the sidebar, highlighted in the list. */
  activeConversationId?: string;
  /** Latest title of that conversation (the first answer renames it), shown without a refetch. */
  activeConversationTitle?: string;
  /** The home already fetches these; given here, the sidebar skips its own request. */
  reviewSessions?: ReviewSessionSummary[];
}

interface HistoryItem {
  key: string;
  kind: '대화' | '검색' | '리뷰';
  label: string;
  at: string;
  status?: string;
  /** Raw review status, used only to tone the chip. */
  statusKey?: string;
  to?: string;
  onClick?: () => void;
}

const REVIEW_STATUS_LABEL: Record<string, string> = {
  analyzing: '진행 중',
  processing: '진행 중',
  completed: '완료',
  failed: '실패',
};
const reviewStatusKey = (status: string): string => (status === 'analyzing' ? 'processing' : status);
const KIND_ICON: Record<HistoryItem['kind'], IconName> = { 대화: 'chat', 검색: 'search', 리뷰: 'review' };

function readUsername(): string {
  try {
    return localStorage.getItem('username') || '내 계정';
  } catch {
    return '내 계정';
  }
}

/**
 * History sidebar shared by the home and the conversation page: conversations
 * (or this device's recent searches before the first one), deep reviews,
 * curricula and the account. Below 860px it is a drawer behind 기록 열기.
 */
function HomeSidebar({
  onNew,
  onAsk,
  activeConversationId,
  activeConversationTitle,
  reviewSessions: givenSessions,
}: HomeSidebarProps) {
  const { isAuthenticated, userRole, setShowLoginModal, logout } = useAuth();
  const username = readUsername();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [fetchedSessions, setFetchedSessions] = useState<ReviewSessionSummary[]>([]);
  const reviewSessions = givenSessions ?? fetchedSessions;
  const fetchSessions = givenSessions === undefined;
  const [curricula, setCurricula] = useState<CurriculumSummary[]>([]);
  const [recentSearches] = useState(readRecentSearches);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const newButtonRef = useRef<HTMLButtonElement | null>(null);
  const now = useMemo(() => new Date(), []);

  useEffect(() => {
    if (!isAuthenticated) return undefined;
    const controller = new AbortController();
    fetchMyConversations(20, controller.signal)
      .then(list => { if (!controller.signal.aborted) setConversations(list); })
      .catch(() => { /* recent searches stand in */ });
    if (fetchSessions) {
      fetchMyReviewSessions(5, controller.signal)
        .then(response => { if (!controller.signal.aborted) setFetchedSessions(response.sessions ?? []); })
        .catch(() => { /* empty state */ });
    }
    fetchCurricula()
      // Preset courses belong to everyone; the sidebar lists only the user's own.
      .then(response => { if (!controller.signal.aborted) setCurricula((response.curricula ?? []).filter(course => !course.is_preset)); })
      .catch(() => { /* empty state */ });
    return () => controller.abort();
  }, [isAuthenticated, fetchSessions]);

  const closeDrawer = () => {
    setDrawerOpen(false);
    menuButtonRef.current?.focus();
  };

  useEffect(() => {
    if (!drawerOpen) return undefined;
    newButtonRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setDrawerOpen(false);
        menuButtonRef.current?.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [drawerOpen]);

  const grouped = useMemo(() => {
    const threads: HistoryItem[] = conversations.length > 0
      ? conversations.map(item => ({
        key: `conversation:${item.id}`,
        kind: '대화',
        label: (item.id === activeConversationId && activeConversationTitle) || item.title,
        at: item.updated_at,
        to: `/c/${item.id}`,
      }))
      : recentSearches.map(item => ({
        key: `search:${item.query}`,
        kind: '검색',
        label: item.query,
        at: item.at,
        onClick: () => onAsk(item.query),
      }));
    const reviews: HistoryItem[] = reviewSessions.map(session => ({
      key: `review:${session.session_id}`,
      kind: '리뷰',
      label: session.title ? `${session.title} 딥리뷰` : `딥리뷰 ${session.num_papers}편`,
      at: session.created_at,
      status: REVIEW_STATUS_LABEL[session.status] ?? session.status,
      statusKey: reviewStatusKey(session.status),
      to: '/mypage',
    }));
    const items = [...threads, ...reviews].sort((left, right) => (
      new Date(right.at).getTime() - new Date(left.at).getTime()
    ));
    const groups = new Map<HistoryGroup, HistoryItem[]>(HISTORY_GROUPS.map(group => [group, []]));
    items.forEach(item => groups.get(groupOf(item.at, now))!.push(item));
    return HISTORY_GROUPS.map(group => [group, groups.get(group)!] as const).filter(([, list]) => list.length > 0);
  }, [activeConversationId, activeConversationTitle, conversations, now, onAsk, recentSearches, reviewSessions]);

  return (
    <>
      <button
        type="button"
        className="home-menu-btn"
        ref={menuButtonRef}
        aria-label="기록 열기"
        aria-expanded={drawerOpen}
        aria-controls="home-sidebar"
        onClick={() => (drawerOpen ? closeDrawer() : setDrawerOpen(true))}
      >
        <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16">
          <path d="M2.5 4h11M2.5 8h11M2.5 12h7" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
        <span className="home-menu-label" aria-hidden="true">기록</span>
      </button>
      <div className="home-scrim" hidden={!drawerOpen} onClick={closeDrawer} />

      <nav className={`home-sidebar${drawerOpen ? ' is-open' : ''}`} id="home-sidebar" aria-label="내 기록">
        <button
          type="button"
          className="home-btn home-btn-outline"
          ref={newButtonRef}
          onClick={() => { setDrawerOpen(false); onNew(); }}
        >
          <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14">
            <path d="M8 3v10M3 8h10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          새 대화
        </button>

        {/* History scrolls between the fixed 새 대화 button and the pinned account footer. */}
        <div className="home-sidebar-scroll">
          {isAuthenticated && grouped.length === 0 && (
            <p className="home-empty">아직 기록이 없어요. 첫 질문이 여기에 쌓입니다. <kbd>/</kbd> 키로 입력창에 바로 갈 수 있어요.</p>
          )}
          {isAuthenticated && grouped.map(([group, items]) => (
            <section key={group}>
              <h4 className="home-label">{group} · {items.length}</h4>
              <ul className="home-list">
                {items.map(item => (
                  <Row
                    key={item.key}
                    lead={<Icon name={KIND_ICON[item.kind]} />}
                    label={item.label}
                    meta={`${item.kind} · ${relativeLabel(item.at, now)}`}
                    chip={item.status && <span className={`home-chip is-${item.statusKey}`}>{item.status}</span>}
                    to={item.to}
                    onClick={() => { setDrawerOpen(false); item.onClick?.(); }}
                    arrow={false}
                    current={item.key === `conversation:${activeConversationId}`}
                  />
                ))}
              </ul>
            </section>
          ))}
          {isAuthenticated && curricula.length > 0 && (
            <section>
              <h4 className="home-label">커리큘럼 · {curricula.length}</h4>
              <ul className="home-list">
                {curricula.slice(0, 4).map(course => (
                  <Row
                    key={course.id}
                    lead={<Icon name="course" />}
                    label={course.name}
                    meta={`커리큘럼 · ${course.total_papers}편`}
                    to="/curriculum"
                    onClick={() => setDrawerOpen(false)}
                    arrow={false}
                  />
                ))}
              </ul>
            </section>
          )}
        </div>

        {isAuthenticated ? (
          <div className="home-account">
            <div className="home-account-card">
              <span className="home-account-avatar" aria-hidden="true">{userInitials(username)}</span>
              <span className="home-account-text">
                <span className="home-account-name">{username}</span>
                <span className="home-account-role">{userRole === 'admin' ? '관리자' : '연구자'}</span>
              </span>
            </div>
            <div className="home-account-actions">
              <Link to="/mypage">
                <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14">
                  <path d="M8 5.75a2.25 2.25 0 1 0 0 4.5 2.25 2.25 0 0 0 0-4.5zM8 1.75v1.5M8 12.75v1.5M1.75 8h1.5M12.75 8h1.5M3.6 3.6l1.05 1.05M11.35 11.35l1.05 1.05M3.6 12.4l1.05-1.05M11.35 4.65l1.05-1.05" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                </svg>
                설정
              </Link>
              <button type="button" onClick={logout}>
                <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14">
                  <path d="M6.5 2.75H3.75v10.5H6.5M10.5 5.25 13.25 8l-2.75 2.75M13 8H6.25" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                로그아웃
              </button>
            </div>
          </div>
        ) : (
          <div className="home-signin">
            <p>로그인하면 대화가 저장돼요</p>
            <button type="button" className="home-btn" onClick={() => setShowLoginModal(true)}>로그인</button>
          </div>
        )}
      </nav>
    </>
  );
}

export default HomeSidebar;
