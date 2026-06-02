import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(_req: Request, ctx: { params: { id: string } }) {
  const base = serviceBase()
  const { id } = ctx.params
  try {
    const data = await fetchJson<{ data: any }>(
      `${base.knowledge}/api/v1/mcp/tool-calls/${encodeURIComponent(id)}`,
    )
    return Response.json({ success: true, ...data })
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    const isNotFound = /404|不存在|not.*found/i.test(msg)
    return Response.json(
      { success: false, error: msg },
      { status: isNotFound ? 404 : 502 },
    )
  }
}
