import type { NextRequest } from 'next/server'
import { NextResponse } from 'next/server'

import { serviceBase } from '../../_shared'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

function targetUrl(pathSegments: string[] | undefined, search: string): string {
  const base = serviceBase().adReview.replace(/\/$/, '')
  const sub = (pathSegments || []).join('/')
  return `${base}/api/v1/ad-review/${sub}${search}`
}

async function proxy(request: NextRequest, method: string, pathSegments: string[] | undefined) {
  const url = targetUrl(pathSegments, request.nextUrl.search)
  const ct = request.headers.get('content-type') || ''

  let body: BodyInit | undefined | null = undefined
  if (method !== 'GET' && method !== 'HEAD') {
    if (ct.includes('multipart/form-data')) {
      body = await request.formData()
    } else {
      const buf = await request.arrayBuffer()
      body = buf.byteLength ? buf : undefined
    }
  }

  const headers = new Headers()
  const accept = request.headers.get('accept')
  if (accept) headers.set('accept', accept)
  if (!ct.includes('multipart/form-data') && ct) {
    headers.set('content-type', ct)
  }

  const init: RequestInit = { method, headers, body: body ?? undefined }
  const res = await fetch(url, init)

  const outHeaders = new Headers()
  const pass = ['content-type', 'cache-control', 'x-accel-buffering']
  for (const h of pass) {
    const v = res.headers.get(h)
    if (v) outHeaders.set(h, v)
  }
  if (!outHeaders.has('cache-control')) {
    outHeaders.set('cache-control', 'no-store, no-transform')
  }

  if (res.body) {
    return new NextResponse(res.body, { status: res.status, headers: outHeaders })
  }
  return new NextResponse(null, { status: res.status, headers: outHeaders })
}

export async function GET(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, 'GET', context.params.path)
}

export async function POST(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, 'POST', context.params.path)
}

export async function PUT(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, 'PUT', context.params.path)
}

export async function DELETE(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, 'DELETE', context.params.path)
}
