import { api } from './base';
import type { Soul } from '../types';

export const SOUL_PROFILE_MAX = 2000;

export const fetchSoul = async (signal?: AbortSignal): Promise<Soul> => {
  const response = await api.get<Soul>('/api/me/soul', { signal });
  return response.data;
};

export const saveSoulProfile = async (userMd: string): Promise<{ user_md: string }> => {
  const response = await api.put<{ user_md: string }>('/api/me/soul', { user_md: userMd });
  return response.data;
};

export const deleteSoulMemory = async (id: string): Promise<{ ok: boolean }> => {
  const response = await api.delete<{ ok: boolean }>(`/api/me/soul/memories/${encodeURIComponent(id)}`);
  return response.data;
};

export const clearSoul = async (): Promise<{ deleted: number }> => {
  const response = await api.delete<{ deleted: number }>('/api/me/soul');
  return response.data;
};
