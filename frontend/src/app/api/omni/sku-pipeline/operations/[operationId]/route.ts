import { NextResponse } from 'next/server'

import { isSkuPipelineOperationId } from '@/lib/sku-pipeline/operations'
import { requireSameOrigin, serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: Request, context: { params: { operationId: string } }) {
  const operationId = context.params.operationId
  if (!isSkuPipelineOperationId(operationId)) {
    return NextResponse.json({ success: false, error: 'unknown_sku_operation' }, { status: 404 })
  }
  try {
    requireSameOrigin(request)
    const body = await request.text()
    const response = await fetch(`${serviceBase().knowledge}/api/v1/mcp/execute/${encodeURIComponent(operationId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      cache: 'no-store',
    })
    const data = await response.json().catch(() => ({ ok: false, error: 'invalid_upstream_json' }))
    if (!response.ok) return NextResponse.json({ success: false, error: data.error || data.detail || 'operation_failed', data }, { status: response.status })
    return NextResponse.json({ success: true, data })
  } catch (reason) {
    return NextResponse.json({ success: false, error: reason instanceof Error ? reason.message : 'operation_proxy_failed' }, { status: 502 })
  }
}
