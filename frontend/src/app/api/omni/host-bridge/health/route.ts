export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET() {
  const base = (process.env.OMNI_HOST_BRIDGE_URL || 'http://127.0.0.1:7777').replace(/\/$/, '')
  try {
    const response = await fetch(`${base}/api/v1/host-bridge/health`, { cache: 'no-store', signal: AbortSignal.timeout(2000) })
    if (!response.ok) throw new Error('host_bridge_unavailable')
    const health = await response.json() as {
      state: string
      build_identity?: { build_commit?: string | null; worktree_id?: string | null; allocation_id?: string | null }
      reason_codes?: string[]
    }
    const expected = {
      build_commit: process.env.OMNI_BUILD_COMMIT,
      worktree_id: process.env.OMNI_WORKTREE_ID,
      allocation_id: process.env.OMNI_ALLOCATION_ID,
    }
    const mismatches = Object.entries(expected)
      .filter(([, value]) => Boolean(value))
      .filter(([key, value]) => health.build_identity?.[key as keyof typeof expected] !== value)
      .map(([key]) => `host_${key}_mismatch`)
    if (mismatches.length) {
      health.state = 'stale'
      health.reason_codes = Array.from(new Set([...(health.reason_codes || []), ...mismatches]))
    }
    return Response.json(health, { status: 200 })
  } catch {
    return Response.json({ state: 'unavailable', instance_id: 'host:unavailable', capabilities: [], build_identity: {}, reason_codes: ['host_bridge_unavailable'] }, { status: 503 })
  }
}
