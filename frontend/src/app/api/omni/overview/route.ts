import { ServiceFetchError, serviceBase, type ServiceOperationError } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

type HealthState = 'healthy' | 'degraded' | 'unavailable' | 'stale' | 'unknown'
type JsonRecord = Record<string, unknown>

interface BuildIdentity {
  expected_commit: string | null
  observed_commit: string | null
  expected_source_fingerprint: string | null
  source_fingerprint: string | null
  worktree_id: string | null
  allocation_id: string | null
  runtime_id: string | null
}

interface DependencyHealth {
  dependency_id: string
  ref: string
  required: boolean
  state: HealthState
  reason_codes: string[]
  latest_data_at: string | null
  freshness_seconds: number | null
  build_identity: BuildIdentity
  observed_at: string
}

interface FeatureHealth {
  feature_id: string
  title: string
  href: string | null
  state: HealthState
  dependencies: DependencyHealth[]
  reason_codes: string[]
}

interface SystemHealthResp {
  schema_version: 1
  state: HealthState
  healthy_percentage: number
  partial: boolean
  generated_at: string
  build_identity: BuildIdentity
  features: FeatureHealth[]
  errors: ServiceOperationError[]
}

interface KnowledgeStatsResp {
  code: number
  message: string
  data: {
    knowledge_bases: number
    documents: number
    tasks_by_status: Record<string, number>
  }
}

interface KnowledgeBasesResp {
  code: number
  message: string
  data: Array<{ id: string }>
}

const HEALTH_STATES = new Set<HealthState>([
  'healthy',
  'degraded',
  'unavailable',
  'stale',
  'unknown',
])

const HEALTH_PRIORITY: Record<HealthState, number> = {
  healthy: 0,
  degraded: 1,
  unknown: 2,
  stale: 3,
  unavailable: 4,
}

function buildEvidence(value: string | undefined): string | null {
  const candidate = value?.trim()
  return !candidate || ['unknown', 'unset', 'none'].includes(candidate.toLowerCase())
    ? null
    : candidate.slice(0, 256)
}

function opaqueCoordinate(value: string | undefined): string | null {
  const candidate = buildEvidence(value)
  return candidate && !candidate.includes('/') && !candidate.includes('\\') ? candidate : null
}

function frontendBuildIdentity(): BuildIdentity {
  return {
    expected_commit: buildEvidence(
      process.env.OMNI_DELIVERY_COMMIT ||
      process.env.OMNI_EXPECTED_COMMIT ||
      process.env.OMNI_SOURCE_COMMIT,
    ),
    // Observed values are baked into the frontend image. Runtime expected
    // values must never self-attest an old image.
    observed_commit: buildEvidence(process.env.OMNI_BUILD_COMMIT),
    expected_source_fingerprint: buildEvidence(process.env.OMNI_SOURCE_FINGERPRINT),
    source_fingerprint: buildEvidence(process.env.OMNI_BUILD_SOURCE_FINGERPRINT),
    worktree_id: opaqueCoordinate(process.env.OMNI_WORKTREE_ID),
    allocation_id: opaqueCoordinate(
      process.env.OMNI_ALLOCATION_ID || process.env.OMNI_RUNTIME_ALLOCATION_ID,
    ),
    runtime_id: opaqueCoordinate(process.env.OMNI_RUNTIME_ID),
  }
}

function frontendBuildHealth(identity: BuildIdentity): {
  state: HealthState
  reasonCodes: string[]
} {
  if (!identity.expected_commit || !identity.observed_commit) {
    return { state: 'unknown', reasonCodes: ['frontend_build_identity_unknown'] }
  }
  if (identity.expected_commit !== identity.observed_commit) {
    return { state: 'stale', reasonCodes: ['frontend_build_identity_mismatch'] }
  }
  if (!identity.expected_source_fingerprint || !identity.source_fingerprint) {
    return { state: 'unknown', reasonCodes: ['frontend_build_source_fingerprint_unknown'] }
  }
  if (identity.expected_source_fingerprint !== identity.source_fingerprint) {
    return { state: 'stale', reasonCodes: ['frontend_build_source_fingerprint_mismatch'] }
  }
  return { state: 'healthy', reasonCodes: [] }
}

function worstState(...states: HealthState[]): HealthState {
  return states.reduce<HealthState>(
    (worst, state) => (HEALTH_PRIORITY[state] > HEALTH_PRIORITY[worst] ? state : worst),
    'healthy',
  )
}

function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isHealthState(value: unknown): value is HealthState {
  return typeof value === 'string' && HEALTH_STATES.has(value as HealthState)
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function isBuildIdentity(value: unknown): value is BuildIdentity {
  if (!isRecord(value)) return false
  return [
    'expected_commit',
    'observed_commit',
    'expected_source_fingerprint',
    'source_fingerprint',
    'worktree_id',
    'allocation_id',
    'runtime_id',
  ].every((key) => isNullableString(value[key]))
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

function isDependencyHealth(value: unknown): value is DependencyHealth {
  if (!isRecord(value)) return false
  return (
    typeof value.dependency_id === 'string' &&
    typeof value.ref === 'string' &&
    typeof value.required === 'boolean' &&
    isHealthState(value.state) &&
    isStringArray(value.reason_codes) &&
    isNullableString(value.latest_data_at) &&
    (value.freshness_seconds === null ||
      (typeof value.freshness_seconds === 'number' && Number.isFinite(value.freshness_seconds))) &&
    isBuildIdentity(value.build_identity) &&
    typeof value.observed_at === 'string'
  )
}

function isFeatureHealth(value: unknown): value is FeatureHealth {
  if (!isRecord(value)) return false
  return (
    typeof value.feature_id === 'string' &&
    typeof value.title === 'string' &&
    (value.href === null || (typeof value.href === 'string' && /^\/[^?#]*$/.test(value.href))) &&
    isHealthState(value.state) &&
    isStringArray(value.reason_codes) &&
    Array.isArray(value.dependencies) &&
    value.dependencies.every(isDependencyHealth)
  )
}

function isServiceOperationError(value: unknown): value is ServiceOperationError {
  if (!isRecord(value)) return false
  return (
    typeof value.code === 'string' &&
    typeof value.message === 'string' &&
    typeof value.source === 'string' &&
    typeof value.status === 'number' &&
    value.status >= 400 &&
    value.status <= 599 &&
    typeof value.retryable === 'boolean'
  )
}

function isSystemHealthResp(value: unknown): value is SystemHealthResp {
  if (!isRecord(value)) return false
  return (
    value.schema_version === 1 &&
    isHealthState(value.state) &&
    typeof value.healthy_percentage === 'number' &&
    Number.isFinite(value.healthy_percentage) &&
    value.healthy_percentage >= 0 &&
    value.healthy_percentage <= 100 &&
    typeof value.partial === 'boolean' &&
    typeof value.generated_at === 'string' &&
    Number.isFinite(Date.parse(value.generated_at)) &&
    isBuildIdentity(value.build_identity) &&
    Array.isArray(value.features) &&
    value.features.every(isFeatureHealth) &&
    Array.isArray(value.errors) &&
    value.errors.every(isServiceOperationError)
  )
}

function isKnowledgeStatsResp(value: unknown): value is KnowledgeStatsResp {
  if (!isRecord(value) || !isRecord(value.data)) return false
  const tasks = value.data.tasks_by_status
  return (
    typeof value.code === 'number' &&
    typeof value.message === 'string' &&
    typeof value.data.knowledge_bases === 'number' &&
    Number.isFinite(value.data.knowledge_bases) &&
    typeof value.data.documents === 'number' &&
    Number.isFinite(value.data.documents) &&
    isRecord(tasks) &&
    Object.values(tasks).every((item) => typeof item === 'number' && Number.isFinite(item))
  )
}

function isKnowledgeBasesResp(value: unknown): value is KnowledgeBasesResp {
  if (!isRecord(value)) return false
  return (
    typeof value.code === 'number' &&
    typeof value.message === 'string' &&
    Array.isArray(value.data) &&
    value.data.every((item) => isRecord(item) && typeof item.id === 'string')
  )
}

function safeCode(value: unknown, fallback: string): string {
  return typeof value === 'string' && /^[a-zA-Z0-9_.:-]{1,80}$/.test(value) ? value : fallback
}

function safeSource(value: unknown, fallback: string): string {
  return typeof value === 'string' && /^[a-zA-Z0-9_.:/-]{1,160}$/.test(value) ? value : fallback
}

function publicMessage(code: string): string {
  if (code === 'upstream_timeout') return '上游健康检查超时。'
  if (code === 'upstream_schema_invalid') return '上游返回了不兼容的健康数据。'
  if (code === 'upstream_invalid_json') return '上游返回了无法解析的健康数据。'
  return '上游健康信息暂时不可用。'
}

function upstreamCode(body: unknown): string {
  if (!isRecord(body)) return 'upstream_error'
  const nested = isRecord(body.error) ? body.error : null
  return safeCode(nested?.code ?? body.code, 'upstream_error')
}

function requestTimeoutMs(): number {
  const configured = Number(process.env.OMNI_OVERVIEW_TIMEOUT_MS || 5000)
  return Number.isFinite(configured) ? Math.min(15_000, Math.max(25, configured)) : 5000
}

async function fetchContract<T>(
  url: string,
  source: string,
  validate: (value: unknown) => value is T,
): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
      signal: AbortSignal.timeout(requestTimeoutMs()),
    })
  } catch (error) {
    const timedOut = error instanceof Error && ['AbortError', 'TimeoutError'].includes(error.name)
    throw new ServiceFetchError(publicMessage(timedOut ? 'upstream_timeout' : 'source_unavailable'), {
      status: 503,
      source,
      code: timedOut ? 'upstream_timeout' : 'source_unavailable',
    })
  }

  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ServiceFetchError(publicMessage('upstream_invalid_json'), {
      status: response.ok ? 502 : response.status,
      source,
      code: 'upstream_invalid_json',
    })
  }
  if (!response.ok) {
    const code = upstreamCode(body)
    throw new ServiceFetchError(publicMessage(code), {
      status: response.status,
      source,
      code,
    })
  }
  if (!validate(body)) {
    throw new ServiceFetchError(publicMessage('upstream_schema_invalid'), {
      status: 502,
      source,
      code: 'upstream_schema_invalid',
    })
  }
  return body
}

function operationError(error: unknown, source: string): ServiceOperationError {
  if (error instanceof ServiceFetchError) {
    const code = safeCode(error.code, 'upstream_error')
    const status = error.status >= 400 && error.status <= 599 ? error.status : 503
    return {
      code,
      message: publicMessage(code),
      source: safeSource(error.source, source),
      status,
      retryable: code !== 'upstream_schema_invalid' && (status >= 500 || code === 'upstream_timeout'),
    }
  }
  return {
    code: 'source_unavailable',
    message: publicMessage('source_unavailable'),
    source,
    status: 503,
    retryable: true,
  }
}

function sanitizeRegistryError(error: ServiceOperationError): ServiceOperationError {
  const code = safeCode(error.code, 'upstream_error')
  return {
    code,
    message: publicMessage(code),
    source: safeSource(error.source, 'knowledge-engine:system-health'),
    status: error.status,
    retryable: error.retryable,
  }
}

function dependencyState(result: SystemHealthResp, dependencyId: string): HealthState {
  return result.features
    .flatMap((feature) => feature.dependencies)
    .filter((item) => item.dependency_id === dependencyId)
    .reduce<HealthState>(
      (worst, item) => (HEALTH_PRIORITY[item.state] > HEALTH_PRIORITY[worst] ? item.state : worst),
      'healthy',
    )
}

function gatewayStatus(error: ServiceOperationError): number {
  return error.status === 503 || error.status === 504 || error.code === 'upstream_timeout' ? 503 : 502
}

export async function GET() {
  const base = serviceBase()
  const [healthResult, statsResult, basesResult] = await Promise.allSettled([
    fetchContract(
      `${base.knowledge}/api/v1/system/health`,
      'knowledge-engine:system-health',
      isSystemHealthResp,
    ),
    fetchContract(
      `${base.knowledge}/api/v1/knowledge/stats`,
      'knowledge-engine:stats',
      isKnowledgeStatsResp,
    ),
    fetchContract(
      `${base.knowledge}/api/v1/knowledge/bases`,
      'knowledge-engine:bases',
      isKnowledgeBasesResp,
    ),
  ])

  if (healthResult.status === 'rejected') {
    const error = operationError(healthResult.reason, 'knowledge-engine:system-health')
    return Response.json({ success: false, error }, { status: gatewayStatus(error) })
  }

  const systemHealth = healthResult.value
  const localBuildIdentity = frontendBuildIdentity()
  const localBuildHealth = frontendBuildHealth(localBuildIdentity)
  const errors = systemHealth.errors.map(sanitizeRegistryError)
  let stats: KnowledgeStatsResp['data'] | null = null
  let bases: KnowledgeBasesResp['data'] | null = null
  if (statsResult.status === 'fulfilled') stats = statsResult.value.data
  else errors.push(operationError(statsResult.reason, 'knowledge-engine:stats'))
  if (basesResult.status === 'fulfilled') bases = basesResult.value.data
  else errors.push(operationError(basesResult.reason, 'knowledge-engine:bases'))

  const partial = systemHealth.partial ||
    errors.length > 0 ||
    systemHealth.features.length === 0 ||
    localBuildHealth.state === 'unknown'
  const registrySummary: HealthState = systemHealth.features.length === 0
    ? 'unknown'
    : systemHealth.state === 'healthy' && partial
      ? 'degraded'
      : systemHealth.state
  const summary = worstState(registrySummary, localBuildHealth.state)
  const runningTasks = stats
    ? (stats.tasks_by_status.running || 0) +
      (stats.tasks_by_status.processing || 0) +
      (stats.tasks_by_status.queued || 0)
    : null

  return Response.json({
    success: true,
    data: {
      health: {
        aiHub: dependencyState(systemHealth, 'ai-provider-hub'),
        knowledge: dependencyState(systemHealth, 'knowledge-engine'),
        summary,
        partial,
        generatedAt: systemHealth.generated_at,
        buildIdentity: systemHealth.build_identity,
        frontendBuild: {
          state: localBuildHealth.state,
          reasonCodes: localBuildHealth.reasonCodes,
          buildIdentity: localBuildIdentity,
        },
        features: systemHealth.features,
        errors,
      },
      metrics: {
        aiTokenToday: null,
        knowledgeDocuments: stats?.documents ?? null,
        infraUptime: summary === 'healthy' && !partial ? systemHealth.healthy_percentage : null,
        knowledgeBases: stats?.knowledge_bases ?? bases?.length ?? null,
        runningTasks,
      },
    },
  })
}
