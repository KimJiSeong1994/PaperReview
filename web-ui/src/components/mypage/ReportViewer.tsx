import { useState, useRef, useEffect, useMemo, Fragment } from 'react';
import type React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { HighlightItem, ShareInfo } from '../../api/client';
import type { CitationTreeData } from './types';
import ConsensusMeter from './ConsensusMeter';

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
  // Citation Tree
  citationTreeData: CitationTreeData | null;
  citationTreeLoading: boolean;
  citationTreeError: string | null;
  onGenerateCitationTree: () => void;
  onDeleteCitationTree: () => void;
  onRenameBookmark: (title: string) => void;
  // Share
  shareInfo: ShareInfo | null;
  shareLoading: boolean;
  onCreateShare: () => void;
  onRevokeShare: () => void;
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
  citationTreeData, citationTreeLoading, citationTreeError,
  onGenerateCitationTree, onDeleteCitationTree,
  onRenameBookmark,
  shareInfo, shareLoading, onCreateShare, onRevokeShare,
}: ReportViewerProps) {
  const [activeTab, setActiveTab] = useState<'report' | 'further-reading'>('report');
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [shareCopied, setShareCopied] = useState(false);
  const [expandedCitationId, setExpandedCitationId] = useState<string | null>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const titleSavingRef = useRef(false);

  // Group and sort citation nodes: root → backward → forward, then by citations desc
  const groupedNodes = useMemo(() => {
    if (!citationTreeData) return [];
    const order: Record<string, number> = { root: 0, backward: 1, forward: 2 };
    return [...citationTreeData.nodes].sort((a, b) => {
      const diff = (order[a.direction] ?? 9) - (order[b.direction] ?? 9);
      if (diff !== 0) return diff;
      return (b.citations ?? 0) - (a.citations ?? 0);
    });
  }, [citationTreeData]);

  // Build citation context lookup: nodeId → {contexts, intents, is_influential}
  const citationContextMap = useMemo(() => {
    if (!citationTreeData) return new Map<string, { contexts: string[]; intents: string[]; is_influential: boolean }>();
    const map = new Map<string, { contexts: string[]; intents: string[]; is_influential: boolean }>();
    for (const edge of citationTreeData.edges) {
      const nodeId = citationTreeData.root_paper_ids.includes(edge.source) ? edge.target : edge.source;
      const existing = map.get(nodeId);
      const edgeContexts = edge.contexts ?? [];
      if (!existing || edgeContexts.length > existing.contexts.length) {
        map.set(nodeId, {
          contexts: edgeContexts,
          intents: edge.intents ?? [],
          is_influential: edge.is_influential ?? false,
        });
      }
    }
    return map;
  }, [citationTreeData]);

  const nodeAbstractMap = useMemo(() => {
    if (!citationTreeData) return new Map<string, string>();
    const map = new Map<string, string>();
    for (const node of citationTreeData.nodes) {
      if (node.abstract) map.set(node.id, node.abstract);
    }
    return map;
  }, [citationTreeData]);

  // Auto-focus title input when entering edit mode
  useEffect(() => {
    if (editingTitle && titleInputRef.current) {
      titleInputRef.current.focus();
      titleInputRef.current.select();
    }
  }, [editingTitle]);

  const handleTitleSave = () => {
    if (titleSavingRef.current) return;
    titleSavingRef.current = true;
    const trimmed = titleDraft.trim();
    if (trimmed && trimmed !== bookmarkDetail?.title) {
      onRenameBookmark(trimmed);
    }
    setEditingTitle(false);
    // Reset guard after current event cycle
    requestAnimationFrame(() => { titleSavingRef.current = false; });
  };

  if (!hasSelectedBookmark) {
    return (
      <div className="mypage-report-panel" role="region" aria-label="Research report">
        <div className="mypage-report-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="40" height="40" style={{ color: '#4b5563', marginBottom: '12px' }}>
            <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2z" />
          </svg>
          <p className="mypage-report-empty-title">Select a Bookmark</p>
          <p className="mypage-report-empty-subtitle">Choose a bookmark from the sidebar to view its report</p>
        </div>
      </div>
    );
  }

  if (loadingDetail) {
    return (
      <div className="mypage-report-panel" role="region" aria-label="Research report">
        <div className="mypage-loading" style={{ padding: '40px' }}>Loading...</div>
      </div>
    );
  }

  if (!bookmarkDetail) return null;

  return (
    <div className="mypage-report-panel" role="region" aria-label="Research report">
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
        {editingTitle ? (
          <input
            ref={titleInputRef}
            className="mypage-report-title-input"
            value={titleDraft}
            onChange={(e) => setTitleDraft(e.target.value)}
            onBlur={handleTitleSave}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleTitleSave();
              if (e.key === 'Escape') setEditingTitle(false);
            }}
          />
        ) : (
          <h2
            className="mypage-report-title"
            onDoubleClick={() => {
              setTitleDraft(bookmarkDetail.title);
              setEditingTitle(true);
            }}
            title="Double-click to edit title"
          >
            {bookmarkDetail.title}
          </h2>
        )}
        <div className="mypage-detail-export-btns">
          <button className="mypage-export-btn" onClick={onExportBibTeX} title="Export as BibTeX">BibTeX</button>
          {bookmarkDetail.report_markdown && (
            <button className="mypage-export-btn" onClick={onExportReport} title="Export as Markdown">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              .md
            </button>
          )}
          <button
            className={`mypage-export-btn mypage-share-btn${shareInfo ? ' active' : ''}`}
            onClick={shareInfo ? undefined : onCreateShare}
            disabled={shareLoading}
            title={shareInfo ? 'Share link active' : 'Create share link'}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
              <circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" />
              <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" /><line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
            </svg>
            {shareLoading ? '...' : 'Share'}
          </button>
        </div>
      </div>

      {/* Share panel */}
      {shareInfo && (
        <div className="mypage-share-panel">
          <div className="mypage-share-panel-row">
            <input
              className="mypage-share-url-input"
              value={`${window.location.origin}/share/${shareInfo.token}`}
              readOnly
              onClick={(e) => (e.target as HTMLInputElement).select()}
            />
            <button
              className="mypage-share-copy-btn"
              onClick={() => {
                navigator.clipboard.writeText(`${window.location.origin}/share/${shareInfo.token}`);
                setShareCopied(true);
                setTimeout(() => setShareCopied(false), 2000);
              }}
            >
              {shareCopied ? 'Copied!' : 'Copy'}
            </button>
            <button className="mypage-share-revoke-btn" onClick={onRevokeShare} title="Revoke share link">
              Revoke
            </button>
          </div>
          <div className="mypage-share-panel-meta">
            Expires {new Date(shareInfo.expires_at).toLocaleDateString()}
          </div>
        </div>
      )}

      {/* Tab bar */}
      <div className="mypage-report-tabs">
        <button
          className={`mypage-report-tab ${activeTab === 'report' ? 'active' : ''}`}
          onClick={() => setActiveTab('report')}
        >
          Report
        </button>
        <button
          className={`mypage-report-tab ${activeTab === 'further-reading' ? 'active' : ''}`}
          onClick={() => setActiveTab('further-reading')}
        >
          Further Reading
          {citationTreeData && (
            <span className="mypage-report-tab-badge">{citationTreeData.nodes.length}</span>
          )}
        </button>
      </div>

      {/* ── Report Tab ── */}
      {activeTab === 'report' && (
        <div className="mypage-report-scroll" ref={reportScrollRef}>
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
          {highlightPopover && popoverPos && (highlightPopover.hl.memo || highlightPopover.hl.implication || highlightPopover.hl.question_for_authors) && (
            <div className="mypage-hl-popover" style={{ left: popoverPos.x, top: popoverPos.y }}>
              <button className="mypage-hl-popover-close" onClick={() => setHighlightPopover(null)}>&times;</button>
              {/* Strength/Weakness + Confidence badges */}
              {(highlightPopover.hl.strength_or_weakness || highlightPopover.hl.confidence_level) && (
                <div className="mypage-hl-popover-badges">
                  {highlightPopover.hl.strength_or_weakness && (
                    <span className={`mypage-hl-badge mypage-hl-badge-${highlightPopover.hl.strength_or_weakness}`}>
                      {highlightPopover.hl.strength_or_weakness === 'strength' ? 'Strength' : 'Weakness'}
                    </span>
                  )}
                  {highlightPopover.hl.confidence_level && (
                    <span className="mypage-hl-badge mypage-hl-badge-confidence" title="Reviewer confidence level">
                      Confidence {highlightPopover.hl.confidence_level}/5
                    </span>
                  )}
                </div>
              )}
              {highlightPopover.hl.memo && <div className="mypage-hl-popover-memo">{highlightPopover.hl.memo}</div>}
              {highlightPopover.hl.question_for_authors && (
                <div className="mypage-hl-popover-question">
                  <span className="mypage-hl-popover-question-label">Question for Authors</span>
                  {highlightPopover.hl.question_for_authors}
                </div>
              )}
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
              {saveStatus === 'saved' && <span className="mypage-notes-saved">Saved!</span>}
              {saveStatus === 'error' && <span className="mypage-notes-error">Failed to save</span>}
              {userHighlights.length > 0 && (
                <span className="mypage-notes-badge">{userHighlights.length}</span>
              )}
              {userHighlights.length > 0 && (
                <button
                  className="mypage-clear-highlights-btn"
                  onClick={(e) => { e.stopPropagation(); onClearAllHighlights(); }}
                  title="Remove all highlights"
                >Clear All</button>
              )}
              <button
                className="mypage-auto-highlight-btn"
                onClick={(e) => { e.stopPropagation(); onAutoHighlight(); }}
                disabled={autoHighlighting || !bookmarkDetail?.report_markdown}
                title="Auto-highlight key findings"
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
                <ConsensusMeter highlights={userHighlights} />
                <textarea
                  className="mypage-notes-textarea"
                  value={notesText}
                  onChange={(e) => setNotesText(e.target.value)}
                  onBlur={onSaveNotes}
                  placeholder="Add your notes here..."
                  rows={4}
                />
                {userHighlights.length > 0 && (
                  <div className="mypage-highlights-list">
                    <div className="mypage-highlights-title">
                      Highlights ({userHighlights.length})
                    </div>
                    {sortedHighlights.map(hl => (
                      <div
                        key={hl.id}
                        className={`mypage-highlight-item${expandedHighlightId === hl.id ? ' expanded' : ''}`}
                        onClick={() => setExpandedHighlightId(expandedHighlightId === hl.id ? null : hl.id)}
                        style={{ cursor: (hl.memo || hl.implication || hl.question_for_authors) ? 'pointer' : undefined }}
                      >
                        <div className="mypage-highlight-item-content">
                          <mark className="mypage-highlight-item-text" style={hl.color && hl.color !== '#a5b4fc' ? { background: `${hl.color}44`, borderLeftColor: hl.color } : undefined}>
                            {hl.text.length > 100 ? hl.text.slice(0, 100) + '...' : hl.text}
                          </mark>
                          <div className="mypage-highlight-item-tags">
                            {hl.section && <span className="mypage-highlight-section-badge">{hl.section}</span>}
                            {hl.strength_or_weakness && (
                              <span className={`mypage-hl-badge-inline mypage-hl-badge-${hl.strength_or_weakness}`}>
                                {hl.strength_or_weakness === 'strength' ? 'S' : 'W'}
                              </span>
                            )}
                            {hl.confidence_level && (
                              <span className="mypage-hl-badge-inline mypage-hl-badge-confidence" title={`Confidence ${hl.confidence_level}/5`}>
                                C{hl.confidence_level}
                              </span>
                            )}
                          </div>
                          {expandedHighlightId === hl.id && (
                            <>
                              {hl.memo && <div className="mypage-highlight-item-memo">{hl.memo}</div>}
                              {hl.question_for_authors && (
                                <div className="mypage-highlight-question">
                                  <span className="mypage-highlight-question-label">Q.</span>
                                  {hl.question_for_authors}
                                </div>
                              )}
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
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Further Reading Tab ── */}
      {activeTab === 'further-reading' && (
        <div className="mypage-report-scroll">
          <div className="mypage-citation-table-container">
            {citationTreeLoading && (
              <div className="mypage-citation-table-loading">Analyzing citations...</div>
            )}
            {citationTreeError && (
              <div className="mypage-citation-table-error">{citationTreeError}</div>
            )}
            {!citationTreeData && !citationTreeLoading && (
              <div className="mypage-citation-table-empty">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="32" height="32" style={{ color: '#4b5563' }}>
                  <path d="M12 3v6m0 0l-4 4m4-4l4 4m-8 0v4m8-4v4" /><circle cx="4" cy="21" r="2" /><circle cx="12" cy="21" r="2" /><circle cx="20" cy="21" r="2" />
                </svg>
                <p>Discover related papers through citation analysis</p>
                <button
                  className="mypage-citation-generate-btn"
                  onClick={onGenerateCitationTree}
                  disabled={citationTreeLoading}
                >
                  Generate
                </button>
              </div>
            )}
            {citationTreeData && (
              <>
                <div className="mypage-citation-table-meta">
                  <span>{citationTreeData.nodes.length} Papers</span>
                  <span>{citationTreeData.edges.length} Citations</span>
                  <span>{new Date(citationTreeData.generated_at).toLocaleDateString()}</span>
                  <button
                    className="mypage-citation-delete-btn"
                    onClick={onDeleteCitationTree}
                    title="Remove all further reading data"
                  >Delete</button>
                </div>
                <table className="mypage-citation-table">
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Authors</th>
                      <th>Year</th>
                      <th>Citations</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupedNodes.map((node) => {
                      const ctx = citationContextMap.get(node.id);
                      const hasContext = (ctx?.contexts?.length ?? 0) > 0;
                      const abstract = nodeAbstractMap.get(node.id);
                      const isExpanded = expandedCitationId === node.id;
                      const isExpandable = node.direction !== 'root' && (hasContext || !!abstract);

                      return (
                        <Fragment key={node.id}>
                          <tr
                            className={`mypage-citation-row mypage-citation-${node.direction}${isExpandable ? ' mypage-citation-expandable' : ''}${isExpanded ? ' mypage-citation-expanded' : ''}`}
                            onClick={() => isExpandable && setExpandedCitationId(isExpanded ? null : node.id)}
                          >
                            <td className="mypage-citation-title-cell">
                              {node.url ? (
                                <a href={node.url} target="_blank" rel="noopener noreferrer" className="mypage-citation-link" onClick={(e) => e.stopPropagation()}>
                                  {node.title}
                                </a>
                              ) : (
                                node.title
                              )}
                              {isExpandable && (
                                <span className="mypage-citation-expand-icon">{isExpanded ? ' ▾' : ' ▸'}</span>
                              )}
                            </td>
                            <td className="mypage-citation-meta-cell">{node.authors?.slice(0, 2).join(', ')}{(node.authors?.length ?? 0) > 2 ? ' et al.' : ''}</td>
                            <td className="mypage-citation-meta-cell">{node.year || '—'}</td>
                            <td className="mypage-citation-meta-cell">
                              {node.citations ?? 0}
                              {ctx?.is_influential && <span className="mypage-citation-influential-dot" title="Influential citation" />}
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr className="mypage-citation-context-row">
                              <td colSpan={4}>
                                <div className="mypage-citation-context">
                                  {ctx?.intents && ctx.intents.length > 0 && (
                                    <div className="mypage-citation-intents">
                                      {ctx.intents.map((intent, i) => (
                                        <span key={i} className="mypage-citation-intent-badge">{intent}</span>
                                      ))}
                                      {ctx.is_influential && (
                                        <span className="mypage-citation-influential-badge">Influential</span>
                                      )}
                                    </div>
                                  )}
                                  {hasContext ? (
                                    ctx!.contexts.map((text, i) => (
                                      <p key={i} className="mypage-citation-context-text">"{text}"</p>
                                    ))
                                  ) : abstract ? (
                                    <p className="mypage-citation-context-abstract">
                                      <span className="mypage-citation-context-label">Abstract: </span>{abstract}
                                    </p>
                                  ) : null}
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </>
            )}
          </div>
        </div>
      )}

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
