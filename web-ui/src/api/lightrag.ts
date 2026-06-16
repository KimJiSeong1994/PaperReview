import type { LightRAGQueryRequest, LightRAGQueryResponse, KnowledgeGraphStats } from '../types';
import { api } from './base';

export const queryLightRAG = async (request: LightRAGQueryRequest): Promise<LightRAGQueryResponse> => {
  const response = await api.post<LightRAGQueryResponse>('/api/light-rag/query', request);
  return response.data;
};

export const buildLightRAG = async (maxConcurrent: number = 4, extractionModel?: string) => {
  const payload: { max_concurrent: number; extraction_model?: string } = {
    max_concurrent: maxConcurrent,
  };
  if (extractionModel) {
    payload.extraction_model = extractionModel;
  }
  const response = await api.post('/api/light-rag/build', payload);
  return response.data;
};

export const getLightRAGStatus = async (): Promise<KnowledgeGraphStats> => {
  const response = await api.get<KnowledgeGraphStats>('/api/light-rag/status');
  return response.data;
};
