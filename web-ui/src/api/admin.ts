import { api } from './base';

export interface AdminDashboard {
  total_users: number;
  total_papers: number;
  total_bookmarks: number;
  total_sessions: number;
  kg_nodes: number;
  kg_edges: number;
  papers_by_source: { source: string; count: number }[];
  papers_by_year: { year: string; count: number }[];
  top_queries: { query: string; count: number }[];
  top_categories: { category: string; count: number }[];
  recent_papers: { title: string; source: string; collected_at: string }[];
}

export interface AdminUser {
  username: string;
  role: string;
  created_at: string;
  bookmark_count: number;
}

export interface AdminPaper {
  index: number;
  title: string;
  authors: string[];
  source: string;
  published_date: string;
  search_query: string;
  searched_by: string;
}

export interface AdminPapersResponse {
  papers: AdminPaper[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  usernames: string[];
}

export interface AdminBookmarkPaper {
  title: string;
  authors: string[];
}

export interface AdminBookmark {
  id: string;
  title: string;
  username: string;
  query: string;
  topic: string;
  num_papers: number;
  papers: AdminBookmarkPaper[];
  created_at: string;
}

export interface AdminPaperUserStats {
  total: number;
  users: { username: string; paper_count: number }[];
}

export interface AdminCurriculumItem {
  id: string;
  name: string;
  difficulty: string;
  total_papers: number;
  total_modules: number;
  is_preset: boolean;
  forked_from: string | null;
  type: 'fork' | 'custom';
}

export interface AdminCurriculumUser {
  username: string;
  curricula: AdminCurriculumItem[];
  total_curricula: number;
  fork_count: number;
  custom_count: number;
  total_read_papers: number;
  courses_with_progress: number;
}

export interface AdminCurriculaResponse {
  total_user_curricula: number;
  total_users_with_curricula: number;
  users: AdminCurriculumUser[];
}

export const getAdminDashboard = async (): Promise<AdminDashboard> => {
  const response = await api.get<AdminDashboard>('/api/admin/dashboard');
  return response.data;
};

export const getAdminUsers = async (): Promise<{ users: AdminUser[] }> => {
  const response = await api.get<{ users: AdminUser[] }>('/api/admin/users');
  return response.data;
};

export const updateUserRole = async (username: string, role: string) => {
  const response = await api.patch(`/api/admin/users/${username}/role`, { role });
  return response.data;
};

export const deleteUser = async (username: string) => {
  const response = await api.delete(`/api/admin/users/${username}`);
  return response.data;
};

export const getAdminPaperStats = async (): Promise<AdminPaperUserStats> => {
  const response = await api.get<AdminPaperUserStats>('/api/admin/papers/stats');
  return response.data;
};

export const getAdminPapers = async (page: number = 1, pageSize: number = 50, username?: string): Promise<AdminPapersResponse> => {
  const response = await api.get<AdminPapersResponse>('/api/admin/papers', {
    params: { page, page_size: pageSize, ...(username ? { username } : {}) },
  });
  return response.data;
};

export const deleteAdminPapers = async (indices: number[]) => {
  const response = await api.delete('/api/admin/papers', { data: { indices } });
  return response.data;
};

export const getAdminBookmarks = async (username?: string): Promise<{ bookmarks: AdminBookmark[] }> => {
  const response = await api.get<{ bookmarks: AdminBookmark[] }>('/api/admin/bookmarks', {
    params: username ? { username } : {},
  });
  return response.data;
};

export const deleteAdminBookmark = async (bookmarkId: string) => {
  const response = await api.delete(`/api/admin/bookmarks/${bookmarkId}`);
  return response.data;
};

export const getAdminCurricula = async (): Promise<AdminCurriculaResponse> => {
  const response = await api.get<AdminCurriculaResponse>('/api/admin/curricula');
  return response.data;
};
