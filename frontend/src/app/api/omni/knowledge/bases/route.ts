import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface KnowledgeBaseItem {
  id: string
  name: string
  description: string
  embedding_provider?: string
  embedding_model: string
  dimension: number
  created_at: string
}

interface KnowledgeBasesResp {
  code: number
  message: string
  data: KnowledgeBaseItem[]
}

interface KnowledgeBaseCreateResp {
  code: number
  message: string
  data: KnowledgeBaseItem
}

interface CreateKbBody {
  name: string
  description?: string
  embedding_provider?: string
  embedding_model?: string
  dimension?: number
}

export async function GET() {
  try {
    const base = serviceBase()
    const result = await fetchJson<KnowledgeBasesResp>(`${base.knowledge}/api/v1/knowledge/bases`)
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as CreateKbBody
    const base = serviceBase()
    const result = await fetchJson<KnowledgeBaseCreateResp>(`${base.knowledge}/api/v1/knowledge/bases`, {
      method: 'POST',
      body: JSON.stringify({
        name: payload.name,
        description: payload.description || '',
        embedding_provider: payload.embedding_provider,
        embedding_model: payload.embedding_model,
        dimension: payload.dimension,
      }),
    })
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
