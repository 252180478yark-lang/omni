import { approvalServiceHeaders, fetchJson, requireApprovalActor, ServiceFetchError, serviceBase } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  const base = serviceBase()
  try {
    const actor = await requireApprovalActor(request)
    const url = `${base.knowledge}/api/v1/mcp/human-gates`
    const data = await fetchJson<{ data: any[]; total: number }>(
      url,
      { headers: approvalServiceHeaders('GET', url, actor) },
    )
    return Response.json({ success: true, ...data })
  } catch (err: unknown) {
    return Response.json(
      {
        success: false,
        error: err instanceof ServiceFetchError ? err.code : 'approval_upstream_unavailable',
      },
      { status: err instanceof ServiceFetchError ? err.status : 502 },
    )
  }
}
