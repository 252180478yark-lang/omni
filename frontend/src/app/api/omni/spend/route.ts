import { fetchJson, serviceBase } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

// omni 自身月度运行成本（蓝图 §4 L0-2：omni 自身月成本进 BI 当一等指标）。
export async function GET(request: Request) {
  const url = new URL(request.url)
  const month = url.searchParams.get('month') || ''
  const base = serviceBase()
  try {
    const qs = month ? `?month=${encodeURIComponent(month)}` : ''
    const data = await fetchJson<Record<string, unknown>>(
      `${base.knowledge}/api/v1/mcp/spend/month${qs}`,
    )
    return Response.json({ success: true, data })
  } catch (e) {
    return Response.json({ success: false, error: (e as Error).message }, { status: 502 })
  }
}
