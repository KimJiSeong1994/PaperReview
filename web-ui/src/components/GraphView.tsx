import { useMemo } from 'react';
import Plot from 'react-plotly.js';
import type { Data, Layout } from 'plotly.js';
import './GraphView.css';
import type { GraphData, Paper } from '../types';

interface GraphViewProps {
  graphData: GraphData;
  selectedPaper: Paper | null;
  highlightedPapers: Set<string>;
  papers: Paper[];
  onNodeClick: (paper: Paper) => void;
}

function GraphView({ graphData, selectedPaper, highlightedPapers, papers, onNodeClick }: GraphViewProps) {
  const { plotData, layout } = useMemo(() => {
    if (!graphData || graphData.nodes.length === 0) {
      return { plotData: [], layout: {} };
    }

    const nodes = graphData.nodes;
    const edges = graphData.edges;

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
      const yearRange = maxYear - minYear || 1;
      

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
    }
    
    const selectedPaperIdForEdges = selectedPaper?.doc_id ? String(selectedPaper.doc_id) : null;
    
    // Weight 범위 계산 (투명도 매핑용)
    const weights = edges.map(e => e.weight || 0.1).filter(w => w > 0);
    const minWeight = weights.length > 0 ? Math.min(...weights) : 0.1;
    const maxWeight = weights.length > 0 ? Math.max(...weights) : 1.0;
    const weightRange = maxWeight - minWeight || 1.0;
    
    // 투명도별로 edge 그룹화 (5개 그룹으로 제한하여 trace 수 최소화)
    const normalEdgeGroups: Map<string, EdgeGroup> = new Map();
    const highlightedEdgeGroups: Map<string, EdgeGroup> = new Map();
    
    edges.forEach(edge => {
      const sourceNode = nodeMap.get(String(edge.source));
      const targetNode = nodeMap.get(String(edge.target));
      
      if (sourceNode && targetNode) {
        const sourceId = String(edge.source);
        const targetId = String(edge.target);
        const isHighlighted = 
          (selectedPaperIdForEdges && (sourceId === selectedPaperIdForEdges || targetId === selectedPaperIdForEdges)) ||
          highlightedPapers.has(sourceId) || highlightedPapers.has(targetId);
        
        const edgeWeight = edge.weight || 0.1;
        // Weight를 0~1 범위로 정규화
        const normalizedWeight = weightRange > 0 
          ? (edgeWeight - minWeight) / weightRange 
          : 0.5;
        
        // 투명도를 5단계로 그룹화 (0.2, 0.3, 0.4, 0.5, 0.6)
        let opacity: number;
        if (isHighlighted) {
          // 하이라이트된 edge: 0.3 ~ 0.7
          opacity = Math.round((0.3 + (0.7 - 0.3) * normalizedWeight) * 10) / 10;
        } else {
          // 일반 edge: hasHighlightedNodes 여부에 따라
          const hasHighlightedNodes = selectedPaper || highlightedPapers.size > 0;
          const baseOpacity = hasHighlightedNodes ? 0.15 : 0.3;
          const maxOpacity = hasHighlightedNodes ? 0.35 : 0.6;
          opacity = Math.round((baseOpacity + (maxOpacity - baseOpacity) * normalizedWeight) * 10) / 10;
        }
        
        const opacityKey = opacity.toFixed(1);
        const groupMap = isHighlighted ? highlightedEdgeGroups : normalEdgeGroups;
        
        if (!groupMap.has(opacityKey)) {
          groupMap.set(opacityKey, {
            x: [],
            y: [],
            opacity: opacity,
            isHighlighted: isHighlighted,
          });
        }
        
        const group = groupMap.get(opacityKey)!;
        group.x.push(sourceNode.x, targetNode.x, NaN);
        group.y.push(sourceNode.y, targetNode.y, NaN);
      }
    });

    // 그룹화된 edge trace 생성
    const normalEdgeTraces: Data[] = Array.from(normalEdgeGroups.values()).map(group => ({
      x: group.x,
      y: group.y,
      mode: 'lines' as const,
      line: {
        width: 0.7,
        color: `rgba(156, 163, 175, ${group.opacity})`,
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
        width: 2.5,
        color: `rgba(168, 85, 247, ${group.opacity})`,
      },
      hoverinfo: 'skip' as const,
      showlegend: false,
      type: 'scatter' as const,
    }));

    // Separate nodes into three groups for z-ordering
    const selectedPaperId = selectedPaper ? String(selectedPaper.doc_id) : null;
    const normalNodes: typeof nodes = [];
    const highlightedNodes: typeof nodes = [];
    const selectedNodes: typeof nodes = [];
    
    nodes.forEach(n => {
      const nodeId = String((n as any).doc_id || n.id);
      if (selectedPaperId === nodeId) {
        selectedNodes.push(n);
      } else if (highlightedPapers.has(nodeId)) {
        highlightedNodes.push(n);
      } else {
        normalNodes.push(n);
      }
    });

    // Helper function to truncate title to a brief version
    const truncateTitle = (title: string, maxWords: number = 5): string => {
      if (!title) return 'Untitled';
      const words = title.split(' ');
      if (words.length <= maxWords) return title;
      return words.slice(0, maxWords).join(' ') + '...';
    };

    // Helper function to create node trace
    const createNodeTrace = (nodeList: typeof nodes, isHighlighted: boolean, isSelected: boolean): Data | null => {
      if (nodeList.length === 0) return null;
      
      const nodeX = nodeList.map(n => n.x);
      const nodeY = nodeList.map(n => n.y);
      
      // Calculate opacity for normal nodes based on whether there are selected/highlighted nodes
      const hasHighlightedNodes = selectedPaper || highlightedPapers.size > 0;
      
      // Calculate colors for all nodes - exactly matching web_app.py
      const nodeColors = nodeList.map(n => {
        try {
          // Get year and calculate color - exactly like web_app.py line 298-301
          const nodeYear = n.year ? Number(n.year) : null;
          const year = (nodeYear && !isNaN(nodeYear)) ? nodeYear : minYear;
          
          // Calculate relative position in year range - exactly like web_app.py
          const relative = yearRange > 0 ? (year - minYear) / yearRange : 0;
          const baseGreen = Math.floor(150 + relative * 70); // Green: 150~220 based on year
          
          if (isSelected) {
            // Selected node - purple color matching highlighted edges
            return 'rgba(168, 85, 247, 0.95)'; // Purple color like edges
          } else {
            // All other nodes: use original green/blue color with 0.95 opacity (exactly like web_app.py line 301)
            // Ensure baseGreen is clamped to valid range
            const clampedGreen = Math.max(150, Math.min(220, baseGreen));
            // Return color as a proper rgba string
            return `rgba(60, ${clampedGreen}, 150, 0.95)`;
          }
        } catch (error) {
          // Fallback color if calculation fails
          console.error('Error calculating node color:', error, n);
          return 'rgba(60, 150, 150, 0.95)';
        }
      });
      

      const nodeSizes = nodeList.map(n => {
        const citations = n.citations || 1;
        const baseSize = 12;
        const size = baseSize + 6 * Math.log10(citations + 1);
        if (isSelected) {
          return size * 1.5;
        } else if (isHighlighted) {
          return size * 1.35; // Similar size to selected
        }
        return size;
      });

      // Ensure nodeColors is a valid array with proper color strings
      const validColors = nodeColors.length > 0 && nodeColors.every(c => typeof c === 'string' && c.startsWith('rgba'))
        ? nodeColors 
        : nodeList.map(() => 'rgba(60, 150, 150, 0.95)'); // Fallback if colors are invalid
      

      return {
        x: nodeX,
        y: nodeY,
        mode: 'markers', // Remove text from markers, use separate text trace
        type: 'scatter',
        marker: {
          size: nodeSizes,
          color: validColors, // Use validated colors array (opacity already in rgba values)
          showscale: false, // Disable color scale to use direct color values
          line: {
            width: isSelected ? 3.5 : (isHighlighted ? 3 : 2),
            color: isSelected 
              ? 'rgba(221, 214, 254, 1)' // Light purple border for selected node to match purple node color
              : (isHighlighted 
                ? '#ffffff' // White border for highlighted
                : (hasHighlightedNodes 
                  ? 'rgba(255, 255, 255, 0.6)' // Slightly transparent white border for normal nodes when highlighted
                  : '#ffffff')),
          },
        },
        hovertext: nodeList.map(n => n.title || ''),
        hoverinfo: 'text',
        showlegend: false,
        customdata: nodeList.map(n => {
          const nodeDocId = (n as any).doc_id || n.id;
          return nodeDocId;
        }),
      };
    };

    // Create node traces in order (normal -> highlighted -> selected)
    // Last trace will be drawn on top
    const normalNodeTrace = createNodeTrace(normalNodes, false, false);
    const highlightedNodeTrace = createNodeTrace(highlightedNodes, true, false);
    const selectedNodeTrace = createNodeTrace(selectedNodes, false, true);

    // Helper function to create text-only trace positioned above nodes
    const createTextTrace = (nodeList: typeof nodes, isHighlighted: boolean, isSelected: boolean): Data | null => {
      if (nodeList.length === 0) return null;
      
      const hasHighlightedNodes = selectedPaper || highlightedPapers.size > 0;
      const textOffset = 0.08; // Offset to move text higher above nodes
      
      const nodeX = nodeList.map(n => n.x);
      const nodeY = nodeList.map(n => n.y + textOffset); // Move text higher
      const nodeText = nodeList.map(n => {
        return truncateTitle(n.title || 'Untitled', 5);
      });

      return {
        x: nodeX,
        y: nodeY,
        mode: 'text',
        type: 'scatter',
        text: nodeText,
        textposition: 'middle center',
        textfont: {
          size: 9,
          color: hasHighlightedNodes && !isSelected && !isHighlighted 
            ? 'rgba(255, 255, 255, 0.6)' // More visible text for non-highlighted nodes
            : 'rgba(255, 255, 255, 0.9)', // White text for better visibility on dark background
        },
        hoverinfo: 'skip',
        showlegend: false,
      };
    };

    // Create text traces
    const normalTextTrace = createTextTrace(normalNodes, false, false);
    const highlightedTextTrace = createTextTrace(highlightedNodes, true, false);
    const selectedTextTrace = createTextTrace(selectedNodes, false, true);

    // Build plot data with proper z-ordering:
    // 1. Normal edges (bottom) - weight에 따라 투명도 조절
    // 2. Highlighted edges (middle) - weight에 따라 투명도 조절
    // 3. Normal nodes (middle)
    // 4. Highlighted nodes (upper)
    // 5. Selected node (top)
    // 6. Text traces (on top of nodes)
    const plotData: Data[] = [
      ...normalEdgeTraces,  // Weight에 따라 투명도가 다른 일반 edge들
      ...highlightedEdgeTraces,  // Weight에 따라 투명도가 다른 하이라이트 edge들
      ...(normalNodeTrace ? [normalNodeTrace] : []),
      ...(highlightedNodeTrace ? [highlightedNodeTrace] : []),
      ...(selectedNodeTrace ? [selectedNodeTrace] : []),
      ...(normalTextTrace ? [normalTextTrace] : []),
      ...(highlightedTextTrace ? [highlightedTextTrace] : []),
      ...(selectedTextTrace ? [selectedTextTrace] : []),
    ].filter(Boolean) as Data[];

    const plotLayout: Partial<Layout> = {
      showlegend: false,
      hovermode: 'closest',
      margin: { l: 0, r: 0, t: 10, b: 10 },
      xaxis: { 
        visible: false, 
        range: [-1.2, 1.2],
        fixedrange: false, // Allow zoom/pan
      },
      yaxis: { 
        visible: false, 
        range: [-1.2, 1.2],
        fixedrange: false, // Allow zoom/pan
      },
      plot_bgcolor: '#181818',
      paper_bgcolor: '#181818',
      font: { color: '#ececec', family: 'Roboto, sans-serif' },
      height: 620,
      dragmode: 'pan', // Enable pan mode for dragging
    };

    return { plotData, layout: plotLayout };
  }, [graphData, selectedPaper, highlightedPapers]);

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

  const handlePlotClick = (data: any) => {
    if (!data.points || data.points.length === 0) return;
    
    const point = data.points[0];
    if (!point.customdata) return;
    
    const nodeDocId = String(point.customdata);
    
    // Map을 사용하여 빠른 조회
    const paper = papersMap.get(nodeDocId);
    if (paper) {
      onNodeClick(paper);
      return;
    }
    
    // Fallback: graph node에서 찾기
    const node = graphData.nodes.find(n => {
      const nId = String((n as any).doc_id || n.id);
      return nId === nodeDocId;
    });
    
    if (node && node.title) {
      const paperByTitle = papersMap.get(node.title);
      if (paperByTitle) {
        onNodeClick(paperByTitle);
      }
    }
  };

  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className="graph-empty">
        <p>그래프 데이터가 없습니다.</p>
      </div>
    );
  }

  return (
    <div className="graph-view">
      <Plot
        data={plotData}
        layout={layout}
        config={{ 
          displayModeBar: true,
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
        onClick={handlePlotClick}
        useResizeHandler
      />
    </div>
  );
}

export default GraphView;

