import {
  approvalServiceHeaders,
  fetchJson,
  requireApprovalActor,
  requireSameOrigin,
  ServiceFetchError,
  serviceBase,
} from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  try {
    const actor = await requireApprovalActor(request)
    const url = new URL(request.url)
    const nodeId = url.searchParams.get('node_id') || ''
    const enabledOnly = url.searchParams.get('enabled_only') === 'true'
    const qs = new URLSearchParams()
    if (nodeId) qs.set('node_id', nodeId)
    if (enabledOnly) qs.set('enabled_only', 'true')

    const base = serviceBase()
    const upstreamUrl = `${base.knowledge}/api/v1/prompt/rules${qs.toString() ? '?' + qs.toString() : ''}`
    const body = await fetchJson<{ data: { rules: unknown[] } }>(
      upstreamUrl,
      { headers: approvalServiceHeaders('GET', upstreamUrl, actor) },
    )
    return Response.json({ success: true, data: body.data })
  } catch (error) {
    const status = error instanceof ServiceFetchError ? error.status : 502
    const code = error instanceof ServiceFetchError ? error.code : 'prompt_rules_unavailable'
    return Response.json({ success: false, error: code }, { status })
  }
}

export async function POST(request: Request) {
  try {
    requireSameOrigin(request)
    const actor = await requireApprovalActor(request)
    const payload = await request.text()
    const base = serviceBase()
    const url = `${base.knowledge}/api/v1/prompt/rules`
    const body = await fetchJson<{ data: { id: string } }>(
      url,
      {
        method: 'POST',
        headers: approvalServiceHeaders('POST', url, actor, payload),
        body: payload,
      },
    )
    return Response.json({ success: true, data: body.data })
  } catch (error) {
    const status = error instanceof ServiceFetchError ? error.status : 502
    const code = error instanceof ServiceFetchError ? error.code : 'prompt_rule_create_unavailable'
    return Response.json({ success: false, error: code }, { status })
  }
}
