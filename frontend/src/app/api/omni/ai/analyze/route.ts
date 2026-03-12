import { serviceBase, fetchJson } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  try {
    const body = await request.json()
    const base = serviceBase()
    const result = await fetchJson<{ analysis: string; structured_data?: object }>(
      `${base.aiHub}/api/v1/ai/analyze`,
      { method: 'POST', body: JSON.stringify(body) },
    )
    return Response.json({ success: true, data: result })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
