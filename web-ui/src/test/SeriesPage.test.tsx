import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SeriesPage from '../components/SeriesPage';
import { fetchBlogPosts } from '../api/client';
import { GEO_COMPARISONS } from '../seo/geoComparisons.generated';
import { BLOG_SERIES } from '../seo/series';

vi.mock('../api/client', async () => ({
  ...await vi.importActual<typeof import('../api/client')>('../api/client'),
  fetchBlogPosts: vi.fn(),
}));

type Response = Awaited<ReturnType<typeof fetchBlogPosts>>;
const post = (slug: string, title = slug) => ({ slug, title, excerpt: `${title} 설명`, reading_time_min: 2 });
const response = (posts: ReturnType<typeof post>[], page = 1, pages = 1) => ({ data: { posts, page, pages, total: posts.length } }) as Response;
function deferred() {
  let resolve!: (value: Response) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<Response>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
const page = (seriesId: string) => <MemoryRouter><SeriesPage seriesId={seriesId} /></MemoryRouter>;
const mount = (seriesId = 'graphrag') => render(page(seriesId));
const reading = () => screen.getByRole('region', { name: '추천 읽기 순서' });
const jsonLd = () => Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map((node) => node.textContent).join('');

describe('SeriesPage reading and comparison', () => {
  beforeEach(() => { vi.resetAllMocks(); });

  it('keeps stable labels, guidance and evidence readable during a deferred request', () => {
    vi.mocked(fetchBlogPosts).mockReturnValue(deferred().promise);
    const { container } = mount();
    const comparison = GEO_COMPARISONS.graphrag;
    expect(screen.getByRole('status')).toHaveTextContent('시리즈 글을 불러오는 중입니다.');
    expect(screen.getByText(comparison.question)).toBeInTheDocument();
    for (const step of comparison.reading_guide) {
      expect(screen.getByRole('heading', { name: step.title })).toBeInTheDocument();
      expect(screen.getByText(step.description)).toBeInTheDocument();
    }
    const table = screen.getByRole('table');
    const headers = within(table).getAllByRole('columnheader');
    expect(headers.slice(1).map((cell) => cell.textContent)).toEqual(comparison.entries.map((entry) => entry.label));
    expect(within(table).queryByRole('link', { name: comparison.entries[0].label })).not.toBeInTheDocument();
    expect(within(table).getAllByRole('rowheader')).toHaveLength(comparison.axes.length);
    expect(screen.getByRole('region', { name: '논문 선택 비교표' })).toHaveAttribute('tabindex', '0');
    expect(table.querySelector('caption')).toHaveTextContent('여섯 기준으로 비교한 논문 선택표');
    expect(headers.every((header) => header.getAttribute('scope') === 'col')).toBe(true);
    expect(within(table).getAllByRole('rowheader').every((header) => header.getAttribute('scope') === 'row')).toBe(true);
    const limits = container.querySelector('.geo-comparison-limits')!;
    expect(limits.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(reading().compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const navigation = screen.getByRole('navigation', { name: '시리즈 바로가기' });
    expect(container.querySelector('.blog-header')?.nextElementSibling).toBe(navigation);
    expect(navigation.nextElementSibling).toHaveClass('blog-series-guide');
    for (const link of within(navigation).getAllByRole('link')) {
      expect(container.querySelector(link.getAttribute('href')!)).toBeInTheDocument();
    }
    const cards = container.querySelectorAll('.geo-comparison-card');
    comparison.entries.forEach((entry, index) => {
      expect(cards[index].querySelector('h3')).toHaveTextContent(entry.label);
      comparison.axes.forEach((axis, axisIndex) => {
        const cell = entry.values[axis];
        const desktop = table.querySelectorAll('tbody tr')[axisIndex].querySelectorAll('td')[index];
        const mobile = cards[index].querySelectorAll('dd')[axisIndex];
        for (const rendered of [desktop, mobile]) {
          expect(rendered).toHaveAttribute('data-state', cell.state);
          expect(rendered).toHaveTextContent((cell.state === 'known' ? cell.value : cell.reason)!);
          if (cell.state === 'unknown') expect(rendered).toHaveTextContent('미확인:');
          if (cell.state === 'not_applicable') expect(rendered).toHaveTextContent('해당 없음:');
          expect(Array.from(rendered.querySelectorAll('a')).map((link) => link.href)).toEqual(cell.sources);
          rendered.querySelectorAll('a').forEach((link) => expect(link).toHaveAttribute('rel', 'noopener noreferrer'));
        }
      });
    });
  });

  it('preserves comparison on failure and retries the complete request', async () => {
    vi.mocked(fetchBlogPosts).mockRejectedValueOnce(new Error('temporary failure'))
      .mockResolvedValueOnce(response([post(BLOG_SERIES.gnn.slugs[0], '재시도 논문')]));
    mount('gnn');
    expect(await screen.findByRole('alert')).toHaveTextContent('시리즈 글을 불러오지 못했습니다.');
    expect(screen.getByText(GEO_COMPARISONS.gnn.source_note)).toBeInTheDocument();
    expect(screen.queryByText('아직 공개된 시리즈 글이 없습니다.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await within(reading()).findByRole('link', { name: '재시도 논문' })).toBeInTheDocument();
    expect(fetchBlogPosts).toHaveBeenCalledTimes(2);
  });

  it('distinguishes a successful empty reading list', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(response([]));
    mount();
    expect(await screen.findByText('아직 공개된 시리즈 글이 없습니다.')).toHaveAttribute('role', 'status');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(within(reading()).queryByRole('link')).not.toBeInTheDocument();
  });

  it('finds members older than the newest 100 and preserves configured order', async () => {
    const [first, second] = BLOG_SERIES.gnn.slugs;
    vi.mocked(fetchBlogPosts)
      .mockResolvedValueOnce(response(Array.from({ length: 100 }, (_, i) => post(`unrelated-${i}`)), 1, 2))
      .mockResolvedValueOnce(response([post(second, '두 번째'), post(first, '첫 번째')], 2, 2));
    mount('gnn');
    await within(reading()).findByRole('list');
    expect(within(reading()).getAllByRole('link').map((link) => link.textContent)).toEqual(['1첫 번째', '2두 번째']);
    expect(fetchBlogPosts).toHaveBeenNthCalledWith(2, undefined, undefined, 2, 100);
    expect(jsonLd()).toContain(first);
    expect(jsonLd()).not.toContain('unrelated-');
  });

  it('stops pagination once every configured member has been found', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(response(BLOG_SERIES.gnn.slugs.map((slug) => post(slug, `정식 제목 ${slug}`)), 1, 20));
    mount('gnn');
    await within(reading()).findByRole('list');
    expect(fetchBlogPosts).toHaveBeenCalledTimes(1);
    const table = screen.getByRole('table');
    for (const entry of GEO_COMPARISONS.gnn.entries) {
      const link = within(table).getByRole('link', { name: entry.label });
      expect(link).toHaveAttribute('href', `/blog/${entry.slug}`);
      expect(link).toHaveAttribute('title', `정식 제목 ${entry.slug}`);
    }
  });

  it('does not present a partial list when a later page fails', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValueOnce(response([post(BLOG_SERIES.gnn.slugs[0], '부분 논문')], 1, 2))
      .mockRejectedValueOnce(new Error('page two failed'));
    mount('gnn');
    await screen.findByRole('alert');
    expect(within(reading()).queryByRole('list')).not.toBeInTheDocument();
    expect(jsonLd()).not.toContain('부분 논문');
  });

  it('clears old posts and JSON-LD immediately on series switch, including failure and retry', async () => {
    const next = deferred();
    vi.mocked(fetchBlogPosts).mockResolvedValueOnce(response([post(BLOG_SERIES.gnn.slugs[0], '이전 시리즈 논문')]))
      .mockReturnValueOnce(next.promise)
      .mockResolvedValueOnce(response([post(BLOG_SERIES.graphrag.slugs[0], '새 시리즈 논문')]));
    const view = mount('gnn');
    await within(reading()).findByRole('link', { name: '이전 시리즈 논문' });
    view.rerender(page('graphrag'));
    expect(screen.queryByText('이전 시리즈 논문')).not.toBeInTheDocument();
    expect(jsonLd()).not.toContain('이전 시리즈 논문');
    expect(screen.getByRole('status')).toHaveTextContent('불러오는 중');
    await act(async () => { next.reject(new Error('new series failed')); });
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(jsonLd()).not.toContain('이전 시리즈 논문');
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await within(reading()).findByRole('link', { name: '새 시리즈 논문' });
    await waitFor(() => expect(jsonLd()).toContain('새 시리즈 논문'));
  });

  it('ignores a late response from the previous series', async () => {
    const previous = deferred();
    vi.mocked(fetchBlogPosts).mockReturnValueOnce(previous.promise)
      .mockResolvedValueOnce(response([post(BLOG_SERIES.graphrag.slugs[0], '현재 논문')]));
    const view = mount('gnn');
    view.rerender(page('graphrag'));
    await within(reading()).findByRole('link', { name: '현재 논문' });
    await act(async () => { previous.resolve(response([post(BLOG_SERIES.gnn.slugs[0], '늦은 이전 논문')])); });
    expect(screen.queryByText('늦은 이전 논문')).not.toBeInTheDocument();
    expect(jsonLd()).not.toContain('늦은 이전 논문');
  });

  it('starts fresh when returning A → B → A while B remains pending', async () => {
    const pendingB = deferred();
    const returningA = deferred();
    vi.mocked(fetchBlogPosts)
      .mockResolvedValueOnce(response([post(BLOG_SERIES.gnn.slugs[0], '이전 A 논문')]))
      .mockReturnValueOnce(pendingB.promise)
      .mockReturnValueOnce(returningA.promise);
    const view = mount('gnn');
    await within(reading()).findByRole('link', { name: '이전 A 논문' });
    view.rerender(page('graphrag'));
    view.rerender(page('gnn'));
    expect(screen.getByRole('status')).toHaveTextContent('불러오는 중');
    expect(screen.queryByText('이전 A 논문')).not.toBeInTheDocument();
    expect(jsonLd()).not.toContain('이전 A 논문');
    await act(async () => { pendingB.resolve(response([post(BLOG_SERIES.graphrag.slugs[0], '늦은 B 논문')])); });
    expect(screen.queryByText('늦은 B 논문')).not.toBeInTheDocument();
    await act(async () => { returningA.resolve(response([post(BLOG_SERIES.gnn.slugs[0], '새 A 논문')])); });
    expect(within(reading()).getByRole('link', { name: '새 A 논문' })).toBeInTheDocument();
    expect(fetchBlogPosts).toHaveBeenCalledTimes(3);
  });

  it.each([
    { page: 1, pages: 3, posts: [] },
    { page: 3, pages: 3, posts: [] },
    { page: 2, pages: 1, posts: [] },
    { page: 2, pages: 2.5, posts: [] },
    { page: 2, pages: undefined, posts: [] },
    { page: 2, pages: 2, posts: null },
  ])('rejects invalid/non-progress pagination: %j', async (data) => {
    vi.mocked(fetchBlogPosts)
      .mockResolvedValueOnce(response([post(BLOG_SERIES.gnn.slugs[0], '부분 결과')], 1, 3))
      .mockResolvedValueOnce({ data } as Response);
    mount('gnn');
    await screen.findByRole('alert');
    expect(fetchBlogPosts).toHaveBeenCalledTimes(2);
    expect(within(reading()).queryByRole('list')).not.toBeInTheDocument();
    expect(jsonLd()).not.toContain('부분 결과');
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeInTheDocument();
  });

  it('handles a series without comparison content', async () => {
    const seriesId = Object.keys(BLOG_SERIES).find((id) => !(id in GEO_COMPARISONS))!;
    expect(seriesId).toBeDefined();
    vi.mocked(fetchBlogPosts).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(response([]));
    mount(seriesId);
    expect(screen.getByRole('status')).toHaveTextContent('불러오는 중');
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await screen.findByText('아직 공개된 시리즈 글이 없습니다.');
    expect(screen.queryByRole('heading', { name: '논문 선택 비교' })).not.toBeInTheDocument();
  });

  it('keeps the existing noindex not-found behavior', async () => {
    mount('invalid-series');
    expect(screen.getByText('Series not found.')).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector('meta[name="robots"]')).toHaveAttribute('content', 'noindex,nofollow'));
    expect(fetchBlogPosts).not.toHaveBeenCalled();
  });
});
