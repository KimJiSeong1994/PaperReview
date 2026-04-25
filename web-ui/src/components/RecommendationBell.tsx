import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchRecommendationNotifications,
  type RecommendationNotification,
  type RecommendationPaperNotification,
} from '../api/recommendations';
import './RecommendationBell.css';

function formatDate(value?: string | null): string {
  if (!value) return '최근 추천';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return new Intl.DateTimeFormat('ko-KR', { month: 'short', day: 'numeric' }).format(date);
}

function variantLabel(value: string): string {
  const labels: Record<string, string> = {
    keywords: '키워드',
    soul: 'SOUL',
    narrative: '내러티브',
  };
  return labels[value] ?? value;
}

function scoringModeLabel(value?: string | null): string {
  if (!value) return '키워드 + SOUL 기준';
  const labels: Record<string, string> = {
    listwise: '순위 비교 기반',
    pointwise: '개별 점수 기반',
  };
  return labels[value] ?? value;
}

function paperHref(item: RecommendationPaperNotification): string | undefined {
  return item.url || item.pdf_url || (item.doi ? `https://doi.org/${item.doi}` : undefined);
}

function toViewerPaper(item: RecommendationPaperNotification) {
  return {
    title: item.title,
    authors: item.authors || [],
    year: item.year ?? undefined,
    pdf_url: item.pdf_url || undefined,
    doi: item.doi || undefined,
    arxiv_id: item.arxiv_id || undefined,
    url: item.url || undefined,
    source: item.source || undefined,
  };
}

function legacyToGrouped(items: RecommendationNotification[]): RecommendationPaperNotification[] {
  return items.map((item) => ({
    id: item.id,
    paper_id: item.paper_id ?? item.id,
    title: item.title,
    top_reason: item.reason,
    run_at: item.run_at,
    score: item.score,
    display_score: item.display_score,
    confidence_label: item.confidence_label ?? '추천',
    rank: item.rank,
    year: item.year,
    authors: item.authors,
    venue: item.venue,
    source: item.source,
    url: item.url,
    pdf_url: item.pdf_url,
    doi: item.doi,
    arxiv_id: item.arxiv_id,
    variants: [
      {
        variant: item.variant,
        reason: item.reason,
        score: item.score,
        display_score: item.display_score,
        confidence_label: item.confidence_label ?? '추천',
        rank: item.rank,
      },
    ],
  }));
}

function metaLine(item: RecommendationPaperNotification): string {
  const authors = item.authors.slice(0, 2).join(', ');
  const authorText = authors ? `${authors}${item.authors.length > 2 ? ' et al.' : ''}` : '';
  return [authorText, item.year, item.venue].filter(Boolean).join(' · ');
}

export default function RecommendationBell() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<RecommendationPaperNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [rawCount, setRawCount] = useState(0);
  const [latestRunAt, setLatestRunAt] = useState<string | null>(null);
  const [scoringMode, setScoringMode] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadedOnceRef = useRef(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    window.setTimeout(() => panelRef.current?.focus(), 0);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (!open || loadedOnceRef.current) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchRecommendationNotifications(12)
      .then((data) => {
        if (cancelled) return;
        setItems(data.grouped_items?.length ? data.grouped_items : legacyToGrouped(data.items));
        setUnreadCount(data.unread_count);
        setRawCount(data.raw_count ?? data.items.length);
        setLatestRunAt(data.latest_run_at ?? null);
        setScoringMode(data.scoring_mode ?? null);
        loadedOnceRef.current = true;
      })
      .catch(() => {
        if (!cancelled) setError('추천 논문을 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const handleViewPdf = (item: RecommendationPaperNotification) => {
    setOpen(false);
    navigate('/mypage', { state: { viewPaper: toViewerPaper(item) } });
  };

  const handleSearchPaper = (item: RecommendationPaperNotification) => {
    setOpen(false);
    navigate(`/?q=${encodeURIComponent(item.title)}`);
  };

  const handleOpenSource = (item: RecommendationPaperNotification) => {
    const href = paperHref(item);
    if (!href) return;
    setOpen(false);
    window.open(href, '_blank', 'noopener,noreferrer');
  };

  return (
    <div className="recommendation-bell" ref={rootRef}>
      <button
        className={`recommendation-bell-btn ${open ? 'recommendation-bell-btn-active' : ''}`}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label="추천 논문 열기"
        onClick={() => setOpen((value) => !value)}
        ref={buttonRef}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" aria-hidden="true">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {unreadCount > 0 && <span className="recommendation-bell-dot" aria-hidden="true" />}
      </button>

      {open && (
        <section className="recommendation-panel" role="dialog" aria-label="추천 논문" tabIndex={-1} ref={panelRef}>
          <div className="recommendation-panel-header">
            <div>
              <p className="recommendation-eyebrow">오늘의 추천</p>
              <h2>추천 논문 {unreadCount > 0 ? `${unreadCount}편` : ''}</h2>
            </div>
            <span>{formatDate(latestRunAt)}</span>
          </div>

          <div className="recommendation-summary" aria-label="추천 요약">
            <span>{scoringModeLabel(scoringMode)}</span>
            {rawCount > unreadCount && <span>중복 {rawCount - unreadCount}개 병합</span>}
          </div>

          {loading && <div className="recommendation-empty" role="status">추천 논문을 정리하는 중...</div>}
          {error && <div className="recommendation-empty recommendation-error" role="alert">{error}</div>}
          {!loading && !error && items.length === 0 && (
            <div className="recommendation-empty">아직 표시할 추천 논문이 없습니다. 다음 추천 실행 후 이곳에 모아둘게요.</div>
          )}

          {!loading && !error && items.length > 0 && (
            <div className="recommendation-list">
              {items.map((item) => {
                const href = paperHref(item);
                const itemMeta = metaLine(item);
                return (
                  <article className="recommendation-item" key={item.id}>
                    <div className="recommendation-item-topline">
                      <div className="recommendation-variant-stack">
                        {item.variants.map((variant) => (
                          <span className="recommendation-variant-chip" key={variant.variant}>
                            {variantLabel(variant.variant)}
                            {variant.rank ? ` #${variant.rank}` : ''}
                          </span>
                        ))}
                      </div>
                      <strong>{item.confidence_label}</strong>
                    </div>
                    <h3>{item.title}</h3>
                    {itemMeta && <p className="recommendation-meta">{itemMeta}</p>}
                    {item.top_reason && <p className="recommendation-reason">{item.top_reason}</p>}
                    <div className="recommendation-signals" aria-label="논문 식별 정보">
                      {item.source && <span>{item.source}</span>}
                      {item.arxiv_id && <span>arXiv</span>}
                      {item.doi && <span>DOI</span>}
                    </div>
                    <div className="recommendation-actions" aria-label={`${item.title} 작업`}>
                      <button
                        type="button"
                        className="recommendation-action-primary"
                        onClick={() => handleViewPdf(item)}
                        title="집현전 PDF 뷰어에서 보기"
                      >
                        PDF 보기
                      </button>
                      <button
                        type="button"
                        onClick={() => handleSearchPaper(item)}
                        title="이 논문 제목으로 관련 논문 검색"
                      >
                        관련 검색
                      </button>
                      {href && (
                        <button
                          type="button"
                          onClick={() => handleOpenSource(item)}
                          title="외부 원문 페이지 열기"
                        >
                          원문 열기 ↗
                        </button>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
