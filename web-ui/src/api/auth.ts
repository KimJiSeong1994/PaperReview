import { api } from './base';

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
