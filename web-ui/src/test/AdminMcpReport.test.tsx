import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  },
  daily: [{ date: '2026-09-05', requests: 12, active_accounts: 3, tool_calls: 4, jobs_started: 2, jobs_completed: 1, jobs_failed: 0 }],
  tools: [{ name: 'deep_review', calls: 4, succeeded: 3, failed: 1, unknown: 0, p95_ms: null }],
  routes: [{ name: '/api/review/start', requests: 12, errors: 0, p95_ms: null }],
  clients: [{ name: 'Claude Desktop', version: null, requests: 10, tool_calls: 4 }],
  versions: [{ version: '0.4.0', requests: 10, tool_calls: 4 }],
  jobs: [{ name: 'deep_review', started: 2, completed: 1, failed: 0, pending: 1, unknown: 0 }],
  errors: [],
};

const response = (data: McpReportData) => Promise.resolve({ data } as Awaited<ReturnType<typeof fetchAdminMcpReport>>);

beforeEach(() => vi.clearAllMocks());

describe('AdminMcpReport', () => {
  it('plots daily usage with selectable job outcomes and a collapsed data table', async () => {
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response(REPORT));
    render(<AdminMcpReport />);
    await screen.findByTestId('mcp-daily-plot');
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
    await screen.findByTestId('mcp-daily-plot');
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
    expect(screen.getByText('2일 이상 사용 계정')).toBeInTheDocument();
    expect(screen.getByText(/리텐션 아님/)).toBeInTheDocument();
    expect(screen.getByText(/요청 연결률 75.0% \(90\/120\)/)).toBeInTheDocument();
    expect(screen.getByText(/전체 MCP 수집률이 아닙니다/)).toBeInTheDocument();
    expect(screen.getByText(/실제 호스트나 사람 수를 증명하지 않습니다/)).toBeInTheDocument();
    expect(screen.getByText(/설치 수, 사용자 수 또는 상업적 이용을 뜻하지 않습니다/)).toBeInTheDocument();
    expect(screen.getByText(/시작일 코호트/)).toBeInTheDocument();
    expect(screen.getByText(/24시간 넘게 없거나/)).toBeInTheDocument();
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
      daily: [], tools: [], routes: [], clients: [], versions: [], jobs: [], errors: [],
    };
    vi.mocked(fetchAdminMcpReport).mockImplementation(() => response(zero));
    render(<AdminMcpReport />);

    expect(await screen.findByText(/작업 시작이 0건입니다/)).toBeInTheDocument();
    expect(screen.getByText('오류율 0.0% · p95 미집계')).toBeInTheDocument();
    expect(screen.getByText('측정 범위').parentElement).toHaveTextContent('도구 실행: 미계측');
    expect(screen.getByText('미계측')).toBeInTheDocument();
    expect(screen.getByText(/요청 연결률 미집계/)).toBeInTheDocument();
    expect(screen.getByText('도구 실행은 미계측 상태입니다.')).toBeInTheDocument();
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
});
