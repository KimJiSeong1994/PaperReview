import { Component, lazy, Suspense, useCallback, useEffect, useState } from 'react';
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
  search: '검색',
  login: '로그인',
  sign_up: '가입',
  deep_review_start: '딥리뷰 시작',
  deep_review_complete: '딥리뷰 완료',
  bookmark_save: '북마크',
  report_download: '리포트 다운로드',
  poster_generate_start: '포스터 시작',
  poster_generate_complete: '포스터 완료',
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

function StatTile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="admin-stat-card">
      <p className="admin-stat-label">{label}</p>
      <p className="admin-stat-value">{value}</p>
      {hint && <p className="visits-stat-hint">{hint}</p>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="visits-section">
      <h3 className="visits-section-title">{title}</h3>
      {children}
    </section>
  );
}

/** Chart/table container matching the app's card tone (.admin-stat-card). */
function Card({ children }: { children: ReactNode }) {
  return <div className="visits-card">{children}</div>;
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
        </span>
      </div>

      {(report.ga4.state === 'pending' || report.ga4.state === 'failed') && (
        <div className={`visits-banner visits-banner--${report.ga4.state}`}>
          {report.ga4.state === 'pending' ? (
            <>
              GA4 연동 대기 중입니다 — GA4 속성에 방문 데이터가 아직 쌓이지 않아 BigQuery
              내보내기 데이터셋이 생성되지 않았습니다. 방문자가 쿠키 동의 후 유입되기
              시작하면 자동으로 연결됩니다. 아래 지표는 동의와 무관하게 수집되는 퍼스트파티
              기준입니다.
            </>
          ) : (
            <>
              GA4 동기화 오류 ({report.ga4.last_run?.sync_finished_at?.slice(0, 10)}):{' '}
              {report.ga4.last_run?.error ?? 'unknown error'} — 아래 지표는 퍼스트파티 수집
              기준입니다.
            </>
          )}
        </div>
      )}

      <Section title="방문 추이">
        <div className="admin-stats-grid">
          <StatTile label="방문자" value={totals.visitors} hint={`일 평균 ${totals.avg_daily_visitors}`} />
          <StatTile label="세션" value={totals.sessions} />
          <StatTile label="페이지뷰" value={totals.page_views} />
          <StatTile
            label="신규 / 재방문"
            value={`${totals.new_visitors} / ${totals.returning_visitors}`}
          />
          <StatTile label="로그인 사용자" value={totals.signed_in_users} />
        </div>
        {daily.length > 1 && (
          <Card>
          <ChartErrorBoundary>
            <Suspense fallback={<div className="admin-loading">차트 로딩 중...</div>}>
              <Plot
                data={[
                  {
                    type: 'scatter',
                    mode: 'lines',
                    name: '방문자',
                    x: daily.map((d) => d.date),
                    y: daily.map((d) => d.visitors),
                    line: { color: colors.visitors, width: 2 },
                    hovertemplate: '%{x}<br>방문자 %{y}<extra></extra>',
                  },
                  {
                    type: 'scatter',
                    mode: 'lines',
                    name: '세션',
                    x: daily.map((d) => d.date),
                    y: daily.map((d) => d.sessions),
                    line: { color: colors.sessions, width: 2 },
                    hovertemplate: '%{x}<br>세션 %{y}<extra></extra>',
                  },
                ]}
                layout={{
                  ...BASE_LAYOUT,
                  height: 260,
                  margin: { t: 10, b: 40, l: 36, r: 10 },
                  hovermode: 'x unified',
                  legend: { orientation: 'h', y: 1.12, font: { color: 'var(--text-muted)' } },
                  xaxis: { gridcolor: 'rgba(128,128,128,0.08)', color: 'var(--text-faint)' },
                  yaxis: {
                    gridcolor: 'rgba(128,128,128,0.12)',
                    color: 'var(--text-faint)',
                    rangemode: 'tozero',
                  },
                }}
                config={{ displayModeBar: false, responsive: true }}
                style={{ width: '100%' }}
              />
            </Suspense>
          </ChartErrorBoundary>
          <details className="visits-table-toggle">
            <summary>데이터 표로 보기</summary>
            <table className="visits-table">
              <thead>
                <tr>
                  <th>날짜</th>
                  <th>방문자</th>
                  <th>세션</th>
                  <th>페이지뷰</th>
                </tr>
              </thead>
              <tbody>
                {daily.map((d) => (
                  <tr key={d.date}>
                    <td>{d.date}</td>
                    <td>{d.visitors}</td>
                    <td>{d.sessions}</td>
                    <td>{d.page_views}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
          </Card>
        )}
      </Section>

      <Section
        title={
          timing.peak_hour !== null && timing.peak_day_of_week !== null
            ? `언제 들어오나 — 피크 ${timing.peak_hour}시 · ${DOW_LABELS[timing.peak_day_of_week]}요일`
            : '언제 들어오나'
        }
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
                    marker: { color: colors.bar, line: { width: 0 } },
                    hovertemplate: '%{x}시 · 페이지뷰 %{y}<extra></extra>',
                  },
                ]}
                layout={{
                  ...BASE_LAYOUT,
                  height: 200,
                  bargap: 0.35,
                  margin: { t: 24, b: 30, l: 30, r: 6 },
                  title: { text: '시간대 (KST)', font: { size: 12, color: 'var(--text-muted)' } },
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
                    marker: { color: colors.bar, line: { width: 0 } },
                    hovertemplate: '%{x}요일 · 페이지뷰 %{y}<extra></extra>',
                  },
                ]}
                layout={{
                  ...BASE_LAYOUT,
                  height: 200,
                  bargap: 0.35,
                  margin: { t: 24, b: 30, l: 30, r: 6 },
                  title: { text: '요일', font: { size: 12, color: 'var(--text-muted)' } },
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

      <Section title="인기 페이지">
        <Card>
          <table className="visits-table">
            <thead>
              <tr>
                <th>페이지</th>
                <th>페이지뷰</th>
                <th>방문자</th>
              </tr>
            </thead>
            <tbody>
              {report.top_pages.map((p) => (
                <tr key={p.path}>
                  <td className="visits-path">{p.path}</td>
                  <td>{p.page_views}</td>
                  <td>{p.visitors}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </Section>

      <Section title="어디로 들어와서 남는가">
        <Card>
          <table className="visits-table">
            <thead>
              <tr>
                <th>첫 페이지</th>
                <th>세션</th>
                <th>참여율</th>
              </tr>
            </thead>
            <tbody>
              {report.landing.map((p) => (
                <tr key={p.path}>
                  <td className="visits-path">{p.path}</td>
                  <td>{p.sessions}</td>
                  <td>
                    {Math.round(p.engaged_rate * 100)}%
                    {p.engaged_rate < 0.3 && p.sessions >= 5 && (
                      <span className="visits-flag">즉시 이탈 많음</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <p className="visits-note">참여율 = 페이지를 2개 이상 보거나 제품 이벤트를 남긴 세션 비율.</p>
      </Section>

      <Section title="AI 크롤러·인용 유입">
        {!ai.available ? (
          <p className="visits-note">
            nginx 로그를 읽을 수 없어 크롤러 지표를 표시할 수 없습니다
            {ai.reason ? ` (${ai.reason})` : ''}.
          </p>
        ) : (
          <>
            <div className="admin-stats-grid">
              <StatTile
                label="AI 인용 클릭"
                value={ai.citation_clicks ?? 0}
                hint="ChatGPT·Claude·Perplexity 사용자 fetch"
              />
              <StatTile
                label="AI 리퍼럴 방문"
                value={ai.ai_referral_hits ?? 0}
                hint="브라우저 referrer 기준"
              />
              <StatTile
                label="AI 봇 히트"
                value={(ai.bots ?? []).reduce((sum, b) => sum + b.hits, 0)}
              />
            </div>
            <div className="visits-chart-pair">
              <Card>
                <table className="visits-table">
                  <thead>
                    <tr>
                      <th>봇</th>
                      <th>히트</th>
                      <th>정상</th>
                      <th>오류</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(ai.bots ?? []).map((b) => (
                      <tr key={b.bot}>
                        <td>{b.bot}</td>
                        <td>{b.hits}</td>
                        <td>{b.ok}</td>
                        <td>{b.errors > 0 ? <span className="visits-flag">{b.errors}</span> : 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
              <div className="visits-card-stack">
                {(ai.citation_paths?.length ?? 0) > 0 && (
                  <Card>
                    <p className="visits-subhead">인용 클릭된 페이지</p>
                    <table className="visits-table">
                      <tbody>
                        {(ai.citation_paths ?? []).map((p) => (
                          <tr key={p.path}>
                            <td className="visits-path">{p.path}</td>
                            <td>{p.hits}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </Card>
                )}
                {(ai.ai_referral_sources?.length ?? 0) > 0 && (
                  <Card>
                    <p className="visits-subhead">AI 리퍼럴 출처</p>
                    <table className="visits-table">
                      <tbody>
                        {(ai.ai_referral_sources ?? []).map((s) => (
                          <tr key={s.source}>
                            <td>{s.source}</td>
                            <td>{s.hits}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </Card>
                )}
              </div>
            </div>
          </>
        )}
      </Section>

      <Section title="제품 이벤트">
        {productEvents.length === 0 ? (
          <p className="visits-note">이 기간에 기록된 제품 이벤트가 없습니다.</p>
        ) : (
          <div className="admin-stats-grid">
            {productEvents.map(([name, count]) => (
              <StatTile key={name} label={EVENT_LABELS[name] ?? name} value={count} />
            ))}
          </div>
        )}
      </Section>

      <Section title="유입 경로 (UTM)">
        {report.acquisition.utm_sources.length === 0 ? (
          <p className="visits-note">
            UTM 파라미터가 붙은 유입이 없습니다. AI·검색 리퍼럴은 위 AI 섹션에, 전체 채널 구분은
            GA4 동기화 복구 후 제공됩니다.
          </p>
        ) : (
          <Card>
            <table className="visits-table">
              <thead>
                <tr>
                  <th>소스</th>
                  <th>매체</th>
                  <th>페이지뷰</th>
                  <th>세션</th>
                </tr>
              </thead>
              <tbody>
                {report.acquisition.utm_sources.map((s) => (
                  <tr key={`${s.utm_source}/${s.utm_medium}`}>
                    <td>{s.utm_source}</td>
                    <td>{s.utm_medium ?? '-'}</td>
                    <td>{s.page_views}</td>
                    <td>{s.sessions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </Section>

      {report.ga4.available && (
        <Section title="GA4 채널">
          <Card>
          <table className="visits-table">
            <thead>
              <tr>
                <th>소스</th>
                <th>매체</th>
                <th>사용자</th>
                <th>세션</th>
              </tr>
            </thead>
            <tbody>
              {report.ga4.channels.map((c) => (
                <tr key={`${c.source}/${c.medium}`}>
                  <td>{c.source}</td>
                  <td>{c.medium}</td>
                  <td>{c.users}</td>
                  <td>{c.sessions}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </Card>
        </Section>
      )}
    </div>
  );
}

export default AdminVisitsReport;
