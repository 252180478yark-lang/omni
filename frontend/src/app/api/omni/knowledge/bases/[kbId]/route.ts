import { fetchJson, serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function DELETE(_: Request, context: { params: { kbId: string } }) {
  try {
    const { kbId } = context.params
    const base = serviceBase()
    await fetchJson<{ data: { deleted: boolean } }>(`${base.knowledge}/api/v1/knowledge/bases/${kbId}`, {
      method: 'DELETE',
    })
    return Response.json({ success: true })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
