import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import PaperViewerRoute from '../components/PaperViewerRoute';
import { viewerHrefForPaper } from '../utils/blogPaperReference';

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true }) }));
vi.mock('../components/SEOHead', () => ({ default: () => null }));
vi.mock('../components/mypage/PaperViewerPanel', () => ({
  default: ({ bookmarkDetail }: { bookmarkDetail: { papers: unknown[] } }) => (
    <div data-testid="viewer-paper">{JSON.stringify(bookmarkDetail.papers[0])}</div>
  ),
}));

describe('recommendation viewer identity handoff', () => {
  it.each([
    ['openalex_id', 'W123456'],
    ['semantic_scholar_id', 'a'.repeat(40)],
    ['pmid', '123456'],
  ])('retains %s in the actual viewer panel metadata', async (field, value) => {
    const href = viewerHrefForPaper({ title: 'Provider-only paper', [field]: value }, 'recommendation');
    render(<MemoryRouter initialEntries={[href]}><PaperViewerRoute /></MemoryRouter>);
    const paper = JSON.parse((await screen.findByTestId('viewer-paper')).textContent!);
    expect(paper[field]).toBe(value);
    expect(paper.title).toBe('Provider-only paper');
    expect(paper.doi).toBeUndefined();
  });
});
