const DEFAULTS = {
  gateway: '',
  aiHub: 'http://localhost:8001',
  knowledge: 'http://localhost:8002',
  newsAggregator: 'http://localhost:8005',
  videoAnalysis: 'http://localhost:8006',
  livestreamAnalysis: 'http://localhost:8007',
  adReview: 'http://localhost:8008',
  scoutAgent: 'http://localhost:8009',
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

export interface ApprovalActor {
  id: string
  role: 'admin' | 'owner'
}

export interface AuthenticatedActor {
  id: string
  role: 'admin' | 'owner' | 'user'
}

export const LOCAL_OWNER: ApprovalActor = Object.freeze({ id: 'local-owner', role: 'owner' })

export async function verifyAuthenticatedActor(authorization: string | null): Promise<AuthenticatedActor> {
  void authorization
  return LOCAL_OWNER
}

export async function verifyApprovalActor(authorization: string | null): Promise<ApprovalActor> {
  const actor = await verifyAuthenticatedActor(authorization)
  if (actor.role !== 'admin' && actor.role !== 'owner') {
    throw new ServiceFetchError('approval permission required', {
      status: 403,
      source: 'frontend:local-owner',
      code: 'approval_admin_required',
    })
  }
  return { id: actor.id, role: actor.role }
}

export async function requireApprovalActor(request: Request): Promise<ApprovalActor> {
  void request
  return LOCAL_OWNER
}

export async function requireAuthenticatedActor(request: Request): Promise<AuthenticatedActor> {
  void request
  return LOCAL_OWNER
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
  void method
  void url
  void body
  return {
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
