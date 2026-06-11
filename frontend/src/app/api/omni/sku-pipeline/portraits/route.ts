import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

/**
 * 人群画像（step 3.5 产物）查询：
 * - body 带 portrait_id → 转 get 端点（单条全文 portrait_md）
 * - 否则 → list 端点（sku_id / audience_record_id / limit 过滤，返 preview 列表）
 */
export async function POST(request: Request) {
  const base = serviceBase()
  const body = await request.json()
  const endpoint = body?.portrait_id
    ? 'pipeline_get_audience_portrait'
    : 'pipeline_list_audience_portraits'
  try {
    const data = await fetchJson<unknown>(
      `${base.knowledge}/api/v1/mcp/exec/${endpoint}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    )
    return Response.json({ success: true, data })
  } catch (err: unknown) {
    return Response.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    )
  }
}
