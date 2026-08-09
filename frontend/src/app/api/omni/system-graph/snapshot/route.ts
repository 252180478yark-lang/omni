import { requireRuntimeActor, runtimeTraceError } from '../../runtime-traces/_runtime-auth'
import { fetchSystemGraphSnapshot } from '../_graph-fetch'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  try {
    await requireRuntimeActor(request)
    const response = await fetchSystemGraphSnapshot()
    return new Response(await response.text(), { status: response.status, headers: { 'Content-Type': 'application/json' } })
  } catch (error) { return runtimeTraceError(error) }
}
