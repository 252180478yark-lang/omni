import { serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
export const maxDuration = 300

async function proxyPost(upstreamUrl: string, payload: unknown): Promise<Response> {
  console.log('[proxyPost] →', upstreamUrl, JSON.stringify(payload).slice(0, 200))
  const upstream = await fetch(upstreamUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    cache: 'no-store',
  })
  console.log('[proxyPost] ←', upstream.status, upstream.statusText)
  if (!upstream.ok) {
    let detail = ''
    try {
      const body = await upstream.json()
      detail = body?.detail || body?.error || body?.message || ''
      console.log('[proxyPost] ERROR detail:', detail)
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
    if (action === 'cancel') {
      const jobId = (payload as { job_id?: string })?.job_id
      if (!jobId || typeof jobId !== 'string') {
        return Response.json({ success: false, error: 'job_id required' }, { status: 400 })
      }
      return proxyPost(`${base.knowledge}/api/v1/knowledge/harvester/jobs/${encodeURIComponent(jobId)}/cancel`, {})
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
    if (action === 'feishu-browser-login') {
      return proxyPost(`${base.knowledge}/api/v1/knowledge/harvester/feishu-browser-login`, payload)
    }
    if (action === 'upload-extracted-page') {
      return proxyPost(`${base.knowledge}/api/v1/knowledge/harvester/upload-extracted-page`, payload)
    }
    if (action === 'upload-login-cookies') {
      return proxyPost(`${base.knowledge}/api/v1/knowledge/harvester/upload-login-cookies`, payload)
    }

    return Response.json({ success: false, error: 'Unknown action' }, { status: 400 })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}

export async function DELETE(request: Request) {
  try {
    const url = new URL(request.url)
    const authType = url.searchParams.get('auth_type')
    const base = serviceBase()
    const endpoint = authType === 'feishu'
      ? `${base.knowledge}/api/v1/knowledge/harvester/feishu-auth`
      : `${base.knowledge}/api/v1/knowledge/harvester/auth`
    const upstream = await fetch(endpoint, {
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

    const authType = url.searchParams.get('auth_type')

    const latestUpload = url.searchParams.get('latest_upload')

    let target: string
    if (latestUpload) {
      target = `${base.knowledge}/api/v1/knowledge/harvester/latest-upload`
    } else if (loginSessionId) {
      target = `${base.knowledge}/api/v1/knowledge/harvester/browser-login/${loginSessionId}`
    } else if (jobId && listImages) {
      target = `${base.knowledge}/api/v1/knowledge/harvester/jobs/${jobId}/images`
        + (chapterIndex ? `?chapter_index=${chapterIndex}` : '')
    } else if (jobId) {
      target = `${base.knowledge}/api/v1/knowledge/harvester/jobs/${jobId}`
    } else if (authType === 'feishu') {
      target = `${base.knowledge}/api/v1/knowledge/harvester/feishu-auth-status`
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
