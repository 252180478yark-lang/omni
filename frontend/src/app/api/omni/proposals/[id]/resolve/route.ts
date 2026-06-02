import { fetchJson, serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

// 老板对某条《改进提议》拍板（R-20 三态：accept / ignore / snooze）。
export async function POST(
  request: Request,
  { params }: { params: { id: string } },
) {
  const body = await request.json().catch(() => ({}))
  const base = serviceBase()
  try {
    const data = await fetchJson<Record<string, unknown>>(
      `${base.knowledge}/api/v1/mcp/proposals/${encodeURIComponent(params.id)}/resolve`,
      {
        method: 'POST',
        body: JSON.stringify({
          action: body.action,
          note: body.note ?? null,
          snooze_days: body.snooze_days ?? 7,
        }),
      },
    )
    return Response.json({ success: true, data })
  } catch (e) {
    return Response.json({ success: false, error: (e as Error).message }, { status: 502 })
  }
}
