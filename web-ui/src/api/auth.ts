import { api } from './base';

export interface AuthConfig {
  google_enabled: boolean;
  google_client_id: string | null;
  password_login_enabled: boolean;
  registration_enabled: boolean;
}

export interface GoogleChallenge {
  client_id: string;
  nonce: string;
}

export interface AuthSession {
  access_token: string;
  token_type: string;
  username: string;
  role: string;
  is_new_user?: boolean;
}

export const getAuthConfig = async (signal?: AbortSignal): Promise<AuthConfig> => {
  const response = await api.get<AuthConfig>('/api/auth/config', { baseURL: '', signal });
  return response.data;
};

export const createGoogleChallenge = async (
  credentials?: { username: string; password: string }, signal?: AbortSignal,
): Promise<GoogleChallenge> => {
  const response = await api.post<GoogleChallenge>(
    '/api/auth/google/challenge', credentials ?? {}, { baseURL: '', withCredentials: true, signal },
  );
  return response.data;
};

export const loginWithGoogle = async (credential: string, signal?: AbortSignal): Promise<AuthSession> => {
  const response = await api.post<AuthSession>(
    '/api/auth/google', { credential }, { baseURL: '', withCredentials: true, signal },
  );
  return response.data;
};

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

export const verifyToken = async (token?: string) => {
  const response = await api.get<{ valid: boolean; username: string; role: string }>(
    '/api/auth/verify',
    token ? { headers: { Authorization: `Bearer ${token}` } } : undefined,
  );
  return response.data;
};
