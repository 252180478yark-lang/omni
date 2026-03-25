import { serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  try {
    const body = await request.json()
    const base = serviceBase()

    const upstream = await fetch(`${base.knowledge}/api/v1/knowledge/rag/evaluate`, {
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

    const json = await upstream.json()
    return Response.json({ success: true, data: json.data ?? json })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
