import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ReviewTab from '../components/conversation/ReviewTab';
import {
  downloadPosterPdf, generatePoster, generatePosterDirect, getReviewReport, getVerificationDetail,
} from '../api/review';

vi.mock('../api/review', async () => {
  const actual = await vi.importActual<typeof import('../api/review')>('../api/review');
  return {
    classifyPosterResponse: actual.classifyPosterResponse,
    classifyPosterError: actual.classifyPosterError,
    getReviewReport: vi.fn(),
    getVerificationDetail: vi.fn(),
    generatePoster: vi.fn(),
    generatePosterDirect: vi.fn(),
    downloadPosterPdf: vi.fn(),
  };
});

const report = {
  session_id: 'rev-1', report_markdown: '## 핵심 기여\n\n그래프 기반 기억.', num_papers: 1, created_at: '',
  verification_stats: {
    total_claims: 3, verifiable_claims: 3, verified: 1, partially_verified: 1, unverified: 0, contradicted: 1, verification_rate: 0.5,
  },
};

describe('ReviewTab', () => {
  beforeEach(() => {
    vi.mocked(getReviewReport).mockReset().mockResolvedValue(report as never);
    vi.mocked(getVerificationDetail).mockReset().mockResolvedValue({
      session_id: 'rev-1', cross_references: [], consensus: [],
      claims: [
        { id: 'c1', text: '기억 그래프가 회상을 높인다', verification_status: 'verified', evidence: 'Table 2 shows +12 recall.' },
        { id: 'c2', text: '모든 언어에 일반화된다', evidences: [{ text: 'Only English corpora were used.', verification_status: 'contradicted' }] },
        { id: 'c3', text: '학습 비용이 낮다' },
      ],
    });
    vi.mocked(generatePoster).mockReset();
    vi.mocked(generatePosterDirect).mockReset();
    vi.mocked(downloadPosterPdf).mockReset();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('shows the report with its summary line, then the claims with Korean status and evidence', async () => {
    render(<ReviewTab sessionId="rev-1" title="HippoRAG" />);
    expect(await screen.findByRole('heading', { name: '핵심 기여' })).toBeTruthy();
    expect(screen.getByText(/근거 확인 50%/)).toBeTruthy();
    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.map(row => within(row).getAllByRole('cell').map(cell => cell.textContent))).toEqual([
      ['기억 그래프가 회상을 높인다', '확인', 'Table 2 shows +12 recall.'],
      ['모든 언어에 일반화된다', '반박', 'Only English corpora were used.'],
      ['학습 비용이 낮다', '—', '—'],
    ]);
    expect(getVerificationDetail).toHaveBeenCalledWith('rev-1');
  });

  it('generates the poster, previews it sandboxed, and downloads it as PDF', async () => {
    vi.mocked(generatePoster).mockResolvedValue({ status: 'succeeded', poster_html: '<h1>Poster</h1>' } as never);
    vi.mocked(downloadPosterPdf).mockResolvedValue({ blob: new Blob(['%PDF']), filename: 'hipporag.pdf' });
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(<ReviewTab sessionId="rev-1" title="HippoRAG" />);
    await screen.findByRole('heading', { name: '핵심 기여' });

    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '포스터 생성' })); });
    expect(generatePoster).toHaveBeenCalledWith('rev-1');
    const frame = screen.getByTitle('HippoRAG 포스터 미리보기');
    expect(frame.getAttribute('srcdoc')).toBe('<h1>Poster</h1>');
    expect(frame.getAttribute('sandbox')).toBe('');

    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'PDF 내려받기' })); });
    expect(downloadPosterPdf).toHaveBeenCalledWith('<h1>Poster</h1>');
    expect(click).toHaveBeenCalledTimes(1);
    click.mockRestore();
  });

  it('falls back to the report-based poster when the session poster is unavailable', async () => {
    vi.mocked(generatePoster).mockRejectedValue({ response: { status: 404, data: { detail: { error_code: 'poster_session_unavailable' } } } });
    vi.mocked(generatePosterDirect).mockResolvedValue({ status: 'succeeded', poster_html: '<h1>Direct</h1>' } as never);
    render(<ReviewTab sessionId="rev-1" title="HippoRAG" />);
    await screen.findByRole('heading', { name: '핵심 기여' });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '포스터 생성' })); });
    expect(generatePosterDirect).toHaveBeenCalledWith(report.report_markdown, 1);
    expect(screen.getByTitle('HippoRAG 포스터 미리보기').getAttribute('srcdoc')).toBe('<h1>Direct</h1>');
  });

  it('explains that a fast review has no claim verification, without a summary line', async () => {
    vi.mocked(getReviewReport).mockResolvedValue({ ...report, verification_stats: undefined } as never);
    vi.mocked(getVerificationDetail).mockResolvedValue({
      session_id: 'rev-1', claims: [], cross_references: [], consensus: [], verification_stats: null,
    });
    render(<ReviewTab sessionId="rev-1" title="HippoRAG" />);
    expect(await screen.findByText(/빠른 리뷰에는 주장 검증 단계가 없어요/)).toBeTruthy();
    expect(screen.getByText(/정밀 리뷰 해줘/)).toBeTruthy();
    expect(screen.queryByText(/근거 확인/)).toBeNull();
    expect(screen.queryByText('검증한 주장이 없어요.')).toBeNull();
  });

  it('keeps the plain empty text for a review that verified and found no claims', async () => {
    const stats = { total_claims: 0, verifiable_claims: 0, verified: 0, partially_verified: 0, unverified: 0, contradicted: 0, verification_rate: 0 };
    vi.mocked(getReviewReport).mockResolvedValue({ ...report, verification_stats: stats } as never);
    vi.mocked(getVerificationDetail).mockResolvedValue({
      session_id: 'rev-1', claims: [], cross_references: [], consensus: [], verification_stats: stats,
    });
    render(<ReviewTab sessionId="rev-1" title="HippoRAG" />);
    expect(await screen.findByText('검증한 주장이 없어요.')).toBeTruthy();
    expect(screen.queryByText(/빠른 리뷰에는/)).toBeNull();
  });

  it('reads a vanished session as 확인 불가', async () => {
    vi.mocked(getReviewReport).mockRejectedValue({ response: { status: 404 } });
    render(<ReviewTab sessionId="gone" title="HippoRAG" />);
    expect((await screen.findByRole('status')).textContent).toContain('리뷰 세션을 더 이상 찾을 수 없어요.');
    expect(getVerificationDetail).not.toHaveBeenCalled();
  });
});
