import { useState, useEffect, lazy, Suspense } from 'react';
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import './App.css';
import PaperList from './components/PaperList';
import DetailPanel from './components/DetailPanel';
import SearchBar from './components/SearchBar';
import LoginModal from './components/LoginPage';

const MyPage = lazy(() => import('./components/MyPage'));
const GraphView = lazy(() => import('./components/GraphView'));
const AdminPage = lazy(() => import('./components/AdminPage'));
import { searchPapers, getGraphData, startDeepReview, getReviewStatus, getReviewReport, generatePoster, saveBookmark, verifyToken } from './api/client';
import type { Paper, GraphData } from './types';

// 질의와 논문 간 유사도 계산 함수
function calculateSimilarity(paper: Paper, query: string, queryKeywords: string[] = []): number {
  const queryLower = query.toLowerCase().trim();
  const titleLower = (paper.title || '').toLowerCase();
  const abstractLower = (paper.abstract || '').toLowerCase();
  
  // 키워드 추출 (질의 분석 결과가 있으면 사용, 없으면 간단히 추출)
  const keywords = queryKeywords.length > 0 
    ? queryKeywords.map(k => k.toLowerCase().trim()).filter(k => k.length > 0)
    : queryLower.split(/\s+/).filter(w => w.length > 2);
  
  if (keywords.length === 0) return 0;
  
  let score = 0;
  
  // 제목 전체 매칭 (가장 높은 가중치)
  if (titleLower.includes(queryLower) || queryLower.includes(titleLower)) {
    score += 10;
  }
  
  // 제목 키워드 매칭 (가중치 높음)
  let titleMatchCount = 0;
  keywords.forEach(keyword => {
    if (titleLower.includes(keyword)) {
      titleMatchCount++;
      score += 3; // 제목에 키워드가 있으면 높은 점수
    }
  });
  
  // 모든 키워드가 제목에 있으면 보너스
  if (titleMatchCount === keywords.length && keywords.length > 0) {
    score += 5;
  }
  
  // Abstract 전체 매칭
  if (abstractLower.includes(queryLower)) {
    score += 3;
  }
  
  // Abstract 키워드 매칭
  let abstractMatchCount = 0;
  keywords.forEach(keyword => {
    if (abstractLower.includes(keyword)) {
      abstractMatchCount++;
      score += 1; // Abstract에 키워드가 있으면 낮은 점수
    }
  });
  
  // 키워드 매칭 비율 계산
  const totalMatches = titleMatchCount + abstractMatchCount;
  const matchRatio = totalMatches / (keywords.length * 2); // 제목과 abstract 모두 고려
  score += matchRatio * 2;
  
  // 저자 매칭 (낮은 가중치)
  const authorsLower = (paper.authors || []).join(' ').toLowerCase();
  if (authorsLower.includes(queryLower)) {
    score += 0.5;
  }
  
  return score;
}

// 질의와 유사도 순으로 논문 정렬
function sortPapersByQuerySimilarity(
  papers: Paper[], 
  query: string, 
  queryAnalysis: any = null
): Paper[] {
  if (!query || papers.length === 0) return papers;
  
  // 질의 분석 결과에서 키워드 추출
  const queryKeywords = queryAnalysis?.keywords || [];
  
  // 각 논문에 유사도 점수 계산
  const papersWithScore = papers.map(paper => ({
    paper,
    similarity: calculateSimilarity(paper, query, queryKeywords),
  }));
  
  // 유사도 순으로 정렬 (높은 점수부터)
  papersWithScore.sort((a, b) => b.similarity - a.similarity);
  
  // 정렬된 논문 배열 반환
  return papersWithScore.map(item => item.paper);
}

function App() {
  const navigate = useNavigate();

  // Auth state
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(() => !!localStorage.getItem('access_token'));
  const [userRole, setUserRole] = useState<string>(() => localStorage.getItem('user_role') || 'user');

  // Verify token on mount
  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (token) {
      verifyToken(token)
        .then((data) => {
          setIsAuthenticated(true);
          setUserRole(data.role || 'user');
          localStorage.setItem('user_role', data.role || 'user');
        })
        .catch(() => {
          localStorage.removeItem('access_token');
          localStorage.removeItem('username');
          localStorage.removeItem('user_role');
          setIsAuthenticated(false);
          setUserRole('user');
        });
    }
  }, []);

  const [showLoginModal, setShowLoginModal] = useState(false);

  const handleLoginSuccess = () => {
    setIsAuthenticated(true);
    const role = localStorage.getItem('user_role') || 'user';
    setUserRole(role);
    setShowLoginModal(false);
    navigate('/mypage');
  };

  const handleLogout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('username');
    localStorage.removeItem('user_role');
    setIsAuthenticated(false);
    setUserRole('user');
    navigate('/');
  };

  const handleMyPageClick = () => {
    if (isAuthenticated) {
      navigate('/mypage');
    } else {
      setShowLoginModal(true);
    }
  };

  const [papers, setPapers] = useState<Paper[]>([]);
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [highlightedPapers, setHighlightedPapers] = useState<Set<string>>(new Set());
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  
  // Deep Review states
  const [selectedPapersForReview, setSelectedPapersForReview] = useState<Set<string>>(new Set());
  const [reviewSessionId, setReviewSessionId] = useState<string | null>(null);
  const [reviewStatus, setReviewStatus] = useState<string>('idle'); // idle, processing, completed, failed
  const [reviewProgress, setReviewProgress] = useState<string>('');
  const [reviewReport, setReviewReport] = useState<string | null>(null);
  const [showReport, setShowReport] = useState(false);
  const [, setDetailsCollapsed] = useState(false);  // detailsCollapsed 사용 안함
  const [showToolsMenu, setShowToolsMenu] = useState(false);
  
  // Poster visualization states
  const [posterHtml, setPosterHtml] = useState<string | null>(null);
  const [showPoster, setShowPoster] = useState(false);
  const [posterLoading, setPosterLoading] = useState(false);

  // Bookmark states
  const [bookmarkSaved, setBookmarkSaved] = useState(false);

  const hashString = (str: string) => {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return Math.abs(hash).toString();
  };

  const handleSearch = async (searchQuery: string) => {
    if (!searchQuery.trim()) return;

    setLoading(true);
    setQuery(searchQuery);

    try {
      {
        const results = await searchPapers({
          query: searchQuery,
          max_results: 50,
          sources: ['arxiv', 'connected_papers', 'google_scholar'],
          sort_by: 'relevance',
        });

        const allPapers: Paper[] = [];

        Object.entries(results.results).forEach(([source, sourcePapers]) => {
          sourcePapers.forEach((paper: any) => {
            const title = paper.title || 'Untitled';
            const doc_id = hashString(title);

            allPapers.push({
              doc_id,
              title,
              authors: paper.authors || [],
              year: paper.year || paper.published,
              journal: paper.journal || paper.publication || '',
              abstract: paper.abstract || '',
              url: paper.url || paper.paper_url,
              pdf_url: paper.pdf_url,
              doi: paper.doi,
              citations: paper.citations || 0,
              source: source,
              ...paper,
            });
          });
        });

        const queryAnalysis = (results as any).query_analysis || null;
        const sortedPapers = sortPapersByQuerySimilarity(allPapers, searchQuery, queryAnalysis);
        setPapers(sortedPapers);

        if (allPapers.length > 0) {
          const graph = await getGraphData(JSON.stringify(allPapers));
          setGraphData(graph);

          if (!selectedPaper && allPapers.length > 0) {
            setSelectedPaper(allPapers[0]);
            setHighlightedPapers(new Set());
          }
        }
      }
    } catch (error: any) {
      console.error('Search error:', error);

      let errorMessage = '알 수 없는 오류가 발생했습니다.';

      if (error.code === 'ECONNREFUSED' || error.message?.includes('Network Error') || error.message?.includes('Failed to fetch')) {
        errorMessage = '백엔드 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요. (http://localhost:8000)';
      } else if (error.response?.data?.detail) {
        errorMessage = error.response.data.detail;
      } else if (error.message) {
        errorMessage = error.message;
      }

      alert(`검색 중 오류가 발생했습니다: ${errorMessage}`);

      setPapers([]);
      setGraphData(null);
      setSelectedPaper(null);
      setHighlightedPapers(new Set());
    } finally {
      setLoading(false);
    }
  };

  // Bookmark handlers
  const handleSaveBookmark = async () => {
    if (!reviewSessionId || !reviewReport) return;
    if (!isAuthenticated) {
      setShowLoginModal(true);
      return;
    }
    try {
      const selectedPaperIds = Array.from(selectedPapersForReview);
      const selectedPapersData = papers.filter(paper =>
        selectedPaperIds.includes(paper.doc_id || '') ||
        selectedPaperIds.includes(String(paper.doc_id || ''))
      );
      const title = query
        ? `${query} - ${new Date().toLocaleDateString()}`
        : `Deep Research - ${new Date().toLocaleDateString()}`;
      await saveBookmark({
        session_id: reviewSessionId,
        title,
        query,
        papers: selectedPapersData.map(p => ({
          title: p.title,
          authors: p.authors,
          year: p.year,
        })),
        report_markdown: reviewReport,
      });
      setBookmarkSaved(true);
      setTimeout(() => setBookmarkSaved(false), 3000);
    } catch (error: any) {
      if (error.response?.status === 401) {
        setShowLoginModal(true);
        return;
      }
      console.error('Bookmark save error:', error);
      alert(`북마크 저장 실패: ${error.message || error}`);
    }
  };

  const handlePaperSelect = (paper: Paper) => {
    setSelectedPaper(paper);
    // Clear previous highlights
    setHighlightedPapers(new Set());
  };

  const handleNodeClickWithHighlight = (paper: Paper) => {
    setSelectedPaper(paper);
    
    // Find connected papers with highest similarity
    if (graphData && graphData.edges) {
      const paperId = paper.doc_id;
      const connectedPapers: Array<{ docId: string; weight: number }> = [];
      
      // Find all edges connected to this paper
      graphData.edges.forEach(edge => {
        if (edge.source === paperId || String(edge.source) === String(paperId)) {
          connectedPapers.push({
            docId: edge.target,
            weight: edge.weight || 0,
          });
        } else if (edge.target === paperId || String(edge.target) === String(paperId)) {
          connectedPapers.push({
            docId: edge.source,
            weight: edge.weight || 0,
          });
        }
      });
      
      // Sort by weight (similarity) descending
      connectedPapers.sort((a, b) => b.weight - a.weight);
      
      // Get top 5 most similar papers (or all if less than 5)
      const topSimilar = connectedPapers.slice(0, 5).map(p => String(p.docId));
      
      // Set highlighted papers
      setHighlightedPapers(new Set(topSimilar));
    }
  };

  // Deep Review handlers
  const handlePaperToggleForReview = (paperId: string) => {
    setSelectedPapersForReview(prev => {
      const newSet = new Set(prev);
      if (newSet.has(paperId)) {
        newSet.delete(paperId);
      } else {
        newSet.add(paperId);
      }
      return newSet;
    });
  };

  const handleDownloadPDFs = async () => {
    if (selectedPapersForReview.size === 0) {
      alert('다운로드할 논문을 선택해주세요.');
      return;
    }

    const selectedPaperIds = Array.from(selectedPapersForReview);
    const selectedPapersData = papers.filter(paper => 
      selectedPaperIds.includes(paper.doc_id || '') ||
      selectedPaperIds.includes(String(paper.doc_id || ''))
    );

    // PDF URL이 있는 논문들만 필터링
    const papersWithPDF = selectedPapersData.filter(paper => paper.pdf_url);

    if (papersWithPDF.length === 0) {
      alert('선택된 논문 중 다운로드 가능한 PDF가 없습니다.');
      return;
    }

    // 각 PDF 다운로드
    let downloadedCount = 0;
    for (const paper of papersWithPDF) {
      try {
        // PDF URL을 새 탭에서 열어 브라우저가 다운로드 처리하도록 함
        const link = document.createElement('a');
        link.href = paper.pdf_url || '';
        link.target = '_blank';
        link.download = `${paper.title.substring(0, 50).replace(/[^a-zA-Z0-9]/g, '_')}.pdf`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        downloadedCount++;
        
        // 브라우저가 여러 다운로드를 차단하지 않도록 약간의 딜레이 추가
        if (downloadedCount < papersWithPDF.length) {
          await new Promise(resolve => setTimeout(resolve, 500));
        }
      } catch (error) {
        console.error(`Failed to download PDF for paper: ${paper.title}`, error);
      }
    }

    alert(`${downloadedCount}개의 PDF 다운로드를 시작했습니다.`);
  };

  const handleStartDeepReview = async () => {
    if (selectedPapersForReview.size === 0) {
      return;
    }

    try {
      setReviewStatus('processing');
      setShowReport(true);
      setDetailsCollapsed(true);

      // 선택한 논문들의 전체 데이터 추출
      const selectedPaperIds = Array.from(selectedPapersForReview);
      const selectedPapersData = papers.filter(paper => 
        selectedPaperIds.includes(paper.doc_id || '') ||
        selectedPaperIds.includes(String(paper.doc_id || ''))
      );

      console.log('Selected paper IDs:', selectedPaperIds);
      console.log('Selected papers data:', selectedPapersData.length);

      const response = await startDeepReview({
        paper_ids: selectedPaperIds,
        papers: selectedPapersData,  // 논문 전체 데이터 포함
        num_researchers: Math.min(selectedPapersForReview.size, 5),
        model: 'gpt-4.1'
      });

      setReviewSessionId(response.session_id);
      setReviewProgress('Starting deep research...');

    } catch (error: any) {
      console.error('Deep review error:', error);
      alert(`Failed to start deep research: ${error.message || error}`);
      setReviewStatus('failed');
      setShowReport(false);
      setDetailsCollapsed(false);
    }
  };

  // Poll review status
  useEffect(() => {
    if (!reviewSessionId || reviewStatus !== 'processing') return;

    const pollInterval = setInterval(async () => {
      try {
        const status = await getReviewStatus(reviewSessionId);
        
        setReviewProgress(status.progress || 'Analyzing papers...');

        if (status.status === 'completed') {
          setReviewStatus('completed');
          // Fetch report
          const report = await getReviewReport(reviewSessionId);
          setReviewReport(report.report_markdown);
          clearInterval(pollInterval);
        } else if (status.status === 'failed') {
          setReviewStatus('failed');
          setReviewProgress(status.error || 'Analysis failed');
          clearInterval(pollInterval);
        }
      } catch (error) {
        console.error('Status poll error:', error);
      }
    }, 3000); // Poll every 3 seconds

    return () => clearInterval(pollInterval);
  }, [reviewSessionId, reviewStatus]);

  // Generate poster visualization
  const handleGeneratePoster = async () => {
    if (!reviewSessionId) {
      alert('No review session available');
      return;
    }

    try {
      setPosterLoading(true);
      const response = await generatePoster(reviewSessionId);
      
      if (response.success) {
        setPosterHtml(response.poster_html);
        setShowPoster(true);
      } else {
        alert('Failed to generate poster');
      }
    } catch (error: any) {
      console.error('Poster generation error:', error);
      alert(`포스터 생성 실패: ${error.message || error}`);
    } finally {
      setPosterLoading(false);
    }
  };

  // Close tools menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (!target.closest('.tools-dropdown-container')) {
        setShowToolsMenu(false);
      }
    };

    if (showToolsMenu) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showToolsMenu]);


  return (
    <div className="app">
      {/* Login modal overlay */}
      {showLoginModal && !isAuthenticated && (
        <LoginModal
          onLoginSuccess={handleLoginSuccess}
          onClose={() => setShowLoginModal(false)}
        />
      )}

      <Routes>
      <Route path="/mypage" element={isAuthenticated ? <Suspense fallback={<div className="app-loading">Loading...</div>}><MyPage onBack={() => navigate('/')} /></Suspense> : <Navigate to="/" />} />
      <Route path="/admin" element={isAuthenticated && userRole === 'admin' ? <Suspense fallback={<div className="app-loading">Loading...</div>}><AdminPage /></Suspense> : <Navigate to="/" />} />
      <Route path="*" element={<>
      {/* Minimal header */}
      <div className="app-header">
        <div className="header-nav">
          <div className="logo" onClick={() => navigate('/')} style={{ cursor: 'pointer' }}>
            <img
              src="/Jipyheonjeon_llama.png"
              alt="Jipyheonjeon"
              className="logo-icon"
              onError={(e) => {
                e.currentTarget.style.display = 'none';
              }}
            />
            <span className="brand-name">Jipyheonjeon</span>
          </div>
          <div className="header-actions">
            {isAuthenticated && userRole === 'admin' && (
              <button
                className="nav-btn"
                onClick={() => navigate('/admin')}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px', verticalAlign: 'middle' }}>
                  <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
                Admin
              </button>
            )}
            <button
              className="nav-btn"
              onClick={handleMyPageClick}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px', verticalAlign: 'middle' }}>
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                <circle cx="12" cy="7" r="4"></circle>
              </svg>
              My Page
            </button>
            {isAuthenticated && (
              <button
                className="nav-btn"
                onClick={handleLogout}
              >
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
      <div className="main-content">
        {!loading && papers.length === 0 && !query && (
          <div className="centered-search">
            <div className="brand-section">
              <h1 className="brand-title">Jipyheonjeon</h1>
              <p className="brand-tagline">The AI Search Engine You Control</p>
            </div>
            <SearchBar onSearch={handleSearch} loading={loading} />
          </div>
        )}

        {loading && (
          <div className="loading-screen">
            <div className="loading-message-bubble">
              <div className="loading-text">
                결과를 분석하고 있습니다...
              </div>
            </div>
          </div>
        )}

        {!loading && papers.length > 0 && (
          <div className="results-view">
            <div className="search-bar-fixed">
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', width: '100%', position: 'relative' }}>
                <div style={{ flex: 1 }}>
                  <SearchBar onSearch={handleSearch} loading={loading} />
                </div>
                <div className="tools-dropdown-container">
                  <button
                    className="tools-button"
                    onClick={() => setShowToolsMenu(!showToolsMenu)}
                  >
                    <svg 
                      className="tools-icon" 
                      viewBox="0 0 24 24" 
                      fill="none" 
                      stroke="currentColor" 
                      strokeWidth="2"
                    >
                      <circle cx="12" cy="6" r="1" fill="currentColor"></circle>
                      <circle cx="12" cy="12" r="1" fill="currentColor"></circle>
                      <circle cx="12" cy="18" r="1" fill="currentColor"></circle>
                      <circle cx="6" cy="12" r="1" fill="currentColor"></circle>
                      <circle cx="18" cy="12" r="1" fill="currentColor"></circle>
                    </svg>
                    <span className="tools-text">Tools</span>
                  </button>
                  {showToolsMenu && (
                    <div className="tools-dropdown-menu">
                      <button
                        className="tools-menu-item"
                        onClick={() => {
                          setShowToolsMenu(false);
                          handleStartDeepReview();
                        }}
                        disabled={selectedPapersForReview.size === 0 || reviewStatus === 'processing'}
                      >
                        <svg 
                          className="menu-item-icon" 
                          viewBox="0 0 24 24" 
                          fill="none" 
                          stroke="currentColor" 
                          strokeWidth="2"
                        >
                          <circle cx="11" cy="11" r="8"></circle>
                          <path d="m21 21-4.35-4.35"></path>
                        </svg>
                        <span className="menu-item-text">
                          {reviewStatus === 'processing' ? 'Analyzing...' : selectedPapersForReview.size > 0 ? `Deep Research (${selectedPapersForReview.size})` : 'Deep Research'}
                        </span>
                      </button>
                      
                      {/* 구분선 */}
                      <div style={{ 
                        height: '1px', 
                        background: 'rgba(255,255,255,0.1)', 
                        margin: '8px 0' 
                      }} />
                      
                      {/* 학회 포스터 생성 버튼 */}
                      <button
                        className="tools-menu-item"
                        onClick={() => {
                          setShowToolsMenu(false);
                          handleGeneratePoster();
                        }}
                        disabled={reviewStatus !== 'completed' || posterLoading}
                      >
                        <svg 
                          className="menu-item-icon" 
                          viewBox="0 0 24 24" 
                          fill="none" 
                          stroke="currentColor" 
                          strokeWidth="2"
                        >
                          <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                          <line x1="3" y1="9" x2="21" y2="9"></line>
                          <line x1="9" y1="21" x2="9" y2="9"></line>
                        </svg>
                        <span className="menu-item-text">
                          {posterLoading ? 'Generating...' : 'Generate Poster'}
                        </span>
                      </button>
                      
                      {/* 구분선 */}
                      <div style={{ 
                        height: '1px', 
                        background: 'rgba(255,255,255,0.1)', 
                        margin: '8px 0' 
                      }} />
                      
                      {/* PDF 다운로드 버튼 */}
                      <button
                        className="tools-menu-item"
                        onClick={() => {
                          setShowToolsMenu(false);
                          handleDownloadPDFs();
                        }}
                        disabled={selectedPapersForReview.size === 0}
                      >
                        <svg
                          className="menu-item-icon"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                        >
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                          <polyline points="7 10 12 15 17 10"></polyline>
                          <line x1="12" y1="15" x2="12" y2="3"></line>
                        </svg>
                        <span className="menu-item-text">
                          {selectedPapersForReview.size > 0 ? `Download PDFs (${selectedPapersForReview.size})` : 'Download PDFs'}
                        </span>
                      </button>

                    </div>
                  )}
                </div>
              </div>
            </div>
            
            <div className="main-container">
              <div className="left-panel">
                <div className="pane-title">
                  Prior & Related Works
                  {selectedPapersForReview.size > 0 && (
                    <span style={{ marginLeft: '8px', fontSize: '0.9em', color: '#666' }}>
                      ({selectedPapersForReview.size} 선택됨)
                    </span>
                  )}
                </div>
                <PaperList
                  papers={papers}
                  selectedPaper={selectedPaper}
                  onSelect={handlePaperSelect}
                  selectedForReview={selectedPapersForReview}
                  onToggleForReview={handlePaperToggleForReview}
                />
              </div>

              <div className="center-panel">
                <div className="pane-title">Graph View</div>
                {graphData && (
                  <Suspense fallback={<div className="app-loading">Loading graph...</div>}>
                    <GraphView
                      graphData={graphData}
                      selectedPaper={selectedPaper}
                      highlightedPapers={highlightedPapers}
                      papers={papers}
                      onNodeClick={handleNodeClickWithHighlight}
                    />
                  </Suspense>
                )}
              </div>

              {!showReport && (
                <div className="right-panel">
                  <div className="pane-title">Details</div>
                  {selectedPaper ? (
                    <DetailPanel paper={selectedPaper} />
                  ) : (
                    <div className="no-selection">논문을 선택하세요</div>
                  )}
                </div>
              )}

              {showReport && (
                <div className="right-panel">
                  <div className="pane-title">
                    Deep Research Report
                    <div className="report-title-actions">
                      {reviewStatus === 'completed' && reviewReport && (
                        <>
                          <button
                            className="cite-report-button"
                            onClick={() => {
                              // 선택된 논문들을 APA 형식으로 변환
                              const selectedPaperIds = Array.from(selectedPapersForReview);
                              const selectedPapersData = papers.filter(paper =>
                                selectedPaperIds.includes(paper.doc_id || '') ||
                                selectedPaperIds.includes(String(paper.doc_id || ''))
                              );

                              const apaCitations = selectedPapersData.map(paper => {
                                // 저자 포맷팅 (APA: 성, 이니셜.)
                                const formatAuthors = (authors: string[]) => {
                                  if (!authors || authors.length === 0) return 'Unknown Author';

                                  const formatted = authors.slice(0, 20).map((author) => {
                                    const parts = author.trim().split(' ');
                                    if (parts.length === 1) return parts[0];
                                    const lastName = parts[parts.length - 1];
                                    const initials = parts.slice(0, -1).map(p => p[0]?.toUpperCase() + '.').join(' ');
                                    return `${lastName}, ${initials}`;
                                  });

                                  if (authors.length > 20) {
                                    return formatted.slice(0, 19).join(', ') + ', ... ' + formatted[formatted.length - 1];
                                  } else if (formatted.length === 1) {
                                    return formatted[0];
                                  } else if (formatted.length === 2) {
                                    return formatted.join(', & ');
                                  } else {
                                    return formatted.slice(0, -1).join(', ') + ', & ' + formatted[formatted.length - 1];
                                  }
                                };

                                // 연도 추출
                                const getYear = () => {
                                  if (paper.year) return String(paper.year);
                                  if (paper.published_date) {
                                    const match = String(paper.published_date).match(/(\d{4})/);
                                    return match ? match[1] : 'n.d.';
                                  }
                                  return 'n.d.';
                                };

                                // 월 추출
                                const getMonth = () => {
                                  if (paper.month) return paper.month;
                                  if (paper.published_date) {
                                    const date = new Date(paper.published_date);
                                    if (!isNaN(date.getTime())) {
                                      return date.toLocaleString('en-US', { month: 'long' });
                                    }
                                  }
                                  return '';
                                };

                                // 학회/저널 정보 추출
                                const getVenueInfo = () => {
                                  if (paper.journal_ref) return paper.journal_ref;
                                  if (paper.journal) return paper.journal;
                                  if (paper.comment) {
                                    const match = paper.comment.match(/(?:accepted at|published in|presented at)\s+(.+?)(?:;|$)/i);
                                    if (match) return match[1].trim();
                                    if (/conference|proceedings|workshop|symposium|journal/i.test(paper.comment)) {
                                      return paper.comment;
                                    }
                                  }
                                  return '';
                                };

                                const authors = formatAuthors(paper.authors || []);
                                const year = getYear();
                                const month = getMonth();
                                const title = paper.title || 'Untitled';
                                const venue = getVenueInfo();
                                const pages = paper.pages || '';
                                const volume = paper.volume || '';
                                const issue = paper.issue || '';

                                const isConferencePaper = venue && /proceedings|conference|workshop|symposium/i.test(venue);
                                const isArxiv = paper.source === 'arXiv' || paper.arxiv_id;

                                let citation = '';

                                if (isConferencePaper) {
                                  const yearPart = month ? `${year}, ${month}` : year;
                                  const pagesPart = pages ? ` (pp. ${pages})` : '';
                                  citation = `${authors} (${yearPart}). ${title}. In ${venue}${pagesPart}.`;
                                } else if (isArxiv) {
                                  const arxivId = paper.arxiv_id || paper.url?.match(/abs\/(.+)/)?.[1] || '';
                                  citation = `${authors} (${year}). ${title}. arXiv preprint arXiv:${arxivId}.`;
                                } else if (venue) {
                                  let venuePart = venue;
                                  if (volume) {
                                    venuePart += `, ${volume}`;
                                    if (issue) venuePart += `(${issue})`;
                                  }
                                  if (pages) venuePart += `, ${pages}`;
                                  citation = `${authors} (${year}). ${title}. ${venuePart}.`;
                                } else {
                                  citation = `${authors} (${year}). ${title}.`;
                                }

                                if (paper.doi) {
                                  citation += ` https://doi.org/${paper.doi}`;
                                } else if (paper.url) {
                                  citation += ` ${paper.url}`;
                                }

                                return citation;
                              }).join('\n\n');

                              // Clipboard API fallback for HTTP environments
                              const copyToClipboard = (text: string) => {
                                if (navigator.clipboard && window.isSecureContext) {
                                  return navigator.clipboard.writeText(text);
                                } else {
                                  const textArea = document.createElement('textarea');
                                  textArea.value = text;
                                  textArea.style.position = 'fixed';
                                  textArea.style.left = '-999999px';
                                  textArea.style.top = '-999999px';
                                  document.body.appendChild(textArea);
                                  textArea.focus();
                                  textArea.select();
                                  return new Promise<void>((resolve, reject) => {
                                    document.execCommand('copy') ? resolve() : reject();
                                    textArea.remove();
                                  });
                                }
                              };

                              copyToClipboard(apaCitations).then(() => {
                                const btn = document.querySelector('.cite-report-button') as HTMLButtonElement;
                                if (btn) {
                                  btn.classList.add('copied');
                                  setTimeout(() => btn.classList.remove('copied'), 1500);
                                }
                              });
                            }}
                            title="Copy APA Citations"
                          >
                            <svg
                              className="cite-icon"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                            >
                              <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5C7 4 7 7 7 7"></path>
                              <path d="M6 15H4.5a2.5 2.5 0 0 0 0 5C7 20 7 17 7 17"></path>
                              <path d="M18 9h1.5a2.5 2.5 0 0 0 0-5C17 4 17 7 17 7"></path>
                              <path d="M18 15h1.5a2.5 2.5 0 0 1 0 5C17 20 17 17 17 17"></path>
                              <line x1="7" y1="7" x2="7" y2="17"></line>
                              <line x1="17" y1="7" x2="17" y2="17"></line>
                            </svg>
                          </button>
                          <button
                            className="download-report-button"
                            onClick={() => {
                              const blob = new Blob([reviewReport], { type: 'text/markdown' });
                              const url = URL.createObjectURL(blob);
                              const a = document.createElement('a');
                              a.href = url;
                              a.download = `deep_research_${new Date().toISOString().split('T')[0]}.md`;
                              document.body.appendChild(a);
                              a.click();
                              document.body.removeChild(a);
                              URL.revokeObjectURL(url);
                            }}
                            title="Download as Markdown"
                          >
                            <svg
                              className="download-icon"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                            >
                              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                              <polyline points="7 10 12 15 17 10"></polyline>
                              <line x1="12" y1="15" x2="12" y2="3"></line>
                            </svg>
                          </button>
                          <button
                            className={`bookmark-save-button ${bookmarkSaved ? 'saved' : ''}`}
                            onClick={handleSaveBookmark}
                            title={bookmarkSaved ? 'Bookmarked!' : 'Save as Bookmark'}
                          >
                            <svg
                              className="bookmark-icon"
                              viewBox="0 0 24 24"
                              fill={bookmarkSaved ? 'currentColor' : 'none'}
                              stroke="currentColor"
                              strokeWidth="2"
                            >
                              <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path>
                            </svg>
                          </button>
                        </>
                      )}
                      <button
                        className="close-report-button"
                        onClick={() => {
                          setShowReport(false);
                          setDetailsCollapsed(false);
                          setReviewStatus('idle');
                          setReviewReport(null);
                          setBookmarkSaved(false);
                        }}
                        title="Close report"
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                  <div className="report-content">
                    {reviewStatus === 'processing' && (
                      <div className="review-processing">
                        <div className="loading-spinner"></div>
                        <p>{reviewProgress}</p>
                        <p className="review-hint">Researchers are analyzing papers in parallel...</p>
                      </div>
                    )}
                    {reviewStatus === 'completed' && reviewReport && (
                      <div className="review-report-markdown">
                        <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>
                          {reviewReport}
                        </pre>
                      </div>
                    )}
                    {reviewStatus === 'failed' && (
                      <div className="review-error">
                        <p>❌ Analysis Failed</p>
                        <p>{reviewProgress}</p>
                      </div>
                    )}
                  </div>
                </div>
              )}

            </div>
          </div>
        )}

        {!loading && papers.length === 0 && query && (
          <div className="centered-search">
            <div className="search-bar-fixed">
              <SearchBar onSearch={handleSearch} loading={loading} />
            </div>
            <div className="empty-state">
              <p>검색 결과가 없습니다. 다른 키워드로 시도해보세요.</p>
            </div>
          </div>
        )}

        {/* Poster Modal */}
        {showPoster && posterHtml && (
          <div className="poster-modal-overlay" onClick={() => setShowPoster(false)}>
            <div className="poster-modal" onClick={(e) => e.stopPropagation()}>
              <div className="poster-modal-header">
                <h2>🎓 학회 포스터</h2>
                <div className="poster-modal-actions">
                  <button
                    className="poster-download-button"
                    onClick={() => {
                      const blob = new Blob([posterHtml], { type: 'text/html' });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement('a');
                      a.href = url;
                      a.download = `poster_${new Date().toISOString().split('T')[0]}.html`;
                      document.body.appendChild(a);
                      a.click();
                      document.body.removeChild(a);
                      URL.revokeObjectURL(url);
                    }}
                  >
                    📥 HTML 다운로드
                  </button>
                  <button
                    className="poster-close-button"
                    onClick={() => setShowPoster(false)}
                  >
                    ✕
                  </button>
                </div>
              </div>
              <div className="poster-modal-content">
                <iframe
                  srcDoc={posterHtml}
                  title="Conference Poster"
                  className="poster-iframe"
                />
              </div>
            </div>
          </div>
        )}
      </div>
      </>} />
      </Routes>
    </div>
  );
}

export default App;
