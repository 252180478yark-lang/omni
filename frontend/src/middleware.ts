import { NextResponse, type NextFetchEvent, type NextRequest } from 'next/server'

import { isWorkbenchFlagEnabled } from '@/lib/workbench-flags'
import { resolveWorkbenchLocation, type WorkbenchLocation } from '@/lib/workbench-ia'

const EXCLUDED_PATHS = /^(?:\/api(?:\/|$)|\/_next(?:\/|$)|\/favicon\.ico$|\/manifest\.json$|\/icon(?:-[^/]+)?\.svg$|\/robots\.txt$|\/sitemap\.xml$|\/.*\.[a-zA-Z0-9]+$)/
const APPROVAL_SESSION_COOKIE = 'omni_approval_session'
export const ALIAS_RECOVERY_COOKIE = 'omni_alias_recovery'
export const ALIAS_RECOVERY_MAX_AGE_SECONDS = 120

type AliasRecoveryResult = 'redirected' | 'recovered' | 'failed'

interface AliasIdentity {
  requestedHref: string
  canonicalHref: string
  featureId: string
}

interface NavigationEventBody {
  event_type: 'legacy_alias'
  requested_href: string
  canonical_href: string
  feature_id: string
  result: AliasRecoveryResult
}

function isPageMethod(request: NextRequest): boolean {
  return request.method === 'GET' || request.method === 'HEAD'
}

function isHtmlNavigation(request: NextRequest): boolean {
  return isPageMethod(request) && (request.headers.get('accept') || '').toLowerCase().includes('text/html')
}

function isPrefetch(request: NextRequest): boolean {
  return (
    request.headers.get('next-router-prefetch') === '1' ||
    request.headers.get('x-middleware-prefetch') === '1' ||
    (request.headers.get('purpose') || '').toLowerCase() === 'prefetch' ||
    (request.headers.get('sec-purpose') || '').toLowerCase().includes('prefetch')
  )
}

function consumesAliasRecovery(request: NextRequest, location: WorkbenchLocation): boolean {
  if (!isPageMethod(request) || isPrefetch(request)) return false
  return (
    isHtmlNavigation(request) ||
    location.kind === 'canonical' ||
    location.kind === 'owned' ||
    location.kind === 'alias'
  )
}

function aliasIdentity(location: WorkbenchLocation): AliasIdentity | undefined {
  if (location.kind !== 'alias' || !location.featureId) return undefined
  const validated = resolveWorkbenchLocation(location.requestedHref)
  if (
    validated.kind !== 'alias' ||
    validated.canonicalHref !== location.canonicalHref ||
    validated.featureId !== location.featureId
  ) return undefined
  return {
    requestedHref: validated.requestedHref,
    canonicalHref: validated.canonicalHref,
    featureId: validated.featureId,
  }
}

function encodeAliasIdentity(identity: AliasIdentity): string {
  return encodeURIComponent(JSON.stringify([
    identity.requestedHref,
    identity.canonicalHref,
    identity.featureId,
  ]))
}

function decodeAliasIdentity(value: string): AliasIdentity | undefined {
  if (!value || value.length > 768) return undefined
  try {
    const parsed: unknown = JSON.parse(decodeURIComponent(value))
    if (
      !Array.isArray(parsed) || parsed.length !== 3 ||
      parsed.some((item) => typeof item !== 'string')
    ) return undefined
    const [requestedHref, canonicalHref, featureId] = parsed as [string, string, string]
    const validated = resolveWorkbenchLocation(requestedHref)
    if (
      validated.kind !== 'alias' ||
      validated.canonicalHref !== canonicalHref ||
      validated.featureId !== featureId
    ) return undefined
    return { requestedHref: validated.requestedHref, canonicalHref, featureId }
  } catch {
    return undefined
  }
}

function aliasTelemetryBody(identity: AliasIdentity, result: AliasRecoveryResult): NavigationEventBody {
  return {
    event_type: 'legacy_alias',
    requested_href: identity.requestedHref,
    canonical_href: identity.canonicalHref,
    feature_id: identity.featureId,
    result,
  }
}

function internalNavigationEventsUrl(): URL {
  const parsedPort = Number(process.env.PORT || '3000')
  const port = Number.isInteger(parsedPort) && parsedPort > 0 && parsedPort <= 65_535
    ? parsedPort
    : 3000
  return new URL('/api/omni/workbench/navigation-events', `http://127.0.0.1:${port}`)
}

function incomingApprovalCookie(request: NextRequest): string | undefined {
  const value = request.cookies.get(APPROVAL_SESSION_COOKIE)?.value
  if (!value || value.length > 8192) return undefined
  return `${APPROVAL_SESSION_COOKIE}=${encodeURIComponent(value)}`
}

async function postNavigationEvent(cookie: string, body: NavigationEventBody): Promise<void> {
  try {
    const endpoint = internalNavigationEventsUrl()
    await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: cookie,
        Origin: endpoint.origin,
      },
      body: JSON.stringify(body),
      cache: 'no-store',
      signal: AbortSignal.timeout(2000),
    })
  } catch {
    // Compatibility telemetry is append-only evidence and must never block navigation.
  }
}

function queueNavigationEvent(event: NextFetchEvent, request: NextRequest, body: NavigationEventBody): void {
  const cookie = incomingApprovalCookie(request)
  if (cookie) event.waitUntil(postNavigationEvent(cookie, body))
}

function setRecoveryCookie(response: NextResponse, request: NextRequest, identity: AliasIdentity): void {
  response.cookies.set({
    name: ALIAS_RECOVERY_COOKIE,
    value: encodeAliasIdentity(identity),
    httpOnly: true,
    sameSite: 'lax',
    secure: request.nextUrl.protocol === 'https:',
    path: '/',
    maxAge: ALIAS_RECOVERY_MAX_AGE_SECONDS,
  })
}

function clearRecoveryCookie(response: NextResponse, request: NextRequest): void {
  response.cookies.set({
    name: ALIAS_RECOVERY_COOKIE,
    value: '',
    httpOnly: true,
    sameSite: 'lax',
    secure: request.nextUrl.protocol === 'https:',
    path: '/',
    maxAge: 0,
  })
}

export function handleWorkbenchMiddleware(request: NextRequest, event: NextFetchEvent): NextResponse {
  if (
    EXCLUDED_PATHS.test(request.nextUrl.pathname) ||
    !isPageMethod(request)
  ) return NextResponse.next()

  const unified = isWorkbenchFlagEnabled('unified_shell')
  if (unified && request.nextUrl.pathname === '/workspace') {
    const legacyMode = request.nextUrl.searchParams.get('mode')
    const canonicalPath = legacyMode === 'development'
      ? '/system-graph'
      : legacyMode === 'execution'
        ? '/workspace/execution'
        : null
    if (canonicalPath) {
      const target = request.nextUrl.clone()
      target.pathname = canonicalPath
      target.searchParams.delete('mode')
      return NextResponse.redirect(target, 307)
    }
  }

  const location = resolveWorkbenchLocation(request.nextUrl.pathname, request.nextUrl.searchParams)
  const navigationRequest = consumesAliasRecovery(request, location)
  const recoveryValue = navigationRequest
    ? request.cookies.get(ALIAS_RECOVERY_COOKIE)?.value
    : undefined
  const recoveryIdentity = recoveryValue === undefined ? undefined : decodeAliasIdentity(recoveryValue)
  if (recoveryIdentity) {
    const recovered =
      location.kind === 'canonical' &&
      location.requestedHref === recoveryIdentity.canonicalHref &&
      location.canonicalHref === recoveryIdentity.canonicalHref &&
      location.featureId === recoveryIdentity.featureId
    queueNavigationEvent(
      event,
      request,
      aliasTelemetryBody(recoveryIdentity, recovered ? 'recovered' : 'failed'),
    )
  }

  if (location.kind === 'alias') {
    const identity = aliasIdentity(location)
    if (identity && navigationRequest) {
      queueNavigationEvent(event, request, aliasTelemetryBody(identity, 'redirected'))
    }
    const target = request.nextUrl.clone()
    target.pathname = location.canonicalHref
    const response = NextResponse.redirect(target, 307)
    if (identity && navigationRequest) setRecoveryCookie(response, request, identity)
    else if (recoveryValue !== undefined) clearRecoveryCookie(response, request)
    return response
  }

  const response = NextResponse.next()
  if (recoveryValue !== undefined) clearRecoveryCookie(response, request)
  return response
}

export function middleware(request: NextRequest, event: NextFetchEvent): NextResponse {
  return handleWorkbenchMiddleware(request, event)
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico|manifest.json|icon).*)'],
}
