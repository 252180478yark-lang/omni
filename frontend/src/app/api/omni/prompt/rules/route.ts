import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  try {
    const url = new URL(request.url)
    const nodeId = url.searchParams.get('node_id') || ''
    const enabledOnly = url.searchParams.get('enabled_only') === 'true'
    const qs = new URLSearchParams()
    if (nodeId) qs.set('node_id', nodeId)
    if (enabledOnly) qs.set('enabled_only', 'true')

    const base = serviceBase()
    const body = await fetchJson<{ data: { rules: unknown[] } }>(
      `${base.knowledge}/api/v1/prompt/rules${qs.toString() ? '?' + qs.toString() : ''}`,
    )
    return Response.json({ success: true, data: body.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}

export async function POST(request: Request) {
  try {
    const payload = await request.json()
    const base = serviceBase()
    const body = await fetchJson<{ data: { id: string } }>(
      `${base.knowledge}/api/v1/prompt/rules`,
      { method: 'POST', body: JSON.stringify(payload) },
    )
    return Response.json({ success: true, data: body.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
