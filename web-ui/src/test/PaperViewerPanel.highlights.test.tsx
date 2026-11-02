import { render, screen, waitFor } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import PaperViewerPanel from '../components/mypage/PaperViewerPanel';
import type { HighlightItem } from '../api/client';

// pdf.js does not run in jsdom: the document is a stub that records what it was asked to load.
vi.mock('react-pdf', () => ({
  Document: ({ file, children }: { file: string; children?: unknown }) => (
    <div data-testid="pdf-document" data-file={file}>{children as never}</div>
  ),
  Page: () => <div data-testid="pdf-page" />,
  pdfjs: { GlobalWorkerOptions: {}, version: 'test' },
}));
vi.mock('../api/client', () => ({
  resolvePdfUrl: vi.fn().mockResolvedValue({ pdf_url: null, source: null }),
  batchResolvePdfUrls: vi.fn().mockResolvedValue({ results: [] }),
  getS2ReaderUrl: vi.fn().mockResolvedValue({ reader_url: null, pdf_url: null }),
  generatePdfHighlights: vi.fn(),
  explainMathFormula: vi.fn(),
}));

beforeAll(() => {
  if (!('ResizeObserver' in globalThis)) {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  }
});

const highlights: HighlightItem[] = [
  { id: 'h1', text: 'graph memory improves recall', color: '#86efac', memo: '', created_at: '', category: 'finding' },
  { id: 'h2', text: 'only English corpora', color: '#fda4af', memo: '', created_at: '', category: 'limitation' },
];

describe('PaperViewerPanel with tool-made highlights', () => {
  it('loads the paper through the PDF proxy and seeds its overlay with the given highlights', async () => {
    render(
      <PaperViewerPanel
        bookmarkDetail={{ papers: [{ title: 'HippoRAG', authors: ['B. Gutiérrez'], year: 2024, pdf_url: 'https://arxiv.org/pdf/2405.14831' }] }}
        loadingDetail={false}
        hasSelectedBookmark
        autoSelectFirst
        highlights={highlights}
      />,
    );
    const document = await screen.findByTestId('pdf-document');
    expect(document.getAttribute('data-file')).toContain('/api/pdf/proxy');
    expect(document.getAttribute('data-file')).toContain(encodeURIComponent('https://arxiv.org/pdf/2405.14831'));
    await waitFor(() => expect(screen.getByRole('button', { name: /하이라이트 \(2\)/ })).toBeTruthy());
  });

  it('starts with an empty overlay when no highlights are given', async () => {
    render(
      <PaperViewerPanel
        bookmarkDetail={{ papers: [{ title: 'HippoRAG', authors: [], pdf_url: 'https://arxiv.org/pdf/2405.14831' }] }}
        loadingDetail={false}
        hasSelectedBookmark
        autoSelectFirst
      />,
    );
    await screen.findByTestId('pdf-document');
    expect(screen.getByRole('button', { name: /자동 하이라이트/ })).toBeTruthy();
  });
});
