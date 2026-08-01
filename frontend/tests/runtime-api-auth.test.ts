import { afterEach, describe, expect, it, vi } from 'vitest'

import { GET as readFindings } from '@/app/api/omni/runtime-findings/route'
import { POST as createPlanDraft } from '@/app/api/omni/runtime-plan-drafts/route'
import { POST as openVisibleAuth } from '@/app/api/omni/host-bridge/sessions/[sessionId]/visible-auth/route'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('runtime BFF authentication', () => {
  it('rejects anonymous trace reads before contacting an upstream service', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const response = await readFindings(new Request('http://localhost/api/omni/runtime-findings?trace_id=trace:one'))

    expect(response.status).toBe(401)
    expect(await response.json()).toMatchObject({ error: { code: 'authentication_required' } })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects a cross-site or originless plan mutation before authentication or upstream access', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const response = await createPlanDraft(new Request('http://localhost/api/omni/runtime-plan-drafts', {
      method: 'POST', body: '{}', headers: { 'Content-Type': 'application/json' },
    }))

    expect(response.status).toBe(403)
    expect(await response.json()).toMatchObject({ error: { code: 'csrf_origin_required' } })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects an originless visible-auth mutation before Host access', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const response = await openVisibleAuth(new Request('http://localhost/api/omni/host-bridge/sessions/session:one/visible-auth', {
      method: 'POST', body: '{}', headers: { 'Content-Type': 'application/json' },
    }), { params: Promise.resolve({ sessionId: 'session:one' }) })

    expect(response.status).toBe(403)
    expect(await response.json()).toMatchObject({ error: { code: 'csrf_origin_required' } })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
