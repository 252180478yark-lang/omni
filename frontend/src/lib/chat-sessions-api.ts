import type { ChatMessage, ImageResult, SourceRef, VideoResult, RetrievalMeta, OutputMode } from '@/stores/chatStore'

export interface ChatSessionMeta {
  id: string
  title: string
  kb_ids: string[]
  provider: string | null
  model: string | null
  persona_id: string | null
  message_count: number
  last_message_at: string | null
  created_at: string
  updated_at: string
}

interface RawMessage {
  id: number
  session_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  output_mode: string | null
  sources: SourceRef[] | null
  retrieval: RetrievalMeta | null
  images: ImageResult[] | null
  video: VideoResult | null
  created_at: string
}

async function parse<T>(res: Response): Promise<T> {
  const json = await res.json()
  if (!res.ok || json?.success === false) {
    throw new Error(json?.error || json?.message || `HTTP ${res.status}`)
  }
  return json.data as T
}

export async function listSessions(params: { search?: string; limit?: number; offset?: number } = {}): Promise<ChatSessionMeta[]> {
  const qs = new URLSearchParams()
  if (params.search) qs.set('search', params.search)
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.offset) qs.set('offset', String(params.offset))
  const url = `/api/omni/chat/sessions${qs.toString() ? `?${qs.toString()}` : ''}`
  const res = await fetch(url, { cache: 'no-store' })
  return parse<ChatSessionMeta[]>(res)
}

export async function upsertSession(payload: {
  session_id: string
  title?: string
  kb_ids?: string[]
  provider?: string | null
  model?: string | null
  persona_id?: string | null
}): Promise<ChatSessionMeta> {
  const res = await fetch('/api/omni/chat/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return parse<ChatSessionMeta>(res)
}

export async function renameSession(id: string, title: string): Promise<ChatSessionMeta> {
  const res = await fetch(`/api/omni/chat/sessions/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  return parse<ChatSessionMeta>(res)
}

export async function deleteSession(id: string): Promise<void> {
  const res = await fetch(`/api/omni/chat/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
  await parse(res)
}

export async function loadSessionMessages(
  id: string,
): Promise<{ session: ChatSessionMeta; messages: ChatMessage[] }> {
  const res = await fetch(`/api/omni/chat/sessions/${encodeURIComponent(id)}/messages`, {
    cache: 'no-store',
  })
  const raw = await parse<{ session: ChatSessionMeta; messages: RawMessage[] }>(res)

  const messages: ChatMessage[] = raw.messages
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .map<ChatMessage>((m) => ({
      id: `srv-${m.id}`,
      role: m.role as 'user' | 'assistant',
      content: m.content,
      outputMode: (m.output_mode as OutputMode | null) || undefined,
      sources: m.sources || undefined,
      retrieval: m.retrieval || undefined,
      images: m.images || undefined,
      video: m.video || undefined,
      timestamp: Date.parse(m.created_at) || Date.now(),
      loading: false,
    }))
  return { session: raw.session, messages }
}

export async function appendMessageToSession(
  sessionId: string,
  payload: {
    role: 'user' | 'assistant' | 'system'
    content: string
    output_mode?: string | null
    sources?: SourceRef[] | null
    retrieval?: RetrievalMeta | null
    images?: ImageResult[] | null
    video?: VideoResult | null
    ensure_kb_ids?: string[]
    ensure_provider?: string | null
    ensure_model?: string | null
    ensure_persona_id?: string | null
  },
): Promise<void> {
  const res = await fetch(`/api/omni/chat/sessions/${encodeURIComponent(sessionId)}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  await parse(res)
}
