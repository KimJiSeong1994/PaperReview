import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AdminContentTab from '../components/AdminContentTab';
import { fetchSampleConversations, getAdminDashboard } from '../api/client';

vi.mock('../api/client', async () => ({
  ...await vi.importActual<typeof import('../api/client')>('../api/client'),
  fetchSampleConversations: vi.fn(),
  getAdminDashboard: vi.fn(() => new Promise(() => {})),
}));

describe('AdminContentTab', () => {
  it('links public samples without loading the retired paper catalog', async () => {
    vi.mocked(fetchSampleConversations).mockResolvedValue([
      { id: 's1', slug: 'sample-one', title: '샘플 대화 제목', question: 'q', asof: '2026-11-01', turn_count: 3 },
    ]);
    render(<MemoryRouter><AdminContentTab /></MemoryRouter>);
    expect(await screen.findByText('샘플 대화 제목')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'sample-one' })).toHaveAttribute('href', '/samples/sample-one');
    expect(getAdminDashboard).not.toHaveBeenCalled();
    for (const label of ['논문 카탈로그', '최근 수집 논문', '리뷰 작업', '북마크']) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it('shows an empty sample list', async () => {
    vi.mocked(fetchSampleConversations).mockResolvedValue([]);
    render(<MemoryRouter><AdminContentTab /></MemoryRouter>);
    expect(await screen.findByText('공개 샘플이 없습니다.')).toBeInTheDocument();
  });
});
