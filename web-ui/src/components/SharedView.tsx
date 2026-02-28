import { useState, useEffect, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getSharedBookmark } from '../api/client';
import type { SharedBookmarkData, HighlightItem } from '../api/client';
import './MyPage.css';

type SharedError = 'not_found' | 'expired' | 'unknown' | null;

export default function SharedView() {
  const { token } = useParams<{ token: string }>();
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
        <div className="shared-view-loading">Loading shared report...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="shared-view">
        <div className="shared-view-error">
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
              <h2>Error</h2>
              <p>Something went wrong loading this shared report.</p>
            </>
          )}
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
      <div className="shared-view-header">
        <div className="shared-view-brand">
          <img
            src="/Jipyheonjeon_llama.png"
            alt="Jipyheonjeon"
            className="shared-view-logo"
            onError={(e) => { e.currentTarget.style.display = 'none'; }}
          />
          <span className="shared-view-brand-name">Jipyheonjeon</span>
          <span className="shared-view-badge">Shared Report</span>
        </div>
      </div>

      <div className="shared-view-content">
        <h1 className="shared-view-title">{data.title}</h1>
        <div className="shared-view-meta">
          {data.query && <span>Query: {data.query}</span>}
          <span>{data.num_papers} papers</span>
          <span>{new Date(data.created_at).toLocaleDateString()}</span>
        </div>

        {data.papers && data.papers.length > 0 && (
          <div className="shared-view-papers">
            <h3>Papers ({data.papers.length})</h3>
            <div className="mypage-detail-papers">
              {data.papers.map((p: any, i: number) => (
                <div key={i} className="mypage-detail-paper">
                  <span className="mypage-detail-paper-title">{p.title}</span>
                  <span className="mypage-detail-paper-meta">
                    {p.authors?.slice(0, 2).join(', ')}{p.authors?.length > 2 ? ' et al.' : ''} {p.year && `(${p.year})`}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {data.report_markdown && (
          <div className="mypage-report-section">
            <h3 className="mypage-report-section-title">Report</h3>
            <div className="mypage-report-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                {data.report_markdown}
              </ReactMarkdown>
            </div>
          </div>
        )}

        {sortedHighlights.length > 0 && (
          <div className="shared-view-highlights">
            <h3>Highlights ({sortedHighlights.length})</h3>
            <div className="mypage-highlights-list">
              {sortedHighlights.map((hl: HighlightItem) => (
                <div key={hl.id} className="mypage-highlight-item">
                  <div className="mypage-highlight-item-content">
                    <mark
                      className="mypage-highlight-item-text"
                      style={hl.color && hl.color !== '#a5b4fc' ? { background: `${hl.color}44`, borderLeftColor: hl.color } : undefined}
                    >
                      {hl.text.length > 150 ? hl.text.slice(0, 150) + '...' : hl.text}
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
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
