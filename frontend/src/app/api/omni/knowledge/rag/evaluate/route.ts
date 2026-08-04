import {
  approvalServiceHeaders,
  fetchJson,
  requireApprovalActor,
  requireSameOrigin,
  ServiceFetchError,
  serviceBase,
} from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  try {
    requireSameOrigin(request)
    const actor = await requireApprovalActor(request)
    const body = await request.text()
    const base = serviceBase()
    const url = `${base.knowledge}/api/v1/knowledge/rag/evaluate`

    const json = await fetchJson<{ data?: unknown }>(url, {
      method: 'POST',
      headers: {
        ...approvalServiceHeaders('POST', url, actor, body),
      },
      body,
    }, 'knowledge-engine:evaluate')
    return Response.json({ success: true, data: json.data ?? json })
  } catch (error) {
    const status = error instanceof ServiceFetchError ? error.status : 502
    const code = error instanceof ServiceFetchError ? error.code : 'knowledge_evaluation_unavailable'
    return Response.json({ success: false, error: code }, { status })
  }
}
