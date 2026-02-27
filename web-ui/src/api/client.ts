import axios from 'axios';
import type { SearchRequest, SearchResponse, GraphData, LightRAGQueryRequest, LightRAGQueryResponse, KnowledgeGraphStats } from '../types';

// 현재 호스트를 기반으로 API URL을 동적으로 설정 (내부 네트워크 접근 지원)
const getApiBaseUrl = () => {
  // 프로덕션 환경에서는 환경 변수 사용
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  
  // 개발 환경에서는 현재 호스트의 8000 포트 사용
  const hostname = window.location.hostname;
  return `http://${hostname}:8000`;
};

const API_BASE_URL = getApiBaseUrl();

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Attach JWT token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// On 401 response, clear stored token and notify App to show login modal
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !error.config?.url?.includes('/api/auth/')) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('username');
      localStorage.removeItem('user_role');
      window.dispatchEvent(new Event('auth:logout'));
    }
    return Promise.reject(error);
  },
);

// ── Auth API ─────────────────────────────────────────────────────────

export const login = async (username: string, password: string) => {
  const response = await api.post<{ access_token: string; token_type: string; username: string; role: string }>(
    '/api/auth/login',
    { username, password },
  );
  return response.data;
};

export const register = async (username: string, password: string) => {
  const response = await api.post<{ message: string; username: string }>(
    '/api/auth/register',
    { username, password },
  );
  return response.data;
};

export const verifyToken = async (token: string) => {
  const response = await api.get<{ valid: boolean; username: string; role: string }>(
    '/api/auth/verify',
    { params: { token } },
  );
  return response.data;
};

export const searchPapers = async (request: SearchRequest): Promise<SearchResponse> => {
  const response = await api.post<SearchResponse>('/api/search', request);
  return response.data;
};

export const savePapers = async (results: Record<string, any[]>, query: string) => {
  const response = await api.post('/api/save', { results, query });
  return response.data;
};

export const getPapersCount = async (): Promise<number> => {
  const response = await api.get<{ count: number }>('/api/papers/count');
  return response.data.count;
};

export const getGraphData = async (papers: string): Promise<GraphData> => {
  const response = await api.post<GraphData>('/api/graph-data', { papers_json: papers });
  return response.data;
};

// Paper References API
export interface PaperReference {
  title: string;
  authors: string[];
  year: string;
  citations: number;
  abstract: string;
  url: string;
  source: string;
  paper_id: string;
  parent_paper_title?: string;
}

export const fetchPaperReferences = async (paper: {
  title: string;
  doi?: string;
  arxiv_id?: string;
}): Promise<{ references: PaperReference[] }> => {
  const response = await api.post<{ references: PaperReference[] }>('/api/paper-references', {
    title: paper.title,
    doi: paper.doi,
    arxiv_id: paper.arxiv_id,
    max_references: 10,
  });
  return response.data;
};

export const fetchBatchReferences = async (papers: {
  title: string;
  doi?: string;
  arxiv_id?: string;
}[]): Promise<{ references: PaperReference[] }> => {
  const response = await api.post<{ references: PaperReference[] }>('/api/batch-references', {
    papers,
    max_references: 5,
  });
  return response.data;
};

// Deep Review API
export interface DeepReviewRequest {
  paper_ids: string[];
  papers?: any[];  // 선택한 논문의 전체 데이터 (ID 매칭 문제 해결)
  num_researchers?: number;
  model?: string;
}

export interface DeepReviewResponse {
  success: boolean;
  session_id: string;
  status: string;
  message: string;
  status_url: string;
}

export interface VerificationStats {
  total_claims: number;
  verifiable_claims: number;
  verified: number;
  partially_verified: number;
  unverified: number;
  contradicted: number;
  verification_rate: number;
}

export interface ReviewStatusResponse {
  session_id: string;
  status: string;
  progress?: string;
  report_available: boolean;
  error?: string;
  verification_stats?: VerificationStats;
}

export interface ReviewReportResponse {
  session_id: string;
  report_markdown: string;
  report_json?: any;
  num_papers: number;
  created_at: string;
  verification_stats?: VerificationStats;
}

export const startDeepReview = async (request: DeepReviewRequest): Promise<DeepReviewResponse> => {
  const response = await api.post<DeepReviewResponse>('/api/deep-review', request);
  return response.data;
};

export const getReviewStatus = async (sessionId: string): Promise<ReviewStatusResponse> => {
  const response = await api.get<ReviewStatusResponse>(`/api/deep-review/status/${sessionId}`);
  return response.data;
};

export const getReviewReport = async (sessionId: string): Promise<ReviewReportResponse> => {
  const response = await api.get<ReviewReportResponse>(`/api/deep-review/report/${sessionId}`);
  return response.data;
};

// Poster Visualization API
export interface PosterResponse {
  success: boolean;
  session_id: string;
  poster_html: string;
  poster_path: string;
}

export const generatePoster = async (sessionId: string): Promise<PosterResponse> => {
  const response = await api.post<PosterResponse>(`/api/deep-review/visualize/${sessionId}`);
  return response.data;
};

// LightRAG API
export const queryLightRAG = async (request: LightRAGQueryRequest): Promise<LightRAGQueryResponse> => {
  const response = await api.post<LightRAGQueryResponse>('/api/light-rag/query', request);
  return response.data;
};

export const buildLightRAG = async (maxConcurrent: number = 4, extractionModel: string = 'gpt-4o-mini') => {
  const response = await api.post('/api/light-rag/build', {
    max_concurrent: maxConcurrent,
    extraction_model: extractionModel,
  });
  return response.data;
};

export const getLightRAGStatus = async (): Promise<KnowledgeGraphStats> => {
  const response = await api.get<KnowledgeGraphStats>('/api/light-rag/status');
  return response.data;
};

// Bookmarks API
export const saveBookmark = async (request: {
  session_id: string;
  title: string;
  query: string;
  papers: any[];
  report_markdown: string;
  tags?: string[];
  topic?: string;
}) => {
  const response = await api.post('/api/bookmarks', request);
  return response.data;
};

export const getBookmarks = async () => {
  const response = await api.get('/api/bookmarks');
  return response.data;
};

export const getBookmarkDetail = async (bookmarkId: string) => {
  const response = await api.get(`/api/bookmarks/${bookmarkId}`);
  return response.data;
};

export const deleteBookmark = async (bookmarkId: string) => {
  const response = await api.delete(`/api/bookmarks/${bookmarkId}`);
  return response.data;
};

export const updateBookmarkTitle = async (bookmarkId: string, title: string) => {
  const response = await api.patch(`/api/bookmarks/${bookmarkId}/title`, { title });
  return response.data;
};

export const updateBookmarkTopic = async (bookmarkId: string, topic: string) => {
  const response = await api.patch(`/api/bookmarks/${bookmarkId}/topic`, { topic });
  return response.data;
};

// Notes & Highlights
export interface HighlightItem {
  id: string;
  text: string;
  color: string;
  memo: string;
  created_at: string;
  category?: string;
  significance?: number;
  section?: string;
  implication?: string;
  strength_or_weakness?: 'strength' | 'weakness';
  question_for_authors?: string;
  confidence_level?: number;
}

export const updateBookmarkNotes = async (
  bookmarkId: string,
  notes?: string,
  highlights?: HighlightItem[],
) => {
  const body: Record<string, unknown> = {};
  if (notes !== undefined) body.notes = notes;
  if (highlights !== undefined) body.highlights = highlights;
  const response = await api.patch(`/api/bookmarks/${bookmarkId}/notes`, body);
  return response.data;
};

// Auto Highlight (LLM-based)
export const autoHighlightBookmark = async (bookmarkId: string): Promise<{ highlights: HighlightItem[] }> => {
  const response = await api.post<{ highlights: HighlightItem[] }>(`/api/bookmarks/${bookmarkId}/auto-highlight`);
  return response.data;
};

// Citation Tree
export const generateCitationTree = async (bookmarkId: string, depth: number = 1, maxPerDirection: number = 10) => {
  const response = await api.post(`/api/bookmarks/${bookmarkId}/citation-tree`, { depth, max_per_direction: maxPerDirection });
  return response.data;
};

export const getCitationTree = async (bookmarkId: string) => {
  const response = await api.get(`/api/bookmarks/${bookmarkId}/citation-tree`);
  return response.data;
};

export const deleteCitationTree = async (bookmarkId: string) => {
  const response = await api.delete(`/api/bookmarks/${bookmarkId}/citation-tree`);
  return response.data;
};

// Bulk bookmark operations
export const bulkDeleteBookmarks = async (bookmarkIds: string[]) => {
  const response = await api.post('/api/bookmarks/bulk-delete', { bookmark_ids: bookmarkIds });
  return response.data;
};

export const bulkMoveBookmarks = async (bookmarkIds: string[], topic: string) => {
  const response = await api.post('/api/bookmarks/bulk-move', { bookmark_ids: bookmarkIds, topic });
  return response.data;
};

// Chat API (SSE streaming)
export interface ChatSource {
  ref: number;
  id: string;
  title: string;
  num_papers: number;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  sources?: ChatSource[];
}

export const chatWithBookmarks = async (
  messages: ChatMessage[],
  bookmarkIds: string[],
  onChunk: (content: string) => void,
  onSources: (sources: ChatSource[]) => void,
  onDone: () => void,
  onError: (error: string) => void,
): Promise<void> => {
  const token = localStorage.getItem('access_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}/api/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ messages, bookmark_ids: bookmarkIds }),
  });

  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('username');
    }
    onError(`HTTP ${response.status}: ${response.statusText}`);
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    onError('No response body');
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6));
          if (data.content) {
            onChunk(data.content);
          } else if (data.sources) {
            onSources(data.sources);
          } else if (data.done) {
            onDone();
            return;
          } else if (data.error) {
            onError(data.error);
            return;
          }
        } catch {
          // skip malformed lines
        }
      }
    }
  }
  onDone();
};

// ── Admin API ─────────────────────────────────────────────────────────

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

export interface AdminPaperUserStats {
  total: number;
  users: { username: string; paper_count: number }[];
}

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
