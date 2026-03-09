import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface IngestBody {
  kb_id: string
  title: string
  text: string
  source_url?: string
}

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as IngestBody
    const base = serviceBase()
    const result = await fetchJson<{ data: { task_id: string } }>(`${base.knowledge}/api/v1/knowledge/ingest`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    return Response.json({ success: true, data: result.data })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
