import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SeriesPage from '../components/SeriesPage';
import { fetchBlogPosts } from '../api/client';
import { GEO_COMPARISONS } from '../seo/geoComparisons.generated';
import { BLOG_SERIES } from '../seo/series';

vi.mock('../api/client', async () => ({
  ...await vi.importActual<typeof import('../api/client')>('../api/client'),
  fetchBlogPosts: vi.fn(),
}));

const mount = (seriesId = 'graphrag') => render(
  <MemoryRouter initialEntries={[`/blog/series/${seriesId}`]}>
    <SeriesPage seriesId={seriesId} />
  </MemoryRouter>,
);

describe('SeriesPage GEO comparison', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('keeps the generated comparison readable while the post list is pending', () => {
    vi.mocked(fetchBlogPosts).mockReturnValue(new Promise(() => {}));
    mount();

    const comparison = GEO_COMPARISONS.graphrag;
    expect(screen.getByText(comparison.question)).toBeInTheDocument();
    expect(screen.getByText('Loading series...')).toBeInTheDocument();
    expect(screen.getAllByRole('rowheader').map((cell) => cell.textContent)).toEqual([
      '검색·표현 단위',
      '그래프 구성',
      '평가 조건',
      '근거 추적',
      '비용',
      '실패 조건',
    ]);
    const firstSource = comparison.entries.flatMap((entry) =>
      comparison.axes.flatMap((axis) => entry.values[axis].sources),
    )[0];
    const sourceLink = screen.getAllByRole('link', { name: /출처 1/ })[0];
    expect(sourceLink).toHaveAttribute('href', firstSource);
    expect(sourceLink).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('preserves comparison content when the post API fails', async () => {
    vi.mocked(fetchBlogPosts).mockRejectedValue(new Error('temporary failure'));
    mount('gnn');
    const comparison = GEO_COMPARISONS.gnn;

    expect(screen.getByText(comparison.question)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('Loading series...')).not.toBeInTheDocument());
    expect(screen.getByText(comparison.limits)).toBeInTheDocument();
    expect(screen.getByText(comparison.source_note)).toBeInTheDocument();
  });

  it('orders the fetched reading list by the unchanged series metadata', async () => {
    const [firstSlug, secondSlug] = BLOG_SERIES.gnn.slugs;
    vi.mocked(fetchBlogPosts).mockResolvedValue({
      data: {
        posts: [
          { slug: secondSlug, title: 'Second title', excerpt: 'second', reading_time_min: 2 },
          { slug: firstSlug, title: 'First title', excerpt: 'first', reading_time_min: 1 },
        ],
      },
    } as never);
    mount('gnn');

    const list = await screen.findByRole('list');
    expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      expect.stringContaining('First title'),
      expect.stringContaining('Second title'),
    ]);
  });

  it('keeps the existing noindex not-found behavior for an invalid series', () => {
    mount('invalid-series');
    expect(screen.getByText('Series not found.')).toBeInTheDocument();
    expect(document.querySelector('meta[name="robots"]')).toHaveAttribute('content', 'noindex,nofollow');
    expect(fetchBlogPosts).not.toHaveBeenCalled();
  });
});
