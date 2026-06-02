/**
 * @vitest-environment happy-dom
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useAgentChat } from '@/hooks/useAgentChat'

class MockWebSocket {
  static instances: MockWebSocket[] = []
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []
  constructor(public url: string) {
    MockWebSocket.instances.push(this)
    setTimeout(() => {
      this.readyState = 1
      this.onopen?.()
    }, 10)
  }
  send(data: string) { this.sent.push(data) }
  close() { this.readyState = 3; this.onclose?.() }
  emit(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }) }
}

beforeEach(() => {
  MockWebSocket.instances = []
  ;(global as unknown as { WebSocket: typeof MockWebSocket }).WebSocket = MockWebSocket
})

describe('useAgentChat', () => {
  it('connects to ws/agent-chat on mount', async () => {
    const { result } = renderHook(() => useAgentChat('sess-1'))
    await waitFor(() => expect(result.current.connected).toBe(true))
    expect(MockWebSocket.instances[0].url).toContain('/ws/agent-chat')
  })

  it('sends open_session after connect', async () => {
    renderHook(() => useAgentChat('sess-1'))
    await waitFor(() => expect(MockWebSocket.instances[0].sent.length).toBeGreaterThan(0))
    const sent = JSON.parse(MockWebSocket.instances[0].sent[0])
    expect(sent.kind).toBe('open_session')
    expect(sent.session_id).toBe('sess-1')
  })

  it('appends incoming chunk to messages', async () => {
    const { result } = renderHook(() => useAgentChat('sess-1'))
    await waitFor(() => expect(result.current.connected).toBe(true))
    act(() => {
      MockWebSocket.instances[0].emit({
        kind: 'chunk',
        session_id: 'sess-1',
        message: {
          id: 'm1', session_id: 'sess-1', role: 'assistant', text: 'hello',
          created_at: '2026-05-15T10:00:00Z',
        },
      })
    })
    expect(result.current.messages).toHaveLength(1)
    expect(result.current.messages[0].text).toBe('hello')
  })

  it('sendPrompt sends ws message and clears input', async () => {
    const { result } = renderHook(() => useAgentChat('sess-1'))
    await waitFor(() => expect(result.current.connected).toBe(true))
    act(() => result.current.sendPrompt('查 SKU'))
    const last = JSON.parse(MockWebSocket.instances[0].sent[MockWebSocket.instances[0].sent.length - 1])
    expect(last.kind).toBe('send_prompt')
    expect(last.prompt).toBe('查 SKU')
  })
})
