import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'

import { requireAuthenticatedActor, requireSameOrigin, ServiceFetchError, serviceBase } from '../../_shared'
import {
  resolveWorkbenchLocation,
  workbenchNavigationForMode,
  type WorkbenchGroupId,
  type WorkbenchMode,
} from '@/lib/workbench-ia'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

type NavigationEventType = 'legacy_alias' | 'primary_navigation' | 'route_gap'
type NavigationResult =
  | 'redirected'
  | 'recovered'
  | 'failed'
  | 'selected'
  | 'opened'
  | 'unregistered'
  | 'ambiguous'

interface NavigationEventInput {
  event_type: NavigationEventType
  requested_href: string
  canonical_href?: string
  feature_id?: string
  mode?: WorkbenchMode
  primary_group?: WorkbenchGroupId
  secondary_depth?: number
  result: NavigationResult
}

const EVENT_TYPES = new Set<NavigationEventType>(['legacy_alias', 'primary_navigation', 'route_gap'])
const RESULTS = new Set<NavigationResult>([
  'redirected', 'recovered', 'failed', 'selected', 'opened', 'unregistered', 'ambiguous',
])
const MODES = new Set<WorkbenchMode>(['work', 'development'])
const GROUPS = new Set<WorkbenchGroupId>([
  'today', 'products', 'operations', 'content', 'knowledge',
  'agents', 'skills-tools', 'workflows', 'prompt-eval', 'runs-system',
])
const ALLOWED_KEYS = new Set([
  'event_type', 'requested_href', 'canonical_href', 'feature_id',
  'mode', 'primary_group', 'secondary_depth', 'result',
])
const RATE_LIMIT_PER_ACTOR_PER_MINUTE = 60
const MAX_TRACKED_ACTORS = 256

interface ValidatedNavigationContract {
  capabilityId: string
  routeFamily: string
}

interface ActorMinuteWindow {
  minute: number
  requests: number
  outcomes: Map<string, Promise<boolean>>
}

const actorWindows = new Map<string, ActorMinuteWindow>()

function typedError(code: string, status: number, retryable = false): Response {
  return Response.json(
    { success: false, error: { code, retryable } },
    { status },
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function pathValue(value: unknown): string | undefined {
  return typeof value === 'string' && /^\/[^?#]{0,511}$/.test(value) ? value : undefined
}

function parseInput(value: unknown): NavigationEventInput | null {
  if (!isRecord(value) || Object.keys(value).some((key) => !ALLOWED_KEYS.has(key))) return null
  const eventType = value.event_type
  const result = value.result
  const requestedHref = pathValue(value.requested_href)
  const canonicalHref = value.canonical_href === undefined ? undefined : pathValue(value.canonical_href)
  const featureId = value.feature_id
  const mode = value.mode
  const primaryGroup = value.primary_group
  const secondaryDepth = value.secondary_depth
  if (
    typeof eventType !== 'string' || !EVENT_TYPES.has(eventType as NavigationEventType) ||
    typeof result !== 'string' || !RESULTS.has(result as NavigationResult) ||
    !requestedHref ||
    (value.canonical_href !== undefined && !canonicalHref) ||
    (featureId !== undefined && (typeof featureId !== 'string' || !/^[a-z][a-z0-9-]{2,63}$/.test(featureId))) ||
    (mode !== undefined && (typeof mode !== 'string' || !MODES.has(mode as WorkbenchMode))) ||
    (primaryGroup !== undefined && (typeof primaryGroup !== 'string' || !GROUPS.has(primaryGroup as WorkbenchGroupId))) ||
    (secondaryDepth !== undefined && (!Number.isInteger(secondaryDepth) || Number(secondaryDepth) < 0 || Number(secondaryDepth) > 20))
  ) return null
  return {
    event_type: eventType as NavigationEventType,
    requested_href: requestedHref,
    canonical_href: canonicalHref,
    feature_id: featureId as string | undefined,
    mode: mode as WorkbenchMode | undefined,
    primary_group: primaryGroup as WorkbenchGroupId | undefined,
    secondary_depth: secondaryDepth as number | undefined,
    result: result as NavigationResult,
  }
}

function compatibilityToken(): string {
  const path = process.env.OMNI_COMPATIBILITY_TOKEN_FILE?.trim()
  if (!path) throw new Error('compatibility_token_unconfigured')
  let token = ''
  try {
    token = readFileSync(path, 'utf8').trim()
  } catch {
    throw new Error('compatibility_token_unavailable')
  }
  if (token.length < 24) throw new Error('compatibility_token_invalid')
  return token
}

function routeSlug(pathname: string): string {
  const slug = pathname === '/'
    ? 'root'
    : pathname.slice(1).replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-|-$/g, '').toLowerCase()
  if (slug && slug.length <= 72) return slug
  return `sha256-${createHash('sha256').update(pathname).digest('hex').slice(0, 16)}`
}

function validateContract(input: NavigationEventInput): ValidatedNavigationContract | null {
  const location = resolveWorkbenchLocation(input.requested_href)
  if (input.event_type === 'legacy_alias') {
    if (
      location.kind !== 'alias' || !['redirected', 'recovered', 'failed'].includes(input.result) ||
      input.canonical_href !== location.canonicalHref ||
      input.feature_id !== location.featureId
    ) return null
    return {
      capabilityId: `legacy-alias:${routeSlug(location.requestedHref)}:${location.featureId}`,
      routeFamily: `workbench-alias:${routeSlug(location.canonicalHref)}`,
    }
  }
  if (input.event_type === 'route_gap') {
    if (
      !['unregistered', 'ambiguous'].includes(location.kind) ||
      input.result !== location.kind || input.canonical_href !== undefined ||
      input.feature_id !== undefined
    ) return null
    const fingerprint = createHash('sha256').update(location.requestedHref).digest('hex').slice(0, 16)
    return { capabilityId: `route-gap:sha256-${fingerprint}`, routeFamily: 'workbench-gap' }
  }
  if (
    !location.featureId || ['alias', 'unregistered', 'ambiguous'].includes(location.kind) ||
    !['selected', 'opened'].includes(input.result) || input.feature_id !== location.featureId ||
    input.canonical_href !== location.canonicalHref || !input.mode || !input.primary_group
  ) return null
  const placementMatches =
    (location.primary?.mode === input.mode && location.primary.group === input.primary_group) ||
    location.contextualGroups.some((group) => group.mode === input.mode && group.group === input.primary_group)
  if (!placementMatches) return null
  const navigationGroup = workbenchNavigationForMode(input.mode)
    .find((group) => group.id === input.primary_group)
  const landing = navigationGroup?.entries[0]
  const expectedDepth = landing?.featureId === location.featureId ? 0 : 1
  if (!landing || input.secondary_depth !== expectedDepth) return null
  return {
    capabilityId: `navigation:${location.featureId}`,
    routeFamily: `workbench-nav:${input.mode}:${input.primary_group}:depth-${expectedDepth}`,
  }
}

function actorMinuteWindow(actorId: string, minute: number): ActorMinuteWindow {
  const key = createHash('sha256').update(actorId).digest('hex')
  const existing = actorWindows.get(key)
  if (existing?.minute === minute) {
    actorWindows.delete(key)
    actorWindows.set(key, existing)
    return existing
  }
  if (existing) actorWindows.delete(key)
  while (actorWindows.size >= MAX_TRACKED_ACTORS) {
    const oldest = actorWindows.keys().next().value
    if (typeof oldest !== 'string') break
    actorWindows.delete(oldest)
  }
  const created: ActorMinuteWindow = { minute, requests: 0, outcomes: new Map() }
  actorWindows.set(key, created)
  return created
}

function outcomeKey(input: NavigationEventInput, contract: ValidatedNavigationContract): string {
  return createHash('sha256')
    .update([input.event_type, input.result, contract.capabilityId, contract.routeFamily].join('\n'))
    .digest('hex')
}

async function submitCompatibilityTelemetry(
  input: NavigationEventInput,
  contract: ValidatedNavigationContract,
  observedAt: string,
): Promise<boolean> {
  let token: string
  try {
    token = compatibilityToken()
  } catch {
    return false
  }
  try {
    const response = await fetch(`${serviceBase().knowledge}/api/v1/compatibility/telemetry`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        client_id: 'web-workbench',
        capability_id: contract.capabilityId,
        route_family: contract.routeFamily,
        exclusive: false,
        observed_at: observedAt,
        metadata: {
          state: input.result,
          reason_code: input.event_type,
        },
      }),
      cache: 'no-store',
      signal: AbortSignal.timeout(1500),
    })
    return response.ok
  } catch {
    return false
  }
}

export async function POST(request: Request): Promise<Response> {
  try {
    requireSameOrigin(request)
  } catch (error) {
    return typedError(error instanceof ServiceFetchError ? error.code : 'csrf_rejected', 403)
  }

  let actorId: string
  try {
    actorId = (await requireAuthenticatedActor(request)).id
  } catch (error) {
    if (error instanceof ServiceFetchError) {
      return typedError(error.code, error.status, error.status >= 500)
    }
    return typedError('identity_verification_unavailable', 503, true)
  }

  const minute = Math.floor(Date.now() / 60_000)
  const actorWindow = actorMinuteWindow(actorId, minute)
  actorWindow.requests += 1
  if (actorWindow.requests > RATE_LIMIT_PER_ACTOR_PER_MINUTE) {
    return typedError('navigation_event_rate_limited', 429, true)
  }

  let raw = ''
  const contentLength = Number(request.headers.get('content-length') || 0)
  if (Number.isFinite(contentLength) && contentLength > 4096) {
    return typedError('invalid_navigation_event', 400)
  }
  try {
    raw = await request.text()
  } catch {
    return typedError('invalid_navigation_event', 400)
  }
  if (!raw || raw.length > 4096) return typedError('invalid_navigation_event', 400)

  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return typedError('invalid_navigation_event', 400)
  }
  const input = parseInput(parsed)
  if (!input) return typedError('invalid_navigation_event', 400)
  const contract = validateContract(input)
  if (!contract) return typedError('navigation_event_contract_mismatch', 400)

  const key = outcomeKey(input, contract)
  const existing = actorWindow.outcomes.get(key)
  if (existing) {
    if (await existing) {
      return Response.json({ success: true, accepted: true, deduplicated: true }, { status: 202 })
    }
    return typedError('compatibility_telemetry_unavailable', 503, true)
  }

  const submission = submitCompatibilityTelemetry(
    input,
    contract,
    new Date(minute * 60_000).toISOString(),
  )
  actorWindow.outcomes.set(key, submission)
  const accepted = await submission
  if (!accepted) {
    if (actorWindow.outcomes.get(key) === submission) actorWindow.outcomes.delete(key)
    return typedError('compatibility_telemetry_unavailable', 503, true)
  }
  return Response.json({ success: true, accepted: true }, { status: 202 })
}
