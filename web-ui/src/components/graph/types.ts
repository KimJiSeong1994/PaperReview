import type { GraphData, Paper } from '../../types';

export interface SigmaGraphViewProps {
  graphData: GraphData;
  selectedPaper: Paper | null;
  highlightedPapers: Set<string>;
  papers: Paper[];
  onNodeClick: (paper: Paper) => void;
  showLabels: boolean;
  edgeOpacity: number;
  minCitations: number;
  yearFilter: [number, number] | null;
}

export interface GraphStats {
  nodes: number;
  edges: number;
  avgCitations: number;
  yearRange: [number, number];
}
