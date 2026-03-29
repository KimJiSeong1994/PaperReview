import { api } from './base';

export const generateCitationTree = async (bookmarkId: string, depth: number = 1, maxPerDirection: number = 10) => {
  const response = await api.post(`/api/bookmarks/${bookmarkId}/citation-tree`, { depth, max_per_direction: maxPerDirection });
  return response.data;
};

export const getCitationTree = async (bookmarkId: string) => {
  const response = await api.get(`/api/bookmarks/${bookmarkId}/citation-tree`);
  return response.data;
};

export const deleteCitationTree = async (bookmarkId: string) => {
  const response = await api.delete(`/api/bookmarks/${bookmarkId}/citation-tree`);
  return response.data;
};
