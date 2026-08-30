import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import BlogTagsPage from '../components/BlogTagsPage';
import { fetchBlogTags } from '../api/client';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return { ...actual, fetchBlogTags: vi.fn() };
});

type TagsResponse = Awaited<ReturnType<typeof fetchBlogTags>>;

const respond = (tags: { tag: string; count: number }[], pages = 1, page = 1) =>
  ({ data: { tags, total: tags.length, page, pages } }) as unknown as TagsResponse;

const TAGS = [
  { tag: 'GraphRAG', count: 4 },
  { tag: 'Graph Neural Network', count: 2 },
];

/** Mirrors the live URL into the DOM so tests can assert on ?page=. */
function LocationProbe() {
  const { pathname, search } = useLocation();
  return <span data-testid="location">{`${pathname}${search}`}</span>;
}

function renderTags(entry = '/blog/tags') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <BlogTagsPage />
      <LocationProbe />
    </MemoryRouter>,
  );
}

/** The page argument of the most recent request. */
function lastRequestedPage() {
  const calls = vi.mocked(fetchBlogTags).mock.calls;
  return calls[calls.length - 1][0];
}

describe('BlogTagsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBlogTags).mockResolvedValue(respond(TAGS));
    window.scrollTo = vi.fn();
  });

  it('renders one chip per tag, without counts', async () => {
    renderTags();
    const chip = await screen.findByRole('link', { name: 'GraphRAG' });
    expect(chip).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Graph Neural Network' })).toBeTruthy();
    // Kakao shows no counts on chips; neither do we.
    expect(screen.queryByText('4')).toBeNull();
  });

  it('links each chip to the filtered blog list with the tag encoded', async () => {
    renderTags();
    const chip = await screen.findByRole('link', { name: 'Graph Neural Network' });
    expect(chip.getAttribute('href')).toBe('/blog?tag=Graph%20Neural%20Network');
  });

  it('requests page 2 when mounted at ?page=2', async () => {
    renderTags('/blog/tags?page=2');
    await waitFor(() => expect(fetchBlogTags).toHaveBeenCalled());
    expect(lastRequestedPage()).toBe(2);
  });

  it('Next moves the URL to ?page=2 and refetches', async () => {
    vi.mocked(fetchBlogTags).mockResolvedValue(respond(TAGS, 3));
    renderTags();
    fireEvent.click(await screen.findByRole('button', { name: '다음' }));

    await waitFor(() => expect(lastRequestedPage()).toBe(2));
    expect(screen.getByTestId('location').textContent).toBe('/blog/tags?page=2');
  });

  it('Prev returns to page 1 and drops ?page= from the URL', async () => {
    vi.mocked(fetchBlogTags).mockResolvedValue(respond(TAGS, 3, 2));
    renderTags('/blog/tags?page=2');
    fireEvent.click(await screen.findByRole('button', { name: '이전' }));

    await waitFor(() => expect(lastRequestedPage()).toBe(1));
    expect(screen.getByTestId('location').textContent).toBe('/blog/tags');
  });

  it('disables Prev on the first page and Next on the last', async () => {
    vi.mocked(fetchBlogTags).mockResolvedValue(respond(TAGS, 2));
    renderTags();
    expect((await screen.findByRole('button', { name: '이전' })).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('button', { name: '다음' }).hasAttribute('disabled')).toBe(false);

    vi.mocked(fetchBlogTags).mockResolvedValue(respond(TAGS, 2, 2));
    renderTags('/blog/tags?page=2');
    await waitFor(() => {
      const nexts = screen.getAllByRole('button', { name: '다음' });
      expect(nexts[nexts.length - 1].hasAttribute('disabled')).toBe(true);
    });
  });

  it('marks the current page button with aria-current', async () => {
    vi.mocked(fetchBlogTags).mockResolvedValue(respond(TAGS, 3, 2));
    renderTags('/blog/tags?page=2');
    const current = await screen.findByRole('button', { name: '2' });
    expect(current.getAttribute('aria-current')).toBe('page');
    expect(screen.getByRole('button', { name: '1' }).getAttribute('aria-current')).toBeNull();
  });

  it('shows the empty state for an out-of-range page instead of crashing', async () => {
    vi.mocked(fetchBlogTags).mockResolvedValue(respond([], 4, 99));
    renderTags('/blog/tags?page=99');
    expect(await screen.findByText('태그가 없습니다')).toBeTruthy();
  });

  it('shows an error message when the request fails', async () => {
    vi.mocked(fetchBlogTags).mockRejectedValue(new Error('boom'));
    renderTags();
    expect(await screen.findByText(/태그를 불러오지 못했습니다/)).toBeTruthy();
    // A failure must not read as "no tags exist".
    expect(screen.queryByText('태그가 없습니다')).toBeNull();
  });
});
