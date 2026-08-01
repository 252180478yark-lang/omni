import { serviceBase } from '../../../_shared'
import { requireRuntimeActor, runtimeTraceAuthorization, runtimeTraceError } from '../../_runtime-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: Request, { params }: { params: { traceId: string } }) {
  try {
    await requireRuntimeActor(request)
    const requestUrl = new URL(request.url)
    const cursor = requestUrl.searchParams.get('cursor') || '0'
    const response = await fetch(`${serviceBase().knowledge}/api/v1/runtime-traces/${encodeURIComponent(params.traceId)}/replay?cursor=${encodeURIComponent(cursor)}`, {
      headers: { Authorization: runtimeTraceAuthorization() }, cache: 'no-store', signal: AbortSignal.timeout(3000),
    })
    return new Response(await response.text(), { status: response.status, headers: { 'Content-Type': 'application/json' } })
  } catch (error) { return runtimeTraceError(error) }
}
