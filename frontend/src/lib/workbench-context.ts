import type { WorkbenchContinuity } from '@/stores/workbenchStore'

export interface WorkbenchContextInput {
  context_ref: string
  workspace_ref: string
  shop_ref: string | null
  sku_ref: string | null
  project_ref: string | null
  environment_ref: string | null
  task_ref: string | null
  evidence_refs: string[]
  origin_surface_ref: string
  availability: 'available' | 'unavailable'
  rebind_reason: string | null
}

export interface WorkbenchContextSnapshot extends WorkbenchContextInput {
  schema_version: 1
  snapshot_id: string
  revision: number
  permission_scope_hash: string
  created_at: string
}

export interface WorkbenchContextResult {
  snapshot: WorkbenchContextSnapshot
  reused: boolean
}

export interface SynchronizeWorkbenchContextOptions {
  current: Pick<WorkbenchContinuity, 'contextSnapshotId' | 'contextRevisionNumber' | 'agentSessionId'>
  fetcher?: typeof fetch
}

function safeRoute(pathname: string): string {
  const route = pathname.split('?', 1)[0].replace(/\/{2,}/g, '/')
  return /^\/[A-Za-z0-9._/-]*$/.test(route) ? route : '/unknown'
}

function safeObjectRef(prefix: string, value: string | null): string | null {
  const normalized = value?.trim()
  if (!normalized || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/.test(normalized)) return null
  return `${prefix}:${normalized}`
}

export function deriveWorkbenchContext(pathname: string, queryString = ''): WorkbenchContextInput {
  const route = safeRoute(pathname)
  const params = new URLSearchParams(queryString)
  const routeParts = route.split('/').filter(Boolean)
  const skuFromRoute = routeParts[0] === 'sku' && routeParts[1] ? routeParts[1] : null
  const taskFromRoute = routeParts[0] === 'tasks' && routeParts[1] ? routeParts[1] : null
  const skuRef = safeObjectRef('sku', params.get('sku_id') || params.get('sku') || skuFromRoute)
  const taskRef = safeObjectRef('task', params.get('task_id') || taskFromRoute)
  const surfaceRef = `ui_route:${route}`

  return {
    context_ref: 'context:workspace:active',
    workspace_ref: 'workspace:omni',
    shop_ref: safeObjectRef('shop', params.get('shop_id')),
    sku_ref: skuRef,
    project_ref: 'project:omni',
    environment_ref: 'environment:local',
    task_ref: taskRef,
    evidence_refs: [surfaceRef],
    origin_surface_ref: surfaceRef,
    availability: 'available',
    rebind_reason: 'surface_observed',
  }
}

export async function synchronizeWorkbenchContext(
  context: WorkbenchContextInput,
  options: SynchronizeWorkbenchContextOptions,
): Promise<WorkbenchContextResult> {
  const { contextSnapshotId, contextRevisionNumber, agentSessionId } = options.current
  const hasCurrent = Boolean(contextSnapshotId && contextRevisionNumber)
  const fetcher = options.fetcher || fetch
  const response = await fetcher(
    hasCurrent ? '/api/omni/workbench/context/rebind' : '/api/omni/workbench/context',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        context,
        expected_snapshot_id: hasCurrent ? contextSnapshotId : null,
        expected_revision: hasCurrent ? contextRevisionNumber : null,
        session_id: agentSessionId,
      }),
    },
  )
  const value = await response.json().catch(() => null) as WorkbenchContextResult | null
  if (!response.ok || !value?.snapshot) {
    throw new Error(`workbench_context_status_${response.status}`)
  }
  return value
}
