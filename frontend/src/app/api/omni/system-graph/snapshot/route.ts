import { serviceBase } from '../../_shared'
import { requireRuntimeActor, runtimeTraceError } from '../../runtime-traces/_runtime-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  try {
    await requireRuntimeActor(request)
    const response = await fetch(`${serviceBase().knowledge}/api/v1/system-graph/snapshot`, { cache: 'no-store', signal: AbortSignal.timeout(8000) })
    return new Response(await response.text(), { status: response.status, headers: { 'Content-Type': 'application/json' } })
  } catch (error) { return runtimeTraceError(error) }
}
