import { serviceBase } from '../../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(_: Request, context: { params: { kbId: string } }) {
  try {
    const { kbId } = context.params
    const base = serviceBase()
    const upstream = await fetch(`${base.knowledge}/api/v1/knowledge/bases/${kbId}/rebuild`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
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
