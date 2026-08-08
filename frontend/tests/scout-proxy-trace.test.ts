import { NextRequest } from 'next/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { GET } from '@/app/api/omni/scout/[[...path]]/route'

describe('Scout BFF trace propagation', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('forwards the allowlisted trace context and returns Scout trace evidence', async () => {
    const upstream = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const headers = new Headers(init?.headers)
      expect(headers.get('x-omni-trace-id')).toBe('trace:frontend-scout')
      expect(headers.get('x-omni-execution-id')).toBe('execution:frontend-scout')
      expect(headers.get('x-omni-parent-span-id')).toBe('span:frontend')
      expect(headers.get('authorization')).toBeNull()
      return new Response('{}', {
        status: 200,
        headers: {
          'content-type': 'application/json',
          'x-omni-trace-id': 'trace:frontend-scout',
          'x-omni-execution-id': 'execution:frontend-scout',
          'x-omni-span-id': 'scout:span',
        },
      })
    })
    vi.stubGlobal('fetch', upstream)

    const response = await GET(
      new NextRequest('http://localhost/api/omni/scout/jobs?limit=1', {
        headers: {
          'x-omni-trace-id': 'trace:frontend-scout',
          'x-omni-execution-id': 'execution:frontend-scout',
          'x-omni-parent-span-id': 'span:frontend',
          authorization: 'Bearer browser-session',
        },
      }),
      { params: { path: ['jobs'] } },
    )

    expect(upstream).toHaveBeenCalledOnce()
    expect(response.headers.get('x-omni-trace-id')).toBe('trace:frontend-scout')
    expect(response.headers.get('x-omni-execution-id')).toBe('execution:frontend-scout')
    expect(response.headers.get('x-omni-span-id')).toBe('scout:span')
  })

  it('accepts local-owner trace propagation but rejects malformed trace injection before Scout', async () => {
    const upstream = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', upstream)

    const unauthenticated = await GET(
      new NextRequest('http://localhost/api/omni/scout/jobs', {
        headers: { 'x-omni-trace-id': 'trace:frontend-scout' },
      }),
      { params: { path: ['jobs'] } },
    )
    expect(unauthenticated.status).toBe(200)

    const malformed = await GET(
      new NextRequest('http://localhost/api/omni/scout/jobs', {
        headers: {
          'x-omni-trace-id': 'trace id with spaces',
          authorization: 'Bearer browser-session',
        },
      }),
      { params: { path: ['jobs'] } },
    )
    expect(malformed.status).toBe(400)
    expect((await malformed.json()).error).toBe('invalid_trace_context')
    expect(upstream).toHaveBeenCalledOnce()
  })

  it('does not forward unsupported W3C traceparent as Omni continuity', async () => {
    const upstream = vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      expect(new Headers(init?.headers).get('traceparent')).toBeNull()
      return new Response('{}', { status: 200 })
    })
    vi.stubGlobal('fetch', upstream)

    const response = await GET(
      new NextRequest('http://localhost/api/omni/scout/jobs', {
        headers: { traceparent: '00-0123456789abcdef0123456789abcdef-0123456789abcdef-01' },
      }),
      { params: { path: ['jobs'] } },
    )
    expect(response.status).toBe(200)
    expect(upstream).toHaveBeenCalledOnce()
  })
})
