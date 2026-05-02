import { serviceBase } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  try {
    const base = serviceBase()
    const url = new URL(request.url)
    const q = url.searchParams.toString()
    const res = await fetch(`${base.videoAnalysis}/api/v1/video-analysis/decompose${q ? `?${q}` : ''}`, { cache: 'no-store' })
    const text = await res.text()
    return new Response(text, {
      status: res.status,
      headers: { 'Content-Type': res.headers.get('Content-Type') || 'application/json' },
    })
  } catch (error) {
    return Response.json({ error: String(error) }, { status: 500 })
  }
}

export async function POST(request: Request) {
  try {
    const base = serviceBase()
    const url = new URL(request.url)
    const mode = url.searchParams.get('mode') || 'video'
    const form = await request.formData()
    const target =
      mode === 'video'
        ? `${base.videoAnalysis}/api/v1/video-analysis/decompose/video`
        : mode === 'detail-page'
          ? `${base.videoAnalysis}/api/v1/video-analysis/decompose/detail-page`
          : `${base.videoAnalysis}/api/v1/video-analysis/decompose/main-image`
    const res = await fetch(target, { method: 'POST', body: form, cache: 'no-store' })
    const text = await res.text()
    return new Response(text, {
      status: res.status,
      headers: { 'Content-Type': res.headers.get('Content-Type') || 'application/json' },
    })
  } catch (error) {
    return Response.json({ error: String(error) }, { status: 500 })
  }
}
