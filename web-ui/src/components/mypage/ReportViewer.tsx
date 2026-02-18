import type React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { HighlightItem } from '../../api/client';

export interface ReportViewerProps {
  bookmarkDetail: any;
  loadingDetail: boolean;
  hasSelectedBookmark: boolean;
  reportScrollRef: React.RefObject<HTMLDivElement | null>;
  // Highlight evidence
  highlightTerms: string[];
  setHighlightTerms: (terms: string[]) => void;
  highlightChildren: (children: React.ReactNode) => React.ReactNode;
  // User highlights
  userHighlights: HighlightItem[];
  sortedHighlights: HighlightItem[];
  applyUserHighlights: (children: React.ReactNode) => React.ReactNode;
  expandedHighlightId: string | null;
  setExpandedHighlightId: (id: string | null) => void;
  highlightPopover: { hl: HighlightItem } | null;
  popoverPos: { x: number; y: number } | null;
  setHighlightPopover: (v: null) => void;
  // Notes
  notesText: string;
  setNotesText: (v: string) => void;
  notesSaving: boolean;
  notesCollapsed: boolean;
  setNotesCollapsed: (v: boolean) => void;
  saveStatus: 'idle' | 'saved' | 'error';
  autoHighlighting: boolean;
  onSaveNotes: () => void;
  onAutoHighlight: () => void;
  onClearAllHighlights: () => void;
  onRemoveHighlight: (id: string) => void;
  // Papers
  papersCollapsed: boolean;
  setPapersCollapsed: (v: boolean) => void;
  // Export
  onExportBibTeX: () => void;
  onExportReport: () => void;
  // Selection toolbar
  selectionToolbar: { x: number; y: number; text: string } | null;
  memoMode: boolean;
  memoInput: string;
  setMemoInput: (v: string) => void;
  onAddHighlight: () => void;
  onStartMemo: () => void;
  onSaveMemo: () => void;
  onCancelMemo: () => void;
}

export default function ReportViewer({
  bookmarkDetail, loadingDetail, hasSelectedBookmark,
  reportScrollRef,
  highlightTerms, setHighlightTerms, highlightChildren,
  userHighlights, sortedHighlights, applyUserHighlights,
  expandedHighlightId, setExpandedHighlightId,
  highlightPopover, popoverPos, setHighlightPopover,
  notesText, setNotesText, notesSaving, notesCollapsed, setNotesCollapsed,
  saveStatus, autoHighlighting,
  onSaveNotes, onAutoHighlight, onClearAllHighlights, onRemoveHighlight,
  papersCollapsed, setPapersCollapsed,
  onExportBibTeX, onExportReport,
  selectionToolbar, memoMode, memoInput, setMemoInput,
  onAddHighlight, onStartMemo, onSaveMemo, onCancelMemo,
}: ReportViewerProps) {
  if (!hasSelectedBookmark) {
    return (
      <div className="mypage-report-panel" role="region" aria-label="Research report">
        <div className="mypage-report-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="40" height="40" style={{ color: '#4b5563', marginBottom: '12px' }}>
            <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2z" />
          </svg>
          <p className="mypage-report-empty-title">Select a bookmark</p>
          <p className="mypage-report-empty-subtitle">Click a bookmark on the left to view its report and papers</p>
        </div>
      </div>
    );
  }

  if (loadingDetail) {
    return (
      <div className="mypage-report-panel" role="region" aria-label="Research report">
        <div className="mypage-loading" style={{ padding: '40px' }}>Loading detail...</div>
      </div>
    );
  }

  if (!bookmarkDetail) return null;

  return (
    <div className="mypage-report-panel" role="region" aria-label="Research report">
      <div className="mypage-report-scroll" ref={reportScrollRef}>
        {/* Highlight indicator */}
        {highlightTerms.length > 0 && (
          <div className="mypage-highlight-bar">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
              <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <span>Evidence highlighted</span>
            <button className="mypage-highlight-clear" onClick={() => setHighlightTerms([])}>Clear</button>
          </div>
        )}

        {/* Header */}
        <div className="mypage-report-header">
          <h2 className="mypage-report-title">{bookmarkDetail.title}</h2>
          <div className="mypage-detail-export-btns">
            <button className="mypage-export-btn" onClick={onExportBibTeX} title="Export BibTeX">BibTeX</button>
            {bookmarkDetail.report_markdown && (
              <button className="mypage-export-btn" onClick={onExportReport} title="Download Report">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                .md
              </button>
            )}
          </div>
        </div>

        {/* Papers list */}
        {bookmarkDetail.papers && bookmarkDetail.papers.length > 0 && (
          <div className={`mypage-papers-section ${papersCollapsed ? 'collapsed' : ''}`}>
            <div className="mypage-papers-header" onClick={() => setPapersCollapsed(!papersCollapsed)}>
              <svg className="mypage-papers-chevron" viewBox="0 0 16 16" fill="currentColor" width="10" height="10">
                <path d="M6 4l4 4-4 4z" />
              </svg>
              <span>Papers ({bookmarkDetail.papers.length})</span>
            </div>
            {!papersCollapsed && (
              <div className="mypage-detail-papers">
                {bookmarkDetail.papers.map((p: any, i: number) => (
                  <div key={i} className="mypage-detail-paper">
                    <span className="mypage-detail-paper-title">{p.title}</span>
                    <span className="mypage-detail-paper-meta">
                      {p.authors?.slice(0, 2).join(', ')}{p.authors?.length > 2 ? ' et al.' : ''} {p.year && `(${p.year})`}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Report markdown */}
        {bookmarkDetail.report_markdown && (
          <div className="mypage-report-section">
            <h3 className="mypage-report-section-title">Report</h3>
            <div className="mypage-report-content">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={(highlightTerms.length > 0 || userHighlights.length > 0) ? {
                  p: ({ children }) => {
                    let c: React.ReactNode = children;
                    if (userHighlights.length > 0) c = applyUserHighlights(c);
                    if (highlightTerms.length > 0) c = highlightChildren(c);
                    return <p>{c}</p>;
                  },
                  li: ({ children }) => {
                    let c: React.ReactNode = children;
                    if (userHighlights.length > 0) c = applyUserHighlights(c);
                    if (highlightTerms.length > 0) c = highlightChildren(c);
                    return <li>{c}</li>;
                  },
                  td: ({ children }) => {
                    let c: React.ReactNode = children;
                    if (userHighlights.length > 0) c = applyUserHighlights(c);
                    if (highlightTerms.length > 0) c = highlightChildren(c);
                    return <td>{c}</td>;
                  },
                } : undefined}
              >
                {bookmarkDetail.report_markdown}
              </ReactMarkdown>
            </div>
          </div>
        )}

        {/* Highlight Popover */}
        {highlightPopover && popoverPos && (highlightPopover.hl.memo || highlightPopover.hl.implication) && (
          <div className="mypage-hl-popover" style={{ left: popoverPos.x, top: popoverPos.y }}>
            <button className="mypage-hl-popover-close" onClick={() => setHighlightPopover(null)}>&times;</button>
            {highlightPopover.hl.memo && <div className="mypage-hl-popover-memo">{highlightPopover.hl.memo}</div>}
            {highlightPopover.hl.implication && (
              <div className="mypage-hl-popover-implication">
                <span className="mypage-hl-popover-implication-label">Implication</span>
                {highlightPopover.hl.implication}
              </div>
            )}
          </div>
        )}

        {/* Notes & Highlights */}
        <div className={`mypage-notes-section ${notesCollapsed ? 'collapsed' : ''}`} role="region" aria-label="Notes and highlights">
          <div className="mypage-notes-header" onClick={() => setNotesCollapsed(!notesCollapsed)} role="button" aria-expanded={!notesCollapsed} tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setNotesCollapsed(!notesCollapsed); } }}>
            <svg className="mypage-notes-chevron" viewBox="0 0 16 16" fill="currentColor" width="10" height="10">
              <path d="M6 4l4 4-4 4z" />
            </svg>
            <span>Notes & Highlights</span>
            {notesSaving && <span className="mypage-notes-saving">Saving...</span>}
            {saveStatus === 'saved' && <span className="mypage-notes-saved">Saved</span>}
            {saveStatus === 'error' && <span className="mypage-notes-error">Save failed</span>}
            {userHighlights.length > 0 && (
              <span className="mypage-notes-badge">{userHighlights.length}</span>
            )}
            {userHighlights.length > 0 && (
              <button
                className="mypage-clear-highlights-btn"
                onClick={(e) => { e.stopPropagation(); onClearAllHighlights(); }}
                title="하이라이트 전체 삭제"
              >Clear</button>
            )}
            <button
              className="mypage-auto-highlight-btn"
              onClick={(e) => { e.stopPropagation(); onAutoHighlight(); }}
              disabled={autoHighlighting || !bookmarkDetail?.report_markdown}
              title="LLM 기반 자동 하이라이트"
            >
              {autoHighlighting ? (
                <>
                  <svg className="mypage-auto-highlight-spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                    <path d="M12 2v4m0 12v4m-7.07-2.93l2.83-2.83m8.48-8.48l2.83-2.83M2 12h4m12 0h4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83" />
                  </svg>
                  Analyzing...
                </>
              ) : (
                <>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                    <path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                  Auto
                </>
              )}
            </button>
          </div>
          {!notesCollapsed && (
            <div className="mypage-notes-body">
              <textarea
                className="mypage-notes-textarea"
                value={notesText}
                onChange={(e) => setNotesText(e.target.value)}
                onBlur={onSaveNotes}
                placeholder="Write your notes here (Markdown supported)..."
                rows={4}
              />
              {userHighlights.length > 0 && (
                <div className="mypage-highlights-list">
                  <div className="mypage-highlights-title">
                    Highlights ({userHighlights.length})
                  </div>
                  {sortedHighlights.map(hl => {
                    return (
                      <div
                        key={hl.id}
                        className={`mypage-highlight-item${expandedHighlightId === hl.id ? ' expanded' : ''}`}
                        onClick={() => setExpandedHighlightId(expandedHighlightId === hl.id ? null : hl.id)}
                        style={{ cursor: (hl.memo || hl.implication) ? 'pointer' : undefined }}
                      >
                        <div className="mypage-highlight-item-content">
                          <mark className="mypage-highlight-item-text" style={hl.color && hl.color !== '#a5b4fc' ? { background: `${hl.color}44`, borderLeftColor: hl.color } : undefined}>
                            {hl.text.length > 100 ? hl.text.slice(0, 100) + '...' : hl.text}
                          </mark>
                          {hl.section && <span className="mypage-highlight-section-badge">{hl.section}</span>}
                          {expandedHighlightId === hl.id && (
                            <>
                              {hl.memo && <div className="mypage-highlight-item-memo">{hl.memo}</div>}
                              {hl.implication && (
                                <div className="mypage-highlight-implication">
                                  <span className="mypage-highlight-implication-label">Implication</span>
                                  {hl.implication}
                                </div>
                              )}
                            </>
                          )}
                        </div>
                        <button className="mypage-highlight-remove" onClick={(e) => { e.stopPropagation(); onRemoveHighlight(hl.id); }} title="Remove">&#x2715;</button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Selection toolbar */}
      {selectionToolbar && (
        <div
          className={`mypage-selection-toolbar ${memoMode ? 'memo-mode' : ''}`}
          style={{ left: selectionToolbar.x, top: selectionToolbar.y }}
        >
          {memoMode ? (
            <div className="mypage-memo-form">
              <div className="mypage-memo-preview">
                {selectionToolbar.text.length > 60 ? selectionToolbar.text.slice(0, 60) + '...' : selectionToolbar.text}
              </div>
              <input
                className="mypage-memo-input"
                value={memoInput}
                onChange={(e) => setMemoInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') onSaveMemo();
                  if (e.key === 'Escape') onCancelMemo();
                }}
                placeholder="Write a memo..."
                autoFocus
              />
              <div className="mypage-memo-actions">
                <button className="mypage-memo-save-btn" onClick={onSaveMemo}>Save</button>
                <button className="mypage-memo-cancel-btn" onClick={onCancelMemo}>Cancel</button>
              </div>
            </div>
          ) : (
            <>
              <button className="mypage-selection-toolbar-btn" onClick={onAddHighlight} aria-label="Highlight selected text">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                  <path d="M12 20h9" /><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                </svg>
                Highlight
              </button>
              <div className="mypage-selection-toolbar-divider" />
              <button className="mypage-selection-toolbar-btn" onClick={onStartMemo} aria-label="Add memo to selection">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
                Memo
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
