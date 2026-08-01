import type { NextRequest } from 'next/server'
import { NextResponse } from 'next/server'
import {
  approvalServiceHeaders,
  requireApprovalActor,
  requireSameOrigin,
  ServiceFetchError,
  serviceBase,
} from '../../_shared'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

function isAllowed(method: string, parts: string[]): boolean {
  if (method === 'POST' && parts.length === 0) return true
  if (method === 'GET' && parts.length === 1) return true
  if (method === 'PATCH' && parts.length === 1) return true
  return method === 'POST' && parts.length === 2 && parts[1] === 'confirm'
}

async function proxy(request: NextRequest, method: string, parts: string[]) {
  if (!isAllowed(method, parts)) {
    return NextResponse.json({ success: false, error: 'system_graph_route_not_allowed' }, { status: 404 })
  }
  try {
    requireSameOrigin(request)
    const actor = await requireApprovalActor(request)
    const body = method === 'GET' ? '' : await request.text()
    const base = serviceBase()
    const suffix = parts.map(encodeURIComponent).join('/')
    const url = `${base.knowledge}/api/v1/system-graph/integration-plans${suffix ? `/${suffix}` : ''}${request.nextUrl.search}`
    const response = await fetch(url, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...approvalServiceHeaders(method, url, actor, body),
      },
      body: body || undefined,
      cache: 'no-store',
    })
    const headers = new Headers()
    const contentType = response.headers.get('content-type')
    if (contentType) headers.set('content-type', contentType)
    headers.set('cache-control', 'no-store, no-transform')
    return new NextResponse(response.body, { status: response.status, headers })
  } catch (error: unknown) {
    const status = error instanceof ServiceFetchError ? error.status : 502
    const code = error instanceof ServiceFetchError ? error.code : 'system_graph_upstream_unavailable'
    return NextResponse.json({ success: false, error: code }, { status })
  }
}

export async function GET(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, 'GET', context.params.path || [])
}

export async function POST(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, 'POST', context.params.path || [])
}

export async function PATCH(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, 'PATCH', context.params.path || [])
}
