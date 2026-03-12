import { serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface RAGBody {
  kb_id: string
  query: string
  top_k?: number
  model?: string
  provider?: string
  stream?: boolean
}

/**
 * POST /api/omni/knowledge/rag
 * Proxies to knowledge-engine /api/v1/knowledge/rag.
 * When stream=true, returns raw SSE passthrough.
 */
export async function POST(request: Request) {
  try {
    const body = (await request.json()) as RAGBody
    const base = serviceBase()
    const isStream = body.stream === true

    const upstream = await fetch(`${base.knowledge}/api/v1/knowledge/rag`, {
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

    if (isStream && upstream.body) {
      return new Response(upstream.body, {
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
        },
      })
    }

    const json = await upstream.json()
    return Response.json({ success: true, data: json.data ?? json })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
