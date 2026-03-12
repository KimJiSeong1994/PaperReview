import { useState, useCallback, useRef, useEffect } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import './PaperViewerPanel.css';

// Configure pdf.js worker
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

// ── Types ──────────────────────────────────────────────────────────────

interface BookmarkPaper {
  title: string;
  authors: string[];
  year?: number | string;
  pdf_url?: string | null;
  doi?: string | null;
  url?: string | null;
  source?: string | null;
}

export interface PaperViewerPanelProps {
  bookmarkDetail: any;
  loadingDetail: boolean;
  hasSelectedBookmark: boolean;
}

// ── Helpers ────────────────────────────────────────────────────────────

const ZOOM_STEP = 0.15;
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 3.0;
const ZOOM_DEFAULT = 1.0;

function buildPdfSrc(pdfUrl: string): string {
  if (pdfUrl.includes('arxiv.org')) {
    return pdfUrl;
  }
  return `/api/pdf/proxy?url=${encodeURIComponent(pdfUrl)}`;
}

function formatAuthors(authors: string[]): string {
  if (!authors || authors.length === 0) return '';
  if (authors.length === 1) return authors[0];
  if (authors.length === 2) return authors.join(', ');
  return `${authors[0]} et al.`;
}

function paperExternalUrl(paper: BookmarkPaper): string | null {
  if (paper.doi) return `https://doi.org/${paper.doi}`;
  if (paper.url) return paper.url;
  return null;
}

// ── Icons (inline SVGs, no external dependency) ───────────────────────

function IconFilePdf() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
      <path d="M4 0a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V5.5L9.5 0H4zm5.5 1.5v3h3L9.5 1.5zM4.5 8.5h.75c.69 0 1.25.56 1.25 1.25S5.94 11 5.25 11H4.5V8.5zm.75 1.5h-.25v-.5h.25c.138 0 .25.112.25.25S5.388 10 5.25 10zM7 8.5h.9c.33 0 .6.27.6.6v1.3c0 .33-.27.6-.6.6H7V8.5zm.5.5v1h.4a.1.1 0 0 0 .1-.1V9.1a.1.1 0 0 0-.1-.1H7.5zm1.5 0h1.25v.5H9.5v.25h.75V10H9.5V11H9V8.5h1z" />
    </svg>
  );
}

function IconFileText() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  );
}

function IconChevronLeft() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="15 18 9 12 15 6" />
    </svg>
  );
}

function IconChevronRight() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

function IconZoomIn() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
      <line x1="11" y1="8" x2="11" y2="14" />
      <line x1="8" y1="11" x2="14" y2="11" />
    </svg>
  );
}

function IconZoomOut() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
      <line x1="8" y1="11" x2="14" y2="11" />
    </svg>
  );
}

function IconExternalLink() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  );
}

function IconAlertCircle() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  );
}

function IconFitWidth() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 9V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v4" />
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <line x1="7" y1="12" x2="17" y2="12" />
      <polyline points="10 9 7 12 10 15" />
      <polyline points="14 9 17 12 14 15" />
    </svg>
  );
}

// ── Component ──────────────────────────────────────────────────────────

export default function PaperViewerPanel({
  bookmarkDetail,
  loadingDetail,
  hasSelectedBookmark,
}: PaperViewerPanelProps) {
  const papers: BookmarkPaper[] = bookmarkDetail?.papers ?? [];

  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [numPages, setNumPages] = useState<number | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInputValue, setPageInputValue] = useState('1');
  const [zoom, setZoom] = useState(ZOOM_DEFAULT);
  const [fitWidth, setFitWidth] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);

  const docScrollRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState<number>(600);

  // Reset viewer state whenever bookmark changes
  useEffect(() => {
    setSelectedIndex(null);
    setNumPages(null);
    setCurrentPage(1);
    setPageInputValue('1');
    setZoom(ZOOM_DEFAULT);
    setFitWidth(false);
    setPdfError(null);
    setPdfLoading(false);
  }, [bookmarkDetail]);

  // Track container width for fit-width mode
  useEffect(() => {
    const el = docScrollRef.current;
    if (!el) return;
    const obs = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        // Subtract padding (2 * 16px)
        setContainerWidth(Math.max(300, entry.contentRect.width - 32));
      }
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const selectedPaper = selectedIndex !== null ? papers[selectedIndex] ?? null : null;

  const pdfSrc = selectedPaper?.pdf_url ? buildPdfSrc(selectedPaper.pdf_url) : null;

  const handleSelectPaper = useCallback((index: number) => {
    setSelectedIndex(index);
    setNumPages(null);
    setCurrentPage(1);
    setPageInputValue('1');
    setPdfError(null);
    setPdfLoading(true);
  }, []);

  const handleDocumentLoadSuccess = useCallback(({ numPages: n }: { numPages: number }) => {
    setNumPages(n);
    setPdfLoading(false);
    setPdfError(null);
  }, []);

  const handleDocumentLoadError = useCallback((err: Error) => {
    setPdfLoading(false);
    setPdfError(err.message || 'Failed to load PDF.');
  }, []);

  const goToPrevPage = useCallback(() => {
    setCurrentPage((p) => {
      const next = Math.max(1, p - 1);
      setPageInputValue(String(next));
      return next;
    });
  }, []);

  const goToNextPage = useCallback(() => {
    setCurrentPage((p) => {
      const next = Math.min(numPages ?? p, p + 1);
      setPageInputValue(String(next));
      return next;
    });
  }, [numPages]);

  const handlePageInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setPageInputValue(e.target.value);
  }, []);

  const handlePageInputCommit = useCallback(() => {
    const parsed = parseInt(pageInputValue, 10);
    if (!isNaN(parsed) && numPages !== null) {
      const clamped = Math.min(numPages, Math.max(1, parsed));
      setCurrentPage(clamped);
      setPageInputValue(String(clamped));
    } else {
      setPageInputValue(String(currentPage));
    }
  }, [pageInputValue, numPages, currentPage]);

  const handlePageInputKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') handlePageInputCommit();
      if (e.key === 'Escape') setPageInputValue(String(currentPage));
    },
    [handlePageInputCommit, currentPage],
  );

  const handleZoomIn = useCallback(() => {
    setFitWidth(false);
    setZoom((z) => Math.min(ZOOM_MAX, parseFloat((z + ZOOM_STEP).toFixed(2))));
  }, []);

  const handleZoomOut = useCallback(() => {
    setFitWidth(false);
    setZoom((z) => Math.max(ZOOM_MIN, parseFloat((z - ZOOM_STEP).toFixed(2))));
  }, []);

  const handleFitWidth = useCallback(() => {
    setFitWidth((fw) => !fw);
  }, []);

  const effectiveWidth = fitWidth ? containerWidth : undefined;
  const effectiveScale = fitWidth ? undefined : zoom;

  // ── Render ─────────────────────────────────────────────────────────

  const renderPdfArea = () => {
    if (!selectedPaper) {
      return (
        <div className="paper-viewer-placeholder">
          <span className="paper-viewer-placeholder-icon">
            <IconFileText />
          </span>
          <span>Select a paper to view</span>
        </div>
      );
    }

    if (!pdfSrc) {
      const externalUrl = paperExternalUrl(selectedPaper);
      return (
        <div className="paper-viewer-no-pdf">
          <span className="paper-viewer-no-pdf-icon">
            <IconAlertCircle />
          </span>
          <div>
            <div className="paper-viewer-no-pdf-title">PDF not available for this paper</div>
            <div>No PDF URL is associated with this paper.</div>
          </div>
          {externalUrl && (
            <a
              className="paper-viewer-no-pdf-link"
              href={externalUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              <IconExternalLink />
              Open paper page
            </a>
          )}
        </div>
      );
    }

    return (
      <>
        <div className="paper-viewer-doc-scroll" ref={docScrollRef}>
          <Document
            file={pdfSrc}
            onLoadSuccess={handleDocumentLoadSuccess}
            onLoadError={handleDocumentLoadError}
            loading={
              <div className="paper-viewer-loading">
                <div className="paper-viewer-spinner" />
                <span>Loading PDF...</span>
              </div>
            }
            error={
              <div className="paper-viewer-error">
                <span className="paper-viewer-error-icon">
                  <IconAlertCircle />
                </span>
                <span>{pdfError ?? 'Failed to load PDF.'}</span>
                <button
                  className="paper-viewer-error-retry"
                  onClick={() => {
                    setPdfError(null);
                    setPdfLoading(true);
                    // Force re-mount by toggling a key via re-select
                    handleSelectPaper(selectedIndex!);
                  }}
                >
                  Retry
                </button>
              </div>
            }
          >
            {numPages !== null && (
              <Page
                pageNumber={currentPage}
                scale={effectiveScale}
                width={effectiveWidth}
                renderTextLayer={true}
                renderAnnotationLayer={true}
              />
            )}
          </Document>

          {pdfLoading && numPages === null && (
            <div className="paper-viewer-loading">
              <div className="paper-viewer-spinner" />
              <span>Loading PDF...</span>
            </div>
          )}
        </div>

        <div className="paper-viewer-toolbar">
          {/* Navigation */}
          <div className="paper-viewer-toolbar-group">
            <button
              className="paper-viewer-icon-btn"
              title="Previous page"
              onClick={goToPrevPage}
              disabled={currentPage <= 1}
            >
              <IconChevronLeft />
            </button>
            <div className="paper-viewer-page-info">
              <input
                className="paper-viewer-page-input"
                type="text"
                inputMode="numeric"
                value={pageInputValue}
                onChange={handlePageInputChange}
                onBlur={handlePageInputCommit}
                onKeyDown={handlePageInputKeyDown}
                aria-label="Page number"
              />
              <span className="paper-viewer-page-total">
                / {numPages ?? '—'}
              </span>
            </div>
            <button
              className="paper-viewer-icon-btn"
              title="Next page"
              onClick={goToNextPage}
              disabled={numPages === null || currentPage >= numPages}
            >
              <IconChevronRight />
            </button>
          </div>

          <div className="paper-viewer-toolbar-sep" />

          {/* Zoom */}
          <div className="paper-viewer-toolbar-group">
            <button
              className="paper-viewer-icon-btn"
              title="Zoom out"
              onClick={handleZoomOut}
              disabled={fitWidth || zoom <= ZOOM_MIN}
            >
              <IconZoomOut />
            </button>
            <span className="paper-viewer-zoom-label">
              {fitWidth ? 'fit' : `${Math.round(zoom * 100)}%`}
            </span>
            <button
              className="paper-viewer-icon-btn"
              title="Zoom in"
              onClick={handleZoomIn}
              disabled={fitWidth || zoom >= ZOOM_MAX}
            >
              <IconZoomIn />
            </button>
          </div>

          <div className="paper-viewer-toolbar-sep" />

          {/* Fit width */}
          <button
            className={`paper-viewer-fit-btn${fitWidth ? ' active' : ''}`}
            title="Fit to width"
            onClick={handleFitWidth}
          >
            <IconFitWidth />
            Fit width
          </button>

          <div className="paper-viewer-toolbar-spacer" />
        </div>
      </>
    );
  };

  return (
    <div className="paper-viewer-panel">
      {/* ── Left: Paper list ── */}
      <div className="paper-viewer-list">
        <div className="paper-viewer-list-header">Papers</div>

        <div className="paper-viewer-list-scroll">
          {loadingDetail ? (
            <div className="paper-viewer-list-loading">Loading papers...</div>
          ) : !hasSelectedBookmark ? (
            <div className="paper-viewer-list-empty">No bookmark selected</div>
          ) : papers.length === 0 ? (
            <div className="paper-viewer-list-empty">No papers in this bookmark</div>
          ) : (
            papers.map((paper, index) => {
              const hasPdf = Boolean(paper.pdf_url);
              const isSelected = selectedIndex === index;
              return (
                <div
                  key={index}
                  className={`paper-viewer-item${isSelected ? ' selected' : ''}`}
                  onClick={() => handleSelectPaper(index)}
                  title={paper.title}
                >
                  {hasPdf && (
                    <span className="paper-viewer-item-pdf-icon" title="PDF available">
                      <IconFilePdf />
                    </span>
                  )}
                  <div className="paper-viewer-item-content">
                    <div className="paper-viewer-item-title">{paper.title}</div>
                    <div className="paper-viewer-item-meta">
                      {formatAuthors(paper.authors)}
                      {paper.year ? ` · ${paper.year}` : ''}
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* ── Right: PDF viewer ── */}
      <div className="paper-viewer-pdf-area">{renderPdfArea()}</div>
    </div>
  );
}
