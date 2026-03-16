import { fetchJson, serviceBase } from '../../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: Request, context: { params: { documentId: string } }) {
  try {
    const { documentId } = context.params
    const { searchParams } = new URL(request.url)
    const limit = searchParams.get('limit') || '50'
    const offset = searchParams.get('offset') || '0'
    const base = serviceBase()
    const data = await fetchJson<{ data: unknown }>(
      `${base.knowledge}/api/v1/knowledge/documents/${documentId}/chunks?limit=${limit}&offset=${offset}`,
    )
    return Response.json({ success: true, data: data.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
