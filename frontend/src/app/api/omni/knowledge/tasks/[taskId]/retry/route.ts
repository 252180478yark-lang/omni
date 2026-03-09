import { fetchJson, serviceBase } from '../../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(_: Request, context: { params: { taskId: string } }) {
  try {
    const { taskId } = context.params
    const base = serviceBase()
    const result = await fetchJson<{ data: { task_id: string } }>(
      `${base.knowledge}/api/v1/knowledge/tasks/${taskId}/retry`,
      { method: 'POST' }
    )
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
