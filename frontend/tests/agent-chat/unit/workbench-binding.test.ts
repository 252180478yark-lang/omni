import { describe, expect, it, vi } from 'vitest'

import { startHostBridgeRunner } from '@/lib/agent-chat/host-bridge-runner'

vi.mock('node:fs', () => ({ readFileSync: () => 'x'.repeat(32) }))

describe('workbench agent binding', () => {
  it('sends only an opaque project identity and a complete context pair', async () => {
    process.env.OMNI_HOST_TOKEN_FILE = 'fixture.token'
    const bodies: unknown[] = []
    const originalFetch = global.fetch
    global.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (init?.body) bodies.push(JSON.parse(String(init.body)))
      if (url.endsWith('/sessions')) return Response.json({
        runner_session_id: null, requested_provider: 'codex', resolved_provider: 'codex',
        runner_mode: 'host', fallback_reason_code: null, accepted_at: null,
      })
      if (url.endsWith('/runs')) return Response.json({ run_id: 'run:binding' })
      return Response.json({ status: 'completed', next_cursor: 0, events: [] })
    }) as typeof fetch

    try {
      const runner = startHostBridgeRunner({
        sessionId: 'session:binding', provider: 'codex', traceId: 'trace:binding',
        executionId: 'execution:binding', parentSpanId: 'ws:binding', projectHandle: 'project:default',
        context: { context_snapshot_id: 'context:sku-a', context_revision: 7 },
        prompt: 'analyze', mcpConfigPath: 'unused',
      })
      await new Promise<void>((resolve, reject) => { runner.on('exit', () => resolve()); runner.on('error', reject) })

      expect(bodies[0]).toMatchObject({
        project_handle: 'project:default', context_snapshot_id: 'context:sku-a', context_revision: 7,
      })
      expect(bodies[0]).not.toHaveProperty('project_dir')
    } finally {
      global.fetch = originalFetch
      delete process.env.OMNI_HOST_TOKEN_FILE
    }
  })
})
