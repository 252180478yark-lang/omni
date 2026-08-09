import { serviceBase } from '../../_shared'
import { requireRuntimeActor, runtimeTraceError } from '../../runtime-traces/_runtime-auth'
import { buildWorkbenchActionCard } from '@/lib/workbench-runtime'
import type { SystemGraphSnapshot } from '@/lib/system-command-center/runtime-model'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  try {
    await requireRuntimeActor(request, true)
    const payload = await request.json() as { question?: unknown }
    if (typeof payload.question !== 'string' || payload.question.length > 500) {
      return Response.json({ detail: { code: 'workbench_question_invalid' } }, { status: 422 })
    }
    const response = await fetch(`${serviceBase().knowledge}/api/v1/system-graph/snapshot`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(8_000),
    })
    if (!response.ok) {
      return Response.json(buildWorkbenchActionCard(null, payload.question), { status: 503 })
    }
    const snapshot = await response.json() as SystemGraphSnapshot
    return Response.json(buildWorkbenchActionCard(snapshot, payload.question))
  } catch (error) {
    return runtimeTraceError(error)
  }
}
