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
const post = (slug: string, title = slug, extra: Partial<{ reading_time_min: number; thumbnail_url: string; category: string }> = {}) => ({
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

describe('SeriesPage reading and comparison', () => {
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

  it('keeps stable labels, guidance and evidence readable during a deferred request, in reading-first order', () => {
    vi.mocked(fetchBlogPosts).mockReturnValue(deferred().promise);
    const { container } = mount();
    const comparison = GEO_COMPARISONS.graphrag;
    expect(screen.getByRole('status')).toHaveTextContent('시리즈 글을 불러오는 중입니다.');
    expect(screen.getByText(comparison.question)).toBeInTheDocument();
    for (const step of comparison.reading_guide) {
      expect(screen.getByRole('heading', { name: step.title })).toBeInTheDocument();
      expect(screen.getByText(step.description)).toBeInTheDocument();
    }
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(container.querySelector('details')).not.toBeInTheDocument();
    expect(container.querySelectorAll('.blog-series-kicker')).toHaveLength(1);
    expect(screen.getByText('여기서 시작하세요')).toBeInTheDocument();
    const summary = screen.getByRole('region', { name: '논문 선택 비교' });
    const evidence = screen.getByRole('region', { name: '상세 근거와 출처' });
    expect(within(summary).queryByRole('link', { name: comparison.entries[0].label })).not.toBeInTheDocument();
    // Section order: start -> path -> reading list -> comparison -> evidence.
    expect(container.querySelector('.blog-header')?.nextElementSibling).toHaveClass('blog-series-start');
    const path = screen.getByRole('navigation', { name: '한눈에 보는 학습 경로' });
    expect(container.querySelector('.blog-series-start')?.nextElementSibling).toBe(path);
    expect(reading().compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(summary.compareDocumentPosition(evidence) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    comparison.reading_guide.forEach((step, index) => {
      expect(within(path).getByRole('link', { name: step.title })).toHaveAttribute('href', `#series-stage-${index + 1}`);
      expect(path).not.toHaveTextContent(step.description);
      expect(container.querySelector(`#series-stage-${index + 1}`)).toHaveTextContent(step.title);
    });
    const limits = container.querySelector('.geo-comparison-limits')!;
    expect(evidence).toContainElement(limits as HTMLElement);
    expect(within(summary).queryByText(comparison.limits)).not.toBeInTheDocument();
    const navigation = screen.getByRole('navigation', { name: '시리즈 바로가기' });
    // Jump nav order matches reading order: reading list, then comparison, then evidence.
    expect(within(navigation).getAllByRole('link').map((link) => link.textContent)).toEqual([
      '추천 읽기 순서', '논문 선택 비교', '상세 근거와 출처',
    ]);
    for (const link of within(navigation).getAllByRole('link')) {
      expect(container.querySelector(link.getAttribute('href')!)).toBeInTheDocument();
    }
    const cards = container.querySelectorAll('.geo-evidence-method');
    const decisions = container.querySelectorAll('.geo-decision');
    expect(container.querySelector('.geo-decision-grid')).toHaveAttribute('data-count', String(comparison.entries.length));
    comparison.entries.forEach((entry, index) => {
      expect(decisions[index].querySelectorAll('dd')).toHaveLength(3);
      expect(Array.from(decisions[index].querySelectorAll('dd')).map((cell) => cell.textContent)).toEqual([entry.summary.role, entry.summary.fit, entry.summary.caution]);
      expect(within(decisions[index] as HTMLElement).getByRole('link', { name: `${entry.label} 상세 근거` })).toHaveAttribute('href', `#series-evidence-${index + 1}`);
      expect(cards[index].querySelector('h3')).toHaveTextContent(entry.label);
      expect(cards[index].querySelectorAll('dt')).toHaveLength(comparison.axes.length);
      expect(cards[index].querySelector('h3')).toHaveAttribute('id', `series-evidence-${index + 1}`);
      comparison.axes.forEach((axis, axisIndex) => {
        const cell = entry.values[axis];
        const rendered = cards[index].querySelectorAll('dd')[axisIndex];
        expect(rendered).toHaveAttribute('data-state', cell.state);
        expect(rendered).toHaveTextContent((cell.state === 'known' ? cell.value : cell.reason)!);
        if (cell.state === 'unknown') expect(within(rendered).getByText('미확인')).toHaveClass('geo-state');
        if (cell.state === 'not_applicable') expect(within(rendered).getByText('해당 없음')).toHaveClass('geo-state');
      });
    });
  });

  it('hoists identical per-method sources beside the heading and omits per-cell copies', () => {
    vi.mocked(fetchBlogPosts).mockReturnValue(deferred().promise);
    const { container } = mount('gnn');
    const gcn = GEO_COMPARISONS.gnn.entries.find((entry) => entry.label === 'GCN')!;
    const sharedSource = gcn.values.retrieval_or_representation_unit.sources[0];
    expect(GEO_COMPARISONS.gnn.axes.every((axis) => gcn.values[axis].sources.length === 1 && gcn.values[axis].sources[0] === sharedSource)).toBe(true);
    const method = container.querySelector(`#series-evidence-${GEO_COMPARISONS.gnn.entries.indexOf(gcn) + 1}`)!.closest('.geo-evidence-method')!;
    const hoisted = method.querySelector('.geo-evidence-method-sources')!;
    expect(within(hoisted as HTMLElement).getAllByRole('link', { name: /출처/ })).toHaveLength(1);
    expect(method.querySelectorAll('dd .geo-comparison-sources')).toHaveLength(0);
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

  it('shows the first-post spotlight, reading time and series meta', async () => {
    const series = BLOG_SERIES.graphrag;
    const published = series.slugs.slice(1);
    vi.mocked(fetchBlogPosts).mockResolvedValue(response(
      [...published].reverse().map((slug, i) => post(slug, `제목 ${slug}`, { reading_time_min: i + 1, category: 'paper-review' })),
    ));
    const { container } = mount();
    const start = container.querySelector('.blog-series-start')! as HTMLElement;
    const cta = await within(start).findByRole('link', { name: '첫 글 읽기' });
    expect(cta).toHaveAttribute('href', `/blog/${published[0]}`);
    expect(within(start).getByRole('heading', { name: `제목 ${published[0]}` })).toBeInTheDocument();
    // The first chapter's minutes ride on the kicker, not on a lonely line.
    expect(start.querySelector('.blog-series-kicker')!.textContent).toBe(`여기서 시작하세요 · ${published.length}분`);
    expect(container.querySelector(`a[href="/blog/${series.slugs[0]}"]`)).not.toBeInTheDocument();
    expect(within(reading()).getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual(published.map((slug) => `/blog/${slug}`));
    const meta = container.querySelector('.blog-series-meta')!;
    expect(within(meta as HTMLElement).getByText('Paper Review')).toBeInTheDocument();
    // Count and minutes share one basis: published chapters (1+2+...+n minutes).
    const minutes = (published.length * (published.length + 1)) / 2;
    expect(meta.textContent).toContain(`${published.length}편 · 약 ${minutes}분`);
    expect(container.querySelector('.blog-series-path ol')).toHaveAttribute('data-count', String(GEO_COMPARISONS.graphrag.reading_guide.length));
    GEO_COMPARISONS.graphrag.reading_guide.forEach((stage, index) => {
      const group = screen.getByRole('region', { name: stage.title });
      expect(group).toHaveAttribute('aria-labelledby', `series-stage-${index + 1}`);
      expect(within(group).getByText(stage.description)).toBeInTheDocument();
      const firstMember = stage.slugs.find((slug) => published.includes(slug))!;
      expect(within(group).getByRole('list')).toHaveAttribute('start', String(published.indexOf(firstMember) + 1));
      expect(within(group).queryAllByRole('link').map((link) => link.getAttribute('href'))).toEqual(stage.slugs.filter((slug) => published.includes(slug)).map((slug) => `/blog/${slug}`));
    });
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
    expect(within(reading()).getAllByRole('link').map((link) => link.getAttribute('aria-label'))).toEqual(['첫 번째', '두 번째']);
    expect(fetchBlogPosts).toHaveBeenNthCalledWith(2, undefined, undefined, 2, 100);
    expect(jsonLd()).toContain(first);
    expect(jsonLd()).not.toContain('unrelated-');
  });

  it('stops pagination once every configured member has been found', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(response(BLOG_SERIES.gnn.slugs.map((slug) => post(slug, `정식 제목 ${slug}`)), 1, 20));
    mount('gnn');
    await within(reading()).findAllByRole('list');
    expect(fetchBlogPosts).toHaveBeenCalledTimes(1);
    const summary = screen.getByRole('region', { name: '논문 선택 비교' });
    for (const entry of GEO_COMPARISONS.gnn.entries) {
      const link = within(summary).getByRole('link', { name: entry.label });
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

  it('keeps a real starting paper and ordinary reading list without comparison data', async () => {
    const seriesId = 'jiphyeonjeon-build';
    const slug = BLOG_SERIES[seriesId].slugs[0];
    vi.mocked(fetchBlogPosts).mockResolvedValue(response([post(slug, '개발 기록 시작')]));
    const { container } = mount(seriesId);
    expect(await screen.findByRole('link', { name: '첫 글 읽기' })).toHaveAttribute('href', `/blog/${slug}`);
    expect(within(reading()).getByRole('link', { name: '개발 기록 시작' })).toHaveAttribute('href', `/blog/${slug}`);
    expect(screen.queryByRole('navigation', { name: '한눈에 보는 학습 경로' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '상세 근거와 출처' })).not.toBeInTheDocument();
    // A single reading-list target means no jump nav is rendered.
    expect(screen.queryByRole('navigation', { name: '시리즈 바로가기' })).not.toBeInTheDocument();
    expect(container.querySelector('.blog-series-reading-intro')).toHaveTextContent(
      BLOG_SERIES[seriesId].description.split('. ').slice(1).join('. '),
    );
  });

  it('scrolls to the hash target once it exists, after loading completes', async () => {
    Element.prototype.scrollIntoView = vi.fn();
    vi.mocked(fetchBlogPosts).mockResolvedValue(response([post(BLOG_SERIES.gnn.slugs[0])]));
    render(page('gnn', '#geo-comparison-title'));
    const target = await screen.findByRole('region', { name: '논문 선택 비교' });
    await waitFor(() => expect(target.scrollIntoView).toHaveBeenCalledWith({ block: 'start' }));
  });

  it('keeps the existing noindex not-found behavior', async () => {
    mount('invalid-series');
    expect(screen.getByText('Series not found.')).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector('meta[name="robots"]')).toHaveAttribute('content', 'noindex,nofollow'));
    expect(fetchBlogPosts).not.toHaveBeenCalled();
  });
});
