import axios from 'axios';
import type { SearchRequest, SearchResponse, GraphData, LightRAGQueryRequest, LightRAGQueryResponse, KnowledgeGraphStats } from '../types';

// 현재 호스트를 기반으로 API URL을 동적으로 설정 (내부 네트워크 접근 지원)
const getApiBaseUrl = () => {
  // 프로덕션 환경에서는 환경 변수 사용
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }

  // 프로덕션(HTTPS)에서는 같은 origin 사용 (Nginx가 /api를 프록시)
  if (window.location.protocol === 'https:') {
    return '';
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
  timeout: 120_000, // 120초 — 검색 작업의 전체 타임아웃
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

export const searchPapers = async (request: SearchRequest, signal?: AbortSignal): Promise<SearchResponse> => {
  const response = await api.post<SearchResponse>('/api/search', request, { signal });
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

// Code Repos API (GitHub)
export interface CodeRepo {
  url: string;
  stars: number;
  description: string;
  language: string;
  is_official: boolean;
  source?: string;
}

export const fetchPaperCodeRepos = async (
  title: string,
  opts?: { arxiv_id?: string | null; doi?: string | null; authors?: string[] },
): Promise<CodeRepo[]> => {
  const response = await api.post<{ repos: CodeRepo[] }>('/api/paper-code-repos', {
    title,
    arxiv_id: opts?.arxiv_id || undefined,
    doi: opts?.doi || undefined,
    authors: opts?.authors || undefined,
  });
  return response.data.repos || [];
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
  const response = await api.post<PosterResponse>(
    `/api/deep-review/visualize/${sessionId}`,
    {},
    { timeout: 300_000 },
  );
  return response.data;
};

export const generatePosterDirect = async (
  reportContent: string,
  numPapers: number,
): Promise<PosterResponse> => {
  const response = await api.post<PosterResponse>(
    '/api/deep-review/visualize-direct',
    { report_content: reportContent, num_papers: numPapers },
    { timeout: 300_000 },
  );
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

export const saveBookmarkFromPaper = async (request: {
  title: string;
  authors: string[];
  year?: number;
  venue?: string;
  doi?: string | null;
  arxiv_id?: string | null;
  context?: string;
  source_curriculum?: string;
  topic?: string;
  tags?: string[];
}) => {
  const response = await api.post('/api/bookmarks/from-paper', request);
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

// Per-Paper Review API
export interface PaperReviewStrength {
  point: string;
  evidence: string;
  significance: 'high' | 'medium' | 'low';
}

export interface PaperReviewWeakness {
  point: string;
  evidence: string;
  severity: 'major' | 'minor';
}

export interface MethodologyAssessment {
  rigor: number;
  novelty: number;
  reproducibility: number;
  commentary: string;
}

export interface PaperReview {
  summary: string;
  strengths: PaperReviewStrength[];
  weaknesses: PaperReviewWeakness[];
  methodology_assessment: MethodologyAssessment;
  key_contributions: string[];
  questions_for_authors: string[];
  overall_score: number;
  confidence: number;
  detailed_review_markdown: string;
  created_at: string;
  model: string;
  input_type: 'full_text' | 'abstract' | 'metadata';
}

export interface PaperReviewResponse {
  success: boolean;
  review: PaperReview;
  highlights: HighlightItem[];
  highlight_count: number;
}

export const startPaperReview = async (
  bookmarkId: string,
  paperIndex: number,
  fullText?: string,
  abstract?: string,
): Promise<PaperReviewResponse> => {
  const body: Record<string, unknown> = { review_mode: 'fast' };
  if (fullText) body.full_text = fullText;
  if (abstract) body.abstract = abstract;
  const response = await api.post<PaperReviewResponse>(
    `/api/bookmarks/${bookmarkId}/papers/${paperIndex}/review`,
    body,
    { timeout: 180_000 },
  );
  return response.data;
};

export const getPaperReview = async (
  bookmarkId: string,
  paperIndex: number,
): Promise<{ review: PaperReview; highlights: HighlightItem[] }> => {
  const response = await api.get(`/api/bookmarks/${bookmarkId}/papers/${paperIndex}/review`);
  return response.data;
};

export const deletePaperReview = async (
  bookmarkId: string,
  paperIndex: number,
): Promise<{ success: boolean }> => {
  const response = await api.delete(`/api/bookmarks/${bookmarkId}/papers/${paperIndex}/review`);
  return response.data;
};

export const autoHighlightPaperReview = async (
  bookmarkId: string,
  paperIndex: number,
): Promise<{ highlights: HighlightItem[]; added_count: number; enriched_count: number }> => {
  const response = await api.post(
    `/api/bookmarks/${bookmarkId}/papers/${paperIndex}/auto-highlight`,
    {},
    { timeout: 180_000 },
  );
  return response.data;
};

// PDF Overlay Highlights (standalone — no bookmark required)
export const generatePdfHighlights = async (
  text: string,
  title: string,
): Promise<{ highlights: HighlightItem[] }> => {
  const response = await api.post<{ highlights: HighlightItem[] }>(
    '/api/pdf-highlights',
    { text, title },
    { timeout: 300_000 },
  );
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

// Share API
export interface ShareInfo {
  token: string;
  share_url: string;
  created_at: string;
  expires_at: string;
}

export interface SharedBookmarkData {
  id: string;
  title: string;
  query: string;
  papers: any[];
  num_papers: number;
  report_markdown: string;
  created_at: string;
  tags: string[];
  topic: string;
  notes?: string;
  highlights?: HighlightItem[];
}

export const createShareLink = async (bookmarkId: string, expiresInDays?: number): Promise<ShareInfo> => {
  const body: Record<string, unknown> = {};
  if (expiresInDays !== undefined) body.expires_in_days = expiresInDays;
  const response = await api.post<ShareInfo>(`/api/bookmarks/${bookmarkId}/share`, body);
  return response.data;
};

export const revokeShareLink = async (bookmarkId: string) => {
  const response = await api.delete(`/api/bookmarks/${bookmarkId}/share`);
  return response.data;
};

export const getSharedBookmark = async (token: string): Promise<SharedBookmarkData> => {
  // Use raw axios to bypass auth interceptor — this is a public endpoint
  const response = await axios.get<SharedBookmarkData>(`${API_BASE_URL}/api/shared/${token}`);
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

// ── Curriculum API ────────────────────────────────────────────────────

export interface CurriculumListResponse {
  curricula: import('../components/curriculum/types').CurriculumSummary[];
}

export interface CurriculumProgressResponse {
  course_id: string;
  read_papers: string[];
  total_papers: number;
  progress_percent: number;
  updated_at: string | null;
}

export const fetchCurricula = async (): Promise<CurriculumListResponse> => {
  const response = await api.get<CurriculumListResponse>('/api/curricula');
  return response.data;
};

export const fetchCurriculumDetail = async (id: string): Promise<import('../components/curriculum/types').CurriculumCourse> => {
  const response = await api.get(`/api/curricula/${id}`);
  return response.data;
};

export const fetchCurriculumProgress = async (id: string): Promise<CurriculumProgressResponse> => {
  const response = await api.get<CurriculumProgressResponse>(`/api/curricula/${id}/progress`);
  return response.data;
};

export const updateCurriculumProgress = async (id: string, paperId: string, read: boolean) => {
  const response = await api.patch(`/api/curricula/${id}/progress`, { paper_id: paperId, read });
  return response.data;
};

export const generateCurriculum = async (topic: string, difficulty: string, numModules: number) => {
  const response = await api.post('/api/curricula/generate', { topic, difficulty, num_modules: numModules });
  return response.data;
};

export interface CurriculumGenerateProgress {
  step: number;
  step_name: string;
  progress: number;
  message: string;
  detail?: {
    modules?: string[];
    reference_courses?: { university: string; course_code: string; course_name: string }[];
  };
}

export const generateCurriculumStream = async (
  request: {
    topic: string;
    difficulty: string;
    num_modules: number;
    learning_goals?: string;
    paper_preference?: string;
  },
  onProgress: (progress: CurriculumGenerateProgress) => void,
  onComplete: (result: { course_id: string }) => void,
  onError: (error: string) => void,
  signal?: AbortSignal,
): Promise<void> => {
  const token = localStorage.getItem('access_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/curricula/generate-stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify(request),
      signal,
    });
  } catch (err) {
    // Network-level failure (server unreachable, DNS error, CORS block, etc.)
    if (signal?.aborted) return;
    onError(err instanceof TypeError ? `서버 연결 실패: ${err.message}` : String(err));
    return;
  }

  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('username');
      localStorage.removeItem('user_role');
      window.dispatchEvent(new Event('auth:logout'));
    }
    onError(`HTTP ${response.status}: ${response.statusText}`);
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) { onError('No response body'); return; }

  const decoder = new TextDecoder();
  let buffer = '';
  let completed = false;

  try {
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
            if (data.done && data.course_id) {
              completed = true;
              onComplete({ course_id: data.course_id });
              return;
            } else if (data.error) {
              completed = true;
              onError(data.error);
              return;
            } else if (data.step !== undefined) {
              onProgress(data);
            }
          } catch {
            // skip malformed
          }
        }
      }
    }
  } catch (err) {
    // Stream read error (connection dropped mid-stream)
    if (signal?.aborted) return;
    if (!completed) {
      onError(err instanceof TypeError
        ? '스트림이 중단되었습니다. 다시 시도해주세요.'
        : `Stream error: ${err}`);
    }
    return;
  } finally {
    reader.releaseLock();
  }

  // Stream ended without completion event
  if (!completed) {
    onError('Stream ended unexpectedly. Please try again.');
  }
};

export const forkCurriculum = async (courseId: string): Promise<{ success: boolean; course_id: string; forked_from: string }> => {
  const response = await api.post(`/api/curricula/${courseId}/fork`);
  return response.data;
};

export const deleteCurriculum = async (courseId: string): Promise<{ success: boolean; deleted: string }> => {
  const response = await api.delete(`/api/curricula/${courseId}`);
  return response.data;
};

// ── Curriculum Sharing ────────────────────────────────────────────────

export interface CurriculumShareInfo {
  token: string;
  share_url: string;
  created_at: string;
  expires_at: string;
}

export const createCurriculumShareLink = async (
  courseId: string,
  expiresInDays: number = 30,
): Promise<CurriculumShareInfo> => {
  const response = await api.post(`/api/curricula/${courseId}/share`, { expires_in_days: expiresInDays });
  return response.data;
};

export const revokeCurriculumShareLink = async (courseId: string): Promise<{ success: boolean }> => {
  const response = await api.delete(`/api/curricula/${courseId}/share`);
  return response.data;
};

export interface SharedCurriculumData {
  summary: {
    id: string;
    name: string;
    university: string;
    instructor: string;
    difficulty: string;
    prerequisites: string[];
    description: string;
    total_papers: number;
    total_modules: number;
  };
  course: {
    modules: {
      id: string;
      week: number;
      title: string;
      description: string;
      topics: {
        id: string;
        title: string;
        papers: {
          id: string;
          title: string;
          authors: string[];
          year: number;
          venue: string;
          arxiv_id?: string | null;
          doi?: string | null;
          category: string;
          context: string;
        }[];
      }[];
    }[];
    reference_courses?: { university: string; course_code: string; course_name: string; url?: string }[];
  };
}

export const getSharedCurriculum = async (token: string): Promise<SharedCurriculumData> => {
  const response = await axios.get<SharedCurriculumData>(`${API_BASE_URL}/api/shared/curriculum/${token}`);
  return response.data;
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

// Admin Curricula
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

export const getAdminCurricula = async (): Promise<AdminCurriculaResponse> => {
  const response = await api.get<AdminCurriculaResponse>('/api/admin/curricula');
  return response.data;
};

// ── Math Formula Explanation API ───────────────────────────────────────

export interface MathExplanation {
  explanation: string;
  variables: { symbol: string; meaning: string }[];
  formula_type: string;
}

export const explainMathFormula = async (
  formulaText: string,
  context: string,
  paperTitle: string,
): Promise<MathExplanation> => {
  const response = await api.post<MathExplanation>(
    '/api/math-explain',
    { formula_text: formulaText, context, paper_title: paperTitle },
    { timeout: 60_000 },
  );
  return response.data;
};

// ── PDF API ───────────────────────────────────────────────────────────

export async function resolvePdfUrl(title: string, doi?: string, arxivId?: string): Promise<{pdf_url: string | null; source: string | null}> {
  const params: Record<string, string> = { title };
  if (doi) params.doi = doi;
  if (arxivId) params.arxiv_id = arxivId;
  const { data } = await api.get('/api/pdf/resolve', { params });
  return data;
}

export async function batchResolvePdfUrls(
  papers: { title: string; doi?: string; arxiv_id?: string }[],
): Promise<{ results: { pdf_url: string | null; source: string | null }[] }> {
  const { data } = await api.post('/api/pdf/resolve-batch', { papers });
  return data;
}

// Semantic Scholar Reader
export async function getS2ReaderUrl(
  title: string,
  doi?: string,
  arxivId?: string,
): Promise<{ reader_url: string | null; paper_id: string | null; pdf_url: string | null }> {
  const params: Record<string, string> = { title };
  if (doi) params.doi = doi;
  if (arxivId) params.arxiv_id = arxivId;
  const { data } = await api.get('/api/s2/reader-url', { params });
  return data;
}

// ── Blog API ──────────────────────────────────────────────────────────

export const fetchBlogPosts = (tag?: string, page?: number) =>
  api.get('/api/blog/posts', { params: { tag, page } });

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
