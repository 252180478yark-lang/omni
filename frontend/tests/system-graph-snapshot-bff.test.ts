import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  delete process.env.OMNI_SYSTEM_GRAPH_TIMEOUT_MS
})

describe('system graph snapshot BFF', () => {
  it('uses the shared sixty-second cold-start budget and preserves the upstream response', async () => {
    const timeout = vi.spyOn(AbortSignal, 'timeout')
    const fetchMock = vi.fn(async () => Response.json({ snapshot_id: 'snapshot:one' }, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const { GET } = await import('@/app/api/omni/system-graph/snapshot/route')

    const response = await GET(new Request('http://localhost/api/omni/system-graph/snapshot'))

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ snapshot_id: 'snapshot:one' })
    expect(timeout).toHaveBeenCalledWith(60_000)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/system-graph/snapshot'),
      expect.objectContaining({ cache: 'no-store', signal: expect.any(AbortSignal) }),
    )
  })

  it('accepts a bounded override and keeps a real upstream failure explicit', async () => {
    process.env.OMNI_SYSTEM_GRAPH_TIMEOUT_MS = '45000'
    const timeout = vi.spyOn(AbortSignal, 'timeout')
    vi.stubGlobal('fetch', vi.fn(async () => { throw new DOMException('timed out', 'TimeoutError') }))
    const { GET } = await import('@/app/api/omni/system-graph/snapshot/route')

    const response = await GET(new Request('http://localhost/api/omni/system-graph/snapshot'))

    expect(response.status).toBe(502)
    expect(await response.json()).toMatchObject({ error: { source: 'frontend:runtime-trace' } })
    expect(timeout).toHaveBeenCalledWith(45_000)
  })

  it('falls back to sixty seconds for invalid configuration', async () => {
    const { systemGraphTimeoutMs } = await import('@/app/api/omni/system-graph/_graph-fetch')
    expect(systemGraphTimeoutMs('999')).toBe(60_000)
    expect(systemGraphTimeoutMs('120001')).toBe(60_000)
    expect(systemGraphTimeoutMs('not-a-number')).toBe(60_000)
  })
})
