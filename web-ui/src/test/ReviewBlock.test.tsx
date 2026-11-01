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

  it('shows the failure in Korean, keeping the raw error out of the text, with a way to 마이페이지', async () => {
    vi.mocked(getReviewStatus).mockResolvedValue({
      session_id: 'rev-1', status: 'failed', error: 'KeyError: abstract', report_available: false,
    });
    render(<MemoryRouter><ReviewBlock block={block} onCompleted={vi.fn()} onOpenReport={vi.fn()} /></MemoryRouter>);
    await tick(2000);
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('심층 리뷰에 실패했어요.');
    expect(alert.textContent).not.toContain('KeyError');
    expect(screen.getByTitle('KeyError: abstract')).toBeTruthy();
    expect(screen.getByRole('link', { name: '마이페이지에서 보기' }).getAttribute('href')).toBe('/mypage');
  });

  it('maps the service\'s English progress to Korean', async () => {
    vi.mocked(getReviewStatus).mockResolvedValue({
      session_id: 'rev-1', status: 'processing', progress: 'AI is analysing the papers...', report_available: false,
    });
    render(<MemoryRouter><ReviewBlock block={block} onCompleted={vi.fn()} onOpenReport={vi.fn()} /></MemoryRouter>);
    await tick(2000);
    expect(screen.getByRole('status').textContent).toContain('논문을 분석하는 중…');
    expect(screen.queryByText(/analysing/)).toBeNull();
  });

  it('treats a 404 as a vanished session: final state, no more polls, no retry', async () => {
    vi.mocked(getReviewStatus).mockRejectedValue({ response: { status: 404 } });
    render(<MemoryRouter><ReviewBlock block={block} onCompleted={vi.fn()} onOpenReport={vi.fn()} /></MemoryRouter>);
    await tick(2000);
    expect(screen.getByText('확인 불가')).toBeTruthy();
    expect(screen.getByText('리뷰 세션을 더 이상 찾을 수 없어요. 다시 요청하면 새로 시작합니다.')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
    await tick(60000);
    expect(getReviewStatus).toHaveBeenCalledTimes(1);
  });

  it('keeps polling through other errors', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(getReviewStatus).mockRejectedValue({ response: { status: 503 } });
    render(<MemoryRouter><ReviewBlock block={block} onCompleted={vi.fn()} onOpenReport={vi.fn()} /></MemoryRouter>);
    await tick(2000);
    await tick(2000);
    expect(getReviewStatus).toHaveBeenCalledTimes(2);
    expect(screen.queryByText('확인 불가')).toBeNull();
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
