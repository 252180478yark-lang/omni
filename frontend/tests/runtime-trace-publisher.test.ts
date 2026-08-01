import { describe, expect, it, vi } from 'vitest'

import { createRuntimeTracePublisher } from '@/lib/agent-chat/runtime-trace'

const event = {
  source: 'agent.websocket' as const, event_id: 'ws:execution:one:0', trace_id: 'trace:one', execution_id: 'execution:one',
  span_id: 'ws:execution:one', parent_span_id: null, session_id: 'session:one', sequence: 0,
  event_type: 'started' as const, status: 'running' as const, span_kind: 'websocket' as const, node_id: 'ui_route:/chat', read_write: 'none' as const,
  payload: { message_kind: 'send_prompt' },
}

describe('explicit websocket runtime publisher', () => {
  it('posts a redacted event under the stable trace path when a service identity exists', async () => {
    const fetchImpl = vi.fn(async () => new Response('{}', { status: 200 }))
    const publisher = createRuntimeTracePublisher({ baseUrl: 'http://ke.test', token: 'x'.repeat(24), fetchImpl })
    expect(await publisher.publish(event)).toBe(true)
    const [url, init] = (fetchImpl.mock.calls as unknown as Array<[string, RequestInit]>)[0]
    expect(url).toBe('http://ke.test/api/v1/runtime-traces/trace%3Aone/events')
    expect(JSON.parse(String(init!.body)).payload).toEqual({ message_kind: 'send_prompt' })
    expect(new Headers(init!.headers).get('Authorization')).toBe(`Bearer ${'x'.repeat(24)}`)
  })

  it('does not pretend to publish when host identity is unavailable', async () => {
    const publisher = createRuntimeTracePublisher({ token: null, fetchImpl: vi.fn() })
    expect(await publisher.publish(event)).toBe(false)
  })

  it('retries transient failure without reordering queued events', async () => {
    const attempts: string[] = []
    let firstFailed = false
    const fetchImpl = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const eventId = JSON.parse(String(init?.body)).event_id as string
      attempts.push(eventId)
      if (!firstFailed) {
        firstFailed = true
        return new Response('{}', { status: 503 })
      }
      return new Response('{}', { status: 200 })
    }) as typeof fetch
    const publisher = createRuntimeTracePublisher({ token: 'x'.repeat(24), fetchImpl })
    const second = { ...event, event_id: 'ws:execution:one:1', sequence: 1 }
    const results = await Promise.all([publisher.publish(event), publisher.publish(second)])
    expect(results).toEqual([true, true])
    expect(attempts).toEqual([event.event_id, event.event_id, second.event_id])
    expect(await publisher.flush()).toBe(true)
  })
})
