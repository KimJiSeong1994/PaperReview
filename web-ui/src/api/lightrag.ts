import type { LightRAGQueryRequest, LightRAGQueryResponse, KnowledgeGraphStats } from '../types';
import { api } from './base';

export const queryLightRAG = async (request: LightRAGQueryRequest): Promise<LightRAGQueryResponse> => {
  const response = await api.post<LightRAGQueryResponse>('/api/light-rag/query', request);
  return response.data;
};

export const buildLightRAG = async (maxConcurrent: number = 4, extractionModel: string = 'gpt-4o-mini') => {
  const response = await api.post('/api/light-rag/build', {
    max_concurrent: maxConcurrent,
    extraction_model: extractionModel,
  });
  return response.data;
};

export const getLightRAGStatus = async (): Promise<KnowledgeGraphStats> => {
  const response = await api.get<KnowledgeGraphStats>('/api/light-rag/status');
  return response.data;
};
