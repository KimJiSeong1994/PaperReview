import { api } from './base';

export const BLOG_DETAIL_TIMEOUT_MS = 8_000;

interface BlogDetailRequestOptions {
  signal?: AbortSignal;
}

function isCancelled(error: unknown, signal?: AbortSignal): boolean {
  const code = (error as { code?: string })?.code;
  return signal?.aborted === true || code === 'ERR_CANCELED' || code === 'CanceledError';
}

function isTransientBlogError(error: unknown): boolean {
  const candidate = error as { code?: string; response?: { status?: number } };
  if (!candidate.response) return true;
  return [500, 502, 503, 504].includes(candidate.response.status ?? 0);
}

export type BlogCategory = 'paper-review' | 'engineering';

export const fetchBlogPosts = (
  tag?: string,
  category?: BlogCategory,
  page?: number,
  limit?: number,
  /** Full-text query: tokens are ANDed over title/tags/excerpt/body server-side. */
  q?: string,
) => api.get('/api/blog/posts', { params: { tag, category, page, limit, q } });

export const fetchBlogPost = async (slug: string, options: BlogDetailRequestOptions = {}) => {
  const request = () => api.get(`/api/blog/posts/${slug}`, {
    signal: options.signal,
    timeout: BLOG_DETAIL_TIMEOUT_MS,
  });
  try {
    return await request();
  } catch (error) {
    if (isCancelled(error, options.signal) || !isTransientBlogError(error)) throw error;
    return request();
  }
};

export const createBlogPost = (data: Record<string, unknown>) =>
  api.post('/api/blog/posts', data);

export const updateBlogPost = (id: string, data: Record<string, unknown>) =>
  api.put(`/api/blog/posts/${id}`, data);

export const deleteBlogPost = (id: string) =>
  api.delete(`/api/blog/posts/${id}`);

/** Paginated tag index. Zero-arg keeps the server defaults (page 1, 60, by name). */
export const fetchBlogTags = (
  page?: number,
  limit?: number,
  sort?: 'name' | 'count',
) => api.get('/api/blog/tags', { params: { page, limit, sort } });
