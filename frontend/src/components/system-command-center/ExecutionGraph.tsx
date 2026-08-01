'use client'

import type { RuntimeEvent, SystemGraphSnapshot } from '@/lib/system-command-center/runtime-model'

interface DisplayNode {
  id: string
  label: string
  layer: 'planned' | 'fact' | 'runtime' | 'gap'
  status: string
}

export function ExecutionGraph({ snapshot, events, activeIndex }: {
  snapshot: SystemGraphSnapshot | null
  events: RuntimeEvent[]
  activeIndex: number
}) {
  const visibleEvents = activeIndex < 0 ? [] : events.slice(0, activeIndex + 1)
  const facts = new Map((snapshot?.content.nodes || []).map((node) => [node.id, node]))
  const nodes = new Map<string, DisplayNode>()
  for (const node of snapshot?.content.nodes || []) {
    if (node.state.existence === 'planned') nodes.set(node.id, { id: node.id, label: node.label, layer: 'planned', status: node.state.health })
  }
  for (const event of visibleEvents) {
    const id = event.node_id || `gap:${event.source}:${event.event_id}`
    const fact = event.node_id ? facts.get(event.node_id) : undefined
    nodes.set(id, {
      id,
      label: fact?.label || event.node_id || '未映射 gap',
      layer: event.node_id ? (fact ? 'runtime' : 'gap') : 'gap',
      status: event.status,
    })
  }
  const selected = Array.from(nodes.values()).slice(-14)
  const selectedIds = new Set(selected.map((node) => node.id))
  const factEdges = (snapshot?.content.edges || []).filter((edge) => selectedIds.has(edge.source) && selectedIds.has(edge.target))
  const runtimeEdges: Array<{ id: string; source: string; target: string }> = []
  const bySpan = new Map<string, RuntimeEvent>()
  for (const event of visibleEvents) if (event.span_id) bySpan.set(event.span_id, event)
  for (const event of visibleEvents) {
    if (!event.parent_span_id || !event.node_id) continue
    const parent = bySpan.get(event.parent_span_id)
    if (parent?.node_id && parent.node_id !== event.node_id) {
      runtimeEdges.push({ id: `runtime:${event.source}:${event.event_id}`, source: parent.node_id, target: event.node_id })
    }
  }
  const width = Math.max(720, selected.length * 150)
  const position = new Map(selected.map((node, index) => [node.id, { x: 75 + index * 150, y: 90 + (index % 2) * 90 }]))
  const active = visibleEvents.at(-1)?.node_id || (visibleEvents.at(-1) ? `gap:${visibleEvents.at(-1)!.source}:${visibleEvents.at(-1)!.event_id}` : '')

  return <div className="overflow-x-auto rounded-lg border bg-slate-950 p-2" aria-label="计划事实运行图">
    <svg role="img" aria-label="实际执行路径图" viewBox={`0 0 ${width} 270`} className="h-64 min-w-[720px] w-full">
      {factEdges.map((edge) => {
        const source = position.get(edge.source); const target = position.get(edge.target)
        if (!source || !target) return null
        return <line key={edge.id} x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke="#64748b" strokeWidth="2" strokeDasharray={edge.state.existence === 'planned' ? '7 6' : undefined} />
      })}
      {runtimeEdges.map((edge) => {
        const source = position.get(edge.source); const target = position.get(edge.target)
        if (!source || !target) return null
        return <line key={edge.id} x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke="#a78bfa" strokeWidth="4" />
      })}
      {selected.map((node) => {
        const point = position.get(node.id)!
        const colour = node.layer === 'gap' ? '#fb7185' : node.layer === 'planned' ? '#60a5fa' : node.status === 'failed' ? '#fb7185' : '#8b5cf6'
        return <g key={node.id} data-layer={node.layer} data-active={node.id === active ? 'true' : 'false'}>
          <circle cx={point.x} cy={point.y} r={node.id === active ? 28 : 22} fill={colour} fillOpacity={node.layer === 'planned' ? 0.25 : 0.9} stroke={node.id === active ? '#f8fafc' : colour} strokeWidth={node.id === active ? 4 : 2} strokeDasharray={node.layer === 'planned' || node.layer === 'gap' ? '5 4' : undefined} />
          <text x={point.x} y={point.y + 43} textAnchor="middle" fill="#e2e8f0" fontSize="11">{node.label.slice(0, 20)}</text>
          <title>{`${node.layer} · ${node.label} · ${node.status}`}</title>
        </g>
      })}
      {!selected.length ? <text x="30" y="50" fill="#94a3b8" fontSize="14">暂无已观测路径；不会补画节点或连线。</text> : null}
    </svg>
    <div className="flex flex-wrap gap-4 px-2 pb-2 text-xs text-slate-300">
      <span>虚线蓝：planned</span><span>灰线：fact</span><span>紫线：runtime</span><span>红色虚线：gap / unmapped</span>
    </div>
  </div>
}
