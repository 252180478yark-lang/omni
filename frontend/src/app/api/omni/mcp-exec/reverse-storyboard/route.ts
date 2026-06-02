import { NextResponse } from 'next/server'
import { serviceBase } from '@/app/api/omni/_shared'

export const runtime = 'nodejs'
// 反推视频耗时(Gemini Files API 上传 + 推理),给前端 6 分钟超时
export const maxDuration = 360

/**
 * 转发到 KE /api/v1/mcp/exec/reverse_storyboard_video.
 *
 * video_path 由前端在 page 里做 host→container 映射(C:/Users/Administrator/Desktop/X
 * → /host/Desktop/X), 这里只透传不做转换.
 */
export async function POST(req: Request) {
  let body: unknown
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ ok: false, error: 'invalid_json' }, { status: 400 })
  }

  const { knowledge } = serviceBase()
  const url = `${knowledge}/api/v1/mcp/exec/reverse_storyboard_video`

  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      // KE tool 内部直调 Gemini Files API, 上传 + 推理可能 1-5 min
      signal: AbortSignal.timeout(355_000),
    })
    const text = await r.text()
    return new NextResponse(text, {
      status: r.status,
      headers: {
        'Content-Type': r.headers.get('content-type') || 'application/json',
      },
    })
  } catch (e) {
    const msg = (e as Error).message || String(e)
    return NextResponse.json(
      { ok: false, error: 'ke_unreachable', detail: msg },
      { status: 502 },
    )
  }
}
