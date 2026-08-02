import { lazy, Suspense } from 'react';
import { Link, Routes, Route, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom';
import './App.css';
import LoginModal from './components/LoginPage';
import AnalyticsConsentBanner from './components/AnalyticsConsentBanner';
import RecommendationBell from './components/RecommendationBell';
import SEOHead from './components/SEOHead';
import SiteFooter from './components/SiteFooter';
import ThemeToggle from './components/ThemeToggle';
import { useAuth } from './contexts/AuthContext';
import { INTRODUCE_KO_URL, INTRODUCE_URL, OG_DEFAULT_IMAGE, introduceGraph } from './seo/structuredData';

const MyPage = lazy(() => import('./components/MyPage'));
const AdminPage = lazy(() => import('./components/AdminPage'));
const SharedView = lazy(() => import('./components/SharedView'));
const SharedCurriculumView = lazy(() => import('./components/SharedCurriculumView'));
const BlogPage = lazy(() => import('./components/BlogPage'));
const SearchPage = lazy(() => import('./components/SearchPage'));
const PaperViewerRoute = lazy(() => import('./components/PaperViewerRoute'));
const SeriesPage = lazy(() => import('./components/SeriesPage'));
const IntroducePage = lazy(() => import('./components/IntroducePage'));

const HOME_TITLE = 'AI 논문 검색·리뷰 도구 | 집현전';
const HOME_DESCRIPTION = '집현전은 여러 학술 소스의 AI 논문 검색, 다중 논문 비교·딥리뷰, 원문 근거 검증, 인용 그래프와 다음 읽기를 한곳에서 잇는 연구 도구입니다.';
const INTRODUCE_TITLE = 'AI Paper Search & Review | About Jiphyeonjeon';
const INTRODUCE_DESCRIPTION = 'Jiphyeonjeon searches across scholarly sources, compares papers in an AI deep review, and checks important claims against source passages before guiding the next read.';
const INTRODUCE_KO_TITLE = 'AI 논문 검색·리뷰 도구 | 집현전 소개';
const INTRODUCE_KO_DESCRIPTION = '집현전은 여러 학술 소스에서 논문을 검색하고, 여러 논문을 AI로 비교·리뷰한 뒤 핵심 주장을 원문 근거와 대조하는 연구 도구입니다.';
const SITE_URL = 'https://jiphyeonjeon.kr';
const INTRODUCE_JSON_LD = introduceGraph();
const INTRODUCE_KO_JSON_LD = introduceGraph('ko');
const INTRODUCE_ALTERNATES = { en: INTRODUCE_URL, ko: INTRODUCE_KO_URL, 'x-default': INTRODUCE_URL };
const INDEX_ROBOTS = 'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1';

function BlogPostRoute({ isAdmin }: { isAdmin: boolean }) {
  const { slug } = useParams<{ slug: string }>();
  return <BlogPage isAdmin={isAdmin} slug={slug} />;
}

function BlogSeriesRoute() {
  const { seriesId } = useParams<{ seriesId: string }>();
  return <SeriesPage seriesId={seriesId ?? ''} />;
}

function BlogCategoryRoute({ isAdmin }: { isAdmin: boolean }) {
  const { category } = useParams<{ category: string }>();
  if (category !== 'paper-review' && category !== 'engineering') {
    return <Navigate to="/blog" replace />;
  }
  return <BlogPage isAdmin={isAdmin} initialCategory={category} />;
}

function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, userRole, showLoginModal, setShowLoginModal, login, logout } = useAuth();
  const isKoreanIntroduce = location.pathname.startsWith('/ko/introduce');
  const isIntroduceRoute = isKoreanIntroduce || location.pathname.startsWith('/introduce');

  const handleMyPageClick = () => {
    if (isAuthenticated) {
      navigate('/mypage');
    } else {
      setShowLoginModal(true);
    }
  };

  // Shared by the root route and /introduce. The other routes ship their own
  // headers (BlogPage, AdminPage, ...), so this stays a plain element rather
  // than a component — no remount of RecommendationBell on App re-render.
  const header = (
    <div className="app-header">
      <div className="header-nav">
        <a
          className="logo"
          href="/"
          onClick={(e) => {
            e.preventDefault();
            navigate('/');
          }}
          style={{ cursor: 'pointer', textDecoration: 'none' }}
        >
          <picture>
            <source srcSet="/Jiphyeonjeon_llama.webp" type="image/webp" />
            <img
              src="/Jiphyeonjeon_llama.png"
              alt="Jiphyeonjeon"
              className="logo-icon"
              width={128}
              height={128}
              loading="eager"
              fetchPriority="high"
              onError={(e) => {
                e.currentTarget.style.display = 'none';
              }}
            />
          </picture>
          <span className="brand-name">Jiphyeonjeon</span>
        </a>
        <div className="header-right">
        <nav className="header-actions" aria-label={isKoreanIntroduce ? '주요 메뉴' : 'Main navigation'}>
          {isAuthenticated && <RecommendationBell />}
          {isAuthenticated && userRole === 'admin' && (
            <button className="nav-btn" onClick={() => navigate('/admin')}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px', verticalAlign: 'middle' }}>
                <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path>
                <circle cx="12" cy="12" r="3"></circle>
              </svg>
              Admin
            </button>
          )}
          <Link className="nav-btn" to={isKoreanIntroduce ? '/ko/introduce/' : '/introduce/'}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px', verticalAlign: 'middle' }}>
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="16" x2="12" y2="12"></line>
              <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
            {isKoreanIntroduce ? '소개' : 'About'}
          </Link>
          <Link className="nav-btn" to="/blog">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px', verticalAlign: 'middle' }}>
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
              <polyline points="10 9 9 9 8 9"></polyline>
            </svg>
            {isKoreanIntroduce ? '블로그' : 'Blog'}
          </Link>
          <button className="nav-btn" onClick={handleMyPageClick}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px', verticalAlign: 'middle' }}>
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
              <circle cx="12" cy="7" r="4"></circle>
            </svg>
            {isKoreanIntroduce ? '마이페이지' : 'My Page'}
          </button>
          {isAuthenticated && (
            <button className="nav-btn" onClick={logout}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px', verticalAlign: 'middle' }}>
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                <polyline points="16 17 21 12 16 7"></polyline>
                <line x1="21" y1="12" x2="9" y2="12"></line>
              </svg>
              {isKoreanIntroduce ? '로그아웃' : 'Logout'}
            </button>
          )}
        </nav>
        <div className="header-utilities" role="group" aria-label={isKoreanIntroduce ? '화면 설정' : 'Display settings'}>
          {isIntroduceRoute && (
            <Link
              className="language-switch"
              to={isKoreanIntroduce ? '/introduce/' : '/ko/introduce/'}
              lang={isKoreanIntroduce ? 'en' : 'ko'}
              hrefLang={isKoreanIntroduce ? 'en' : 'ko'}
              aria-label={isKoreanIntroduce ? 'View this page in English' : '이 페이지를 한국어로 보기'}
            >
              {isKoreanIntroduce ? 'EN' : '한국어'}
            </Link>
          )}
          <ThemeToggle />
        </div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="app">
      <AnalyticsConsentBanner />
      {/* Global login modal overlay */}
      {showLoginModal && !isAuthenticated && (
        <LoginModal
          onLoginSuccess={login}
          onClose={() => setShowLoginModal(false)}
        />
      )}

      <Routes>
        <Route
          path="/share/:token"
          element={
            <Suspense fallback={<div className="app-loading">Loading...</div>}>
              <SharedView />
            </Suspense>
          }
        />
        <Route
          path="/share/curriculum/:token"
          element={
            <Suspense fallback={<div className="app-loading">Loading...</div>}>
              <SharedCurriculumView />
            </Suspense>
          }
        />
        <Route
          path="/mypage"
          element={
            isAuthenticated ? (
              <Suspense fallback={<div className="app-loading">Loading...</div>}>
                <MyPage onBack={() => navigate('/')} />
              </Suspense>
            ) : (
              <Navigate to="/" />
            )
          }
        />
        <Route
          path="/paper-viewer"
          element={
            <Suspense fallback={<div className="app-loading">Loading...</div>}>
              <PaperViewerRoute />
            </Suspense>
          }
        />
        <Route
          path="/admin"
          element={
            isAuthenticated && userRole === 'admin' ? (
              <Suspense fallback={<div className="app-loading">Loading...</div>}>
                <AdminPage />
              </Suspense>
            ) : (
              <Navigate to="/" />
            )
          }
        />
        <Route
          path="/blog"
          element={
            <Suspense fallback={<div className="app-loading">Loading...</div>}>
              <BlogPage isAdmin={userRole === 'admin'} />
            </Suspense>
          }
        />
        <Route
          path="/blog/category/:category"
          element={
            <Suspense fallback={<div className="app-loading">Loading...</div>}>
              <BlogCategoryRoute isAdmin={userRole === 'admin'} />
            </Suspense>
          }
        />
        <Route
          path="/blog/series/:seriesId"
          element={
            <Suspense fallback={<div className="app-loading">Loading...</div>}>
              <BlogSeriesRoute />
            </Suspense>
          }
        />
        <Route
          path="/blog/:slug"
          element={
            <Suspense fallback={<div className="app-loading">Loading...</div>}>
              <BlogPostRoute isAdmin={userRole === 'admin'} />
            </Suspense>
          }
        />
        <Route
          path="/introduce"
          element={
            <>
              <SEOHead
                title={INTRODUCE_TITLE}
                description={INTRODUCE_DESCRIPTION}
                canonical={INTRODUCE_URL}
                locale="en_US"
                image={OG_DEFAULT_IMAGE}
                robots={INDEX_ROBOTS}
                jsonLd={INTRODUCE_JSON_LD}
                alternates={INTRODUCE_ALTERNATES}
              />
              {header}
              <Suspense fallback={<div className="app-loading">Loading...</div>}>
                <IntroducePage locale="en" />
              </Suspense>
            </>
          }
        />
        <Route
          path="/ko/introduce"
          element={
            <>
              <SEOHead
                title={INTRODUCE_KO_TITLE}
                description={INTRODUCE_KO_DESCRIPTION}
                canonical={INTRODUCE_KO_URL}
                locale="ko_KR"
                image={OG_DEFAULT_IMAGE}
                robots={INDEX_ROBOTS}
                jsonLd={INTRODUCE_KO_JSON_LD}
                alternates={INTRODUCE_ALTERNATES}
              />
              {header}
              <Suspense fallback={<div className="app-loading">불러오는 중...</div>}>
                <IntroducePage locale="ko" />
              </Suspense>
            </>
          }
        />
        <Route
          path="*"
          element={
            <>
              {/* No jsonLd here: web-ui/index.html already ships the identical
                  home @graph statically, and SEOHead does not remove it. Passing
                  it again emitted a second, byte-identical graph after hydration
                  — the same @id nodes twice. The static copy is the one to keep;
                  it is the only one non-JS crawlers ever see. */}
              <SEOHead
                title={HOME_TITLE}
                description={HOME_DESCRIPTION}
                canonical={`${SITE_URL}/`}
                locale="ko_KR"
                robots={INDEX_ROBOTS}
              />
              {header}
              <Suspense fallback={<div className="app-loading">Loading...</div>}>
                <SearchPage />
              </Suspense>
            </>
          }
        />
      </Routes>
      <SiteFooter />
    </div>
  );
}

export default App;
