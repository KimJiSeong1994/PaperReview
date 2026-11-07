import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import AdminOverviewTab from '../components/AdminOverviewTab';
import { fetchAdminOverview } from '../api/client';
import { OVERVIEW } from './fixtures/adminOverview';

vi.mock('../api/client', async () => ({ ...await vi.importActual('../api/client'), fetchAdminOverview: vi.fn() }));
vi.mock('../PlotlyChart', () => ({ default: () => <div data-testid="traffic-chart" /> }));
beforeEach(() => vi.mocked(fetchAdminOverview).mockReset().mockResolvedValue({ data: OVERVIEW } as Awaited<ReturnType<typeof fetchAdminOverview>>));
const renderOverview = () => render(<MemoryRouter><AdminOverviewTab days={7} onDays={vi.fn()} /></MemoryRouter>);

it('shows only three traffic KPIs, one trend, and readable page/channel ranks', async () => {
  renderOverview();
  const metrics = await screen.findByRole('group', { name: '방문 핵심 지표' });
  expect(within(metrics).getAllByRole('article')).toHaveLength(3);
  expect(metrics).toHaveTextContent('1,248');
  expect(metrics).toHaveTextContent('↑ 20.0%');
  expect(metrics).toHaveTextContent('↓ 4.0%');
  expect(await screen.findByTestId('traffic-chart')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /GraphRAG/ })).toHaveAttribute('href', '/blog/graphrag');
  expect(screen.getByText('직접 방문')).toBeInTheDocument();
  expect(screen.queryByText('24시간 첫 이용률')).not.toBeInTheDocument();
  expect(screen.queryByText('주의')).not.toBeInTheDocument();
});

it('does not invent growth when the baseline is zero or missing', async () => {
  vi.mocked(fetchAdminOverview).mockResolvedValueOnce({ data: { ...OVERVIEW,
    comparison: { ...OVERVIEW.comparison, totals: { visitors: 0, page_views: 0, returning_visitors: 0 } },
  } } as unknown as Awaited<ReturnType<typeof fetchAdminOverview>>);
  const first = renderOverview();
  expect((await screen.findAllByText('이전 0 · 증감률 없음'))).toHaveLength(3);
  first.unmount();
  vi.mocked(fetchAdminOverview).mockResolvedValueOnce({ data: { ...OVERVIEW,
    comparison: { ...OVERVIEW.comparison, available: false },
  } } as unknown as Awaited<ReturnType<typeof fetchAdminOverview>>);
  renderOverview();
  expect((await screen.findAllByText('비교 데이터 부족'))).toHaveLength(3);
});

it('shows an unconnected source as unavailable, not zero acquisition', async () => {
  vi.mocked(fetchAdminOverview).mockResolvedValueOnce({ data: { ...OVERVIEW,
    acquisition: { state: 'not_connected', synced_at: null, channels: [] },
  } } as unknown as Awaited<ReturnType<typeof fetchAdminOverview>>);
  renderOverview();
  expect(await screen.findByText('유입 경로 데이터가 아직 연결되지 않았습니다.')).toBeInTheDocument();
});

it('keeps the period control and retry available on failure', async () => {
  vi.mocked(fetchAdminOverview).mockRejectedValueOnce(new Error('unavailable'));
  renderOverview();
  expect(await screen.findByRole('alert')).toHaveTextContent('unavailable');
  expect(screen.queryByRole('group', { name: '방문 핵심 지표' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '28일' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
  expect(await screen.findByRole('group', { name: '방문 핵심 지표' })).toBeInTheDocument();
});
