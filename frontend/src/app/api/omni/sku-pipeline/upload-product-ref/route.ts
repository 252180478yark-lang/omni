import { serviceBase } from '../../_shared'
import { NextRequest } from 'next/server'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest) {
  const base = serviceBase()
  try {
    const formData = await req.formData()
    const res = await fetch(`${base.knowledge}/api/v1/knowledge/upload-product-ref`, {
      method: 'POST',
      body: formData,
    })
    const data = await res.json()
    if (!res.ok) return Response.json({ success: false, error: data.detail || 'upload failed' }, { status: res.status })
    return Response.json({ success: true, url: data.url })
  } catch (err: unknown) {
    return Response.json({ success: false, error: String(err) }, { status: 502 })
  }
}
