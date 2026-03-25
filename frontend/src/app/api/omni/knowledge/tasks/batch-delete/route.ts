import { fetchJson, serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  try {
    const body = await request.json()
    const base = serviceBase()
    const result = await fetchJson<{ data: { deleted: number } }>(
      `${base.knowledge}/api/v1/knowledge/tasks/batch-delete`,
      { method: 'POST', body: JSON.stringify(body) }
    )
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
