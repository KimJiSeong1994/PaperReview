import axios from 'axios';
import { api, API_BASE_URL } from './base';

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

// Curriculum Sharing
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
