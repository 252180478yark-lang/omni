import { serviceBase } from '../_shared'
import { requireRuntimeActor, runtimeTraceAuthorization, runtimeTraceError } from '../runtime-traces/_runtime-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  try {
    await requireRuntimeActor(request)
    const query = new URL(request.url).searchParams
    const traceId = query.get('trace_id') || ''
    const sourceStatus = query.get('source_status') || 'success'
    const response = await fetch(`${serviceBase().knowledge}/api/v1/runtime-findings?trace_id=${encodeURIComponent(traceId)}&source_status=${encodeURIComponent(sourceStatus)}`, {
      headers: { Authorization: runtimeTraceAuthorization() }, cache: 'no-store', signal: AbortSignal.timeout(3000),
    })
    return new Response(await response.text(), { status: response.status, headers: { 'Content-Type': 'application/json' } })
  } catch (error) { return runtimeTraceError(error) }
}
