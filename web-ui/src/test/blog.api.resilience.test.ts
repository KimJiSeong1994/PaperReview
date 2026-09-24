import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/base';
import { BLOG_DETAIL_TIMEOUT_MS, fetchBlogPost } from '../api/blog';

describe('blog detail API resilience', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('uses a dedicated bounded timeout without changing the shared search client', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: { slug: 'post' } } as never);
    const controller = new AbortController();
    await fetchBlogPost('post', { signal: controller.signal });
    expect(get).toHaveBeenCalledWith('/api/blog/posts/post', {
      signal: controller.signal,
      timeout: BLOG_DETAIL_TIMEOUT_MS,
    });
    expect(api.defaults.timeout).toBe(120_000);
  });

  it('retries one transient 503 and then succeeds', async () => {
    const get = vi.spyOn(api, 'get')
      .mockRejectedValueOnce({ response: { status: 503 } })
      .mockResolvedValueOnce({ data: { slug: 'post' } } as never);
    await expect(fetchBlogPost('post')).resolves.toMatchObject({ data: { slug: 'post' } });
    expect(get).toHaveBeenCalledTimes(2);
  });

  it.each([404, 410, 401])('does not retry definitive status %s', async (status) => {
    const error = { response: { status } };
    const get = vi.spyOn(api, 'get').mockRejectedValue(error);
    await expect(fetchBlogPost('post')).rejects.toBe(error);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it('does not retry a cancelled request', async () => {
    const error = { code: 'ERR_CANCELED' };
    const get = vi.spyOn(api, 'get').mockRejectedValue(error);
    await expect(fetchBlogPost('post')).rejects.toBe(error);
    expect(get).toHaveBeenCalledTimes(1);
  });
});
