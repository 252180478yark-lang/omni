import { fetchJson, serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface PatchBody {
  sku_id?: string | null
  category?: 'product' | 'logistics' | 'partner_quote'
  item_name?: string
  unit_cost?: number
  currency?: string
  unit?: string
  quantity_per_unit?: number
  vendor?: string | null
  valid_from?: string | null
  valid_to?: string | null
  is_active?: boolean
  notes?: string | null
}

export async function GET(_: Request, context: { params: { id: string } }) {
  try {
    const { id } = context.params
    const base = serviceBase()
    const result = await fetchJson<{ data: unknown }>(
      `${base.knowledge}/api/v1/accounting/cost-items/${id}`,
    )
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}

export async function PATCH(request: Request, context: { params: { id: string } }) {
  try {
    const { id } = context.params
    const payload = (await request.json()) as PatchBody
    const base = serviceBase()
    const result = await fetchJson<{ data: unknown }>(
      `${base.knowledge}/api/v1/accounting/cost-items/${id}`,
      { method: 'PATCH', body: JSON.stringify(payload) },
    )
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}

export async function DELETE(_: Request, context: { params: { id: string } }) {
  try {
    const { id } = context.params
    const base = serviceBase()
    await fetchJson<{ data: { deleted: boolean } }>(
      `${base.knowledge}/api/v1/accounting/cost-items/${id}`,
      { method: 'DELETE' },
    )
    return Response.json({ success: true })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
