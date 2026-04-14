import { serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

/** 代理 SP6 视频列表，供投放复盘「关联视频」等使用 */
export async function GET() {
  try {
    const base = serviceBase()
    const res = await fetch(`${base.videoAnalysis}/api/v1/video-analysis/videos`, { cache: 'no-store' })
    const text = await res.text()
    return new Response(text, {
      status: res.status,
      headers: { 'Content-Type': res.headers.get('Content-Type') || 'application/json' },
    })
  } catch (error) {
    return Response.json({ error: String(error) }, { status: 500 })
  }
}

/** 代理 SP6 上传视频（投放复盘页可直接发起分析） */
export async function POST(request: Request) {
  try {
    const base = serviceBase()
    const form = await request.formData()
    const res = await fetch(`${base.videoAnalysis}/api/v1/video-analysis/videos`, {
      method: 'POST',
      body: form,
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
