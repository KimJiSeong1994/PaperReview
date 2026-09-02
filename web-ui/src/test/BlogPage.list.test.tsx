import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import BlogPage from '../components/BlogPage';
import { fetchBlogPosts } from '../api/client';
import { BLOG_SERIES } from '../seo/series';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return { ...actual, fetchBlogPosts: vi.fn(), fetchBlogPost: vi.fn() };
});

/** `day` drives created_at, so recency is explicit rather than positional. */
function post(id: string, day: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id,
    slug: id,
    title: `Post ${id}`,
    excerpt: `Post ${id} excerpt`,
    content: '',
    author: '집현전 팀',
    tags: ['GraphRAG'],
    category: 'engineering',
    thumbnail_url: `/api/blog/figures/${id}.png`,
    reading_time_min: 7,
    created_at: `2026-06-${day}T00:00:00.000Z`,
    updated_at: `2026-06-${day}T00:00:00.000Z`,
    ...extra,
  };
}

/** Served out of order on purpose: the hero must sort, not trust the array. */
const POSTS = [
  post('c', '03'),
  post('f', '06'),
  post('a', '01', { thumbnail_url: null }),
  post('e', '05'),
  // The backend field may still be missing entirely if the list API is older.
  { ...post('b', '02'), thumbnail_url: undefined },
  post('d', '04', { tags: ['graphrag'] }),
];
// Newest → oldest: f, e, d | c, b, a. The first three are the hero's.

type PostsResponse = Awaited<ReturnType<typeof fetchBlogPosts>>;
const respond = (posts: unknown[]) => ({ data: { posts } }) as unknown as PostsResponse;

function LocationProbe() {
  const { pathname, search } = useLocation();
  return <span data-testid="location">{`${pathname}${search}`}</span>;
}

function renderBlog(entry = '/blog', isAdmin = false, initialCategory?: 'paper-review' | 'engineering') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <BlogPage isAdmin={isAdmin} initialCategory={initialCategory} />
      <LocationProbe />
    </MemoryRouter>,
  );
}

const list = () => screen.getByRole('region', { name: '전체 아티클' });
const hero = () => screen.getByRole('region', { name: '주요 글' });
const heroTitle = () => within(hero()).getByRole('heading').textContent;
const row = (title: string) => within(list()).getByRole('link', { name: title });

describe('BlogPage list rows', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(POSTS));
  });

  it('shows category, author, title, excerpt and thumbnail — and nothing else', async () => {
    renderBlog();
    await screen.findByRole('region', { name: '전체 아티클' });

    const article = row('Post c');
    expect(within(article).getByText('Engineering')).toBeInTheDocument();
    expect(within(article).getByText('집현전 팀')).toBeInTheDocument();
    expect(within(article).getByRole('heading', { name: 'Post c' })).toBeInTheDocument();
    expect(within(article).getByText('Post c excerpt')).toBeInTheDocument();
    expect(article.querySelector('img')).toHaveAttribute('src', '/api/blog/figures/c.png?w=456');

    // The deleting is the redesign: no date, no dot, no reading time, no tags,
    // no arrow. Three text pieces, one image.
    expect(article.querySelector('time')).toBeNull();
    expect(article.textContent).not.toMatch(/2026/);
    expect(article.textContent).not.toMatch(/min read/);
    expect(article.textContent).not.toMatch(/GraphRAG/i);
    expect(article.querySelector('svg')).toBeNull();
  });

  it('renders a row without an image when the post has no thumbnail', async () => {
    renderBlog();
    await screen.findByRole('region', { name: '전체 아티클' });

    // `null` from the resolver, and the field missing altogether.
    for (const title of ['Post a', 'Post b']) {
      const article = row(title);
      expect(article.querySelector('img')).toBeNull();
      expect(article.querySelector('.blog-row-thumb')).toBeNull();
      // Still a row: same class, same text column, so the geometry holds.
      expect(article).toHaveClass('blog-row');
      expect(within(article).getByRole('heading', { name: title })).toBeInTheDocument();
      expect(within(article).getByText(`${title} excerpt`)).toBeInTheDocument();
    }
    expect(within(list()).getAllByRole('link')).toHaveLength(5);
  });

  it('lazy-loads every image at a sized figure URL with explicit dimensions', async () => {
    renderBlog();
    await screen.findByRole('region', { name: '전체 아티클' });

    const rowImages = Array.from(document.querySelectorAll<HTMLImageElement>('.blog-row img'));
    // Page 1 is c, f, a, e, b — three of them carry a thumbnail.
    expect(rowImages).toHaveLength(3);
    for (const img of rowImages) {
      expect(img).toHaveAttribute('loading', 'lazy');
      expect(img).toHaveAttribute('decoding', 'async');
      expect(img).toHaveAttribute('width', '228');
      expect(img).toHaveAttribute('height', '128');
      expect(img.getAttribute('src')).toContain('?w=456');
    }

    const heroImage = document.querySelector<HTMLImageElement>('.blog-hero-media img');
    expect(heroImage).toHaveAttribute('loading', 'lazy');
    expect(heroImage).toHaveAttribute('decoding', 'async');
    expect(heroImage).toHaveAttribute('width', '520');
    expect(heroImage).toHaveAttribute('height', '280');
    expect(heroImage?.getAttribute('src')).toBe('/api/blog/figures/f.png?w=640');
  });
});

describe('BlogPage hash target', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(POSTS));
  });

  it('scrolls to the fragment the footer links at, once the list has loaded', async () => {
    // React Router ignores the fragment, so /blog#series-index used to land at
    // the top of the list with the shelf ~2,000px below. The list is fetched,
    // so the target does not exist on the first render either.
    const scrolled: string[] = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function scrollIntoViewStub(this: Element) {
      scrolled.push(this.id || this.className);
    };
    try {
      renderBlog('/blog#series-index');
      await screen.findByRole('region', { name: '아티클 시리즈' });
      await waitFor(() => expect(scrolled).toContain('series-index'));
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });
});

describe('BlogPage hero carousel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(POSTS));
  });

  it('opens on the newest post and steps through the three newest', async () => {
    renderBlog();
    await screen.findByRole('region', { name: '주요 글' });

    expect(heroTitle()).toBe('Post f');

    fireEvent.click(within(hero()).getByRole('button', { name: '다음 글' }));
    expect(heroTitle()).toBe('Post e');

    fireEvent.click(within(hero()).getByRole('button', { name: '다음 글' }));
    expect(heroTitle()).toBe('Post d');

    // Wraps rather than dead-ending.
    fireEvent.click(within(hero()).getByRole('button', { name: '다음 글' }));
    expect(heroTitle()).toBe('Post f');

    fireEvent.click(within(hero()).getByRole('button', { name: '이전 글' }));
    expect(heroTitle()).toBe('Post d');
  });

  it('stays away until there are three posts to rotate', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(POSTS.slice(0, 2)));
    renderBlog();
    await screen.findByRole('region', { name: '전체 아티클' });

    expect(screen.queryByRole('region', { name: '주요 글' })).toBeNull();
    // …and with no hero there is nothing for the rail's 최근 글 to exclude,
    // so that card stays away too instead of echoing the list.
    expect(screen.queryByRole('region', { name: '최근 글' })).toBeNull();
  });
});

describe('BlogPage right rail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(POSTS));
  });

  it('lists the recent posts the hero is not already showing', async () => {
    renderBlog();
    await screen.findByRole('region', { name: '최근 글' });

    const recent = within(screen.getByRole('region', { name: '최근 글' }));
    expect(recent.getAllByRole('link').map((a) => a.textContent)).toEqual([
      'Post c',
      'Post b',
      'Post a',
    ]);
    // Nothing the hero is showing may appear here.
    for (const title of ['Post f', 'Post e', 'Post d']) {
      expect(recent.queryByText(title)).toBeNull();
    }
  });

  it('counts tags across casings and links them at the existing ?tag= filter', async () => {
    renderBlog();
    await screen.findByRole('region', { name: '인기 태그' });

    const tags = within(screen.getByRole('region', { name: '인기 태그' }));
    // 5 × "GraphRAG" + 1 × "graphrag" merge into one chip under the dominant
    // casing, exactly as /blog/tags shows it.
    const chip = tags.getByRole('link', { name: /GraphRAG/ });
    expect(chip).toHaveAttribute('href', '/blog?tag=GraphRAG');
    expect(chip.textContent).toBe('GraphRAG6');
    expect(tags.getByRole('link', { name: '태그 전체 보기' })).toHaveAttribute('href', '/blog/tags');
  });

  it('no longer duplicates the series, and the category tabs are gone', async () => {
    renderBlog();
    await screen.findByRole('region', { name: '아티클 시리즈' });

    // Series live in the bottom section only — not in the rail as well.
    expect(screen.queryByRole('region', { name: '시리즈' })).toBeNull();
    expect(screen.queryByRole('navigation', { name: '카테고리' })).toBeNull();
  });
});

describe('BlogPage pagination', () => {
  /** n posts, newest first in array order (all share a created_at). */
  const many = (n: number) => Array.from({ length: n }, (_, i) => post(`p${i}`, '01'));
  // The row's accessible name is the post title; its textContent is the whole row.
  const titles = () => within(list()).getAllByRole('link').map((a) => a.getAttribute('aria-label'));
  const pager = () => screen.getByRole('navigation', { name: '페이지' });
  const buttons = () => within(pager()).getAllByRole('button').map((b) => b.getAttribute('aria-label'));

  beforeEach(() => vi.clearAllMocks());

  it('shows five rows a page and windows the numbers around the current one', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(many(65)));
    renderBlog();
    await screen.findByRole('navigation', { name: '페이지' });

    expect(within(list()).getAllByRole('link')).toHaveLength(5);
    // 13 pages, 5 buttons: a window, not the whole range.
    expect(buttons()).toEqual(['이전 페이지', '1페이지', '2페이지', '3페이지', '4페이지', '5페이지', '다음 페이지']);
    expect(within(pager()).getByRole('button', { name: '1페이지' })).toHaveAttribute('aria-current', 'page');
  });

  it('slides the window and clamps it at the last page', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(many(65)));
    renderBlog('/blog?page=7');
    await screen.findByRole('navigation', { name: '페이지' });
    expect(buttons()).toEqual(['이전 페이지', '5페이지', '6페이지', '7페이지', '8페이지', '9페이지', '다음 페이지']);

    fireEvent.click(within(pager()).getByRole('button', { name: '다음 페이지' }));
    expect(buttons()).toEqual(['이전 페이지', '6페이지', '7페이지', '8페이지', '9페이지', '10페이지', '다음 페이지']);
  });

  it('moves to the sixth-through-tenth post and puts the page in the URL', async () => {
    const posts = many(65);
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(posts));
    renderBlog();
    await screen.findByRole('navigation', { name: '페이지' });

    fireEvent.click(within(pager()).getByRole('button', { name: '2페이지' }));

    expect(titles()).toEqual(posts.slice(5, 10).map((p) => p.title));
    expect(screen.getByTestId('location')).toHaveTextContent('/blog?page=2');

    // Page 1 drops the param rather than writing ?page=1.
    fireEvent.click(within(pager()).getByRole('button', { name: '이전 페이지' }));
    expect(screen.getByTestId('location').textContent).toBe('/blog');
  });

  it('disables prev on the first page', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(many(65)));
    renderBlog();
    await screen.findByRole('navigation', { name: '페이지' });

    expect(within(pager()).getByRole('button', { name: '이전 페이지' })).toBeDisabled();
    expect(within(pager()).getByRole('button', { name: '다음 페이지' })).not.toBeDisabled();
  });

  it('disables next on the last page', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(many(65)));
    // 65 posts = 13 pages, which the window never reaches in one click.
    renderBlog('/blog?page=13');
    await screen.findByRole('navigation', { name: '페이지' });

    expect(within(pager()).getByRole('button', { name: '다음 페이지' })).toBeDisabled();
    expect(within(pager()).getByRole('button', { name: '이전 페이지' })).not.toBeDisabled();
    expect(within(list()).getAllByRole('link')).toHaveLength(5);
  });

  it('clamps an out-of-range ?page= to the last page instead of emptying the list', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(POSTS));
    renderBlog('/blog?page=99');
    await screen.findByRole('navigation', { name: '페이지' });

    // 6 posts = 2 pages; page 2 holds the one left over.
    expect(titles()).toEqual(['Post d']);
    expect(within(pager()).getByRole('button', { name: '2페이지' })).toHaveAttribute('aria-current', 'page');
  });

  it('stays away when everything fits on one page', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(POSTS.slice(0, 5)));
    renderBlog();
    await screen.findByRole('region', { name: '전체 아티클' });

    expect(screen.queryByRole('navigation', { name: '페이지' })).toBeNull();
  });

  it('leaves the hero and the rail alone while the rows page', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(POSTS));
    renderBlog();
    await screen.findByRole('navigation', { name: '페이지' });
    const railTitles = () =>
      within(screen.getByRole('region', { name: '최근 글' })).getAllByRole('link').map((a) => a.textContent);
    const before = railTitles();

    fireEvent.click(within(pager()).getByRole('button', { name: '2페이지' }));

    expect(heroTitle()).toBe('Post f');
    expect(railTitles()).toEqual(before);
    // Still no overlap with the hero after paging.
    expect(railTitles()).toEqual(['Post c', 'Post b', 'Post a']);
  });
});

describe('BlogPage row and carousel controls', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(POSTS));
  });

  it('keeps the admin buttons out of the row anchor', async () => {
    renderBlog('/blog', true);
    await screen.findByRole('region', { name: '전체 아티클' });

    const anchor = row('Post c');
    const edit = within(anchor.parentElement!).getByRole('button', { name: 'Edit post' });
    // Interactive content cannot nest: this is what makes Edit tabbable at all.
    expect(anchor.contains(edit)).toBe(false);
    expect(within(anchor.parentElement!).getByRole('button', { name: 'Delete post' })).toBeInTheDocument();
    // The link's name stays the title — the buttons no longer fold into it.
    expect(anchor).toHaveAccessibleName('Post c');
    // A real href, so Enter on the focused row opens the post natively.
    expect(anchor).toHaveAttribute('href', '/blog/c');

    fireEvent.click(edit);
    expect(screen.queryByRole('region', { name: '전체 아티클' })).toBeNull();
    expect(screen.getByTestId('location').textContent).toBe('/blog');
  });

  it('collapses the thumbnail wrapper when the image fails to load', async () => {
    renderBlog();
    await screen.findByRole('region', { name: '전체 아티클' });

    const image = row('Post c').querySelector('img')!;
    const wrapper = image.parentElement!;
    expect(wrapper).toHaveClass('blog-row-thumb');
    expect(wrapper.style.display).toBe('');

    fireEvent.error(image);

    // Hiding only the <img> left the wrapper's 228x128 grey ground behind.
    expect(wrapper.style.display).toBe('none');
  });

  it('steps the hero with the arrow keys', async () => {
    renderBlog();
    await screen.findByRole('region', { name: '주요 글' });
    expect(hero()).toHaveAttribute('tabindex', '0');

    fireEvent.keyDown(hero(), { key: 'ArrowRight' });
    expect(heroTitle()).toBe('Post e');

    fireEvent.keyDown(hero(), { key: 'ArrowLeft' });
    expect(heroTitle()).toBe('Post f');

    // The arrows resolve by role, so only the visible slide's pair exists as
    // far as assistive tech — and as far as this query — is concerned.
    fireEvent.click(within(hero()).getByRole('button', { name: '다음 글' }));
    expect(heroTitle()).toBe('Post e');
  });
});

describe('BlogPage series index', () => {
  const entries = Object.entries(BLOG_SERIES);
  const section = () => screen.getByRole('region', { name: '아티클 시리즈' });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(POSTS));
  });

  it('renders one card per series with its title, count and link', async () => {
    renderBlog();
    await screen.findByRole('region', { name: '아티클 시리즈' });

    const cards = within(section()).getAllByRole('link');
    expect(cards).toHaveLength(entries.length);

    const [sid, series] = entries[0];
    const card = cards[0];
    expect(card).toHaveAttribute('href', `/blog/series/${sid}`);
    expect(within(card).getByRole('heading', { name: series.title })).toBeInTheDocument();
    expect(within(card).getByText(`아티클 ${series.slugs.length}개`)).toBeInTheDocument();
  });

  it('covers a card with its first chapter thumbnail, or with nothing at all', async () => {
    const [sid, series] = entries[0];
    // Deliberately paper-review while the list shows engineering: the cover
    // lookup runs over every post, not the category-filtered slice.
    const chapter = post('chapter', '01', {
      slug: series.slugs[0],
      category: 'paper-review',
      thumbnail_url: '/api/blog/figures/cover.png',
    });
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([...POSTS, chapter]));
    renderBlog();
    await screen.findByRole('region', { name: '아티클 시리즈' });

    const cards = within(section()).getAllByRole('link');
    const covered = cards.find((c) => c.getAttribute('href') === `/blog/series/${sid}`)!;
    const image = covered.querySelector('img')!;
    expect(image).toHaveAttribute('src', '/api/blog/figures/cover.png?w=456');
    expect(image).toHaveAttribute('loading', 'lazy');
    expect(image).toHaveAttribute('width', '190');
    expect(image).toHaveAttribute('height', '190');

    // Every other series has no post here, so no <img> — and still a card.
    const bare = cards.filter((c) => c !== covered);
    expect(bare).toHaveLength(entries.length - 1);
    for (const card of bare) {
      expect(card.querySelector('img')).toBeNull();
      expect(card.querySelector('.blog-series-cover')).toBeInTheDocument();
    }
  });
});

describe('BlogPage unified list', () => {
  const mixed = [
    post('e1', '06'),
    post('r1', '05', { category: 'paper-review' }),
    post('e2', '04'),
    post('r2', '03', { category: 'paper-review' }),
    post('e3', '02'),
    post('r3', '01', { category: 'paper-review' }),
  ];
  const titles = () => within(list()).getAllByRole('link').map((a) => a.getAttribute('aria-label'));

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(mixed));
  });

  it('shows both categories in one stream at /blog', async () => {
    renderBlog();
    await screen.findByRole('region', { name: '전체 아티클' });

    expect(titles()).toEqual(['Post e1', 'Post r1', 'Post e2', 'Post r2', 'Post e3']);
    // The row chip is what still tells them apart.
    expect(within(row('Post r1')).getByText('Paper Review')).toBeInTheDocument();
    expect(within(row('Post e1')).getByText('Engineering')).toBeInTheDocument();
  });

  it('still filters on the indexed /blog/category route, with a way back', async () => {
    renderBlog('/blog/category/paper-review', false, 'paper-review');
    await screen.findByRole('region', { name: '전체 아티클' });

    expect(titles()).toEqual(['Post r1', 'Post r2', 'Post r3']);
    expect(screen.getByText('Paper Reviews')).toBeInTheDocument();
    expect(screen.getByLabelText('전체 글 보기')).toHaveAttribute('href', '/blog');
  });

  it('windows the pager correctly at the real 71-post size', async () => {
    const all = Array.from({ length: 71 }, (_, i) => post(`p${i}`, '01'));
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(all));
    renderBlog('/blog?page=15');
    await screen.findByRole('navigation', { name: '페이지' });

    const pager = within(screen.getByRole('navigation', { name: '페이지' }));
    // 71 posts = 15 pages; the last window clamps to 11-15.
    expect(pager.getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual([
      '이전 페이지', '11페이지', '12페이지', '13페이지', '14페이지', '15페이지', '다음 페이지',
    ]);
    expect(pager.getByRole('button', { name: '다음 페이지' })).toBeDisabled();
    // 70 posts on 14 full pages leaves one on the last.
    expect(within(list()).getAllByRole('link')).toHaveLength(1);
  });

  it('draws the hero and the rail from the unified set', async () => {
    renderBlog();
    await screen.findByRole('region', { name: '주요 글' });

    expect(heroTitle()).toBe('Post e1');
    const recent = within(screen.getByRole('region', { name: '최근 글' }));
    // Newest three are the hero's; the rail picks up where it left off, across
    // both categories, with no overlap.
    expect(recent.getAllByRole('link').map((a) => a.textContent)).toEqual(['Post r2', 'Post e3', 'Post r3']);
  });
});

describe('BlogPage series shelf', () => {
  const section = () => screen.getByRole('region', { name: '아티클 시리즈' });
  const track = () => document.querySelector<HTMLElement>('.blog-series-grid')!;
  const REAL_SERIES = { ...BLOG_SERIES };

  /** Pin the shelf to `count` series, so these tests do not re-break every
   *  time a real series is added — the arrow rule is about count vs columns,
   *  not about which series happen to exist today. */
  function pinSeriesCount(count: number) {
    for (const id of Object.keys(BLOG_SERIES)) delete BLOG_SERIES[id];
    for (let i = 0; i < count; i += 1) {
      BLOG_SERIES[`s${i}`] = { title: `Series ${i}`, description: 'x', slugs: ['s'] };
    }
  }

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(POSTS));
  });

  afterEach(() => {
    for (const id of Object.keys(BLOG_SERIES)) delete BLOG_SERIES[id];
    Object.assign(BLOG_SERIES, REAL_SERIES);
  });

  it('renders one card per real series', async () => {
    const expected = Object.keys(REAL_SERIES).length;
    // Guards the guard: an emptied BLOG_SERIES would make the count assertion
    // vacuously true, and the shelf renders nothing at zero.
    expect(expected).toBeGreaterThanOrEqual(5);

    renderBlog();
    await screen.findByRole('region', { name: '아티클 시리즈' });

    expect(within(section()).getAllByRole('link')).toHaveLength(expected);
  });

  it('shows no arrows while the series fit one row', async () => {
    pinSeriesCount(4);
    renderBlog();
    await screen.findByRole('region', { name: '아티클 시리즈' });

    expect(within(section()).getAllByRole('link')).toHaveLength(4);
    // Not disabled — absent. Four across is a plain static grid.
    expect(within(section()).queryByRole('button')).toBeNull();
  });

  it('pages by a full row once the series overflow the shelf', async () => {
    pinSeriesCount(6);
    renderBlog();
    await screen.findByRole('region', { name: '아티클 시리즈' });

    const prev = within(section()).getByRole('button', { name: '이전 시리즈' });
    const next = within(section()).getByRole('button', { name: '다음 시리즈' });
    expect(prev).toBeDisabled();
    expect(next).not.toBeDisabled();
    expect(track().style.transform).toBe('translateX(calc(0 * (100% + 24px)))');

    fireEvent.click(next);

    // 6 series over 4 columns = 2 pages; one step lands on the last.
    expect(track().style.transform).toBe('translateX(calc(-1 * (100% + 24px)))');
    expect(next).toBeDisabled();
    expect(prev).not.toBeDisabled();

    fireEvent.click(prev);
    expect(track().style.transform).toBe('translateX(calc(0 * (100% + 24px)))');
  });
});

describe('BlogPage hero stacking', () => {
  const slides = () => Array.from(document.querySelectorAll('.blog-hero-slide'));
  const shown = () => slides().filter((el) => !el.classList.contains('is-hidden'));

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(POSTS));
  });

  it('keeps every slide mounted so the hero cannot change height', async () => {
    renderBlog();
    await screen.findByRole('region', { name: '주요 글' });

    // All three share one grid cell; the container is as tall as the tallest.
    expect(slides()).toHaveLength(3);
    expect(shown()).toHaveLength(1);

    const container = hero();
    const nodes = slides();
    fireEvent.click(within(hero()).getByRole('button', { name: '다음 글' }));

    // Same section, same slide nodes — only which one is visible changed, so
    // there is nothing for the browser to reflow.
    expect(hero()).toBe(container);
    expect(slides()).toEqual(nodes);
    expect(slides()).toHaveLength(3);
    expect(shown()).toHaveLength(1);
    expect(heroTitle()).toBe('Post e');
  });

  it('offers no link or button from a hidden slide', async () => {
    renderBlog();
    await screen.findByRole('region', { name: '주요 글' });

    // One title link and one pair of arrows, though three slides are mounted.
    expect(within(hero()).getAllByRole('link')).toHaveLength(1);
    expect(within(hero()).getAllByRole('button')).toHaveLength(2);
    expect(within(hero()).getByRole('link')).toHaveAccessibleName('Post f');
  });
});
