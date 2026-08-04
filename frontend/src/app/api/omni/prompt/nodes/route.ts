import {
  approvalServiceHeaders,
  fetchJson,
  requireApprovalActor,
  ServiceFetchError,
  serviceBase,
} from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  try {
    const actor = await requireApprovalActor(request)
    const base = serviceBase()
    const url = `${base.knowledge}/api/v1/prompt/nodes`
    const body = await fetchJson<{ data: { nodes: unknown[] } }>(
      url,
      { headers: approvalServiceHeaders('GET', url, actor) },
    )
    return Response.json({ success: true, data: body.data })
  } catch (error) {
    const status = error instanceof ServiceFetchError ? error.status : 502
    const code = error instanceof ServiceFetchError ? error.code : 'prompt_nodes_unavailable'
    return Response.json({ success: false, error: code }, { status })
  }
}
