import { serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(_request: Request, context: { params: { id: string } }) {
  try {
    const base = serviceBase()
    const res = await fetch(
      `${base.videoAnalysis}/api/v1/video-analysis/decompose/stream/${encodeURIComponent(context.params.id)}`,
      {
        cache: 'no-store',
        headers: { Accept: 'text/event-stream' },
      },
    )
    return new Response(res.body, {
      status: res.status,
      headers: {
        'Content-Type': res.headers.get('Content-Type') || 'text/event-stream',
        'Cache-Control': 'no-cache',
      },
    })
  } catch (error) {
    return Response.json({ error: String(error) }, { status: 500 })
  }
}
