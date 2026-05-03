import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface MarginBody {
  sku_id: string
  sale_price: number
  quantity?: number
  platform_fee_rate?: number
  include_shared_logistics?: boolean
}

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as MarginBody
    const base = serviceBase()
    const result = await fetchJson<{ data: unknown }>(
      `${base.knowledge}/api/v1/accounting/margin`,
      { method: 'POST', body: JSON.stringify(payload) },
    )
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
