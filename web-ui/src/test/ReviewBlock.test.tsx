import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ReviewBlock from '../components/conversation/ReviewBlock';
import { getReviewReport, getReviewStatus } from '../api/client';

vi.mock('../api/client', () => ({ getReviewStatus: vi.fn(), getReviewReport: vi.fn() }));

const block = {
  type: 'review_started' as const, session_id: 'rev-1', paper_index: 2, paper_title: 'HippoRAG', paper_key: 'k2',
};

const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

describe('ReviewBlock', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(getReviewStatus).mockReset();
    vi.mocked(getReviewReport).mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it('polls until the review completes, then offers the report and stops polling', async () => {
    vi.mocked(getReviewStatus)
      .mockResolvedValueOnce({ session_id: 'rev-1', status: 'processing', progress: '분석 1/3', report_available: false })
      .mockResolvedValueOnce({ session_id: 'rev-1', status: 'completed', report_available: true });
    vi.mocked(getReviewReport).mockResolvedValue({
      session_id: 'rev-1', report_markdown: '# 리포트', num_papers: 1, created_at: '',
    });
    const onCompleted = vi.fn();
    const onOpenReport = vi.fn();
    render(<MemoryRouter><ReviewBlock block={block} onCompleted={onCompleted} onOpenReport={onOpenReport} /></MemoryRouter>);

    expect(screen.getByText('진행 중')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('심층 리뷰를 시작하는 중…');
    expect(screen.queryByText(/Starting deep research/)).toBeNull();
    await tick(2000);
    expect(screen.getByRole('status').textContent).toContain('분석 1/3');
    await tick(2000);
    expect(screen.getByText('완료')).toBeTruthy();
    expect(onCompleted).toHaveBeenCalledWith({ sessionId: 'rev-1', title: 'HippoRAG', markdown: '# 리포트', stats: undefined });

    fireEvent.click(screen.getByRole('button', { name: '리포트 보기 →' }));
    expect(onOpenReport).toHaveBeenCalledWith('rev-1');
    await tick(30000);
    expect(getReviewStatus).toHaveBeenCalledTimes(2);
  });

  it('shows the failure with a way to 마이페이지', async () => {
    vi.mocked(getReviewStatus).mockResolvedValue({
      session_id: 'rev-1', status: 'failed', error: '원문을 받지 못했어요', report_available: false,
    });
    render(<MemoryRouter><ReviewBlock block={block} onCompleted={vi.fn()} onOpenReport={vi.fn()} /></MemoryRouter>);
    await tick(2000);
    expect(screen.getByRole('alert').textContent).toContain('원문을 받지 못했어요');
    expect(screen.getByRole('link', { name: '마이페이지에서 보기' }).getAttribute('href')).toBe('/mypage');
  });

  it('stops polling on unmount', async () => {
    vi.mocked(getReviewStatus).mockResolvedValue({ session_id: 'rev-1', status: 'processing', report_available: false });
    const { unmount } = render(<MemoryRouter><ReviewBlock block={block} onCompleted={vi.fn()} onOpenReport={vi.fn()} /></MemoryRouter>);
    await tick(2000);
    unmount();
    await tick(30000);
    expect(getReviewStatus).toHaveBeenCalledTimes(1);
  });
});
