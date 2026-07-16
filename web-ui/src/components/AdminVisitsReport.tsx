import { Component, lazy, Suspense, useCallback, useEffect, useId, useState } from 'react';
import type { ReactNode } from 'react';
import { fetchAdminVisitsReport, type AdminVisitsReport as VisitsReportData } from '../api/client';

const Plot = lazy(() => import('../PlotlyChart'));

// Validated categorical palette (dataviz method): slot 1 blue = 방문자,
// slot 2 aqua = 세션. Dark steps are the same hues re-stepped for the dark
// surface (#0f0f0f) — CVD ΔE and 3:1 contrast checked with the palette
// validator; the light-mode aqua contrast WARN is relieved by the data
// tables that accompany every chart on this page.
const SERIES = {
  light: { visitors: '#2a78d6', sessions: '#1baf7a', bar: '#256abf' },
  dark: { visitors: '#3987e5', sessions: '#199e70', bar: '#3987e5' },
};

const WINDOWS = [7, 28, 90] as const;
const DOW_LABELS = ['일', '월', '화', '수', '목', '금', '토'];
const EVENT_LABELS: Record<string, string> = {
  page_view: '방문',
  search: '검색',
  paper_select: '논문 선택',
  login: '로그인',
  sign_up: '가입',
  deep_review_start: '딥리뷰 시작',
  deep_review_complete: '딥리뷰 완료',
  deep_review_fail: '딥리뷰 실패',
  bookmark_save: '북마크',
  report_download: '리포트 다운로드',
  poster_generate_start: '포스터 시작',
  poster_generate_complete: '포스터 완료',
  poster_generate_fail: '포스터 실패',
};

function useIsDark(): boolean {
  const read = () => document.documentElement.getAttribute('data-theme') !== 'light';
  const [isDark, setIsDark] = useState(read);
  useEffect(() => {
    const observer = new MutationObserver(() => setIsDark(read()));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    });
    return () => observer.disconnect();
  }, []);
  return isDark;
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
  font: { color: 'var(--text-muted)', size: 11, family: 'Pretendard, sans-serif' },
} as const;

const nf = new Intl.NumberFormat('ko-KR');
const fmt = (n: number) => nf.format(n);
const pct = (r: number) => `${Math.round(r * 100)}%`;

/** Inclusive calendar-day span between two YYYY-MM-DD dates (0 if unparsable). */
function daySpan(startISO: string, endISO: string): number {
  const s = Date.parse(`${startISO}T00:00:00Z`);
  const e = Date.parse(`${endISO}T00:00:00Z`);
  if (Number.isNaN(s) || Number.isNaN(e)) return 0;
  return Math.round((e - s) / 86_400_000) + 1;
}

/** Emphasize the peak bar; recede the rest (45% alpha) so the peak reads at
 *  a glance. ``color`` is a 6-digit hex; ``73`` is the appended alpha byte. */
function peakColors(values: number[], peak: number | null, color: string): string[] {
  return values.map((_, i) => (i === peak ? color : `${color}73`));
}

/** Accessible ⓘ tooltip: hover + keyboard focus reveal it (pure CSS), Escape
 *  dismisses. Placed on section titles / subheads (left-anchored, never near
 *  the right edge) so the popover cannot clip off-screen. No layout shift. */
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

/** Big headline number for the at-a-glance row (indigo, larger than tiles). */
function HeroStat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="visits-hero-stat">
      <p className="visits-hero-value">{value}</p>
      <p className="visits-hero-label">{label}</p>
    </div>
  );
}

/** Eyebrow band divider grouping the report into 사람 방문 / AI·유입 / 제품. */
function Band({ label }: { label: string }) {
  return <div className="visits-band" role="separator" aria-label={label}>{label}</div>;
}

function StatTile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
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
  title: string;
  tip?: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <section className="visits-section">
      <h3 className="visits-section-title">
        <span>{title}</span>
        {tip && <InfoTip label={`${title} 설명`}>{tip}</InfoTip>}
      </h3>
      {note && <p className="visits-section-note">{note}</p>}
      {children}
    </section>
  );
}

/** Chart/table container matching the app's card tone (.admin-stat-card). */
function Card({ children }: { children: ReactNode }) {
  return <div className="visits-card">{children}</div>;
}

/** A right-aligned magnitude cell with a faint inline bar behind the number. */
function BarCell({ value, max }: { value: number; max: number }) {
  const w = max > 0 ? Math.max((value / max) * 100, 2) : 0;
  return (
    <td className="visits-barcell">
      <span className="visits-barcell-bar" style={{ width: `${w}%` }} />
      <span className="visits-barcell-num">{fmt(value)}</span>
    </td>
  );
}

function EmptyState({ children }: { children: ReactNode }) {
  return <p className="visits-note">{children}</p>;
}

/** Deep-review terminal outcome as one stacked bar: completed / failed /
 *  abandoned — separates "it broke" from "the user left". */
function ReviewOutcome({ outcome }: { outcome: VisitsReportData['deep_review_outcome'] }) {
  const { started, completed, failed, abandoned } = outcome;
  const seg = (n: number) => `${(n / started) * 100}%`;
  return (
    <Card>
      <div className="visits-funnel-head">
        <span>딥리뷰 결과 — 시작 {fmt(started)}건</span>
        <span className="visits-funnel-conv">완료율 {pct(completed / started)}</span>
      </div>
      <div className="visits-outcome-bar">
        {completed > 0 && (
          <span className="visits-outcome-seg visits-outcome-done" style={{ width: seg(completed) }} />
        )}
        {failed > 0 && (
          <span className="visits-outcome-seg visits-outcome-fail" style={{ width: seg(failed) }} />
        )}
        {abandoned > 0 && (
          <span className="visits-outcome-seg visits-outcome-drop" style={{ width: seg(abandoned) }} />
        )}
      </div>
      <div className="visits-outcome-legend">
        <span>
          <i className="visits-outcome-done" />
          완료 {fmt(completed)}
        </span>
        <span>
          <i className="visits-outcome-fail" />
          실패 {fmt(failed)}
        </span>
        <span>
          <i className="visits-outcome-drop" />
          이탈 {fmt(abandoned)}
        </span>
      </div>
    </Card>
  );
}

/** A curated conversion funnel: each step a bar scaled to its conversion rate
 *  (vs. the first step), with session count, rate, and drop-off from the
 *  previous step. Design-token bars (theme-aware), no chart dependency. */
function FunnelChart({ funnel }: { funnel: VisitsReportData['funnels'][number] }) {
  const base = funnel.steps[0]?.count ?? 0;
  return (
    <Card>
      <div className="visits-funnel-head">
        <span>{funnel.label}</span>
        <span className="visits-funnel-conv">전환 {base ? pct(funnel.overall_conversion) : '—'}</span>
      </div>
      <div className="visits-funnel">
        {funnel.steps.map((step, i) => (
          <div className="visits-funnel-row" key={step.event}>
            <span className="visits-funnel-name">{EVENT_LABELS[step.event] ?? step.event}</span>
            <span className="visits-funnel-track">
              <span
                className="visits-funnel-fill"
                style={{ width: `${base ? Math.max(step.rate * 100, step.count > 0 ? 3 : 0) : 0}%` }}
              />
              <span className="visits-funnel-count">{fmt(step.count)}</span>
            </span>
            <span className="visits-funnel-pct">
              {base ? (i === 0 ? '100%' : pct(step.rate)) : '—'}
              {i > 0 && step.drop_off > 0 && (
                <span className="visits-funnel-drop">↓{fmt(step.drop_off)}</span>
              )}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function AdminVisitsReport() {
  const isDark = useIsDark();
  const colors = isDark ? SERIES.dark : SERIES.light;
  const [days, setDays] = useState<number>(28);
  const [report, setReport] = useState<VisitsReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (window: number) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchAdminVisitsReport(window);
      setReport(response.data);
    } catch (err: unknown) {
      const maybe = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(maybe.response?.data?.detail ?? maybe.message ?? '방문 리포트를 불러오지 못했습니다.');
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

  if (loading && !report) return <div className="admin-loading">방문 리포트 로딩 중...</div>;
  if (error) {
    return (
      <div className="admin-loading" style={{ color: 'var(--danger-strong)' }}>
        Error: {error}
      </div>
    );
  }
  if (!report) return null;

  const { totals, daily } = report.traffic;
  const { timing } = report;
  const ai = report.ai;
  const productEvents = Object.entries(report.product_events).sort((a, b) => b[1] - a[1]);
  // Guard against an older backend during rollout that predates these keys.
  const funnels = report.funnels ?? [];
  const reviewOutcome = report.deep_review_outcome ?? {
    started: 0,
    completed: 0,
    failed: 0,
    abandoned: 0,
  };

  // Analytics history is finite: when the selected window reaches back before
  // the first collected day, the report only covers from that first day — so
  // e.g. 28일 and 90일 look near-identical. Surface that so the shorter result
  // doesn't read as "the toggle is broken".
  const coveredDays = daySpan(report.window.start, report.window.end);
  const windowLimited = coveredDays > 0 && coveredDays < days - 1;

  return (
    <div className="admin-dashboard visits-report">
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
        <span className="visits-window-range">
          {report.window.start} ~ {report.window.end} (KST)
          {windowLimited && (
            <>
              <span className="visits-window-coverage">· 집계 {coveredDays}일분</span>
              <InfoTip label="집계 기간 안내">
                분석 데이터가 아직 {coveredDays}일치만 쌓여 있어, 이보다 긴 기간(예: 28·90일)을
                선택해도 결과가 거의 같습니다. 데이터가 더 쌓일수록 기간별 차이가 뚜렷해집니다.
              </InfoTip>
            </>
          )}
        </span>
      </div>

      {/* At-a-glance: the four numbers that answer "how are we doing". */}
      <div className="visits-hero">
        <HeroStat label="방문자" value={fmt(totals.visitors)} />
        <HeroStat label="세션" value={fmt(totals.sessions)} />
        <HeroStat label="참여율" value={pct(totals.engaged_rate)} />
        <HeroStat label="AI 인용 fetch" value={fmt(ai.citation_clicks ?? 0)} />
      </div>

      <p className="visits-meta-line">
        사람 지표는 퍼스트파티 직접수집, AI·채널은 nginx 로그 기준 · 모든 시각 KST
        <InfoTip label="데이터 출처 설명">
          방문·세션·페이지뷰는 동의 방문자의 퍼스트파티 직접 수집 — 봇은 자바스크립트를 실행하지
          않아 제외돼 GA4보다 깨끗합니다. AI 크롤러·인용은 nginx 접근 로그(10분 캐시)로 사람
          지표와 겹치지 않습니다. 전체 채널(GA4)은 연동 복구 시 표시되며 오늘 자는 아직 집계
          중입니다.
        </InfoTip>
      </p>

      <Band label="사람 방문" />

      <Section
        title="방문 추이"
        tip="방문자는 중복 제거한 순 방문자, 세션은 30분 이상 끊긴 뒤 다시 들어온 방문 묶음입니다. 한 사람이 여러 번 오면 세션이 방문자보다 큽니다."
      >
        <div className="admin-stats-grid">
          <StatTile
            label="방문자"
            value={fmt(totals.visitors)}
            hint={`일 평균 ${totals.avg_daily_visitors}`}
          />
          <StatTile label="세션" value={fmt(totals.sessions)} />
          <StatTile label="페이지뷰" value={fmt(totals.page_views)} />
          <StatTile label="페이지 / 세션" value={totals.pages_per_session} />
          <StatTile label="참여율" value={pct(totals.engaged_rate)} />
        </div>
        {daily.length > 1 && (
          <Card>
          <ChartErrorBoundary>
            <Suspense fallback={<div className="admin-loading">차트 로딩 중...</div>}>
              <Plot
                data={[
                  // 세션 is the larger series → draw it first (behind) so the
                  // smaller 방문자 line + fill sit on top and are never
                  // occluded. legendrank keeps the legend in 방문자→세션 order.
                  {
                    type: 'scatter',
                    mode: 'lines',
                    name: '세션',
                    legendrank: 2,
                    x: daily.map((d) => d.date),
                    y: daily.map((d) => d.sessions),
                    line: { color: colors.sessions, width: 2, shape: 'spline', smoothing: 0.5 },
                    fill: 'tozeroy',
                    fillcolor: `${colors.sessions}${isDark ? '2b' : '1e'}`,
                    hovertemplate: '%{x}<br>세션 %{y}<extra></extra>',
                  },
                  {
                    type: 'scatter',
                    mode: 'lines',
                    name: '방문자',
                    legendrank: 1,
                    x: daily.map((d) => d.date),
                    y: daily.map((d) => d.visitors),
                    line: { color: colors.visitors, width: 2, shape: 'spline', smoothing: 0.5 },
                    fill: 'tozeroy',
                    fillcolor: `${colors.visitors}${isDark ? '30' : '22'}`,
                    hovertemplate: '%{x}<br>방문자 %{y}<extra></extra>',
                  },
                ]}
                layout={{
                  ...BASE_LAYOUT,
                  height: 260,
                  margin: { t: 10, b: 40, l: 36, r: 10 },
                  hovermode: 'x unified',
                  hoverlabel: {
                    bgcolor: isDark ? 'rgba(22,22,25,0.96)' : 'rgba(255,255,255,0.98)',
                    bordercolor: isDark ? 'rgba(255,255,255,0.14)' : 'rgba(15,23,42,0.10)',
                    font: {
                      color: isDark ? '#e8e8ea' : '#1e293b',
                      size: 12,
                      family: 'Pretendard, sans-serif',
                    },
                  },
                  legend: { orientation: 'h', y: 1.12, font: { color: 'var(--text-muted)' } },
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
          <p className="visits-caption">마지막 날짜는 아직 집계 중이라 낮게 보일 수 있습니다.</p>
          <details className="visits-table-toggle">
            <summary>데이터 표로 보기</summary>
            <table className="visits-table">
              <thead>
                <tr>
                  <th>날짜</th>
                  <th className="visits-num-th">방문자</th>
                  <th className="visits-num-th">세션</th>
                  <th className="visits-num-th">페이지뷰</th>
                </tr>
              </thead>
              <tbody>
                {daily.map((d) => (
                  <tr key={d.date}>
                    <td>{d.date}</td>
                    <td className="visits-num">{fmt(d.visitors)}</td>
                    <td className="visits-num">{fmt(d.sessions)}</td>
                    <td className="visits-num">{fmt(d.page_views)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
          </Card>
        )}
      </Section>

      <Section
        title="독자층"
        tip="신규는 이 기간에 처음 방문한 브라우저, 재방문은 이전에도 온 적 있는 브라우저입니다. 표본이 작을 때는 참고용으로만 보세요."
      >
        <div className="admin-stats-grid">
          <StatTile label="신규 방문자" value={fmt(totals.new_visitors)} />
          <StatTile label="재방문자" value={fmt(totals.returning_visitors)} />
          <StatTile
            label="재방문율"
            value={totals.visitors ? pct(totals.returning_visitors / totals.visitors) : '—'}
          />
          <StatTile
            label="이탈률"
            value={pct(totals.bounce_rate)}
            hint="한 페이지만 보고 떠난 세션"
          />
          <StatTile label="로그인 사용자" value={fmt(totals.signed_in_users)} />
        </div>
      </Section>

      <Section
        title={
          timing.peak_hour !== null && timing.peak_day_of_week !== null
            ? `언제 들어오나 — 피크 ${timing.peak_hour}시 · ${DOW_LABELS[timing.peak_day_of_week]}요일`
            : '언제 들어오나'
        }
        tip="방문이 아니라 페이지뷰를 시간대(KST)·요일로 나눈 분포입니다. 가장 진한 막대가 피크이며 발행·공지 발송 시점을 잡는 데 씁니다."
      >
        <div className="visits-chart-pair">
          <Card>
          <ChartErrorBoundary>
            <Suspense fallback={<div className="admin-loading">차트 로딩 중...</div>}>
              <Plot
                data={[
                  {
                    type: 'bar',
                    x: Array.from({ length: 24 }, (_, h) => `${h}`),
                    y: timing.hour_of_day,
                    marker: { color: peakColors(timing.hour_of_day, timing.peak_hour, colors.bar), line: { width: 0 } },
                    hovertemplate: '%{x}시 · 페이지뷰 %{y}<extra></extra>',
                  },
                ]}
                layout={{
                  ...BASE_LAYOUT,
                  height: 200,
                  bargap: 0.35,
                  margin: { t: 24, b: 30, l: 30, r: 6 },
                  title: { text: '시간대 (KST) · 세로축=페이지뷰', font: { size: 12, color: 'var(--text-muted)' } },
                  xaxis: { color: 'var(--text-faint)', dtick: 2 },
                  yaxis: { gridcolor: 'rgba(128,128,128,0.12)', color: 'var(--text-faint)' },
                }}
                config={{ displayModeBar: false, responsive: true }}
                style={{ width: '100%' }}
              />
            </Suspense>
          </ChartErrorBoundary>
          </Card>
          <Card>
          <ChartErrorBoundary>
            <Suspense fallback={<div className="admin-loading">차트 로딩 중...</div>}>
              <Plot
                data={[
                  {
                    type: 'bar',
                    x: DOW_LABELS,
                    y: timing.day_of_week,
                    marker: { color: peakColors(timing.day_of_week, timing.peak_day_of_week, colors.bar), line: { width: 0 } },
                    hovertemplate: '%{x}요일 · 페이지뷰 %{y}<extra></extra>',
                  },
                ]}
                layout={{
                  ...BASE_LAYOUT,
                  height: 200,
                  bargap: 0.35,
                  margin: { t: 24, b: 30, l: 30, r: 6 },
                  title: { text: '요일 · 세로축=페이지뷰', font: { size: 12, color: 'var(--text-muted)' } },
                  xaxis: { color: 'var(--text-faint)' },
                  yaxis: { gridcolor: 'rgba(128,128,128,0.12)', color: 'var(--text-faint)' },
                }}
                config={{ displayModeBar: false, responsive: true }}
                style={{ width: '100%' }}
              />
            </Suspense>
          </ChartErrorBoundary>
          </Card>
        </div>
      </Section>

      <Section
        title="인기 페이지"
        tip="동의 방문자 기준 페이지뷰 순입니다. 봇은 제외되며 크롤러 트래픽은 아래 AI 섹션에서 봅니다."
      >
        {report.top_pages.length === 0 ? (
          <EmptyState>이 기간에 집계된 페이지뷰가 없습니다.</EmptyState>
        ) : (
          <Card>
            <table className="visits-table">
              <thead>
                <tr>
                  <th>페이지</th>
                  <th className="visits-num-th">페이지뷰</th>
                  <th className="visits-num-th">방문자</th>
                </tr>
              </thead>
              <tbody>
                {report.top_pages.map((p) => (
                  <tr key={p.path}>
                    <td className="visits-path">{p.path}</td>
                    <BarCell value={p.page_views} max={report.top_pages[0].page_views} />
                    <td className="visits-num">{fmt(p.visitors)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </Section>

      <Section
        title="어디로 들어와서 남는가"
        tip="세션이 처음 도착한 페이지(랜딩)별 참여율입니다. 참여율 = 2페이지 이상 봤거나 제품 이벤트(검색·북마크 등)를 남긴 세션의 비율. 낮으면 유입은 되지만 읽히지 않는다는 뜻이고, '즉시 이탈 많음'은 세션 5건 이상에서 참여율 30% 미만인 랜딩에 붙습니다."
      >
        {report.landing.length === 0 ? (
          <EmptyState>이 기간에 랜딩 데이터가 없습니다.</EmptyState>
        ) : (
          <Card>
            <table className="visits-table">
              <thead>
                <tr>
                  <th>첫 페이지</th>
                  <th className="visits-num-th">세션</th>
                  <th className="visits-num-th">참여율</th>
                </tr>
              </thead>
              <tbody>
                {report.landing.map((p) => (
                  <tr key={p.path}>
                    <td className="visits-path">{p.path}</td>
                    <BarCell value={p.sessions} max={report.landing[0].sessions} />
                    <td className="visits-num">
                      {pct(p.engaged_rate)}
                      {p.engaged_rate < 0.3 && p.sessions >= 5 && (
                        <span className="visits-flag">즉시 이탈 많음</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </Section>

      <Band label="AI · 유입" />

      <Section
        title="AI 크롤러·인용 유입"
        tip="이 섹션만 nginx 접근 로그에서 집계하며 사람 방문 지표와 겹치지 않습니다."
        note="색인 크롤 → 답변용 fetch → 클릭 유입 3단계로 봅니다."
      >
        {!ai.available ? (
          <EmptyState>
            nginx 로그를 읽을 수 없어 크롤러 지표를 표시할 수 없습니다
            {ai.reason ? ` (${ai.reason})` : ''}.
          </EmptyState>
        ) : (
          <>
            <div className="admin-stats-grid">
              <StatTile
                label="AI 봇 히트"
                value={fmt((ai.bots ?? []).reduce((sum, b) => sum + b.hits, 0))}
                hint="색인 크롤러 요청(사람 방문 아님)"
              />
              <StatTile
                label="AI 인용 fetch"
                value={fmt(ai.citation_clicks ?? 0)}
                hint="답변 위해 페이지를 가져간 횟수"
              />
              <StatTile
                label="AI 클릭 유입"
                value={fmt(ai.ai_referral_hits ?? 0)}
                hint="AI 답변 링크로 실제 방문"
              />
            </div>
            <div className="visits-chart-pair">
              <Card>
                <p className="visits-subhead">
                  색인 크롤러
                  <InfoTip label="색인 크롤러 설명">
                    오류(빨간 숫자)가 많으면 크롤러가 해당 콘텐츠를 못 읽고 있다는 신호입니다.
                  </InfoTip>
                </p>
                <table className="visits-table">
                  <thead>
                    <tr>
                      <th>봇</th>
                      <th className="visits-num-th">히트</th>
                      <th className="visits-num-th">정상</th>
                      <th className="visits-num-th">오류</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(ai.bots ?? []).map((b) => (
                      <tr key={b.bot}>
                        <td>{b.bot}</td>
                        <td className="visits-num">{fmt(b.hits)}</td>
                        <td className="visits-num">{fmt(b.ok)}</td>
                        <td className="visits-num">
                          {b.errors > 0 ? <span className="visits-flag">{fmt(b.errors)}</span> : 0}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
              <div className="visits-card-stack">
                {(ai.crawled_pages?.length ?? 0) > 0 && (
                  <Card>
                    <details className="visits-drill">
                      <summary className="visits-subhead">AI가 크롤한 페이지 (색인 커버리지)</summary>
                      <table className="visits-table">
                        <thead>
                          <tr>
                            <th>페이지</th>
                            <th className="visits-num-th">크롤</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(ai.crawled_pages ?? []).map((p) => (
                            <tr key={p.path}>
                              <td className="visits-path">{p.path}</td>
                              <td className="visits-num">{fmt(p.hits)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </details>
                  </Card>
                )}
                {(ai.citation_paths?.length ?? 0) > 0 && (
                  <Card>
                    <details className="visits-drill">
                      <summary className="visits-subhead">AI 답변에서 클릭된 페이지 (GEO 성과)</summary>
                      <table className="visits-table">
                        <thead>
                          <tr>
                            <th>페이지</th>
                            <th className="visits-num-th">fetch</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(ai.citation_paths ?? []).map((p) => (
                            <tr key={p.path}>
                              <td className="visits-path">{p.path}</td>
                              <td className="visits-num">{fmt(p.hits)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </details>
                  </Card>
                )}
              </div>
            </div>
          </>
        )}
      </Section>

      <Section
        title="검색·소셜 유입"
        tip="nginx referrer 기준 실제 외부 유입 채널입니다. 퍼스트파티 payload는 개인정보 보호를 위해 referrer를 지우므로 이 채널 구분은 로그에서만 볼 수 있습니다."
      >
        {(ai.channels?.length ?? 0) === 0 ? (
          <EmptyState>이 기간에 집계된 외부 검색·소셜 유입이 없습니다.</EmptyState>
        ) : (
          <Card>
            <table className="visits-table">
              <thead>
                <tr>
                  <th>채널</th>
                  <th className="visits-num-th">방문</th>
                </tr>
              </thead>
              <tbody>
                {(ai.channels ?? []).map((c) => (
                  <tr key={c.channel}>
                    <td>{c.channel}</td>
                    <BarCell value={c.hits} max={ai.channels![0].hits} />
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </Section>

      <Section title="유입 경로 (UTM)">
        {report.acquisition.utm_sources.length === 0 ? (
          <EmptyState>
            UTM 파라미터가 붙은 링크로 들어온 방문이 없습니다. 캠페인·뉴스레터 링크에 UTM을 달면
            여기에 채널별로 잡힙니다. AI·검색 리퍼럴은 위 섹션, 전체 채널 구분은 GA4 연동 후
            제공됩니다.
          </EmptyState>
        ) : (
          <Card>
            <table className="visits-table">
              <thead>
                <tr>
                  <th>소스</th>
                  <th>매체</th>
                  <th className="visits-num-th">페이지뷰</th>
                  <th className="visits-num-th">세션</th>
                </tr>
              </thead>
              <tbody>
                {report.acquisition.utm_sources.map((s) => (
                  <tr key={`${s.utm_source}/${s.utm_medium}`}>
                    <td>{s.utm_source}</td>
                    <td>{s.utm_medium ?? '-'}</td>
                    <td className="visits-num">{fmt(s.page_views)}</td>
                    <td className="visits-num">{fmt(s.sessions)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </Section>

      {report.ga4.available && (
        <Section
          title="GA4 채널"
          tip="GA4가 집계한 소스/매체별 채널입니다. GA4는 동의 기반 표본이라 퍼스트파티 지표보다 수치가 작을 수 있습니다."
        >
          <Card>
          <table className="visits-table">
            <thead>
              <tr>
                <th>소스</th>
                <th>매체</th>
                <th className="visits-num-th">사용자</th>
                <th className="visits-num-th">세션</th>
              </tr>
            </thead>
            <tbody>
              {report.ga4.channels.map((c) => (
                <tr key={`${c.source}/${c.medium}`}>
                  <td>{c.source}</td>
                  <td>{c.medium}</td>
                  <td className="visits-num">{fmt(c.users)}</td>
                  <td className="visits-num">{fmt(c.sessions)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </Card>
        </Section>
      )}

      <Band label="제품" />

      <Section
        title="전환 퍼널"
        tip="세션 단위 순차 전환입니다. 각 단계는 같은 세션 안에서 앞 단계를 거친 뒤 해당 이벤트를 남긴 세션 수이며, 전환율은 첫 단계 대비 비율입니다. 표본이 작으면 비율이 크게 흔들리니 건수를 함께 보세요."
      >
        {funnels.every((f) => (f.steps[0]?.count ?? 0) === 0) ? (
          <EmptyState>이 기간에 퍼널 첫 단계에 도달한 세션이 없습니다.</EmptyState>
        ) : (
          <div className="visits-funnel-grid">
            {funnels.map((f) => (
              <FunnelChart key={f.id} funnel={f} />
            ))}
          </div>
        )}
      </Section>

      <Section
        title="딥리뷰 결과"
        tip="딥리뷰를 시작한 세션이 완료됐는지, 실패했는지, 아니면 완료·실패 없이 이탈했는지를 나눕니다. 시작→완료 이탈 중 '실패'와 '그냥 떠남'을 구분해 줍니다."
      >
        {reviewOutcome.started === 0 ? (
          <EmptyState>이 기간에 시작된 딥리뷰가 없습니다.</EmptyState>
        ) : (
          <ReviewOutcome outcome={reviewOutcome} />
        )}
      </Section>

      <Section
        title="제품 이벤트"
        tip="방문자가 남긴 핵심 행동(검색·로그인·딥리뷰·북마크 등)의 발생 횟수로, 트래픽이 실제 제품 사용으로 이어졌는지 봅니다."
      >
        {productEvents.length === 0 ? (
          <EmptyState>이 기간에 기록된 제품 이벤트가 없습니다.</EmptyState>
        ) : (
          <div className="admin-stats-grid">
            {productEvents.map(([name, count]) => (
              <StatTile key={name} label={EVENT_LABELS[name] ?? name} value={fmt(count)} />
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}

export default AdminVisitsReport;
