import { fetchJson, serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface PatchKbBody {
  kb_role?: string
}

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

export async function PATCH(request: Request, context: { params: { kbId: string } }) {
  try {
    const { kbId } = context.params
    const payload = (await request.json()) as PatchKbBody
    if (!payload.kb_role) {
      return Response.json({ success: false, error: 'kb_role is required' }, { status: 400 })
    }
    const base = serviceBase()
    const result = await fetchJson<{ data: unknown }>(`${base.knowledge}/api/v1/knowledge/bases/${kbId}`, {
      method: 'PATCH',
      body: JSON.stringify({ kb_role: payload.kb_role }),
    })
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
