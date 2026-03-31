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
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
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
  use_llm_search?: boolean;
}

export interface QueryAnalysis {
  intent: string;
  keywords: string[];
  improved_query: string;
  search_filters: Record<string, unknown>;
  confidence: number;
  original_query: string;
  analysis_details?: string;
}

export interface SearchResponse {
  results: Record<string, Paper[]>;
  total: number;
  query_analysis?: QueryAnalysis;
}

// LightRAG types
export interface LightRAGQueryRequest {
  query: string;
  mode: string;
  top_k: number;
  temperature: number;
}

export interface LightRAGEntity {
  name: string;
  type: string;
  description: string;
  relevance: number;
}

export interface LightRAGRelation {
  source: string;
  target: string;
  description: string;
  keywords: string[];
}

export interface LightRAGQueryResponse {
  answer: string;
  query: string;
  mode: string;
  keywords: { low_level: string[]; high_level: string[] };
  retrieval: {
    entities: LightRAGEntity[];
    relationships: LightRAGRelation[];
    paper_count: number;
  };
  source_papers: {
    title: string;
    authors: string[];
    published_date: string;
    url: string;
    source: string;
  }[];
  statistics: {
    entities_found: number;
    relationships_found: number;
    papers_found: number;
    chunks_found: number;
    kg_total_nodes: number;
    kg_total_edges: number;
  };
}

export interface KnowledgeGraphStats {
  status: string;
  stats?: {
    kg_nodes: number;
    kg_edges: number;
    entity_types: Record<string, number>;
    storage: {
      entities: number;
      relations: number;
      chunks: number;
    };
  };
  error?: string;
}

