import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  deriveWorkbenchContext,
  synchronizeWorkbenchContext,
} from '@/lib/workbench-context'

vi.mock('node:fs', () => ({ readFileSync: () => 'x'.repeat(32) }))

const originalFetch = global.fetch
const originalHostTokenFile = process.env.OMNI_HOST_TOKEN_FILE
afterEach(() => {
  global.fetch = originalFetch
  if (originalHostTokenFile === undefined) delete process.env.OMNI_HOST_TOKEN_FILE
  else process.env.OMNI_HOST_TOKEN_FILE = originalHostTokenFile
  vi.restoreAllMocks()
})

describe('workbench context persistence', () => {
  it('derives stable opaque references from the committed route', () => {
    const context = deriveWorkbenchContext('/sku/soy-sauce', 'shop_id=tianmao&task_id=review')

    expect(context).toMatchObject({
      context_ref: 'context:workspace:active',
      workspace_ref: 'workspace:omni',
      sku_ref: 'sku:soy-sauce',
      shop_ref: 'shop:tianmao',
      task_ref: 'task:review',
      origin_surface_ref: 'ui_route:/sku/soy-sauce',
      evidence_refs: ['ui_route:/sku/soy-sauce'],
    })
    expect(JSON.stringify(context)).not.toContain('E:/')
    expect(deriveWorkbenchContext('/含中文')).toMatchObject({ origin_surface_ref: 'ui_route:/unknown' })
  })

  it('uses creation once and a complete CAS pair for later navigation', async () => {
    const calls: Array<{ url: string; body: Record<string, unknown> }> = []
    const fetcher = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      calls.push({ url: String(input), body })
      return Response.json({
        snapshot: {
          ...(body.context as object),
          schema_version: 1,
          snapshot_id: calls.length === 1 ? 'context:first' : 'context:second',
          revision: calls.length,
          permission_scope_hash: `sha256:${'a'.repeat(64)}`,
          created_at: '2026-08-09T00:00:00Z',
        },
        reused: false,
      })
    })
    const context = deriveWorkbenchContext('/workspace')

    await synchronizeWorkbenchContext(context, {
      current: { contextSnapshotId: null, contextRevisionNumber: null, agentSessionId: null },
      fetcher: fetcher as typeof fetch,
    })
    await synchronizeWorkbenchContext(deriveWorkbenchContext('/sku/one'), {
      current: {
        contextSnapshotId: 'context:first',
        contextRevisionNumber: 1,
        agentSessionId: 'session:one',
      },
      fetcher: fetcher as typeof fetch,
    })

    expect(calls[0].url).toBe('/api/omni/workbench/context')
    expect(calls[0].body).toMatchObject({ expected_snapshot_id: null, expected_revision: null })
    expect(calls[1].url).toBe('/api/omni/workbench/context/rebind')
    expect(calls[1].body).toMatchObject({
      expected_snapshot_id: 'context:first',
      expected_revision: 1,
      session_id: 'session:one',
    })
  })

  it('projects a successful CAS rebind to the Host current head', async () => {
    process.env.OMNI_HOST_TOKEN_FILE = 'fixture.token'
    const { POST } = await import('@/app/api/omni/workbench/context/rebind/route')
    const calls: string[] = []
    global.fetch = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      calls.push(url)
      if (url.includes('/api/v1/workbench-contexts/rebind')) {
        return Response.json({
          snapshot: { snapshot_id: 'context:second', revision: 2 },
          reused: false,
        })
      }
      if (url.endsWith('/context')) return Response.json({ context_snapshot_id: 'context:second' })
      throw new Error(`unexpected fetch ${url}`)
    }) as typeof fetch

    const response = await POST(new Request('http://localhost/api/omni/workbench/context/rebind', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: 'http://localhost' },
      body: JSON.stringify({
        context: deriveWorkbenchContext('/sku/one'),
        expected_snapshot_id: 'context:first',
        expected_revision: 1,
        session_id: 'session:one',
      }),
    }))

    const responseBody = await response.clone().json()
    expect(response.status, JSON.stringify({ responseBody, calls })).toBe(200)
    expect(calls.some((url) => url.endsWith('/sessions/session%3Aone/context'))).toBe(true)
  })
})
