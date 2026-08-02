import {
  approvalServiceHeaders,
  fetchJson,
  requireApprovalActor,
  requireSameOrigin,
  ServiceFetchError,
  serviceBase,
} from '../../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: Request, context: { params: { kbId: string } }) {
  try {
    requireSameOrigin(request)
    const actor = await requireApprovalActor(request)
    const { kbId } = context.params
    const base = serviceBase()
    const url = `${base.knowledge}/api/v1/knowledge/bases/${encodeURIComponent(kbId)}/rebuild`
    const body = '{}'
    const json = await fetchJson<{ data?: unknown }>(url, {
      method: 'POST',
      headers: {
        ...approvalServiceHeaders('POST', url, actor, body),
      },
      body,
    }, 'knowledge-engine:rebuild')
    return Response.json({ success: true, data: json.data ?? json })
  } catch (error) {
    const status = error instanceof ServiceFetchError ? error.status : 502
    const code = error instanceof ServiceFetchError ? error.code : 'knowledge_rebuild_unavailable'
    return Response.json({ success: false, error: code }, { status })
  }
}
