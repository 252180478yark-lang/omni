import { fetchJson, serviceBase } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

// 按 asset_id 反查全链路（roadmap E2 榜单下钻：这条素材从哪个 SKU/卖点/人群/脚本来的）。
export async function GET(request: Request) {
  const url = new URL(request.url)
  const asset_id = url.searchParams.get('asset_id')
  if (!asset_id) {
    return Response.json({ success: false, error: 'asset_id required' }, { status: 400 })
  }
  const base = serviceBase()
  try {
    const data = await fetchJson<Record<string, unknown>>(
      `${base.knowledge}/api/v1/mcp/exec/pipeline_get_asset_lineage`,
      { method: 'POST', body: JSON.stringify({ asset_id }) },
    )
    return Response.json({ success: true, data })
  } catch (e) {
    return Response.json({ success: false, error: (e as Error).message }, { status: 502 })
  }
}
