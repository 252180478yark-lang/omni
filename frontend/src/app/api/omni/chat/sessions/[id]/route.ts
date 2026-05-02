import { serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface RouteCtx {
  params: Promise<{ id: string }>
}

/** GET /api/omni/chat/sessions/[id] — session meta */
export async function GET(_request: Request, ctx: RouteCtx) {
  const { id } = await ctx.params
  try {
    const base = serviceBase()
    const upstream = await fetch(`${base.knowledge}/api/v1/chat/sessions/${encodeURIComponent(id)}`, {
      cache: 'no-store',
    })
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

/** PATCH /api/omni/chat/sessions/[id] — rename / update meta */
export async function PATCH(request: Request, ctx: RouteCtx) {
  const { id } = await ctx.params
  try {
    const body = await request.json()
    const base = serviceBase()
    const upstream = await fetch(`${base.knowledge}/api/v1/chat/sessions/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
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

/** DELETE /api/omni/chat/sessions/[id] — soft delete */
export async function DELETE(_request: Request, ctx: RouteCtx) {
  const { id } = await ctx.params
  try {
    const base = serviceBase()
    const upstream = await fetch(`${base.knowledge}/api/v1/chat/sessions/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    })
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
