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

function upstreamParts(method: string, parts: string[]): string[] | null {
  // Preserve the original compact plan routes while exposing the explicit S4/S5
  // route tree used by the owner co-design page.
  if (parts.length === 0 && method === 'POST') return ['integration-plans']
  if (parts.length === 1 && ['GET', 'PATCH'].includes(method)) return ['integration-plans', parts[0]]
  if (parts.length === 2 && method === 'POST' && parts[1] === 'confirm') {
    return ['integration-plans', parts[0], 'confirm']
  }
  if (parts[0] === 'integration-plans') {
    if (parts.length === 1 && ['GET', 'POST'].includes(method)) return parts
    if (parts.length === 2 && ['GET', 'PATCH'].includes(method)) return parts
    if (parts.length === 3 && method === 'POST' && ['confirm', 'rebase', 'archive'].includes(parts[2])) return parts
  }
  if (parts[0] === 'issues') {
    if (parts.length === 1 && method === 'GET') return parts
    if (parts.length === 3 && method === 'POST' && parts[2] === 'transition') return parts
  }
  if (parts.length === 1 && parts[0] === 'refresh' && method === 'POST') return parts
  if (parts.length === 2 && parts[0] === 'refreshes' && method === 'GET') return parts
  if (parts.length === 3 && parts[0] === 'snapshots' && parts[2] === 'graph' && method === 'GET') return parts
  if (parts.length === 1 && ['search', 'diff'].includes(parts[0]) && method === 'GET') return parts
  return null
}

async function proxy(request: NextRequest, method: string, parts: string[]) {
  const targetParts = upstreamParts(method, parts)
  if (!targetParts) {
    return NextResponse.json({ success: false, error: 'system_graph_route_not_allowed' }, { status: 404 })
  }
  try {
    requireSameOrigin(request)
    const actor = await requireApprovalActor(request)
    const body = method === 'GET' ? '' : await request.text()
    const base = serviceBase()
    const suffix = targetParts.map(encodeURIComponent).join('/')
    const url = `${base.knowledge}/api/v1/system-graph/${suffix}${request.nextUrl.search}`
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
