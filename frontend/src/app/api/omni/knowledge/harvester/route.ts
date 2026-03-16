import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
export const maxDuration = 300

export async function POST(request: Request) {
  try {
    const url = new URL(request.url)
    const action = url.searchParams.get('action') || 'crawl'
    const base = serviceBase()
    const payload = await request.json()

    if (action === 'tree') {
      const result = await fetchJson<{ success: boolean; data: unknown }>(
        `${base.knowledge}/api/v1/knowledge/harvester/tree`,
        { method: 'POST', body: JSON.stringify(payload) },
      )
      return Response.json(result)
    }

    if (action === 'crawl') {
      const result = await fetchJson<{ success: boolean; data: { job_id: string } }>(
        `${base.knowledge}/api/v1/knowledge/harvester/crawl`,
        { method: 'POST', body: JSON.stringify(payload) },
      )
      return Response.json(result)
    }

    if (action === 'save') {
      const result = await fetchJson<{ success: boolean; data: unknown }>(
        `${base.knowledge}/api/v1/knowledge/harvester/save`,
        { method: 'POST', body: JSON.stringify(payload) },
      )
      return Response.json(result)
    }

    return Response.json({ success: false, error: 'Unknown action' }, { status: 400 })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url)
    const jobId = url.searchParams.get('job_id')
    const base = serviceBase()

    if (jobId) {
      const result = await fetchJson<{ success: boolean; data: unknown }>(
        `${base.knowledge}/api/v1/knowledge/harvester/jobs/${jobId}`,
      )
      return Response.json(result)
    }

    const result = await fetchJson<{ success: boolean; data: unknown }>(
      `${base.knowledge}/api/v1/knowledge/harvester/auth-status`,
    )
    return Response.json(result)
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
