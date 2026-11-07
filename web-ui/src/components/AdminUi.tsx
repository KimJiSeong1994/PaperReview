import { lazy, Suspense } from 'react';
import type { ReactNode } from 'react';
import type { AdminWindowDays } from '../api/client';
import type { Data } from '../PlotlyChart';
import LazyLoadErrorBoundary from './LazyLoadErrorBoundary';
import { COLORS, WINDOWS, type Block } from './adminShared';

const Plot = lazy(() => import('../PlotlyChart'));

/** Tab title, optional muted range, and the shared window toggle on the right. */
export function AdminTabHeader({ id, title, range, days, onDays }: {
  id: string;
  title: string;
  range?: string | null;
  days?: AdminWindowDays;
  onDays?: (days: AdminWindowDays) => void;
}) {
  return (
    <header className="admin-tab-head">
      <h1 id={id}>{title}</h1>
      {range && <span className="admin-tab-range">{range}</span>}
      {days !== undefined && onDays && (
        <div className="admin-window" role="group" aria-label="조회 기간">
          {WINDOWS.map((w) => (
            <button type="button" key={w} aria-pressed={days === w} onClick={() => onDays(w)}>{w}일</button>
          ))}
        </div>
      )}
    </header>
  );
}

/** One titled block of a tab; `aside` sits right of the title (a count, a note). */
export function AdminSection({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="admin-sec" aria-label={title}>
      <div className="admin-sec-head">
        <h2>{title}</h2>
        {aside && <span className="admin-sec-aside">{aside}</span>}
      </div>
      {children}
    </section>
  );
}

/** One-line failure notice for one source, with a retry for just that source. */
export function BlockError<T>({ block, label }: { block: Block<T>; label: string }) {
  if (!block.error || block.loading) return null;
  return (
    <div className="admin-inline-error" role="alert">
      <span>{label}을(를) 불러오지 못했습니다 · {block.error}</span>
      <button type="button" className="admin-action-btn" onClick={block.retry}>다시 시도</button>
    </div>
  );
}

/** Loading line, then the error line, then the content once data exists. */
export function BlockBody<T>({ block, label, children }: { block: Block<T>; label: string; children: (data: T) => ReactNode }) {
  if (block.data) return <>{children(block.data)}</>;
  if (block.error && !block.loading) return <BlockError block={block} label={label} />;
  return <div className="admin-loading">{label} 불러오는 중...</div>;
}

/** Compact KPI tile (88px); the long explanation lives in the title tooltip. */
export function KpiTile({ label, value, hint, title }: { label: string; value: ReactNode; hint?: ReactNode; title?: string }) {
  return (
    <article className="admin-kpi" title={title}>
      <p className="admin-kpi-label">{label}</p>
      <p className="admin-kpi-value">{value}</p>
      {hint && <p className="admin-kpi-hint">{hint}</p>}
    </article>
  );
}

const CHART_LAYOUT = {
  paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
  margin: { t: 8, b: 28, l: 44, r: 8 },
  font: { color: COLORS.font, size: 11, family: 'Pretendard, sans-serif' },
  xaxis: { gridcolor: 'transparent', color: COLORS.axis, fixedrange: true },
  yaxis: { gridcolor: COLORS.grid, color: COLORS.axis, zeroline: false, fixedrange: true, rangemode: 'tozero' as const },
  legend: { orientation: 'h' as const, x: 1, xanchor: 'right' as const, y: 1.14 },
};

/** Plotly chart with hex colors, loaded lazily; a load failure leaves a one-line note. */
export function AdminChart({ data, label, height = 220, barmode, showlegend }: {
  data: Data[]; label: string; height?: number; barmode?: 'stack' | 'group'; showlegend?: boolean;
}) {
  return (
    <LazyLoadErrorBoundary fallback={<div className="admin-empty">차트를 표시할 수 없습니다.</div>}>
      <Suspense fallback={<div className="admin-loading" style={{ height }}>차트 로딩 중...</div>}>
        <div role="img" aria-label={label}>
          <Plot
            data={data}
            layout={{ ...CHART_LAYOUT, height, ...(barmode ? { barmode } : {}), ...(showlegend === undefined ? {} : { showlegend }) }}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: '100%' }}
          />
        </div>
      </Suspense>
    </LazyLoadErrorBoundary>
  );
}

/** Scrollable, keyboard-reachable compact table. */
export function AdminTable({ label, headings, children }: { label: string; headings: string[]; children: ReactNode }) {
  return (
    <div className="admin-table-scroll" tabIndex={0} role="region" aria-label={label}>
      <table className="admin-table">
        <thead><tr>{headings.map((h) => <th scope="col" key={h}>{h}</th>)}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
