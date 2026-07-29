import { approvalServiceHeaders, requireApprovalActor, requireSameOrigin, ServiceFetchError, serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface Body {
  note?: string
}

export async function POST(req: Request, ctx: { params: { id: string } }) {
  const base = serviceBase()
  const { id } = ctx.params
  try {
    requireSameOrigin(req)
    const actor = await requireApprovalActor(req)
    let body: Body
    try {
      body = await req.json()
    } catch {
      return Response.json({ success: false, error: 'invalid_json' }, { status: 400 })
    }
    const url = `${base.knowledge}/api/v1/mcp/human-gates/${encodeURIComponent(id)}/reject`
    const upstreamBody = JSON.stringify({ note: body.note ?? '' })
    const r = await fetch(
      url,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...approvalServiceHeaders('POST', url, actor, upstreamBody),
        },
        body: upstreamBody,
        cache: 'no-store',
      },
    )
    const data = await r.json().catch(() => ({}))
    return Response.json({ success: r.ok, ...data }, { status: r.status })
  } catch (err: unknown) {
    const code = err instanceof ServiceFetchError ? err.code : 'approval_upstream_unavailable'
    const status = err instanceof ServiceFetchError ? err.status : 502
    return Response.json({ success: false, error: code }, { status })
  }
}
