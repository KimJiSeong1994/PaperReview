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
  processing: '진행 중',
  completed: '완료',
  failed: '실패',
};

const initialsOf = (name: string): string => name.trim().slice(0, 2).toUpperCase() || '나';

function readUsername(): string {
  try {
    return localStorage.getItem('username') || '내 계정';
  } catch {
    return '내 계정';
  }
}

function Row({ label, meta, to, onClick, external }: {
  label: ReactNode;
  meta?: ReactNode;
  to?: string;
  onClick?: () => void;
  external?: boolean;
}) {
  const body = (
    <>
      <span className="home-row-text">
        {label}
        {meta && <span className="home-row-meta">{meta}</span>}
      </span>
      <svg className="home-row-arrow" aria-hidden="true" viewBox="0 0 16 16" width="16" height="16">
        <path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </>
  );
  if (to && external) {
    return <li><a className="home-row" href={to} target="_blank" rel="noopener noreferrer">{body}</a></li>;
  }
  if (to) return <li><Link className="home-row" to={to}>{body}</Link></li>;
  return <li><button type="button" className="home-row" onClick={onClick}>{body}</button></li>;
}

/**
 * The home as a research workspace: history sidebar, one question over a
 * composer, task and continue rows, and a rail of today's picks.
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
    // closeDrawer only touches refs and a setter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      statusKey: session.status,
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
  const recommendationItems = data.recommendations?.items?.slice(0, 3) ?? [];
  const degradedReason = data.recommendations?.degraded_reasons?.[0] ?? null;
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
        <button type="button" className="home-new-search" ref={newSearchRef} onClick={startNewSearch}>
          <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14">
            <path d="M8 3v10M3 8h10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          새 검색
        </button>

        {isAuthenticated ? (
          <>
            {grouped.length === 0 && (
              <div className="home-sidebar-empty">
                <p className="home-empty">아직 기록이 없어요. 첫 검색이 여기에 쌓입니다.</p>
                <p className="home-empty-hint"><kbd>/</kbd> 키로 검색창에 바로 갈 수 있어요.</p>
              </div>
            )}
            {grouped.map(([group, items]) => (
              <div className="home-history" key={group}>
                <h4>{group}</h4>
                <ul>
                  {items.map(item => (
                    <li key={item.key}>
                      {item.to ? (
                        <Link to={item.to} onClick={() => setDrawerOpen(false)}>
                          <span className="home-history-kind" aria-hidden="true">{item.kind}</span>
                          <span className="home-history-label">{item.label}</span>
                          {item.status && <span className={`home-history-status is-${item.statusKey}`}>{item.status}</span>}
                        </Link>
                      ) : (
                        <button type="button" onClick={() => { setDrawerOpen(false); item.onClick?.(); }}>
                          <span className="home-history-kind" aria-hidden="true">{item.kind}</span>
                          <span className="home-history-label">{item.label}</span>
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            {data.curricula.length > 0 && (
              <div className="home-history">
                <h4>커리큘럼</h4>
                <ul>
                  {data.curricula.slice(0, 4).map(course => (
                    <li key={course.id}>
                      <Link to="/curriculum" onClick={() => setDrawerOpen(false)}>
                        <span className="home-history-kind" aria-hidden="true">과정</span>
                        <span className="home-history-label">{course.name}</span>
                        <span className="home-history-status">{course.total_papers}편</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="home-account">
              <div className="home-avatar" aria-hidden="true">{initialsOf(username)}</div>
              <div className="home-account-name">{username}</div>
              <div className="home-account-links">
                <Link to="/mypage">마이페이지</Link>
                <button type="button" onClick={logout}>로그아웃</button>
              </div>
            </div>
          </>
        ) : (
          <div className="home-signin">
            <p>로그인하면 논문 검색과 딥리뷰·커리큘럼을 이용하고, 그 기록을 여기서 이어서 볼 수 있어요.</p>
            <button type="button" className="home-btn" onClick={() => setShowLoginModal(true)}>로그인</button>
            <Link className="home-signin-link" to="/blog/category/paper-review">공개 리뷰 먼저 읽어보기 →</Link>
          </div>
        )}
      </nav>

      <section className="home-main" aria-labelledby="home-title">
        <div className="home-main-inner">
          <div>
            <p className="home-eyebrow">{eyebrow}</p>
            <h1 id="home-title" className="home-title">오늘은 어떤 논문부터 볼까요?</h1>
            <p className="home-lead">주제나 논문 제목을 적으면 여러 소스에서 찾아 중복을 걷어내고, 근거까지 읽어 드려요.</p>
          </div>

          <div className="home-ask">
            <HomeComposer
              key={`${attemptedQuery}#${resetKey}`}
              initialQuery={attemptedQuery}
              onSearch={onSearch}
              guidanceMessage={guidanceMessage}
              guidanceSticky={guidanceSticky}
              onQueryChange={onQueryChange}
              autoFocus={resetKey > 0}
            />
            {!isAuthenticated && (
              <p className="home-note">검색은 로그인 후 이용할 수 있어요. 공개 리뷰는 바로 읽을 수 있습니다.</p>
            )}
          </div>

          <section className="home-rows" aria-labelledby="home-tasks">
            <h2 id="home-tasks">집현전에 이런 걸 맡겨 보세요</h2>
            <ul>
              <Row
                label="GraphRAG와 기존 RAG, 무엇이 달라졌는지 비교 리뷰"
                meta="비교 질문도 검색어로 바로 던질 수 있어요"
                onClick={() => onSearch('GraphRAG와 기존 RAG 비교')}
              />
              {isAuthenticated ? (
                <Row
                  label={data.bookmarks.length > 0
                    ? `북마크 ${data.bookmarks.length}편 중에서 골라 딥리뷰 만들기`
                    : '검색 결과에서 논문을 골라 딥리뷰 만들기'}
                  meta="근거 검증 · 포스터 생성까지 한 번에"
                  to="/mypage"
                />
              ) : (
                <Row
                  label="논문을 골라 딥리뷰 만들기"
                  meta="로그인 후 검색 결과에서 선택합니다"
                  onClick={() => setShowLoginModal(true)}
                />
              )}
              <Row
                label="주제 입문 커리큘럼 짜기"
                meta="읽을 순서와 주차별 핵심 논문을 정합니다"
                to="/curriculum"
              />
            </ul>
          </section>

          {isAuthenticated ? (
            <section className="home-rows" aria-labelledby="home-continue">
              <h2 id="home-continue">이어서 하기</h2>
              {lastSearch || latestReview || data.bookmarks.length > 0 ? (
                <ul>
                  {lastSearch && (
                    <Row
                      label={<>{relativeLabel(lastSearch.at, now)} 검색 <em>{lastSearch.query}</em> 결과 다시 보기</>}
                      meta="같은 검색어로 다시 찾습니다"
                      onClick={() => onSearch(lastSearch.query)}
                    />
                  )}
                  {latestReview && (
                    <Row
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
            <section className="home-rows" aria-labelledby="home-public">
              <h2 id="home-public">공개 리뷰 읽어보기</h2>
              <ul>
                {data.posts.map(post => (
                  <Row key={post.slug} label={post.title} meta="논문 리뷰 · 쉬운 읽기 / 상세 읽기" to={`/blog/${post.slug}`} />
                ))}
                <Row
                  label="집현전 사용법 자세히 보기"
                  meta="검색 → 리뷰 → 검증 → 학습 흐름"
                  to="/ko/introduce/"
                />
              </ul>
            </section>
          )}

          <p className="home-disclaimer">AI 리뷰도 틀릴 수 있어요. 중요한 주장은 원문 근거를 한 번 더 확인해 주세요.</p>
        </div>
      </section>

      <aside className="home-rail" aria-label="오늘의 추천">
        <section>
          <h3>오늘의 추천 논문</h3>
          {isAuthenticated ? (
            <>
              {latestRunLabel && <p className="home-fresh">{latestRunLabel}</p>}
              {recommendationItems.length > 0 && (
                <ul className="home-picks">
                  {recommendationItems.map(item => (
                    <li key={item.canonical_key}>
                      <a href={item.url || item.pdf_url || '#'} target="_blank" rel="noopener noreferrer">
                        <span className="home-pick-title">{item.title}</span>
                        {item.reason && <span className="home-pick-why">{item.reason}</span>}
                        <span className="home-pick-venue">
                          {[item.year, item.venue ?? item.candidate_sources?.[0]].filter(Boolean).join(' · ')}
                        </span>
                      </a>
                    </li>
                  ))}
                </ul>
              )}
              {data.recommendations && recommendationItems.length === 0 && !degradedReason && (
                <p className="home-rail-note">논문을 3편만 북마크하면 다음 날부터 관심 주제에 맞는 추천이 여기에 와요.</p>
              )}
              {(data.recommendations?.total_count ?? 0) > recommendationItems.length && (
                <p className="home-rail-note">전체 {data.recommendations?.total_count}편은 상단 종 아이콘에서 볼 수 있어요.</p>
              )}
              {(data.recommendationsFailed || degradedReason) && (
                <div className="home-degraded">
                  <span>{data.recommendationsFailed ? '추천을 불러오지 못했어요.' : degradedReason}</span>
                  <button type="button" onClick={data.reloadRecommendations}>다시 불러오기</button>
                </div>
              )}
            </>
          ) : (
            <p className="home-rail-note">로그인하고 논문을 3편만 북마크하면 다음 날부터 관심 주제에 맞는 추천이 여기에 와요.</p>
          )}
        </section>

        {data.posts.length > 0 && (
          <section>
            <h3>공개 리뷰 최신</h3>
            <ul className="home-picks">
              {data.posts.map(post => (
                <li key={post.slug}>
                  <Link to={`/blog/${post.slug}`}>
                    <span className="home-pick-title">{post.title}</span>
                    <span className="home-pick-venue">논문 리뷰</span>
                  </Link>
                </li>
              ))}
            </ul>
            <Link className="home-more" to="/blog">블로그 전체 보기 →</Link>
          </section>
        )}
      </aside>
    </div>
  );
}

export default HomeWorkspace;
