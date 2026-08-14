import { api } from './base';

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
export type PosterStatus =
  | 'succeeded'
  | 'degraded'
  | 'failed'
  | 'timeout'
  | 'active'
  | 'rate_limited'
  | 'poster_session_unavailable'
  | 'unknown';

export interface PosterManifest {
  version?: string;
  status?: PosterStatus | string;
  poster_status?: PosterStatus | string;
  error_code?: string;
  generation_id?: string;
  reason?: string;
  retryable?: boolean;
  warnings?: string[];
  [key: string]: unknown;
}

export interface PosterResponse {
  success: boolean;
  session_id: string;
  error_code?: string;
  generation_id?: string;
  poster_html?: string;
  poster_path?: string;
  status?: PosterStatus | string;
  poster_status?: PosterStatus | string;
  reason?: string;
  retryable?: boolean;
  error?: string;
  warnings?: string[];
  manifest?: PosterManifest;
  poster_manifest?: PosterManifest;
}

export const generatePoster = async (sessionId: string): Promise<PosterResponse> => {
  const response = await api.post<PosterResponse>(
    `/api/deep-review/visualize/${sessionId}`,
    {},
    { timeout: 300_000 },
  );
  return response.data;
};

export interface ClassifiedPosterResponse {
  status: PosterStatus;
  posterHtml: string;
  posterPath: string;
  warning: string;
  canPreview: boolean;
  isCompleteAnalytics: boolean;
  canUseDirectFallback: boolean;
  error: string;
  errorCode: string;
  generationId: string;
  retryable: boolean | null;
  raw: PosterResponse;
}

export const normalizePosterCode = (code: unknown): string => (
  typeof code === 'string'
    ? code.trim().toLowerCase().replace(/[-\s]+/g, '_')
    : ''
);

export const normalizePosterStatus = (status: unknown): PosterStatus => {
  const normalized = normalizePosterCode(status);
  if (normalized === 'success' || normalized === 'completed' || normalized === 'complete') {
    return 'succeeded';
  }
  if (normalized === 'rate' || normalized === 'rate_limit' || normalized === 'rate_limited') {
    return 'rate_limited';
  }
  if (normalized === 'poster_timeout' || normalized === 'poster_generation_timeout') {
    return 'timeout';
  }
  if (normalized === 'poster_active' || normalized === 'poster_generation_active') {
    return 'active';
  }
  if (normalized === 'poster_rate_limited' || normalized === 'poster_generation_rate_limited') {
    return 'rate_limited';
  }
  if (
    normalized === 'succeeded' ||
    normalized === 'degraded' ||
    normalized === 'failed' ||
    normalized === 'timeout' ||
    normalized === 'active' ||
    normalized === 'poster_session_unavailable'
  ) {
    return normalized;
  }
  return 'unknown';
};

export const classifyPosterResponse = (response: PosterResponse): ClassifiedPosterResponse => {
  const errorCode = normalizePosterCode(
    response.error_code
      ?? response.poster_manifest?.error_code
      ?? response.manifest?.error_code,
  );
  const status = normalizePosterStatus(
    response.poster_status
      ?? response.status
      ?? response.poster_manifest?.status
      ?? response.poster_manifest?.poster_status
      ?? response.manifest?.status
      ?? response.manifest?.poster_status
      ?? (errorCode || undefined)
      ?? (response.success && response.poster_html ? 'succeeded' : undefined),
  );
  const warnings = [
    ...(response.warnings ?? []),
    ...(response.poster_manifest?.warnings ?? []),
    ...(response.manifest?.warnings ?? []),
  ].filter(Boolean);
  const reason = response.reason
    ?? response.poster_manifest?.reason
    ?? response.manifest?.reason
    ?? response.error
    ?? '';
  const posterHtml = response.poster_html ?? '';

  return {
    status,
    posterHtml,
    posterPath: response.poster_path ?? '',
    warning: warnings[0] ?? reason,
    canPreview: Boolean(posterHtml) && (status === 'succeeded' || status === 'degraded'),
    isCompleteAnalytics: status === 'succeeded',
    canUseDirectFallback: errorCode === 'poster_session_unavailable',
    error: reason,
    errorCode,
    generationId: response.generation_id
      ?? response.poster_manifest?.generation_id
      ?? response.manifest?.generation_id
      ?? '',
    retryable: response.retryable
      ?? response.poster_manifest?.retryable
      ?? response.manifest?.retryable
      ?? null,
    raw: response,
  };
};

type PosterErrorBody = {
  code?: unknown;
  detail?: unknown;
  error_code?: unknown;
  generation_id?: unknown;
  message?: unknown;
  poster_status?: unknown;
  reason?: unknown;
  retryable?: unknown;
  status?: unknown;
};

type PosterHttpError = {
  message?: unknown;
  response?: {
    status?: number;
    data?: PosterErrorBody;
  };
};

const isPosterHttpError = (error: unknown): error is PosterHttpError => (
  typeof error === 'object' && error !== null
);

const isPosterErrorBody = (value: unknown): value is PosterErrorBody => (
  typeof value === 'object' && value !== null
);

const stringMessage = (value: unknown): string => (
  typeof value === 'string' ? value : ''
);

export const classifyPosterError = (error: unknown): Pick<
  ClassifiedPosterResponse,
  'status' | 'canUseDirectFallback' | 'error' | 'errorCode' | 'generationId' | 'retryable'
> => {
  const httpError = isPosterHttpError(error) ? error : {};
  const data = httpError.response?.data;
  const detail = data?.detail;
  const detailBody = isPosterErrorBody(detail) ? detail : undefined;
  const errorCode = normalizePosterCode(
    detailBody?.error_code
      ?? data?.error_code
      ?? detailBody?.code
      ?? data?.code,
  );
  const status = normalizePosterStatus(
    detailBody?.poster_status
      ?? data?.poster_status
      ?? data?.status
      ?? detailBody?.status
      ?? errorCode,
  );
  const message = typeof detail === 'string'
    ? detail
    : stringMessage(detailBody?.message)
      || stringMessage(data?.message)
      || stringMessage(data?.reason)
      || stringMessage(httpError.message);

  return {
    status,
    canUseDirectFallback: errorCode === 'poster_session_unavailable',
    error: message,
    errorCode,
    generationId: stringMessage(detailBody?.generation_id) || stringMessage(data?.generation_id),
    retryable: typeof detailBody?.retryable === 'boolean'
      ? detailBody.retryable
      : typeof data?.retryable === 'boolean'
        ? data.retryable
        : null,
  };
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
