'use client'

import type {
  DebateParams,
  StreamChunk,
  DebateEvent,
  Session,
  ChatNode,
} from './types'

const BASE = '/api/tri-mind'

export const triMindApi = {
  async startDebate(
    params: DebateParams,
    onChunk: (chunk: StreamChunk) => void,
    onEvent: (event: DebateEvent) => void,
    signal?: AbortSignal
  ): Promise<void> {
    const res = await fetch(`${BASE}/debate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
      signal,
    })
    if (!res.ok) throw new Error(await res.text())
    if (!res.body) throw new Error('No response body')
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const obj = JSON.parse(line)
          if (obj.kind === 'event') {
            const rest = { ...obj }
            delete rest.kind
            onEvent(rest as DebateEvent)
          } else {
            onChunk(obj as StreamChunk)
          }
        } catch {
          // skip invalid lines
        }
      }
    }
  },

  stopGeneration(): void {
    // Abort is handled by the fetch signal
  },

  async newSession(): Promise<{ success: boolean; data?: Session }> {
    const res = await fetch(`${BASE}/sessions`, { method: 'POST' })
    return res.json()
  },

  async listSessions(): Promise<{ success: boolean; data?: Session[] }> {
    const res = await fetch(`${BASE}/sessions`)
    return res.json()
  },

  async loadSession(
    sessionId: string
  ): Promise<{ success: boolean; data?: { session: Session; nodes: ChatNode[] } }> {
    const res = await fetch(`${BASE}/sessions/${sessionId}`)
    return res.json()
  },

  async deleteSession(sessionId: string): Promise<{ success: boolean }> {
    const res = await fetch(`${BASE}/sessions/${sessionId}`, { method: 'DELETE' })
    return res.json()
  },

  async testConnection(params: {
    provider: string
    apiKey: string
    baseUrl?: string
    model: string
  }): Promise<{ success: boolean; data?: { ok: boolean; error?: string }; error?: string }> {
    const res = await fetch(`${BASE}/test-connection`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    })
    return res.json()
  },
}
