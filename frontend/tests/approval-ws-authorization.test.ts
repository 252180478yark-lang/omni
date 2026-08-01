import { afterEach, describe, expect, it, vi } from 'vitest'

const redisHarness = vi.hoisted(() => ({
  handlers: new Map<string, (...args: unknown[]) => void>(),
}))

vi.mock('ioredis', () => ({
  default: class RedisFixture {
    subscribe(): Promise<void> {
      return Promise.resolve()
    }

    on(event: string, handler: (...args: unknown[]) => void): void {
      redisHarness.handlers.set(event, handler)
    }
  },
}))

vi.mock('pg', () => ({
  Pool: class PoolFixture {},
}))

import { attachWsHandler } from '@/lib/agent-chat/ws-handler'

class FakeWebSocket {
  readyState = 1
  closed = false
  readonly sent: string[] = []
  private readonly handlers = new Map<string, (...args: unknown[]) => unknown>()

  on(event: string, handler: (...args: unknown[]) => unknown): void {
    this.handlers.set(event, handler)
  }

  send(payload: string): void {
    this.sent.push(payload)
  }

  async message(payload: object): Promise<void> {
    await this.handlers.get('message')?.(JSON.stringify(payload))
  }

  close(): void {
    this.closed = true
    this.readyState = 3
    this.handlers.get('close')?.()
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('approval WebSocket authorization', () => {
  it('never broadcasts to or accepts a gate decision from an unauthenticated connection', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const anonymous = new FakeWebSocket()
    attachWsHandler(anonymous as never, null)
    await Promise.resolve()

    redisHarness.handlers.get('message')?.(
      'mcp.human_gates.new',
      JSON.stringify({ short_id: 'gate-1', tool_name: 'fixture', summary: 'pending' }),
    )
    expect(anonymous.sent.map((item) => JSON.parse(item))).toContainEqual({
      kind: 'error',
      error: 'authentication_required',
    })
    expect(anonymous.closed).toBe(true)

    await anonymous.message({
      kind: 'human_gate_decide',
      short_id: 'gate-1',
      decision: 'approve',
      note: '',
    })
    expect(fetchMock).not.toHaveBeenCalled()
    anonymous.close()
  })
})
