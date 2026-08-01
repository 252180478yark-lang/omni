import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  const base = serviceBase()
  const body = await request.json().catch(() => ({}))
  try {
    const data = await fetchJson<any>(
      `${base.knowledge}/api/v1/mcp/execute/sku.audience-pack.get`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    )
    return Response.json({ success: true, data })
  } catch (err: unknown) {
    return Response.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    )
  }
}
