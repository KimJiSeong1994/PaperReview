import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AdminGrowthReport from '../components/AdminGrowthReport';
import AdminVisitsReport from '../components/AdminVisitsReport';
import AdminOverviewTab from '../components/AdminOverviewTab';
import { fetchAdminGrowthStats } from '../api/client';
import { GROWTH } from './fixtures/adminGrowth';

vi.mock('../PlotlyChart', () => ({ default: () => <div data-testid="growth-chart" /> }));

vi.mock('../api/client', async () => ({
  ...await vi.importActual('../api/client'),
  fetchAdminOverview: vi.fn(() => Promise.reject(new Error('analytics unavailable'))),
  fetchAdminGrowthStats: vi.fn(),
  fetchAdminVisitsReport: vi.fn(() => Promise.reject(new Error('analytics unavailable'))),
  fetchSampleConversations: vi.fn(() => Promise.resolve([])),
  fetchAdminConversationStats: vi.fn(() => Promise.reject(new Error('conversations unavailable'))),
  fetchAdminSoulStats: vi.fn(() => Promise.reject(new Error('souls unavailable'))),
  fetchAdminLlmUsage: vi.fn(() => Promise.reject(new Error('ledger unavailable'))),
}));

beforeEach(() => { vi.mocked(fetchAdminGrowthStats).mockReset().mockResolvedValue({ data: GROWTH } as Awaited<ReturnType<typeof fetchAdminGrowthStats>>); });

describe('account growth', () => {
  it('shows real-use totals, eligible denominators, pending cohorts and retention gaps', async () => {
    render(<AdminGrowthReport days={28} />);
    const kpis = await screen.findByRole('group', { name: '사용자 성장 핵심 지표' });
    expect(within(kpis).getByText('활성 사용자').closest('article')).toHaveTextContent('42');
    expect(within(kpis).getByText('첫 이용 사용자').closest('article')).toHaveTextContent('12');
    expect(within(kpis).getByText('24시간 첫 이용률').closest('article')).toHaveTextContent('50.0%');
    expect(screen.getByLabelText('가입에서 첫 메시지까지')).toHaveTextContent('가입 10명 → 관찰 완료 8명 → 24시간 내 첫 메시지 4명');
    expect(screen.getByText('D7').closest('tr')).toHaveTextContent('D700—12');
    expect(screen.getByText('D1').closest('tr')).toHaveTextContent('30.0%');
    expect(screen.getByText(/대기 계정은 성공·실패 비율에서 모두 제외/)).toBeInTheDocument();
    expect(screen.getByText(/계정 수와 나누어 전환율을 계산하지 않습니다/)).toBeInTheDocument();
    expect(screen.getByText(/가입 시각을 확인할 수 없는 2개 계정/)).toBeInTheDocument();
  });

  it('keeps account growth and the period control usable when browser analytics fails', async () => {
    const onDays = vi.fn();
    render(<AdminVisitsReport days={28} onDays={onDays} />);
    expect(await screen.findByRole('group', { name: '사용자 성장 핵심 지표' })).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('analytics unavailable');
    fireEvent.click(screen.getByRole('button', { name: '90일' }));
    expect(onDays).toHaveBeenCalledWith(90);
  });

  it('allows retry without showing a failed request as zero users', async () => {
    vi.mocked(fetchAdminGrowthStats).mockRejectedValueOnce(new Error('growth unavailable'));
    render(<AdminGrowthReport days={7} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('growth unavailable');
    expect(screen.queryByRole('group', { name: '사용자 성장 핵심 지표' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByRole('group', { name: '사용자 성장 핵심 지표' })).toBeInTheDocument();
  });

  it('keeps overview independent of account-growth data', async () => {
    render(<AdminOverviewTab days={28} onDays={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('analytics unavailable');
    expect(fetchAdminGrowthStats).not.toHaveBeenCalled();
    expect(screen.queryByText('24시간 첫 이용률')).not.toBeInTheDocument();
  });
});
