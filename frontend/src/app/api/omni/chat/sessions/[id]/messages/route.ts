import { serviceBase } from '../../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface RouteCtx {
  params: Promise<{ id: string }>
}

/** GET /api/omni/chat/sessions/[id]/messages — load full history */
export async function GET(request: Request, ctx: RouteCtx) {
  const { id } = await ctx.params
  try {
    const url = new URL(request.url)
    const qs = url.searchParams.toString()
    const base = serviceBase()
    const upstream = await fetch(
      `${base.knowledge}/api/v1/chat/sessions/${encodeURIComponent(id)}/messages${qs ? `?${qs}` : ''}`,
      { cache: 'no-store' },
    )
    const json = await upstream.json()
    if (!upstream.ok) {
      return Response.json(
        { success: false, error: json?.detail || `HTTP ${upstream.status}` },
        { status: upstream.status },
      )
    }
    return Response.json({ success: true, data: json.data ?? json })
  } catch (err) {
    return Response.json({ success: false, error: String(err) }, { status: 500 })
  }
}

/** POST /api/omni/chat/sessions/[id]/messages — append one message (used by no-KB direct chat) */
export async function POST(request: Request, ctx: RouteCtx) {
  const { id } = await ctx.params
  try {
    const body = await request.json()
    const base = serviceBase()
    const upstream = await fetch(
      `${base.knowledge}/api/v1/chat/sessions/${encodeURIComponent(id)}/messages`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    )
    const json = await upstream.json()
    if (!upstream.ok) {
      return Response.json(
        { success: false, error: json?.detail || `HTTP ${upstream.status}` },
        { status: upstream.status },
      )
    }
    return Response.json({ success: true, data: json.data ?? json })
  } catch (err) {
    return Response.json({ success: false, error: String(err) }, { status: 500 })
  }
}
