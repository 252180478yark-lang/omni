import { serviceBase } from '../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

/**
 * POST /api/omni/knowledge/upload
 * Proxies multipart file upload to knowledge-engine /api/v1/knowledge/documents/ingest.
 */
export async function POST(request: Request) {
  try {
    const formData = await request.formData()
    const base = serviceBase()

    const upstream = await fetch(`${base.knowledge}/api/v1/knowledge/documents/ingest`, {
      method: 'POST',
      body: formData,
    })

    if (!upstream.ok) {
      const text = await upstream.text()
      return Response.json(
        { success: false, error: `${upstream.status}: ${text}` },
        { status: upstream.status },
      )
    }

    const json = await upstream.json()
    return Response.json({ success: true, data: json.data ?? json })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
