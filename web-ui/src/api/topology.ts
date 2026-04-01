import type { GraphData, TopologyAnalysis, TemporalAnalysis } from '../types';
import { api } from './base';

export const analyzeTopology = async (graphData: GraphData): Promise<TopologyAnalysis> => {
  const response = await api.post<TopologyAnalysis>('/api/topology/analyze', {
    graph_data: { nodes: graphData.nodes, edges: graphData.edges },
  });
  return response.data;
};

export const analyzeTemporalCommunities = async (graphData: GraphData): Promise<TemporalAnalysis> => {
  const response = await api.post<TemporalAnalysis>('/api/topology/temporal', {
    graph_data: { nodes: graphData.nodes, edges: graphData.edges },
  });
  return response.data;
};
