import { api } from './base';

// Deep Review API
export interface DeepReviewRequest {
  paper_ids: string[];
  papers?: Record<string, unknown>[];  // 선택한 논문의 전체 데이터 (ID 매칭 문제 해결)
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