import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import BlogPage from '../components/BlogPage';
import { fetchBlogPosts } from '../api/client';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return { ...actual, fetchBlogPosts: vi.fn(), fetchBlogPost: vi.fn() };
});

function post(id: string, title: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    slug: id,
    title,
    excerpt: `${title} excerpt`,
    content: '',
    author: 'Jiphyeonjeon Team',
    tags: ['GraphRAG'],
    category: 'paper-review',
    reading_time_min: 3,
    created_at: '2026-06-14T00:00:00.000Z',
    updated_at: '2026-06-14T00:00:00.000Z',
    ...extra,
  };
}

type PostsResponse = Awaited<ReturnType<typeof fetchBlogPosts>>;
const respond = (posts: unknown[]) => ({ data: { posts } }) as unknown as PostsResponse;

function LocationProbe() {
  const { pathname, search } = useLocation();
  return <span data-testid="location">{`${pathname}${search}`}</span>;
}

function renderBlog(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <BlogPage isAdmin={false} />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe('BlogPage ?tag= filter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBlogPosts).mockResolvedValue(respond([post('a', 'GraphRAG survey')]));
  });

  it('fetches with the tag and shows it as a heading', async () => {
    renderBlog('/blog?tag=GraphRAG');
    await screen.findByText('GraphRAG survey');

    expect(vi.mocked(fetchBlogPosts).mock.calls[0][0]).toBe('GraphRAG');
    expect(screen.getByText('태그: GraphRAG')).toBeTruthy();
  });

  it('clears the filter back to /blog when × is clicked', async () => {
    renderBlog('/blog?tag=GraphRAG');
    await screen.findByText('태그: GraphRAG');

    fireEvent.click(screen.getByLabelText('태그 필터 해제'));

    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/blog'));
    await waitFor(() => expect(vi.mocked(fetchBlogPosts).mock.calls.at(-1)?.[0]).toBeUndefined());
    expect(screen.queryByText('태그: GraphRAG')).toBeNull();
  });

  it('loads everything when no tag is present', async () => {
    // Without a tag there is no auto-switch, so this post has to sit in the
    // default (engineering) tab to be visible at all.
    vi.mocked(fetchBlogPosts).mockResolvedValue(
      respond([post('b', 'Crawler health', { category: 'engineering' })]),
    );
    renderBlog('/blog');
    await screen.findByText('Crawler health');

    expect(vi.mocked(fetchBlogPosts).mock.calls[0][0]).toBeUndefined();
    expect(screen.queryByText(/^태그: /)).toBeNull();
  });
});
