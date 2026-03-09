import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface TasksResp {
  code: number
  message: string
  data: Array<{
    id: string
    kb_id: string
    title: string | null
    source_url: string | null
    status: string
    error: string | null
    document_id: string | null
    created_at: string
    updated_at: string
    progress: number
  }>
}

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url)
    const kbId = searchParams.get('kb_id')
    const status = searchParams.get('status')
    const limit = searchParams.get('limit') || '100'
    const params = new URLSearchParams({ limit })
    if (kbId) params.set('kb_id', kbId)
    if (status) params.set('status', status)

    const base = serviceBase()
    const result = await fetchJson<TasksResp>(`${base.knowledge}/api/v1/knowledge/tasks?${params.toString()}`)
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
