import axios from 'axios';
import type { SearchRequest, SearchResponse, GraphData } from '../types';

// 같은 서버에서 서빙되므로 상대 경로 사용 (외부 접속 지원)
const API_BASE_URL = window.location.origin;

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

