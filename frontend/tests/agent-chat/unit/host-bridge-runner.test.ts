import { describe, expect, it, vi } from 'vitest'

import { startHostBridgeRunner } from '@/lib/agent-chat/host-bridge-runner'

vi.mock('node:fs', () => ({ readFileSync: () => 'x'.repeat(32) }))

describe('host bridge runner', () => {
  it('uses authenticated provider-neutral session and cursor APIs', async () => {
    const previousTokenFile = process.env.OMNI_HOST_TOKEN_FILE
    process.env.OMNI_HOST_TOKEN_FILE = 'fixture.token'
    const calls: string[] = []
    const originalFetch = global.fetch
    global.fetch = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      calls.push(url)
      if (url.endsWith('/sessions')) return Response.json({ session_id: 'session:one' })
      if (url.endsWith('/runs')) return Response.json({ run_id: 'run:one' })
      return Response.json({ status: 'completed', next_cursor: 2, events: [
        { cursor: 1, kind: 'provider.chunk', payload: { chunk: { type: 'thread.started', thread_id: 'runner:real' } } },
        { cursor: 2, kind: 'provider.chunk', payload: { chunk: { type: 'turn.completed', usage: { input_tokens: 1, output_tokens: 2 } } } },
      ] })
    }) as typeof fetch
    try {
      const runner = startHostBridgeRunner({
        sessionId: 'session:one', provider: 'codex', traceId: 'trace:one', executionId: 'execution:one', parentSpanId: 'ws:one', projectDir: 'E:/agent/omni',
        prompt: 'hello', mcpConfigPath: 'unused',
      })
      const chunks: string[] = []
      runner.on('chunk', (chunk: { type: string }) => chunks.push(chunk.type))
      await new Promise<void>((resolve, reject) => { runner.on('exit', () => resolve()); runner.on('error', reject) })
      expect(chunks).toEqual(['system', 'result'])
      expect(calls.some((url) => url.includes('/runs/run%3Aone/events?cursor=0'))).toBe(true)
    } finally {
      global.fetch = originalFetch
      if (previousTokenFile === undefined) delete process.env.OMNI_HOST_TOKEN_FILE
      else process.env.OMNI_HOST_TOKEN_FILE = previousTokenFile
    }
  })

  it('falls back only before a host run is accepted', async () => {
    const previousTokenFile = process.env.OMNI_HOST_TOKEN_FILE
    process.env.OMNI_HOST_TOKEN_FILE = 'fixture.token'
    const originalFetch = global.fetch
    global.fetch = vi.fn(async () => new Response('{}', { status: 503 })) as typeof fetch
    const fallback = { proc: { killed: false }, cancel: vi.fn(), on: vi.fn().mockReturnThis() }
    try {
      startHostBridgeRunner({ sessionId: 'session:one', provider: 'claude', traceId: 'trace:one', executionId: 'execution:one', parentSpanId: 'ws:one', projectDir: 'E:/agent/omni', prompt: 'hello', mcpConfigPath: 'unused', fallbackFactory: () => fallback as never })
      await vi.waitFor(() => expect(fallback.on).toHaveBeenCalled())
    } finally {
      global.fetch = originalFetch
      if (previousTokenFile === undefined) delete process.env.OMNI_HOST_TOKEN_FILE
      else process.env.OMNI_HOST_TOKEN_FILE = previousTokenFile
    }
  })

  it('does not risk duplicate execution after run submission becomes ambiguous', async () => {
    const previousTokenFile = process.env.OMNI_HOST_TOKEN_FILE
    process.env.OMNI_HOST_TOKEN_FILE = 'fixture.token'
    const originalFetch = global.fetch
    let calls = 0
    global.fetch = vi.fn(async () => {
      calls += 1
      if (calls === 1) return Response.json({ session_id: 'session:one' })
      throw new Error('response_lost_after_possible_acceptance')
    }) as typeof fetch
    const fallback = { proc: { killed: false }, cancel: vi.fn(), on: vi.fn().mockReturnThis() }
    try {
      const runner = startHostBridgeRunner({
        sessionId: 'session:one', provider: 'codex', traceId: 'trace:one', executionId: 'execution:one',
        parentSpanId: 'ws:one', projectDir: 'E:/agent/omni', prompt: 'hello', mcpConfigPath: 'unused',
        fallbackFactory: () => fallback as never,
      })
      const error = await new Promise<Error>((resolve) => runner.on('error', resolve))
      expect(error.message).toBe('response_lost_after_possible_acceptance')
      expect(fallback.on).not.toHaveBeenCalled()
    } finally {
      global.fetch = originalFetch
      if (previousTokenFile === undefined) delete process.env.OMNI_HOST_TOKEN_FILE
      else process.env.OMNI_HOST_TOKEN_FILE = previousTokenFile
    }
  })
})
