import { readFileSync } from 'node:fs'

export interface RuntimeTraceEventInput {
  source: 'agent.websocket'
  event_id: string
  trace_id: string
  execution_id: string
  span_id: string | null
  parent_span_id: string | null
  session_id: string
  sequence: number
  event_type: 'started' | 'completed' | 'failed' | 'cancelled' | 'retry' | 'gap' | 'annotation'
  status: 'running' | 'completed' | 'failed' | 'cancelled' | 'partial' | 'unknown'
  span_kind: 'websocket' | 'tool' | 'model'
  node_id: string | null
  read_write: 'none' | 'read' | 'write' | 'read_write'
  payload: Record<string, unknown>
}

type FetchLike = typeof fetch

function tokenFromFile(path = process.env.OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE?.trim() || ''): string | null {
  if (!path) return null
  try {
    const token = readFileSync(path, 'utf8').trim()
    return token.length >= 24 ? token : null
  } catch {
    return null
  }
}

export function createRuntimeTracePublisher(options: { baseUrl?: string; token?: string | null; fetchImpl?: FetchLike } = {}) {
  const baseUrl = options.baseUrl || process.env.KNOWLEDGE_ENGINE_URL || process.env.OMNI_KE_URL || 'http://localhost:8002'
  const token = options.token === undefined ? tokenFromFile() : options.token
  const fetchImpl = options.fetchImpl || fetch
  let queue: Promise<boolean> = Promise.resolve(true)
  const send = async (event: RuntimeTraceEventInput): Promise<boolean> => {
    if (!token) return false
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const response = await fetchImpl(`${baseUrl}/api/v1/runtime-traces/${encodeURIComponent(event.trace_id)}/events`, {
          method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(event), signal: AbortSignal.timeout(3000),
        })
        if (response.ok) return true
        if (response.status < 500) return false
      } catch {
        // One bounded retry preserves event order without hiding a collector gap.
      }
    }
    return false
  }
  return {
    enabled: Boolean(token),
    async publish(event: RuntimeTraceEventInput): Promise<boolean> {
      queue = queue.then(() => send(event), () => send(event))
      return queue
    },
    async flush(): Promise<boolean> { return queue },
  }
}
