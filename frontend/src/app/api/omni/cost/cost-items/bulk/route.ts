import { fetchJson, serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface BulkBody {
  items: Array<{
    sku_id?: string | null
    category: 'product' | 'logistics' | 'partner_quote'
    item_name: string
    unit_cost: number
    currency?: string
    unit?: string
    quantity_per_unit?: number
    vendor?: string | null
    valid_from?: string | null
    valid_to?: string | null
    notes?: string | null
  }>
}

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as BulkBody
    if (!payload.items || payload.items.length === 0) {
      return Response.json({ success: false, error: 'items 数组为空' }, { status: 400 })
    }
    const base = serviceBase()
    const result = await fetchJson<{ data: { created: unknown[]; errors: unknown[] } }>(
      `${base.knowledge}/api/v1/accounting/cost-items/bulk`,
      { method: 'POST', body: JSON.stringify(payload) },
    )
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
