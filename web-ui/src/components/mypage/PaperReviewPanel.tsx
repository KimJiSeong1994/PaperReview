import { useState, useMemo, useRef, useCallback, cloneElement, isValidElement, lazy, Suspense } from 'react';
import ReactMarkdown from 'react-markdown';
import type { PaperReview, HighlightItem } from '../../api/client';
import './PaperReviewPanel.css';
const Plot = lazy(() => import('../../PlotlyChart'));

interface PaperReviewPanelProps {
  review: PaperReview | null;
  loading: boolean;
  error: string | null;
  highlights: HighlightItem[];
  activeTab: 'review' | 'highlights';
  highlightFilter: string | null;
  onTabChange: (tab: 'review' | 'highlights') => void;
  onFilterChange: (category: string | null) => void;
  onClose: () => void;
  onDelete?: () => void;
  onReReview?: () => void;
  onRemoveHighlight?: (hlId: string) => void;
  onAutoHighlight?: () => void;
  autoHighlighting?: boolean;
}

const CATEGORY_LABELS: Record<string, string> = {
  finding: 'Finding',
  evidence: 'Evidence',
  contribution: 'Contribution',
  methodology: 'Methodology',
  insight: 'Insight',
  reproducibility: 'Reproducibility',
  limitation: 'Limitation',
  gap: 'Gap',
  assumption: 'Assumption',
};

const CATEGORY_COLORS: Record<string, string> = {
  finding: '#a5b4fc',
  evidence: '#a5b4fc',
  contribution: '#a5b4fc',
  methodology: '#93c5fd',
  insight: '#93c5fd',
  reproducibility: '#93c5fd',
  limitation: '#fda4af',
  gap: '#fda4af',
  assumption: '#fda4af',
};

function ScoreBadge({ score, label }: { score: number; label: string }) {
  const color = score >= 8 ? '#4ade80' : score >= 6 ? '#a5b4fc' : score >= 4 ? '#fbbf24' : '#f87171';
  return (
    <div className="pr-score-badge" style={{ borderColor: `${color}44`, background: `${color}11` }}>
      <span className="pr-score-value" style={{ color }}>{score}</span>
      <span className="pr-score-label">{label}</span>
    </div>
  );
}

function MethodologyBar({ label, value }: { label: string; value: number }) {
  const pct = (value / 5) * 100;
  const color = value >= 4 ? '#4ade80' : value >= 3 ? '#a5b4fc' : value >= 2 ? '#fbbf24' : '#f87171';
  return (
    <div className="pr-method-bar">
      <span className="pr-method-label">{label}</span>
      <div className="pr-method-track">
        <div className="pr-method-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="pr-method-value" style={{ color }}>{value}/5</span>
    </div>
  );
}

function MethodologyRadar({ assessment, score, confidence }: { assessment: { rigor: number; novelty: number; reproducibility: number }; score: number; confidence: number }) {
  const data = [{
    type: 'scatterpolar' as const,
    r: [assessment.rigor, assessment.novelty, assessment.reproducibility, Math.min(5, score / 2), confidence],
    theta: ['Rigor', 'Novelty', 'Reproducibility', 'Overall', 'Confidence'],
    fill: 'toself' as const,
    fillcolor: 'rgba(165,180,252,0.15)',
    line: { color: '#a5b4fc', width: 1.5 },
    marker: { size: 4, color: '#a5b4fc' },
  }];
  const layout = {
    polar: {
      radialaxis: { visible: true, range: [0, 5], tickvals: [1, 2, 3, 4, 5], tickfont: { size: 8, color: '#6b7280' }, gridcolor: '#1e1e1e' },
      angularaxis: { tickfont: { size: 9, color: '#9ca3af' }, gridcolor: '#1e1e1e' },
      bgcolor: 'transparent',
    },
    showlegend: false,
    margin: { t: 20, b: 20, l: 40, r: 40 },
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    width: 200,
    height: 200,
  };
  return (
    <Suspense fallback={<div className="pr-radar-loading">Loading chart...</div>}>
      <Plot data={data} layout={layout} config={{ displayModeBar: false, staticPlot: true }} />
    </Suspense>
  );
}

export default function PaperReviewPanel({
  review,
  loading,
  error,
  highlights,
  activeTab,
  highlightFilter,
  onTabChange,
  onFilterChange,
  onClose,
  onDelete,
  onReReview,
  onRemoveHighlight,
  onAutoHighlight,
  autoHighlighting,
}: PaperReviewPanelProps) {
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    strengths: true,
    weaknesses: true,
    questions: false,
    detailed: false,
  });

  const filteredHighlights = useMemo(() => {
    const sorted = [...highlights].sort((a, b) => (b.significance ?? 3) - (a.significance ?? 3));
    if (!highlightFilter) return sorted;
    return sorted.filter(h => h.category === highlightFilter);
  }, [highlights, highlightFilter]);

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const h of highlights) {
      const cat = h.category || 'finding';
      counts[cat] = (counts[cat] || 0) + 1;
    }
    return counts;
  }, [highlights]);

  const toggleSection = (key: string) => {
    setExpandedSections(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const reviewContentRef = useRef<HTMLDivElement>(null);

  // Apply highlights overlay to rendered markdown text (same pattern as useHighlights)
  const applyHighlightsToText = useCallback((children: React.ReactNode): React.ReactNode => {
    if (highlights.length === 0) return children;
    const processNode = (node: React.ReactNode, key: number): React.ReactNode => {
      if (typeof node === 'string') {
        let result: React.ReactNode[] = [node];
        for (const hl of highlights) {
          const nextResult: React.ReactNode[] = [];
          for (const part of result) {
            if (typeof part !== 'string') { nextResult.push(part); continue; }
            const idx = part.indexOf(hl.text);
            if (idx === -1) { nextResult.push(part); continue; }
            if (idx > 0) nextResult.push(part.slice(0, idx));
            const color = CATEGORY_COLORS[hl.category || 'finding'] || '#a5b4fc';
            nextResult.push(
              <mark
                key={`hl-${hl.id}-${idx}`}
                className="pr-review-highlight"
                style={{ background: `${color}22`, borderBottom: `2px solid ${color}66` }}
                data-hl-id={hl.id}
              >
                {hl.text}
              </mark>
            );
            if (idx + hl.text.length < part.length) nextResult.push(part.slice(idx + hl.text.length));
          }
          result = nextResult;
        }
        return result.length === 1 ? result[0] : <>{result}</>;
      }
      if (isValidElement(node) && (node.props as any).children) {
        return cloneElement(node, { key } as any, applyHighlightsToText((node.props as any).children));
      }
      return node;
    };
    if (Array.isArray(children)) return children.map((child, i) => processNode(child, i));
    return processNode(children, 0);
  }, [highlights]);

  // Scroll to highlight in the detailed review
  const scrollToHighlight = useCallback((hlId: string) => {
    // Ensure detailed section is expanded first
    setExpandedSections(prev => ({ ...prev, detailed: true }));

    // Use requestAnimationFrame + retry to wait for React render
    const tryScroll = (retries: number) => {
      requestAnimationFrame(() => {
        const target = reviewContentRef.current?.querySelector(`[data-hl-id="${hlId}"]`);
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'center' });
          target.classList.add('pr-hl-flash');
          setTimeout(() => target.classList.remove('pr-hl-flash'), 1500);
        } else if (retries > 0) {
          setTimeout(() => tryScroll(retries - 1), 100);
        }
      });
    };
    tryScroll(3);
  }, []);

  // Loading state
  if (loading) {
    return (
      <div className="pr-panel">
        <div className="pr-panel-header">
          <span className="pr-panel-title">Review</span>
          <button className="pr-close-btn" onClick={onClose} title="Close">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div className="pr-loading">
          <div className="pr-spinner" />
          <span>Analyzing paper...</span>
          <span className="pr-loading-sub">This may take 15-30 seconds</span>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="pr-panel">
        <div className="pr-panel-header">
          <span className="pr-panel-title">Review</span>
          <button className="pr-close-btn" onClick={onClose} title="Close">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div className="pr-error">
          <span className="pr-error-icon">!</span>
          <span>{error}</span>
          {onReReview && (
            <button className="pr-retry-btn" onClick={onReReview}>Retry</button>
          )}
        </div>
      </div>
    );
  }

  // No review
  if (!review) return null;

  return (
    <div className="pr-panel">
      {/* Header */}
      <div className="pr-panel-header">
        <div className="pr-tabs">
          <button
            className={`pr-tab${activeTab === 'review' ? ' active' : ''}`}
            onClick={() => onTabChange('review')}
          >
            Review
          </button>
          <button
            className={`pr-tab${activeTab === 'highlights' ? ' active' : ''}`}
            onClick={() => onTabChange('highlights')}
          >
            Highlights
            {highlights.length > 0 && (
              <span className="pr-tab-badge">{highlights.length}</span>
            )}
          </button>
        </div>
        <div className="pr-header-actions">
          {onDelete && (
            <button className="pr-action-btn" onClick={onDelete} title="Delete review">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
            </button>
          )}
          <button className="pr-close-btn" onClick={onClose} title="Close">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      {/* Review Tab */}
      {activeTab === 'review' && (
        <div className="pr-content" ref={reviewContentRef}>
          {/* Scores */}
          <div className="pr-scores">
            <ScoreBadge score={review.overall_score} label="Overall" />
            <ScoreBadge score={review.confidence} label="Confidence" />
            <span className="pr-input-badge" title={`Reviewed from: ${review.input_type}`}>
              {review.input_type === 'full_text' ? 'Full Text' : review.input_type === 'abstract' ? 'Abstract' : 'Metadata'}
            </span>
          </div>

          {/* Summary */}
          <div className="pr-section">
            <div className="pr-section-title">Summary</div>
            <p className="pr-summary-text">{review.summary}</p>
          </div>

          {/* Methodology */}
          <div className="pr-section">
            <div className="pr-section-title">Methodology</div>
            <div className="pr-method-bars">
              <MethodologyBar label="Rigor" value={review.methodology_assessment.rigor} />
              <MethodologyBar label="Novelty" value={review.methodology_assessment.novelty} />
              <MethodologyBar label="Reproducibility" value={review.methodology_assessment.reproducibility} />
            </div>
            <div className="pr-radar-wrap">
              <MethodologyRadar
                assessment={review.methodology_assessment}
                score={review.overall_score}
                confidence={review.confidence}
              />
            </div>
            {review.methodology_assessment.commentary && (
              <p className="pr-method-comment">{review.methodology_assessment.commentary}</p>
            )}
          </div>

          {/* Strengths */}
          <div className="pr-section">
            <button className="pr-section-toggle" onClick={() => toggleSection('strengths')}>
              <span className="pr-section-title" style={{ color: '#4ade80' }}>
                Strengths ({review.strengths.length})
              </span>
              <span className={`pr-chevron${expandedSections.strengths ? ' open' : ''}`}>&#9656;</span>
            </button>
            {expandedSections.strengths && (
              <ul className="pr-list pr-strengths">
                {review.strengths.map((s, i) => (
                  <li key={i}>
                    <div className="pr-list-point">{s.point}</div>
                    {s.evidence && <div className="pr-list-evidence">{s.evidence}</div>}
                    <span className={`pr-significance-tag ${s.significance}`}>{s.significance}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Weaknesses */}
          <div className="pr-section">
            <button className="pr-section-toggle" onClick={() => toggleSection('weaknesses')}>
              <span className="pr-section-title" style={{ color: '#fda4af' }}>
                Weaknesses ({review.weaknesses.length})
              </span>
              <span className={`pr-chevron${expandedSections.weaknesses ? ' open' : ''}`}>&#9656;</span>
            </button>
            {expandedSections.weaknesses && (
              <ul className="pr-list pr-weaknesses">
                {review.weaknesses.map((w, i) => (
                  <li key={i}>
                    <div className="pr-list-point">{w.point}</div>
                    {w.evidence && <div className="pr-list-evidence">{w.evidence}</div>}
                    <span className={`pr-severity-tag ${w.severity}`}>{w.severity}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Questions */}
          <div className="pr-section">
            <button className="pr-section-toggle" onClick={() => toggleSection('questions')}>
              <span className="pr-section-title">Questions for Authors ({review.questions_for_authors.length})</span>
              <span className={`pr-chevron${expandedSections.questions ? ' open' : ''}`}>&#9656;</span>
            </button>
            {expandedSections.questions && (
              <ol className="pr-questions">
                {review.questions_for_authors.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ol>
            )}
          </div>

          {/* Detailed Review */}
          <div className="pr-section">
            <button className="pr-section-toggle" onClick={() => toggleSection('detailed')}>
              <span className="pr-section-title">Detailed Review</span>
              <span className={`pr-chevron${expandedSections.detailed ? ' open' : ''}`}>&#9656;</span>
            </button>
            {expandedSections.detailed && (
              <div className="pr-detailed-review">
                <ReactMarkdown
                  components={{
                    p: ({ children }) => <p>{applyHighlightsToText(children)}</p>,
                    li: ({ children }) => <li>{applyHighlightsToText(children)}</li>,
                    td: ({ children }) => <td>{applyHighlightsToText(children)}</td>,
                  }}
                >
                  {review.detailed_review_markdown}
                </ReactMarkdown>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Highlights Tab */}
      {activeTab === 'highlights' && (
        <div className="pr-content">
          {/* Category Filters */}
          <div className="pr-hl-filters">
            <button
              className={`pr-hl-filter-chip${!highlightFilter ? ' active' : ''}`}
              onClick={() => onFilterChange(null)}
            >
              All ({highlights.length})
            </button>
            {Object.entries(categoryCounts).map(([cat, count]) => (
              <button
                key={cat}
                className={`pr-hl-filter-chip${highlightFilter === cat ? ' active' : ''}`}
                onClick={() => onFilterChange(highlightFilter === cat ? null : cat)}
                style={highlightFilter === cat ? { borderColor: CATEGORY_COLORS[cat], color: CATEGORY_COLORS[cat] } : undefined}
              >
                {CATEGORY_LABELS[cat] || cat} ({count})
              </button>
            ))}
          </div>

          {/* Category Distribution Bar */}
          {highlights.length > 0 && (
            <div className="pr-cat-dist">
              <div className="pr-cat-dist-bar">
                {Object.entries(categoryCounts).map(([cat, count]) => (
                  <div
                    key={cat}
                    className="pr-cat-dist-seg"
                    style={{
                      width: `${(count / highlights.length) * 100}%`,
                      background: CATEGORY_COLORS[cat] || '#a5b4fc',
                    }}
                    title={`${CATEGORY_LABELS[cat] || cat}: ${count}`}
                  />
                ))}
              </div>
              <div className="pr-cat-dist-summary">
                <span style={{ color: '#4ade80' }}>
                  {highlights.filter(h => h.strength_or_weakness === 'strength').length} strengths
                </span>
                <span style={{ color: '#6b7280' }}>/</span>
                <span style={{ color: '#fda4af' }}>
                  {highlights.filter(h => h.strength_or_weakness === 'weakness').length} weaknesses
                </span>
              </div>
            </div>
          )}

          {/* Auto Highlight Button */}
          {onAutoHighlight && (
            <div className="pr-hl-actions">
              <button
                className="pr-hl-auto-btn"
                onClick={onAutoHighlight}
                disabled={autoHighlighting}
              >
                {autoHighlighting ? (
                  <><span className="pr-hl-auto-spinner" /> Analyzing...</>
                ) : (
                  <><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2L15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2z"/></svg> Auto Highlight</>
                )}
              </button>
            </div>
          )}

          {/* Highlight List */}
          <div className="pr-hl-list">
            {filteredHighlights.length === 0 ? (
              <div className="pr-hl-empty">No highlights{highlightFilter ? ' in this category' : ''}</div>
            ) : (
              filteredHighlights.map(hl => (
                <HighlightCard
                  key={hl.id}
                  highlight={hl}
                  onScrollTo={scrollToHighlight}
                  onRemove={onRemoveHighlight}
                />
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function HighlightCard({ highlight, onScrollTo, onRemove }: { highlight: HighlightItem; onScrollTo?: (hlId: string) => void; onRemove?: (hlId: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const cat = highlight.category || 'finding';
  const color = CATEGORY_COLORS[cat] || '#a5b4fc';

  return (
    <div className="pr-hl-card" style={{ borderLeftColor: color }}>
      <div className="pr-hl-text" onClick={() => { setExpanded(!expanded); onScrollTo?.(highlight.id); }}>
        &ldquo;{highlight.text}&rdquo;
      </div>
      <div className="pr-hl-meta">
        <span className="pr-hl-category" style={{ color, borderColor: `${color}44` }}>
          {CATEGORY_LABELS[cat] || cat}
        </span>
        {highlight.strength_or_weakness && (
          <span className={`pr-hl-sw ${highlight.strength_or_weakness}`}>
            {highlight.strength_or_weakness === 'strength' ? 'S' : 'W'}
          </span>
        )}
        {highlight.significance && (
          <span className="pr-hl-sig" title={`Significance: ${highlight.significance}/5`}>
            {'★'.repeat(highlight.significance)}{'☆'.repeat(5 - highlight.significance)}
          </span>
        )}
        {onRemove && (
          <button
            className="pr-hl-remove"
            onClick={() => onRemove(highlight.id)}
            title="Remove highlight"
          >
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        )}
      </div>
      {highlight.memo && (
        <div className={`pr-hl-memo${expanded ? ' expanded' : ''}`}>
          {highlight.memo}
        </div>
      )}
      {expanded && highlight.implication && (
        <div className="pr-hl-implication">
          <span className="pr-hl-impl-label">Impact:</span> {highlight.implication}
        </div>
      )}
      {expanded && highlight.question_for_authors && (
        <div className="pr-hl-question">
          <span className="pr-hl-q-label">Q:</span> {highlight.question_for_authors}
        </div>
      )}
    </div>
  );
}
