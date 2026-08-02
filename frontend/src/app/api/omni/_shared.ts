import { createHash, createHmac, randomUUID } from 'node:crypto'
import { readFileSync } from 'node:fs'

const DEFAULTS = {
  gateway: '',
  aiHub: 'http://localhost:8001',
  knowledge: 'http://localhost:8002',
  newsAggregator: 'http://localhost:8005',
  videoAnalysis: 'http://localhost:8006',
  livestreamAnalysis: 'http://localhost:8007',
  adReview: 'http://localhost:8008',
  scoutAgent: 'http://localhost:8009',
  identity: 'http://localhost:8000',
}

function trimSlash(value: string): string {
  return value.endsWith('/') ? value.slice(0, -1) : value
}

export function serviceBase() {
  const gateway = trimSlash(process.env.OMNI_API_BASE_URL || DEFAULTS.gateway)
  const fallback = gateway || ''
  return {
    // In local dev (without OMNI_API_BASE_URL), prefer direct service ports.
    aiHub: trimSlash(process.env.AI_PROVIDER_HUB_URL || fallback || DEFAULTS.aiHub),
    knowledge: trimSlash(process.env.KNOWLEDGE_ENGINE_URL || fallback || DEFAULTS.knowledge),
    newsAggregator: trimSlash(process.env.NEWS_AGGREGATOR_URL || fallback || DEFAULTS.newsAggregator),
    videoAnalysis: trimSlash(process.env.VIDEO_ANALYSIS_SERVICE_URL || fallback || DEFAULTS.videoAnalysis),
    livestreamAnalysis: trimSlash(process.env.LIVESTREAM_ANALYSIS_SERVICE_URL || fallback || DEFAULTS.livestreamAnalysis),
    adReview: trimSlash(process.env.AD_REVIEW_SERVICE_URL || fallback || DEFAULTS.adReview),
    scoutAgent: trimSlash(process.env.SCOUT_AGENT_URL || fallback || DEFAULTS.scoutAgent),
    identity: trimSlash(process.env.IDENTITY_SERVICE_URL || fallback || DEFAULTS.identity),
  }
}

export interface ServiceOperationError {
  code: string
  message: string
  source: string
  status: number
  retryable: boolean
  details?: Record<string, unknown>
}

export class ServiceFetchError extends Error {
  readonly status: number
  readonly source: string
  readonly body: unknown
  readonly code: string

  constructor(message: string, options: { status: number; source: string; body?: unknown; code?: string }) {
    super(message)
    this.name = 'ServiceFetchError'
    this.status = options.status
    this.source = options.source
    this.body = options.body
    this.code = options.code || 'upstream_error'
  }
}

function approvalServiceSecret(): Buffer {
  const path = process.env.OMNI_APPROVAL_SERVICE_SECRET_FILE?.trim()
  if (!path) {
    throw new ServiceFetchError('approval service identity is unavailable', {
      status: 503,
      source: 'frontend:approval-auth',
      code: 'approval_service_identity_unavailable',
    })
  }
  let secret: Buffer
  try {
    secret = readFileSync(path)
  } catch {
    throw new ServiceFetchError('approval service identity is unavailable', {
      status: 503,
      source: 'frontend:approval-auth',
      code: 'approval_service_identity_unavailable',
    })
  }
  if (secret.length < 32) {
    throw new ServiceFetchError('approval service identity is invalid', {
      status: 503,
      source: 'frontend:approval-auth',
      code: 'approval_service_identity_invalid',
    })
  }
  return secret
}

export interface ApprovalActor {
  id: string
  role: 'admin' | 'owner'
}

export interface AuthenticatedActor {
  id: string
  role: 'admin' | 'owner' | 'user'
}

export const APPROVAL_SESSION_COOKIE = 'omni_approval_session'

function cookieValue(cookieHeader: string | null, name: string): string | null {
  if (!cookieHeader) return null
  for (const item of cookieHeader.split(';')) {
    const separator = item.indexOf('=')
    if (separator < 1 || item.slice(0, separator).trim() !== name) continue
    try {
      const value = decodeURIComponent(item.slice(separator + 1).trim())
      return value && value.length <= 8192 ? value : null
    } catch {
      return null
    }
  }
  return null
}

export function approvalAuthorizationFromCookie(cookieHeader: string | null): string | null {
  const token = cookieValue(cookieHeader, APPROVAL_SESSION_COOKIE)
  return token ? `Bearer ${token}` : null
}

export async function verifyAuthenticatedActor(authorization: string | null): Promise<AuthenticatedActor> {
  if (!authorization || !/^Bearer\s+\S+$/i.test(authorization)) {
    throw new ServiceFetchError('authentication required', {
      status: 401,
      source: 'identity-service:verify',
      code: 'authentication_required',
    })
  }
  let response: Response
  try {
    response = await fetch(`${serviceBase().identity}/api/v1/auth/verify`, {
      headers: { Authorization: authorization },
      cache: 'no-store',
      signal: AbortSignal.timeout(3000),
    })
  } catch {
    throw new ServiceFetchError('identity verification unavailable', {
      status: 503,
      source: 'identity-service:verify',
      code: 'identity_verification_unavailable',
    })
  }
  let body: unknown
  try { body = await response.json() } catch { body = null }
  const data = body && typeof body === 'object' && 'data' in body
    ? (body as { data?: unknown }).data
    : null
  const actor = data && typeof data === 'object' ? data as Record<string, unknown> : null
  const id = typeof actor?.sub === 'string' ? actor.sub : ''
  const role = typeof actor?.role === 'string' ? actor.role.toLowerCase() : ''
  if (!response.ok || actor?.valid !== true || !/^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$/.test(id)) {
    throw new ServiceFetchError('authentication required', {
      status: 401,
      source: 'identity-service:verify',
      code: 'authentication_required',
    })
  }
  if (role !== 'admin' && role !== 'owner' && role !== 'user') {
    throw new ServiceFetchError('authentication required', {
      status: 401,
      source: 'identity-service:verify',
      code: 'authentication_required',
    })
  }
  return { id, role }
}

export async function verifyApprovalActor(authorization: string | null): Promise<ApprovalActor> {
  const actor = await verifyAuthenticatedActor(authorization)
  if (actor.role !== 'admin' && actor.role !== 'owner') {
    throw new ServiceFetchError('approval permission required', {
      status: 403,
      source: 'identity-service:verify',
      code: 'approval_admin_required',
    })
  }
  return { id: actor.id, role: actor.role }
}

export async function requireApprovalActor(request: Request): Promise<ApprovalActor> {
  const authorization = request.headers.get('authorization')
    || approvalAuthorizationFromCookie(request.headers.get('cookie'))
  return verifyApprovalActor(authorization)
}

export async function requireAuthenticatedActor(request: Request): Promise<AuthenticatedActor> {
  const authorization = request.headers.get('authorization')
    || approvalAuthorizationFromCookie(request.headers.get('cookie'))
  return verifyAuthenticatedActor(authorization)
}

export function requireSameOrigin(request: Request): void {
  const origin = request.headers.get('origin')
  if (!origin) {
    throw new ServiceFetchError('same-origin request required', {
      status: 403,
      source: 'frontend:csrf',
      code: 'csrf_origin_required',
    })
  }
  let originUrl: URL
  try {
    originUrl = new URL(origin)
  } catch {
    throw new ServiceFetchError('same-origin request required', {
      status: 403,
      source: 'frontend:csrf',
      code: 'csrf_origin_invalid',
    })
  }
  const requestUrl = new URL(request.url)
  const forwardedHost = request.headers.get('x-forwarded-host')?.split(',')[0]?.trim()
  const expectedHost = forwardedHost || request.headers.get('host') || requestUrl.host
  const forwardedProto = request.headers.get('x-forwarded-proto')?.split(',')[0]?.trim()
  const expectedProtocol = forwardedProto ? `${forwardedProto}:` : requestUrl.protocol
  if (originUrl.host !== expectedHost || originUrl.protocol !== expectedProtocol) {
    throw new ServiceFetchError('same-origin request required', {
      status: 403,
      source: 'frontend:csrf',
      code: 'csrf_origin_mismatch',
    })
  }
}

export function approvalServiceHeaders(
  method: string,
  url: string,
  actor: ApprovalActor,
  body = '',
): Record<string, string> {
  const serviceId = 'frontend'
  const timestamp = Math.floor(Date.now() / 1000).toString()
  const nonce = randomUUID()
  const parsed = new URL(url)
  const target = `${parsed.pathname}${parsed.search}`
  const bodyHash = createHash('sha256').update(body).digest('hex')
  const canonical = [
    serviceId,
    timestamp,
    nonce,
    method.toUpperCase(),
    target,
    bodyHash,
    actor.id,
    actor.role,
  ].join('\n')
  const signature = createHmac('sha256', approvalServiceSecret()).update(canonical).digest('hex')
  return {
    'X-Omni-Service-Id': serviceId,
    'X-Omni-Timestamp': timestamp,
    'X-Omni-Nonce': nonce,
    'X-Omni-Body-SHA256': bodyHash,
    'X-Omni-Signature': signature,
    'X-Omni-Actor-Id': actor.id,
    'X-Omni-Actor-Role': actor.role,
  }
}

export async function fetchJson<T>(url: string, init?: RequestInit, source = url): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    cache: 'no-store',
  })
  const raw = await response.text()
  let body: unknown = null
  if (raw) {
    try { body = JSON.parse(raw) } catch { body = raw }
  }
  if (!response.ok) {
    const object = body && typeof body === 'object' ? body as Record<string, unknown> : null
    const nested = object?.error && typeof object.error === 'object'
      ? object.error as Record<string, unknown>
      : null
    const detail = String(object?.detail || nested?.message || object?.message || raw || `${response.status} ${response.statusText}`)
    throw new ServiceFetchError(detail, {
      status: response.status,
      source,
      body,
      code: String(nested?.code || object?.code || 'upstream_error'),
    })
  }
  return body as T
}
