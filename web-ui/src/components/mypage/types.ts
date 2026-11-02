import type { HighlightItem } from '../../api/client';

export interface Bookmark {
  id: string;
  title: string;
  session_id: string;
  query: string;
  num_papers: number;
  created_at: string;
  tags: string[];
  topic: string;
  has_notes?: boolean;
  has_citation_tree?: boolean;
  has_share?: boolean;
}

// ── Citation Tree types ──────────────────────────────────────────────

export interface CitationNode {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  citations: number;
  depth: number;
  direction: 'root' | 'forward' | 'backward';
  url?: string;
  abstract?: string;
  x: number;
  y: number;
}

export interface CitationEdge {
  source: string;
  target: string;
  weight: number;
  contexts?: string[];
  intents?: string[];
  is_influential?: boolean;
}

export interface CitationTreeData {
  nodes: CitationNode[];
  edges: CitationEdge[];
  root_paper_ids: string[];
  generated_at: string;
  skipped_papers?: string[];
}

export type { HighlightItem };
