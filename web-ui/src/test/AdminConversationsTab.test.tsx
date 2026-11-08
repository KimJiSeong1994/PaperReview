import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AdminConversationsTab from '../components/AdminConversationsTab';
import { fetchAdminConversationStats, type AdminConversationStats } from '../api/client';
import { CONVERSATIONS, EMPTY_CONVERSATIONS } from './fixtures/adminConversations';

type Response = Awaited<ReturnType<typeof fetchAdminConversationStats>>;
const response = (data: AdminConversationStats) => ({ data } as Response);
const plotSpy = vi.hoisted(() => vi.fn());
vi.mock('../PlotlyChart', () => ({ default: (props: Record<string, unknown>) => {
  plotSpy(props);
  return <div data-testid="conversation-trend" />;
} }));
vi.mock('../api/client', async () => ({
  ...await vi.importActual('../api/client'), fetchAdminConversationStats: vi.fn(),
}));

beforeEach(() => {
  plotSpy.mockClear();
  vi.mocked(fetchAdminConversationStats).mockReset().mockResolvedValue(response(CONVERSATIONS));
});

const renderTab = () => render(<AdminConversationsTab days={90} onDays={vi.fn()} />);
const metric = (group: HTMLElement, label: string) => within(group).getByText(label).closest('article')!;
const disclosure = (label: string) => screen.getByText(label, { exact: true }).closest('summary')!;

describe('AdminConversationsTab — operational summary', () => {
  it('uses period totals and combines failed and interrupted responses consistently', async () => {
    renderTab();
    const summary = await screen.findByRole('group', { name: '대화 운영 요약' });
    expect(within(summary).getAllByRole('article')).toHaveLength(4);
    expect(metric(summary, '사용자 메시지').querySelector('.admin-kpi-value')).toHaveTextContent(/^126$/);
    expect(metric(summary, '활성 계정').querySelector('.admin-kpi-value')).toHaveTextContent(/^6$/);
    expect(metric(summary, '실패·중단').querySelector('.admin-kpi-value')).toHaveTextContent(/^5$/);
    expect(metric(summary, '실패·중단')).toHaveTextContent('문제 응답률 4.8%');
    expect(metric(summary, '진행 중 응답').querySelector('.admin-kpi-value')).toHaveTextContent(/^2$/);
  });

  it('defers all 90 daily rows until requested and names the partial day and combined failures', async () => {
    renderTab();
    await screen.findByRole('group', { name: '대화 운영 요약' });
    for (const label of ['일별 상세', '유형별 응답 상세', '리뷰 상세', '집계 기준']) {
      expect(disclosure(label).closest('details')).not.toHaveAttribute('open');
    }
    expect(screen.queryByRole('region', { name: '일별 대화 이용', hidden: true })).not.toBeInTheDocument();
    fireEvent.click(disclosure('일별 상세'));
    const daily = await screen.findByRole('region', { name: '일별 대화 이용' });
    expect(within(daily).getAllByRole('row')).toHaveLength(91);
    expect(within(daily).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
      '날짜', '이용한 대화', '사용자 메시지', '활성 계정', '실패·중단',
    ]);
    expect(within(daily).getAllByRole('row')[1]).toHaveTextContent('2026-11-08');
    expect(within(daily).getAllByRole('row')[1]).toHaveTextContent('집계 중');
    expect(within(daily).getAllByRole('row')[2]).toHaveTextContent('2026-11-07');
    expect(within(daily).getAllByRole('row')[2].lastElementChild).toHaveTextContent(/^5$/);
  });

  it('switches the trend between actual messages and problem-response counts', async () => {
    renderTab();
    await screen.findByTestId('conversation-trend');
    expect(plotSpy.mock.lastCall![0].data[0].y).toEqual(CONVERSATIONS.daily.map((day) => day.user_turns));
    expect(plotSpy.mock.lastCall![0].layout.yaxis.dtick).not.toBe(1);
    const selector = within(screen.getByRole('group', { name: '추이 지표' }));
    expect(selector.getByRole('button', { name: '메시지' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(selector.getByRole('button', { name: '실패·중단' }));
    expect(plotSpy.mock.lastCall![0].data[0].y).toEqual(CONVERSATIONS.daily.map((day) => day.failed));
    expect(selector.getByRole('button', { name: '실패·중단' })).toHaveAttribute('aria-pressed', 'true');
    expect(plotSpy.mock.lastCall![0].data[0].x).toEqual(CONVERSATIONS.daily.map((day) => day.date));
    expect(plotSpy.mock.lastCall![0].layout.yaxis.dtick).toBe(1);
  });

  it('prioritizes actual problem counts and keeps unattributed failures visible', async () => {
    renderTab();
    const attention = await screen.findByRole('region', { name: '확인할 응답 유형' });
    const ranked = within(attention).getAllByRole('listitem');
    expect(ranked).toHaveLength(2);
    expect(ranked[0]).toHaveTextContent('검색');
    expect(ranked[0]).toHaveTextContent('응답 15건 중2건');
    expect(ranked[1]).toHaveTextContent('대화');
    expect(ranked[1]).toHaveTextContent('응답 90건 중1건');
    // Overall failures+interruptions=5, but only 3 carry a known intent.
    expect(attention).toHaveTextContent('유형 미분류 2건은 위 목록에서 제외했습니다.');
  });

  it('excludes review-start times and undersized samples from the answer latency reference', async () => {
    vi.mocked(fetchAdminConversationStats).mockResolvedValue(response({
      ...CONVERSATIONS,
      latency: [
        { intent: 'chat', samples: 4, p50_ms: 2000, p95_ms: 60000 },
        { intent: 'search', samples: 13, p50_ms: 4800, p95_ms: 15300 },
        { intent: 'review', samples: 5, p50_ms: 30000, p95_ms: 90000 },
      ],
    }));
    renderTab();
    const label = await screen.findByText('응답 시간 참고 · 가장 긴 p95');
    const latency = label.parentElement!;
    expect(latency).toHaveTextContent('검색');
    expect(latency).toHaveTextContent('15.3초');
    expect(latency).toHaveTextContent('완료 응답 13건 측정');
    expect(latency).not.toHaveTextContent('60.0초');
    expect(latency).not.toHaveTextContent('90.0초');
  });

  it('can reopen daily details and resets them when the reporting period changes', async () => {
    const view = renderTab();
    await screen.findByRole('group', { name: '대화 운영 요약' });
    fireEvent.click(disclosure('일별 상세'));
    expect(await screen.findByRole('region', { name: '일별 대화 이용' })).toBeInTheDocument();
    fireEvent.click(disclosure('일별 상세'));
    await waitFor(() => expect(screen.queryByRole('region', { name: '일별 대화 이용', hidden: true })).not.toBeInTheDocument());
    fireEvent.click(disclosure('일별 상세'));
    expect(within(await screen.findByRole('region', { name: '일별 대화 이용' })).getAllByRole('row')).toHaveLength(91);

    vi.mocked(fetchAdminConversationStats).mockResolvedValueOnce(response({
      ...CONVERSATIONS,
      window: { ...CONVERSATIONS.window, days: 7, start: '2026-11-01T15:00:00Z' },
      daily: CONVERSATIONS.daily.slice(-7),
    }));
    view.rerender(<AdminConversationsTab days={7} onDays={vi.fn()} />);
    expect(screen.queryByRole('region', { name: '일별 대화 이용', hidden: true })).not.toBeInTheDocument();
    await screen.findByRole('group', { name: '대화 운영 요약' });
    expect(disclosure('일별 상세').closest('details')).not.toHaveAttribute('open');
    fireEvent.click(disclosure('일별 상세'));
    expect(within(await screen.findByRole('region', { name: '일별 대화 이용' })).getAllByRole('row')).toHaveLength(8);
  });

  it('shows latency samples beside percentiles and preserves missing p95 for small samples', async () => {
    renderTab();
    await screen.findByRole('group', { name: '대화 운영 요약' });
    expect(screen.queryByRole('region', { name: '유형별 응답 표', hidden: true })).not.toBeInTheDocument();
    fireEvent.click(disclosure('유형별 응답 상세'));
    const intents = await screen.findByRole('region', { name: '유형별 응답 표' });
    const search = within(intents).getByRole('rowheader', { name: '검색' }).closest('tr')!;
    expect(within(search).getAllByRole('cell').map((cell) => cell.textContent)).toEqual([
      '15', '1', '1', '4.8초', '15.3초', '13건',
    ]);
    const review = within(intents).getByRole('rowheader', { name: '리뷰 시작' }).closest('tr')!;
    expect(within(review).getAllByRole('cell').map((cell) => cell.textContent)).toEqual([
      '2', '0', '0', '1.2초', '—', '2건',
    ]);
  });

  it('shows a concise empty state without zero-filled charts or detail tables', async () => {
    vi.mocked(fetchAdminConversationStats).mockResolvedValue(response(EMPTY_CONVERSATIONS));
    renderTab();
    expect(await screen.findByRole('status')).toHaveTextContent('선택 기간에 대화 이용 기록이 없습니다.');
    expect(screen.queryByTestId('conversation-trend')).not.toBeInTheDocument();
    expect(screen.queryByRole('table', { hidden: true })).not.toBeInTheDocument();
    expect(plotSpy).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '7일' })).toBeInTheDocument();
  });

  it('keeps running-only activity visible and does not invent a zero error rate', async () => {
    vi.mocked(fetchAdminConversationStats).mockResolvedValue(response({
      ...EMPTY_CONVERSATIONS,
      totals: { ...EMPTY_CONVERSATIONS.totals, assistant_turns: 3, running: 3 },
    }));
    renderTab();
    const summary = await screen.findByRole('group', { name: '대화 운영 요약' });
    expect(metric(summary, '진행 중 응답').querySelector('.admin-kpi-value')).toHaveTextContent(/^3$/);
    expect(metric(summary, '실패·중단')).toHaveTextContent('문제 응답률 —');
    expect(screen.queryByText('선택 기간에 대화 이용 기록이 없습니다.')).not.toBeInTheDocument();
  });

  it('keeps retries and period controls available without presenting failures as zero activity', async () => {
    vi.mocked(fetchAdminConversationStats).mockRejectedValueOnce(new Error('stats unavailable'));
    const onDays = vi.fn();
    render(<AdminConversationsTab days={90} onDays={onDays} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('stats unavailable');
    expect(screen.queryByRole('group', { name: '대화 운영 요약' })).not.toBeInTheDocument();
    expect(screen.queryByText('선택 기간에 대화 이용 기록이 없습니다.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '28일' }));
    expect(onDays).toHaveBeenCalledWith(28);
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByRole('group', { name: '대화 운영 요약' })).toBeInTheDocument();
  });

  it('hides the old period while loading and ignores a late response from a superseded period', async () => {
    let resolve28!: (value: Response) => void;
    let resolve7!: (value: Response) => void;
    vi.mocked(fetchAdminConversationStats)
      .mockResolvedValueOnce(response(CONVERSATIONS))
      .mockReturnValueOnce(new Promise((resolve) => { resolve28 = resolve; }))
      .mockReturnValueOnce(new Promise((resolve) => { resolve7 = resolve; }));
    const view = renderTab();
    await screen.findByRole('group', { name: '대화 운영 요약' });
    view.rerender(<AdminConversationsTab days={28} onDays={vi.fn()} />);
    expect(screen.queryByRole('group', { name: '대화 운영 요약' })).not.toBeInTheDocument();
    await waitFor(() => expect(fetchAdminConversationStats).toHaveBeenCalledTimes(2));
    view.rerender(<AdminConversationsTab days={7} onDays={vi.fn()} />);
    await waitFor(() => expect(fetchAdminConversationStats).toHaveBeenCalledTimes(3));
    await act(async () => resolve7(response({ ...CONVERSATIONS,
      window: { ...CONVERSATIONS.window, days: 7 },
      totals: { ...CONVERSATIONS.totals, user_turns: 10 },
    })));
    const summary = await screen.findByRole('group', { name: '대화 운영 요약' });
    expect(metric(summary, '사용자 메시지').querySelector('.admin-kpi-value')).toHaveTextContent(/^10$/);
    await act(async () => resolve28(response(CONVERSATIONS)));
    expect(metric(summary, '사용자 메시지').querySelector('.admin-kpi-value')).toHaveTextContent(/^10$/);
  });
});
