import type { RuntimeEvent, RuntimeMode } from './runtime-model'

export interface RuntimeTimeline {
  mode: RuntimeMode
  cursor: number
  events: RuntimeEvent[]
  gaps: number
}

export function reduceRuntimeEvents(previous: RuntimeTimeline, incoming: RuntimeEvent[], now = Date.now()): RuntimeTimeline {
  const unique = new Map(previous.events.map((event) => [`${event.source}:${event.event_id}`, event]))
  for (const event of incoming) unique.set(`${event.source}:${event.event_id}`, event)
  const sequenceCounts = new Map<number, number>()
  for (const event of Array.from(unique.values())) {
    if (event.sequence !== null) sequenceCounts.set(event.sequence, (sequenceCounts.get(event.sequence) || 0) + 1)
  }
  const events = Array.from(unique.values())
    .map((event) => ({
      ...event,
      ordering: event.sequence === null || (sequenceCounts.get(event.sequence) || 0) > 1 ? 'ordering_unknown' : event.ordering,
    }))
    .sort((left, right) => {
      if (left.sequence !== null && right.sequence !== null && left.sequence !== right.sequence) return left.sequence - right.sequence
      if (left.sequence !== null && right.sequence === null) return -1
      if (left.sequence === null && right.sequence !== null) return 1
      return new Date(left.observed_at).getTime() - new Date(right.observed_at).getTime() || left.cursor - right.cursor
    })
  const newest = events.at(-1)
  const gaps = events.filter((event) => event.event_type === 'gap' || event.node_id === null || event.ordering === 'ordering_unknown').length
  const age = newest ? now - new Date(newest.received_at).getTime() : 0
  const mode: RuntimeMode = events.some((event) => event.status === 'failed') ? 'failed'
    : events.some((event) => event.status === 'cancelled') ? 'cancelled'
      : gaps > 0 ? 'partial'
        : newest?.status === 'completed' ? 'completed'
          : age > 5_000 ? 'delayed' : 'live'
  return { mode, cursor: Math.max(previous.cursor, ...events.map((event) => event.cursor), 0), events, gaps }
}

export function factualExplanation(event: RuntimeEvent): string {
  const node = event.node_id || '未映射节点'
  const input = event.payload_schema.length ? `字段：${event.payload_schema.join('、')}` : '未记录字段 schema'
  const io = event.read_write === 'none' ? '未观测到读写' : `观测到${event.read_write === 'read_write' ? '读写' : event.read_write === 'read' ? '读取' : '写入'}`
  if (event.node_id === null || event.event_type === 'gap') return `此处没有足够证据：${input}；事件已标为缺口，系统没有补画路径。`
  return `已观测到 ${node}：状态为 ${event.status}，${io}；${input}。下一跳只会在后续真实事件到达后显示。`
}
