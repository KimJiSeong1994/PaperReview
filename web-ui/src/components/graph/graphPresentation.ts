import type { GraphData, GraphEdge } from '../../types';

export type GraphMode = 'landscape' | 'neighborhood' | 'path';
export type GraphNodeLimit = 20 | 35 | 50;

export const graphEdgeKey = (source: string, target: string): string => (
  source < target ? `${source}--${target}` : `${target}--${source}`
);

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

  const assignedNodes = orderedGroups.flatMap(([, nodes]) => nodes);
  const graphCenter = {
    x: assignedNodes.reduce((sum, node) => sum + node.x, 0) / assignedNodes.length,
    y: assignedNodes.reduce((sum, node) => sum + node.y, 0) / assignedNodes.length,
  };
  const horizontalCenterScale = 0.96;
  const verticalCenterScale = 1.08;
  const communityCompaction = 0.88;

  const positionedById = new Map<string, { x: number; y: number }>();
  orderedGroups.forEach(([, communityNodes]) => {
    const centroidX = communityNodes.reduce((sum, node) => sum + node.x, 0) / communityNodes.length;
    const centroidY = communityNodes.reduce((sum, node) => sum + node.y, 0) / communityNodes.length;
    const centerX = graphCenter.x + (centroidX - graphCenter.x) * horizontalCenterScale;
    const centerY = graphCenter.y + (centroidY - graphCenter.y) * verticalCenterScale;

    communityNodes.forEach(node => {
      positionedById.set(String(node.id), {
        x: centerX + (node.x - centroidX) * communityCompaction,
        y: centerY + (node.y - centroidY) * communityCompaction,
      });
    });
  });

  return {
    ...graphData,
    nodes: graphData.nodes.map(node => {
      const position = positionedById.get(String(node.id));
      return position ? { ...node, ...position } : node;
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
