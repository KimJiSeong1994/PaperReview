import { lazy, Suspense, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import DetailPanel from '../DetailPanel';
import PaperList from '../PaperList';
import { rankedNeighbors } from '../graph/graphPresentation';
import { openPaperViewer, viewerHrefForPaper } from '../../utils/blogPaperReference';
import type { GraphData, Paper, SearchResultsBlock } from '../../types';
import type { CompletedReview } from './ReviewBlock';

const GraphView = lazy(() => import('../GraphView'));

export type ArtifactTab = 'graph' | 'list' | 'review';

interface ArtifactPanelProps {
  search: SearchResultsBlock | null;
  graph: GraphData | null;
  /** The turn that owns this search is still streaming, so its graph may yet arrive. */
  graphPending: boolean;
  /** Report for the 리뷰 tab; the tab is shown only when there is one. */
  review: CompletedReview | null;
  tab: ArtifactTab;
  onTab: (tab: ArtifactTab) => void;
  selectedPaper: Paper | null;
  onSelect: (paper: Paper | null) => void;
  onClose: () => void;
}

const keyOf = (paper: Paper): string => String(paper.result_key ?? paper.doc_id);

/** Right-hand results surface: relation graph or ranked list, with the selected paper's detail below. */
function ArtifactPanel({ search, graph, graphPending, review, tab, onTab, selectedPaper, onSelect, onClose }: ArtifactPanelProps) {
  const papers = useMemo(() => search?.papers ?? [], [search]);
  const selectedKey = selectedPaper ? keyOf(selectedPaper) : null;
  const neighbors = useMemo(() => rankedNeighbors(graph, selectedKey, 5), [graph, selectedKey]);
  const highlightedPapers = useMemo(() => new Set(neighbors.map(neighbor => neighbor.id)), [neighbors]);
  const relatedPapers = useMemo(() => {
    const byKey = new Map(papers.map(paper => [keyOf(paper), paper] as const));
    return neighbors.flatMap(neighbor => {
      const paper = byKey.get(neighbor.id);
      return paper ? [{ paper, weight: neighbor.weight, sharedTerms: neighbor.sharedTerms }] : [];
    });
  }, [neighbors, papers]);

  return (
    <aside className="conv-artifact" id="conv-artifact" aria-label="검색 결과 아티팩트">
      <div className="conv-artifact-bar">
        <div className="conv-tabs" role="tablist" aria-label="보기">
          {(review ? ['graph', 'list', 'review'] as const : ['graph', 'list'] as const).map(name => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={tab === name}
              className={`conv-tab${tab === name ? ' is-active' : ''}`}
              onClick={() => onTab(name)}
            >
              {name === 'graph' ? '그래프' : name === 'review' ? '리뷰' : `목록${search ? ` ${papers.length}` : ''}`}
            </button>
          ))}
        </div>
        {tab === 'review' && review ? (
          <span className="conv-artifact-query">{review.title}</span>
        ) : search && (
          <span className="conv-artifact-query" title={search.executed_query || undefined}>{search.query}</span>
        )}
        <button type="button" className="conv-icon-btn" aria-label="아티팩트 닫기" onClick={onClose}>
          <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16">
            <path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <div className="conv-artifact-body" role="tabpanel">
        {tab === 'review' && review ? (
          <div className="conv-report">
            {review.stats && review.stats.total_claims > 0 && (
              <p className="conv-report-stats">
                근거 확인 {Math.round(review.stats.verification_rate * 100)}% · 주장 {review.stats.total_claims}개 중
                확인 {review.stats.verified} · 부분 {review.stats.partially_verified} · 미확인 {review.stats.unverified}
                {review.stats.contradicted > 0 && ` · 반박 ${review.stats.contradicted}`}
              </p>
            )}
            <div className="conv-markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{review.markdown}</ReactMarkdown>
            </div>
          </div>
        ) : !search ? (
          <p className="conv-artifact-empty">검색 결과가 생기면 관계 그래프와 목록이 여기에 열립니다.</p>
        ) : tab === 'graph' ? (
          graph ? (
            <Suspense fallback={<p className="conv-artifact-empty">그래프를 불러오는 중…</p>}>
              <GraphView
                key={search.query_hash}
                graphData={graph}
                selectedPaper={selectedPaper}
                highlightedPapers={highlightedPapers}
                papers={papers}
                onNodeClick={onSelect}
              />
            </Suspense>
          ) : graphPending ? (
            <p className="conv-artifact-empty">관계 그래프를 그리는 중이에요. 목록은 먼저 볼 수 있어요.</p>
          ) : (
            <div className="conv-artifact-empty">
              <p>이 검색은 관계 그래프를 만들지 못했어요.</p>
              <button type="button" className="conv-results-more" onClick={() => onTab('list')}>목록에서 보기 →</button>
            </div>
          )
        ) : (
          <PaperList
            papers={papers}
            selectedPaper={selectedPaper}
            onSelect={onSelect}
            highlightedPapers={highlightedPapers}
          />
        )}
      </div>

      {selectedPaper && tab !== 'review' && (
        <div className="conv-artifact-detail">
          <button type="button" className="conv-icon-btn conv-detail-close" aria-label="논문 정보 닫기" onClick={() => onSelect(null)}>
            <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14">
              <path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
          <DetailPanel
            paper={selectedPaper}
            relatedPapers={relatedPapers}
            edgeMeta={graph?.meta}
            onSelectRelated={onSelect}
            onViewPaper={paper => openPaperViewer(viewerHrefForPaper(paper, 'search'))}
          />
        </div>
      )}
    </aside>
  );
}

export default ArtifactPanel;
