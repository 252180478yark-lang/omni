import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface CostItem {
  id: string
  sku_id: string | null
  category: 'product' | 'logistics' | 'partner_quote'
  item_name: string
  unit_cost: number
  currency: string
  unit: string
  quantity_per_unit: number
  vendor: string | null
  valid_from: string
  valid_to: string | null
  is_active: boolean
  notes: string | null
  created_at: string
  updated_at: string
}

interface ListResp {
  code: number
  message: string
  data: CostItem[]
}

interface CreateResp {
  code: number
  message: string
  data: CostItem
}

interface CreateBody {
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
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url)
    const qs = url.search // 直接透传查询参数
    const base = serviceBase()
    const result = await fetchJson<ListResp>(
      `${base.knowledge}/api/v1/accounting/cost-items${qs}`,
    )
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as CreateBody
    const base = serviceBase()
    const result = await fetchJson<CreateResp>(
      `${base.knowledge}/api/v1/accounting/cost-items`,
      { method: 'POST', body: JSON.stringify(payload) },
    )
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
