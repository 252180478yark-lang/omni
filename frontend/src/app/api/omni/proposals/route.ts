import { fetchJson, serviceBase } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

// 诊断官《改进提议》收件箱（蓝图 §6.2）：GET 列表 / POST 触发跑一轮诊断。
export async function GET(request: Request) {
  const url = new URL(request.url)
  const status = url.searchParams.get('status') || 'open'
  const mode = url.searchParams.get('mode') || ''
  const base = serviceBase()
  try {
    const qs = new URLSearchParams({ status, limit: '100' })
    if (mode) qs.set('mode', mode)
    const data = await fetchJson<Record<string, unknown>>(
      `${base.knowledge}/api/v1/mcp/proposals?${qs.toString()}`,
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
      `${base.knowledge}/api/v1/mcp/proposals/diagnose`,
      {
        method: 'POST',
        body: JSON.stringify({
          mode: body.mode || 'content',
          lookback_days: body.lookback_days || 7,
        }),
      },
    )
    return Response.json({ success: true, data })
  } catch (e) {
    return Response.json({ success: false, error: (e as Error).message }, { status: 502 })
  }
}
