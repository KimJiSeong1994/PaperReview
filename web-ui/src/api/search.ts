import type { SearchRequest, SearchResponse, GraphData } from '../types';
import { api, API_BASE_URL } from './base';

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

// Deep Search SSE Streaming
export interface DeepSearchStreamEvent {
  event: 'turn_start' | 'query_analysis' | 'papers_found' | 'gap_analysis' | 'evaluation' | 'complete' | 'error';
  data: Record<string, unknown>;
}

export interface DeepSearchStreamCallbacks {
  onTurnStart?: (data: { turn: number; phase: string; max_turns?: number; difficulty?: string }) => void;
  onQueryAnalysis?: (data: { intent: string; keywords: string[]; confidence?: number }) => void;
  onPapersFound?: (data: { count: number; turns_used: number }) => void;
  onGapAnalysis?: (data: { missing: string[] }) => void;
  onEvaluation?: (data: { overall_score: number; dimensions: Record<string, number> }) => void;
  onComplete?: (data: { papers: any[]; total: number; search_time: number; evaluation: any; metadata: any }) => void;
  onError?: (error: string) => void;
}

export const deepSearchStream = async (
  request: { query: string; max_results?: number; context?: string; save_papers?: boolean },
  callbacks: DeepSearchStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> => {
  const token = localStorage.getItem('access_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/deep-search-stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify(request),
      signal,
    });
  } catch (err) {
    if (signal?.aborted) return;
    callbacks.onError?.(err instanceof TypeError ? `Server connection failed: ${(err as TypeError).message}` : String(err));
    return;
  }

  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('username');
      localStorage.removeItem('user_role');
      window.dispatchEvent(new Event('auth:logout'));
    }
    callbacks.onError?.(`HTTP ${response.status}: ${response.statusText}`);
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    callbacks.onError?.('No response body');
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ') && currentEvent) {
          try {
            const data = JSON.parse(line.slice(6));
            switch (currentEvent) {
              case 'turn_start':
                callbacks.onTurnStart?.(data);
                break;
              case 'query_analysis':
                callbacks.onQueryAnalysis?.(data);
                break;
              case 'papers_found':
                callbacks.onPapersFound?.(data);
                break;
              case 'gap_analysis':
                callbacks.onGapAnalysis?.(data);
                break;
              case 'evaluation':
                callbacks.onEvaluation?.(data);
                break;
              case 'complete':
                callbacks.onComplete?.(data);
                return;
              case 'error':
                callbacks.onError?.(data.message || 'Unknown error');
                return;
            }
          } catch {
            // skip malformed JSON
          }
          currentEvent = '';
        } else if (line.trim() === '') {
          currentEvent = '';
        }
      }
    }
  } catch (err) {
    if (signal?.aborted) return;
    callbacks.onError?.(err instanceof TypeError
      ? 'Stream interrupted. Please try again.'
      : `Stream error: ${err}`);
  } finally {
    reader.releaseLock();
  }
};
