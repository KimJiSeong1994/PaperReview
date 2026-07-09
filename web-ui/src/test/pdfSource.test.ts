import { describe, expect, it } from 'vitest';
import { buildPdfSrc } from '../utils/pdfSource';

describe('buildPdfSrc', () => {
  it('routes arXiv PDFs through the same-origin proxy to avoid browser CORS failures', () => {
    expect(buildPdfSrc('https://arxiv.org/pdf/1903.03894.pdf')).toBe(
      '/api/pdf/proxy?url=https%3A%2F%2Farxiv.org%2Fpdf%2F1903.03894.pdf',
    );
  });

  it('keeps local API proxy URLs unchanged', () => {
    expect(buildPdfSrc('/api/pdf/proxy?url=https%3A%2F%2Farxiv.org%2Fpdf%2F1903.03894.pdf')).toBe(
      '/api/pdf/proxy?url=https%3A%2F%2Farxiv.org%2Fpdf%2F1903.03894.pdf',
    );
  });

  it('normalizes same-origin absolute URLs to relative paths', () => {
    expect(buildPdfSrc('http://localhost:3000/api/pdf/proxy?url=x')).toBe('/api/pdf/proxy?url=x');
  });
});
