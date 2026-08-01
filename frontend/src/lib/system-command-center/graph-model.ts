import type { SystemGraphEdge, SystemGraphNode, SystemGraphSnapshot } from './runtime-model'

export const GRAPH_STATUSES = ['planned', 'healthy', 'broken', 'unknown', 'deprecated', 'verified_not_delivered'] as const
export type GraphDisplayStatus = typeof GRAPH_STATUSES[number]

export interface GraphModel {
  snapshotId: string
  generatedAt?: string
  nodes: SystemGraphNode[]
  edges: SystemGraphEdge[]
  byId: Map<string, SystemGraphNode>
  outgoing: Map<string, SystemGraphEdge[]>
  incoming: Map<string, SystemGraphEdge[]>
  roots: SystemGraphNode[]
  orphans: SystemGraphNode[]
  partial: boolean
  unavailableSources: string[]
}

export function graphDisplayStatus(node: SystemGraphNode): GraphDisplayStatus {
  if (node.state.existence === 'planned') return 'planned'
  if (node.state.existence === 'unknown' || node.state.evidence === 'unknown') return 'unknown'
  if (node.state.lifecycle === 'deprecated' || node.state.existence === 'removed') return 'deprecated'
  if (node.state.health === 'broken' || node.state.health === 'unhealthy' || node.state.health === 'failed') return 'broken'
  if (node.state.health === 'verified_not_delivered' || node.attrs?.delivery_status === 'verified_not_delivered') return 'verified_not_delivered'
  return 'healthy'
}

export function buildGraphModel(snapshot: SystemGraphSnapshot): GraphModel {
  const nodes = [...(snapshot.content.nodes || [])].sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
  const known = new Set(nodes.map((node) => node.id))
  const edges = [...(snapshot.content.edges || [])]
    .filter((edge) => known.has(edge.source) && known.has(edge.target))
    .sort((a, b) => a.id.localeCompare(b.id))
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const outgoing = new Map<string, SystemGraphEdge[]>()
  const incoming = new Map<string, SystemGraphEdge[]>()
  for (const node of nodes) {
    outgoing.set(node.id, [])
    incoming.set(node.id, [])
  }
  for (const edge of edges) {
    outgoing.get(edge.source)?.push(edge)
    incoming.get(edge.target)?.push(edge)
  }
  const roots = nodes.filter((node) => (incoming.get(node.id)?.length || 0) === 0)
  const orphans = nodes.filter((node) => (incoming.get(node.id)?.length || 0) + (outgoing.get(node.id)?.length || 0) === 0)
  const unavailableSources = (snapshot.content.source_results || [])
    .filter((source) => source.status !== 'success')
    .map((source) => `${source.collector_id}:${source.status}`)
  return {
    snapshotId: snapshot.snapshot_id,
    generatedAt: snapshot.generated_at_utc,
    nodes,
    edges,
    byId,
    outgoing,
    incoming,
    roots: roots.length ? roots : nodes.slice(0, 1),
    orphans,
    partial: unavailableSources.length > 0,
    unavailableSources,
  }
}

export function pathToNode(model: GraphModel, nodeId: string): string[] {
  const result = [nodeId]
  const seen = new Set(result)
  let current = nodeId
  while ((model.incoming.get(current)?.length || 0) > 0) {
    const edge = model.incoming.get(current)?.[0]
    if (!edge || seen.has(edge.source)) break
    result.unshift(edge.source)
    seen.add(edge.source)
    current = edge.source
  }
  return result
}
