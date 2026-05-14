'use client'
import { useEffect, useRef, useState, useCallback } from 'react'
import type {
  ChatMessage, SessionState,
  WsClientMessage, WsServerMessage,
} from '@/lib/agent-chat/types'

interface UseAgentChatResult {
  connected: boolean
  session: SessionState | null
  messages: ChatMessage[]
  running: boolean
  error: string | null
  sendPrompt: (prompt: string) => void
  cancel: () => void
  decideGate: (shortId: string, decision: 'approved' | 'rejected', note?: string) => void
}

export function useAgentChat(sessionId: string | null): UseAgentChatResult {
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const [session, setSession] = useState<SessionState | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!sessionId) return
    const proto = typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = typeof window !== 'undefined' ? window.location.host : 'localhost:3000'
    const ws = new WebSocket(`${proto}//${host}/ws/agent-chat`)
    wsRef.current = ws
    ws.onopen = () => {
      setConnected(true)
      ws.send(JSON.stringify({ kind: 'open_session', session_id: sessionId } satisfies WsClientMessage))
    }
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data) as WsServerMessage
      if (msg.kind === 'session_opened') {
        setSession(msg.session)
        setMessages(msg.history)
      } else if (msg.kind === 'chunk') {
        setMessages((prev) => mergeMessage(prev, msg.message))
      } else if (msg.kind === 'task_done') {
        setRunning(false)
      } else if (msg.kind === 'human_gate_new') {
        const gateMsg: ChatMessage = {
          id: `gate-${msg.gate.short_id}`,
          session_id: msg.session_id,
          role: 'human_gate',
          gate_short_id: msg.gate.short_id,
          gate_summary: msg.gate.summary,
          gate_decision: 'pending',
          created_at: new Date().toISOString(),
        }
        setMessages((prev) => [...prev, gateMsg])
      } else if (msg.kind === 'error') {
        setError(msg.error + (msg.detail ? `: ${msg.detail}` : ''))
        setRunning(false)
      }
    }
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setError('websocket_error')
    return () => {
      ws.close()
    }
  }, [sessionId])

  const sendPrompt = useCallback((prompt: string) => {
    if (!wsRef.current || wsRef.current.readyState !== 1 || !sessionId) return
    setRunning(true)
    setError(null)
    setMessages((prev) => [
      ...prev,
      { id: `local-${Date.now()}`, session_id: sessionId, role: 'user', text: prompt, created_at: new Date().toISOString() },
    ])
    wsRef.current.send(JSON.stringify({ kind: 'send_prompt', session_id: sessionId, prompt } satisfies WsClientMessage))
  }, [sessionId])

  const cancel = useCallback(() => {
    if (!wsRef.current || !sessionId) return
    wsRef.current.send(JSON.stringify({ kind: 'cancel', session_id: sessionId } satisfies WsClientMessage))
    setRunning(false)
  }, [sessionId])

  const decideGate = useCallback((shortId: string, decision: 'approved' | 'rejected', note?: string) => {
    if (!wsRef.current) return
    wsRef.current.send(JSON.stringify({ kind: 'human_gate_decide', short_id: shortId, decision, note } satisfies WsClientMessage))
    setMessages((prev) => prev.map((m) => (m.gate_short_id === shortId ? { ...m, gate_decision: decision } : m)))
  }, [])

  return { connected, session, messages, running, error, sendPrompt, cancel, decideGate }
}

function mergeMessage(prev: ChatMessage[], incoming: ChatMessage): ChatMessage[] {
  if (incoming.role === 'tool_result' && incoming.tool_use_id) {
    const callIdx = prev.findIndex((m) => m.role === 'tool_call' && m.tool_use_id === incoming.tool_use_id)
    if (callIdx >= 0) {
      const next = [...prev]
      next[callIdx] = { ...next[callIdx], tool_status: 'completed' }
      return [...next, incoming]
    }
  }
  return [...prev, incoming]
}
