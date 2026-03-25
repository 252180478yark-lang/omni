import { serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
export const maxDuration = 300

async function proxyPost(upstreamUrl: string, payload: unknown): Promise<Response> {
  const upstream = await fetch(upstreamUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    cache: 'no-store',
  })
  if (!upstream.ok) {
    let detail = ''
    try {
      const body = await upstream.json()
      detail = body?.detail || body?.error || body?.message || ''
    } catch {
      try { detail = await upstream.text() } catch { /* noop */ }
    }
    return Response.json(
      { success: false, error: detail || `${upstream.status} ${upstream.statusText}` },
      { status: upstream.status },
    )
  }
  const json = await upstream.json()
  return Response.json(json)
}

export async function POST(request: Request) {
  try {
    const url = new URL(request.url)
    const action = url.searchParams.get('action') || 'crawl'
    const base = serviceBase()
    const payload = await request.json()

    if (action === 'tree') {
      return proxyPost(`${base.knowledge}/api/v1/knowledge/harvester/tree`, payload)
    }
    if (action === 'crawl') {
      return proxyPost(`${base.knowledge}/api/v1/knowledge/harvester/crawl`, payload)
    }
    if (action === 'save') {
      return proxyPost(`${base.knowledge}/api/v1/knowledge/harvester/save`, payload)
    }
    if (action === 'save-auth') {
      return proxyPost(`${base.knowledge}/api/v1/knowledge/harvester/save-auth`, payload)
    }
    if (action === 'analyze-images') {
      return proxyPost(`${base.knowledge}/api/v1/knowledge/harvester/analyze-images`, payload)
    }
    if (action === 'browser-login') {
      return proxyPost(`${base.knowledge}/api/v1/knowledge/harvester/browser-login`, payload)
    }

    return Response.json({ success: false, error: 'Unknown action' }, { status: 400 })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}

export async function DELETE() {
  try {
    const base = serviceBase()
    const upstream = await fetch(`${base.knowledge}/api/v1/knowledge/harvester/auth`, {
      method: 'DELETE',
      cache: 'no-store',
    })
    const json = await upstream.json()
    return Response.json(json)
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url)
    const jobId = url.searchParams.get('job_id')
    const base = serviceBase()

    const chapterIndex = url.searchParams.get('chapter_index')
    const listImages = url.searchParams.get('images')

    const loginSessionId = url.searchParams.get('login_session_id')

    let target: string
    if (loginSessionId) {
      target = `${base.knowledge}/api/v1/knowledge/harvester/browser-login/${loginSessionId}`
    } else if (jobId && listImages) {
      target = `${base.knowledge}/api/v1/knowledge/harvester/jobs/${jobId}/images`
        + (chapterIndex ? `?chapter_index=${chapterIndex}` : '')
    } else if (jobId) {
      target = `${base.knowledge}/api/v1/knowledge/harvester/jobs/${jobId}`
    } else {
      target = `${base.knowledge}/api/v1/knowledge/harvester/auth-status`
    }

    const upstream = await fetch(target, { cache: 'no-store' })
    if (!upstream.ok) {
      let detail = ''
      try {
        const body = await upstream.json()
        detail = body?.detail || body?.error || ''
      } catch { /* noop */ }
      return Response.json(
        { success: false, error: detail || `${upstream.status} ${upstream.statusText}` },
        { status: upstream.status },
      )
    }
    const json = await upstream.json()
    return Response.json(json)
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
