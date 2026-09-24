export interface BlogPostDetail {
  id: string;
  slug: string;
  title: string;
  excerpt: string;
  content: string;
  deep_content?: string | null;
  index_deep_view?: boolean;
  deep_reading_time_min?: number | null;
  author: string;
  tags: string[];
  category?: string;
  thumbnail_url?: string | null;
  reading_time_min: number;
  created_at: string;
  updated_at: string | null;
  published?: boolean;
  has_thumbnail?: boolean;
}

export interface BlogBootstrap {
  version: 1;
  route: { slug: string };
  post: BlogPostDetail;
}

interface BootstrapCache {
  parsed: boolean;
  value: BlogBootstrap | null;
  invalidatedSlugs: Set<string>;
}

const caches = new WeakMap<Document, BootstrapCache>();

function cacheFor(document: Document): BootstrapCache {
  let cache = caches.get(document);
  if (!cache) {
    cache = { parsed: false, value: null, invalidatedSlugs: new Set() };
    caches.set(document, cache);
  }
  return cache;
}

function isNullableString(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === 'string';
}

function isNullableNumber(value: unknown): value is number | null | undefined {
  return value === undefined || value === null || (typeof value === 'number' && Number.isFinite(value));
}

export function isBlogPostDetail(
  value: unknown,
  expectedSlug?: string,
  requirePublicShape = false,
): value is BlogPostDetail {
  if (!value || typeof value !== 'object') return false;
  const post = value as Record<string, unknown>;
  const valid = typeof post.id === 'string'
    && typeof post.slug === 'string'
    && (!expectedSlug || post.slug === expectedSlug)
    && typeof post.title === 'string'
    && typeof post.excerpt === 'string'
    && typeof post.content === 'string'
    && isNullableString(post.deep_content)
    && (post.index_deep_view === undefined || typeof post.index_deep_view === 'boolean')
    && isNullableNumber(post.deep_reading_time_min)
    && typeof post.author === 'string'
    && Array.isArray(post.tags)
    && post.tags.every((tag) => typeof tag === 'string')
    && (post.category === undefined || typeof post.category === 'string')
    && isNullableString(post.thumbnail_url)
    && typeof post.reading_time_min === 'number'
    && Number.isFinite(post.reading_time_min)
    && typeof post.created_at === 'string'
    && (post.updated_at === undefined || post.updated_at === null || typeof post.updated_at === 'string')
    && (post.published === undefined || typeof post.published === 'boolean')
    && (post.has_thumbnail === undefined || typeof post.has_thumbnail === 'boolean');
  return valid && (!requirePublicShape || (
    post.published === true
    && typeof post.has_thumbnail === 'boolean'
    && typeof post.index_deep_view === 'boolean'
    && Object.hasOwn(post, 'updated_at')
  ));
}

function parseBootstrap(document: Document): BlogBootstrap | null {
  const script = document.getElementById('blog-bootstrap');
  if (!(script instanceof HTMLScriptElement) || script.type !== 'application/json' || !script.textContent) return null;
  try {
    const value = JSON.parse(script.textContent) as Record<string, unknown>;
    const route = value?.route as Record<string, unknown> | undefined;
    if (value?.version !== 1 || typeof route?.slug !== 'string') return null;
    if (!isBlogPostDetail(value.post, route.slug, true)) return null;
    return value as unknown as BlogBootstrap;
  } catch {
    return null;
  }
}

/** Parse the server payload at most once for a document. */
export function readBlogBootstrap(document: Document = window.document): BlogBootstrap | null {
  const cache = cacheFor(document);
  if (!cache.parsed) {
    cache.value = parseBootstrap(document);
    cache.parsed = true;
  }
  if (cache.value && cache.invalidatedSlugs.has(cache.value.route.slug)) return null;
  return cache.value;
}

export function getBlogBootstrapPost(slug: string, document: Document = window.document): BlogPostDetail | null {
  const bootstrap = readBlogBootstrap(document);
  return bootstrap?.route.slug === slug ? bootstrap.post : null;
}

export function invalidateBlogBootstrap(slug: string, document: Document = window.document): void {
  const cache = cacheFor(document);
  cache.invalidatedSlugs.add(slug);
  if (cache.value?.route.slug === slug) {
    cache.value = null;
    document.getElementById('blog-bootstrap')?.remove();
  }
}

export async function prepareBlogBootstrap(
  document: Document,
  pathname: string,
  preload: () => Promise<unknown>,
): Promise<'ready' | 'preserve-ssr'> {
  const bootstrap = readBlogBootstrap(document);
  if (!bootstrap || pathname !== `/blog/${encodeURIComponent(bootstrap.route.slug)}`) return 'ready';
  try {
    await preload();
    return 'ready';
  } catch {
    // createRoot must not replace useful server HTML with an error/suspense
    // shell when the article chunk itself could not be downloaded.
    return 'preserve-ssr';
  }
}

/** Test isolation for the module-level, per-document parse cache. */
export function resetBlogBootstrapForTests(document: Document = window.document): void {
  caches.delete(document);
}
