import type { GraphData, GraphEdge } from '../../types';

export type GraphMode = 'landscape' | 'neighborhood' | 'path';
export type GraphNodeLimit = 20 | 35 | 50;

export const graphEdgeKey = (source: string, target: string): string => (
  source < target ? `${source}--${target}` : `${target}--${source}`
);

export interface RankedNeighbor {
  id: string;
  weight: number;
  sharedTerms: string[];
}

export function rankedNeighbors(
  graphData: GraphData | null | undefined,
  selectedId: string | null | undefined,
  limit = 5,
): RankedNeighbor[] {
  if (!graphData || selectedId === null || selectedId === undefined) return [];

  const selectedKey = String(selectedId);
  const neighbors = new Map<string, RankedNeighbor>();
  graphData.edges.forEach(edge => {
    const source = String(edge.source);
    const target = String(edge.target);
    if (source === target) return;

    const neighborId = source === selectedKey
      ? target
      : target === selectedKey
        ? source
        : null;
    if (neighborId === null || neighborId === selectedKey) return;

    const weight = edge.weight;
    if (typeof weight !== 'number' || !Number.isFinite(weight)) return;
    const existing = neighbors.get(neighborId);
    if (!existing || weight > existing.weight) {
      neighbors.set(neighborId, {
        id: neighborId,
        weight,
        sharedTerms: [...(edge.shared_terms ?? [])],
      });
    }
  });

  return [...neighbors.values()]
    .sort((left, right) => (
      right.weight - left.weight || (left.id < right.id ? -1 : left.id > right.id ? 1 : 0)
    ))
    .slice(0, Math.max(0, Math.floor(limit)));
}

export function describeEdgeMethod(meta?: GraphData['meta']): { label: string; explanation: string } {
  if (meta?.edge_method === 'semantic_cosine') {
    return {
      label: meta.edge_label || '제목 의미 유사도',
      explanation: '제목 임베딩 코사인 유사도 · 인용·인과 관계 아님',
    };
  }
  if (meta?.edge_method === 'title_keyword_jaccard') {
    return {
      label: meta.edge_label || '제목·키워드 유사도',
      explanation: '제목·키워드 겹침(Jaccard) · 인용·인과 관계 아님',
    };
  }
  return {
    label: '논문 간 유사도',
    explanation: '관계 계산 정보 없음',
  };
}

export function strongestPathToOrigin(
  graphData: GraphData,
  selectedId: string | null,
  originId: string | null,
): string[] {
  if (!selectedId || !originId) return [];
  if (selectedId === originId) return [originId];

  const adjacency = new Map<string, Array<{ node: string; cost: number }>>();
  graphData.nodes.forEach(node => adjacency.set(String(node.id), []));
  graphData.edges.forEach(edge => {
    const source = String(edge.source);
    const target = String(edge.target);
    const similarity = Math.max(0.001, Math.min(0.999999, edge.weight || 0.1));
    const cost = -Math.log(similarity);
    adjacency.set(source, [...(adjacency.get(source) || []), { node: target, cost }]);
    adjacency.set(target, [...(adjacency.get(target) || []), { node: source, cost }]);
  });

  const distances = new Map<string, number>([[selectedId, 0]]);
  const previous = new Map<string, string>();
  const pending = new Set(adjacency.keys());

  while (pending.size > 0) {
    let current: string | null = null;
    let currentDistance = Number.POSITIVE_INFINITY;
    pending.forEach(nodeId => {
      const distance = distances.get(nodeId) ?? Number.POSITIVE_INFINITY;
      if (distance < currentDistance) {
        current = nodeId;
        currentDistance = distance;
      }
    });

    if (!current || !Number.isFinite(currentDistance)) break;
    pending.delete(current);
    if (current === originId) break;

    for (const neighbor of adjacency.get(current) || []) {
      if (!pending.has(neighbor.node)) continue;
      const nextDistance = currentDistance + neighbor.cost;
      if (nextDistance < (distances.get(neighbor.node) ?? Number.POSITIVE_INFINITY)) {
        distances.set(neighbor.node, nextDistance);
        previous.set(neighbor.node, current);
      }
    }
  }

  if (!previous.has(originId)) return [];
  const path = [originId];
  let cursor = originId;
  while (cursor !== selectedId) {
    const parent = previous.get(cursor);
    if (!parent) return [];
    path.push(parent);
    cursor = parent;
  }
  return path.reverse();
}

export function pathEdgeKeys(path: string[]): Set<string> {
  const keys = new Set<string>();
  for (let index = 0; index < path.length - 1; index += 1) {
    keys.add(graphEdgeKey(path[index], path[index + 1]));
  }
  return keys;
}

function filteredGraph(
  graphData: GraphData,
  visibleIds: Set<string>,
  hopDistances?: Map<string, number>,
  visibleEdgeKeys?: Set<string>,
): GraphData {
  return {
    ...graphData,
    nodes: graphData.nodes
      .filter(node => visibleIds.has(String(node.id)))
      .map(node => hopDistances
        ? { ...node, hop_distance: hopDistances.get(String(node.id)) }
        : node),
    edges: graphData.edges.filter(edge => (
      visibleIds.has(String(edge.source)) &&
      visibleIds.has(String(edge.target)) &&
      (!visibleEdgeKeys || visibleEdgeKeys.has(graphEdgeKey(String(edge.source), String(edge.target))))
    )),
  };
}

export function rankedSubgraph(
  graphData: GraphData,
  limit: GraphNodeLimit,
  pinnedIds: string[] = [],
): GraphData {
  if (graphData.nodes.length <= limit) return graphData;

  const weightedDegree = new Map<string, number>();
  graphData.edges.forEach(edge => {
    const source = String(edge.source);
    const target = String(edge.target);
    const weight = edge.weight || 0.1;
    weightedDegree.set(source, (weightedDegree.get(source) || 0) + weight);
    weightedDegree.set(target, (weightedDegree.get(target) || 0) + weight);
  });

  const availableIds = new Set(graphData.nodes.map(node => String(node.id)));
  const pinned = Array.from(new Set(pinnedIds)).filter(nodeId => availableIds.has(nodeId));
  const effectiveLimit = Math.max(limit, pinned.length);
  const ranked = [...graphData.nodes].sort((left, right) => {
    const leftId = String(left.id);
    const rightId = String(right.id);
    const degreeDelta = (weightedDegree.get(rightId) || 0) - (weightedDegree.get(leftId) || 0);
    if (degreeDelta !== 0) return degreeDelta;
    return (right.citations || 0) - (left.citations || 0);
  });

  const visibleIds = new Set(pinned);
  for (const node of ranked) {
    if (visibleIds.size >= effectiveLimit) break;
    visibleIds.add(String(node.id));
  }
  return filteredGraph(graphData, visibleIds);
}

/**
 * Packs topic communities so their hulls never overlap: the largest community
 * sits in the middle and the rest are placed on a ring, each scaled to a
 * radius proportional to sqrt(size). Relative positions inside a community
 * come from the source layout, so the organic structure is preserved.
 */
export function separateCommunityLayout(graphData: GraphData): GraphData {
  const communityGroups = new Map<number, typeof graphData.nodes>();
  graphData.nodes.forEach(node => {
    if (typeof node.community_id !== 'number') return;
    communityGroups.set(node.community_id, [
      ...(communityGroups.get(node.community_id) || []),
      node,
    ]);
  });

  const orderedGroups = [...communityGroups.entries()]
    .sort((left, right) => right[1].length - left[1].length || left[0] - right[0]);
  if (orderedGroups.length < 2) return graphData;

  const gap = 0.6;
  const groups = orderedGroups.map(([, communityNodes]) => {
    const centroidX = communityNodes.reduce((sum, node) => sum + node.x, 0) / communityNodes.length;
    const centroidY = communityNodes.reduce((sum, node) => sum + node.y, 0) / communityNodes.length;
    const sourceRadius = Math.max(
      0.05,
      ...communityNodes.map(node => Math.hypot(node.x - centroidX, node.y - centroidY)),
    );
    return {
      nodes: communityNodes,
      centroidX,
      centroidY,
      sourceRadius,
      radius: Math.sqrt(communityNodes.length),
      centerX: 0,
      centerY: 0,
    };
  });

  const [core, ...ring] = groups;
  const ringCircumference = ring.reduce((sum, group) => sum + 2 * group.radius + gap, 0);
  const ringRadius = Math.max(
    core.radius + Math.max(...ring.map(group => group.radius)) + gap,
    ringCircumference / (2 * Math.PI),
  );
  let angle = -Math.PI / 2;
  ring.forEach(group => {
    const span = ((2 * group.radius + gap) / ringCircumference) * 2 * Math.PI;
    const center = angle + span / 2;
    group.centerX = ringRadius * Math.cos(center);
    group.centerY = ringRadius * Math.sin(center);
    angle += span;
  });

  const positionedById = new Map<string, { x: number; y: number }>();
  groups.forEach(group => {
    const scale = group.radius / group.sourceRadius;
    group.nodes.forEach(node => {
      positionedById.set(String(node.id), {
        x: group.centerX + (node.x - group.centroidX) * scale,
        y: group.centerY + (node.y - group.centroidY) * scale,
      });
    });
  });
  // Papers without a community sit on an outer ring so they never land inside a hull.
  const uncategorized = graphData.nodes.filter(node => typeof node.community_id !== 'number');
  const outerRadius = ringRadius + Math.max(...ring.map(group => group.radius)) + gap;
  uncategorized.forEach((node, index) => {
    const theta = -Math.PI / 2 + (2 * Math.PI * index) / uncategorized.length;
    positionedById.set(String(node.id), {
      x: outerRadius * Math.cos(theta),
      y: outerRadius * Math.sin(theta),
    });
  });
  const extent = Math.max(
    1e-6,
    ...[...positionedById.values()].flatMap(position => [Math.abs(position.x), Math.abs(position.y)]),
  );

  return {
    ...graphData,
    nodes: graphData.nodes.map(node => {
      const position = positionedById.get(String(node.id));
      return position ? { ...node, x: position.x / extent, y: position.y / extent } : node;
    }),
  };
}

export function neighborhoodSubgraph(
  graphData: GraphData,
  selectedId: string,
  limit: GraphNodeLimit,
  maxHops: number = 3,
): GraphData {
  const adjacency = new Map<string, Array<{ edge: GraphEdge; neighbor: string }>>();
  graphData.nodes.forEach(node => adjacency.set(String(node.id), []));
  graphData.edges.forEach(edge => {
    const source = String(edge.source);
    const target = String(edge.target);
    adjacency.set(source, [...(adjacency.get(source) || []), { edge, neighbor: target }]);
    adjacency.set(target, [...(adjacency.get(target) || []), { edge, neighbor: source }]);
  });
  const communityByNode = new Map(
    graphData.nodes.map(node => [String(node.id), node.community_id]),
  );
  adjacency.forEach((neighbors, nodeId) => {
    const sorted = [...neighbors]
      .sort((left, right) => (right.edge.weight || 0) - (left.edge.weight || 0));
    const retained = sorted.slice(0, 4);
    const ownCommunity = communityByNode.get(nodeId);
    const foreignCommunityBridges = new Map<number, { edge: GraphEdge; neighbor: string }>();
    if (typeof ownCommunity === 'number') {
      sorted.forEach(candidate => {
        const neighborCommunity = communityByNode.get(candidate.neighbor);
        if (
          typeof neighborCommunity === 'number' &&
          neighborCommunity !== ownCommunity &&
          !foreignCommunityBridges.has(neighborCommunity)
        ) {
          foreignCommunityBridges.set(neighborCommunity, candidate);
        }
      });
    }
    const unique = new Map<string, { edge: GraphEdge; neighbor: string }>();
    [...retained, ...foreignCommunityBridges.values()].forEach(candidate => {
      unique.set(candidate.neighbor, candidate);
    });
    adjacency.set(
      nodeId,
      [...unique.values()],
    );
  });

  const hopDistances = new Map<string, number>([[selectedId, 0]]);
  const discoveryStrength = new Map<string, number>([[selectedId, 1]]);
  const queue = [selectedId];

  while (queue.length > 0) {
    const current = queue.shift()!;
    const currentHop = hopDistances.get(current) || 0;
    if (currentHop >= maxHops) continue;

    const neighbors = [...(adjacency.get(current) || [])]
      .sort((left, right) => (right.edge.weight || 0) - (left.edge.weight || 0));
    for (const { edge, neighbor } of neighbors) {
      const candidateStrength = (discoveryStrength.get(current) || 1) * Math.max(edge.weight || 0.1, 0.1);
      if (!hopDistances.has(neighbor)) {
        hopDistances.set(neighbor, currentHop + 1);
        discoveryStrength.set(neighbor, candidateStrength);
        queue.push(neighbor);
      } else if (hopDistances.get(neighbor) === currentHop + 1) {
        discoveryStrength.set(neighbor, Math.max(discoveryStrength.get(neighbor) || 0, candidateStrength));
      }
    }
  }

  const reachableNodes = graphData.nodes
    .filter(node => hopDistances.has(String(node.id)))
    .sort((left, right) => {
      const leftId = String(left.id);
      const rightId = String(right.id);
      const hopDelta = (hopDistances.get(leftId) || 0) - (hopDistances.get(rightId) || 0);
      if (hopDelta !== 0) return hopDelta;
      const strengthDelta = (discoveryStrength.get(rightId) || 0) - (discoveryStrength.get(leftId) || 0);
      if (strengthDelta !== 0) return strengthDelta;
      return (right.citations || 0) - (left.citations || 0);
    });

  const visibleIds = new Set(reachableNodes.slice(0, limit).map(node => String(node.id)));
  const contextGraph = rankedSubgraph(graphData, limit, [selectedId]);
  for (const node of contextGraph.nodes) {
    if (visibleIds.size >= limit) break;
    visibleIds.add(String(node.id));
  }
  visibleIds.add(selectedId);
  return filteredGraph(graphData, visibleIds, hopDistances);
}

// ── Labels ────────────────────────────────────────────────────────────

const LABEL_FUNCTION_WORDS = new Set([
  'a', 'an', 'the', 'of', 'for', 'on', 'in', 'with', 'to', 'and', 'or', 'via', 'from', 'by',
  'using', 'towards', 'toward', 'at', 'as', 'is', 'are', 'its', 'into', 'over', 'under', 'vs',
]);

const normalizeLabelToken = (word: string): string => (
  word.toLowerCase().replace(/^[^a-z0-9가-힣]+|[^a-z0-9가-힣]+$/g, '')
);

/**
 * Short display label for a graph node.
 *
 * Uses the name prefix before ':' when it is at most six words and carries at
 * least one distinctive token (e.g. "GRAG", "LogicPoison"). Otherwise keeps the
 * first distinctive words of the title, dropping `commonTerms` (tokens most
 * result titles share, i.e. the search query echo) and function words. The
 * token normalization mirrors the backend (`lowercase`, hyphen preserved).
 */
export function shortLabel(
  title: string,
  commonTerms: Iterable<string> = [],
  maxWords = 3,
): string {
  const common = new Set(commonTerms);
  const cleaned = title.trim().replace(/\s+/g, ' ');
  if (!cleaned) return 'Untitled';

  const isFunctionWord = (word: string) => LABEL_FUNCTION_WORDS.has(normalizeLabelToken(word));
  const isDistinctive = (word: string) => {
    const token = normalizeLabelToken(word);
    return token.length > 0 && !common.has(token) && !isFunctionWord(word);
  };

  const colonIndex = cleaned.indexOf(':');
  if (colonIndex > 0) {
    const prefix = cleaned.slice(0, colonIndex).trim();
    const prefixWords = prefix.split(' ');
    if (prefixWords.length <= 6 && prefixWords.some(isDistinctive)) return prefix;
  }

  const words = cleaned.split(' ');
  const picked = new Set<number>();
  words.forEach((word, index) => {
    if (picked.size < maxWords && isDistinctive(word)) picked.add(index);
  });
  words.forEach((word, index) => {
    if (picked.size < Math.min(2, words.length) && !isFunctionWord(word)) picked.add(index);
  });
  if (picked.size === 0) words.slice(0, maxWords).forEach((_, index) => picked.add(index));
  const chosen = [...picked].sort((left, right) => left - right).map(index => words[index]);
  const label = chosen.join(' ');
  return label === cleaned ? label : `${label}…`;
}

/**
 * Short labels that are unique across the given nodes. Duplicates are widened
 * to five words, then suffixed with the year, then numbered.
 */
export function uniqueLabels(
  nodes: Array<{ id: string; title?: string; year?: string | number }>,
  commonTerms: Iterable<string> = [],
): Map<string, string> {
  const common = [...commonTerms];
  const labels = new Map(nodes.map(node => [node.id, shortLabel(node.title || '', common)]));

  const duplicates = () => {
    const byLabel = new Map<string, typeof nodes>();
    nodes.forEach(node => {
      const label = labels.get(node.id)!;
      byLabel.set(label, [...(byLabel.get(label) || []), node]);
    });
    return [...byLabel.values()].filter(group => group.length > 1);
  };

  duplicates().forEach(group => group.forEach(node => {
    labels.set(node.id, shortLabel(node.title || '', common, 5));
  }));
  duplicates().forEach(group => group.forEach(node => {
    if (node.year) labels.set(node.id, `${labels.get(node.id)} (${node.year})`);
  }));
  duplicates().forEach(group => group.forEach((node, index) => {
    if (index > 0) labels.set(node.id, `${labels.get(node.id)} ${index + 1}`);
  }));
  return labels;
}

export interface LabelCandidate {
  id: string;
  x: number;
  y: number;
  text: string;
  /** Higher wins when two labels collide. */
  priority: number;
  fontPx: number;
  /** Marker radius in px; the label sits just outside it. */
  anchorPx: number;
}

export interface PlacedLabel {
  id: string;
  x: number;
  y: number;
  text: string;
}

export function estimateTextWidthPx(text: string, fontPx: number): number {
  let em = 0;
  for (const character of text) {
    if (/[ㄱ-힝一-鿿]/.test(character)) em += 1;
    else if (/[A-Z]/.test(character)) em += 0.68;
    else em += 0.56;
  }
  return em * fontPx;
}

/**
 * Greedy collision-free label placement in data coordinates.
 *
 * Candidates are tried in priority order, first above the marker then below;
 * a label whose box would overlap an already placed one is dropped. Pixel
 * scales come from the plot's axis ranges and container size, so the result
 * is only guaranteed at the default zoom.
 */
export function placeLabels(
  candidates: LabelCandidate[],
  pxPerUnitX: number,
  pxPerUnitY: number,
): PlacedLabel[] {
  if (!(pxPerUnitX > 0) || !(pxPerUnitY > 0)) return [];
  type Box = { x0: number; x1: number; y0: number; y1: number };
  const overlaps = (left: Box, right: Box) => (
    left.x0 < right.x1 && right.x0 < left.x1 && left.y0 < right.y1 && right.y0 < left.y1
  );
  const placedBoxes: Box[] = [];
  const placed: PlacedLabel[] = [];

  [...candidates]
    .sort((left, right) => right.priority - left.priority)
    .forEach(candidate => {
      const widthPx = estimateTextWidthPx(candidate.text, candidate.fontPx);
      const heightPx = candidate.fontPx * 1.3;
      const centerX = candidate.x * pxPerUnitX;
      const baseY = candidate.y * pxPerUnitY;
      const offsetPx = candidate.anchorPx + heightPx / 2 + 2;

      for (const direction of [1, -1]) {
        const centerY = baseY + direction * offsetPx;
        const box: Box = {
          x0: centerX - widthPx / 2,
          x1: centerX + widthPx / 2,
          y0: centerY - heightPx / 2,
          y1: centerY + heightPx / 2,
        };
        if (placedBoxes.some(existing => overlaps(existing, box))) continue;
        placedBoxes.push(box);
        placed.push({
          id: candidate.id,
          x: candidate.x,
          y: centerY / pxPerUnitY,
          text: candidate.text,
        });
        return;
      }
    });

  return placed;
}

// ── Community hulls ───────────────────────────────────────────────────

export interface Point { x: number; y: number }

/** Convex hull (Andrew's monotone chain), counter-clockwise, no repeated end point. */
export function convexHull(points: Point[]): Point[] {
  const sorted = [...points].sort((left, right) => left.x - right.x || left.y - right.y);
  if (sorted.length < 3) return sorted;
  const cross = (o: Point, a: Point, b: Point) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lower: Point[] = [];
  sorted.forEach(point => {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], point) <= 0) lower.pop();
    lower.push(point);
  });
  const upper: Point[] = [];
  [...sorted].reverse().forEach(point => {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], point) <= 0) upper.pop();
    upper.push(point);
  });
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}

/**
 * SVG path string (data coordinates) for a padded convex hull, as Plotly's
 * `shape.type = 'path'` expects. Each hull vertex is pushed `padding` units
 * away from the hull centroid.
 */
export function hullPath(points: Point[], padding: number): string {
  const hull = convexHull(points);
  if (hull.length < 3) return '';
  const centroid = {
    x: hull.reduce((sum, point) => sum + point.x, 0) / hull.length,
    y: hull.reduce((sum, point) => sum + point.y, 0) / hull.length,
  };
  const padded = hull.map(point => {
    const dx = point.x - centroid.x;
    const dy = point.y - centroid.y;
    const length = Math.hypot(dx, dy) || 1;
    return { x: point.x + (dx / length) * padding, y: point.y + (dy / length) * padding };
  });
  return `M ${padded.map(point => `${point.x},${point.y}`).join(' L ')} Z`;
}
