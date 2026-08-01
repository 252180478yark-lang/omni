import { readFileSync } from 'node:fs'
import { requireApprovalActor, requireSameOrigin, ServiceFetchError } from '../_shared'

export async function requireRuntimeActor(request: Request, mutation = false): Promise<void> {
  if (mutation) requireSameOrigin(request)
  await requireApprovalActor(request)
}

export function runtimeTraceAuthorization(): string {
  const path = process.env.OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE?.trim()
  if (!path) throw new Error('runtime_trace_service_identity_unavailable')
  let token = ''
  try { token = readFileSync(path, 'utf8').trim() } catch { throw new Error('runtime_trace_service_identity_unavailable') }
  if (token.length < 24) throw new Error('runtime_trace_service_identity_invalid')
  return `Bearer ${token}`
}

export function runtimeTraceError(error: unknown): Response {
  if (error instanceof ServiceFetchError) {
    return Response.json({ success: false, error: { code: error.code, source: error.source, status: error.status } }, { status: error.status })
  }
  const code = error instanceof Error ? error.message : 'runtime_trace_upstream_unavailable'
  const status = code.startsWith('runtime_trace_service_identity') ? 503 : 502
  return Response.json({ success: false, error: { code, source: 'frontend:runtime-trace', status } }, { status })
}
