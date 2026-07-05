import { api } from './base';

export type BlogCategory = 'paper-review' | 'engineering';

export const fetchBlogPosts = (
  tag?: string,
  category?: BlogCategory,
  page?: number,
  limit?: number,
) => api.get('/api/blog/posts', { params: { tag, category, page, limit } });

export const fetchBlogPost = (slug: string) =>
  api.get(`/api/blog/posts/${slug}`);

export const createBlogPost = (data: Record<string, unknown>) =>
  api.post('/api/blog/posts', data);

export const updateBlogPost = (id: string, data: Record<string, unknown>) =>
  api.put(`/api/blog/posts/${id}`, data);

export const deleteBlogPost = (id: string) =>
  api.delete(`/api/blog/posts/${id}`);

export const fetchBlogTags = () =>
  api.get('/api/blog/tags');
