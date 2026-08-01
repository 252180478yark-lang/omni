import { serviceBase } from '../_shared'
import { requireRuntimeActor, runtimeTraceAuthorization, runtimeTraceError } from '../runtime-traces/_runtime-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  try {
    await requireRuntimeActor(request, true)
    const body = await request.text()
    const response = await fetch(`${serviceBase().knowledge}/api/v1/runtime-plan-drafts`, {
      method: 'POST', body,
      headers: { 'Content-Type': 'application/json', Authorization: runtimeTraceAuthorization() },
      cache: 'no-store', signal: AbortSignal.timeout(3000),
    })
    return new Response(await response.text(), { status: response.status, headers: { 'Content-Type': 'application/json' } })
  } catch (error) { return runtimeTraceError(error) }
}
