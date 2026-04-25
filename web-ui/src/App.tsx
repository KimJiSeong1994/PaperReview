import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import './App.css';
import LoginModal from './components/LoginPage';
import RecommendationBell from './components/RecommendationBell';
import { useAuth } from './contexts/AuthContext';

const MyPage = lazy(() => import('./components/MyPage'));
const AdminPage = lazy(() => import('./components/AdminPage'));
const SharedView = lazy(() => import('./components/SharedView'));
const SharedCurriculumView = lazy(() => import('./components/SharedCurriculumView'));
const BlogPage = lazy(() => import('./components/BlogPage'));
const SearchPage = lazy(() => import('./components/SearchPage'));

function App() {
  const navigate = useNavigate();
  const { isAuthenticated, userRole, showLoginModal, setShowLoginModal, login, logout } = useAuth();

  const handleMyPageClick = () => {
    if (isAuthenticated) {
      navigate('/mypage');
    } else {
      setShowLoginModal(true);
    }
  };

  return (
    <div className="app">
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
          path="*"
          element={
            <>
              {/* Minimal header */}
              <div className="app-header">
                <div className="header-nav">
                  <div className="logo" onClick={() => navigate('/')} style={{ cursor: 'pointer' }}>
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
                  </div>
                  <div className="header-actions">
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
                    <button className="nav-btn" onClick={() => navigate('/blog')}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px', verticalAlign: 'middle' }}>
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                        <line x1="16" y1="13" x2="8" y2="13"></line>
                        <line x1="16" y1="17" x2="8" y2="17"></line>
                        <polyline points="10 9 9 9 8 9"></polyline>
                      </svg>
                      Blog
                    </button>
                    <button className="nav-btn" onClick={handleMyPageClick}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px', verticalAlign: 'middle' }}>
                        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                        <circle cx="12" cy="7" r="4"></circle>
                      </svg>
                      My Page
                    </button>
                    {isAuthenticated && (
                      <button className="nav-btn" onClick={logout}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px', verticalAlign: 'middle' }}>
                          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                          <polyline points="16 17 21 12 16 7"></polyline>
                          <line x1="21" y1="12" x2="9" y2="12"></line>
                        </svg>
                        Logout
                      </button>
                    )}
                  </div>
                </div>
              </div>
              <Suspense fallback={<div className="app-loading">Loading...</div>}>
                <SearchPage />
              </Suspense>
            </>
          }
        />
      </Routes>
    </div>
  );
}

export default App;
