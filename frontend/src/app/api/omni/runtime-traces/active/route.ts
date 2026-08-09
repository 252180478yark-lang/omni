import { serviceBase } from '../../_shared'
import { requireRuntimeActor, runtimeTraceError } from '../_runtime-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  try {
    await requireRuntimeActor(request)
    const response = await fetch(`${serviceBase().knowledge}/api/v1/runtime-traces/active`, {
      cache: 'no-store', signal: AbortSignal.timeout(3000),
    })
    return new Response(await response.text(), { status: response.status, headers: { 'Content-Type': 'application/json' } })
  } catch (error) { return runtimeTraceError(error) }
}
