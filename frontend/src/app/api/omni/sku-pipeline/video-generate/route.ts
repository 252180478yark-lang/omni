import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  const base = serviceBase()
  const body = await request.json().catch(() => ({}))
  try {
    // 视频生成更慢（单段 60-180s + 排队 + 轮询），并发 6 段总可能 5-10min，
    // 前端 AbortController 给 15 分钟 timeout
    const ctl = new AbortController()
    const tid = setTimeout(() => ctl.abort(), 900_000)
    let data: any
    try {
      data = await fetchJson<any>(
      `${base.knowledge}/api/v1/mcp/execute/sku.video.generate`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: ctl.signal,
        },
      )
    } finally {
      clearTimeout(tid)
    }
    return Response.json({ success: true, data })
  } catch (err: unknown) {
    return Response.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    )
  }
}
