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

export interface ReviewStatusResponse {
  session_id: string;
  status: string;
  progress?: string;
  report_available: boolean;
  error?: string;
}

export interface ReviewReportResponse {
  session_id: string;
  report_markdown: string;
  report_json?: any;
  num_papers: number;
  created_at: string;
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

export const updateBookmarkTopic = async (bookmarkId: string, topic: string) => {
  const response = await api.patch(`/api/bookmarks/${bookmarkId}/topic`, { topic });
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
  const response = await fetch(`${API_BASE_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, bookmark_ids: bookmarkIds }),
  });

  if (!response.ok) {
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

