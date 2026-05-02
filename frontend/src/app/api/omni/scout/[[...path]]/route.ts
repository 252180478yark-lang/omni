import type { NextRequest } from 'next/server'
import { NextResponse } from 'next/server'
import { serviceBase } from '../../_shared'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

function targetUrl(pathSegments: string[] | undefined, search: string): string {
  const base = serviceBase().scoutAgent.replace(/\/$/, '')
  const sub = (pathSegments || []).join('/')
  return `${base}/api/v1/scout/${sub}${search}`
}

async function proxy(request: NextRequest, method: string, pathSegments: string[] | undefined) {
  const url = targetUrl(pathSegments, request.nextUrl.search)
  const ct = request.headers.get('content-type') || ''

  let body: BodyInit | undefined = undefined
  if (method !== 'GET' && method !== 'HEAD') {
    const buf = await request.arrayBuffer()
    body = buf.byteLength ? buf : undefined
  }

  const headers = new Headers()
  if (ct) headers.set('content-type', ct)

  const res = await fetch(url, { method, headers, body })

  const outHeaders = new Headers()
  const ct2 = res.headers.get('content-type')
  if (ct2) outHeaders.set('content-type', ct2)
  outHeaders.set('cache-control', 'no-store, no-transform')

  return new NextResponse(res.body, { status: res.status, headers: outHeaders })
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
