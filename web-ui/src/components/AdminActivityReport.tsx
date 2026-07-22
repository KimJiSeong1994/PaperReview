import { Component, lazy, Suspense, useCallback, useEffect, useId, useState } from 'react';
import type { ReactNode } from 'react';
import {
  fetchAdminActivity,
  type AdminActivityReport as ActivityData,
} from '../api/client';
import type { Data } from '../PlotlyChart';

const Plot = lazy(() => import('../PlotlyChart'));

// Report-local palette, kept in the same violet family as the Visitors/
// Dashboard surfaces so this tab reads as a sibling. Bookmark add/remove and
// review completed/failed use semantic green/red because the pairing carries
// meaning ("gained vs lost", "worked vs broke").
const C = {
  primary: '#4f46e5',
  accent: '#9b5cff',
  bar: '#5b4df5',
  gain: '#34a853',
  loss: '#ea4335',
};

const WINDOWS = [7, 28, 90] as const;

const nf = new Intl.NumberFormat('ko-KR');
const fmt = (n: number) => nf.format(n ?? 0);
const pct = (r: number) => `${Math.round((r ?? 0) * 100)}%`;
const usd = (n: number) => `$${(n ?? 0).toFixed(2)}`;

/** Seconds → "45초" or "1.5분"; "—" when unknown/zero. Exported for test. */
export function fmtDuration(sec: number | null): string {
  const s = sec ?? 0;
  if (s <= 0) return '—';
  return s >= 60 ? `${(s / 60).toFixed(1)}분` : `${Math.round(s)}초`;
}

interface SeriesPoint {
  date: string;
  value: number;
}

class ChartErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return <div className="admin-loading">차트를 표시할 수 없습니다.</div>;
    }
    return this.props.children;
  }
}

const BASE_LAYOUT = {
  paper_bgcolor: 'transparent',
  plot_bgcolor: 'transparent',
  font: { color: '#706d7d', size: 11, family: 'Pretendard, sans-serif' },
} as const;

/** ⓘ tooltip: hover + keyboard focus reveal (pure CSS), Escape dismisses. */
function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const [dismissed, setDismissed] = useState(false);
  const id = useId();
  return (
    <span
      className="infotip"
      data-dismissed={dismissed || undefined}
      onMouseLeave={() => setDismissed(false)}
    >
      <button
        type="button"
        className="infotip-trigger"
        aria-label={label}
        aria-describedby={id}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setDismissed(true);
            e.currentTarget.blur();
          }
        }}
      >
        ⓘ
      </button>
      <span role="tooltip" id={id} className="infotip-pop">
        {children}
      </span>
    </span>
  );
}

function Band({ label, title, description }: { label: string; title: string; description: string }) {
  return (
    <header className="visits-band" aria-label={label}>
      <span className="visits-band-eyebrow">{label}</span>
      <h2>{title}</h2>
      <p>{description}</p>
    </header>
  );
}

function StatTile({ label, value, hint }: { label: ReactNode; value: ReactNode; hint?: string }) {
  return (
    <div className="admin-stat-card">
      <p className="admin-stat-label">{label}</p>
      <p className="admin-stat-value">{value}</p>
      {hint && <p className="visits-stat-hint">{hint}</p>}
    </div>
  );
}

function Section({
  title,
  tip,
  note,
  children,
}: {
  title: ReactNode;
  tip?: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <section className="visits-section">
      <h3 className="visits-section-title">
        <span>{title}</span>
        {tip && <InfoTip label="지표 설명">{tip}</InfoTip>}
      </h3>
      {note && <p className="visits-section-note">{note}</p>}
      {children}
    </section>
  );
}

function Card({ children }: { children: ReactNode }) {
  return <div className="visits-card">{children}</div>;
}

function EmptyState({ children }: { children: ReactNode }) {
  return <p className="visits-note">{children}</p>;
}

/** Ranked list mirroring AdminDashboardReport's RankList. */
function RankList({
  title,
  emptyLabel,
  rows,
}: {
  title: string;
  emptyLabel: string;
  rows: { label: string; count: number }[];
}) {
  const maxCount = Math.max(...rows.map((row) => row.count), 0);
  return (
    <section className="dashboard-rank-card">
      <h3>{title}</h3>
      {rows.length > 0 ? (
        <ol className="dashboard-rank-list">
          {rows.map((row, index) => (
            <li key={`${row.label}-${index}`} className="dashboard-rank-item">
              <span className="dashboard-rank-index">{String(index + 1).padStart(2, '0')}</span>
              <div className="dashboard-rank-detail">
                <div className="dashboard-rank-copy">
                  <span>{row.label || '(빈 값)'}</span>
                  <strong>{fmt(row.count)}</strong>
                </div>
                <span className="dashboard-rank-track" aria-hidden="true">
                  <span style={{ width: `${maxCount ? (row.count / maxCount) * 100 : 0}%` }} />
                </span>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <div className="admin-empty">{emptyLabel}</div>
      )}
    </section>
  );
}

function areaTrace(points: SeriesPoint[], name: string, color: string): Data {
  return {
    type: 'scatter',
    mode: 'lines',
    name,
    x: points.map((p) => p.date),
    y: points.map((p) => p.value),
    line: { color, width: 2, shape: 'spline', smoothing: 0.5 },
    fill: 'tozeroy',
    fillcolor: `${color}20`,
    hovertemplate: `%{x}<br>${name} %{y}<extra></extra>`,
  };
}

/** A single-series data-table disclosure matching the Visitors toggle. */
function SeriesTable({ points, valueLabel }: { points: SeriesPoint[]; valueLabel: string }) {
  return (
    <details className="visits-table-toggle">
      <summary>데이터 표로 보기</summary>
      <table className="visits-table">
        <thead>
          <tr>
            <th>날짜</th>
            <th className="visits-num-th">{valueLabel}</th>
          </tr>
        </thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.date}>
              <td>{p.date}</td>
              <td className="visits-num">{fmt(p.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

/** Chart card: boundary + suspense + a themed line/area layout, optional table. */
function PlotCard({
  data,
  height = 260,
  legend = false,
  table,
}: {
  data: Data[];
  height?: number;
  legend?: boolean;
  table?: ReactNode;
}) {
  return (
    <Card>
      <ChartErrorBoundary>
        <Suspense fallback={<div className="admin-loading">차트 로딩 중...</div>}>
          <Plot
            data={data}
            layout={{
              ...BASE_LAYOUT,
              height,
              margin: { t: legend ? 24 : 10, b: 40, l: 40, r: 12 },
              hovermode: 'x unified',
              hoverlabel: {
                bgcolor: 'rgba(255,255,255,0.98)',
                bordercolor: 'rgba(15,23,42,0.10)',
                font: { color: '#1e293b', size: 12, family: 'Pretendard, sans-serif' },
              },
              showlegend: legend,
              legend: { orientation: 'h', y: 1.14, font: { color: 'var(--text-muted)' } },
              xaxis: { gridcolor: 'rgba(128,128,128,0.08)', color: 'var(--text-faint)', zeroline: false },
              yaxis: {
                gridcolor: 'rgba(128,128,128,0.10)',
                color: 'var(--text-faint)',
                rangemode: 'tozero',
                zeroline: false,
              },
            }}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: '100%' }}
          />
        </Suspense>
      </ChartErrorBoundary>
      {table}
    </Card>
  );
}

function fmtDateTime(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  return new Date(t).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });
}

function AdminActivityReport() {
  const [days, setDays] = useState<number>(28);
  const [report, setReport] = useState<ActivityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (window: number) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchAdminActivity(window);
      setReport(response.data);
    } catch (err: unknown) {
      const maybe = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(maybe.response?.data?.detail ?? maybe.message ?? '활동 리포트를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void load(days);
    });
    return () => {
      cancelled = true;
    };
  }, [days, load]);

  if (loading && !report) return <div className="admin-loading">활동 리포트 로딩 중...</div>;
  if (error) {
    return (
      <div className="admin-loading" style={{ color: 'var(--danger-strong)' }}>
        Error: {error}
      </div>
    );
  }
  if (!report) return null;

  const { growth, active_users, search, bookmarks, reviews } = report;

  const signupPts: SeriesPoint[] = (growth.signups_series ?? []).map((p) => ({ date: p.date, value: p.count }));
  const activePts: SeriesPoint[] = (active_users.active_series ?? []).map((p) => ({ date: p.date, value: p.active }));
  const queryPts: SeriesPoint[] = (search.query_series ?? []).map((p) => ({ date: p.date, value: p.count }));
  const reviewPts: SeriesPoint[] = (reviews.create_series ?? []).map((p) => ({ date: p.date, value: p.count }));
  const addPts: SeriesPoint[] = (bookmarks.add_series ?? []).map((p) => ({ date: p.date, value: p.count }));
  const removePts: SeriesPoint[] = (bookmarks.remove_series ?? []).map((p) => ({ date: p.date, value: p.count }));

  const researcherBars = Object.entries(reviews.researcher_hist ?? {}).sort(
    (a, b) => Number(a[0]) - Number(b[0]),
  );
  const recentUsers = report.recent_activity_by_user ?? [];
  const metricEntries = Object.entries(report.metric_definitions ?? {});
  const notes = report.notes ?? [];

  return (
    <div className="admin-dashboard visits-report">
      <header className="visits-report-header">
        <div className="visits-report-heading">
          <span className="visits-report-kicker">ADMIN ANALYTICS</span>
          <h1>활동 분석 리포트</h1>
          <p>가입·활성 사용자부터 검색, 북마크, 딥리뷰 파이프라인까지 제품 활동을 한 흐름으로 봅니다.</p>
        </div>
        <div className="visits-toolbar">
          <div className="visits-window-picker" role="tablist" aria-label="기간 선택">
            {WINDOWS.map((w) => (
              <button
                key={w}
                role="tab"
                aria-selected={days === w}
                className={`visits-window-btn ${days === w ? 'visits-window-btn--active' : ''}`}
                onClick={() => setDays(w)}
              >
                {w}일
              </button>
            ))}
          </div>
          <span className="visits-window-range">최근 {report.window_days}일 · 생성 {fmtDateTime(report.generated_at)}</span>
        </div>
      </header>

      <Band
        label="성장 · 활성"
        title="사용자 성장과 활성"
        description="새 사용자가 얼마나 유입됐고, 기존 사용자가 얼마나 다시 돌아오는지 봅니다."
      />

      <Section
        title="성장"
        tip="가입 추이는 선택 기간 동안 새로 만들어진 계정 수의 일별 흐름입니다. 누적 사용자 수와 함께 봅니다."
      >
        <div className="admin-stats-grid">
          <StatTile label="누적 사용자" value={fmt(growth.total_users)} hint="등록 계정 총합" />
          <StatTile label="기간 내 신규 가입" value={fmt(growth.new_users_in_window)} hint={`최근 ${days}일`} />
        </div>
        {signupPts.length > 0 ? (
          <PlotCard
            data={[areaTrace(signupPts, '가입', C.primary)]}
            table={<SeriesTable points={signupPts} valueLabel="가입" />}
          />
        ) : (
          <EmptyState>이 기간에 집계된 가입 데이터가 없습니다.</EmptyState>
        )}
      </Section>

      <Section
        title="활성 사용자"
        tip="DAU·WAU·MAU는 각각 하루·7일·30일 동안 활동한 순사용자 수입니다. 고착도(Stickiness)는 DAU를 MAU로 나눈 값으로, 월간 사용자가 얼마나 자주 돌아오는지를 나타냅니다."
        note={active_users.basis || undefined}
      >
        <div className="admin-stats-grid">
          <StatTile label="DAU" value={fmt(active_users.dau)} hint="일간 활성" />
          <StatTile label="WAU" value={fmt(active_users.wau)} hint="주간 활성" />
          <StatTile label="MAU" value={fmt(active_users.mau)} hint="월간 활성" />
          <StatTile label="고착도" value={pct(active_users.stickiness)} hint="DAU / MAU" />
        </div>
        {activePts.length > 0 ? (
          <PlotCard
            data={[
              {
                type: 'scatter',
                mode: 'lines',
                name: '활성 사용자',
                x: activePts.map((p) => p.date),
                y: activePts.map((p) => p.value),
                line: { color: C.accent, width: 2, shape: 'spline', smoothing: 0.5 },
                hovertemplate: '%{x}<br>활성 %{y}<extra></extra>',
              },
            ]}
            table={<SeriesTable points={activePts} valueLabel="활성 사용자" />}
          />
        ) : (
          <EmptyState>이 기간에 집계된 활성 사용자 데이터가 없습니다.</EmptyState>
        )}
      </Section>

      <Band
        label="검색 · 북마크"
        title="탐색과 저장 행동"
        description="사용자가 무엇을 검색했고, 어떤 주제를 저장하거나 지웠는지 봅니다."
      />

      <Section
        title="검색"
        tip="검색 추이는 실행된 검색 쿼리 수의 일별 흐름입니다. CTR은 검색 결과에서 논문을 실제로 연 비율입니다. 하단 목록은 개인정보 보호를 위해 원문 대신 익명 해시로 집계됩니다(원문 미저장)."
      >
        <div className="admin-stats-grid">
          <StatTile label="총 검색" value={fmt(search.total_queries)} hint={`최근 ${days}일`} />
          <StatTile label="클릭률 (CTR)" value={pct(search.click_through_rate)} hint="검색 → 논문 열람" />
        </div>
        {queryPts.length > 0 ? (
          <PlotCard
            data={[areaTrace(queryPts, '검색', C.bar)]}
            table={<SeriesTable points={queryPts} valueLabel="검색" />}
          />
        ) : (
          <EmptyState>이 기간에 집계된 검색 데이터가 없습니다.</EmptyState>
        )}
        <RankList
          title="반복된 검색(익명 해시) · 횟수"
          emptyLabel="집계된 검색어가 없습니다."
          rows={(search.top_queries ?? []).map((q) => ({ label: q.query, count: q.count }))}
        />
      </Section>

      <Section
        title="북마크"
        tip="추가와 삭제를 함께 봅니다. 순증(net)은 기간 내 추가에서 삭제를 뺀 값입니다."
      >
        <div className="admin-stats-grid">
          <StatTile label="기간 내 순증" value={fmt(bookmarks.net_in_window)} hint="추가 − 삭제" />
        </div>
        {addPts.length > 0 || removePts.length > 0 ? (
          <PlotCard
            legend
            data={[areaTrace(addPts, '추가', C.gain), areaTrace(removePts, '삭제', C.loss)]}
          />
        ) : (
          <EmptyState>이 기간에 집계된 북마크 변동이 없습니다.</EmptyState>
        )}
        <RankList
          title="상위 주제 · 북마크 수"
          emptyLabel="집계된 주제가 없습니다."
          rows={(bookmarks.top_topics ?? []).map((t) => ({ label: t.topic, count: t.count }))}
        />
      </Section>

      <Band
        label="딥리뷰 · 최근 활동"
        title="딥리뷰 파이프라인과 최근 사용자"
        description="딥리뷰 작업의 처리량·성공률·소요시간과, 최근 활동한 사용자를 봅니다."
      />

      <Section
        title="딥리뷰 파이프라인"
        tip="시작·완료·실패 건수와 성공률, 소요 시간 분위수(p50/p90/p99), 빠른 모드 비중을 봅니다. 비용은 토큰 사용량 기반 추정치입니다."
      >
        <div className="admin-stats-grid">
          <StatTile label="시작" value={fmt(reviews.started)} />
          <StatTile label="완료" value={fmt(reviews.completed)} />
          <StatTile label="실패" value={fmt(reviews.failed)} />
          <StatTile label="성공률" value={pct(reviews.success_rate)} hint="완료 / 시작" />
          <StatTile label="빠른 모드 비중" value={pct(reviews.fast_mode_share)} hint="fast_mode 사용" />
          <StatTile label="소요 p50" value={fmtDuration(reviews.duration_p50_s)} hint="중앙값" />
          <StatTile label="소요 p90" value={fmtDuration(reviews.duration_p90_s)} />
          <StatTile label="소요 p99" value={fmtDuration(reviews.duration_p99_s)} />
          <StatTile
            label={
              <>
                비용 추정{' '}
                <InfoTip label="비용 추정 설명">
                  실측 청구액이 아니라 토큰 사용량 기반 추정치(프록시)입니다. {reviews.basis || ''}
                </InfoTip>
              </>
            }
            value={usd(reviews.cost_estimate_usd)}
            hint={reviews.basis || '토큰 기반 추정치'}
          />
        </div>
        {reviewPts.length > 0 ? (
          <PlotCard
            data={[areaTrace(reviewPts, '딥리뷰 생성', C.primary)]}
            table={<SeriesTable points={reviewPts} valueLabel="딥리뷰 생성" />}
          />
        ) : (
          <EmptyState>이 기간에 집계된 딥리뷰 생성이 없습니다.</EmptyState>
        )}
        {researcherBars.length > 0 && (
          <Card>
            <p className="visits-subhead">리서처 수 분포 · 세로축=세션 수</p>
            <ChartErrorBoundary>
              <Suspense fallback={<div className="admin-loading">차트 로딩 중...</div>}>
                <Plot
                  data={[
                    {
                      type: 'bar',
                      x: researcherBars.map(([k]) => `${k}명`),
                      y: researcherBars.map(([, v]) => v),
                      marker: { color: C.bar, line: { width: 0 } },
                      hovertemplate: '리서처 %{x} · 세션 %{y}<extra></extra>',
                    },
                  ]}
                  layout={{
                    ...BASE_LAYOUT,
                    height: 200,
                    bargap: 0.4,
                    margin: { t: 12, b: 32, l: 40, r: 12 },
                    xaxis: { color: 'var(--text-faint)' },
                    yaxis: { gridcolor: 'rgba(128,128,128,0.12)', color: 'var(--text-faint)' },
                  }}
                  config={{ displayModeBar: false, responsive: true }}
                  style={{ width: '100%' }}
                />
              </Suspense>
            </ChartErrorBoundary>
          </Card>
        )}
        <RankList
          title="실패 사유 · 건수"
          emptyLabel="집계된 실패 사유가 없습니다."
          rows={(reviews.failure_reasons ?? []).map((f) => ({ label: f.reason, count: f.count }))}
        />
      </Section>

      <Section
        title="최근 활동 사용자"
        tip="선택 기간 안에서 마지막으로 활동한 시각과 이벤트 수 기준 상위 사용자입니다."
      >
        {recentUsers.length === 0 ? (
          <EmptyState>이 기간에 활동한 사용자가 없습니다.</EmptyState>
        ) : (
          <Card>
            <table className="visits-table">
              <thead>
                <tr>
                  <th>사용자</th>
                  <th>마지막 활동</th>
                  <th className="visits-num-th">이벤트 수</th>
                </tr>
              </thead>
              <tbody>
                {recentUsers.map((u, i) => (
                  <tr key={`${u.username}-${i}`}>
                    <td>{u.username || '(익명)'}</td>
                    <td>{u.last_active || '—'}</td>
                    <td className="visits-num">{fmt(u.events_in_window)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </Section>

      <details className="visits-method">
        <summary>
          <span>지표 정의와 집계 기준</span>
          <span>기간 {report.window_days}일 · 생성 {fmtDateTime(report.generated_at)}</span>
        </summary>
        {metricEntries.length > 0 ? (
          metricEntries.map(([key, value]) => (
            <p key={key}>
              <strong>{key}</strong> — {value}
            </p>
          ))
        ) : (
          <p>등록된 지표 정의가 없습니다.</p>
        )}
        {notes.length > 0 && (
          <ul>
            {notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        )}
      </details>
    </div>
  );
}

export default AdminActivityReport;
