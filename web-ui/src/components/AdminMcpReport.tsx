import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  fetchAdminMcpReport,
  type AdminMcpReport as McpReportData,
  type AdminMcpWindowDays,
} from '../api/client';
import LazyLoadErrorBoundary from './LazyLoadErrorBoundary';
import './AdminMcpReport.css';

const Plot = lazy(() => import('../PlotlyChart'));
const WINDOWS: AdminMcpWindowDays[] = [7, 28, 90];
const numberFormat = new Intl.NumberFormat('ko-KR');
const DAILY_SERIES = [
  { key: 'requests', name: '서버 요청', color: '#9b5cff', unit: '건', primary: true },
  { key: 'tool_calls', name: '도구 실행', color: '#4f46e5', unit: '건', primary: true },
  { key: 'active_accounts', name: '활성 계정', color: '#0d9488', unit: '계정', primary: true },
  { key: 'jobs_started', name: '작업 시작', color: '#0284c7', unit: '건', primary: false },
  { key: 'jobs_completed', name: '작업 완료', color: '#16a34a', unit: '건', primary: false },
  { key: 'jobs_failed', name: '작업 실패', color: '#e05266', unit: '건', primary: false },
] as const;

const kstDate = (value: string | null) => {
  const timestamp = value ? Date.parse(value) : NaN;
  return Number.isFinite(timestamp) ? new Date(timestamp + 9 * 60 * 60 * 1000).toISOString().slice(0, 10) : null;
};

const count = (value: number) => numberFormat.format(value);
const duration = (value: number | null) => value === null ? '미집계' : `${numberFormat.format(Math.round(value))}ms`;
const rate = (value: number | null) => value === null ? '미집계' : `${(value * 100).toFixed(1)}%`;
const claimedValue = (value: string | null) => value || '미제공';

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <article className="mcp-metric">
      <p>{label}</p>
      <strong>{value}</strong>
      <span>{note}</span>
    </article>
  );
}

function EmptyRows({ columns, children }: { columns: number; children: string }) {
  return <tr><td className="mcp-empty" colSpan={columns}>{children}</td></tr>;
}

function reasonCopy(reason: string | null) {
  if (!reason) return 'MCP 측정 상태를 확인할 수 없습니다.';
  if (['not_instrumented', 'storage_missing', 'not_configured'].includes(reason)) {
    return 'MCP 사용 측정 저장소가 아직 설정되지 않았습니다.';
  }
  return 'MCP 측정 저장소를 현재 조회할 수 없습니다.';
}

const isMissingInstrumentation = (reason: string | null) =>
  reason !== null && ['not_instrumented', 'storage_missing', 'not_configured'].includes(reason);

export default function AdminMcpReport() {
  const [days, setDays] = useState<AdminMcpWindowDays>(28);
  const [includeInternal, setIncludeInternal] = useState(false);
  const [report, setReport] = useState<McpReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  useEffect(() => {
    const id = ++requestId.current;
    const controller = new AbortController();
    queueMicrotask(() => {
      if (controller.signal.aborted) return;
      setLoading(true);
      setError(null);

      void fetchAdminMcpReport(days, includeInternal, controller.signal)
        .then(({ data }) => {
          if (id === requestId.current) setReport(data);
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted || id !== requestId.current) return;
          const detail = (err as { response?: { data?: { detail?: string } }; message?: string });
          setError(detail.response?.data?.detail ?? detail.message ?? 'MCP 사용 리포트를 불러오지 못했습니다.');
        })
        .finally(() => {
          if (id === requestId.current) setLoading(false);
        });
    });

    return () => controller.abort();
  }, [days, includeInternal]);

  if (loading && !report) return <div className="admin-loading">MCP 사용 리포트 로딩 중...</div>;
  if (error && !report) return <div className="mcp-state mcp-state--error" role="alert"><strong>리포트 조회 실패</strong><p>{error}</p></div>;
  if (!report) return null;

  if (!report.available) {
    const missing = isMissingInstrumentation(report.reason);
    return (
      <section className="mcp-report" aria-labelledby="mcp-report-title">
        <Header days={days} setDays={setDays} includeInternal={includeInternal} setIncludeInternal={setIncludeInternal} loading={loading} />
        <div className="mcp-state" role="status">
          <strong>{missing ? 'MCP 사용 측정 설정 없음' : 'MCP 사용 측정 조회 불가'}</strong>
          <p>{reasonCopy(report.reason)}</p>
          {report.reason && <code>{report.reason}</code>}
        </div>
      </section>
    );
  }

  const { totals } = report;
  const measurementStart = kstDate(report.measurement.started_at);
  const dailyValue = (row: McpReportData['daily'][number], key: typeof DAILY_SERIES[number]['key']) => (
    (measurementStart !== null && row.date < measurementStart)
    || (key === 'tool_calls' && !report.measurement.tool_telemetry_available)
      ? null : row[key]
  );
  const unknownJobs = report.jobs.reduce((total, row) => total + row.unknown, 0);
  const measuredZero = totals.requests === 0 && totals.tool_calls === 0 && totals.jobs_started === 0;

  return (
    <section className="mcp-report" aria-labelledby="mcp-report-title">
      <Header days={days} setDays={setDays} includeInternal={includeInternal} setIncludeInternal={setIncludeInternal} loading={loading} report={report} />
      {error && <div className="mcp-inline-error" role="alert">새 데이터를 불러오지 못했습니다: {error}</div>}

      <div className="mcp-trust-note">
        <strong>측정 범위</strong>
        <p>
          서버가 받은 MCP 요청과 작업 수명주기를 집계합니다. 클라이언트·버전·User-Agent는 클라이언트가 보낸 주장값이며 실제 호스트나 사람 수를 증명하지 않습니다.
        </p>
        <p>도구 실행: {report.measurement.tool_telemetry_available ? '업그레이드된 어댑터에서 직접 관측' : '미계측'} · 기존 어댑터, 로컬 옵트아웃 또는 전송 유실의 도구 실행 총량은 알 수 없습니다.</p>
        <p>요청 연결률 {rate(report.measurement.invocation_coverage)} ({count(report.measurement.requests_with_invocation_id)}/{count(report.measurement.claimed_adapter_requests)}) · invocation 헤더가 붙은 어댑터 주장 요청의 비율이며 전체 MCP 수집률이 아닙니다. 기존·미귀속 요청 {count(report.measurement.legacy_or_unattributed_requests)}건.</p>
        <p>측정 시작 {report.measurement.started_at ?? '기록 없음'} · 마지막 이벤트 {report.measurement.last_event_at ?? '기록 없음'}</p>
      </div>

      {measuredZero && (
        <div className="mcp-zero" role="status">
          선택한 기간에 기록된 MCP 요청·도구 호출·작업 시작이 0건입니다. 미계측 도구와 전송 누락은 포함되지 않습니다.
        </div>
      )}

      <div className="mcp-metrics" aria-label="MCP 핵심 지표">
        <Metric label="서버 요청" value={count(totals.requests)} note={`오류율 ${rate(totals.request_error_rate)} · p95 ${duration(totals.request_p95_ms)}`} />
        <Metric label="관측된 도구 실행" value={report.measurement.tool_telemetry_available ? count(totals.tool_calls) : '미계측'} note={report.measurement.tool_telemetry_available ? `성공 ${count(totals.tool_successes)} · 실패 ${count(totals.tool_failures)} · 미확인 ${count(totals.tool_unknown)}` : '업그레이드된 어댑터 텔레메트리 없음'} />
        <Metric label="작업 시작" value={count(totals.jobs_started)} note={`완료 ${count(totals.jobs_completed)} · 실패 ${count(totals.jobs_failed)} · 종료 대기 ${count(totals.jobs_pending)} · 미확인 ${count(unknownJobs)}`} />
        <Metric label="활성 계정" value={count(totals.active_accounts)} note="읽기·상태 조회와 초기화 제외" />
        <Metric label="2일 이상 사용 계정" value={count(totals.repeat_accounts)} note="서로 다른 KST 날짜의 의미 있는 사용 · 리텐션 아님" />
        <Metric label="작업 p95" value={duration(totals.job_p95_ms)} note={`도구 p95 ${duration(totals.tool_p95_ms)}`} />
      </div>

      <section className="mcp-section">
        <h2>일별 사용</h2>
        <p>범례를 눌러 지표를 표시하거나 숨길 수 있습니다. 작업 완료·실패는 해당 작업의 시작일 코호트에 표시합니다.</p>
        {report.daily.length > 0 && (
          <figure className="mcp-daily-chart" aria-label="일별 MCP 사용 추이">
            <LazyLoadErrorBoundary fallback={<p role="alert">차트를 표시할 수 없습니다. 아래 데이터 표를 확인해 주세요.</p>}>
              <Suspense fallback={<div className="admin-loading">차트 로딩 중...</div>}>
                <Plot
                  data={DAILY_SERIES.map((series) => ({
                    type: 'scatter',
                    mode: 'lines+markers',
                    name: series.name,
                    x: report.daily.map((row) => row.date),
                    y: report.daily.map((row) => dailyValue(row, series.key)),
                    visible: series.primary ? true : 'legendonly',
                    connectgaps: false,
                    line: { color: series.color, width: 2 },
                    marker: { color: series.color, size: 5 },
                    fill: series.key === 'requests' ? 'tozeroy' : 'none',
                    fillcolor: `${series.color}18`,
                    hovertemplate: `%{x|%Y-%m-%d}<br>${series.name} %{y:,d}${series.unit}<extra></extra>`,
                  }))}
                  layout={{
                    autosize: true,
                    height: 320,
                    paper_bgcolor: 'transparent',
                    plot_bgcolor: 'transparent',
                    font: { color: '#706d7d', size: 11, family: 'Pretendard, sans-serif' },
                    margin: { t: 10, b: 100, l: 40, r: 12 },
                    hovermode: 'x unified',
                    hoverlabel: { bgcolor: 'rgba(255,255,255,0.98)', bordercolor: 'rgba(15,23,42,0.10)', font: { color: '#1e293b', size: 12 } },
                    legend: { orientation: 'h', y: -0.25, x: 0, yanchor: 'top' },
                    xaxis: { type: 'date', range: [report.window.start, `${report.window.end}T23:59:59`], tickformat: '%m/%d', nticks: 7, gridcolor: 'rgba(128,128,128,0.08)', zeroline: false },
                    yaxis: { gridcolor: 'rgba(128,128,128,0.10)', rangemode: 'nonnegative', zeroline: false },
                    uirevision: `${report.window.start}:${report.window.end}:${includeInternal}`,
                  }}
                  config={{ displayModeBar: false, responsive: true }}
                  useResizeHandler
                  style={{ width: '100%' }}
                />
              </Suspense>
            </LazyLoadErrorBoundary>
            <figcaption>계측 시작 전 기간과 미계측 도구는 빈 구간으로 표시합니다. 마지막 날짜는 아직 집계 중입니다.</figcaption>
          </figure>
        )}
        <details className="mcp-daily-data">
          <summary>데이터 표로 보기</summary>
          <Table className="mcp-daily-table" headings={['날짜', '요청', '활성 계정', '도구 호출', '작업 시작', '완료', '실패']}>
          {report.daily.length === 0 ? <EmptyRows columns={7}>선택 기간의 일별 기록이 없습니다.</EmptyRows> : report.daily.map((row) => (
            <tr key={row.date}><th scope="row">{row.date}</th>{(['requests', 'active_accounts', 'tool_calls', 'jobs_started', 'jobs_completed', 'jobs_failed'] as const).map((key) => {
              const value = dailyValue(row, key);
              return <td key={key}>{value === null ? '미계측' : count(value)}</td>;
            })}</tr>
          ))}
          </Table>
        </details>
      </section>

      <div className="mcp-two-column">
        <section className="mcp-section">
          <h2>관측된 도구 실행</h2>
          <Table headings={['도구', '호출', '성공', '실패', '미확인', 'p95']}>
            {report.tools.length === 0 ? <EmptyRows columns={6}>{report.measurement.tool_telemetry_available ? '관측된 도구 실행이 없습니다.' : '도구 실행은 미계측 상태입니다.'}</EmptyRows> : report.tools.map((row) => (
              <tr key={row.name}><th scope="row"><code>{row.name}</code></th><td>{count(row.calls)}</td><td>{count(row.succeeded)}</td><td>{count(row.failed)}</td><td>{count(row.unknown)}</td><td>{duration(row.p95_ms)}</td></tr>
            ))}
          </Table>
        </section>
        <section className="mcp-section">
          <h2>서버 경로</h2>
          <Table headings={['경로', '요청', '오류', 'p95']}>
            {report.routes.length === 0 ? <EmptyRows columns={4}>측정된 서버 요청이 없습니다.</EmptyRows> : report.routes.map((row) => (
              <tr key={row.name}><th scope="row"><code>{row.name}</code></th><td>{count(row.requests)}</td><td>{count(row.errors)}</td><td>{duration(row.p95_ms)}</td></tr>
            ))}
          </Table>
        </section>
      </div>

      <div className="mcp-two-column">
        <section className="mcp-section">
          <h2>작업 수명주기</h2>
          <p>기간 안에 시작된 작업의 현재 최종 상태입니다. 종료 이벤트가 24시간 넘게 없거나 시작 없는 종료 이벤트는 미확인이며 실패로 추정하지 않습니다.</p>
          <Table headings={['작업', '시작', '완료', '실패', '종료 대기', '미확인']}>
            {report.jobs.length === 0 ? <EmptyRows columns={6}>시작된 작업이 없습니다.</EmptyRows> : report.jobs.map((row) => (
              <tr key={row.name}><th scope="row">{row.name}</th><td>{count(row.started)}</td><td>{count(row.completed)}</td><td>{count(row.failed)}</td><td>{count(row.pending)}</td><td>{count(row.unknown)}</td></tr>
            ))}
          </Table>
        </section>
        <section className="mcp-section">
          <h2>오류 분류</h2>
          <Table headings={['종류', '코드', '건수']}>
            {report.errors.length === 0 ? <EmptyRows columns={3}>집계된 오류가 없습니다.</EmptyRows> : report.errors.map((row) => (
              <tr key={`${row.kind}:${row.code}`}><th scope="row">{row.kind}</th><td><code>{row.code}</code></td><td>{count(row.count)}</td></tr>
            ))}
          </Table>
        </section>
      </div>

      <section className="mcp-section">
        <h2>클라이언트 주장값</h2>
        <p>어댑터가 전달한 이름과 버전입니다. 설치 수, 사용자 수 또는 상업적 이용을 뜻하지 않습니다.</p>
        <div className="mcp-two-column mcp-two-column--nested">
          <Table headings={['클라이언트', '버전', '요청', '도구 호출']}>
            {report.clients.length === 0 ? <EmptyRows columns={4}>클라이언트 주장값이 없습니다.</EmptyRows> : report.clients.map((row, index) => (
              <tr key={`${row.name}:${row.version}:${index}`}><th scope="row">{claimedValue(row.name)}</th><td>{claimedValue(row.version)}</td><td>{count(row.requests)}</td><td>{count(row.tool_calls)}</td></tr>
            ))}
          </Table>
          <Table headings={['어댑터 버전', '요청', '도구 호출']}>
            {report.versions.length === 0 ? <EmptyRows columns={3}>어댑터 버전 주장값이 없습니다.</EmptyRows> : report.versions.map((row) => (
              <tr key={row.version}><th scope="row">{claimedValue(row.version)}</th><td>{count(row.requests)}</td><td>{count(row.tool_calls)}</td></tr>
            ))}
          </Table>
        </div>
      </section>

      {(report.measurement.limitations.length > 0 || report.measurement.source_trust) && (
        <details className="mcp-method">
          <summary>측정 한계와 출처</summary>
          <p>출처 신뢰 수준: {report.measurement.source_trust}</p>
          {report.measurement.limitations.length > 0 && <ul>{report.measurement.limitations.map((item) => <li key={item}>{item}</li>)}</ul>}
        </details>
      )}
    </section>
  );
}

function Header({
  days,
  setDays,
  includeInternal,
  setIncludeInternal,
  loading,
  report,
}: {
  days: AdminMcpWindowDays;
  setDays: (days: AdminMcpWindowDays) => void;
  includeInternal: boolean;
  setIncludeInternal: (value: boolean) => void;
  loading: boolean;
  report?: McpReportData;
}) {
  return (
    <header className="mcp-header">
      <div>
        <p className="mcp-kicker">독립 운영 측정</p>
        <h1 id="mcp-report-title">MCP 사용 리포트</h1>
        <p>{report ? `${report.window.start} — ${report.window.end} · ${report.window.timezone}` : '브라우저 분석 및 GA4와 분리된 MCP 사용 집계'}</p>
      </div>
      <div className="mcp-controls" aria-busy={loading}>
        <div className="mcp-window" aria-label="조회 기간">
          {WINDOWS.map((window) => <button type="button" key={window} aria-pressed={days === window} onClick={() => setDays(window)}>{window}일</button>)}
        </div>
        <label className="mcp-internal-toggle">
          <input type="checkbox" checked={includeInternal} onChange={(event) => setIncludeInternal(event.target.checked)} />
          관리자 계정 포함
        </label>
      </div>
    </header>
  );
}

function Table({ headings, children, className = '' }: { headings: string[]; children: ReactNode; className?: string }) {
  return (
    <div className="mcp-table-scroll">
      <table className={`mcp-table ${className}`}>
        <thead><tr>{headings.map((heading) => <th scope="col" key={heading}>{heading}</th>)}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
