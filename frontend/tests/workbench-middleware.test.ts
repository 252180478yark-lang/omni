import { NextRequest } from 'next/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

const APPROVAL_COOKIE = 'omni_approval_session=browser-token'

afterEach(() => {
  vi.resetModules()
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

function eventCollector() {
  const promises: Promise<unknown>[] = []
  return {
    event: { waitUntil: vi.fn((promise: Promise<unknown>) => promises.push(promise)) },
    promises,
  }
}

async function middlewareWithFlag(value: string) {
  vi.stubEnv('NEXT_PUBLIC_OMNI_UNIFIED_SHELL', value)
  vi.stubEnv('PORT', '3000')
  return import('@/middleware')
}

function bffMock(status = 202) {
  const fetchMock = vi.fn(async (_input: string | URL | Request, _init?: RequestInit) => {
    void _input
    void _init
    return new Response(null, { status })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function cookieHeader(response: Response): string {
  return response.headers.get('set-cookie') || ''
}

describe('workbench compatibility middleware', () => {
  it('redirects a genuine alias, preserves query and posts an authenticated attempt to loopback', async () => {
    const fetchMock = bffMock()
    const {
      ALIAS_RECOVERY_COOKIE,
      ALIAS_RECOVERY_MAX_AGE_SECONDS,
      handleWorkbenchMiddleware,
    } = await middlewareWithFlag('1')
    const collector = eventCollector()
    const response = handleWorkbenchMiddleware(
      new NextRequest('http://attacker.example/qa?source=bookmark&round=2', {
        headers: {
          Accept: 'text/html',
          Cookie: `theme=dark; ${APPROVAL_COOKIE}`,
        },
      }),
      collector.event as never,
    )

    expect(response.status).toBe(307)
    expect(response.headers.get('location')).toBe('http://attacker.example/chat?source=bookmark&round=2')
    const recovery = response.cookies.get(ALIAS_RECOVERY_COOKIE)
    expect(recovery).toBeDefined()
    expect(JSON.parse(decodeURIComponent(recovery?.value || ''))).toEqual(['/qa', '/chat', 'chat'])
    expect(recovery?.value).not.toContain('source')
    const setCookie = cookieHeader(response).toLowerCase()
    expect(setCookie).toContain('httponly')
    expect(setCookie).toContain('samesite=lax')
    expect(setCookie).toContain(`max-age=${ALIAS_RECOVERY_MAX_AGE_SECONDS}`)
    expect(setCookie).toContain('path=/')

    expect(collector.event.waitUntil).toHaveBeenCalledTimes(1)
    await Promise.all(collector.promises)
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toBe('http://127.0.0.1:3000/api/omni/workbench/navigation-events')
    const headers = init?.headers as Record<string, string>
    expect(headers.Origin).toBe('http://127.0.0.1:3000')
    expect(headers.Cookie).toBe(APPROVAL_COOKIE)
    expect(headers.Cookie).not.toContain('theme')
    expect(JSON.parse(String(init?.body))).toEqual({
      event_type: 'legacy_alias',
      requested_href: '/qa',
      canonical_href: '/chat',
      feature_id: 'chat',
      result: 'redirected',
    })
  })

  it('redirects the legacy advertising-review URL to its canonical renderer with one telemetry attempt', async () => {
    const fetchMock = bffMock()
    const { handleWorkbenchMiddleware } = await middlewareWithFlag('1')
    const collector = eventCollector()
    const response = handleWorkbenchMiddleware(
      new NextRequest('http://localhost/marketing/review?source=legacy-bookmark', {
        headers: { Accept: 'text/html', Cookie: APPROVAL_COOKIE },
      }),
      collector.event as never,
    )

    expect(response.status).toBe(307)
    expect(response.headers.get('location')).toBe('http://localhost/ad-review?source=legacy-bookmark')
    expect(collector.event.waitUntil).toHaveBeenCalledTimes(1)
    await Promise.all(collector.promises)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      event_type: 'legacy_alias',
      requested_href: '/marketing/review',
      canonical_href: '/ad-review',
      feature_id: 'ad-review',
      result: 'redirected',
    })
  })

  it('consumes recovery on a canonical RSC navigation, emits recovered and clears the cookie', async () => {
    const fetchMock = bffMock()
    const { ALIAS_RECOVERY_COOKIE, handleWorkbenchMiddleware } = await middlewareWithFlag('1')
    const attemptCollector = eventCollector()
    const attempt = handleWorkbenchMiddleware(
      new NextRequest('http://localhost/qa?source=client', {
        headers: { Accept: 'text/html', Cookie: APPROVAL_COOKIE },
      }),
      attemptCollector.event as never,
    )
    await Promise.all(attemptCollector.promises)
    const recoveryValue = attempt.cookies.get(ALIAS_RECOVERY_COOKIE)?.value
    expect(recoveryValue).toBeTruthy()

    const recoveryCollector = eventCollector()
    const response = handleWorkbenchMiddleware(
      new NextRequest('http://localhost/chat?source=client', {
        headers: {
          Accept: 'text/x-component',
          RSC: '1',
          Cookie: `${APPROVAL_COOKIE}; ${ALIAS_RECOVERY_COOKIE}=${recoveryValue}`,
        },
      }),
      recoveryCollector.event as never,
    )

    expect(response.headers.get('x-middleware-next')).toBe('1')
    expect(cookieHeader(response).toLowerCase()).toContain('max-age=0')
    expect(recoveryCollector.event.waitUntil).toHaveBeenCalledTimes(1)
    await Promise.all(recoveryCollector.promises)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toMatchObject({
      event_type: 'legacy_alias',
      requested_href: '/qa',
      canonical_href: '/chat',
      feature_id: 'chat',
      result: 'recovered',
    })
  })

  it('emits failed on another page, while anonymous attempts never call the authenticated BFF', async () => {
    const fetchMock = bffMock()
    const { ALIAS_RECOVERY_COOKIE, handleWorkbenchMiddleware } = await middlewareWithFlag('1')
    const anonymousCollector = eventCollector()
    const attempt = handleWorkbenchMiddleware(
      new NextRequest('http://localhost/qa', { headers: { Accept: 'text/html' } }),
      anonymousCollector.event as never,
    )
    const recoveryValue = attempt.cookies.get(ALIAS_RECOVERY_COOKIE)?.value
    expect(recoveryValue).toBeTruthy()
    expect(anonymousCollector.event.waitUntil).not.toHaveBeenCalled()
    expect(fetchMock).not.toHaveBeenCalled()

    const failedCollector = eventCollector()
    const response = handleWorkbenchMiddleware(
      new NextRequest('http://localhost/workspace', {
        headers: {
          Accept: 'text/x-component',
          RSC: '1',
          Cookie: `${APPROVAL_COOKIE}; ${ALIAS_RECOVERY_COOKIE}=${recoveryValue}`,
        },
      }),
      failedCollector.event as never,
    )
    expect(cookieHeader(response).toLowerCase()).toContain('max-age=0')
    await Promise.all(failedCollector.promises)
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      event_type: 'legacy_alias',
      requested_href: '/qa',
      canonical_href: '/chat',
      feature_id: 'chat',
      result: 'failed',
    })
  })

  it('clears a tampered recovery identity without emitting telemetry', async () => {
    const fetchMock = bffMock()
    const { ALIAS_RECOVERY_COOKIE, handleWorkbenchMiddleware } = await middlewareWithFlag('1')
    const tampered = encodeURIComponent(JSON.stringify(['/qa', '/workspace', 'chat']))
    const collector = eventCollector()
    const response = handleWorkbenchMiddleware(
      new NextRequest('http://localhost/chat', {
        headers: {
          Accept: 'text/x-component',
          RSC: '1',
          Cookie: `${APPROVAL_COOKIE}; ${ALIAS_RECOVERY_COOKIE}=${tampered}`,
        },
      }),
      collector.event as never,
    )
    expect(cookieHeader(response).toLowerCase()).toContain('max-age=0')
    expect(collector.event.waitUntil).not.toHaveBeenCalled()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('does not consume recovery evidence for prefetch and keeps aliases alive when the Shell is flagged off', async () => {
    const fetchMock = bffMock()
    const enabled = await middlewareWithFlag('1')
    const attempt = enabled.handleWorkbenchMiddleware(
      new NextRequest('http://localhost/qa', { headers: { Accept: 'text/html' } }),
      eventCollector().event as never,
    )
    const recoveryValue = attempt.cookies.get(enabled.ALIAS_RECOVERY_COOKIE)?.value

    const prefetchCollector = eventCollector()
    const prefetch = enabled.handleWorkbenchMiddleware(
      new NextRequest('http://localhost/chat', {
        headers: {
          Accept: 'text/x-component',
          RSC: '1',
          'Next-Router-Prefetch': '1',
          Purpose: 'prefetch',
          Cookie: `${APPROVAL_COOKIE}; ${enabled.ALIAS_RECOVERY_COOKIE}=${recoveryValue}`,
        },
      }),
      prefetchCollector.event as never,
    )
    expect(cookieHeader(prefetch)).toBe('')
    expect(prefetchCollector.event.waitUntil).not.toHaveBeenCalled()

    const prefetchAliasCollector = eventCollector()
    const prefetchAlias = enabled.handleWorkbenchMiddleware(
      new NextRequest('http://localhost/qa', {
        headers: { Accept: 'text/x-component', 'Next-Router-Prefetch': '1', Cookie: APPROVAL_COOKIE },
      }),
      prefetchAliasCollector.event as never,
    )
    expect(prefetchAlias.status).toBe(307)
    expect(cookieHeader(prefetchAlias)).toBe('')
    expect(prefetchAliasCollector.event.waitUntil).not.toHaveBeenCalled()
    expect(fetchMock).not.toHaveBeenCalled()

    vi.resetModules()
    const disabled = await middlewareWithFlag('0')
    const disabledCollector = eventCollector()
    const response = disabled.handleWorkbenchMiddleware(
      new NextRequest('http://localhost/marketing/review?source=rollback', {
        headers: { Accept: 'text/html' },
      }),
      disabledCollector.event as never,
    )
    expect(response.status).toBe(307)
    expect(response.headers.get('location')).toBe('http://localhost/ad-review?source=rollback')
    expect(disabledCollector.event.waitUntil).not.toHaveBeenCalled()
  })

  it('canonicalizes the old workspace submodes only while the unified Shell is enabled', async () => {
    const enabled = await middlewareWithFlag('1')
    for (const [mode, expected] of [
      ['development', '/system-graph?source=bookmark'],
      ['execution', '/workspace/execution?source=bookmark'],
    ] as const) {
      const response = enabled.handleWorkbenchMiddleware(
        new NextRequest(`http://localhost/workspace?mode=${mode}&source=bookmark`, {
          headers: { Accept: 'text/html' },
        }),
        eventCollector().event as never,
      )
      expect(response.status).toBe(307)
      expect(response.headers.get('location')).toBe(`http://localhost${expected}`)
    }

    vi.resetModules()
    const disabled = await middlewareWithFlag('0')
    const legacy = disabled.handleWorkbenchMiddleware(
      new NextRequest('http://localhost/workspace?mode=development', {
        headers: { Accept: 'text/html' },
      }),
      eventCollector().event as never,
    )
    expect(legacy.headers.get('x-middleware-next')).toBe('1')
    expect(legacy.headers.get('location')).toBeNull()
  })

  it('keeps six real capability pages on their renderers instead of redirecting', async () => {
    const fetchMock = bffMock()
    const { handleWorkbenchMiddleware } = await middlewareWithFlag('1')
    for (const path of [
      '/ad-review/flywheel', '/content-leaderboard', '/decisions',
      '/insights', '/review', '/system-graph',
    ]) {
      const collector = eventCollector()
      const response = handleWorkbenchMiddleware(
        new NextRequest(`http://localhost${path}?source=bookmark`, {
          headers: { Accept: 'text/html', Cookie: APPROVAL_COOKIE },
        }),
        collector.event as never,
      )
      expect(response.headers.get('x-middleware-next')).toBe('1')
      expect(response.headers.get('location')).toBeNull()
      expect(collector.event.waitUntil).not.toHaveBeenCalled()
    }
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('passes unknown HTML routes to the App Router without raw HTML or anonymous telemetry', async () => {
    const fetchMock = bffMock()
    const { handleWorkbenchMiddleware } = await middlewareWithFlag('1')
    const collector = eventCollector()
    const response = handleWorkbenchMiddleware(
      new NextRequest('http://localhost/not-registered', { headers: { Accept: 'text/html' } }),
      collector.event as never,
    )

    expect(response.headers.get('x-middleware-next')).toBe('1')
    expect(response.headers.get('content-type')).toBeNull()
    expect(response.headers.get('x-omni-route-gap')).toBeNull()
    expect(await response.text()).toBe('')
    expect(collector.event.waitUntil).not.toHaveBeenCalled()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('ignores BFF 401, 429 and identity-unavailable responses without blocking alias navigation', async () => {
    const statuses = [401, 429, 503]
    const fetchMock = vi.fn(async () => new Response(null, { status: statuses.shift() || 503 }))
    vi.stubGlobal('fetch', fetchMock)
    const { handleWorkbenchMiddleware } = await middlewareWithFlag('1')
    for (let index = 0; index < 3; index += 1) {
      const collector = eventCollector()
      const response = handleWorkbenchMiddleware(
        new NextRequest(`http://localhost/qa?attempt=${index}`, {
          headers: { Accept: 'text/html', Cookie: APPROVAL_COOKIE },
        }),
        collector.event as never,
      )
      expect(response.status).toBe(307)
      await Promise.all(collector.promises)
    }
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('does not intercept excluded paths, non-page verbs or non-HTML unknown requests', async () => {
    const fetchMock = bffMock()
    const { handleWorkbenchMiddleware } = await middlewareWithFlag('1')
    for (const request of [
      new NextRequest('http://localhost/api/not-registered', { headers: { Accept: 'text/html', Cookie: APPROVAL_COOKIE } }),
      new NextRequest('http://localhost/_next/static/missing.js', { headers: { Accept: 'text/html', Cookie: APPROVAL_COOKIE } }),
      new NextRequest('http://localhost/assets/manual.pdf', { headers: { Accept: 'text/html', Cookie: APPROVAL_COOKIE } }),
      new NextRequest('http://localhost/not-registered', { method: 'POST', headers: { Accept: 'text/html', Cookie: APPROVAL_COOKIE } }),
      new NextRequest('http://localhost/not-registered', { headers: { Accept: 'application/json', Cookie: APPROVAL_COOKIE } }),
    ]) {
      const collector = eventCollector()
      const response = handleWorkbenchMiddleware(request, collector.event as never)
      expect(response.headers.get('x-middleware-next')).toBe('1')
      expect(collector.event.waitUntil).not.toHaveBeenCalled()
    }
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
