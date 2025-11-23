import { useState } from 'react';
import './App.css';
import GraphView from './components/GraphView';
import PaperList from './components/PaperList';
import DetailPanel from './components/DetailPanel';
import SearchBar from './components/SearchBar';
import { searchPapers, getGraphData } from './api/client';
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
          <div className="header-actions">
            <button className="nav-btn">Settings</button>
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
              <SearchBar onSearch={handleSearch} loading={loading} />
            </div>
            
            <div className="main-container">
              <div className="left-panel">
                <div className="pane-title">Prior & Related Works</div>
                <PaperList
                  papers={papers}
                  selectedPaper={selectedPaper}
                  onSelect={handlePaperSelect}
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

              <div className="right-panel">
                <div className="pane-title">Details</div>
                {selectedPaper ? (
                  <DetailPanel paper={selectedPaper} />
                ) : (
                  <div className="no-selection">논문을 선택하세요</div>
                )}
              </div>
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
      </div>
    </div>
  );
}

export default App;
