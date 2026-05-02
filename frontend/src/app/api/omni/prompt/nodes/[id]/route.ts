import { fetchJson, serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(
  _request: Request,
  { params }: { params: { id: string } },
) {
  try {
    const base = serviceBase()
    const body = await fetchJson<{ data: unknown }>(
      `${base.knowledge}/api/v1/prompt/nodes/${encodeURIComponent(params.id)}`,
    )
    return Response.json({ success: true, data: body.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
