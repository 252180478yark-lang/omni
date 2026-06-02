import { fetchJson, serviceBase } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET() {
  const base = serviceBase()
  try {
    const data = await fetchJson<{ data: any[]; total: number }>(
      `${base.knowledge}/api/v1/mcp/human-gates`,
    )
    return Response.json({ success: true, ...data })
  } catch (err: unknown) {
    return Response.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    )
  }
}
