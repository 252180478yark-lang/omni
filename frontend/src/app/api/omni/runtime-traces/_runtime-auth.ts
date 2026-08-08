import { requireApprovalActor, requireSameOrigin, ServiceFetchError } from '../_shared'

export async function requireRuntimeActor(request: Request, mutation = false): Promise<void> {
  if (mutation) requireSameOrigin(request)
  await requireApprovalActor(request)
}

export function runtimeTraceAuthorization(): string {
  return ''
}

export function runtimeTraceError(error: unknown): Response {
  if (error instanceof ServiceFetchError) {
    return Response.json({ success: false, error: { code: error.code, source: error.source, status: error.status } }, { status: error.status })
  }
  const code = error instanceof Error ? error.message : 'runtime_trace_upstream_unavailable'
  const status = 502
  return Response.json({ success: false, error: { code, source: 'frontend:runtime-trace', status } }, { status })
}
