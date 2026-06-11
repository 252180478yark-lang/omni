import { serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

/**
 * 工具级 👍👎 反馈入口（反馈飞轮前端通路）。
 * body: { tool_name, rating: 'good'|'bad', category?, note? (≤500 字) }
 * → KE POST /api/v1/mcp/tool-calls/rate-recent（按 tool_name 取最近一条评）
 * KE 404 no_recent_call 时把 hint 透传给前端（如"120 分钟内没有该工具的调用记录可评"）。
 */
export async function POST(request: Request) {
  const base = serviceBase()
  const body = await request.json()
  try {
    const response = await fetch(`${base.knowledge}/api/v1/mcp/tool-calls/rate-recent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
    })
    const data = await response.json().catch(() => null)
    if (!response.ok || !data?.ok) {
      return Response.json(
        {
          success: false,
          error: data?.hint || data?.error || `${response.status} ${response.statusText}`,
        },
        { status: response.ok ? 400 : response.status },
      )
    }
    return Response.json({ success: true, data })
  } catch (err: unknown) {
    return Response.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    )
  }
}
