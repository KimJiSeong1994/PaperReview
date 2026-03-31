import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getSharedBookmark } from '../api/client';
import type { SharedBookmarkData, HighlightItem } from '../api/client';
import './MyPage.css';

type SharedError = 'not_found' | 'expired' | 'unknown' | null;

export default function SharedView() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<SharedBookmarkData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<SharedError>(null);

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    setError(null);
    getSharedBookmark(token)
      .then(setData)
      .catch((err) => {
        const status = err?.response?.status;
        if (status === 410) setError('expired');
        else if (status === 404) setError('not_found');
        else setError('unknown');
      })
      .finally(() => setLoading(false));
  }, [token]);

  const highlights = useMemo(() => data?.highlights ?? [], [data]);

  const applyHighlights = (children: React.ReactNode): React.ReactNode => {
    if (highlights.length === 0) return children;
    const processNode = (node: React.ReactNode): React.ReactNode => {
      if (typeof node === 'string') {
        let result: React.ReactNode[] = [node];
        for (const hl of highlights) {
          const nextResult: React.ReactNode[] = [];
          for (const part of result) {
            if (typeof part !== 'string') { nextResult.push(part); continue; }
            const idx = part.indexOf(hl.text);
            if (idx === -1) { nextResult.push(part); continue; }
            if (idx > 0) nextResult.push(part.slice(0, idx));
            nextResult.push(
              <mark
                key={`sh-${hl.id}-${idx}`}
                className="mypage-user-highlight shared-hl"
                style={hl.color && hl.color !== '#a5b4fc' ? { background: `${hl.color}33`, borderBottomColor: `${hl.color}aa` } : undefined}
                title={hl.memo || undefined}
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
      if (Array.isArray(node)) return node.map((child) => processNode(child));
      return node;
    };
    if (Array.isArray(children)) return children.map((child) => processNode(child));
    return processNode(children);
  };

  const sortedHighlights = useMemo(() =>
    [...highlights].sort((a, b) => (b.significance ?? 3) - (a.significance ?? 3)),
    [highlights],
  );

  if (loading) {
    return (
      <div className="shared-view">
        <div className="shared-view-loading">
          <div className="shared-view-spinner" />
          Loading shared report...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="shared-view">
        <div className="shared-view-error">
          <div className="shared-view-error-icon">
            {error === 'expired' ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="48" height="48">
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 6 12 12 16 14" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="48" height="48">
                <circle cx="12" cy="12" r="10" />
                <line x1="15" y1="9" x2="9" y2="15" />
                <line x1="9" y1="9" x2="15" y2="15" />
              </svg>
            )}
          </div>
          {error === 'expired' && (
            <>
              <h2>Link Expired</h2>
              <p>This share link has expired and is no longer available.</p>
            </>
          )}
          {error === 'not_found' && (
            <>
              <h2>Not Found</h2>
              <p>This share link is invalid or has been revoked.</p>
            </>
          )}
          {error === 'unknown' && (
            <>
              <h2>Something went wrong</h2>
              <p>Failed to load this shared report. Please try again later.</p>
            </>
          )}
          <button className="shared-view-home-btn" onClick={() => navigate('/')}>
            Go to Home
          </button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const markdownComponents = highlights.length > 0 ? {
    p: ({ children }: { children?: React.ReactNode }) => <p>{applyHighlights(children)}</p>,
    li: ({ children }: { children?: React.ReactNode }) => <li>{applyHighlights(children)}</li>,
    td: ({ children }: { children?: React.ReactNode }) => <td>{applyHighlights(children)}</td>,
  } : undefined;

  return (
    <div className="shared-view">
      {/* ── Header ── */}
      <header className="shared-view-header">
        <div className="shared-view-header-inner">
          <div className="shared-view-brand" onClick={() => navigate('/')} style={{ cursor: 'pointer' }}>
            <img
              src="/Jiphyeonjeon_llama.png"
              alt="Jiphyeonjeon"
              className="shared-view-logo"
              width={28}
              height={28}
              onError={(e) => { e.currentTarget.style.display = 'none'; }}
            />
            <span className="shared-view-brand-name">Jiphyeonjeon</span>
          </div>
          <span className="shared-view-badge">Shared Report</span>
        </div>
      </header>

      {/* ── Hero section ── */}
      <div className="shared-view-hero">
        <div className="shared-view-hero-inner">
          <h1 className="shared-view-title">{data.title}</h1>
          <div className="shared-view-meta">
            {data.query && (
              <span className="shared-view-meta-item">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13">
                  <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
                {data.query}
              </span>
            )}
            <span className="shared-view-meta-item">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
              {data.num_papers} papers
            </span>
            <span className="shared-view-meta-item">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13">
                <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                <line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" />
                <line x1="3" y1="10" x2="21" y2="10" />
              </svg>
              {new Date(data.created_at).toLocaleDateString()}
            </span>
          </div>
        </div>
      </div>

      <div className="shared-view-body">
        <div className="shared-view-body-inner">
          {/* ── Papers section ── */}
          {data.papers && data.papers.length > 0 && (
            <div className="shared-view-papers">
              <h3 className="shared-view-section-title">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                  <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
                  <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
                </svg>
                Papers ({data.papers.length})
              </h3>
              <div className="shared-view-papers-list">
                {data.papers.map((p: any, i: number) => (
                  <div key={i} className="shared-view-paper-item">
                    <span className="shared-view-paper-num">{i + 1}</span>
                    <div className="shared-view-paper-info">
                      <span className="shared-view-paper-title">{p.title}</span>
                      <span className="shared-view-paper-authors">
                        {p.authors?.slice(0, 3).join(', ')}{p.authors?.length > 3 ? ' et al.' : ''} {p.year && `(${p.year})`}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── Report section ── */}
          {data.report_markdown && (
            <div className="shared-view-report">
              <h3 className="shared-view-section-title">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
                  <polyline points="10 9 9 9 8 9" />
                </svg>
                Report
              </h3>
              <div className="shared-view-report-content mypage-report-content">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {data.report_markdown}
                </ReactMarkdown>
              </div>
            </div>
          )}

          {/* ── Highlights section ── */}
          {sortedHighlights.length > 0 && (
            <div className="shared-view-highlights">
              <h3 className="shared-view-section-title">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                  <path d="M12 2L2 7l10 5 10-5-10-5z" />
                  <path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
                </svg>
                Highlights ({sortedHighlights.length})
              </h3>
              <div className="shared-view-highlights-list">
                {sortedHighlights.map((hl: HighlightItem) => (
                  <div key={hl.id} className="shared-view-hl-item">
                    <div className="shared-view-hl-bar" style={hl.color && hl.color !== '#a5b4fc' ? { background: hl.color } : undefined} />
                    <div className="shared-view-hl-body">
                      <div className="shared-view-hl-text">
                        {hl.text.length > 200 ? hl.text.slice(0, 200) + '...' : hl.text}
                      </div>
                      <div className="shared-view-hl-tags">
                        {hl.section && <span className="shared-view-hl-tag section">{hl.section}</span>}
                        {hl.strength_or_weakness && (
                          <span className={`shared-view-hl-tag ${hl.strength_or_weakness}`}>
                            {hl.strength_or_weakness === 'strength' ? 'Strength' : 'Weakness'}
                          </span>
                        )}
                        {hl.confidence_level && (
                          <span className="shared-view-hl-tag confidence" title={`Confidence ${hl.confidence_level}/5`}>
                            C{hl.confidence_level}
                          </span>
                        )}
                      </div>
                      {hl.memo && <div className="shared-view-hl-memo">{hl.memo}</div>}
                      {hl.question_for_authors && (
                        <div className="shared-view-hl-extra">
                          <span className="shared-view-hl-extra-label">Q.</span>
                          {hl.question_for_authors}
                        </div>
                      )}
                      {hl.implication && (
                        <div className="shared-view-hl-extra">
                          <span className="shared-view-hl-extra-label">Implication</span>
                          {hl.implication}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Footer ── */}
      <footer className="shared-view-footer">
        <span>Shared via Jiphyeonjeon</span>
      </footer>
    </div>
  );
}
