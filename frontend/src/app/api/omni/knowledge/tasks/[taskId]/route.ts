import { fetchJson, serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function DELETE(_: Request, context: { params: { taskId: string } }) {
  try {
    const { taskId } = context.params
    const base = serviceBase()
    const result = await fetchJson<{ data: { deleted: boolean } }>(
      `${base.knowledge}/api/v1/knowledge/tasks/${taskId}`,
      { method: 'DELETE' }
    )
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
