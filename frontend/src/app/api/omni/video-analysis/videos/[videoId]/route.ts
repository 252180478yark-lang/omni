import { serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(_request: Request, context: { params: { videoId: string } }) {
  try {
    const { videoId } = context.params
    const base = serviceBase()
    const res = await fetch(`${base.videoAnalysis}/api/v1/video-analysis/videos/${encodeURIComponent(videoId)}`, {
      cache: 'no-store',
    })
    const text = await res.text()
    return new Response(text, {
      status: res.status,
      headers: { 'Content-Type': res.headers.get('Content-Type') || 'application/json' },
    })
  } catch (error) {
    return Response.json({ error: String(error) }, { status: 500 })
  }
}
