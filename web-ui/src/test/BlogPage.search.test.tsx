import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import BlogPage from '../components/BlogPage';
import { fetchBlogPosts } from '../api/client';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    fetchBlogPosts: vi.fn(),
    fetchBlogPost: vi.fn(),
  };
});

function post(id: string, title: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    slug: id,
    title,
    excerpt: `${title} excerpt`,
    content: '',
    author: 'Jiphyeonjeon Team',
    tags: ['Search'],
    category: 'engineering',
    reading_time_min: 3,
    created_at: '2026-06-14T00:00:00.000Z',
    updated_at: '2026-06-14T00:00:00.000Z',
    ...extra,
  };
}

const ALL_POSTS = [post('a', 'Ranking rewrite'), post('b', 'Crawler health')];

type PostsResponse = Awaited<ReturnType<typeof fetchBlogPosts>>;
const respond = (posts: unknown[]) => ({ data: { posts } }) as unknown as PostsResponse;

/** Calls carrying the 5th (`q`) argument — i.e. searches, not the initial load-all. */
function searchCalls() {
  return vi.mocked(fetchBlogPosts).mock.calls.filter((call) => Boolean(call[4]));
}

/** Mirrors the live URL into the DOM so tests can assert on ?q=. */
function LocationProbe() {
  const { pathname, search } = useLocation();
  return <span data-testid="location">{`${pathname}${search}`}</span>;
}

function renderBlog(entry = '/blog') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <BlogPage isAdmin={false} />
      <LocationProbe />
    </MemoryRouter>,
  );
}

/** The overlay is the only place search lives — everything below goes through it. */
function openSearch() {
  fireEvent.click(screen.getByLabelText('블로그 글 검색'));
}

async function type(value: string) {
  fireEvent.change(screen.getByLabelText('검색어'), { target: { value } });
}

/** Result rows inside the overlay, so the list underneath can't satisfy a match. */
function resultTitles() {
  return Array.from(document.querySelectorAll('.blog-search-result-title')).map((n) => n.textContent);
}

describe('BlogPage search overlay', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(ALL_POSTS));
  });

  it('opens from the header icon and focuses the input', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    openSearch();

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByLabelText('검색어'));
    // Must stay a child of .blog-container: every --wov-*/--indigo* token is
    // scoped to it (and re-declared under :root[data-theme="light"]), so a
    // portal to <body> would render the overlay unstyled in both themes.
    expect(document.querySelector('.blog-container > .blog-search-overlay')).toBeTruthy();
  });

  it('closes on Escape and returns focus to the trigger', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByLabelText('블로그 글 검색'));
  });

  it('suggests the 3 most recent posts while the query is empty', async () => {
    const many = ['a', 'b', 'c', 'd'].map((id, i) => post(id, `Post ${i}`));
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(many));
    renderBlog();
    // Load barrier only. findAll, not find: with 4 posts the list also renders
    // the hero carousel, so the newest title is on screen twice by design.
    await screen.findAllByText('Post 0');

    openSearch();

    // No heading (toss lists suggestions bare) — assert the rows themselves.
    expect(resultTitles()).toEqual(['Post 0', 'Post 1', 'Post 2']);
    // The suggestions reuse the already-loaded list rather than refetching.
    expect(searchCalls()).toHaveLength(0);
  });

  it('debounces typing into a single query carrying q', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([ALL_POSTS[0]]));
    await type('r');
    await type('ra');
    await type('rank');

    await waitFor(() => expect(searchCalls()).toHaveLength(1));
    expect(searchCalls()[0][4]).toBe('rank');
    await waitFor(() => expect(resultTitles()).toEqual(['Ranking rewrite']));
  });

  it('shows the body snippet instead of the stored excerpt', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(
      respond([post('a', 'Ranking rewrite', { snippet: '…we reworked rank fusion…' })]),
    );
    await type('rank');

    const dialog = within(await screen.findByRole('dialog'));
    const snippet = await dialog.findByText(/we reworked/);
    expect(snippet).toHaveTextContent('…we reworked rank fusion…');
    expect(dialog.queryByText(/Ranking rewrite excerpt/)).not.toBeInTheDocument();
  });

  it('restores the unsearched state when the overlay is closed', async () => {
    renderBlog();
    await screen.findByText('Crawler health');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([ALL_POSTS[0]]));
    await type('rank');
    await waitFor(() => expect(resultTitles()).toEqual(['Ranking rewrite']));

    fireEvent.click(screen.getByLabelText('검색 닫기'));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    // Reopening starts clean rather than resurrecting the last query.
    openSearch();
    expect(screen.getByLabelText('검색어')).toHaveValue('');
    expect(resultTitles()).toEqual(ALL_POSTS.map((p) => p.title));
  });

  it('runs the query from ?q= on mount so a shared link reloads searched', async () => {
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([ALL_POSTS[0]]));
    renderBlog('/blog?q=rank');

    await waitFor(() => expect(searchCalls()).toHaveLength(1));
    expect(searchCalls()[0][4]).toBe('rank');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByLabelText('검색어')).toHaveValue('rank');
  });

  it('survives a click on the takeover background without dropping ?q=', async () => {
    // The overlay is a full-screen opaque takeover, so *every* stray click lands
    // on it. While it closed on backdrop mousedown, one click after opening a
    // shared /blog?q=… link closed the search and replaced the URL with /blog —
    // which read as "the link never opened the overlay at all".
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([ALL_POSTS[0]]));
    renderBlog('/blog?q=rank');
    await waitFor(() => expect(resultTitles()).toEqual(['Ranking rewrite']));

    const overlay = document.querySelector('.blog-search-overlay') as HTMLElement;
    fireEvent.mouseDown(overlay);
    fireEvent.click(overlay);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByLabelText('검색어')).toHaveValue('rank');
    expect(screen.getByTestId('location')).toHaveTextContent('/blog?q=rank');
  });

  it('still shows search results when the initial load-all failed', async () => {
    // The overlay must not inherit the list's empty/error state — a failed
    // load-all used to hide valid search results behind "게시물이 없습니다".
    vi.mocked(fetchBlogPosts).mockRejectedValueOnce(new Error('boom'));
    renderBlog();
    await screen.findByText('게시물이 없습니다');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([ALL_POSTS[0]]));
    await type('rank');

    await waitFor(() => expect(resultTitles()).toEqual(['Ranking rewrite']));
  });

  it('reports a failed search as a failure, not as "no results"', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    // e.g. a 422 from an over-long query, or any network error.
    vi.mocked(fetchBlogPosts).mockRejectedValue(new Error('boom'));
    await type('rank');

    expect(await screen.findByText('검색을 완료하지 못했습니다')).toBeInTheDocument();
    expect(screen.queryByText('검색 결과가 없어요')).not.toBeInTheDocument();
  });

  it('clears the search failure once the overlay is closed', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockRejectedValue(new Error('boom'));
    await type('rank');
    await screen.findByText('검색을 완료하지 못했습니다');

    vi.mocked(fetchBlogPosts).mockResolvedValue(respond(ALL_POSTS));
    fireEvent.click(screen.getByLabelText('검색 닫기'));
    openSearch();

    expect(screen.queryByText('검색을 완료하지 못했습니다')).not.toBeInTheDocument();
    // Reopening lands back on the suggestion list.
    expect(resultTitles()).toEqual(ALL_POSTS.map((p) => p.title));
  });

  it('does not blame the search when only the load-all failed', async () => {
    // Shared error state used to invert the fix: a *successful* empty search
    // reported itself as failed because load-all had errored earlier.
    vi.mocked(fetchBlogPosts).mockImplementation(((...args: unknown[]) =>
      args[4] ? Promise.resolve(respond([])) : Promise.reject(new Error('boom'))) as never);
    renderBlog('/blog?q=zzz');

    expect(await screen.findByText('검색 결과가 없어요')).toBeInTheDocument();
    expect(screen.queryByText('검색을 완료하지 못했습니다')).not.toBeInTheDocument();
  });

  it('does not flash "no results" while the request is still in flight', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    // The flash lasts a single render, so watch every mutation rather than
    // sampling: the render that publishes the debounced query lands before the
    // effect that flags `searching`, and used to paint the empty state with no
    // response yet in hand.
    const flashes: string[] = [];
    const observer = new MutationObserver(() => {
      const text = document.body.textContent ?? '';
      if (text.includes('검색 결과가 없어요')) flashes.push('empty');
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });

    vi.mocked(fetchBlogPosts).mockReturnValue(new Promise(() => {}) as never);
    await type('zzz');
    await waitFor(() => expect(searchCalls()).toHaveLength(1));
    observer.disconnect();

    expect(flashes).toEqual([]);
  });

  it('gives a result row the same figure the list already fetched, lazily', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(
      respond([post('a', 'Ranking rewrite', { thumbnail_url: '/api/blog/figures/fig-a.png' })]),
    );
    await type('rank');

    await waitFor(() => expect(resultTitles()).toEqual(['Ranking rewrite']));
    // Scoped to the row: alt="" keeps the figure out of the a11y tree, and the
    // overlay's brand logo is the only <img> with a role.
    const img = document.querySelector('.blog-search-result-thumb img') as HTMLImageElement;
    // w=456 and not w=228: the list rows under the overlay request the very
    // same URL, so a post visible in the list costs no extra bytes here.
    expect(img).toHaveAttribute('src', '/api/blog/figures/fig-a.png?w=456');
    expect(img).toHaveAttribute('loading', 'lazy');
    expect(img).toHaveAttribute('decoding', 'async');
    // Explicit box, so the row does not reflow when the figure lands.
    expect(img).toHaveAttribute('width', '164');
    expect(img).toHaveAttribute('height', '92');
  });

  it('renders a thumbnail-less result as a row with no image at all', async () => {
    // Never a broken image and never a shorter row: min-height holds the
    // geometry and the text column simply takes the width.
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(
      respond([post('a', 'Ranking rewrite', { thumbnail_url: null })]),
    );
    await type('rank');

    await waitFor(() => expect(resultTitles()).toEqual(['Ranking rewrite']));
    const row = document.querySelector('.blog-search-result') as HTMLElement;
    expect(row.querySelector('img')).toBeNull();
    expect(row.querySelector('.blog-search-result-thumb')).toBeNull();
  });

  it('carries title and snippet only — no category chip, no author', async () => {
    // The search row is deliberately lighter than the list row it covers.
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(
      respond([post('a', 'Ranking rewrite', {
        snippet: '…we reworked rank fusion…',
        author: 'Hong Gildong',
        category: 'paper-review',
      })]),
    );
    await type('rank');

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText(/we reworked/)).toBeInTheDocument();
    expect(within(dialog).queryByText('Hong Gildong')).not.toBeInTheDocument();
    expect(within(dialog).queryByText('Paper Review')).not.toBeInTheDocument();
    expect(dialog.querySelector('.blog-row-cat')).toBeNull();
    expect(dialog.querySelector('.blog-row-author')).toBeNull();
  });

  it('renders the no-results state when nothing matches', async () => {
    renderBlog();
    await screen.findByText('Ranking rewrite');
    openSearch();

    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([]));
    await type('zzz');

    expect(await screen.findByText('검색 결과가 없어요')).toBeInTheDocument();
  });
});
