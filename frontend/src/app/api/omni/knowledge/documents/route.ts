import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface DocumentsResp {
  code: number
  message: string
  data: Array<{
    id: string
    kb_id: string
    title: string
    source_url: string | null
    created_at: string
    chunk_count: number
  }>
}

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url)
    const kbId = searchParams.get('kb_id')
    const search = searchParams.get('search')
    const limit = searchParams.get('limit') || '100'

    const params = new URLSearchParams({ limit })
    if (kbId) params.set('kb_id', kbId)
    if (search) params.set('search', search)

    const base = serviceBase()
    const result = await fetchJson<DocumentsResp>(`${base.knowledge}/api/v1/knowledge/documents?${params.toString()}`)
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
