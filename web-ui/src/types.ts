export interface Paper {
  doc_id: string;
  title: string;
  authors: string[];
  year?: string | number;
  journal?: string;
  abstract?: string;
  url?: string;
  pdf_url?: string;
  doi?: string;
  citations?: number;
  source?: string;
  [key: string]: any;
}

export interface GraphNode {
  id: string;
  x: number;
  y: number;
  title: string;
  year?: string | number;
  citations?: number;
  authors?: string[];
  weight?: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  weight?: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface SearchRequest {
  query: string;
  max_results?: number;
  sources?: string[];
  sort_by?: string;
  year_start?: number;
  year_end?: number;
  author?: string;
  category?: string;
}

export interface QueryAnalysis {
  intent: string;
  keywords: string[];
  improved_query: string;
  search_filters: Record<string, any>;
  confidence: number;
  original_query: string;
  analysis_details?: string;
}

export interface SearchResponse {
  results: Record<string, Paper[]>;
  total: number;
  query_analysis?: QueryAnalysis;
}

