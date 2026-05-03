import { serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

// 上传文件 → multipart 透传到 knowledge-engine /api/v1/accounting/extract-from-file
// LLM 解析后返回 cost_items 草稿，前端预览编辑后再调 /cost-items/bulk 入库
export async function POST(request: Request) {
  try {
    const inForm = await request.formData()
    const file = inForm.get('file')
    if (!(file instanceof File)) {
      return Response.json({ success: false, error: 'file 字段缺失' }, { status: 400 })
    }
    const skuId = inForm.get('sku_id')
    const model = inForm.get('model')

    const outForm = new FormData()
    outForm.append('file', file, file.name)
    if (typeof skuId === 'string' && skuId) outForm.append('sku_id', skuId)
    if (typeof model === 'string' && model) outForm.append('model', model)

    const base = serviceBase()
    const resp = await fetch(`${base.knowledge}/api/v1/accounting/extract-from-file`, {
      method: 'POST',
      body: outForm,
      // 不要手动设 Content-Type，让 fetch 自动加 multipart boundary
    })
    if (!resp.ok) {
      let detail = ''
      try {
        const body = await resp.json()
        detail = body?.detail || body?.error || body?.message || ''
      } catch { /* noop */ }
      return Response.json(
        { success: false, error: detail || `${resp.status} ${resp.statusText}` },
        { status: resp.status },
      )
    }
    const json = await resp.json()
    return Response.json({ success: true, data: json.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
