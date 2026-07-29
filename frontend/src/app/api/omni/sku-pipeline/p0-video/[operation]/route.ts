import { fetchJson, serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

// Keep this proxy deliberately closed: it exposes the P0 planting-video atom,
// not an arbitrary MCP execution tunnel or the frozen P1 branches.
const TOOL_BY_OPERATION: Record<string, string> = {
  preflight: 'p0_preflight_video_production',
  inputs: 'p0_list_video_production_inputs',
  orders: 'p0_list_video_production_orders',
  order: 'p0_get_video_production_order',
  create: 'p0_create_video_production_order',
  bridgeReview: 'p0_generate_planting_bridge_candidates',
  // Compatibility alias for callers that used the early implementation name.
  generateBridge: 'p0_generate_planting_bridge_candidates',
  buildSpec: 'p0_build_video_content_spec',
  generateScripts: 'p0_generate_video_script_candidates',
  reviewScripts: 'p0_review_video_script_candidates',
  selectScript: 'p0_select_video_script',
  preparePrompt: 'p0_prepare_video_prompt',
  assessCandidateVector: 'p0_assess_video_candidate_vector_match',
  assessExecutionVector: 'p0_assess_video_execution_vector_match',
  assessMatch: 'p0_assess_video_content_match',
  requestApproval: 'p0_request_video_generation_approval',
  startGeneration: 'p0_start_video_generation',
  recoverGeneration: 'p0_recover_video_generation',
  rawQa: 'p0_run_raw_video_qa',
  compose: 'p0_compose_video_final',
  finalQa: 'p0_run_final_video_qa',
  release: 'p0_release_video_package',
  cancel: 'p0_cancel_video_production',
}

export async function POST(
  request: Request,
  context: { params: Promise<{ operation: string }> },
) {
  const { operation } = await context.params
  const toolName = TOOL_BY_OPERATION[operation]
  if (!toolName) {
    return Response.json({ success: false, error: 'P0 operation not found' }, { status: 404 })
  }
  const body = await request.json().catch(() => ({}))
  try {
    const base = serviceBase()
    const data = await fetchJson<unknown>(`${base.knowledge}/api/v1/mcp/exec/${toolName}`, {
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
