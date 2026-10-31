import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import './HomeWorkspace.css';
import { useAuth } from '../../contexts/AuthContext';
import HomeComposer from './HomeComposer';
import { Icon, Row } from './HomeRow';
import HomeSidebar from './HomeSidebar';
import { relativeLabel } from './homeTime';
import { readRecentSearches } from './recentSearches';
import { useHomeData } from './useHomeData';

interface HomeWorkspaceProps {
  attemptedQuery: string;
  onSearch: (query: string) => void;
  guidanceMessage: string | null;
  guidanceSticky: boolean;
  onQueryChange: () => void;
}

const REVIEW_STATUS_LABEL: Record<string, string> = {
  analyzing: '진행 중',
  processing: '진행 중',
  completed: '완료',
  failed: '실패',
};

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
  const { isAuthenticated, setShowLoginModal } = useAuth();
  const data = useHomeData(isAuthenticated);
  const [recentSearches] = useState(readRecentSearches);
  const [resetKey, setResetKey] = useState(0);
  const now = useMemo(() => new Date(), []);

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

  const startNewSearch = () => setResetKey(key => key + 1);

  return (
    <div className="home-shell">
      <HomeSidebar onNew={startNewSearch} onAsk={onSearch} reviewSessions={data.reviewSessions} />

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
