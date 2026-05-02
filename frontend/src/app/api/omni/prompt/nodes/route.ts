import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET() {
  try {
    const base = serviceBase()
    const body = await fetchJson<{ data: { nodes: unknown[] } }>(
      `${base.knowledge}/api/v1/prompt/nodes`,
    )
    return Response.json({ success: true, data: body.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
