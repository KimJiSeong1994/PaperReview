import axios from 'axios';

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

export const API_BASE_URL = getApiBaseUrl();

export const api = axios.create({
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

// ── Shared types used across multiple domains ─────────────────────────

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
