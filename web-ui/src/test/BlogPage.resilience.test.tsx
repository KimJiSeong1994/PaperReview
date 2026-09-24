import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import BlogPage from '../components/BlogPage';
import { fetchBlogPost } from '../api/client';
import { resetBlogBootstrapForTests } from '../utils/blogBootstrap';

vi.mock('../api/client', async () => ({
  ...await vi.importActual<typeof import('../api/client')>('../api/client'),
  fetchBlogPost: vi.fn(),
}));

const seededPost = {
  id: 'seed', slug: 'seeded-post', title: 'Seeded title', excerpt: 'Seed excerpt',
  content: 'EASY_SEED_BODY', deep_content: 'DEEP_SEED_BODY', index_deep_view: true,
  deep_reading_time_min: 11, author: 'Team', tags: ['seed'], category: 'paper-review',
  thumbnail_url: null, reading_time_min: 3, created_at: '2026-09-20T10:00:00Z', updated_at: null,
  published: true, has_thumbnail: false,
};

function installSeed(post = seededPost, routeSlug = post.slug) {
  const script = document.createElement('script');
  script.id = 'blog-bootstrap';
  script.type = 'application/json';
  script.textContent = JSON.stringify({ version: 1, route: { slug: routeSlug }, post });
  document.body.append(script);
}

function RoutePage() {
  const { slug } = useParams();
  return <BlogPage isAdmin={false} slug={slug} />;
}

function NavigateToOther() {
  const navigate = useNavigate();
  return <button onClick={() => navigate('/blog/other-post')}>Other</button>;
}

function mount(path = '/blog/seeded-post') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <NavigateToOther />
      <Routes><Route path="/blog/:slug" element={<RoutePage />} /></Routes>
    </MemoryRouter>,
  );
}

describe('BlogPage bootstrap resilience', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('scrollTo', vi.fn());
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })));
  });

  afterEach(() => {
    cleanup();
    document.querySelector('#blog-bootstrap')?.remove();
    resetBlogBootstrapForTests(document);
    vi.unstubAllGlobals();
  });

  it('renders both seeded reading levels while revalidation is pending', async () => {
    installSeed();
    vi.mocked(fetchBlogPost).mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    mount();
    expect(await screen.findByText('EASY_SEED_BODY')).toBeInTheDocument();
    expect(screen.queryByText('Loading post...')).not.toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: /상세 읽기/ }));
    expect(await screen.findByText('DEEP_SEED_BODY')).toBeInTheDocument();
  });

  it('preserves a readable seed without an internal error banner on transient failure', async () => {
    installSeed();
    vi.mocked(fetchBlogPost).mockRejectedValue({ response: { status: 503 }, message: 'internal upstream detail' });
    mount();
    expect(await screen.findByText('EASY_SEED_BODY')).toBeInTheDocument();
    await waitFor(() => expect(fetchBlogPost).toHaveBeenCalled());
    expect(screen.queryByText('internal upstream detail')).not.toBeInTheDocument();
    expect(document.querySelector('meta[name="robots"]')).toHaveAttribute(
      'content', 'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1',
    );
  });

  it.each([404, 410])('purges body, bootstrap and article JSON-LD after %s', async status => {
    installSeed();
    const ssrGraph = document.createElement('script');
    ssrGraph.id = 'seo-json-ld';
    ssrGraph.type = 'application/ld+json';
    ssrGraph.textContent = JSON.stringify({ '@type': 'BlogPosting', articleBody: seededPost.content });
    document.head.append(ssrGraph);
    let rejectRequest!: (reason: unknown) => void;
    vi.mocked(fetchBlogPost).mockReturnValue(new Promise((_, reject) => { rejectRequest = reject; }));
    const first = mount();
    expect(await screen.findByText('EASY_SEED_BODY')).toBeInTheDocument();
    await act(async () => rejectRequest({ response: { status }, message: 'gone' }));
    expect(await screen.findByText('gone')).toBeInTheDocument();
    expect(screen.queryByText('EASY_SEED_BODY')).not.toBeInTheDocument();
    expect(document.getElementById('blog-bootstrap')).toBeNull();
    const structured = [...document.querySelectorAll('script[type="application/ld+json"]')];
    expect(structured.map(node => node.textContent).join('')).not.toContain('EASY_SEED_BODY');
    expect(structured.map(node => node.textContent).join('')).not.toContain('DEEP_SEED_BODY');
    expect(structured.map(node => node.textContent).join('')).not.toContain('"@type":"BlogPosting"');
    first.unmount();
    vi.mocked(fetchBlogPost).mockReturnValue(new Promise(() => {}));
    mount();
    expect(await screen.findByText('Loading post...')).toBeInTheDocument();
    expect(screen.queryByText('EASY_SEED_BODY')).not.toBeInTheDocument();
  });

  it('never shows an A seed under B and ignores A resolving after navigation', async () => {
    installSeed();
    let resolveA!: (value: unknown) => void;
    const requestA = new Promise(resolve => { resolveA = resolve; });
    const other = { ...seededPost, id: 'other', slug: 'other-post', title: 'Other title', content: 'OTHER_BODY' };
    vi.mocked(fetchBlogPost).mockImplementation((slug) => (
      slug === 'seeded-post' ? requestA : Promise.resolve({ data: other })
    ) as never);
    const user = userEvent.setup();
    mount();
    expect(await screen.findByText('EASY_SEED_BODY')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Other' }));
    expect(await screen.findByText('OTHER_BODY')).toBeInTheDocument();
    expect(screen.queryByText('EASY_SEED_BODY')).not.toBeInTheDocument();
    await act(async () => resolveA({ data: { ...seededPost, content: 'LATE_A_BODY' } }));
    expect(screen.queryByText('LATE_A_BODY')).not.toBeInTheDocument();
    expect(screen.getByText('OTHER_BODY')).toBeInTheDocument();
  });

  it('ignores a wrong-route seed and a malformed successful response', async () => {
    installSeed(seededPost, 'different-route');
    vi.mocked(fetchBlogPost).mockResolvedValue({ data: { slug: 'seeded-post', content: 42 } } as never);
    mount();
    expect(await screen.findByText('Failed to load post.')).toBeInTheDocument();
    expect(screen.queryByText('EASY_SEED_BODY')).not.toBeInTheDocument();
  });
});
