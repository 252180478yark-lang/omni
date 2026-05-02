import { serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

/** GET /api/omni/chat/sessions — list */
export async function GET(request: Request) {
  try {
    const url = new URL(request.url)
    const qs = url.searchParams.toString()
    const base = serviceBase()
    const upstream = await fetch(
      `${base.knowledge}/api/v1/chat/sessions${qs ? `?${qs}` : ''}`,
      { cache: 'no-store' },
    )
    const json = await upstream.json()
    if (!upstream.ok) {
      return Response.json(
        { success: false, error: json?.detail || json?.message || `HTTP ${upstream.status}` },
        { status: upstream.status },
      )
    }
    return Response.json({ success: true, data: json.data ?? json })
  } catch (err) {
    return Response.json({ success: false, error: String(err) }, { status: 500 })
  }
}

/** POST /api/omni/chat/sessions — upsert */
export async function POST(request: Request) {
  try {
    const body = await request.json()
    const base = serviceBase()
    const upstream = await fetch(`${base.knowledge}/api/v1/chat/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const json = await upstream.json()
    if (!upstream.ok) {
      return Response.json(
        { success: false, error: json?.detail || json?.message || `HTTP ${upstream.status}` },
        { status: upstream.status },
      )
    }
    return Response.json({ success: true, data: json.data ?? json })
  } catch (err) {
    return Response.json({ success: false, error: String(err) }, { status: 500 })
  }
}
