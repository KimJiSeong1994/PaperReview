import { lazy, Suspense, useMemo } from 'react';
import DetailPanel from '../DetailPanel';
import PaperList from '../PaperList';
import { rankedNeighbors } from '../graph/graphPresentation';
import { openPaperViewer, viewerHrefForPaper } from '../../utils/blogPaperReference';
import LazyLoadErrorBoundary from '../LazyLoadErrorBoundary';
import type { GraphData, Paper, PaperPdfBlock, PdfHighlightsBlock, SearchResultsBlock } from '../../types';
import ReviewTab from './ReviewTab';

const GraphView = lazy(() => import('../GraphView'));
// The /paper-viewer route's viewer: same pdf.js core, proxy and highlight overlay.
const PaperViewerPanel = lazy(() => import('../mypage/PaperViewerPanel'));

export type ArtifactTab = 'graph' | 'list' | 'review' | 'pdf';

interface ArtifactPanelProps {
  search: SearchResultsBlock | null;
  graph: GraphData | null;
  /** The turn that owns this search is still streaming, so its graph may yet arrive. */
  graphPending: boolean;
  /** Session for the 리뷰 tab (report, verification, poster); the tab shows only with one. */
  review: { sessionId: string; title: string } | null;
  /** Paper for the PDF tab (with highlights when the tool found some); the tab shows only with one. */
  pdf: PaperPdfBlock | PdfHighlightsBlock | null;
  /** Remounts the viewer when another turn's paper or highlights are shown. */
  pdfKey: string;
  tab: ArtifactTab;
  onTab: (tab: ArtifactTab) => void;
  selectedPaper: Paper | null;
  onSelect: (paper: Paper | null) => void;
  onClose: () => void;
}

const keyOf = (paper: Paper): string => String(paper.result_key ?? paper.doc_id);
const TAB_LABEL: Partial<Record<ArtifactTab, string>> = { graph: '그래프', review: '리뷰', pdf: 'PDF' };

/** Right-hand results surface: relation graph or ranked list, with the selected paper's detail below. */
function ArtifactPanel({ search, graph, graphPending, review, pdf, pdfKey, tab, onTab, selectedPaper, onSelect, onClose }: ArtifactPanelProps) {
  const papers = useMemo(() => search?.papers ?? [], [search]);
  const tabs: ArtifactTab[] = ['graph', 'list', ...(review ? ['review' as const] : []), ...(pdf ? ['pdf' as const] : [])];
  // The viewer resets whenever bookmarkDetail changes identity, so build it once per paper.
  const pdfDetail = useMemo(() => (pdf ? {
    papers: [{ title: pdf.paper_title, authors: pdf.authors ?? [], year: pdf.year ?? undefined, pdf_url: pdf.pdf_url ?? undefined }],
  } : null), [pdf]);
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
          {tabs.map(name => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={tab === name}
              className={`conv-tab${tab === name ? ' is-active' : ''}`}
              onClick={() => onTab(name)}
            >
              {TAB_LABEL[name] ?? `목록${search ? ` ${papers.length}` : ''}`}
            </button>
          ))}
        </div>
        {tab === 'pdf' && pdf ? (
          <span className="conv-artifact-query">{pdf.paper_title}</span>
        ) : tab === 'review' && review ? (
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
        {tab === 'pdf' && pdf ? (
          <div className="conv-pdf">
            <div className="conv-pdf-bar">
              {'highlights' in pdf && <span className="conv-artifact-query">하이라이트 {pdf.highlights.length}개</span>}
              <a className="conv-results-more" href={pdf.viewer_url} target="_blank" rel="noopener noreferrer">새 창에서 열기 ↗</a>
            </div>
            <LazyLoadErrorBoundary>
              <Suspense fallback={<p className="conv-artifact-empty">뷰어 불러오는 중…</p>}>
                <PaperViewerPanel
                  key={pdfKey}
                  bookmarkDetail={pdfDetail}
                  loadingDetail={false}
                  hasSelectedBookmark
                  autoSelectFirst
                  highlights={'highlights' in pdf ? pdf.highlights : undefined}
                />
              </Suspense>
            </LazyLoadErrorBoundary>
          </div>
        ) : tab === 'review' && review ? (
          <ReviewTab key={review.sessionId} sessionId={review.sessionId} title={review.title} />
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

      {selectedPaper && (tab === 'graph' || tab === 'list') && (
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
