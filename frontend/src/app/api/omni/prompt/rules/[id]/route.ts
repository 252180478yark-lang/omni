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

export async function PATCH(
  request: Request,
  { params }: { params: { id: string } },
) {
  try {
    requireSameOrigin(request)
    const actor = await requireApprovalActor(request)
    const payload = await request.text()
    const base = serviceBase()
    const url = `${base.knowledge}/api/v1/prompt/rules/${encodeURIComponent(params.id)}`
    const body = await fetchJson<{ data: { id: string } }>(
      url,
      {
        method: 'PATCH',
        headers: approvalServiceHeaders('PATCH', url, actor, payload),
        body: payload,
      },
    )
    return Response.json({ success: true, data: body.data })
  } catch (error) {
    const status = error instanceof ServiceFetchError ? error.status : 502
    const code = error instanceof ServiceFetchError ? error.code : 'prompt_rule_update_unavailable'
    return Response.json({ success: false, error: code }, { status })
  }
}

export async function DELETE(
  request: Request,
  { params }: { params: { id: string } },
) {
  try {
    requireSameOrigin(request)
    const actor = await requireApprovalActor(request)
    const base = serviceBase()
    const url = `${base.knowledge}/api/v1/prompt/rules/${encodeURIComponent(params.id)}`
    const body = await fetchJson<{ data: unknown }>(
      url,
      {
        method: 'DELETE',
        headers: approvalServiceHeaders('DELETE', url, actor),
      },
    )
    return Response.json({ success: true, data: body.data })
  } catch (error) {
    const status = error instanceof ServiceFetchError ? error.status : 502
    const code = error instanceof ServiceFetchError ? error.code : 'prompt_rule_delete_unavailable'
    return Response.json({ success: false, error: code }, { status })
  }
}
