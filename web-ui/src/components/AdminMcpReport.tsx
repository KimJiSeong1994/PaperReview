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
// 요청과 도구 실행은 기본으로 함께 켜지므로 두 색이 색각 이상에서도 갈라져야 하고(indigo 둘은
// deuteranopia에서 사실상 같은 색), 마커 모양은 색과 무관한 두 번째 채널이다.
const DAILY_SERIES = [
  { key: 'requests', name: '서버 요청', color: '#9b5cff', symbol: 'circle', unit: '건', primary: true },
  { key: 'tool_calls', name: '도구 실행', color: '#d97706', symbol: 'square', unit: '건', primary: true },
  { key: 'active_accounts', name: '활성 계정', color: '#0d9488', symbol: 'diamond', unit: '계정', primary: true },
  { key: 'jobs_started', name: '작업 시작', color: '#0284c7', symbol: 'triangle-up', unit: '건', primary: false },
  { key: 'jobs_completed', name: '작업 완료', color: '#16a34a', symbol: 'cross', unit: '건', primary: false },
  { key: 'jobs_failed', name: '작업 실패', color: '#e05266', symbol: 'x', unit: '건', primary: false },
] as const;
const ERROR_CODE: Partial<Record<string, string>> = { failed: '실패', tool_failed: '실패', job_failed: '실패', cancelled: '취소' };

const kstDate = (value: string | null) => {
  const timestamp = value ? Date.parse(value) : NaN;
  return Number.isFinite(timestamp) ? new Date(timestamp + 9 * 60 * 60 * 1000).toISOString().slice(0, 10) : null;
};
const kstDateTime = (value: string | null) => {
  const timestamp = value ? Date.parse(value) : NaN;
  return Number.isFinite(timestamp) ? new Date(timestamp + 9 * 60 * 60 * 1000).toISOString().slice(0, 16).replace('T', ' ') : null;
};
// 창의 끝 날짜(KST 오늘)를 기준으로 세어야 화면과 테스트가 같은 답을 낸다.
const relativeDays = (from: string, to: string) => {
  const days = Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
  return days <= 0 ? '오늘' : `${days}일 전`;
};

const count = (value: number) => numberFormat.format(value);
const duration = (value: number | null) => {
  if (value === null) return '미집계';
  if (value < 1) return '<1ms';
  if (Math.round(value) < 1000) return `${numberFormat.format(Math.round(value))}ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(1)}초`;
  const seconds = Math.round(value / 1000);
  return `${Math.floor(seconds / 60)}분 ${seconds % 60}초`;
};
const ms = (value: number | null) => (value === null ? '미집계' : value < 1 ? '<1' : numberFormat.format(Math.round(value)));
const rate = (value: number | null) => value === null ? '미집계' : `${(value * 100).toFixed(1)}%`;
// Below this many samples a single event moves a rate by 5%p or more, and the
// backend's p95 is literally the observed maximum (mcp_usage.py:_percentile_95
// indexes the last element for every n < 20). So under it we show the counts
// themselves and call the latency what it is.
const RATE_SAMPLE_FLOOR = 20;
// 미확인 stays in the denominator: a rate over succeeded+failed would hide it.
const rateOf = (part: number, whole: number) => {
  if (whole === 0) return '미집계';
  return whole < RATE_SAMPLE_FLOOR ? `${count(part)}/${count(whole)}` : rate(part / whole);
};
// 표본은 duration이 기록된 이벤트 수이지 요청·호출 건수가 아니다 — 종료 대기 중인
// 작업이 많으면 작업 25건에도 지연 표본은 15건일 수 있다.
const latencyLabel = (samples: number) => (samples < RATE_SAMPLE_FLOOR ? '최대' : 'p95');
const claimedValue = (value: string | null) => value || '미제공';

type MetricPart = { label: string; value: string; bad?: boolean };

// A breakdown ("성공 49 · 실패 8") is what the admin scans for; as a sentence it
// was the quietest text on the card. `parts` lays it out value-over-label, and
// a non-zero failure is red and bold. Definitions and caveats stay prose.
function Metric({ label, value, note, parts, unmeasured = false }: {
  label: string; value: string; note?: string; parts?: MetricPart[]; unmeasured?: boolean;
}) {
  return (
    <article className={unmeasured ? 'mcp-metric mcp-metric--unmeasured' : 'mcp-metric'}>
      <p>{label}</p>
      <strong>{value}</strong>
      {parts && (
        <div className="mcp-metric-parts">
          {parts.map((part) => (
            <span key={part.label} className={part.bad ? 'bad' : undefined}><b>{part.value}</b><small>{part.label}</small></span>
          ))}
        </div>
      )}
      {note && <span>{note}</span>}
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
  const [dailyOpen, setDailyOpen] = useState(false);
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
      <section className="mcp-report visits-report" aria-labelledby="mcp-report-title" aria-busy={loading}>
        <Header days={days} setDays={setDays} includeInternal={includeInternal} setIncludeInternal={setIncludeInternal} report={report} />
        <div className="mcp-state" role="status">
          <strong>{missing ? 'MCP 사용 측정 설정 없음' : 'MCP 사용 측정 조회 불가'}</strong>
          <p>{reasonCopy(report.reason)}</p>
          {report.reason && <code>{report.reason}</code>}
        </div>
      </section>
    );
  }

  const { totals, measurement } = report;
  const measurementStart = kstDate(measurement.started_at);
  const lastEventDate = kstDate(measurement.last_event_at);
  const dailyValue = (row: McpReportData['daily'][number], key: typeof DAILY_SERIES[number]['key']) => (
    (measurementStart !== null && row.date < measurementStart)
    || (key === 'tool_calls' && !measurement.tool_telemetry_available)
      ? null : row[key]
  );
  // 요청이 0건이면 셀 수 있는 분모가 없다 — 백엔드가 보낸 비율을 그대로 두어야
  // 측정된 0(0.0%)과 미집계가 갈린다.
  const requestErrors = totals.requests > 0 && totals.requests < RATE_SAMPLE_FLOOR && totals.request_error_rate !== null
    ? Math.round(totals.request_error_rate * totals.requests)
    : null;
  const measuredZero = totals.requests === 0 && totals.tool_calls === 0 && totals.jobs_started === 0;
  // 0건과 "몇 건" 사이가 관리자에게 가장 헷갈리는 구간이다. 0건 배너는 여기서 뜨지
  // 않는데 화면은 100.0% 같은 붉은 비율로 채워져 고장처럼 보인다.
  const activity = totals.requests + totals.tool_calls + totals.jobs_started;
  const sparseActivity = !measuredZero && activity < RATE_SAMPLE_FLOOR;
  const yMax = Math.max(0, ...report.daily.flatMap((row) => DAILY_SERIES.map((series) => dailyValue(row, series.key) ?? 0)));
  const preMeasured = measurementStart !== null && measurementStart > report.window.start;

  return (
    <section className="mcp-report visits-report" aria-labelledby="mcp-report-title" aria-busy={loading}>
      <Header days={days} setDays={setDays} includeInternal={includeInternal} setIncludeInternal={setIncludeInternal} report={report} />
      {error && <div className="mcp-inline-error" role="alert">새 데이터를 불러오지 못했습니다: {error}</div>}

      {/* 지표가 전부 0일 때 관리자가 먼저 묻는 것은 "고장인가, 안 쓰는가"다. 이 줄은 전부
          선택 기간·관리자 필터와 무관한 원장 전체 기준이라 창 안 숫자들과 섞지 않는다. */}
      <div className="dashboard-context-strip" role="group" aria-label="원장 전체 기준 측정 상태">
        <div>
          <span>마지막 이벤트 · 전체 기간</span>
          <strong>{lastEventDate ? `${relativeDays(lastEventDate, report.window.end)} · ${kstDateTime(measurement.last_event_at)}` : '기록 없음'}</strong>
        </div>
        <div>
          <span>측정 시작</span>
          <strong>{kstDateTime(measurement.started_at) ?? '기록 없음'}</strong>
        </div>
        <div>
          <span>어댑터 도구 보고 · 전체 기간</span>
          <strong>{measurement.tool_telemetry_available ? '기록 있음' : '기록 없음'}</strong>
        </div>
      </div>

      {sparseActivity && (
        <div className="mcp-zero mcp-zero--sparse">
          <div role="status">
            <strong>선택한 기간({report.window.days}일{includeInternal ? '' : ', 관리자 제외'})에 기록된 활동이 요청·도구 호출·작업 시작 합계 {count(activity)}건입니다.</strong>
            <p>
              표본이 {RATE_SAMPLE_FLOOR}건 미만이라 비율 대신 건수를 그대로 보여 주고, 지연은 p95가 아니라 관측된 최대값입니다.
              {!includeInternal && ' 관리자 계정을 포함하면 내부 사용이 보일 수 있습니다.'}
            </p>
          </div>
          {!includeInternal && (
            <button type="button" className="mcp-zero-action" onClick={() => setIncludeInternal(true)}>관리자 계정 포함해서 보기</button>
          )}
        </div>
      )}

      {measuredZero && (
        <div className="mcp-zero">
          <div role="status">
            <strong>선택한 기간({report.window.days}일{includeInternal ? '' : ', 관리자 제외'})에 기록된 MCP 요청·도구 호출·작업 시작이 0건입니다.</strong>
            <p>
              {lastEventDate
                ? `원장의 마지막 이벤트는 ${lastEventDate}(전체 기간·관리자 포함 기준)${includeInternal ? '입니다.' : '이며, 관리자 계정을 포함하면 내부 사용이 보일 수 있습니다.'}`
                : '원장에 기록된 이벤트가 없습니다.'}
            </p>
          </div>
          {!includeInternal && lastEventDate && (
            <button type="button" className="mcp-zero-action" onClick={() => setIncludeInternal(true)}>관리자 계정 포함해서 보기</button>
          )}
        </div>
      )}

      <div className="mcp-metrics" role="group" aria-label="MCP 핵심 지표">
        <Metric label="서버 요청" value={count(totals.requests)} parts={[
          // 표본이 충분하면 백엔드가 준 비율을 그대로 쓴다(역산해 다시 나누면 8.6%가 8.7%로 흔들린다).
          // 요청이 0건이면 셀 분모가 없으니 역시 백엔드 값 — 측정된 0과 미집계는 거기서 갈린다.
          { label: '오류율', value: requestErrors === null ? rate(totals.request_error_rate) : `${count(requestErrors)}/${count(totals.requests)}` },
          { label: latencyLabel(totals.request_duration_samples), value: duration(totals.request_p95_ms) },
        ]} />
        <Metric
          label="관측된 도구 실행"
          value={measurement.tool_telemetry_available ? count(totals.tool_calls) : '미계측'}
          unmeasured={!measurement.tool_telemetry_available}
          note={measurement.tool_telemetry_available ? undefined : '업그레이드된 어댑터 텔레메트리 없음'}
          parts={measurement.tool_telemetry_available ? [
            { label: '실패율', value: rateOf(totals.tool_failures, totals.tool_calls) },
            { label: '성공', value: count(totals.tool_successes) },
            { label: '실패', value: count(totals.tool_failures), bad: totals.tool_failures > 0 },
            { label: '미확인', value: count(totals.tool_unknown) },
            { label: latencyLabel(totals.tool_duration_samples), value: duration(totals.tool_p95_ms) },
          ] : undefined}
        />
        {/* 미확인은 시작 기록 없는 종료도 세므로 시작 수와 더해지지 않는다 — 작업 표에서만 보인다. */}
        <Metric label="작업 시작" value={count(totals.jobs_started)} parts={[
          { label: '완료', value: count(totals.jobs_completed) },
          { label: '실패', value: count(totals.jobs_failed), bad: totals.jobs_failed > 0 },
          { label: '종료 대기', value: count(totals.jobs_pending) },
          { label: latencyLabel(totals.job_duration_samples), value: duration(totals.job_p95_ms) },
        ]} />
        <Metric
          label="활성 계정"
          value={count(totals.active_accounts)}
          parts={[{ label: '2일 이상 사용 계정', value: count(totals.repeat_accounts) }]}
          note="조회성 호출을 제외한 성공 호출 또는 작업 시작 기준 · 2일 이상은 서로 다른 KST 날짜의 의미 있는 사용이며 리텐션 아님"
        />
        {/* 창·필터 기준 값이라 스트립이 아니라 여기에 있고, 100%가 "다 잡고 있다"로 읽히지 않도록 단서를 숫자 옆에 붙인다. */}
        <Metric
          label="요청 연결률"
          // 주장 요청이 20건 미만이면 이 카드도 백분율 대신 건수를 낸다 — 헤드라인이
          // 분수면 노트가 같은 분수를 되풀이할 필요는 없다.
          value={measurement.invocation_coverage === null || measurement.claimed_adapter_requests >= RATE_SAMPLE_FLOOR
            ? rate(measurement.invocation_coverage)
            : `${count(measurement.requests_with_invocation_id)}/${count(measurement.claimed_adapter_requests)}`}
          unmeasured={measurement.invocation_coverage === null}
          note={measurement.invocation_coverage !== null && measurement.claimed_adapter_requests < RATE_SAMPLE_FLOOR
            ? 'invocation 헤더가 붙은 어댑터 주장 요청 비율. 전체 MCP 수집률이 아닙니다'
            : `${count(measurement.requests_with_invocation_id)}/${count(measurement.claimed_adapter_requests)} · invocation 헤더가 붙은 어댑터 주장 요청 비율. 전체 MCP 수집률이 아닙니다`}
        />
      </div>

      <div className="mcp-two-column">
        <section className="mcp-section">
          <h2>관측된 도구 실행</h2>
          <Table label="관측된 도구 실행 표" headings={['도구', '호출', '성공', '실패', '실패율', '미확인', 'p95 (ms)']}>
            {report.tools.length === 0 ? <EmptyRows columns={7}>{measurement.tool_telemetry_available ? '관측된 도구 실행이 없습니다.' : '도구 실행은 미계측 상태입니다.'}</EmptyRows> : report.tools.map((row) => (
              <tr key={row.name}><th scope="row" title={row.name}><code>{row.name}</code></th><td>{count(row.calls)}</td><td>{count(row.succeeded)}</td><td className={failClass(row.failed)}>{count(row.failed)}</td><td>{rateOf(row.failed, row.calls)}</td><td>{count(row.unknown)}</td><td>{ms(row.p95_ms)}</td></tr>
            ))}
          </Table>
          <ErrorLine label="실패 사유" rows={report.errors.filter((row) => row.kind === 'tool')} />
        </section>
        <section className="mcp-section">
          <h2>서버 경로</h2>
          <Table label="서버 경로 표" headings={['경로', '요청', '오류', '오류율', 'p95 (ms)']}>
            {report.routes.length === 0 ? <EmptyRows columns={5}>측정된 서버 요청이 없습니다.</EmptyRows> : report.routes.map((row) => (
              <tr key={row.name}><th scope="row" title={row.name}><RouteName name={row.name} /></th><td>{count(row.requests)}</td><td className={failClass(row.errors)}>{count(row.errors)}</td><td>{rateOf(row.errors, row.requests)}</td><td>{ms(row.p95_ms)}</td></tr>
            ))}
          </Table>
          <ErrorLine label="오류 코드" rows={report.errors.filter((row) => row.kind === 'request')} />
        </section>
      </div>

      <section className="mcp-section mcp-section--aside">
        <h2>작업 수명주기</h2>
        <p>종료 이벤트가 24시간 넘게 없거나 시작 기록 없는 종료는 미확인으로 두며 실패로 추정하지 않습니다.</p>
        <Table label="작업 수명주기 표" headings={['작업', '시작', '완료', '실패', '종료 대기', '미확인']}>
          {report.jobs.length === 0 ? <EmptyRows columns={6}>시작된 작업이 없습니다.</EmptyRows> : report.jobs.map((row) => (
            <tr key={row.name}><th scope="row" title={row.name}><code>{row.name}</code></th><td>{count(row.started)}</td><td>{count(row.completed)}</td><td className={failClass(row.failed)}>{count(row.failed)}</td><td>{count(row.pending)}</td><td>{count(row.unknown)}</td></tr>
          ))}
        </Table>
        <ErrorLine label="실패 사유" rows={report.errors.filter((row) => row.kind === 'job')} />
      </section>

      <section className="mcp-section">
        <h2>클라이언트 주장값</h2>
        <p>어댑터가 보낸 이름·버전이며 설치 수, 사용자 수 또는 상업적 이용을 뜻하지 않습니다.</p>
        <Table
          label="클라이언트·어댑터 버전 표"
          headings={['클라이언트', '클라이언트 버전', '어댑터 버전', '요청', '오류', '오류율', '도구 호출', '도구 실패', '도구 실패율']}
        >
          {report.client_versions.length === 0 ? <EmptyRows columns={9}>클라이언트 주장값이 없습니다.</EmptyRows> : report.client_versions.map((row) => (
            <tr key={`${row.client}:${row.client_version}:${row.adapter_version}`}>
              <th scope="row">{claimedValue(row.client)}</th>
              <td>{claimedValue(row.client_version)}</td>
              <td>{claimedValue(row.adapter_version)}</td>
              <td>{count(row.requests)}</td>
              <td className={failClass(row.errors)}>{count(row.errors)}</td>
              <td>{rateOf(row.errors, row.requests)}</td>
              <td>{count(row.tool_calls)}</td>
              <td className={failClass(row.tool_failures)}>{count(row.tool_failures)}</td>
              <td>{rateOf(row.tool_failures, row.tool_calls)}</td>
            </tr>
          ))}
        </Table>
      </section>

      {/* Mounting <Plot> inside a closed <details> lays it out at 0 width and `responsive`
          only reacts to window resize, so the chart exists only while the section is open.
          Plotly (~1.5MB) is fetched on the first open, not on every visit. */}
      <details className="mcp-section mcp-daily" onToggle={(event) => setDailyOpen(event.currentTarget.open)}>
        <summary><h2>일별 사용</h2><span>{report.window.days}일 추이 · 일별 표</span></summary>
        {dailyOpen && report.daily.length > 0 && (
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
                    marker: { color: series.color, size: 6, symbol: series.symbol },
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
                    margin: { t: 20, b: 68, l: 40, r: 12 },
                    hovermode: 'x unified',
                    hoverlabel: { bgcolor: 'rgba(255,255,255,0.98)', bordercolor: 'rgba(15,23,42,0.10)', font: { color: '#1e293b', size: 12 } },
                    legend: { orientation: 'h', y: -0.18, x: 0, yanchor: 'top' },
                    xaxis: { type: 'date', range: [report.window.start, `${report.window.end}T23:59:59`], tickformat: '%m/%d', nticks: 7, gridcolor: 'rgba(128,128,128,0.08)', zeroline: false },
                    // 건수 축은 0에서 시작하고 눈금은 정수여야 한다. 최대값이 작으면 Plotly가 0.2 간격을
                    // 고르므로 그 구간만 1로 고정한다. yMax는 숨긴 계열까지 본다 — 켰을 때 눈금 40개가 되는 쪽이 더 나쁘다.
                    // ponytail: 숨긴 계열만 6을 넘고 보이는 계열이 작으면 소수 눈금이 남음. 완전 방어는 legend 토글마다 relayout 필요
                    yaxis: { gridcolor: 'rgba(128,128,128,0.10)', rangemode: 'tozero', zeroline: false, tickformat: ',d', ...(yMax <= 6 ? { tick0: 0, dtick: 1 } : {}) },
                    // 계측 시작 전 구간은 0이 아니라 "재지 않음"이다. 빈 선만으로는 그 차이가 안 보인다.
                    shapes: preMeasured ? [{ type: 'rect', xref: 'x', yref: 'paper', layer: 'below', x0: report.window.start, x1: measurementStart, y0: 0, y1: 1, fillcolor: 'rgba(128,128,128,0.07)', line: { width: 0 } }] : [],
                    annotations: preMeasured ? [{ x: measurementStart, xref: 'x', y: 1, yref: 'paper', yanchor: 'bottom', text: '계측 시작', showarrow: false, font: { size: 10 } }] : [],
                    uirevision: `${report.window.start}:${report.window.end}:${includeInternal}`,
                  }}
                  config={{ displayModeBar: false, responsive: true }}
                  style={{ width: '100%' }}
                />
              </Suspense>
            </LazyLoadErrorBoundary>
            <figcaption>빈 구간은 계측 전이거나 미계측입니다. 완료·실패는 시작일 코호트에 표시합니다. 마지막 날짜는 집계 중입니다.</figcaption>
          </figure>
        )}
        <details className="mcp-daily-data">
          <summary>데이터 표로 보기</summary>
          <Table label="일별 사용 표" className="mcp-daily-table" headings={['날짜', '요청', '활성 계정', '도구 호출', '작업 시작', '완료', '실패']}>
          {report.daily.length === 0 ? <EmptyRows columns={7}>선택 기간의 일별 기록이 없습니다.</EmptyRows> : report.daily.map((row) => (
            <tr key={row.date}><th scope="row">{row.date}</th>{(['requests', 'active_accounts', 'tool_calls', 'jobs_started', 'jobs_completed', 'jobs_failed'] as const).map((key) => {
              const value = dailyValue(row, key);
              return <td key={key} className={key === 'jobs_failed' && value ? 'mcp-fail' : undefined}>{value === null ? '미계측' : count(value)}</td>;
            })}</tr>
          ))}
          </Table>
        </details>
      </details>

      <details className="mcp-method">
        <summary>측정 한계와 출처</summary>
        <p>브라우저 분석·GA4와 분리된 서버 관측 집계입니다. 도구 실행은 업그레이드된 어댑터가 보고한 것만 관측합니다. 기존 어댑터, 로컬 옵트아웃, 전송 유실의 도구 실행 총량은 알 수 없습니다.</p>
        <p>마지막 이벤트·측정 시작·어댑터 도구 보고는 선택 기간·관리자 필터와 무관한 원장 전체 기준입니다.</p>
        <p>지연 p95는 표본이 {RATE_SAMPLE_FLOOR}건 미만이면 관측된 최대값과 같습니다. 같은 구간에서 비율은 백분율 대신 건수로 표시합니다.</p>
        <p>클라이언트·버전·User-Agent는 클라이언트가 보낸 주장값이며 실제 호스트나 사람 수를 증명하지 않습니다. 서버가 받은 MCP 요청과 작업 수명주기만 집계합니다.</p>
      </details>
    </section>
  );
}

function Header({
  days,
  setDays,
  includeInternal,
  setIncludeInternal,
  report,
}: {
  days: AdminMcpWindowDays;
  setDays: (days: AdminMcpWindowDays) => void;
  includeInternal: boolean;
  setIncludeInternal: (value: boolean) => void;
  report?: McpReportData;
}) {
  return (
    <header className="visits-report-header mcp-header">
      <div className="visits-report-heading">
        <span className="visits-report-kicker">MCP TELEMETRY</span>
        <h1 id="mcp-report-title">MCP 사용 리포트</h1>
        <p>{report ? `${report.window.start} — ${report.window.end} · ${report.window.timezone}` : 'MCP 사용 집계'}</p>
      </div>
      <div className="mcp-controls">
        <div className="mcp-window" role="group" aria-label="조회 기간">
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

function ErrorLine({ label, rows }: { label: string; rows: McpReportData['errors'] }) {
  if (rows.length === 0) return null;
  return (
    <p className="mcp-error-line">
      <span>{label}</span>
      {rows.map((row) => <span key={row.code}>{ERROR_CODE[row.code] ?? <code>{row.code}</code>} ×{count(row.count)}</span>)}
    </p>
  );
}

// 백엔드는 매칭 실패 시 "GET (unmatched)"도 남기므로 경로가 /로 시작하지 않을 수 있다.
const ROUTE_NAME = /^([A-Z]+) (.+)$/;

// 모바일에서 첫 칸은 sticky라 가로로 스크롤해도 잘린 뒤가 드러나지 않고, title은
// 터치에서 뜨지 않는다. 그래서 좁은 화면에서는 메서드를 윗줄로 빼고, 모든 경로가
// 공유하는 /api 접두사와 파라미터 이름을 줄여 경로가 한 줄에 들어오게 한다.
// 전체 문자열은 넓은 화면과 title에 그대로 남는다.
const compactPath = (path: string) => path.replace('/api/', '/').replace(/\{[^}]+\}/g, '…');

function RouteName({ name }: { name: string }) {
  const parsed = ROUTE_NAME.exec(name);
  const method = parsed?.[1];
  const path = parsed?.[2] ?? name;
  return (
    <>
      <code className="mcp-route-full">{name}</code>
      <span className="mcp-route-compact">
        {method && <span className="mcp-route-method">{method}</span>}
        <code>{compactPath(path)}</code>
      </span>
    </>
  );
}

/* A non-zero failure count is the thing being scanned for; grey 12px hid it. */
const failClass = (value: number) => (value > 0 ? 'mcp-fail' : undefined);

function Table({ label, headings, children, className = '' }: { label: string; headings: string[]; children: ReactNode; className?: string }) {
  return (
    // Every table overflows on a phone; without a tab stop the hidden columns are unreachable by keyboard.
    <div className="mcp-table-scroll" tabIndex={0} role="region" aria-label={label}>
      <table className={`mcp-table ${className}`}>
        <thead><tr>{headings.map((heading) => <th scope="col" key={heading}>{heading}</th>)}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
