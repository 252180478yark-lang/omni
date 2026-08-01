import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  const base = serviceBase()
  const body = await request.json().catch(() => ({}))
  try {
    const ctl = new AbortController()
    const tid = setTimeout(() => ctl.abort(), 600_000)
    let data: any
    try {
      data = await fetchJson<any>(
      `${base.knowledge}/api/v1/mcp/execute/sku.character-sheets.generate`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: ctl.signal,
        },
      )
    } finally {
      clearTimeout(tid)
    }
    return Response.json({ success: true, data })
  } catch (err: unknown) {
    return Response.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    )
  }
}
