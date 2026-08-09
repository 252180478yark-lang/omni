import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { GET as getAssetLineage } from '@/app/api/omni/asset-lineage/route'
import { GET as getAssetMetrics, POST as recordAssetMetrics } from '@/app/api/omni/asset-metrics/route'
import { GET as getAssets } from '@/app/api/omni/assets/route'
import { POST as reverseStoryboard } from '@/app/api/omni/mcp-exec/reverse-storyboard/route'

const fetchMock = vi.fn<(input: string | URL | Request, init?: RequestInit) => Promise<Response>>()

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function calledPath(index: number): string {
  return String(fetchMock.mock.calls[index]?.[0])
}

function calledBody(index: number): Record<string, unknown> {
  return JSON.parse(String(fetchMock.mock.calls[index]?.[1]?.body)) as Record<string, unknown>
}

beforeEach(() => {
  vi.stubEnv('KNOWLEDGE_ENGINE_URL', 'http://knowledge.test')
  fetchMock.mockReset()
  fetchMock.mockImplementation(async () => jsonResponse({ ok: true, source: 'canonical-operation' }))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('canonical tool-execution BFFs', () => {
  it('routes asset reads through registered operation IDs without changing public responses', async () => {
    const lineage = await getAssetLineage(new Request('http://localhost/api/omni/asset-lineage?asset_id=asset-1'))
    const metrics = await getAssetMetrics(new Request('http://localhost/api/omni/asset-metrics?sku_id=sku-1&limit=12'))
    const assets = await getAssets(new Request('http://localhost/api/omni/assets?sku_id=sku-1&asset_type=video&limit=7'))

    expect([lineage.status, metrics.status, assets.status]).toEqual([200, 200, 200])
    expect(calledPath(0)).toBe('http://knowledge.test/api/v1/mcp/execute/sku.asset-lineage.get')
    expect(calledBody(0)).toEqual({ asset_id: 'asset-1' })
    expect(calledPath(1)).toBe('http://knowledge.test/api/v1/mcp/execute/sku.asset-performance.list')
    expect(calledBody(1)).toEqual({ sku_id: 'sku-1', limit: 12 })
    expect(calledPath(2)).toBe('http://knowledge.test/api/v1/mcp/execute/sku.assets.list')
    expect(calledBody(2)).toEqual({ sku_id: 'sku-1', asset_type: 'video', limit: 7 })
    expect(await lineage.json()).toEqual({ success: true, data: { ok: true, source: 'canonical-operation' } })
  })

  it('preserves the ad-metrics write payload on the canonical operation', async () => {
    const response = await recordAssetMetrics(new Request('http://localhost/api/omni/asset-metrics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        asset_id: 'asset-2',
        metrics: { ctr: 0.21 },
        mark_published: false,
      }),
    }))

    expect(response.status).toBe(200)
    expect(calledPath(0)).toBe('http://knowledge.test/api/v1/mcp/execute/sku.ad-metrics.record')
    expect(calledBody(0)).toEqual({
      metrics: { ctr: 0.21 },
      asset_id: 'asset-2',
      external_video_id: null,
      external_creative_id: null,
      experiment_arm_id: null,
      mark_published: false,
    })
  })

  it('keeps the long-running reverse-storyboard proxy on its canonical operation', async () => {
    const response = await reverseStoryboard(new Request('http://localhost/api/omni/mcp-exec/reverse-storyboard', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_path: '/tmp/example.mp4' }),
    }))

    expect(response.status).toBe(200)
    expect(calledPath(0)).toBe('http://knowledge.test/api/v1/mcp/execute/video.storyboard.reverse')
    expect(calledBody(0)).toEqual({ video_path: '/tmp/example.mp4' })
    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBeInstanceOf(AbortSignal)
  })

  it('retains validation and upstream failure status semantics', async () => {
    const missing = await getAssetLineage(new Request('http://localhost/api/omni/asset-lineage'))
    expect(missing.status).toBe(400)
    expect(fetchMock).not.toHaveBeenCalled()

    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: false, error: 'unavailable' }, 503))
    const upstream = await getAssets(new Request('http://localhost/api/omni/assets'))
    expect(upstream.status).toBe(502)
    expect(await upstream.json()).toMatchObject({ success: false })
  })
})
