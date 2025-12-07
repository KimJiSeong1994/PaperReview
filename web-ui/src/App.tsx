import { useState, useEffect } from 'react';
import './App.css';
import GraphView from './components/GraphView';
import PaperList from './components/PaperList';
import DetailPanel from './components/DetailPanel';
import SearchBar from './components/SearchBar';
import { searchPapers, getGraphData, startDeepReview, getReviewStatus, getReviewReport, generatePoster } from './api/client';
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

  const handleSearch = async (searchQuery: string) => {
    if (!searchQuery.trim()) return;
    
    setLoading(true);
    setQuery(searchQuery);
    try {
      const results = await searchPapers({
        query: searchQuery,
        max_results: 50,
        sources: ['arxiv', 'connected_papers', 'google_scholar'],
        sort_by: 'relevance',
      });

      // Flatten results from all sources
      // Use title hash for consistent ID generation (matches backend)
      const hashString = (str: string) => {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
          const char = str.charCodeAt(i);
          hash = ((hash << 5) - hash) + char;
          hash = hash & hash; // Convert to 32bit integer
        }
        return Math.abs(hash).toString();
      };

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

      // 질의와 유사도 순으로 정렬
      const queryAnalysis = (results as any).query_analysis || null;
      const sortedPapers = sortPapersByQuerySimilarity(allPapers, searchQuery, queryAnalysis);
      setPapers(sortedPapers);
      
      // Generate graph data
      if (allPapers.length > 0) {
        const graph = await getGraphData(JSON.stringify(allPapers));
        setGraphData(graph);
        
        // Select first paper by default
        if (!selectedPaper && allPapers.length > 0) {
          setSelectedPaper(allPapers[0]);
          setHighlightedPapers(new Set());
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
      
      // 에러 발생 시 빈 결과 설정
      setPapers([]);
      setGraphData(null);
      setSelectedPaper(null);
      setHighlightedPapers(new Set());
    } finally {
      setLoading(false);
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
      {/* Minimal header */}
      <div className="app-header">
        <div className="header-nav">
          <div className="logo">
            <img 
              src="/Jipyheonjeon_llama.png" 
              alt="Jipyheonjeon" 
              className="logo-icon"
              onError={(e) => {
                console.error('Logo image failed to load:', '/Jipyheonjeon_llama.png');
                e.currentTarget.style.display = 'none';
              }}
              onLoad={() => {
                console.log('Logo image loaded successfully');
              }}
            />
            <span className="brand-name">Jipyheonjeon</span>
          </div>
        </div>
      </div>

      {/* Main content - Perplexity style */}
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
                  <GraphView
                    graphData={graphData}
                    selectedPaper={selectedPaper}
                    highlightedPapers={highlightedPapers}
                    papers={papers}
                    onNodeClick={handleNodeClickWithHighlight}
                  />
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
                    <button
                      className="close-report-button"
                      onClick={() => {
                        setShowReport(false);
                        setDetailsCollapsed(false);
                        setReviewStatus('idle');
                        setReviewReport(null);
                      }}
                      title="Close report"
                    >
                      ✕
                    </button>
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
    </div>
  );
}

export default App;
