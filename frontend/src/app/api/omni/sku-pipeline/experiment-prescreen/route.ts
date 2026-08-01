import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

// 投前视觉快环：多模态 judge 给本轮 AI 视频打 5 维质量分 + gate。
// 仅 ai_video / mixed track 有意义（真人臂没 AI 视频）。
// body: { experiment_id, round_no? } → canonical closed operation registry
export async function POST(request: Request) {
  const base = serviceBase()
  const body = await request.json()
  try {
    const data = await fetchJson<unknown>(
      `${base.knowledge}/api/v1/mcp/execute/experiment.prescreen`,
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
