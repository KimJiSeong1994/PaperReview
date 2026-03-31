import { useState, useEffect, useRef, Suspense, lazy } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import PaperList from './PaperList';
import DetailPanel from './DetailPanel';
import SearchBar from './SearchBar';
import {
  searchPapers,
  getGraphData,
  startDeepReview,
  saveBookmark,
  fetchBatchReferences,
  generatePoster,
  generatePosterDirect,
} from '../api/client';
import type { Paper, GraphData } from '../types';
import { useDeepReview } from '../hooks/useDeepReview';
import { useAuth } from '../contexts/AuthContext';
import { generateApaCitation } from '../utils/citation';
import { copyToClipboard } from '../utils/clipboard';

const GraphViewComponent = lazy(() => import('./GraphView'));

function SearchPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, setShowLoginModal } = useAuth();

  const [papers, setPapers] = useState<Paper[]>([]);
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [highlightedPapers, setHighlightedPapers] = useState<Set<string>>(new Set());
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');

  // Deep Review states
  const [selectedPapersForReview, setSelectedPapersForReview] = useState<Set<string>>(new Set());
  const {
    reviewSessionId, reviewStatus, reviewProgress, reviewReport,
    verificationStats, startReview: startReviewHook, resetReview,
  } = useDeepReview();
  const [showReport, setShowReport] = useState(false);
  const [showToolsMenu, setShowToolsMenu] = useState(false);

  // Bookmark states
  const [bookmarkSaved, setBookmarkSaved] = useState(false);

  // Poster states
  const [posterLoading, setPosterLoading] = useState(false);
  const [posterHtml, setPosterHtml] = useState<string | null>(null);

  // Query guidance (non-academic query feedback)
  const [guidanceMessage, setGuidanceMessage] = useState<string | null>(null);

  // AbortController ref for cancelling in-flight search requests
  const searchAbortRef = useRef<AbortController | null>(null);

  // Auto-dismiss guidance message after 3 seconds
  useEffect(() => {
    if (!guidanceMessage) return;
    const timer = setTimeout(() => setGuidanceMessage(null), 3000);
    return () => clearTimeout(timer);
  }, [guidanceMessage]);

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

    if (searchAbortRef.current) {
      searchAbortRef.current.abort();
    }
    const abortController = new AbortController();
    searchAbortRef.current = abortController;

    setGuidanceMessage(null);

    // Delay loading indicator so non-academic responses (~0.5s) don't flash it
    const loadingTimer = setTimeout(() => {
      setLoading(true);
      setQuery(searchQuery);
    }, 500);

    try {
      const results = await searchPapers({
        query: searchQuery,
        max_results: 50,
        sources: ['arxiv', 'connected_papers', 'google_scholar', 'openalex', 'dblp', 'openalex_korean'],
        sort_by: 'relevance',
        use_llm_search: true,
      }, abortController.signal);

      // Check if query was classified as non-academic
      const qa = (results as any).query_analysis;
      if (qa && qa.is_academic === false) {
        clearTimeout(loadingTimer);
        setGuidanceMessage(
          '학술 논문 및 연구 관련 주제를 입력해주세요. 예: "transformer attention mechanism", "강화학습 정책 최적화"'
        );
        setPapers([]);
        setGraphData(null);
        setSelectedPaper(null);
        setHighlightedPapers(new Set());
        setSelectedPapersForReview(new Set());
        setQuery('');
        setLoading(false);
        return;
      }

      // Academic query confirmed — ensure loading is shown
      clearTimeout(loadingTimer);
      setLoading(true);
      setQuery(searchQuery);

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

      setPapers(allPapers);

      if (allPapers.length > 0) {
        setSelectedPaper(allPapers[0]);
        setHighlightedPapers(new Set());
        setSelectedPapersForReview(new Set());

        const topPapers = allPapers.slice(0, 5).map(p => ({
          title: p.title,
          doi: p.doi,
          arxiv_id: p.arxiv_id,
        }));

        const [graphResult, refsResult] = await Promise.allSettled([
          getGraphData(JSON.stringify(allPapers)),
          fetchBatchReferences(topPapers),
        ]);

        if (graphResult.status === 'fulfilled') {
          setGraphData(graphResult.value);
        }

        if (refsResult.status === 'fulfilled') {
          const { references } = refsResult.value;
          if (references.length > 0) {
            const existingTitles = new Set(allPapers.map(p => p.title.trim().toLowerCase()));
            const refPapers: Paper[] = [];
            for (const ref of references) {
              const normTitle = (ref.title || '').trim().toLowerCase();
              if (!normTitle || existingTitles.has(normTitle)) continue;
              existingTitles.add(normTitle);
              refPapers.push({
                doc_id: hashString(ref.title),
                title: ref.title,
                authors: ref.authors || [],
                year: ref.year,
                abstract: ref.abstract || '',
                url: ref.url || '',
                citations: ref.citations || 0,
                source: 'reference',
                parent_paper_title: ref.parent_paper_title,
              });
            }
            if (refPapers.length > 0) {
              const merged = [...allPapers, ...refPapers];
              setPapers(merged);
              getGraphData(JSON.stringify(merged)).then(g => setGraphData(g)).catch(() => {});
            }
          }
        }
      }
    } catch (error: any) {
      clearTimeout(loadingTimer);

      if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return;

      console.error('Search error:', error);

      let errorMessage = '알 수 없는 오류가 발생했습니다.';

      if (error.code === 'ECONNREFUSED' || error.message?.includes('Network Error') || error.message?.includes('Failed to fetch')) {
        errorMessage = '백엔드 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.';
      } else if (error.response?.data?.detail) {
        errorMessage = error.response.data.detail;
      } else if (error.message) {
        errorMessage = error.message;
      }

      setGuidanceMessage(`검색 중 오류가 발생했습니다: ${errorMessage}`);

      setPapers([]);
      setGraphData(null);
      setSelectedPaper(null);
      setHighlightedPapers(new Set());
      setSelectedPapersForReview(new Set());
    } finally {
      setLoading(false);
    }
  };

  // Auto-search from URL query param (e.g. /?q=paper+title)
  useEffect(() => {
    if (location.pathname !== '/') return;
    const params = new URLSearchParams(location.search);
    const q = params.get('q');
    if (q && q.trim() && q !== query) {
      handleSearch(q.trim());
      navigate('/', { replace: true });
    }
  }, [location.search, location.pathname]);

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
          pdf_url: p.pdf_url || undefined,
          doi: p.doi || undefined,
          arxiv_id: p.arxiv_id || undefined,
          url: p.url || undefined,
          source: p.source || undefined,
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
      setGuidanceMessage(`북마크 저장 실패: ${error.message || error}`);
    }
  };

  const handlePaperSelect = (paper: Paper) => {
    setSelectedPaper(paper);
    setHighlightedPapers(new Set());
  };

  const handleNodeClickWithHighlight = (paper: Paper) => {
    setSelectedPaper(paper);

    if (graphData && graphData.edges) {
      const paperId = paper.doc_id;
      const connectedPapers: Array<{ docId: string; weight: number }> = [];

      graphData.edges.forEach(edge => {
        if (edge.source === paperId || String(edge.source) === String(paperId)) {
          connectedPapers.push({ docId: edge.target, weight: edge.weight || 0 });
        } else if (edge.target === paperId || String(edge.target) === String(paperId)) {
          connectedPapers.push({ docId: edge.source, weight: edge.weight || 0 });
        }
      });

      connectedPapers.sort((a, b) => b.weight - a.weight);
      const topSimilar = connectedPapers.slice(0, 5).map(p => String(p.docId));
      setHighlightedPapers(new Set(topSimilar));
    }
  };

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

  const handleGeneratePoster = async () => {
    if (reviewSessionId && reviewStatus === 'completed' && reviewReport) {
      setPosterLoading(true);
      try {
        const result = await generatePoster(reviewSessionId);
        if (result.poster_html) {
          setPosterHtml(result.poster_html);
          return;
        }
      } catch (err: any) {
        console.warn('Session-based poster failed, trying direct:', err?.response?.status);
      }

      try {
        const result = await generatePosterDirect(reviewReport, selectedPapersForReview.size);
        if (result.poster_html) {
          setPosterHtml(result.poster_html);
        } else {
          setGuidanceMessage(`포스터 생성 실패: ${(result as any).error || '알 수 없는 오류'}`);
        }
      } catch (err: any) {
        console.error('Direct poster generation failed:', err);
        setGuidanceMessage(`포스터 생성 중 오류: ${err?.response?.data?.detail || err?.message || '알 수 없는 오류'}`);
      } finally {
        setPosterLoading(false);
      }
      return;
    }

    if (selectedPapersForReview.size === 0) {
      setGuidanceMessage('포스터를 생성하려면 논문을 선택한 후 Deep Research를 먼저 실행해주세요.');
      return;
    }

    if (reviewStatus === 'processing') {
      setGuidanceMessage('Deep Research가 진행 중입니다. 완료 후 다시 시도해주세요.');
      return;
    }

    const confirmed = confirm(
      `선택된 ${selectedPapersForReview.size}편의 논문으로 Deep Research를 실행한 후 포스터를 생성합니다.\n계속하시겠습니까?`
    );
    if (confirmed) {
      await handleStartDeepReview();
    }
  };

  const handleDownloadPDFs = async () => {
    if (selectedPapersForReview.size === 0) {
      setGuidanceMessage('다운로드할 논문을 선택해주세요.');
      return;
    }

    const selectedPaperIds = Array.from(selectedPapersForReview);
    const selectedPapersData = papers.filter(paper =>
      selectedPaperIds.includes(paper.doc_id || '') ||
      selectedPaperIds.includes(String(paper.doc_id || ''))
    );

    const papersWithPDF = selectedPapersData.filter(paper => paper.pdf_url);

    if (papersWithPDF.length === 0) {
      setGuidanceMessage('선택된 논문 중 다운로드 가능한 PDF가 없습니다.');
      return;
    }

    let downloadedCount = 0;
    for (const paper of papersWithPDF) {
      try {
        const link = document.createElement('a');
        link.href = paper.pdf_url || '';
        link.target = '_blank';
        link.download = `${paper.title.substring(0, 50).replace(/[^a-zA-Z0-9]/g, '_')}.pdf`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        downloadedCount++;
        if (downloadedCount < papersWithPDF.length) {
          await new Promise(resolve => setTimeout(resolve, 500));
        }
      } catch (error) {
        console.error(`Failed to download PDF for paper: ${paper.title}`, error);
      }
    }

    setGuidanceMessage(`${downloadedCount}개의 PDF 다운로드를 시작했습니다.`);
  };

  const handleStartDeepReview = async () => {
    if (selectedPapersForReview.size === 0) return;

    try {
      setShowReport(true);

      const selectedPaperIds = Array.from(selectedPapersForReview);
      const selectedPapersData = papers.filter(paper =>
        selectedPaperIds.includes(paper.doc_id || '') ||
        selectedPaperIds.includes(String(paper.doc_id || ''))
      );

      const response = await startDeepReview({
        paper_ids: selectedPaperIds,
        papers: selectedPapersData,
        num_researchers: Math.min(selectedPapersForReview.size, 5),
        model: 'gpt-4.1',
      });

      startReviewHook(response.session_id);
    } catch (error: any) {
      console.error('Deep review error:', error);
      setGuidanceMessage(`Failed to start deep research: ${error.message || error}`);
      setShowReport(false);
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
    <div className="main-content">
      {!loading && papers.length === 0 && !query && (
        <div className="centered-search">
          <div className="brand-section">
            <h1 className="brand-title">Jiphyeonjeon</h1>
            <p className="brand-tagline">The AI Search Engine You Control</p>
          </div>
          <SearchBar
            onSearch={handleSearch}
            loading={loading}
            guidanceMessage={guidanceMessage}
            onQueryChange={() => setGuidanceMessage(null)}
          />
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
                <SearchBar
                  onSearch={handleSearch}
                  loading={loading}
                  guidanceMessage={guidanceMessage}
                  onQueryChange={() => setGuidanceMessage(null)}
                />
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
                        {reviewStatus === 'processing'
                          ? 'Analyzing...'
                          : selectedPapersForReview.size > 0
                            ? `Deep Research (${selectedPapersForReview.size})`
                            : 'Deep Research'}
                      </span>
                    </button>

                    <div style={{ height: '1px', background: 'rgba(255,255,255,0.1)', margin: '8px 0' }} />

                    <button
                      className="tools-menu-item"
                      disabled={posterLoading}
                      onClick={() => {
                        setShowToolsMenu(false);
                        handleGeneratePoster();
                      }}
                      title="Generate Conference Poster"
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

                    <div style={{ height: '1px', background: 'rgba(255,255,255,0.1)', margin: '8px 0' }} />

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
                        {selectedPapersForReview.size > 0
                          ? `Download PDFs (${selectedPapersForReview.size})`
                          : 'Download PDFs'}
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
                  <GraphViewComponent
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
                  <DetailPanel
                    paper={selectedPaper}
                    onViewPaper={(paper) => {
                      if (!isAuthenticated) {
                        setShowLoginModal(true);
                        return;
                      }
                      navigate('/mypage', { state: { viewPaper: paper } });
                    }}
                  />
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
                            const selectedPaperIds = Array.from(selectedPapersForReview);
                            const selectedPapersData = papers.filter(paper =>
                              selectedPaperIds.includes(paper.doc_id || '') ||
                              selectedPaperIds.includes(String(paper.doc_id || ''))
                            );
                            const apaCitations = selectedPapersData
                              .map(paper => generateApaCitation(paper))
                              .join('\n\n');

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
                        resetReview();
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
                      {verificationStats && verificationStats.total_claims > 0 && (
                        <div className={`verification-banner ${
                          verificationStats.verification_rate >= 0.7 ? 'verification-banner--high' :
                          verificationStats.verification_rate >= 0.4 ? 'verification-banner--medium' : 'verification-banner--low'
                        }`}>
                          <span className="verification-label">Fact Verification</span>
                          <div className="verification-bar" role="status" aria-label={`${(verificationStats.verification_rate * 100).toFixed(0)}% verified`}>
                            {verificationStats.verified > 0 && (
                              <div
                                className="verification-bar__segment verification-bar__segment--verified"
                                style={{ width: `${(verificationStats.verified / verificationStats.total_claims) * 100}%` }}
                                title={`${verificationStats.verified} verified`}
                              />
                            )}
                            {verificationStats.partially_verified > 0 && (
                              <div
                                className="verification-bar__segment verification-bar__segment--partial"
                                style={{ width: `${(verificationStats.partially_verified / verificationStats.total_claims) * 100}%` }}
                                title={`${verificationStats.partially_verified} partial`}
                              />
                            )}
                            {verificationStats.unverified > 0 && (
                              <div
                                className="verification-bar__segment verification-bar__segment--unverified"
                                style={{ width: `${(verificationStats.unverified / verificationStats.total_claims) * 100}%` }}
                                title={`${verificationStats.unverified} unverified`}
                              />
                            )}
                            {verificationStats.contradicted > 0 && (
                              <div
                                className="verification-bar__segment verification-bar__segment--contradicted"
                                style={{ width: `${(verificationStats.contradicted / verificationStats.total_claims) * 100}%` }}
                                title={`${verificationStats.contradicted} contradicted`}
                              />
                            )}
                          </div>
                          <span className="verification-rate">
                            {(verificationStats.verification_rate * 100).toFixed(0)}% verified
                          </span>
                          <span className="verification-detail">
                            {verificationStats.verified} verified, {verificationStats.partially_verified} partial, {verificationStats.unverified} unverified
                            {verificationStats.contradicted > 0 && `, ${verificationStats.contradicted} contradicted`}
                            &nbsp;&middot;&nbsp;{verificationStats.total_claims} claims ({verificationStats.verifiable_claims} verifiable)
                          </span>
                        </div>
                      )}
                      <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>
                        {reviewReport}
                      </pre>
                      <div style={{
                        marginTop: '16px',
                        padding: '12px 16px',
                        background: 'rgba(99, 102, 241, 0.1)',
                        border: '1px solid rgba(99, 102, 241, 0.3)',
                        borderRadius: '8px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}>
                        <span style={{ color: '#a5b4fc', fontSize: '13px' }}>
                          Deep Research 완료 — 결과를 학회 포스터로 변환할 수 있습니다
                        </span>
                        <button
                          onClick={handleGeneratePoster}
                          disabled={posterLoading}
                          style={{
                            padding: '6px 16px',
                            background: '#6366f1',
                            color: 'white',
                            border: 'none',
                            borderRadius: '6px',
                            cursor: posterLoading ? 'wait' : 'pointer',
                            fontSize: '13px',
                            fontWeight: 500,
                            opacity: posterLoading ? 0.7 : 1,
                          }}
                        >
                          {posterLoading ? 'Generating...' : 'Generate Poster'}
                        </button>
                      </div>
                    </div>
                  )}
                  {reviewStatus === 'failed' && (
                    <div className="review-error">
                      <p>Analysis Failed</p>
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
            <SearchBar
              onSearch={handleSearch}
              loading={loading}
              guidanceMessage={guidanceMessage}
              onQueryChange={() => setGuidanceMessage(null)}
            />
          </div>
          <div className="empty-state">
            <p>검색 결과가 없습니다. 다른 키워드로 시도해보세요.</p>
          </div>
        </div>
      )}

      {/* Poster Viewer Modal */}
      {posterHtml && (
        <div className="poster-modal-overlay" onClick={() => setPosterHtml(null)}>
          <div className="poster-modal" onClick={(e) => e.stopPropagation()}>
            <div className="poster-modal-header">
              <span className="poster-modal-title">Conference Poster</span>
              <div className="poster-modal-actions">
                <button
                  className="poster-modal-btn"
                  onClick={() => {
                    const blob = new Blob([posterHtml], { type: 'text/html' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'poster.html';
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                  title="Download HTML"
                >
                  Download
                </button>
                <button className="poster-modal-close" onClick={() => setPosterHtml(null)}>
                  ✕
                </button>
              </div>
            </div>
            <iframe
              className="poster-modal-iframe"
              srcDoc={posterHtml}
              title="Poster Preview"
            />
          </div>
        </div>
      )}
    </div>
  );
}

export default SearchPage;
