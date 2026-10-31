import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import './HomeWorkspace.css';
import { useAuth } from '../../contexts/AuthContext';
import HomeComposer from './HomeComposer';
import { groupOf, HISTORY_GROUPS, relativeLabel, type HistoryGroup } from './homeTime';
import { readRecentSearches } from './recentSearches';
import { useHomeData } from './useHomeData';

interface HomeWorkspaceProps {
  attemptedQuery: string;
  onSearch: (query: string) => void;
  guidanceMessage: string | null;
  guidanceSticky: boolean;
  onQueryChange: () => void;
}

interface HistoryItem {
  key: string;
  kind: '검색' | '리뷰';
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

// Backend diagnostic codes for a thinner recommendation run, in the reader's words.
const DEGRADED_REASON_LABEL: Record<string, string> = {
  delivery_stale: '오늘 추천이 아직 갱신되지 않아 이전 목록을 보여드려요.',
  delivery_expired: '추천이 오래돼 새로 받아와야 해요.',
  no_eligible_candidates: '아직 추천할 만한 새 논문이 모이지 않았어요.',
  source_error: '일부 출처가 응답하지 않아 추천이 줄었어요.',
  limited_coverage: '오늘은 후보 범위가 좁아 추천이 적어요.',
  ranker_error: '추천 점수 계산에 문제가 있어 일부만 보여드려요.',
};
const describeDegradedReason = (code: string): string => (
  DEGRADED_REASON_LABEL[code] ?? '추천 일부를 불러오지 못했어요.'
);

const MASCOT_SRC = '/Jiphyeonjeon_llama.webp';

// One stroke set for every row's leading slot (16px grid).
const ICON_PATH = {
  compare: 'M3 5.5h9.5M10 3l2.5 2.5L10 8M13 10.5H3.5M6 8l-2.5 2.5L6 13',
  review: 'M4 1.75h5.25L12.5 5v9.25H4zM9 1.75v3.5h3.5M6.25 10l1.25 1.25L10 8.75',
  course: 'M2.5 5.5 8 3l5.5 2.5L8 8zM2.5 8.5 8 11l5.5-2.5M2.5 11.5 8 14l5.5-2.5',
  search: 'M7 2.75a4.25 4.25 0 1 0 0 8.5 4.25 4.25 0 0 0 0-8.5zM10.25 10.25 13.5 13.5',
  clock: 'M8 2.25a5.75 5.75 0 1 0 0 11.5 5.75 5.75 0 0 0 0-11.5zM8 5v3.25l2.25 1.5',
  doc: 'M4 1.75h5.25L12.5 5v9.25H4zM9 1.75v3.5h3.5M6 8.5h4M6 11h4',
  user: 'M8 2.5a2.75 2.75 0 1 0 0 5.5 2.75 2.75 0 0 0 0-5.5zM2.75 13.75c.6-2.4 2.7-3.75 5.25-3.75s4.65 1.35 5.25 3.75',
} as const;
type IconName = keyof typeof ICON_PATH;
const KIND_ICON: Record<string, IconName> = { 검색: 'search', 리뷰: 'review' };

function Icon({ name }: { name: IconName }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" width="18" height="18">
      <path d={ICON_PATH[name]} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function readUsername(): string {
  try {
    return localStorage.getItem('username') || '내 계정';
  } catch {
    return '내 계정';
  }
}

/**
 * The one row anatomy on the home: leading slot, title, meta, optional chip
 * and arrow. Without a target it renders as static text (.home-pick-static).
 */
function Row({ lead, label, meta, chip, to, onClick, external, arrow = true }: {
  lead?: ReactNode;
  label: ReactNode;
  meta?: ReactNode;
  chip?: ReactNode;
  to?: string;
  onClick?: () => void;
  external?: boolean;
  arrow?: boolean;
}) {
  const body = (
    <>
      {lead !== undefined && <span className="home-row-lead" aria-hidden="true">{lead}</span>}
      <span className="home-row-text">
        <span className="home-row-title">{label}</span>
        {meta && <span className="home-row-meta">{meta}</span>}
      </span>
      {chip}
      {arrow && (
        <svg className="home-row-arrow" aria-hidden="true" viewBox="0 0 16 16" width="16" height="16">
          <path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </>
  );
  if (to && external) {
    return <li><a className="home-row" href={to} target="_blank" rel="noopener noreferrer">{body}</a></li>;
  }
  if (to) return <li><Link className="home-row" to={to} onClick={onClick}>{body}</Link></li>;
  if (onClick) return <li><button type="button" className="home-row" onClick={onClick}>{body}</button></li>;
  return <li><span className="home-row home-pick-static">{body}</span></li>;
}

/**
 * The home as a research workspace: history sidebar, one question over a
 * composer with today's picks beside it, then task and continue rows.
 */
function HomeWorkspace({
  attemptedQuery,
  onSearch,
  guidanceMessage,
  guidanceSticky,
  onQueryChange,
}: HomeWorkspaceProps) {
  const { isAuthenticated, setShowLoginModal, logout } = useAuth();
  const data = useHomeData(isAuthenticated);
  const [recentSearches] = useState(readRecentSearches);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [resetKey, setResetKey] = useState(0);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const newSearchRef = useRef<HTMLButtonElement | null>(null);
  const now = useMemo(() => new Date(), []);
  const username = isAuthenticated ? readUsername() : '';

  const closeDrawer = () => {
    setDrawerOpen(false);
    menuButtonRef.current?.focus();
  };

  useEffect(() => {
    if (!drawerOpen) return undefined;
    newSearchRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeDrawer();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [drawerOpen]);

  const historyItems = useMemo<HistoryItem[]>(() => {
    const searches: HistoryItem[] = recentSearches.map(item => ({
      key: `search:${item.query}`,
      kind: '검색',
      label: item.query,
      at: item.at,
      onClick: () => onSearch(item.query),
    }));
    const reviews: HistoryItem[] = data.reviewSessions.map(session => ({
      key: `review:${session.session_id}`,
      kind: '리뷰',
      label: session.title ? `${session.title} 딥리뷰` : `딥리뷰 ${session.num_papers}편`,
      at: session.created_at,
      status: REVIEW_STATUS_LABEL[session.status] ?? session.status,
      statusKey: reviewStatusKey(session.status),
      to: '/mypage',
    }));
    return [...searches, ...reviews].sort((left, right) => (
      new Date(right.at).getTime() - new Date(left.at).getTime()
    ));
  }, [data.reviewSessions, onSearch, recentSearches]);

  const grouped = useMemo(() => {
    const groups = new Map<HistoryGroup, HistoryItem[]>(HISTORY_GROUPS.map(group => [group, []]));
    historyItems.forEach(item => groups.get(groupOf(item.at, now))!.push(item));
    return HISTORY_GROUPS.map(group => [group, groups.get(group)!] as const).filter(([, items]) => items.length > 0);
  }, [historyItems, now]);

  const lastSearch = recentSearches[0] ?? null;
  const latestReview = data.reviewSessions[0] ?? null;
  const eyebrow = !isAuthenticated
    ? <>집현전 · <span>논문을 찾은 뒤, 근거까지 읽습니다.</span></>
    : lastSearch
      ? '집현전 · 지난 검색 이어서'
      : '집현전 · 다시 오셨군요';
  const recommendationItems = data.recommendations?.items?.slice(0, 5) ?? [];
  const degradedCode = data.recommendations?.degraded_reasons?.[0] ?? null;
  const degradedReason = degradedCode ? describeDegradedReason(degradedCode) : null;
  const todayLabel = now.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' });
  const latestRunLabel = data.recommendations?.latest_run_at
    ? `${relativeLabel(data.recommendations.latest_run_at, now)} 갱신`
    : null;

  const startNewSearch = () => {
    setResetKey(key => key + 1);
    setDrawerOpen(false);
  };

  return (
    <div className={`home-shell${drawerOpen ? ' is-drawer-open' : ''}`}>
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

      <nav className="home-sidebar" id="home-sidebar" aria-label="내 기록">
        <button type="button" className="home-btn home-btn-outline" ref={newSearchRef} onClick={startNewSearch}>
          <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14">
            <path d="M8 3v10M3 8h10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          새 검색
        </button>

        {isAuthenticated ? (
          <>
            {grouped.length === 0 && (
              <p className="home-empty">아직 기록이 없어요. 첫 검색이 여기에 쌓입니다. <kbd>/</kbd> 키로 검색창에 바로 갈 수 있어요.</p>
            )}
            {grouped.map(([group, items]) => (
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
                    />
                  ))}
                </ul>
              </section>
            ))}
            {data.curricula.length > 0 && (
              <section>
                <h4 className="home-label">커리큘럼 · {data.curricula.length}</h4>
                <ul className="home-list">
                  {data.curricula.slice(0, 4).map(course => (
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
            <div className="home-account">
              <span className="home-row-lead" aria-hidden="true"><Icon name="user" /></span>
              <span className="home-account-name">{username}</span>
              <Link to="/mypage">마이페이지</Link>
              <button type="button" onClick={logout}>로그아웃</button>
            </div>
          </>
        ) : (
          <div className="home-signin">
            <p>검색은 로그인 후 이용할 수 있어요. 공개 리뷰는 바로 읽을 수 있습니다.</p>
            <button type="button" className="home-btn" onClick={() => setShowLoginModal(true)}>로그인</button>
          </div>
        )}
      </nav>

      <section className="home-main" aria-labelledby="home-title">
        <div className="home-main-inner">
          <div className="home-head">
            <div className="home-hero-top">
              <img className="home-mascot" src={MASCOT_SRC} alt="" width="48" height="48" />
              <p className="home-eyebrow">{eyebrow}</p>
            </div>
            <h1 id="home-title" className="home-title">오늘은 <span className="home-title-accent">어떤 논문</span>부터 볼까요?</h1>
            <p className="home-lead">주제나 논문 제목을 적으면 여러 소스에서 찾아 중복을 걷어내고, 근거까지 읽어 드려요.</p>
          </div>

          <HomeComposer
            key={`${attemptedQuery}#${resetKey}`}
            initialQuery={attemptedQuery}
            onSearch={onSearch}
            guidanceMessage={guidanceMessage}
            guidanceSticky={guidanceSticky}
            onQueryChange={onQueryChange}
            autoFocus={resetKey > 0}
          />

          <section className="home-tasks" aria-labelledby="home-tasks">
            <h2 id="home-tasks" className="home-label">집현전에 이런 걸 맡겨 보세요</h2>
            <ul className="home-list">
              <Row
                lead={<Icon name="compare" />}
                label="GraphRAG와 기존 RAG, 무엇이 달라졌는지 비교 리뷰"
                meta="비교 질문도 검색어로 바로 던질 수 있어요"
                onClick={() => onSearch('GraphRAG와 기존 RAG 비교')}
              />
              {isAuthenticated ? (
                <Row
                  lead={<Icon name="review" />}
                  label={data.bookmarks.length > 0
                    ? `북마크 ${data.bookmarks.length}편 중에서 골라 딥리뷰 만들기`
                    : '검색 결과에서 논문을 골라 딥리뷰 만들기'}
                  meta="근거 검증 · 포스터 생성까지 한 번에"
                  to="/mypage"
                />
              ) : (
                <Row
                  lead={<Icon name="review" />}
                  label="논문을 골라 딥리뷰 만들기"
                  meta="로그인 후 검색 결과에서 선택합니다"
                  onClick={() => setShowLoginModal(true)}
                />
              )}
              <Row
                lead={<Icon name="course" />}
                label="주제 입문 커리큘럼 짜기"
                meta="읽을 순서와 주차별 핵심 논문을 정합니다"
                to="/curriculum"
              />
            </ul>
          </section>

          {isAuthenticated ? (
            <section className="home-continue" aria-labelledby="home-continue">
              <h2 id="home-continue" className="home-label">이어서 하기</h2>
              {lastSearch || latestReview || data.bookmarks.length > 0 ? (
                <ul className="home-list">
                  {lastSearch && (
                    <Row
                      lead={<Icon name="clock" />}
                      label={<>{relativeLabel(lastSearch.at, now)} 검색 <em>{lastSearch.query}</em> 결과 다시 보기</>}
                      meta="같은 검색어로 다시 찾습니다"
                      onClick={() => onSearch(lastSearch.query)}
                    />
                  )}
                  {latestReview && (
                    <Row
                      lead={<Icon name="clock" />}
                      label={`${latestReview.title ? `${latestReview.title} ` : ''}딥리뷰 상태 보기`}
                      meta={[
                        REVIEW_STATUS_LABEL[latestReview.status] ?? latestReview.status,
                        relativeLabel(latestReview.created_at, now),
                        `${latestReview.num_papers}편`,
                      ].filter(Boolean).join(' · ')}
                      to="/mypage"
                    />
                  )}
                  {data.bookmarks.length > 0 && (
                    <Row
                      lead={<Icon name="clock" />}
                      label="지금까지 북마크 정리 보기"
                      meta={`${data.bookmarks.length}편`}
                      to="/mypage"
                    />
                  )}
                </ul>
              ) : (
                <p className="home-empty">아직 기록이 없어요. 첫 검색이 여기에 쌓입니다.</p>
              )}
            </section>
          ) : (
            <section className="home-continue" aria-labelledby="home-public">
              <h2 id="home-public" className="home-label">공개 리뷰 읽어보기</h2>
              <ul className="home-list">
                {data.posts.map(post => (
                  <Row key={post.slug} lead={<Icon name="doc" />} label={post.title} meta="논문 리뷰 · 쉬운 읽기 / 상세 읽기" to={`/blog/${post.slug}`} />
                ))}
                <Row
                  lead={<Icon name="doc" />}
                  label="집현전 사용법 자세히 보기"
                  meta="검색 → 리뷰 → 검증 → 학습 흐름"
                  to="/ko/introduce/"
                />
              </ul>
            </section>
          )}

          <p className="home-disclaimer">AI 리뷰도 틀릴 수 있어요. 중요한 주장은 원문 근거를 한 번 더 확인해 주세요.</p>
          <aside className="home-aside" aria-label="오늘의 추천">
            <section>
              <h3 className="home-label">오늘의 추천 논문 · {todayLabel}</h3>
              {isAuthenticated ? (
                <>
                  {recommendationItems.length > 0 && (
                    <ol className="home-list">
                      {recommendationItems.map((item, index) => (
                        <Row
                          key={item.canonical_key}
                          lead={index + 1}
                          label={item.title}
                          meta={(
                            <>
                              {item.reason && <span className="home-row-why">{item.reason}</span>}
                              {[item.year, item.venue ?? item.candidate_sources?.[0]].filter(Boolean).join(' · ')}
                            </>
                          )}
                          to={item.url || item.pdf_url || undefined}
                          external
                          arrow={false}
                        />
                      ))}
                    </ol>
                  )}
                  {data.recommendations && recommendationItems.length === 0 && !degradedReason && (
                    <p className="home-empty">논문을 3편만 북마크하면 다음 날부터 관심 주제에 맞는 추천이 여기에 와요.</p>
                  )}
                  {((data.recommendations?.total_count ?? 0) > recommendationItems.length || latestRunLabel) && (
                    <p className="home-empty home-aside-note">
                      {[
                        (data.recommendations?.total_count ?? 0) > recommendationItems.length
                          && `오늘 추천 ${data.recommendations?.total_count}편 중 ${recommendationItems.length}편`,
                        latestRunLabel,
                      ].filter(Boolean).join(' · ')}
                    </p>
                  )}
                  {(data.recommendationsFailed || degradedReason) && (
                    <div className="home-degraded">
                      <span>{data.recommendationsFailed ? '추천을 불러오지 못했어요.' : degradedReason}</span>
                      <button type="button" onClick={data.reloadRecommendations}>다시 불러오기</button>
                    </div>
                  )}
                </>
              ) : (
                <p className="home-empty">로그인하고 논문을 3편만 북마크하면 다음 날부터 관심 주제에 맞는 추천이 여기에 와요.</p>
              )}
            </section>

            {isAuthenticated && data.posts.length > 0 && (
              <section>
                <h3 className="home-label">공개 리뷰 최신</h3>
                <ul className="home-list">
                  {data.posts.map(post => (
                    <Row key={post.slug} lead={<Icon name="doc" />} label={post.title} meta="논문 리뷰" to={`/blog/${post.slug}`} arrow={false} />
                  ))}
                </ul>
                <Link className="home-more" to="/blog">블로그 전체 보기 →</Link>
              </section>
            )}
          </aside>
        </div>
      </section>

    </div>
  );
}

export default HomeWorkspace;
