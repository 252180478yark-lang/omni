import { createHash } from 'node:crypto'

import { requireAuthenticatedActor, requireSameOrigin, ServiceFetchError, serviceBase } from '../../_shared'
import {
  isLegacyWorkbenchGroupId,
  LEGACY_WORKBENCH_IA_VERSION,
  resolveLegacyWorkbenchNavigation,
  type LegacyWorkbenchGroupId,
} from '@/lib/workbench-ia-compat'
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
  primary_group?: WorkbenchGroupId | LegacyWorkbenchGroupId
  secondary_depth?: number
  result: NavigationResult
}

const EVENT_TYPES = new Set<NavigationEventType>(['legacy_alias', 'primary_navigation', 'route_gap'])
const RESULTS = new Set<NavigationResult>([
  'redirected', 'recovered', 'failed', 'selected', 'opened', 'unregistered', 'ambiguous',
])
const MODES = new Set<WorkbenchMode>(['work', 'development'])
const CURRENT_WORKBENCH_IA_VERSION = 'workbench-ia-v2' as const
const CURRENT_GROUPS = new Set<WorkbenchGroupId>([
  'production', 'analysis', 'library',
  'agent-tools', 'quality', 'system',
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
  version: typeof LEGACY_WORKBENCH_IA_VERSION | typeof CURRENT_WORKBENCH_IA_VERSION
  exclusive: boolean
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
    (primaryGroup !== undefined && (
      typeof primaryGroup !== 'string' ||
      (!CURRENT_GROUPS.has(primaryGroup as WorkbenchGroupId) && !isLegacyWorkbenchGroupId(primaryGroup))
    )) ||
    (secondaryDepth !== undefined && (!Number.isInteger(secondaryDepth) || Number(secondaryDepth) < 0 || Number(secondaryDepth) > 20))
  ) return null
  return {
    event_type: eventType as NavigationEventType,
    requested_href: requestedHref,
    canonical_href: canonicalHref,
    feature_id: featureId as string | undefined,
    mode: mode as WorkbenchMode | undefined,
    primary_group: primaryGroup as WorkbenchGroupId | LegacyWorkbenchGroupId | undefined,
    secondary_depth: secondaryDepth as number | undefined,
    result: result as NavigationResult,
  }
}

function routeSlug(pathname: string): string {
  const slug = pathname === '/'
    ? 'root'
    : pathname.slice(1).replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-|-$/g, '').toLowerCase()
  if (slug && slug.length <= 72) return slug
  return `sha256-${createHash('sha256').update(pathname).digest('hex').slice(0, 16)}`
}

function validateContract(input: NavigationEventInput): ValidatedNavigationContract | null {
  if (input.event_type === 'primary_navigation' && input.primary_group && isLegacyWorkbenchGroupId(input.primary_group)) {
    if (
      !['selected', 'opened'].includes(input.result) ||
      !input.feature_id || !input.mode
    ) return null
    const legacy = resolveLegacyWorkbenchNavigation({
      featureId: input.feature_id,
      requestedHref: input.requested_href,
      canonicalHref: input.canonical_href,
      mode: input.mode,
      primaryGroup: input.primary_group,
      secondaryDepth: input.secondary_depth,
    })
    if (!legacy) return null
    return {
      capabilityId: `navigation:${input.feature_id}`,
      routeFamily: `workbench-nav:${input.mode}:${input.primary_group}:depth-${legacy.expectedDepth}`,
      version: legacy.version,
      exclusive: legacy.exclusive,
    }
  }

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
      version: CURRENT_WORKBENCH_IA_VERSION,
      exclusive: false,
    }
  }
  if (input.event_type === 'route_gap') {
    if (
      !['unregistered', 'ambiguous'].includes(location.kind) ||
      input.result !== location.kind || input.canonical_href !== undefined ||
      input.feature_id !== undefined
    ) return null
    const fingerprint = createHash('sha256').update(location.requestedHref).digest('hex').slice(0, 16)
    return {
      capabilityId: `route-gap:sha256-${fingerprint}`,
      routeFamily: 'workbench-gap',
      version: CURRENT_WORKBENCH_IA_VERSION,
      exclusive: false,
    }
  }
  if (
    !location.featureId || ['alias', 'unregistered', 'ambiguous'].includes(location.kind) ||
    !['selected', 'opened'].includes(input.result) || input.feature_id !== location.featureId ||
    input.canonical_href !== location.canonicalHref || !input.mode || !input.primary_group ||
    !CURRENT_GROUPS.has(input.primary_group as WorkbenchGroupId)
  ) return null
  const primaryGroup = input.primary_group as WorkbenchGroupId
  const placementMatches =
    (location.primary?.mode === input.mode && location.primary.group === primaryGroup) ||
    location.contextualGroups.some((group) => group.mode === input.mode && group.group === primaryGroup)
  if (!placementMatches) return null
  const navigationGroup = workbenchNavigationForMode(input.mode)
    .find((group) => group.id === primaryGroup)
  const landing = navigationGroup?.entries[0]
  const expectedDepth = landing?.featureId === location.featureId ? 0 : 1
  if (!landing || input.secondary_depth !== expectedDepth) return null
  return {
    capabilityId: `navigation:${location.featureId}`,
    routeFamily: `workbench-nav:${input.mode}:${primaryGroup}:depth-${expectedDepth}`,
    version: CURRENT_WORKBENCH_IA_VERSION,
    exclusive: false,
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
    .update([input.event_type, input.result, contract.capabilityId, contract.routeFamily, contract.version].join('\n'))
    .digest('hex')
}

async function submitCompatibilityTelemetry(
  input: NavigationEventInput,
  contract: ValidatedNavigationContract,
  observedAt: string,
): Promise<boolean> {
  try {
    const response = await fetch(`${serviceBase().knowledge}/api/v1/compatibility/telemetry`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        client_id: 'web-workbench',
        capability_id: contract.capabilityId,
        route_family: contract.routeFamily,
        exclusive: contract.exclusive,
        observed_at: observedAt,
        metadata: {
          state: input.result,
          reason_code: input.event_type,
          version: contract.version,
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
