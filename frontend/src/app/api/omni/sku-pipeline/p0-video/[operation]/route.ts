import { fetchJson, serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

// Keep this proxy deliberately closed: it exposes the P0 planting-video atom,
// not an arbitrary MCP execution tunnel or the frozen P1 branches.
const OPERATION_ID_BY_UI_ACTION: Record<string, string> = {
  preflight: 'p0.preflight',
  inputs: 'p0.inputs.list',
  orders: 'p0.orders.list',
  order: 'p0.order.get',
  create: 'p0.order.create',
  bridgeReview: 'p0.bridge-review.generate',
  // Compatibility alias for callers that used the early implementation name.
  generateBridge: 'p0.bridge-review.generate',
  buildSpec: 'p0.content-spec.build',
  generateScripts: 'p0.scripts.generate',
  reviewScripts: 'p0.scripts.review',
  selectScript: 'p0.script.select',
  preparePrompt: 'p0.prompt.prepare',
  assessCandidateVector: 'p0.candidate-vector.assess',
  assessExecutionVector: 'p0.execution-vector.assess',
  assessMatch: 'p0.content-match.assess',
  requestApproval: 'p0.approval.request',
  startGeneration: 'p0.generation.start',
  recoverGeneration: 'p0.generation.recover',
  rawQa: 'p0.raw-qa.run',
  compose: 'p0.final.compose',
  finalQa: 'p0.final-qa.run',
  release: 'p0.package.release',
  cancel: 'p0.production.cancel',
}

export async function POST(
  request: Request,
  context: { params: Promise<{ operation: string }> },
) {
  const { operation } = await context.params
  const operationId = OPERATION_ID_BY_UI_ACTION[operation]
  if (!operationId) {
    return Response.json({ success: false, error: 'P0 operation not found' }, { status: 404 })
  }
  const body = await request.json().catch(() => ({}))
  try {
    const base = serviceBase()
    const data = await fetchJson<unknown>(`${base.knowledge}/api/v1/mcp/execute/${operationId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return Response.json({ success: true, data })
  } catch (err: unknown) {
    return Response.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    )
  }
}
