import { Component, lazy, Suspense, useEffect, useId, useState } from 'react';
import type { ReactNode } from 'react';
import {
  fetchAdminVisitsReport,
  fetchSampleConversations,
  type AdminWindowDays,
  resolveEstimatedAnswerFetches,
  type AdminVisitsReport as VisitsReportData,
} from '../api/client';
import type { SampleSummary } from '../types';
import { useBlock } from './adminShared';
import { AdminTabHeader, BlockError } from './AdminUi';
import AdminGrowthReport from './AdminGrowthReport';

const Plot = lazy(() => import('../PlotlyChart'));

// Report-local violet palette: the Visitors surface intentionally stays light
// and editorial even when the surrounding admin shell uses the dark theme.
const SERIES = {
  visitors: '#4f46e5',
  sessions: '#9b5cff',
  bar: '#5b4df5',
};

const DOW_LABELS = ['일', '월', '화', '수', '목', '금', '토'];
const EVENT_LABELS: Record<string, string> = {
  page_view: '방문',
  login: '로그인',
  sign_up: '가입',
  sample_view: '샘플 노출 (홈 기본 포함)',
  sample_cta_click: '이어서 묻기 클릭',
  conversation_start: '대화 생성',
};
const SAMPLE_FUNNEL_ID = 'sample_to_conversation';

const GA4_STATE_COPY: Record<VisitsReportData['ga4']['state'], string> = {
  connected: '동기화는 정상이며 선택 기간의 채널 데이터를 표시합니다.',
  pending: 'BigQuery 내보내기 데이터셋이 아직 준비되지 않아 연동을 기다리고 있습니다.',
  failed: '최근 GA4 동기화가 실패했습니다. 오류와 권한 설정을 확인해야 합니다.',
  never_run: 'GA4 동기화 실행 이력이 없습니다.',
};

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

function InsightCard({
  eyebrow,
  headline,
  body,
}: {
  eyebrow: string;
  headline: ReactNode;
  body: ReactNode;
}) {
  return (
    <article className="visits-insight-card">
      <p className="visits-insight-eyebrow">{eyebrow}</p>
      <h3 className="visits-insight-headline">{headline}</h3>
      <p className="visits-insight-body">{body}</p>
    </article>
  );
}

function Band({
  label,
  title,
  description,
}: {
  label: string;
  title: string;
  description: string;
}) {
  return (
    <header className="visits-band" aria-label={label}>
      <span className="visits-band-eyebrow">{label}</span>
      <h2>{title}</h2>
      <p>{description}</p>
    </header>
  );
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

/** Browser measurements remain independent of account growth and its availability. */
function VisitsDetails({ days }: { days: AdminWindowDays }) {
  const colors = SERIES;
  const visits = useBlock(fetchAdminVisitsReport, days);
  const report = visits.data;
  // Public sample list, only for titles; a failure leaves the slugs as labels.
  const [sampleList, setSampleList] = useState<SampleSummary[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    fetchSampleConversations(controller.signal)
      .then((list) => { if (!controller.signal.aborted) setSampleList(list); })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  if (visits.error) return <BlockError block={visits} label="방문 리포트" />;
  if (!report) return <div className="admin-loading">방문 리포트 로딩 중...</div>;

  const { totals, daily } = report.traffic;
  const { timing } = report;
  const ai = report.ai;
  const answerFetches = resolveEstimatedAnswerFetches(ai);
  const answerFetchPaths = ai.available
    ? ai.estimated_answer_fetch_paths ?? ai.citation_paths ?? []
    : [];
  if (answerFetches.mismatch && import.meta.env.DEV) {
    console.warn(
      'Admin visits report metric mismatch: estimated_answer_fetches differs from citation_clicks',
      { canonical: ai.estimated_answer_fetches, legacy: ai.citation_clicks },
    );
  }
  const answerFetchLabel = answerFetches.value == null ? '확인 불가' : fmt(answerFetches.value);
  const answerFetchHeadline = answerFetches.value == null ? answerFetchLabel : `${answerFetchLabel}번`;
  const referralHits = ai.available ? ai.ai_referral_hits : undefined;
  const referralHitsLabel = referralHits == null ? '확인 불가' : fmt(referralHits);
  const referralHitsHeadline = referralHits == null ? referralHitsLabel : `${referralHitsLabel}번`;
  const botRows = ai.bots ?? [];
  const legacyBotHits = botRows.reduce((sum, bot) => sum + bot.hits, 0);
  const verifiedIndexingHits = ai.verified_indexing_hits ?? legacyBotHits;
  const verifiedContentErrors =
    ai.verified_content_errors ?? botRows.reduce((sum, bot) => sum + bot.errors, 0);
  const suspectedScanHits = ai.suspected_scan_hits ?? 0;
  const observedLogDays = ai.log_window?.observed_days ?? days;
  const crawlerWindowLimited = observedLogDays > 0 && observedLogDays < days;
  const productEvents = Object.entries(report.product_events)
    .filter(([name]) => Object.hasOwn(EVENT_LABELS, name))
    .sort((a, b) => b[1] - a[1]);
  // Guard against an older backend during rollout that predates these keys.
  const allFunnels = report.funnels ?? [];
  const sampleFunnel = allFunnels.find((f) => f.id === SAMPLE_FUNNEL_ID) ?? null;
  // Every public sample gets a row (0 when no event names it); slugs seen only in events follow.
  const sampleStats = new Map((report.samples ?? []).map((row) => [row.slug, row]));
  const sampleRows = [
    ...sampleList.map((item) => ({ slug: item.slug, title: item.title })),
    ...[...sampleStats.keys()].filter((slug) => !sampleList.some((item) => item.slug === slug)).map((slug) => ({ slug, title: slug })),
  ].map(({ slug, title }) => {
    const row = sampleStats.get(slug);
    return { slug, title, page_views: row?.page_views ?? 0, card_views: row?.card_views ?? 0, cta_clicks: row?.cta_clicks ?? 0 };
  });
  // Older backends did not expose measurement metadata. Keep the fallback so
  // a rolling deployment remains readable while preferring server definitions.
  const measurement = report.measurement ?? {
    population: 'consented_browser_events' as const,
    session_definition: 'browser_tab_lifetime' as const,
    first_event_at: null,
    last_event_at: null,
    history_days: daySpan(report.window.start, report.window.end),
    observed_days: daily.length,
    event_count: 0,
  };
  const coveredDays = measurement.history_days;
  const windowLimited = coveredDays > 0 && coveredDays < days;
  const lastEventLabel = measurement.last_event_at
    ? new Date(measurement.last_event_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })
    : '수집 기록 없음';

  return (
    <div className="admin-dashboard visits-report">
      <AdminTabHeader
        id="admin-visits-title"
        title="방문·유입"
        range={`${report.window.start} — ${report.window.end} · KST${windowLimited ? ` · 집계 ${coveredDays}일분` : ''}`}
      />

      <section className="visits-summary" aria-labelledby="visits-summary-title">
        <span className="visits-summary-kicker">핵심 요약</span>
        <h2 id="visits-summary-title">이번 기간을 한 문장씩 읽어보세요</h2>
        <p className="visits-summary-copy">세부 지표보다 먼저 방문, 참여, 외부 연결의 규모를 보여줍니다.</p>
        <div className="visits-insight-grid">
          <InsightCard
            eyebrow={`최근 ${days}일 방문`}
            headline={<>{fmt(totals.visitors)}명이 {fmt(totals.sessions)}번 방문</>}
            body={`한 사람당 평균 ${totals.visitors ? (totals.sessions / totals.visitors).toFixed(1) : '0'}회 방문했습니다.`}
          />
          <InsightCard
            eyebrow={`최근 ${days}일 참여`}
            headline={<>{fmt(totals.engaged_sessions)}개 세션이 의미 있게 참여</>}
            body={`전체 세션의 ${pct(totals.engaged_rate)}가 두 페이지 이상 보거나 핵심 행동을 남겼습니다.`}
          />
          <InsightCard
            eyebrow={`최근 ${days}일 AI 연결`}
            headline={<>답변 fetch {answerFetchHeadline} · 실제 유입 {referralHitsHeadline}</>}
            body="AI가 콘텐츠를 가져간 횟수와 답변 링크를 통해 실제로 들어온 방문을 나눠 봅니다."
          />
        </div>
      </section>

      <p
        className="visits-method-line"
        title={`방문·세션·페이지뷰는 분석에 동의한 브라우저의 퍼스트파티 이벤트 표본입니다. 방문자는 브라우저 식별자, 세션은 같은 브라우저 탭이 유지되는 동안의 이벤트 묶음이므로 전체 트래픽이나 GA식 30분 세션과 동일하지 않습니다. 사람 지표는 KST 달력일, AI·외부 유입은 nginx 로그의 최근 시간 범위로 집계합니다. 선택 기간 이벤트는 ${fmt(measurement.event_count)}건입니다.`}
      >
        측정 기준: 동의 표본 · 활동일 {measurement.observed_days}일 · 이벤트 {fmt(measurement.event_count)}건 · 마지막 {lastEventLabel} · 30분 비활동 기준 세션이 아닙니다
      </p>

      <Band
        label="사람 방문"
        title="도달과 이용"
        description="얼마나 발견됐고, 어떤 경로와 시점에 들어왔으며, 다시 찾아왔는지 봅니다."
      />

      <Section
        title="방문 추이"
        tip="방문자는 동의 브라우저 식별자의 기간 순사용자 수입니다. 세션은 같은 브라우저 탭의 수명 동안 유지되는 이벤트 묶음이며, 30분 비활동 기준 세션이 아닙니다."
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
                    fillcolor: `${colors.sessions}18`,
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
                    fillcolor: `${colors.visitors}20`,
                    hovertemplate: '%{x}<br>방문자 %{y}<extra></extra>',
                  },
                ]}
                layout={{
                  ...BASE_LAYOUT,
                  height: 260,
                  margin: { t: 10, b: 40, l: 36, r: 10 },
                  hovermode: 'x unified',
                  hoverlabel: {
                    bgcolor: 'rgba(255,255,255,0.98)',
                    bordercolor: 'rgba(15,23,42,0.10)',
                    font: {
                      color: '#1e293b',
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
          {/* The chart's text alternative: read by screen readers, not drawn. */}
          <div className="admin-sr-only">
            <table className="visits-table" aria-label="일별 방문 표">
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
          </div>
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
        tip="세션이 처음 도착한 페이지(랜딩)별 참여율입니다. 참여율 = 2페이지 이상 봤거나 제품 이벤트를 남긴 세션의 비율. 낮으면 유입은 되지만 읽히지 않는다는 뜻이고, '즉시 이탈 많음'은 세션 5건 이상에서 참여율 30% 미만인 랜딩에 붙습니다."
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

      <Band
        label="AI · 유입"
        title="AI와 외부 유입"
        description="검색·소셜·AI 답변이 콘텐츠 발견과 실제 방문으로 이어지는 흐름을 봅니다."
      />

      <Section
        title="AI 크롤러·인용 유입"
        tip="이 섹션만 nginx 접근 로그에서 집계하며 사람 방문 지표와 겹치지 않습니다."
        note="검증된 색인 크롤 → 성공한 답변용 fetch → 클릭 유입 3단계로 봅니다."
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
                label="검증된 색인 크롤"
                value={fmt(verifiedIndexingHits)}
                hint="공식 IP에서 공개 색인 문서를 정상 수신한 요청"
              />
              <StatTile
                label="AI 답변 fetch (추정)"
                value={answerFetchLabel}
                hint="성공한 공개 콘텐츠 fetch만 포함"
              />
              <StatTile
                label="AI 클릭 유입"
                value={referralHitsLabel}
                hint="AI 답변 링크로 실제 방문"
              />
              <StatTile
                label="스캔 의심 요청"
                value={fmt(suspectedScanHits)}
                hint="민감 경로 탐색 또는 여러 봇 이름을 바꿔 쓴 요청"
              />
            </div>
            {(crawlerWindowLimited || (ai.verification_failures?.length ?? 0) > 0) && (
              <p className="visits-ai-quality-note" role="status">
                {crawlerWindowLimited && (
                  <span>선택한 {days}일 중 nginx 로그 {observedLogDays}일분을 확인했습니다.</span>
                )}
                {(ai.verification_failures?.length ?? 0) > 0 && (
                  <span>
                    공식 IP 확인 불가: {(ai.verification_failures ?? []).join(', ')}. 해당 요청은
                    미검증으로 유지됩니다.
                  </span>
                )}
              </p>
            )}
            <div className="visits-chart-pair">
              <Card>
                <p className="visits-subhead">
                  크롤러 신뢰도
                  <InfoTip label="색인 크롤러 설명">
                    콘텐츠 오류는 공식 IP로 검증된 봇이 실제 색인 문서를 읽지 못한 경우만
                    계산합니다. 대체 사이트맵·이전 정적 파일은 탐색성 404, 민감 경로와 다중 UA는
                    스캔 의심으로 분리합니다.
                  </InfoTip>
                </p>
                <div className="visits-table-scroll">
                  <table className="visits-table visits-crawler-table">
                    <thead>
                      <tr>
                        <th>봇</th>
                        <th className="visits-num-th">전체</th>
                        <th className="visits-num-th">공식 검증</th>
                        <th className="visits-num-th">콘텐츠 정상</th>
                        <th className="visits-num-th">콘텐츠 오류</th>
                        <th className="visits-num-th">탐색·스캔</th>
                      </tr>
                    </thead>
                    <tbody>
                      {botRows.map((b) => (
                        <tr key={b.bot}>
                          <td>{b.bot}</td>
                          <td className="visits-num">{fmt(b.hits)}</td>
                          <td className="visits-num">
                            {b.verification_available ? (
                              fmt(b.verified_hits)
                            ) : (
                              <span className="visits-muted-badge">미지원</span>
                            )}
                          </td>
                          <td className="visits-num">{fmt(b.content_ok ?? 0)}</td>
                          <td className="visits-num">
                            {(b.content_errors ?? 0) > 0 ? (
                              <span className="visits-flag">{fmt(b.content_errors)}</span>
                            ) : (
                              0
                            )}
                          </td>
                          <td className="visits-num">
                            <span className="visits-neutral-badge">
                              {fmt((b.discovery_errors ?? 0) + (b.suspected_scan_hits ?? 0))}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="visits-note">
                  실제 색인 오류 {fmt(verifiedContentErrors)}건 · 탐색성 404{' '}
                  {fmt(ai.discovery_errors ?? 0)}건 · 미검증 요청 {fmt(ai.unverified_hits ?? 0)}건
                </p>
              </Card>
              <div className="visits-card-stack">
                {(ai.crawled_pages?.length ?? 0) > 0 && (
                  <Card>
                    <div className="visits-drill">
                      <h4 className="visits-subhead">검증된 봇이 읽은 페이지 (색인 커버리지)</h4>
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
                    </div>
                  </Card>
                )}
                {answerFetchPaths.length > 0 && (
                  <Card>
                    <div className="visits-drill">
                      <h4 className="visits-subhead">AI 답변이 가져간 페이지 (추정 fetch)</h4>
                      <table className="visits-table">
                        <thead>
                          <tr>
                            <th>페이지</th>
                            <th className="visits-num-th">fetch</th>
                          </tr>
                        </thead>
                        <tbody>
                          {answerFetchPaths.map((p) => (
                            <tr key={p.path}>
                              <td className="visits-path">{p.path}</td>
                              <td className="visits-num">{fmt(p.hits)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
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

      <Section
        title="블로그 유입 경로 (UTM)"
        tip="현재 UTM 집계는 /blog/ 경로의 페이지뷰만 포함하며 서비스 전체 캠페인 성과가 아닙니다."
      >
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

      <Section
        title="GA4 채널"
        tip="GA4가 집계한 소스/매체별 채널입니다. 사용자 값은 일별 total_users 합계여서 선택 기간의 순사용자 수가 아닐 수 있습니다."
      >
        {report.ga4.available ? (
          <Card>
          <table className="visits-table">
            <thead>
              <tr>
                <th>소스</th>
                <th>매체</th>
                <th className="visits-num-th">사용자 · 일별 합</th>
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
        ) : (
          <Card>
            <EmptyState>
              {GA4_STATE_COPY[report.ga4.state]}
              {report.ga4.last_run?.error ? ` 최근 오류: ${report.ga4.last_run.error}` : ''}
            </EmptyState>
          </Card>
        )}
      </Section>

      <Band
        label="전환"
        title="샘플에서 대화로"
        description="비로그인 샘플이 대화로 이어지는지, 샘플을 본 브라우저가 대화를 생성하는지 봅니다. 실제 메시지 이용은 위 계정 지표에서 확인합니다."
      />

      <Section
        title="샘플 → 대화"
        tip="비로그인 샘플이 대화로 이어지는지 봅니다. 샘플 노출 → 이어서 묻기 클릭 → 대화 시작 순서의 세션 퍼널이며, 로그인 단계는 넣지 않습니다. 분석 동의 사용자만 집계해 하한값입니다. 퍼널 첫 단계에는 홈이 기본으로 보여 주는 첫 샘플 노출이 포함되고, 표의 조회·CTA 율은 카드 클릭과 샘플 페이지만 셉니다."
        note="동의 사용자만(하한값) · 퍼널은 홈 기본 노출 포함, 표는 카드 클릭+페이지만"
      >
        <Card>
          {sampleFunnel && (
            <p className="visits-funnel-inline" aria-label={sampleFunnel.label}>
              {sampleFunnel.steps.map((step, i) => (
                <span key={step.event}>
                  {i > 0 && <span className="visits-funnel-arrow" aria-hidden="true">→</span>}
                  {EVENT_LABELS[step.event] ?? step.event} <strong>{fmt(step.count)}</strong>
                  {i > 0 && <small>{sampleFunnel.steps[0].count ? pct(step.rate) : '—'}</small>}
                </span>
              ))}
            </p>
          )}
          {sampleRows.length === 0 ? (
            <EmptyState>공개 샘플이나 샘플 이벤트가 아직 없습니다.</EmptyState>
          ) : (
            <table className="visits-table visits-table--compact">
              <thead>
                <tr>
                  <th>샘플</th>
                  <th className="visits-num-th">페이지 조회</th>
                  {/* card_views = sample_view from a card click or the sample page; the home default is excluded server-side. */}
                  <th className="visits-num-th">샘플 조회 · 카드 클릭+페이지</th>
                  <th className="visits-num-th">CTA 클릭</th>
                  <th className="visits-num-th">CTA 율</th>
                </tr>
              </thead>
              <tbody>
                {sampleRows.map((row) => {
                  // page_view of /samples/<slug> and the sample_page sample_view are the same visit; never add them.
                  const views = row.card_views;
                  return (
                    <tr key={row.slug}>
                      <td>{row.title}</td>
                      <td className="visits-num">{fmt(row.page_views)}</td>
                      <td className="visits-num">{fmt(row.card_views)}</td>
                      <td className="visits-num">{fmt(row.cta_clicks)}</td>
                      <td className="visits-num">{views > 0 ? pct(row.cta_clicks / views) : '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Card>
      </Section>

      <Section
        title="제품 이벤트"
        tip="방문자가 남긴 핵심 행동(로그인·가입·샘플 조회·대화 생성 등)의 발생 횟수로, 트래픽이 실제 제품 사용으로 이어졌는지 봅니다."
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

export default function AdminVisitsReport({ days, onDays }: { days: AdminWindowDays; onDays: (days: AdminWindowDays) => void }) {
  return <div className="admin-tabstack">
    <article className="admin-dashboard visits-report admin-tabview" aria-labelledby="admin-growth-title">
      <AdminTabHeader id="admin-growth-title" title="성장" days={days} onDays={onDays} />
      <AdminGrowthReport days={days} />
    </article>
    <VisitsDetails days={days} />
  </div>;
}
