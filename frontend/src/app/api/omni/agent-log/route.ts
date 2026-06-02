import { fetchJson, serviceBase } from '../_shared'
import type { NextRequest } from 'next/server'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const base = serviceBase()
  const sp = req.nextUrl.searchParams
  const qs = new URLSearchParams()
  for (const k of ['limit', 'offset', 'status', 'tool_name', 'since_hours']) {
    const v = sp.get(k)
    if (v != null) qs.set(k, v)
  }
  try {
    const data = await fetchJson<{ data: any[]; total: number; summary_24h: any }>(
      `${base.knowledge}/api/v1/mcp/tool-calls?${qs.toString()}`,
    )
    return Response.json({ success: true, ...data })
  } catch (err: unknown) {
    return Response.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    )
  }
}
