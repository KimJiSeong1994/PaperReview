import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Plot from '../PlotlyChart';
import type { Data, Layout } from '../PlotlyChart';
import './GraphView.css';
import type { GraphData, Paper } from '../types';
import type { GraphStats } from './graph/types';
import { useGraphData } from './graph/useGraphData';
import { useThemeObserver } from '../theme';
import {
  graphEdgeKey,
  neighborhoodSubgraph,
  pathEdgeKeys,
  rankedSubgraph,
  separateCommunityLayout,
  strongestPathToOrigin,
  type GraphMode,
  type GraphNodeLimit,
} from './graph/graphPresentation';

const SigmaGraphView = lazy(() => import('./graph/SigmaGraphView'));

const useSigma = import.meta.env.VITE_USE_SIGMA === 'true';

const COMMUNITY_COLORS_DARK = [
  [34, 211, 238],
  [91, 124, 250],
  [168, 85, 247],
  [240, 79, 154],
  [34, 197, 94],
  [245, 158, 11],
] as const;

const COMMUNITY_COLORS_LIGHT = [
  [8, 145, 178],
  [67, 97, 196],
  [126, 67, 177],
  [190, 54, 116],
  [22, 135, 66],
  [180, 99, 4],
] as const;

const rgba = (rgb: readonly [number, number, number], alpha: number) => (
  `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`
);

const curvedEdge = (
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
  seed: string,
) => {
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  const length = Math.max(Math.hypot(dx, dy), 0.001);
  const direction = [...seed].reduce((sum, character) => sum + character.charCodeAt(0), 0) % 2 === 0 ? 1 : -1;
  const bend = Math.min(0.13, Math.max(0.045, length * 0.12)) * direction;
  const controlX = (sourceX + targetX) / 2 + (-dy / length) * bend;
  const controlY = (sourceY + targetY) / 2 + (dx / length) * bend;
  const x: number[] = [];
  const y: number[] = [];

  for (let index = 0; index <= 14; index += 1) {
    const t = index / 14;
    const inverse = 1 - t;
    x.push(inverse * inverse * sourceX + 2 * inverse * t * controlX + t * t * targetX);
    y.push(inverse * inverse * sourceY + 2 * inverse * t * controlY + t * t * targetY);
  }

  return { x, y, midpoint: { x: x[7], y: y[7] } };
};

interface GraphViewProps {
  graphData: GraphData;
  selectedPaper: Paper | null;
  highlightedPapers: Set<string>;
  papers: Paper[];
  onNodeClick: (paper: Paper) => void;
}

interface PlotClickEvent {
  points?: Array<{ customdata?: unknown }>;
}

interface PlotlyGraphDiv extends HTMLElement {
  on?: (eventName: 'plotly_click', handler: (event: PlotClickEvent) => void) => void;
  removeListener?: (eventName: 'plotly_click', handler: (event: PlotClickEvent) => void) => void;
}

function GraphView({ graphData, selectedPaper, highlightedPapers, papers, onNodeClick }: GraphViewProps) {
  const [showLabels, setShowLabels] = useState(true);
  const [edgeOpacity, setEdgeOpacity] = useState(0.5);
  const [minCitations, setMinCitations] = useState(0);
  const [yearFilter, setYearFilter] = useState<[number, number] | null>(null);
  const [showControls, setShowControls] = useState(true);
  const [showAllEdges, setShowAllEdges] = useState(true);
  const [showNeighborhoodLayer, setShowNeighborhoodLayer] = useState(false);
  const [showPathLayer, setShowPathLayer] = useState(false);
  const [nodeLimit, setNodeLimit] = useState<GraphNodeLimit>(50);
  const [viewRevision, setViewRevision] = useState(0);
  const [isCompactViewport, setIsCompactViewport] = useState(
    () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia('(max-width: 520px)').matches
      : false,
  );
  const theme = useThemeObserver();

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const mediaQuery = window.matchMedia('(max-width: 520px)');
    const handleChange = (event: MediaQueryListEvent) => setIsCompactViewport(event.matches);
    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  const selectedPaperId = selectedPaper?.doc_id ? String(selectedPaper.doc_id) : null;
  const originPaperId = papers[0]?.doc_id ? String(papers[0].doc_id) : null;

  const relationshipSummary = useMemo(() => {
    if (!selectedPaperId) return { count: 0, strongest: 0, sharedTerms: [] as string[] };
    const connected = graphData.edges.filter(edge => (
      String(edge.source) === selectedPaperId || String(edge.target) === selectedPaperId
    ));
    const strongestEdge = [...connected].sort((left, right) => (right.weight || 0) - (left.weight || 0))[0];
    return {
      count: connected.length,
      strongest: connected.reduce((max, edge) => Math.max(max, edge.weight || 0), 0),
      sharedTerms: strongestEdge?.shared_terms || [],
    };
  }, [graphData.edges, selectedPaperId]);

  const strongestPath = useMemo(
    () => strongestPathToOrigin(graphData, selectedPaperId, originPaperId),
    [graphData, originPaperId, selectedPaperId],
  );
  const strongestPathEdgeKeys = useMemo(() => pathEdgeKeys(strongestPath), [strongestPath]);
  const pathNodeIds = useMemo(() => new Set(strongestPath), [strongestPath]);
  const isNeighborhoodLayerActive = Boolean(showNeighborhoodLayer && selectedPaperId);
  const isPathLayerActive = Boolean(showPathLayer && selectedPaperId && pathNodeIds.size > 1);
  const activeGraphMode: GraphMode = isPathLayerActive
    ? 'path'
    : isNeighborhoodLayerActive
      ? 'neighborhood'
      : 'landscape';
  const positionedGraphData = useMemo(
    () => separateCommunityLayout(graphData),
    [graphData],
  );
  const neighborhoodGraphData = useMemo(
    () => selectedPaperId ? neighborhoodSubgraph(positionedGraphData, selectedPaperId, nodeLimit) : null,
    [nodeLimit, positionedGraphData, selectedPaperId],
  );

  const visibleGraphData = useMemo<GraphData>(() => {
    const pinnedIds = [originPaperId, selectedPaperId].filter((value): value is string => Boolean(value));
    if (isPathLayerActive) pinnedIds.push(...strongestPath);
    const positioned = rankedSubgraph(positionedGraphData, nodeLimit, pinnedIds);
    if (!isNeighborhoodLayerActive || !neighborhoodGraphData) return positioned;

    const hopByNode = new Map(
      neighborhoodGraphData.nodes.map(node => [String(node.id), node.hop_distance]),
    );
    return {
      ...positioned,
      nodes: positioned.nodes.map(node => ({
        ...node,
        hop_distance: hopByNode.get(String(node.id)),
      })),
    };
  }, [isNeighborhoodLayerActive, isPathLayerActive, neighborhoodGraphData, nodeLimit, originPaperId, positionedGraphData, selectedPaperId, strongestPath]);

  const displayGraphData = useMemo<GraphData>(() => {
    if (showAllEdges || visibleGraphData.edges.length <= 40) return visibleGraphData;

    const edgeKey = (source: string, target: string) => (
      source < target ? `${source}--${target}` : `${target}--${source}`
    );
    const retained = new Set<string>();
    const incident = new Map<string, typeof visibleGraphData.edges>();
    const visibleHopByNode = new Map(
      visibleGraphData.nodes.map(node => [String(node.id), node.hop_distance]),
    );

    visibleGraphData.edges.forEach(edge => {
      const source = String(edge.source);
      const target = String(edge.target);
      incident.set(source, [...(incident.get(source) || []), edge]);
      incident.set(target, [...(incident.get(target) || []), edge]);
      const sourceHop = visibleHopByNode.get(source);
      const targetHop = visibleHopByNode.get(target);
      const isTraversalEdge = isNeighborhoodLayerActive &&
        typeof sourceHop === 'number' &&
        typeof targetHop === 'number' &&
        Math.abs(sourceHop - targetHop) === 1;
      const isPathEdge = isPathLayerActive && strongestPathEdgeKeys.has(graphEdgeKey(source, target));
      if (isTraversalEdge || isPathEdge) {
        retained.add(edgeKey(source, target));
      }
    });

    incident.forEach(edges => {
      [...edges]
        .sort((a, b) => (b.weight || 0) - (a.weight || 0))
        .slice(0, 3)
        .forEach(edge => retained.add(edgeKey(String(edge.source), String(edge.target))));
    });

    if (selectedPaperId) {
      [...(incident.get(selectedPaperId) || [])]
        .sort((left, right) => (right.weight || 0) - (left.weight || 0))
        .slice(0, 5)
        .forEach(edge => retained.add(edgeKey(String(edge.source), String(edge.target))));
    }

    return {
      ...visibleGraphData,
      edges: visibleGraphData.edges.filter(edge => (
        retained.has(edgeKey(String(edge.source), String(edge.target)))
      )),
    };
  }, [isNeighborhoodLayerActive, isPathLayerActive, selectedPaperId, showAllEdges, strongestPathEdgeKeys, visibleGraphData]);

  const hopCounts = useMemo(() => {
    const counts = [0, 0, 0, 0];
    visibleGraphData.nodes.forEach(node => {
      if (typeof node.hop_distance === 'number' && node.hop_distance >= 0 && node.hop_distance <= 3) {
        counts[node.hop_distance] += 1;
      }
    });
    return counts;
  }, [visibleGraphData.nodes]);

  const effectiveHighlightedPapers = useMemo(() => {
    if (!isPathLayerActive) return highlightedPapers;
    return new Set(
      strongestPath.filter(nodeId => nodeId !== selectedPaperId && nodeId !== originPaperId),
    );
  }, [highlightedPapers, isPathLayerActive, originPaperId, selectedPaperId, strongestPath]);

  // Sigma mode: use shared stats from useGraphData hook
  const { stats: sigmaStats } = useGraphData(
    useSigma ? displayGraphData : null,
    minCitations,
    yearFilter,
    theme,
  );

  const { plotData, layout, stats } = useMemo(() => {
    if (!displayGraphData || displayGraphData.nodes.length === 0) {
      return { plotData: [], layout: {}, stats: { nodes: 0, edges: 0, avgCitations: 0, yearRange: [0, 0] as [number, number] } };
    }

    let nodes = displayGraphData.nodes;
    const edges = displayGraphData.edges;

    const isLight = theme === 'light';

    // Apply filters
    if (minCitations > 0) {
      nodes = nodes.filter(n => (n.citations || 0) >= minCitations);
    }
    
    if (yearFilter) {
      nodes = nodes.filter(n => {
        const year = typeof n.year === 'number' ? n.year : parseInt(String(n.year), 10);
        return !isNaN(year) && year >= yearFilter[0] && year <= yearFilter[1];
      });
    }

      // Calculate year range for coloring
      const years = nodes.map(n => {
        const year = n.year;
        if (typeof year === 'number') return year;
        if (typeof year === 'string') {
          const parsed = parseInt(year, 10);
          return isNaN(parsed) ? null : parsed;
        }
        return null;
      }).filter((y): y is number => y !== null && !isNaN(y));
      
      const minYear = years.length > 0 ? Math.min(...years) : 2010;
      const maxYear = years.length > 0 ? Math.max(...years) : 2024;
      

    // 노드 조회 최적화: Map 사용
    const nodeMap = new Map<string, typeof nodes[0]>();
    nodes.forEach(node => {
      const nodeId = String((node as any).doc_id || node.id);
      nodeMap.set(nodeId, node);
      nodeMap.set(String(node.id), node); // id로도 조회 가능하도록
    });
    
    // Edge trace - highlight edges connected to selected/highlighted papers
    // Weight에 따라 투명도를 조절하기 위해 edge를 투명도 범위별로 그룹화 (성능 최적화)
    interface EdgeGroup {
      x: number[];
      y: number[];
      opacity: number;
      isHighlighted: boolean;
      color: readonly [number, number, number];
    }
    
    const selectedPaperIdForEdges = selectedPaper?.doc_id ? String(selectedPaper.doc_id) : null;
    
    // Weight 범위 계산 (투명도 매핑용)
    const weights = edges.map(e => e.weight || 0.1).filter(w => w > 0);
    const minWeight = weights.length > 0 ? Math.min(...weights) : 0.1;
    const maxWeight = weights.length > 0 ? Math.max(...weights) : 1.0;
    const weightRange = maxWeight - minWeight || 1.0;
    
    // 투명도별로 edge 그룹화 (5개 그룹으로 제한하여 trace 수 최소화)
    const normalEdgeGroups: Map<string, EdgeGroup> = new Map();
    const hopEdgeGroups: Map<string, EdgeGroup> = new Map();
    const highlightedEdgeGroups: Map<string, EdgeGroup> = new Map();
    const focusedEdgeHover = { x: [] as number[], y: [] as number[], text: [] as string[] };

    const escapeHoverText = (value: string): string => value
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;');
    
    edges.forEach(edge => {
      const sourceNode = nodeMap.get(String(edge.source));
      const targetNode = nodeMap.get(String(edge.target));
      
      if (sourceNode && targetNode) {
        const sourceId = String(edge.source);
        const targetId = String(edge.target);
        const connectsSelectedToRankedNeighbor = Boolean(
          selectedPaperIdForEdges && (
            (sourceId === selectedPaperIdForEdges && effectiveHighlightedPapers.has(targetId)) ||
            (targetId === selectedPaperIdForEdges && effectiveHighlightedPapers.has(sourceId))
          )
        );
        const isPathEdge = isPathLayerActive && strongestPathEdgeKeys.has(graphEdgeKey(sourceId, targetId));
        const sourceHop = sourceNode.hop_distance;
        const targetHop = targetNode.hop_distance;
        const isHopEdge = isNeighborhoodLayerActive &&
          typeof sourceHop === 'number' &&
          typeof targetHop === 'number' &&
          Math.abs(sourceHop - targetHop) === 1;
        const isHighlighted = isPathEdge || (!isPathLayerActive && connectsSelectedToRankedNeighbor);
        
        const edgeWeight = edge.weight || 0.1;
        // Weight를 0~1 범위로 정규화
        const normalizedWeight = weightRange > 0 
          ? (edgeWeight - minWeight) / weightRange 
          : 0.5;
        
        // Keep the network quiet by default; selected relationships carry the focus.
        let opacity: number;
        if (isHighlighted) {
          opacity = Math.round((0.38 + 0.42 * normalizedWeight) * edgeOpacity * 100) / 100;
        } else if (isHopEdge) {
          opacity = Math.round((0.22 + 0.16 * normalizedWeight) * edgeOpacity * 100) / 100;
        } else {
          const hasHighlightedNodes = selectedPaper || effectiveHighlightedPapers.size > 0;
          const baseOpacity = hasHighlightedNodes ? 0.06 : 0.1;
          const maxOpacity = hasHighlightedNodes ? 0.2 : 0.28;
          opacity = Math.round((baseOpacity + (maxOpacity - baseOpacity) * normalizedWeight) * edgeOpacity * 100) / 100;
        }
        
        const communityId = typeof sourceNode.community_id === 'number' ? sourceNode.community_id : 0;
        const edgeColor = (isLight ? COMMUNITY_COLORS_LIGHT : COMMUNITY_COLORS_DARK)[communityId % 6];
        const opacityKey = `${communityId % 6}-${opacity.toFixed(2)}`;
        const groupMap = isHighlighted
          ? highlightedEdgeGroups
          : isHopEdge
            ? hopEdgeGroups
            : normalEdgeGroups;
        
        if (!groupMap.has(opacityKey)) {
          groupMap.set(opacityKey, {
            x: [],
            y: [],
            opacity: opacity,
            isHighlighted: isHighlighted,
            color: edgeColor,
          });
        }
        
        const group = groupMap.get(opacityKey)!;
        const curve = isHighlighted
          ? curvedEdge(sourceNode.x, sourceNode.y, targetNode.x, targetNode.y, graphEdgeKey(sourceId, targetId))
          : null;
        group.x.push(...(curve?.x || [sourceNode.x, targetNode.x]), NaN);
        group.y.push(...(curve?.y || [sourceNode.y, targetNode.y]), NaN);

        if (isHighlighted) {
          const sharedTerms = (edge.shared_terms || []).map(escapeHoverText).join(' · ');
          focusedEdgeHover.x.push(curve?.midpoint.x ?? (sourceNode.x + targetNode.x) / 2);
          focusedEdgeHover.y.push(curve?.midpoint.y ?? (sourceNode.y + targetNode.y) / 2);
          focusedEdgeHover.text.push(
            `유사도 ${Math.round(edgeWeight * 100)}%${sharedTerms ? `<br>공통 단서 · ${sharedTerms}` : ''}`,
          );
        }
      }
    });

    // 그룹화된 edge trace 생성
    const normalEdgeTraces: Data[] = Array.from(normalEdgeGroups.values()).map(group => ({
      x: group.x,
      y: group.y,
      mode: 'lines' as const,
      line: {
        width: 0.62,
        color: rgba(
          group.color,
          Math.min(0.22, Math.max(isNeighborhoodLayerActive || isPathLayerActive ? 0.045 : 0.08, group.opacity)),
        ),
      },
      hoverinfo: 'skip' as const,
      showlegend: false,
      type: 'scatter' as const,
    }));

    const hopEdgeTraces: Data[] = Array.from(hopEdgeGroups.values()).map(group => ({
      x: group.x,
      y: group.y,
      mode: 'lines' as const,
      line: {
        width: 1.2,
        color: rgba(group.color, Math.min(isLight ? 0.24 : 0.34, Math.max(0.16, group.opacity))),
      },
      hoverinfo: 'skip' as const,
      showlegend: false,
      type: 'scatter' as const,
    }));

    const highlightedEdgeGlowTraces: Data[] = Array.from(highlightedEdgeGroups.values()).map(group => ({
      x: group.x,
      y: group.y,
      mode: 'lines' as const,
      line: {
        width: 6,
        color: rgba(group.color, isLight ? 0.08 : 0.16),
      },
      hoverinfo: 'skip' as const,
      showlegend: false,
      type: 'scatter' as const,
    }));

    const highlightedEdgeTraces: Data[] = Array.from(highlightedEdgeGroups.values()).map(group => ({
      x: group.x,
      y: group.y,
      mode: 'lines' as const,
      line: {
        width: 2.1,
        color: rgba(group.color, Math.min(0.9, group.opacity + 0.32)),
      },
      hoverinfo: 'skip' as const,
      showlegend: false,
      type: 'scatter' as const,
    }));

    const focusedEdgeHoverTrace: Data | null = focusedEdgeHover.x.length > 0 ? {
      x: focusedEdgeHover.x,
      y: focusedEdgeHover.y,
      mode: 'markers',
      marker: { size: 20, color: 'rgba(34, 211, 238, 0.01)' },
      hovertext: focusedEdgeHover.text,
      hoverinfo: 'text',
      showlegend: false,
      type: 'scatter',
    } : null;

    // Separate nodes into three groups for z-ordering
    const activeSelectedPaperId = selectedPaper ? String(selectedPaper.doc_id) : null;
    const normalNodes: typeof nodes = [];
    const originNodes: typeof nodes = [];
    const highlightedNodes: typeof nodes = [];
    const selectedNodes: typeof nodes = [];
    
    nodes.forEach(n => {
      const nodeId = String((n as any).doc_id || n.id);
      if (activeSelectedPaperId === nodeId) {
        selectedNodes.push(n);
      } else if (originPaperId === nodeId) {
        originNodes.push(n);
      } else if (effectiveHighlightedPapers.has(nodeId)) {
        highlightedNodes.push(n);
      } else {
        normalNodes.push(n);
      }
    });

    const weightedDegree = new Map<string, number>();
    edges.forEach(edge => {
      const sourceId = String(edge.source);
      const targetId = String(edge.target);
      const weight = Math.max(edge.weight || 0.1, 0.1);
      weightedDegree.set(sourceId, (weightedDegree.get(sourceId) || 0) + weight);
      weightedDegree.set(targetId, (weightedDegree.get(targetId) || 0) + weight);
    });
    const maxWeightedDegree = Math.max(1, ...weightedDegree.values());

    // Helper function to truncate title to a brief version
    const truncateTitle = (title: string, maxWords: number = 5): string => {
      if (!title) return 'Untitled';
      const words = title.split(' ');
      if (words.length <= maxWords) return title;
      return words.slice(0, maxWords).join(' ') + '...';
    };

    // Helper function to create node trace
    const createNodeTrace = (
      nodeList: typeof nodes,
      status: 'normal' | 'origin' | 'highlighted' | 'selected',
    ): Data | null => {
      if (nodeList.length === 0) return null;

      const isHighlighted = status === 'highlighted';
      const isSelected = status === 'selected';
      const isOrigin = status === 'origin';
      const containsOrigin = nodeList.some(n => String((n as any).doc_id || n.id) === originPaperId);
      
      const nodeX = nodeList.map(n => n.x);
      const nodeY = nodeList.map(n => n.y);
      
      // Calculate opacity for normal nodes based on whether there are selected/highlighted nodes
      const hasHighlightedNodes = Boolean(
        (selectedPaper && String(selectedPaper.doc_id) !== originPaperId) ||
        effectiveHighlightedPapers.size > 0
      );
      
      const nodeColors = nodeList.map(n => {
        if (isOrigin) return isLight ? 'rgba(180, 99, 4, 0.98)' : 'rgba(245, 158, 11, 0.98)';
        if (isSelected) return isLight ? 'rgba(126, 67, 177, 0.98)' : 'rgba(168, 85, 247, 0.98)';
        const communityId = typeof n.community_id === 'number' ? n.community_id : 0;
        const color = (isLight ? COMMUNITY_COLORS_LIGHT : COMMUNITY_COLORS_DARK)[communityId % 6];
        if (isNeighborhoodLayerActive) {
          if (typeof n.hop_distance !== 'number') return rgba(color, isLight ? 0.2 : 0.16);
          const hopAlpha = [1, 0.98, 0.9, 0.82][n.hop_distance] || 0.72;
          return rgba(color, isLight ? Math.max(0.68, hopAlpha - 0.08) : hopAlpha);
        }
        const dimmed = hasHighlightedNodes && !isHighlighted ? (isLight ? 0.66 : 0.62) : (isLight ? 0.94 : 0.96);
        return rgba(color, isHighlighted ? 0.98 : dimmed);
      });

      const nodeSizes = nodeList.map(n => {
        const nodeId = String((n as any).doc_id || n.id);
        const citations = Math.max(n.citations || 0, 0);
        const degreeRatio = (weightedDegree.get(nodeId) || 0) / maxWeightedDegree;
        const size = Math.min(22, 6 + 3 * Math.log10(citations + 1) + 8 * Math.sqrt(degreeRatio));
        if (isSelected) {
          return Math.min(30, Math.max(22, size * 1.38));
        } else if (isOrigin) {
          return Math.min(28, Math.max(22, size * 1.3));
        } else if (isHighlighted) {
          return Math.min(24, size * 1.14);
        }
        return size;
      });

      // Ensure nodeColors is a valid array with proper color strings
      const validColors = nodeColors.length > 0 && nodeColors.every(c => typeof c === 'string' && c.startsWith('rgba'))
        ? nodeColors 
        : nodeList.map(() => isLight ? 'rgba(8, 145, 178, 0.9)' : 'rgba(34, 211, 238, 0.9)');

      const defaultLineColor = isLight
        ? (hasHighlightedNodes && !isHighlighted ? 'rgba(15, 23, 42, 0.24)' : 'rgba(15, 23, 42, 0.48)')
        : (isHighlighted
          ? 'rgba(224, 231, 255, 0.9)'
          : (hasHighlightedNodes ? 'rgba(226, 232, 240, 0.22)' : 'rgba(226, 232, 240, 0.48)'));
      const hopRingColors = isLight
        ? ['rgba(8, 145, 178, 0.92)', 'rgba(126, 67, 177, 0.92)', 'rgba(190, 54, 116, 0.92)']
        : ['rgba(34, 211, 238, 0.96)', 'rgba(168, 85, 247, 0.96)', 'rgba(240, 79, 154, 0.96)'];
      const lineColors = nodeList.map(n => {
        if (isSelected) {
          return containsOrigin
            ? (isLight ? 'rgba(180, 83, 9, 0.95)' : 'rgba(251, 191, 36, 0.95)')
            : (isLight ? 'rgba(67, 56, 202, 0.95)' : 'rgba(199, 210, 254, 0.95)');
        }
        if (isOrigin) return isLight ? 'rgba(180, 83, 9, 0.95)' : 'rgba(251, 191, 36, 0.95)';
        if (isNeighborhoodLayerActive && n.hop_distance && n.hop_distance <= 3) {
          return hopRingColors[n.hop_distance - 1];
        }
        return defaultLineColor;
      });
      const lineWidths = nodeList.map(n => (
        isSelected ? 2.2 : isOrigin ? 2 : isNeighborhoodLayerActive && n.hop_distance ? 1.8 : isHighlighted ? 1.4 : 0.9
      ));

      return {
        x: nodeX,
        y: nodeY,
        mode: 'markers', // Remove text from markers, use separate text trace
        type: 'scatter',
        marker: {
          size: nodeSizes,
          color: validColors, // Use validated colors array (opacity already in rgba values)
          symbol: nodeList.map(n => String((n as any).doc_id || n.id) === originPaperId ? 'diamond' : 'circle'),
          showscale: false, // Disable color scale to use direct color values
          line: {
            width: lineWidths,
            color: lineColors,
          },
        },
        hovertext: nodeList.map(n => `${escapeHoverText(n.title || '')}<br>${n.year || '연도 미상'} · 인용 ${n.citations || 0}${n.hop_distance ? `<br>${n.hop_distance}-hop 강한 관계 확장` : ''}<br>${escapeHoverText(n.community_label || '주제 미분류')}`),
        hoverinfo: 'text',
        showlegend: false,
        customdata: nodeList.map(n => {
          const nodeDocId = (n as any).doc_id || n.id;
          return nodeDocId;
        }),
      };
    };

    const createHaloTrace = (
      nodeList: typeof nodes,
      tone: 'origin' | 'selected',
    ): Data | null => {
      if (nodeList.length === 0) return null;

      const haloColor = tone === 'origin'
        ? (isLight ? 'rgba(217, 119, 6, 0.18)' : 'rgba(251, 191, 36, 0.2)')
        : (isLight ? 'rgba(79, 70, 229, 0.16)' : 'rgba(129, 140, 248, 0.2)');

      return {
        x: nodeList.map(node => node.x),
        y: nodeList.map(node => node.y),
        mode: 'markers',
        type: 'scatter',
        marker: {
          size: nodeList.map(node => {
            const citations = Math.max(node.citations || 0, 0);
            return Math.min(42, (8.5 + 3.8 * Math.log10(citations + 1)) * 2.05);
          }),
          color: haloColor,
          line: { width: 0 },
        },
        hoverinfo: 'skip',
        showlegend: false,
      };
    };

    // Create node traces in order (normal -> highlighted -> selected)
    // Last trace will be drawn on top
    const originHaloTrace = createHaloTrace(originNodes, 'origin');
    const selectedHaloTrace = createHaloTrace(
      selectedNodes,
      activeSelectedPaperId === originPaperId ? 'origin' : 'selected',
    );
    const normalNodeTrace = createNodeTrace(normalNodes, 'normal');
    const originNodeTrace = createNodeTrace(originNodes, 'origin');
    const highlightedNodeTrace = createNodeTrace(highlightedNodes, 'highlighted');
    const selectedNodeTrace = createNodeTrace(selectedNodes, 'selected');

    // Helper function to create text-only trace positioned above nodes
    const createTextTrace = (nodeList: typeof nodes, isHighlighted: boolean, isSelected: boolean): Data | null => {
      if (nodeList.length === 0) return null;
      
      const hasHighlightedNodes = selectedPaper || effectiveHighlightedPapers.size > 0;
      const textOffset = 0.065;
      
      const nodeX = nodeList.map(n => n.x);
      const nodeY = nodeList.map(n => n.y + textOffset); // Move text higher
      const nodeText = nodeList.map(n => {
        return truncateTitle(n.title || 'Untitled', isSelected || isHighlighted ? 3 : 4);
      });

      return {
        x: nodeX,
        y: nodeY,
        mode: 'text',
        type: 'scatter',
        text: nodeText,
        textposition: 'middle center',
        textfont: {
          size: isSelected ? 11 : (isHighlighted ? 10 : 9.25),
          // Light: dark-ink labels (white text is invisible on white); dark: unchanged.
          color: isLight
            ? (hasHighlightedNodes && !isSelected && !isHighlighted
              ? 'rgba(30, 41, 59, 0.64)'
              : 'rgba(15, 23, 42, 0.92)')
            : (hasHighlightedNodes && !isSelected && !isHighlighted
              ? 'rgba(226, 232, 240, 0.58)'
              : 'rgba(241, 245, 249, 0.94)'),
        },
        hoverinfo: 'skip',
        showlegend: false,
      };
    };

    // Create text traces (only if labels are enabled)
    const rankedLabelNodes = [...normalNodes]
      .sort((left, right) => {
        const leftId = String((left as any).doc_id || left.id);
        const rightId = String((right as any).doc_id || right.id);
        return (weightedDegree.get(rightId) || 0) - (weightedDegree.get(leftId) || 0);
      });
    const labelLimit = selectedPaper ? 5 : 7;
    const hubLabelNodes: typeof normalNodes = [];
    const labeledNodeIds = new Set<string>();
    const labeledCommunities = new Set<number>();
    rankedLabelNodes.forEach(node => {
      if (hubLabelNodes.length >= labelLimit || typeof node.community_id !== 'number') return;
      if (labeledCommunities.has(node.community_id)) return;
      hubLabelNodes.push(node);
      labeledNodeIds.add(String(node.id));
      labeledCommunities.add(node.community_id);
    });
    rankedLabelNodes.forEach(node => {
      if (hubLabelNodes.length >= labelLimit || labeledNodeIds.has(String(node.id))) return;
      hubLabelNodes.push(node);
      labeledNodeIds.add(String(node.id));
    });
    const normalTextTrace = showLabels && !isCompactViewport ? createTextTrace(hubLabelNodes, false, false) : null;
    const originTextTrace = showLabels && !isCompactViewport ? createTextTrace(originNodes, true, false) : null;
    const highlightedTextTrace = showLabels && !isCompactViewport ? createTextTrace(highlightedNodes.slice(0, 3), true, false) : null;
    const selectedTextTrace = showLabels && !isCompactViewport ? createTextTrace(selectedNodes, false, true) : null;

    const communityShapes: NonNullable<Layout['shapes']> = [];
    const communityAnnotations: NonNullable<Layout['annotations']> = [];
    {
      const communityGroups = new Map<number, typeof nodes>();
      nodes.forEach(node => {
        if (typeof node.community_id !== 'number') return;
        communityGroups.set(node.community_id, [
          ...(communityGroups.get(node.community_id) || []),
          node,
        ]);
      });
      const hasAnalysisLayer = isNeighborhoodLayerActive || isPathLayerActive;
      const communityPalette = (isLight ? COMMUNITY_COLORS_LIGHT : COMMUNITY_COLORS_DARK).map(color => [
        rgba(color, isLight ? (hasAnalysisLayer ? 0.04 : 0.06) : (hasAnalysisLayer ? 0.055 : 0.08)),
        rgba(color, isLight ? (hasAnalysisLayer ? 0.14 : 0.18) : (hasAnalysisLayer ? 0.2 : 0.26)),
      ]);

      communityGroups.forEach((communityNodes, communityId) => {
        if (communityNodes.length < 2) return;
        const xs = communityNodes.map(node => node.x);
        const ys = communityNodes.map(node => node.y);
        const hullPadding = isCompactViewport ? 0.05 : 0.08;
        const left = Math.min(...xs) - hullPadding;
        const right = Math.max(...xs) + hullPadding;
        const bottom = Math.min(...ys) - hullPadding;
        const top = Math.max(...ys) + hullPadding;
        const [fillcolor, lineColor] = communityPalette[communityId % communityPalette.length];
        const communityLabel = communityNodes[0].community_label || `주제 ${communityId + 1}`;
        const annotationText = `<b>${escapeHoverText(communityLabel)}</b>`;
        communityShapes.push({
          type: 'circle',
          xref: 'x',
          yref: 'y',
          x0: left,
          x1: right,
          y0: bottom,
          y1: top,
          fillcolor,
          line: { color: lineColor, width: 1 },
          layer: 'below',
        });
        if (!isCompactViewport) {
          communityAnnotations.push({
            x: (left + right) / 2,
            y: top,
            xref: 'x',
            yref: 'y',
            text: annotationText,
            showarrow: false,
            yshift: 7,
            font: {
              size: 10.5,
              color: isLight ? 'rgba(30, 41, 59, 0.86)' : 'rgba(226, 232, 240, 0.84)',
            },
            bgcolor: isLight ? 'rgba(248, 250, 252, 0.94)' : 'rgba(6, 7, 11, 0.9)',
            bordercolor: lineColor,
            borderwidth: 1,
            borderpad: 4,
          });
        }
      });
    }

    // Build plot data with proper z-ordering:
    // 1. Normal edges (bottom) - weight에 따라 투명도 조절
    // 2. Highlighted edges (middle) - weight에 따라 투명도 조절
    // 3. Normal nodes (middle)
    // 4. Highlighted nodes (upper)
    // 5. Selected node (top)
    // 6. Text traces (on top of nodes)
    const plotData: Data[] = [
      ...normalEdgeTraces,  // Weight에 따라 투명도가 다른 일반 edge들
      ...hopEdgeTraces,
      ...highlightedEdgeGlowTraces,
      ...highlightedEdgeTraces,  // Weight에 따라 투명도가 다른 하이라이트 edge들
      ...(focusedEdgeHoverTrace ? [focusedEdgeHoverTrace] : []),
      ...(originHaloTrace ? [originHaloTrace] : []),
      ...(selectedHaloTrace ? [selectedHaloTrace] : []),
      ...(normalNodeTrace ? [normalNodeTrace] : []),
      ...(originNodeTrace ? [originNodeTrace] : []),
      ...(highlightedNodeTrace ? [highlightedNodeTrace] : []),
      ...(selectedNodeTrace ? [selectedNodeTrace] : []),
      ...(normalTextTrace ? [normalTextTrace] : []),
      ...(originTextTrace ? [originTextTrace] : []),
      ...(highlightedTextTrace ? [highlightedTextTrace] : []),
      ...(selectedTextTrace ? [selectedTextTrace] : []),
    ].filter(Boolean) as Data[];

    const xValues = nodes.map(node => node.x);
    const yValues = nodes.map(node => node.y);
    const xMin = Math.min(...xValues);
    const xMax = Math.max(...xValues);
    const yMin = Math.min(...yValues);
    const yMax = Math.max(...yValues);
    const xPadding = Math.max(0.13, (xMax - xMin) * 0.14);
    const yPadding = Math.max(0.13, (yMax - yMin) * 0.14);
    const plotXRange: [number, number] = [xMin - xPadding, xMax + xPadding];
    const plotYRange: [number, number] = [yMin - yPadding, yMax + yPadding];

    const plotLayout: Partial<Layout> = {
      showlegend: false,
      hovermode: 'closest',
      margin: { l: 0, r: 0, t: 10, b: 10 },
      xaxis: {
        visible: false,
        range: plotXRange,
        fixedrange: false, // Allow zoom/pan
      },
      yaxis: {
        visible: false,
        range: plotYRange,
        fixedrange: false, // Allow zoom/pan
      },
      plot_bgcolor: 'rgba(0, 0, 0, 0)',
      paper_bgcolor: 'rgba(0, 0, 0, 0)',
      font: { color: isLight ? '#1f2937' : '#ececec', family: 'Pretendard, sans-serif' },
      autosize: true,
      dragmode: 'pan', // Enable pan mode for dragging
      shapes: communityShapes,
      annotations: communityAnnotations,
    };

    // Calculate statistics
    const citations = nodes.map(n => n.citations || 0);
    const avgCitations = citations.length > 0 
      ? Math.round(citations.reduce((a, b) => a + b, 0) / citations.length) 
      : 0;
    const stats = {
      nodes: nodes.length,
      edges: edges.length,
      avgCitations,
      yearRange: [minYear, maxYear] as [number, number],
    };

    return { plotData, layout: plotLayout, stats };
  }, [displayGraphData, selectedPaper, effectiveHighlightedPapers, showLabels, edgeOpacity, minCitations, yearFilter, theme, originPaperId, isNeighborhoodLayerActive, isPathLayerActive, strongestPathEdgeKeys, isCompactViewport]);

  // Papers를 Map으로 변환하여 빠른 조회 (useMemo로 최적화)
  const papersMap = useMemo(() => {
    const map = new Map<string, Paper>();
    papers.forEach(paper => {
      const docId = String(paper.doc_id);
      map.set(docId, paper);
      // 여러 키로 저장하여 빠른 조회
      if (paper.title) {
        map.set(paper.title, paper);
      }
    });
    return map;
  }, [papers]);

  const handlePlotClick = useCallback((data: PlotClickEvent) => {
    if (!data.points || data.points.length === 0) return;

    const point = data.points[0];
    if (point.customdata === undefined || point.customdata === null) return;

    const nodeDocId = String(point.customdata);

    // Map을 사용하여 빠른 조회
    const paper = papersMap.get(nodeDocId);
    if (paper) {
      onNodeClick(paper);
      return;
    }

    // Fallback: graph node에서 찾기
    const node = graphData.nodes.find(n => {
      const nodeDocIdValue = (n as unknown as { doc_id?: unknown }).doc_id;
      const nId = String(nodeDocIdValue || n.id);
      return nId === nodeDocId;
    });

    if (node && node.title) {
      const paperByTitle = papersMap.get(node.title);
      if (paperByTitle) {
        onNodeClick(paperByTitle);
      }
    }
  }, [graphData.nodes, onNodeClick, papersMap]);

  const plotClickBindingRef = useRef<{ graphDiv: PlotlyGraphDiv; handler: typeof handlePlotClick } | null>(null);
  const bindPlotClick = useCallback((_figure: unknown, graphDivElement: Readonly<HTMLElement>) => {
    const graphDiv = graphDivElement as unknown as PlotlyGraphDiv;
    const previous = plotClickBindingRef.current;
    if (previous) {
      previous.graphDiv.removeListener?.('plotly_click', previous.handler);
    }

    if (!graphDiv.on) return;
    graphDiv.removeListener?.('plotly_click', handlePlotClick);
    graphDiv.on('plotly_click', handlePlotClick);
    plotClickBindingRef.current = { graphDiv, handler: handlePlotClick };
  }, [handlePlotClick]);

  // react-plotly can lose prop-managed event handlers when Plotly.react runs
  // during StrictMode/search-result updates. Rebind the latest callback even
  // when the graph div itself was retained across the update.
  useEffect(() => {
    const binding = plotClickBindingRef.current;
    if (!binding || binding.handler === handlePlotClick) return;
    binding.graphDiv.removeListener?.('plotly_click', binding.handler);
    if (!binding.graphDiv.on) return;
    binding.graphDiv.on('plotly_click', handlePlotClick);
    plotClickBindingRef.current = { graphDiv: binding.graphDiv, handler: handlePlotClick };
  }, [handlePlotClick]);

  useEffect(() => () => {
    const binding = plotClickBindingRef.current;
    if (binding) {
      binding.graphDiv.removeListener?.('plotly_click', binding.handler);
      plotClickBindingRef.current = null;
    }
  }, []);

  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className="graph-empty">
        <p>그래프 데이터가 없습니다.</p>
      </div>
    );
  }

  // Use sigma stats when in Sigma mode, Plotly stats otherwise
  const activeStats: GraphStats = useSigma ? sigmaStats : stats;
  const edgeMethodLabel = graphData.meta?.edge_label || '논문 간 유사도';
  const edgeThreshold = graphData.meta?.edge_threshold;
  const communityCount = graphData.meta?.communities?.length || 0;
  const activeLayerSummary = [
    '기본 지형',
    isNeighborhoodLayerActive ? '3-hop' : null,
    isPathLayerActive ? '원문 경로' : null,
  ].filter(Boolean).join(' + ');

  // Shared controls UI used by both renderers
  const controlsUI = (
    <div
      className={`graph-controls ${showControls ? 'is-open' : ''}`}
      aria-hidden={!showControls}
      inert={!showControls}
    >
      <div className="graph-controls-header">
        <strong>보기 설정</strong>
        <button type="button" onClick={() => setShowControls(false)} aria-label="보기 설정 닫기">✕</button>
      </div>
        <div className="control-section">
          <div className="control-group">
            <label className="control-label-text" htmlFor="graph-node-limit">표시 논문 수</label>
            <select
              id="graph-node-limit"
              className="control-input"
              value={nodeLimit}
              onChange={(event) => setNodeLimit(Number(event.target.value) as GraphNodeLimit)}
            >
              <option value={20}>20편 · 핵심 구조</option>
              <option value={35}>35편 · 균형</option>
              <option value={50}>50편 · 3-hop 전체</option>
            </select>
          </div>

          <div className="control-group">
            <label className="control-label">
              <input
                type="checkbox"
                checked={showLabels}
                onChange={(e) => setShowLabels(e.target.checked)}
                className="control-checkbox"
              />
              <span>주요 노드 레이블</span>
            </label>
          </div>

          <div className="control-group">
            <label className="control-label">
              <input
                type="checkbox"
                checked={showAllEdges}
                onChange={(e) => setShowAllEdges(e.target.checked)}
                className="control-checkbox"
              />
              <span>전체 연결선 표시</span>
            </label>
          </div>

          <div className="control-group">
            <label className="control-label-text">엣지 투명도</label>
            <input
              type="range"
              min="0.1"
              max="1.0"
              step="0.1"
              value={edgeOpacity}
              onChange={(e) => setEdgeOpacity(parseFloat(e.target.value))}
              className="control-slider"
            />
            <span className="control-value">{(edgeOpacity * 100).toFixed(0)}%</span>
          </div>

          <div className="control-group">
            <label className="control-label-text">최소 인용수</label>
            <input
              type="number"
              min="0"
              max="1000"
              value={minCitations}
              onChange={(e) => setMinCitations(parseInt(e.target.value) || 0)}
              className="control-input"
            />
          </div>

          <div className="control-group">
            <label className="control-label-text">연도 필터</label>
            <div className="control-row">
              <input
                type="number"
                min={activeStats.yearRange[0]}
                max={activeStats.yearRange[1]}
                value={yearFilter?.[0] ?? activeStats.yearRange[0]}
                onChange={(e) => {
                  const val = parseInt(e.target.value);
                  if (!isNaN(val)) {
                    setYearFilter([val, yearFilter?.[1] ?? activeStats.yearRange[1]]);
                  }
                }}
                className="control-input-small"
              />
              <span>~</span>
              <input
                type="number"
                min={activeStats.yearRange[0]}
                max={activeStats.yearRange[1]}
                value={yearFilter?.[1] ?? activeStats.yearRange[1]}
                onChange={(e) => {
                  const val = parseInt(e.target.value);
                  if (!isNaN(val)) {
                    setYearFilter([yearFilter?.[0] ?? activeStats.yearRange[0], val]);
                  }
                }}
                className="control-input-small"
              />
              {yearFilter && (
                <button
                  onClick={() => setYearFilter(null)}
                  className="control-reset-btn"
                  title="필터 초기화"
                >
                  ✕
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="stats-section">
          <div className="stat-item">
            <span className="stat-label">노드:</span>
            <span className="stat-value">{activeStats.nodes}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">엣지:</span>
            <span className="stat-value">{activeStats.edges}/{visibleGraphData.edges.length}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">평균 인용:</span>
            <span className="stat-value">{activeStats.avgCitations}</span>
          </div>
        </div>
    </div>
  );

  const modeSwitcher = (
    <div className="graph-mode-switcher" role="group" aria-label="통합 연구 지형 분석 레이어">
      <span className="graph-base-layer" aria-label="연구 지형은 항상 표시됩니다">
        <span className="graph-layer-indicator is-fixed" aria-hidden="true">●</span>
        기본 지형
      </span>
      <button
        type="button"
        aria-pressed={isNeighborhoodLayerActive}
        className={isNeighborhoodLayerActive ? 'active' : ''}
        disabled={!selectedPaperId}
        title={!selectedPaperId ? '논문을 선택하면 3-hop 관계를 표시합니다' : '현재 지형에 3-hop 관계를 겹쳐 표시합니다'}
        onClick={() => setShowNeighborhoodLayer(value => !value)}
      >
        <span className="graph-layer-indicator" aria-hidden="true">{isNeighborhoodLayerActive ? '✓' : '+'}</span>
        3-hop
      </button>
      <button
        type="button"
        aria-pressed={isPathLayerActive}
        className={isPathLayerActive ? 'active' : ''}
        disabled={!selectedPaperId || pathNodeIds.size <= 1}
        title={!selectedPaperId || pathNodeIds.size <= 1 ? '원 논문과 연결된 논문을 선택하면 사용할 수 있습니다' : '현재 지형에 원 논문 경로를 겹쳐 표시합니다'}
        onClick={() => setShowPathLayer(value => !value)}
      >
        <span className="graph-layer-indicator" aria-hidden="true">{isPathLayerActive ? '✓' : '+'}</span>
        원문 경로
      </button>
    </div>
  );

  const insightBar = (
    <div className="graph-insight-bar">
      <div className="graph-insight-copy" role="status" aria-live="polite">
        <span className="graph-console-title">논문 관계 그래프</span>
        <span className="graph-status-chip">{activeStats.nodes}편</span>
        <span className="graph-status-chip">관계 {activeStats.edges}개</span>
        {communityCount > 0 && <span className="graph-status-chip">주제 {communityCount}개</span>}
        <span className="graph-method-chip">{edgeMethodLabel}</span>
        <span className="graph-layer-state">{activeLayerSummary}</span>
        <span className="graph-sr-only">
          {activeLayerSummary} 표시 중.
          {isNeighborhoodLayerActive ? ` 1-hop ${hopCounts[1]}편, 2-hop ${hopCounts[2]}편, 3-hop ${hopCounts[3]}편.` : ''}
          {isPathLayerActive && strongestPath.length > 1 ? ` 원 논문까지 ${strongestPath.length - 1}단계.` : ''}
        </span>
        {selectedPaper ? (
          <span className="graph-selection-summary">
            <strong>{selectedPaper.title}</strong>
            {!isNeighborhoodLayerActive && !isPathLayerActive && (
              <span>직접 연결 {relationshipSummary.count}편</span>
            )}
            {isNeighborhoodLayerActive && (
              <span>1-hop {hopCounts[1]} · 2-hop {hopCounts[2]} · 3-hop {hopCounts[3]}</span>
            )}
            {isPathLayerActive && strongestPath.length > 1 && (
              <span>원 논문까지 {strongestPath.length - 1}단계</span>
            )}
            {relationshipSummary.sharedTerms.length > 0 && (
              <span>공통 단서 · {relationshipSummary.sharedTerms.slice(0, 2).join(' · ')}</span>
            )}
          </span>
        ) : (
          <span className="graph-selection-summary">
            상위 {visibleGraphData.nodes.length}편 · 노드를 선택해 가까운 연구와 원 논문까지의 경로를 확인하세요
          </span>
        )}
      </div>
      {modeSwitcher}
    </div>
  );

  const floatingTools = (
    <div className="graph-floating-tools" aria-label="그래프 도구">
      <button
        type="button"
        className={showControls ? 'active' : ''}
        aria-label="보기 설정"
        aria-expanded={showControls}
        title="보기 설정"
        onClick={() => setShowControls(value => !value)}
      >
        <span aria-hidden="true">☷</span>
      </button>
      <button
        type="button"
        className={showLabels ? 'active' : ''}
        aria-label={showLabels ? '주요 레이블 숨기기' : '주요 레이블 표시'}
        aria-pressed={showLabels}
        title="주요 레이블"
        onClick={() => setShowLabels(value => !value)}
      >
        <span aria-hidden="true">Aa</span>
      </button>
      <button
        type="button"
        className={showAllEdges ? 'active' : ''}
        aria-label={showAllEdges ? '구조 연결선만 표시' : '전체 연결선 표시'}
        aria-pressed={showAllEdges}
        title="전체 연결선"
        onClick={() => setShowAllEdges(value => !value)}
      >
        <span aria-hidden="true">⌁</span>
      </button>
      <button
        type="button"
        aria-label="그래프 위치 초기화"
        title="그래프 위치 초기화"
        onClick={() => setViewRevision(value => value + 1)}
      >
        <span aria-hidden="true">↺</span>
      </button>
    </div>
  );

  const legendUI = (
    <div className="graph-legend" aria-label="그래프 범례">
      <div className="legend-item">
        <div className="legend-node legend-node-origin"></div>
        <span>원 논문</span>
      </div>
      <div className="legend-item">
        <div className="legend-node legend-node-selected"></div>
        <span>선택 논문</span>
      </div>
      <div className="legend-scale-item" aria-label="커뮤니티 색상">
        {COMMUNITY_COLORS_DARK.slice(0, Math.max(1, Math.min(6, communityCount))).map((color, index) => (
          <span
            key={index}
            className="legend-community-dot"
            style={{ background: rgba(color, 0.9) }}
          />
        ))}
        <span>주제 커뮤니티</span>
      </div>
      <div className="legend-edge-item">
        <span className="legend-edge-line"></span>
        <span>
          {edgeMethodLabel}{edgeThreshold != null ? ` · 기준 ${edgeThreshold}` : ''}
          {isPathLayerActive && strongestPath.length > 1
            ? ` · 강조 경로 ${strongestPath.length - 1}개`
            : (!showAllEdges ? ` · 강한 관계 ${activeStats.edges}개` : '')}
        </span>
      </div>
      {graphData.meta?.communities?.length ? (
        <div className="legend-item">
          <span className="legend-community"></span>
          <span>주제 영역</span>
        </div>
      ) : null}
      {isNeighborhoodLayerActive && (
        <div className="legend-hop-group" aria-label="강한 관계 확장 단계">
          <span><i className="legend-hop legend-hop-1" />1-hop</span>
          <span><i className="legend-hop legend-hop-2" />2-hop</span>
          <span><i className="legend-hop legend-hop-3" />3-hop</span>
        </div>
      )}
      <span className="legend-text">크기 = 인용·연결 허브 · 연도 {activeStats.yearRange[0]}–{activeStats.yearRange[1]}</span>
      <span className="graph-gesture-hint">드래그 이동 · 스크롤 확대 · 더블클릭 초기화</span>
    </div>
  );

  // Sigma WebGL renderer
  if (useSigma) {
    return (
      <div className="graph-view">
        {insightBar}
        <div className="graph-canvas">
          {controlsUI}
          {floatingTools}
          <div className="graph-plot-stage">
            <Suspense fallback={<div className="graph-empty"><p>Loading Sigma...</p></div>}>
              <SigmaGraphView
                key={viewRevision}
                graphData={displayGraphData}
                selectedPaper={selectedPaper}
                highlightedPapers={effectiveHighlightedPapers}
                papers={papers}
                onNodeClick={onNodeClick}
                showLabels={showLabels}
                edgeOpacity={edgeOpacity}
                minCitations={minCitations}
                yearFilter={yearFilter}
                graphMode={activeGraphMode}
                pathEdgeKeys={strongestPathEdgeKeys}
              />
            </Suspense>
          </div>
        </div>
        {legendUI}
      </div>
    );
  }

  // Plotly SVG renderer (default)
  return (
    <div className="graph-view">
      {insightBar}
      <div className="graph-canvas">
        {controlsUI}
        {floatingTools}
        <div className="graph-plot-stage">
          <Plot
            key={viewRevision}
            data={plotData}
            layout={layout}
            config={{
              displayModeBar: false,
              modeBarButtonsToRemove: ['select2d', 'lasso2d'],
              displaylogo: false,
              responsive: true,
              scrollZoom: true,
              doubleClick: 'reset',
              toImageButtonOptions: {
                format: 'png',
                filename: 'graph',
                height: 620,
                width: 1200,
                scale: 1
              }
            }}
            style={{ width: '100%', height: '100%' }}
            onInitialized={bindPlotClick}
            onUpdate={bindPlotClick}
            useResizeHandler
          />
        </div>
      </div>
      {legendUI}
    </div>
  );
}

export default GraphView;
