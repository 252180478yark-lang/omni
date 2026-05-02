import { serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(_request: Request, context: { params: { id: string } }) {
  try {
    const base = serviceBase()
    const res = await fetch(
      `${base.videoAnalysis}/api/v1/video-analysis/decompose/${encodeURIComponent(context.params.id)}`,
      { cache: 'no-store' },
    )
    const text = await res.text()
    return new Response(text, {
      status: res.status,
      headers: { 'Content-Type': res.headers.get('Content-Type') || 'application/json' },
    })
  } catch (error) {
    return Response.json({ error: String(error) }, { status: 500 })
  }
}

export async function DELETE(_request: Request, context: { params: { id: string } }) {
  try {
    const base = serviceBase()
    const res = await fetch(
      `${base.videoAnalysis}/api/v1/video-analysis/decompose/${encodeURIComponent(context.params.id)}`,
      { method: 'DELETE', cache: 'no-store' },
    )
    const text = await res.text()
    return new Response(text, {
      status: res.status,
      headers: { 'Content-Type': res.headers.get('Content-Type') || 'application/json' },
    })
  } catch (error) {
    return Response.json({ error: String(error) }, { status: 500 })
  }
}

export async function POST(_request: Request, context: { params: { id: string } }) {
  try {
    const base = serviceBase()
    const res = await fetch(
      `${base.videoAnalysis}/api/v1/video-analysis/decompose/${encodeURIComponent(context.params.id)}/reingest`,
      { method: 'POST', cache: 'no-store' },
    )
    const text = await res.text()
    return new Response(text, {
      status: res.status,
      headers: { 'Content-Type': res.headers.get('Content-Type') || 'application/json' },
    })
  } catch (error) {
    return Response.json({ error: String(error) }, { status: 500 })
  }
}
