import { serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

/**
 * 代理 AI Provider Hub 流式对话（单人无知识库 / 其他客户端流式场景）
 */
export async function POST(request: Request) {
  try {
    const body = await request.json()
    const base = serviceBase()
    const upstream = await fetch(`${base.aiHub}/api/v1/ai/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    if (!upstream.ok) {
      const text = await upstream.text()
      return Response.json(
        { success: false, error: `${upstream.status}: ${text}` },
        { status: upstream.status },
      )
    }

    if (!upstream.body) {
      return Response.json({ success: false, error: '上游响应体为空' }, { status: 502 })
    }

    return new Response(upstream.body, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      },
    })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
