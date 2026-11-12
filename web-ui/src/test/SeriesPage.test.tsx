import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SeriesPage from '../components/SeriesPage';
import { fetchBlogPosts } from '../api/client';
import { BLOG_SERIES } from '../seo/series';

vi.mock('../api/client', async () => ({
  ...await vi.importActual<typeof import('../api/client')>('../api/client'),
  fetchBlogPosts: vi.fn(),
}));

type Response = Awaited<ReturnType<typeof fetchBlogPosts>>;
const post = (slug: string, title = slug, extra: Partial<{
  reading_time_min: number;
  thumbnail_url: string;
  category: string;
  excerpt: string;
  created_at: string | null;
  updated_at: string;
}> = {}) => ({
  slug, title, excerpt: `${title} 설명`, reading_time_min: 2, ...extra,
});
const response = (posts: ReturnType<typeof post>[], page = 1, pages = 1) => ({ data: { posts, page, pages, total: posts.length } }) as Response;
function deferred() {
  let resolve!: (value: Response) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<Response>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
const page = (seriesId: string, hash = '') => <MemoryRouter initialEntries={[`/blog/series/${seriesId}${hash}`]}><SeriesPage seriesId={seriesId} /></MemoryRouter>;
const mount = (seriesId = 'graphrag', hash = '') => render(page(seriesId, hash));
const reading = () => screen.getByRole('region', { name: '추천 읽기 순서' });
const jsonLd = () => Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map((node) => node.textContent).join('');
const legacyResourceFragments = [
  '#series-about-title',
  '#series-guide-title',
  '#series-stage-1',
  '#geo-comparison-title',
  '#series-evidence-title',
  '#series-evidence-1',
];
function expectNoSeriesResources(container: HTMLElement) {
  expect(container.querySelector([
    '.blog-series-resources',
    '.blog-series-path',
    '.blog-series-stage',
    '.geo-comparison',
    '.geo-evidence',
    '.geo-decision',
    '.geo-evidence-method',
    '#series-about-title',
    '#series-guide-title',
    '[id^="series-stage-"]',
    '#geo-comparison-title',
    '#series-evidence-title',
    '[id^="series-evidence-"]',
  ].join(', '))).not.toBeInTheDocument();
  for (const fragment of legacyResourceFragments) {
    expect(container.querySelector(`a[href="${fragment}"]`)).not.toBeInTheDocument();
  }
  const main = container.querySelector('main#main')!;
  expect(main.lastElementChild).toHaveClass('blog-series-reading');
}

describe('SeriesPage reading list', () => {
  beforeEach(() => { vi.resetAllMocks(); });

  it('renders the shared header and a main landmark', () => {
    vi.mocked(fetchBlogPosts).mockReturnValue(deferred().promise);
    mount();
    expect(screen.getByRole('link', { name: 'Blog' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: /Search/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'My Page' })).toBeInTheDocument();
    const main = screen.getByRole('main');
    expect(main).toHaveAttribute('id', 'main');
    expect(main).toHaveClass('blog-content');
  });

  it('keeps the compact header and service strip above the reading section while loading', () => {
    vi.mocked(fetchBlogPosts).mockReturnValue(deferred().promise);
    const { container } = mount();
    expect(screen.getByRole('status')).toHaveTextContent('시리즈 글을 불러오는 중입니다.');
    expectNoSeriesResources(container);
    expect(container.querySelectorAll('.blog-series-kicker')).toHaveLength(1);
    expect(screen.getByText('SERIES')).toBeInTheDocument();
    expect(container.querySelector('.blog-container.blog-series-page')).toBeInTheDocument();
    expect(container.querySelector('.blog-header')?.nextElementSibling).toHaveClass('blog-series-service');
    const service = container.querySelector('aside.blog-series-service')!;
    expect(service.querySelector('.blog-series-service-label')).toHaveTextContent('SERVICE');
    expect(service).toHaveTextContent('논문 검색과 근거 확인을 집현전에서 이어 가세요.');
    expect(service.querySelector('a')).toHaveAttribute('href', '/');
    expect(service).toHaveTextContent('집현전에서 논문 찾기');
    expect(service.nextElementSibling).toBe(reading());
    expect(reading().querySelector('.blog-series-list')).not.toBeInTheDocument();
  });

  it('keeps the removed section absent on failure and after a successful retry', async () => {
    vi.mocked(fetchBlogPosts).mockRejectedValueOnce(new Error('temporary failure'))
      .mockResolvedValueOnce(response([post(BLOG_SERIES.gnn.slugs[0], '재시도 논문')]));
    const { container } = mount('gnn');
    expect(await screen.findByRole('alert')).toHaveTextContent('시리즈 글을 불러오지 못했습니다.');
    expectNoSeriesResources(container);
    expect(screen.queryByText('아직 공개된 시리즈 글이 없습니다.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await within(reading()).findByRole('link', { name: '재시도 논문' })).toBeInTheDocument();
    expectNoSeriesResources(container);
    expect(fetchBlogPosts).toHaveBeenCalledTimes(2);
  });

  it('renders one flat configured-order list with ordinals, publication metadata and full excerpts', async () => {
    const series = BLOG_SERIES.graphrag;
    const published = series.slugs.slice(1, 4);
    const fullExcerpt = 'GraphRAG는 문서 관계를 색인합니다. 다만 이 결과만으로 답변의 근거가 충분하다고 단정할 수는 없습니다.';
    vi.mocked(fetchBlogPosts).mockResolvedValue(response(
      [...published].reverse().map((slug) => {
        const index = published.indexOf(slug);
        return post(slug, `제목 ${slug}`, {
          reading_time_min: index + 1,
          category: 'paper-review',
          excerpt: index === 0 ? fullExcerpt : `제목 ${slug} 설명`,
          ...(index === 0 ? {
            created_at: '2026-02-28T23:45:00+09:00',
            thumbnail_url: '/api/blog/figures/first.png',
          } : index === 1 ? {
            updated_at: '2026-03-01T00:00:00Z',
            thumbnail_url: '/api/blog/figures/second.png',
          } : {
            created_at: '2026-02-30T12:00:00Z',
          }),
        });
      }),
    ));
    const { container } = mount();
    const rows = await within(reading()).findAllByRole('listitem');
    expect(container.querySelector('.blog-series-start')).not.toBeInTheDocument();
    expect(container.querySelector(`a[href="/blog/${series.slugs[0]}"]`)).not.toBeInTheDocument();
    expect(within(reading()).getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual(published.map((slug) => `/blog/${slug}`));
    expect(rows).toHaveLength(published.length);
    expect(rows.map((row) => row.querySelector('.blog-series-pos')?.textContent)).toEqual(['01', '02', '03']);
    expect(rows[0].querySelector('.blog-row-title')).toHaveTextContent(`제목 ${published[0]}`);
    expect(rows[0].querySelector('.blog-row-excerpt')).toHaveTextContent(fullExcerpt);
    expect(rows[0].querySelector('.blog-series-row-meta .blog-row-cat')).toHaveAttribute('data-cat', 'paper-review');
    expect(rows[0].querySelector('time')).toHaveAttribute('datetime', '2026-02-28');
    expect(rows[0].querySelector('time')).toHaveTextContent('2026.02.28');
    expect(rows[0].querySelector('.blog-series-time')).toHaveTextContent('1분');
    expect(rows[0].querySelector('img')).toHaveAttribute('loading', 'eager');
    expect(rows[0].querySelector('img')).toHaveAttribute('width', '228');
    expect(rows[0].querySelector('img')).toHaveAttribute('height', '128');
    expect(rows[1].querySelector('time')).not.toBeInTheDocument();
    expect(rows[1].querySelector('img')).toHaveAttribute('loading', 'lazy');
    expect(rows[2].querySelector('time')).not.toBeInTheDocument();
    expect(rows[2].querySelector('img')).not.toBeInTheDocument();
    const firstSentence = `${series.description.split('. ')[0]}.`;
    expect(container.querySelector('.blog-subtitle')).toHaveTextContent(firstSentence);
    const meta = container.querySelector('.blog-series-meta')!;
    expect(meta.textContent).toContain(`${published.length}편 · 약 6분`);
    expectNoSeriesResources(container);
  });

  it.each(Object.keys(BLOG_SERIES))('keeps %s compact in the hydrated reading-list view', async (seriesId) => {
    const series = BLOG_SERIES[seriesId];
    const published = series.slugs.slice(0, 2);
    vi.mocked(fetchBlogPosts).mockResolvedValue(response(
      [...published].reverse().map((slug) => post(slug)),
    ));
    const { container } = mount(seriesId);
    await within(reading()).findByRole('list');
    expect(within(reading()).getAllByRole('link').map((link) => link.getAttribute('href')))
      .toEqual(published.map((slug) => `/blog/${slug}`));
    expect(container.querySelector('.blog-series-meta')).toHaveTextContent('2편 · 약 4분');
    const description = document.head.querySelector('meta[name="description"]')?.getAttribute('content');
    expect(description).toBe(series.description);
    expect(description).not.toMatch(/\d+\s*편/);
    const intro = `${series.description.split('. ')[0]}.`;
    expect(container.querySelector('.blog-subtitle')).toHaveTextContent(intro);
    expect(container.querySelector('main#main')).not.toHaveTextContent(series.description.slice(intro.length).trim());
    expectNoSeriesResources(container);
    const graph = JSON.parse(document.querySelector('script#seo-json-ld')!.textContent!)['@graph'];
    expect(graph).toContainEqual(expect.objectContaining({
      '@type': 'CollectionPage',
      description,
      mainEntity: expect.objectContaining({ numberOfItems: published.length }),
    }));
  });

  it('distinguishes a successful empty reading list', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(response([]));
    const { container } = mount();
    expect(await screen.findByText('아직 공개된 시리즈 글이 없습니다.')).toHaveAttribute('role', 'status');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(within(reading()).queryByRole('link')).not.toBeInTheDocument();
    expectNoSeriesResources(container);
  });

  it('finds members older than the newest 100 and preserves configured order', async () => {
    const [first, second] = BLOG_SERIES.gnn.slugs;
    vi.mocked(fetchBlogPosts)
      .mockResolvedValueOnce(response(Array.from({ length: 100 }, (_, i) => post(`unrelated-${i}`)), 1, 2))
      .mockResolvedValueOnce(response([post(second, '두 번째'), post(first, '첫 번째')], 2, 2));
    mount('gnn');
    await within(reading()).findByRole('list');
    expect(within(reading()).getAllByRole('link').map((link) => link.getAttribute('aria-label'))).toEqual(['첫 번째', '두 번째']);
    expect(fetchBlogPosts).toHaveBeenNthCalledWith(2, undefined, undefined, 2, 100);
    await waitFor(() => expect(jsonLd()).toContain(first));
    expect(jsonLd()).not.toContain('unrelated-');
  });

  it('stops pagination once every configured member has been found', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(response(BLOG_SERIES.gnn.slugs.map((slug) => post(slug, `정식 제목 ${slug}`)), 1, 20));
    const { container } = mount('gnn');
    await within(reading()).findAllByRole('list');
    expect(fetchBlogPosts).toHaveBeenCalledTimes(1);
    expect(within(reading()).getAllByRole('link').map((link) => link.getAttribute('href')))
      .toEqual(BLOG_SERIES.gnn.slugs.map((slug) => `/blog/${slug}`));
    expectNoSeriesResources(container);
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

  it('handles development-series loading, error, retry, and empty states without resources', async () => {
    const seriesId = 'jiphyeonjeon-build';
    vi.mocked(fetchBlogPosts).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(response([]));
    const { container } = mount(seriesId);
    expect(screen.getByRole('status')).toHaveTextContent('불러오는 중');
    expectNoSeriesResources(container);
    await screen.findByRole('alert');
    expectNoSeriesResources(container);
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await screen.findByText('아직 공개된 시리즈 글이 없습니다.');
    expectNoSeriesResources(container);
  });

  it('keeps the development-series success view compact and linked', async () => {
    const seriesId = 'jiphyeonjeon-build';
    const slug = BLOG_SERIES[seriesId].slugs[0];
    vi.mocked(fetchBlogPosts).mockResolvedValue(response([post(slug, '개발 기록 시작')]));
    const { container } = mount(seriesId);
    expect(await within(reading()).findByRole('link', { name: '개발 기록 시작' })).toHaveAttribute('href', `/blog/${slug}`);
    expect(screen.queryByRole('link', { name: '첫 글 읽기' })).not.toBeInTheDocument();
    expect(within(reading()).getByRole('link', { name: '개발 기록 시작' })).toHaveAttribute('href', `/blog/${slug}`);
    expectNoSeriesResources(container);
  });

  it.each(Object.keys(BLOG_SERIES).flatMap((seriesId) => legacyResourceFragments.map((fragment) => ({ seriesId, fragment }))))(
    'does not restore removed content for old fragment $fragment on $seriesId',
    async ({ seriesId, fragment }) => {
      vi.mocked(fetchBlogPosts).mockResolvedValue(response([post(BLOG_SERIES[seriesId].slugs[0])]));
      const { container } = render(page(seriesId, fragment));
      await within(reading()).findByRole('list');
      expectNoSeriesResources(container);
      expect(container.querySelector(fragment)).not.toBeInTheDocument();
    },
  );

  it('keeps the existing noindex not-found behavior', async () => {
    mount('invalid-series');
    expect(screen.getByText('Series not found.')).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector('meta[name="robots"]')).toHaveAttribute('content', 'noindex,nofollow'));
    expect(fetchBlogPosts).not.toHaveBeenCalled();
  });
});
