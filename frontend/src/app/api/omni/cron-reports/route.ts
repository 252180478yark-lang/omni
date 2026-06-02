import { fetchJson, serviceBase } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

// cron 周期报（蓝图 §6.1：自动周期报推到 UI/眼前，不只写 markdown 让老板自己找）。
export async function GET() {
  const base = serviceBase()
  try {
    const data = await fetchJson<Record<string, unknown>>(
      `${base.knowledge}/api/v1/agent-state/reports`,
    )
    return Response.json({ success: true, data })
  } catch (e) {
    return Response.json({ success: false, error: (e as Error).message }, { status: 502 })
  }
}
