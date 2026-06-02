import { serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface RateBody {
  rating: 'good' | 'bad' | 'redo'
  note?: string
}

export async function POST(req: Request, ctx: { params: { id: string } }) {
  const base = serviceBase()
  const { id } = ctx.params
  let body: RateBody
  try {
    body = await req.json()
  } catch {
    return Response.json({ success: false, error: 'invalid_json' }, { status: 400 })
  }
  try {
    const r = await fetch(
      `${base.knowledge}/api/v1/mcp/tool-calls/${encodeURIComponent(id)}/rate`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating: body.rating, note: body.note ?? '' }),
        cache: 'no-store',
      },
    )
    const data = await r.json().catch(() => ({}))
    return Response.json({ success: r.ok, ...data }, { status: r.status })
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return Response.json({ success: false, error: msg }, { status: 502 })
  }
}
