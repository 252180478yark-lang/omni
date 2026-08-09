import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import {
  LOCAL_OWNER,
  requireApprovalActor,
  requireSameOrigin,
  ServiceFetchError,
} from '@/app/api/omni/_shared'
import { GET as readSession, POST as openSession } from '@/app/api/omni/auth/session/route'
import { POST as approve } from '@/app/api/omni/inbox/[id]/approve/route'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('single-user local browser session', () => {
  it('projects the fixed local owner without a cookie, account or upstream call', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await expect(requireApprovalActor(new Request('http://localhost/api/omni/inbox'))).resolves.toEqual(LOCAL_OWNER)
    const response = await readSession()
    expect(await response.json()).toEqual({ success: true, mode: 'single-user-local', actor: LOCAL_OWNER })
    expect(response.headers.get('set-cookie')).toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('keeps POST compatibility without reading or storing submitted credentials', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const response = await openSession(new Request('http://localhost/api/omni/auth/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: 'http://localhost', Host: 'localhost' },
      body: JSON.stringify({ email: 'ignored@example.test', password: 'ignored-password' }),
    }))
    expect(await response.json()).toEqual({ success: true, mode: 'single-user-local', actor: LOCAL_OWNER })
    expect(response.headers.get('set-cookie')).toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects cross-origin approval before upstream calls', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const response = await approve(
      new Request('http://localhost/api/omni/inbox/gate-1/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Origin: 'https://evil.example', Host: 'localhost' },
        body: JSON.stringify({ note: '' }),
      }),
      { params: { id: 'gate-1' } },
    )
    expect(response.status).toBe(403)
    expect((await response.json()).error).toBe('csrf_origin_mismatch')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('requires an exact same-origin mutation', () => {
    expect(() => requireSameOrigin(new Request('http://localhost/action', {
      method: 'POST', headers: { Origin: 'http://localhost', Host: 'localhost' },
    }))).not.toThrow()
    expect(() => requireSameOrigin(new Request('http://localhost/action', {
      method: 'POST', headers: { Host: 'localhost' },
    }))).toThrowError(ServiceFetchError)
  })

  it('contains no browser session token path and gates WebSocket upgrades by origin', () => {
    const page = readFileSync(resolve(process.cwd(), 'src/app/inbox/page.tsx'), 'utf8')
    const server = readFileSync(resolve(process.cwd(), 'server.ts'), 'utf8')
    const ws = readFileSync(resolve(process.cwd(), 'src/lib/agent-chat/ws-handler.ts'), 'utf8')
    expect(page).not.toMatch(/localStorage|sessionStorage/)
    expect(server).toContain('isSameOriginWebSocketUpgrade')
    expect(server).not.toContain('omni_approval_session')
    expect(server).not.toMatch(/[?&](?:token|access_token)=/)
    expect(ws).toContain("approvalAuthorization === 'invalid-origin'")
    expect(ws).toContain("same_origin_required")
    expect(ws.match(/_approvalConnections\.add\(ws\)/g)).toHaveLength(1)
    expect(ws).not.toContain('OMNI_APPROVAL_SERVICE_SECRET')
  })
})
