import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import AdminMcpReport from '../components/AdminMcpReport';
import { fetchAdminMcpReport, type AdminMcpReport as McpReportData } from '../api/client';

const plotSpy = vi.hoisted(() => vi.fn());
vi.mock('../PlotlyChart', () => ({
  default: (props: Record<string, unknown>) => {
    plotSpy(props);
    return <div data-testid="mcp-daily-plot" />;
  },
}));

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return { ...actual, fetchAdminMcpReport: vi.fn() };
});

const REPORT: McpReportData = {
  available: true,
  reason: null,
  window: { start: '2026-08-10', end: '2026-09-06', days: 28, timezone: 'Asia/Seoul' },
  measurement: {
    started_at: '2026-08-01T00:00:00Z',
    last_event_at: '2026-09-06T01:02:03Z',
    source_trust: 'client_claimed',
    tool_telemetry_available: true,
    claimed_adapter_requests: 120,
    requests_with_invocation_id: 90,
    legacy_or_unattributed_requests: 30,
    invocation_coverage: 0.75,
    limitations: ['Older adapters only provide request-level evidence.'],
  },
  totals: {
    requests: 120,
    active_accounts: 8,
    tool_calls: 40,
    tool_successes: 32,
    tool_failures: 5,
    tool_unknown: 3,
    jobs_started: 12,
    jobs_completed: 8,
    jobs_failed: 2,
    jobs_pending: 2,
    request_error_rate: 0,
    request_p95_ms: null,
    tool_p95_ms: 420,
    job_p95_ms: null,
    repeat_accounts: 3,
    request_duration_samples: 120,
    tool_duration_samples: 40,
    job_duration_samples: 12,
  },
  daily: [{ date: '2026-09-05', requests: 12, active_accounts: 3, tool_calls: 4, jobs_started: 2, jobs_completed: 1, jobs_failed: 0 }],
  tools: [{ name: 'deep_review', calls: 4, succeeded: 3, failed: 1, unknown: 0, p95_ms: null }],
  routes: [{ name: '/api/review/start', requests: 12, errors: 0, p95_ms: null }],
  client_versions: [{ client: 'Claude Desktop', client_version: 'Unknown', adapter_version: '0.4.0', requests: 10, errors: 1, tool_calls: 4, tool_failures: 1 }],
  jobs: [{ name: 'deep_review', started: 2, completed: 1, failed: 0, pending: 1, unknown: 0 }],
  errors: [],
};

const response = (data: McpReportData) => Promise.resolve({ data } as Awaited<ReturnType<typeof fetchAdminMcpReport>>);
// 차트는 접힌 일별 사용 섹션이 열릴 때만 마운트된다.
const openDaily = async () => {
  fireEvent.click(await screen.findByRole('heading', { name: '일별 사용' }));
  return screen.findByTestId('mcp-daily-plot');
};

beforeEach(() => vi.clearAllMocks());

describe('AdminMcpReport', () => {
  it('plots daily usage with selectable job outcomes and a collapsed data table', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response(REPORT));
    render(<AdminMcpReport />);
    await openDaily();
    const props = plotSpy.mock.lastCall![0];
    expect(props.data).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: '서버 요청', type: 'scatter', mode: 'lines+markers', x: ['2026-09-05'], y: [12], visible: true }),
      expect.objectContaining({ name: '도구 실행', y: [4], visible: true }),
      expect.objectContaining({ name: '활성 계정', y: [3], visible: true }),
      expect.objectContaining({ name: '작업 시작', y: [2], visible: 'legendonly' }),
      expect.objectContaining({ name: '작업 완료', y: [1], visible: 'legendonly' }),
      expect.objectContaining({ name: '작업 실패', y: [0], visible: 'legendonly' }),
    ]));
    expect(props.layout.hovermode).toBe('x unified');
    expect(props.layout.xaxis.range).toEqual(['2026-08-10', '2026-09-06T23:59:59']);
    expect(props.layout.shapes).toEqual([]);
    expect(props.config.responsive).toBe(true);
    expect(screen.getByText('데이터 표로 보기').closest('details')).not.toHaveAttribute('open');
  });

  it('distinguishes pre-measurement gaps, unmeasured tools and measured zero', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response({
      ...REPORT,
      measurement: { ...REPORT.measurement, started_at: '2026-09-05T16:00:00Z', tool_telemetry_available: false },
      daily: [
        { ...REPORT.daily[0], date: '2026-09-05', requests: 0 },
        { ...REPORT.daily[0], date: '2026-09-06', requests: 0 },
      ],
    }));
    render(<AdminMcpReport />);
    await openDaily();
    expect(plotSpy.mock.lastCall![0].data).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: '서버 요청', y: [null, 0], connectgaps: false }),
      expect.objectContaining({ name: '도구 실행', y: [null, null], connectgaps: false }),
    ]));
    expect(screen.getByText('데이터 표로 보기').closest('details')).toHaveTextContent('미계측');
  });

  it('renders distinct request, observed tool, job, account, and repeat-account meanings', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response(REPORT));
    render(<AdminMcpReport />);

    expect(await screen.findByRole('heading', { name: 'MCP 사용 리포트' })).toBeInTheDocument();
    expect(screen.getByText('서버 요청')).toBeInTheDocument();
    expect(screen.getAllByText('관측된 도구 실행').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('작업 시작').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('활성 계정').length).toBeGreaterThanOrEqual(1);
    const accounts = screen.getByText('활성 계정', { selector: '.mcp-metric p' }).parentElement!;
    expect(within(accounts).getByText('2일 이상 사용 계정').previousElementSibling).toHaveTextContent('3');
    expect(screen.getByRole('group', { name: 'MCP 핵심 지표' }).children).toHaveLength(5);
    expect(screen.getByText('요청 연결률').parentElement).toHaveTextContent('75.0%');
    expect(screen.getByText('요청 연결률').parentElement).toHaveTextContent('90/120 · invocation');

    // 정의와 면책은 카드가 아니라 방법론에 산다 — 구분은 그대로, 위치만 옮겼다.
    const method = within(screen.getByText('측정 한계와 출처').closest('details')!);
    expect(method.getByText(/리텐션 아님/)).toBeInTheDocument();
    expect(method.getByText(/조회성 호출을 제외한/)).toBeInTheDocument();
    expect(method.getByText(/전체 MCP 수집률이 아닙니다/)).toBeInTheDocument();
    expect(method.getByText(/실제 호스트나 사람 수를 증명하지 않습니다/)).toBeInTheDocument();
    expect(method.getByText(/설치 수, 사용자 수 또는 상업적 이용을 뜻하지 않습니다/)).toBeInTheDocument();
    expect(method.getByText(/24시간 넘게 없거나/)).toBeInTheDocument();
    await openDaily();
    expect(screen.getByText(/시작일 코호트/)).toBeInTheDocument();
  });

  it('keeps measured zero distinct from missing values and unmeasured tool telemetry', async () => {
    const zero: McpReportData = {
      ...REPORT,
      measurement: {
        ...REPORT.measurement,
        tool_telemetry_available: false,
        claimed_adapter_requests: 0,
        requests_with_invocation_id: 0,
        legacy_or_unattributed_requests: 0,
        invocation_coverage: null,
      },
      totals: Object.fromEntries(Object.entries(REPORT.totals).map(([key]) => [key, key.includes('p95') ? null : 0])) as unknown as McpReportData['totals'],
      daily: [], tools: [], routes: [], client_versions: [], jobs: [], errors: [],
    };
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response(zero));
    render(<AdminMcpReport />);

    // 셀 게 없으면 그리지 않는다 — 배너가 이미 한 문장으로 답했다.
    const banner = await screen.findByRole('status');
    expect(banner).toHaveTextContent(/작업 시작이 0건입니다/);
    expect(banner).toHaveTextContent('미계측이며, 측정된 0건과 다릅니다');
    expect(screen.getByText('어댑터 도구 보고 · 전체 기간').parentElement).toHaveTextContent('기록 없음');
    expect(screen.queryByRole('group', { name: 'MCP 핵심 지표' })).toBeNull();
    expect(screen.queryByRole('region', { name: '서버 경로 표' })).toBeNull();
    expect(screen.queryByRole('heading', { name: '일별 사용' })).toBeNull();
    // 방법론은 남는다 — 왜 0인지 확인할 곳이다.
    expect(screen.getByText('측정 한계와 출처')).toBeInTheDocument();
  });

  it('still separates measured zero, no sample and unmeasured once anything was recorded', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response({
      ...REPORT,
      measurement: { ...REPORT.measurement, tool_telemetry_available: false, claimed_adapter_requests: 0, requests_with_invocation_id: 0, invocation_coverage: null },
      totals: { ...REPORT.totals, requests: 40, request_error_rate: 0, request_p95_ms: null, request_duration_samples: 0, tool_calls: 0 },
      tools: [], routes: [], client_versions: [],
    }));
    render(<AdminMcpReport />);

    const requests = (await screen.findByText('서버 요청', { selector: '.mcp-metric p' })).parentElement!;
    expect(requests).toHaveTextContent('0.0%');   // 측정된 0
    expect(requests).toHaveTextContent('미집계');  // 표본 없음
    expect(screen.getByText('미계측', { selector: '.mcp-metric strong' })).toBeInTheDocument();  // 계측 자체가 없음
    expect(screen.getByText('요청 연결률').parentElement).toHaveTextContent('미집계');
    expect(screen.getByText('요청 연결률').parentElement).toHaveTextContent('0/0');
    expect(screen.getByText('도구 실행은 미계측 상태입니다.').closest('td')).toHaveAttribute('colspan', '7');
    expect(screen.getByText('측정된 서버 요청이 없습니다.').closest('td')).toHaveAttribute('colspan', '5');
    expect(screen.getByText('클라이언트 주장값이 없습니다.').closest('td')).toHaveAttribute('colspan', '9');
  });

  it('renders absent instrumentation separately from a measured empty report', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response({ ...REPORT, available: false, reason: 'not_instrumented' }));
    render(<AdminMcpReport />);

    expect(await screen.findByText('MCP 사용 측정 설정 없음')).toBeInTheDocument();
    expect(screen.getByText(/저장소가 아직 설정되지 않았습니다/)).toBeInTheDocument();
    expect(screen.queryByText(/작업 시작이 0건입니다/)).not.toBeInTheDocument();
  });

  it('labels an initialized storage read problem as unavailable', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response({ ...REPORT, available: false, reason: 'unavailable' }));
    render(<AdminMcpReport />);

    expect(await screen.findByText('MCP 사용 측정 조회 불가')).toBeInTheDocument();
    expect(screen.getByText(/현재 조회할 수 없습니다/)).toBeInTheDocument();
    expect(screen.queryByText('MCP 사용 측정 설정 없음')).not.toBeInTheDocument();
  });

  it('contains API failure in the MCP report', async () => {
    vi.mocked(fetchAdminMcpReport).mockRejectedValue(new Error('network down'));
    render(<AdminMcpReport />);

    expect(await screen.findByRole('alert')).toHaveTextContent('network down');
  });

  it('requests internal accounts only when the toggle is selected', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response(REPORT));
    render(<AdminMcpReport />);
    await waitFor(() => expect(fetchAdminMcpReport).toHaveBeenCalledWith(28, false, expect.any(AbortSignal)));

    fireEvent.click(screen.getByRole('checkbox', { name: '관리자 계정 포함' }));
    await waitFor(() => expect(fetchAdminMcpReport).toHaveBeenLastCalledWith(28, true, expect.any(AbortSignal)));
  });

  it('ignores an older response that resolves after a newer window request', async () => {
    type FetchResponse = Awaited<ReturnType<typeof fetchAdminMcpReport>>;
    let resolveOlder!: (value: FetchResponse) => void;
    let resolveNewest!: (value: FetchResponse) => void;
    vi.mocked(fetchAdminMcpReport)
      .mockImplementationOnce(() => response(REPORT))
      .mockReturnValueOnce(new Promise((resolve) => { resolveOlder = resolve; }) as ReturnType<typeof fetchAdminMcpReport>)
      .mockReturnValueOnce(new Promise((resolve) => { resolveNewest = resolve; }) as ReturnType<typeof fetchAdminMcpReport>);

    render(<AdminMcpReport />);
    await screen.findByRole('heading', { name: 'MCP 사용 리포트' });
    fireEvent.click(screen.getByRole('button', { name: '7일' }));
    await waitFor(() => expect(fetchAdminMcpReport).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole('button', { name: '90일' }));
    await waitFor(() => expect(fetchAdminMcpReport).toHaveBeenCalledTimes(3));
    resolveNewest({ data: { ...REPORT, window: { ...REPORT.window, days: 90, start: '2026-06-09' }, daily: [{ ...REPORT.daily[0], date: '2026-09-06' }] } } as FetchResponse);
    expect(await screen.findByText('2026-09-06')).toBeInTheDocument();

    resolveOlder({ data: { ...REPORT, window: { ...REPORT.window, days: 7 }, daily: [{ ...REPORT.daily[0], date: '2026-08-10' }] } } as FetchResponse);
    await waitFor(() => expect(screen.queryByText('2026-08-10')).not.toBeInTheDocument());
    expect(screen.getByText('2026-09-06')).toBeInTheDocument();
  });

  it('names the active filter and the ledger-wide last event when the window is zero', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response({
      ...REPORT,
      totals: { ...REPORT.totals, requests: 0, tool_calls: 0, jobs_started: 0 },
    }));
    render(<AdminMcpReport />);

    const banner = await screen.findByRole('status');
    expect(banner).toHaveTextContent('선택한 기간(28일, 관리자 제외)');
    expect(banner).toHaveTextContent('원장의 마지막 이벤트는 2026-09-06(전체 기간·관리자 포함 기준)');
    expect(banner).toHaveTextContent('관리자 계정을 포함하면');
    expect(screen.getByText('마지막 이벤트 · 전체 기간').parentElement).toHaveTextContent('오늘 · 2026-09-06');

    expect(within(banner).queryByRole('button')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '관리자 계정 포함해서 보기' }));
    await waitFor(() => expect(fetchAdminMcpReport).toHaveBeenLastCalledWith(28, true, expect.any(AbortSignal)));
  });

  it('shades the span before measurement started and keeps count ticks on integers', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response({
      ...REPORT,
      measurement: { ...REPORT.measurement, started_at: '2026-08-20T00:00:00Z' },
      daily: [{ ...REPORT.daily[0], requests: 3, tool_calls: 2, active_accounts: 1 }],
    }));
    render(<AdminMcpReport />);
    await openDaily();

    const { layout } = plotSpy.mock.lastCall![0];
    expect(layout.shapes).toEqual([expect.objectContaining({ x0: '2026-08-10', x1: '2026-08-20', layer: 'below' })]);
    expect(layout.annotations).toEqual([expect.objectContaining({ x: '2026-08-20', text: '계측 시작' })]);
    expect(layout.yaxis).toEqual(expect.objectContaining({ rangemode: 'tozero', tickformat: ',d', dtick: 1 }));
  });

  it('keeps the chart unmounted until the daily section is opened', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response(REPORT));
    render(<AdminMcpReport />);
    await screen.findByRole('heading', { name: 'MCP 사용 리포트' });
    expect(screen.queryByTestId('mcp-daily-plot')).toBeNull();
    expect(plotSpy).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { name: '일별 사용' }).closest('details')).not.toHaveAttribute('open');
    await openDaily();
    expect(plotSpy).toHaveBeenCalled();
  });

  it('lists error codes under the table that produced them instead of a shared taxonomy', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response({
      ...REPORT,
      errors: [{ kind: 'request', code: '404', count: 5 }, { kind: 'request', code: 'failed', count: 1 }, { kind: 'tool', code: 'cancelled', count: 1 }, { kind: 'job', code: 'job_failed', count: 1 }],
    }));
    render(<AdminMcpReport />);
    await screen.findByRole('heading', { name: '서버 경로' });
    const section = (name: string) => within(screen.getByRole('heading', { name }).closest('section')!);

    expect(screen.queryByText('오류 분류')).toBeNull();
    // 클라이언트와 어댑터 버전이 한 행에 있어야 "어떤 조합이 깨졌나"에 답할 수 있다.
    const claim = within(screen.getByRole('region', { name: '클라이언트·어댑터 버전 표' }));
    expect(claim.getByRole('columnheader', { name: '클라이언트 버전' })).toBeInTheDocument();
    expect(claim.getByRole('columnheader', { name: '어댑터 버전' })).toBeInTheDocument();
    expect(section('서버 경로').getByText('오류 코드').parentElement).toHaveTextContent('404 ×5');
    expect(section('서버 경로').getByText('오류 코드').parentElement).toHaveTextContent('실패 ×1');
    expect(section('관측된 도구 실행').getByText('실패 사유').parentElement).toHaveTextContent('취소 ×1');
    expect(section('관측된 도구 실행').getByText('실패 사유').parentElement).not.toHaveTextContent('404');
    expect(section('작업 수명주기').getByText('실패 사유').parentElement).toHaveTextContent('실패 ×1');
  });

  it('keeps every rate column comparable and only mutes the ones with a thin sample', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response({
      ...REPORT,
      totals: { ...REPORT.totals, requests: 40, request_error_rate: 0.1, request_p95_ms: 1843, request_duration_samples: 40, tool_calls: 4, tool_failures: 1, tool_p95_ms: 420, tool_duration_samples: 4, jobs_started: 12, job_p95_ms: 9000, job_duration_samples: 12 },
    }));
    render(<AdminMcpReport />);

    const requests = (await screen.findByText('서버 요청', { selector: '.mcp-metric p' })).parentElement!;
    expect(within(requests).getByText('오류율').previousElementSibling).toHaveTextContent('10.0%');
    expect(within(requests).getByText('p95')).toBeInTheDocument();
    const tools = screen.getByText('관측된 도구 실행', { selector: '.mcp-metric p' }).parentElement!;
    // 값은 비교 가능한 비율로 두고, 표본이 얇다는 사실은 강조를 빼서 알린다.
    expect(within(tools).getByText('실패율').previousElementSibling).toHaveTextContent('25.0%');
    expect(within(tools).getByText('실패율').closest('span')).toHaveClass('thin');
    expect(within(requests).getByText('오류율').closest('span')).not.toHaveClass('thin');
    expect(within(tools).getByText('최대').previousElementSibling).toHaveTextContent('420ms');
    const jobs = screen.getByText('작업 시작', { selector: '.mcp-metric p' }).parentElement!;
    expect(within(jobs).getByText('최대').previousElementSibling).toHaveTextContent('9.0초');
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('calls the latency a maximum when the duration samples are thin, not when the event count is high', async () => {
    // 작업 25건이라도 종료 대기가 많으면 지연 표본은 15건뿐이다.
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response({
      ...REPORT,
      totals: { ...REPORT.totals, jobs_started: 25, jobs_pending: 10, jobs_completed: 12, jobs_failed: 3, job_p95_ms: 9000, job_duration_samples: 15 },
    }));
    render(<AdminMcpReport />);

    const jobs = (await screen.findByText('작업 시작', { selector: '.mcp-metric p' })).parentElement!;
    expect(within(jobs).getByText('최대')).toBeInTheDocument();
    expect(within(jobs).queryByText('p95')).toBeNull();
  });

  it('explains a near-zero window instead of filling it with alarming rates', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response({
      ...REPORT,
      measurement: { ...REPORT.measurement, claimed_adapter_requests: 1, requests_with_invocation_id: 1, invocation_coverage: 1 },
      totals: { ...REPORT.totals, requests: 1, request_error_rate: 1, tool_calls: 3, tool_failures: 2, jobs_started: 0 },
    }));
    render(<AdminMcpReport />);

    const banner = await screen.findByRole('status');
    expect(banner).toHaveTextContent('합계 4건입니다');
    expect(banner).toHaveTextContent('흐리게 표시하며');
    const requests = screen.getByText('서버 요청', { selector: '.mcp-metric p' }).parentElement!;
    // 1건짜리 100%는 여전히 100%지만 붉지도 굵지도 않다.
    expect(within(requests).getByText('오류율').previousElementSibling).toHaveTextContent('100.0%');
    expect(within(requests).getByText('오류율').closest('span')).toHaveClass('thin');
    const coverage = screen.getByText('요청 연결률', { selector: '.mcp-metric p' }).parentElement!;
    expect(coverage).toHaveTextContent('100.0%');
    expect(coverage).toHaveTextContent('1/1 · invocation');

    fireEvent.click(screen.getByRole('button', { name: '관리자 계정 포함해서 보기' }));
    await waitFor(() => expect(fetchAdminMcpReport).toHaveBeenLastCalledWith(28, true, expect.any(AbortSignal)));
  });

  it('keeps a shortened route label for narrow screens without losing the real one', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response({
      ...REPORT,
      routes: [
        { name: 'GET /api/deep-review/{session_id}/status', requests: 14, errors: 0, p95_ms: 12 },
        { name: '/api/review/start', requests: 12, errors: 0, p95_ms: null },
        { name: 'GET (unmatched)', requests: 3, errors: 3, p95_ms: 2 },
      ],
    }));
    render(<AdminMcpReport />);

    const header = (match: RegExp) => within(screen.getByRole('region', { name: '서버 경로 표' })).getByRole('rowheader', { name: match });
    const withMethod = await screen.findByRole('rowheader', { name: /deep-review/ });
    expect(withMethod).toHaveAttribute('title', 'GET /api/deep-review/{session_id}/status');
    expect(within(withMethod).getByText('GET /api/deep-review/{session_id}/status')).toHaveClass('mcp-route-full');
    expect(within(withMethod).getByText('GET')).toHaveClass('mcp-route-method');
    expect(within(withMethod).getByText('/deep-review/…/status')).toBeInTheDocument();
    // 메서드가 없는 이름도 같은 축약을 받는다.
    expect(within(header(/review\/start/)).getByText('/review/start')).toBeInTheDocument();
    // 경로가 아닌 이름도 메서드를 분리해 보여 준다.
    const unmatched = header(/unmatched/);
    expect(within(unmatched).getByText('GET')).toHaveClass('mcp-route-method');
    expect(within(unmatched).getByText('(unmatched)')).toBeInTheDocument();
  });

  it('shows per-version error counts next to the version claims', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response(REPORT));
    render(<AdminMcpReport />);

    const row = await screen.findByRole('row', { name: /^Claude Desktop/ });
    const cells = within(row).getAllByRole('cell');
    expect(cells.map((cell) => cell.textContent)).toEqual(['Unknown', '0.4.0', '10', '1', '10.0%', '4', '1', '25.0%']);
    expect(cells[4]).toHaveClass('mcp-rate-thin');
  });

  it('rates failures against every call, marks non-zero failures, and keeps table columns in raw ms', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response({
      ...REPORT,
      totals: { ...REPORT.totals, request_p95_ms: 1843, job_p95_ms: 187_500 },
      tools: [{ name: 'deep_review', calls: 4, succeeded: 2, failed: 1, unknown: 1, p95_ms: 0.4 }],
      routes: [{ name: '/api/review/start', requests: 12, errors: 0, p95_ms: 12_410 }],
    }));
    render(<AdminMcpReport />);

    const tools = await screen.findByRole('region', { name: '관측된 도구 실행 표' });
    const tool = within(within(tools).getByRole('row', { name: /^deep_review/ })).getAllByRole('cell');
    expect(tool.map((cell) => cell.textContent)).toEqual(['4', '2', '1', '25.0%', '1', '<1']);
    expect(tool[3]).toHaveClass('mcp-rate-thin');
    expect(tool[2]).toHaveClass('mcp-fail');
    const route = within(screen.getByRole('row', { name: /review\/start/ })).getAllByRole('cell');
    expect(route.map((cell) => cell.textContent)).toEqual(['12', '0', '0.0%', '12,410']);
    expect(route[2]).toHaveClass('mcp-rate-thin');
    expect(route[1]).not.toHaveClass('mcp-fail');
    expect(screen.getByText('서버 요청').parentElement).toHaveTextContent('1.8초');
    expect(screen.getByText('작업 시작', { selector: '.mcp-metric p' }).parentElement).toHaveTextContent('3분 8초');
    expect(screen.getByRole('region', { name: '서버 경로 표' })).toHaveAttribute('tabindex', '0');
  });

  it('groups the window buttons and marks the report busy while a new window loads', async () => {
    vi.mocked(fetchAdminMcpReport)
      .mockImplementationOnce(() => response(REPORT))
      .mockReturnValueOnce(new Promise(() => {}) as ReturnType<typeof fetchAdminMcpReport>);
    render(<AdminMcpReport />);

    const region = await screen.findByRole('region', { name: 'MCP 사용 리포트' });
    expect(region).toHaveAttribute('aria-busy', 'false');
    expect(within(region).getByRole('group', { name: '조회 기간' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '7일' }));
    await waitFor(() => expect(region).toHaveAttribute('aria-busy', 'true'));
  });
});
