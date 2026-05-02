import { fetchJson, serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function PATCH(
  request: Request,
  { params }: { params: { id: string } },
) {
  try {
    const payload = await request.json()
    const base = serviceBase()
    const body = await fetchJson<{ data: { id: string } }>(
      `${base.knowledge}/api/v1/prompt/rules/${encodeURIComponent(params.id)}`,
      { method: 'PATCH', body: JSON.stringify(payload) },
    )
    return Response.json({ success: true, data: body.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}

export async function DELETE(
  _request: Request,
  { params }: { params: { id: string } },
) {
  try {
    const base = serviceBase()
    const body = await fetchJson<{ data: unknown }>(
      `${base.knowledge}/api/v1/prompt/rules/${encodeURIComponent(params.id)}`,
      { method: 'DELETE' },
    )
    return Response.json({ success: true, data: body.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
