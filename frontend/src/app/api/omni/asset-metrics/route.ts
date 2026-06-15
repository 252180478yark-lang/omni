import { fetchJson, serviceBase } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

// 投后回传闭环（roadmap E1/E2）：
//   GET  → pipeline_list_asset_performance （"哪套内容真带货"榜数据源）
//   POST → record_ad_metrics （把测试投放真实数据写回素材血缘）
export async function GET(request: Request) {
  const url = new URL(request.url)
  const sku_id = url.searchParams.get('sku_id') || undefined
  const limit = Number(url.searchParams.get('limit') || '50')
  const base = serviceBase()
  try {
    const data = await fetchJson<Record<string, unknown>>(
      `${base.knowledge}/api/v1/mcp/exec/pipeline_list_asset_performance`,
      { method: 'POST', body: JSON.stringify({ sku_id, limit }) },
    )
    return Response.json({ success: true, data })
  } catch (e) {
    return Response.json({ success: false, error: (e as Error).message }, { status: 502 })
  }
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}))
  const base = serviceBase()
  try {
    const data = await fetchJson<Record<string, unknown>>(
      `${base.knowledge}/api/v1/mcp/exec/record_ad_metrics`,
      {
        method: 'POST',
        body: JSON.stringify({
          metrics: body.metrics || {},
          asset_id: body.asset_id || null,
          external_video_id: body.external_video_id || null,
          external_creative_id: body.external_creative_id || null,
          experiment_arm_id: body.experiment_arm_id || null,
          mark_published: body.mark_published !== false,
        }),
      },
    )
    return Response.json({ success: true, data })
  } catch (e) {
    return Response.json({ success: false, error: (e as Error).message }, { status: 502 })
  }
}
