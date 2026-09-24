import { afterEach, describe, expect, it } from 'vitest';
import {
  invalidateBlogBootstrap,
  prepareBlogBootstrap,
  readBlogBootstrap,
  resetBlogBootstrapForTests,
} from '../utils/blogBootstrap';

const post = {
  id: 'post-1',
  slug: 'seeded-post',
  title: 'Seeded post',
  excerpt: 'Seed excerpt',
  content: 'EASY_SEED',
  deep_content: 'DEEP_SEED',
  index_deep_view: true,
  deep_reading_time_min: 9,
  author: 'Jiphyeonjeon Team',
  tags: ['SEO'],
  category: 'paper-review',
  thumbnail_url: null,
  reading_time_min: 3,
  created_at: '2026-09-20T10:00:00Z',
  updated_at: null,
  published: true,
  has_thumbnail: false,
};

function install(payload: unknown) {
  const script = document.createElement('script');
  script.id = 'blog-bootstrap';
  script.type = 'application/json';
  script.textContent = JSON.stringify(payload);
  document.body.append(script);
  return script;
}

describe('blog bootstrap reader', () => {
  afterEach(() => {
    document.querySelector('#blog-bootstrap')?.remove();
    resetBlogBootstrapForTests(document);
  });

  it('accepts the versioned explicit post shape and memoizes parsing', () => {
    const script = install({ version: 1, route: { slug: post.slug }, post });
    expect(readBlogBootstrap(document)?.post).toEqual(post);
    script.textContent = '{broken after first read';
    expect(readBlogBootstrap(document)?.post).toEqual(post);
  });

  it.each([
    { version: 2, route: { slug: post.slug }, post },
    { version: 1, route: { slug: 'other' }, post },
    { version: 1, route: { slug: post.slug }, post: { ...post, content: 42 } },
    { version: 1, route: { slug: post.slug }, post: { ...post, published: false } },
  ])('rejects an unsupported, wrong-route, or malformed payload', (payload) => {
    install(payload);
    expect(readBlogBootstrap(document)).toBeNull();
  });

  it('cannot resurrect a definitively invalidated seed on a later read', () => {
    install({ version: 1, route: { slug: post.slug }, post });
    expect(readBlogBootstrap(document)?.post.slug).toBe(post.slug);
    invalidateBlogBootstrap(post.slug, document);
    expect(readBlogBootstrap(document)).toBeNull();
    expect(document.getElementById('blog-bootstrap')).toBeNull();
  });

  it('preloads a matching article before mounting and preserves SSR on chunk failure', async () => {
    install({ version: 1, route: { slug: post.slug }, post });
    const failure = new Error('chunk unavailable');
    await expect(prepareBlogBootstrap(document, '/blog/seeded-post', () => Promise.reject(failure)))
      .resolves.toBe('preserve-ssr');
  });

  it('does not preload for a different path or invalid seed', async () => {
    install({ version: 1, route: { slug: post.slug }, post });
    let calls = 0;
    await expect(prepareBlogBootstrap(document, '/blog/other', async () => { calls += 1; }))
      .resolves.toBe('ready');
    expect(calls).toBe(0);
  });
});
