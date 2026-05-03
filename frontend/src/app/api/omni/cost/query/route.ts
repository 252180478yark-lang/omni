import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface QueryBody {
  query: string
  sku_id?: string | null
  sale_price?: number | null
  model?: string | null
}

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as QueryBody
    const base = serviceBase()
    const result = await fetchJson<{ data: unknown }>(
      `${base.knowledge}/api/v1/accounting/query`,
      { method: 'POST', body: JSON.stringify(payload) },
    )
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
