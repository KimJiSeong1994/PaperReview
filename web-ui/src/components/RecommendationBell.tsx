import { useEffect, useRef, useState } from 'react';
import { fetchRecommendationNotifications, type RecommendationNotification } from '../api/recommendations';
import './RecommendationBell.css';

function formatDate(value?: string | null): string {
  if (!value) return '최근 추천';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return new Intl.DateTimeFormat('ko-KR', { month: 'short', day: 'numeric' }).format(date);
}

function paperHref(item: RecommendationNotification): string | undefined {
  return item.url || item.pdf_url || (item.doi ? `https://doi.org/${item.doi}` : undefined);
}

export default function RecommendationBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<RecommendationNotification[]>([]);
  const [latestRunAt, setLatestRunAt] = useState<string | null>(null);
  const [scoringMode, setScoringMode] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadedOnceRef = useRef(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [open]);

  useEffect(() => {
    if (!open || loadedOnceRef.current) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchRecommendationNotifications(10)
      .then((data) => {
        if (cancelled) return;
        setItems(data.items);
        setLatestRunAt(data.latest_run_at ?? null);
        setScoringMode(data.scoring_mode ?? null);
        loadedOnceRef.current = true;
      })
      .catch(() => {
        if (!cancelled) setError('추천 알림을 불러오지 못했습니다.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  return (
    <div className="recommendation-bell" ref={rootRef}>
      <button
        className={`recommendation-bell-btn ${open ? 'recommendation-bell-btn-active' : ''}`}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label="추천 알림 열기"
        onClick={() => setOpen((value) => !value)}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" aria-hidden="true">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {items.length > 0 && <span className="recommendation-bell-dot" aria-hidden="true" />}
      </button>

      {open && (
        <section className="recommendation-panel" role="dialog" aria-label="논문 추천 알림">
          <div className="recommendation-panel-header">
            <div>
              <p className="recommendation-eyebrow">Daily picks</p>
              <h2>추천 알림</h2>
            </div>
            <span>{formatDate(latestRunAt)}</span>
          </div>

          {scoringMode && <div className="recommendation-mode">{scoringMode} rerank</div>}
          {loading && <div className="recommendation-empty" role="status">추천을 확인하는 중...</div>}
          {error && <div className="recommendation-empty recommendation-error" role="alert">{error}</div>}
          {!loading && !error && items.length === 0 && (
            <div className="recommendation-empty">아직 표시할 추천 논문이 없습니다.</div>
          )}

          {!loading && !error && items.length > 0 && (
            <div className="recommendation-list">
              {items.map((item) => {
                const href = paperHref(item);
                const content = (
                  <>
                    <div className="recommendation-item-topline">
                      <span>{item.variant}</span>
                      {item.score != null && <strong>{item.score.toFixed(2)}</strong>}
                    </div>
                    <h3>{item.title}</h3>
                    <p className="recommendation-meta">
                      {item.authors.slice(0, 2).join(', ')}{item.authors.length > 2 ? ' et al.' : ''}
                      {item.year ? ` · ${item.year}` : ''}{item.venue ? ` · ${item.venue}` : ''}
                    </p>
                    {item.reason && <p className="recommendation-reason">{item.reason}</p>}
                  </>
                );
                return href ? (
                  <a className="recommendation-item" href={href} target="_blank" rel="noreferrer" key={item.id}>
                    {content}
                  </a>
                ) : (
                  <article className="recommendation-item" key={item.id}>{content}</article>
                );
              })}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
