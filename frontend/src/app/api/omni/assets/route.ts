import { fetchJson, serviceBase } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

// 列 pipeline.assets（投后回传表单的素材选择器，roadmap E1）。
// KE 端点 pipeline_list_assets 已存在；这里 GET → POST 透传。
export async function GET(request: Request) {
  const url = new URL(request.url)
  const sku_id = url.searchParams.get('sku_id') || undefined
  const asset_type = url.searchParams.get('asset_type') || undefined
  const limit = Number(url.searchParams.get('limit') || '50')
  const base = serviceBase()
  try {
    const data = await fetchJson<Record<string, unknown>>(
      `${base.knowledge}/api/v1/mcp/exec/pipeline_list_assets`,
      { method: 'POST', body: JSON.stringify({ sku_id, asset_type, limit }) },
    )
    return Response.json({ success: true, data })
  } catch (e) {
    return Response.json({ success: false, error: (e as Error).message }, { status: 502 })
  }
}
