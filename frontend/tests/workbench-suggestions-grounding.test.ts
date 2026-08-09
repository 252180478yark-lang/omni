import { afterEach, describe, expect, it, vi } from 'vitest'

const originalFetch = global.fetch
afterEach(() => {
  global.fetch = originalFetch
  vi.restoreAllMocks()
})

describe('grounded workbench suggestions', () => {
  it('returns observations with evidence and never invents a write operation', async () => {
    const { POST } = await import('@/app/api/omni/workbench/suggestions/route')
    global.fetch = vi.fn(async () => Response.json({
      snapshot_id: 'snapshot:one',
      generated_at_utc: '2026-08-09T00:00:00Z',
      content: {
        nodes: [{
          id: 'service:host-bridge', kind: 'service', key: 'host-bridge', label: 'Host Bridge',
          state: { existence: 'observed', health: 'healthy', lifecycle: 'active', evidence: 'code' },
          sources: ['collector:runtime'],
        }],
        edges: [],
      },
    })) as typeof fetch

    const response = await POST(new Request('http://localhost/api/omni/workbench/suggestions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: 'http://localhost' },
      body: JSON.stringify({ question: '现在能否运行？' }),
    }))
    const card = await response.json()

    expect(response.status).toBe(200)
    expect(card.evidenceState).toBe('sufficient')
    expect(card.observations).toHaveLength(1)
    expect(card.evidenceRefs[0]).toMatchObject({ id: 'service:host-bridge' })
    expect(card.toolPlan).not.toContain('operation.create')
    expect(card.approvalRequired).toBe(false)
  })

  it('is fail-closed when the fact snapshot is empty', async () => {
    const { POST } = await import('@/app/api/omni/workbench/suggestions/route')
    global.fetch = vi.fn(async () => Response.json({
      snapshot_id: 'snapshot:empty',
      content: { nodes: [], edges: [] },
    })) as typeof fetch

    const response = await POST(new Request('http://localhost/api/omni/workbench/suggestions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: 'http://localhost' },
      body: JSON.stringify({ question: '下一步是什么？' }),
    }))
    const card = await response.json()

    expect(card).toMatchObject({ evidenceState: 'insufficient', riskLevel: 'R0' })
    expect(card.observations).toEqual([])
    expect(card.toolPlan).not.toContain('operation.create')
  })
})
