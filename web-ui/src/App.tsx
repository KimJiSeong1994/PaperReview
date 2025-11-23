import { useState } from 'react';
import './App.css';
import GraphView from './components/GraphView';
import PaperList from './components/PaperList';
import DetailPanel from './components/DetailPanel';
import SearchBar from './components/SearchBar';
import { searchPapers, getGraphData } from './api/client';
import type { Paper, GraphData } from './types';

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

      setPapers(allPapers);
      
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
          <div className="centered-search">
            <div className="search-query-display">{query}</div>
            <div className="loading-indicator">
              <div className="loading-spinner"></div>
              <p>검색 중...</p>
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
