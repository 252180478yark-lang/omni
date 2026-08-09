import type { NextRequest } from 'next/server'
import { NextResponse } from 'next/server'
import { requireAuthenticatedActor, ServiceFetchError, serviceBase } from '../../_shared'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const TRACE_REQUEST_HEADERS = [
  'x-omni-trace-id',
  'x-omni-execution-id',
  'x-omni-span-id',
  'x-omni-parent-span-id',
  'x-omni-correlation-id',
  'x-omni-session-id',
] as const

const TRACE_IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,199}$/

const TRACE_RESPONSE_HEADERS = [
  'x-omni-trace-id',
  'x-omni-execution-id',
  'x-omni-span-id',
  'x-omni-trace-gap',
] as const

function targetUrl(pathSegments: string[] | undefined, search: string): string {
  const base = serviceBase().scoutAgent.replace(/\/$/, '')
  const sub = (pathSegments || []).join('/')
  return `${base}/api/v1/scout/${sub}${search}`
}

async function proxy(request: NextRequest, method: string, pathSegments: string[] | undefined) {
  try {
    const traceContext = TRACE_REQUEST_HEADERS.flatMap((name) => {
      const value = request.headers.get(name)
      return value ? [[name, value] as const] : []
    })
    if (traceContext.length) {
      for (const [, value] of traceContext) {
        if (!TRACE_IDENTIFIER.test(value)) {
          throw new ServiceFetchError('invalid trace context', {
            status: 400,
            source: 'frontend:scout-proxy',
            code: 'invalid_trace_context',
          })
        }
      }
      await requireAuthenticatedActor(request)
    }

    const url = targetUrl(pathSegments, request.nextUrl.search)
    const ct = request.headers.get('content-type') || ''

    let body: BodyInit | undefined = undefined
    if (method !== 'GET' && method !== 'HEAD') {
      const buf = await request.arrayBuffer()
      body = buf.byteLength ? buf : undefined
    }

    const headers = new Headers()
    if (ct) headers.set('content-type', ct)
    for (const [name, value] of traceContext) headers.set(name, value)

    const res = await fetch(url, { method, headers, body })

    const outHeaders = new Headers()
    const ct2 = res.headers.get('content-type')
    if (ct2) outHeaders.set('content-type', ct2)
    for (const name of TRACE_RESPONSE_HEADERS) {
      const value = res.headers.get(name)
      if (value) outHeaders.set(name, value)
    }
    outHeaders.set('cache-control', 'no-store, no-transform')

    return new NextResponse(res.body, { status: res.status, headers: outHeaders })
  } catch (error: unknown) {
    const status = error instanceof ServiceFetchError ? error.status : 502
    const code = error instanceof ServiceFetchError ? error.code : 'scout_upstream_unavailable'
    return NextResponse.json({ success: false, error: code }, { status })
  }
}

export async function GET(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, 'GET', context.params.path)
}
export async function POST(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, 'POST', context.params.path)
}
export async function PATCH(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, 'PATCH', context.params.path)
}
export async function DELETE(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, 'DELETE', context.params.path)
}
export async function PUT(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, 'PUT', context.params.path)
}
