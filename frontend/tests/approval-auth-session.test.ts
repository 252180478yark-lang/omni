import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import {
  approvalAuthorizationFromCookie,
  requireApprovalActor,
  requireSameOrigin,
  ServiceFetchError,
} from '@/app/api/omni/_shared'
import { POST as login } from '@/app/api/omni/auth/session/route'
import { POST as approve } from '@/app/api/omni/inbox/[id]/approve/route'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('approval browser session', () => {
  it('ignores legacy browser cookies and resolves the configured local owner', async () => {
    const verify = vi.fn()
    vi.stubGlobal('fetch', verify)
    const request = new Request('http://localhost/api/omni/inbox', {
      headers: { Cookie: 'theme=dark; omni_approval_session=test-token-jwt-value' },
    })
    await expect(requireApprovalActor(request)).resolves.toEqual({ id: 'local-owner', role: 'owner' })
    expect(approvalAuthorizationFromCookie(request.headers.get('cookie'))).toBe(
      'Bearer test-token-jwt-value',
    )
  })

  it('returns local-owner trust without calling Identity or issuing a product session', async () => {
    const upstream = vi.fn()
    vi.stubGlobal('fetch', upstream)
    const response = await login(new Request('http://localhost/api/omni/auth/session', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: 'http://localhost',
        Host: 'localhost',
      },
      body: JSON.stringify({}),
    }))
    const body = await response.json()
    const cookie = response.headers.get('set-cookie') || ''
    expect(response.status).toBe(200)
    expect(body).toEqual({ success: true, actor: { id: 'local-owner', role: 'owner' }, trust_mode: 'trusted-local' })
    expect(cookie).not.toContain('omni_approval_session')
    expect(upstream).not.toHaveBeenCalled()
  })

  it('rejects cross-origin approval before identity or upstream calls', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const response = await approve(
      new Request('http://localhost/api/omni/inbox/gate-1/approve', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Origin: 'https://evil.example',
          Host: 'localhost',
          Cookie: 'omni_approval_session=test-token-jwt-value',
        },
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

  it('keeps JWTs out of browser storage and gates WS approval broadcasts', () => {
    const page = readFileSync(resolve(process.cwd(), 'src/app/inbox/page.tsx'), 'utf8')
    const server = readFileSync(resolve(process.cwd(), 'server.ts'), 'utf8')
    const ws = readFileSync(resolve(process.cwd(), 'src/lib/agent-chat/ws-handler.ts'), 'utf8')
    expect(page).not.toMatch(/localStorage|sessionStorage/)
    expect(server).toContain('approvalAuthorizationFromCookie')
    expect(server).not.toMatch(/[?&](?:token|access_token)=/)
    expect(ws).toContain('verifyApprovalActor(approvalAuthorization)')
    expect(ws.indexOf('verifyApprovalActor(approvalAuthorization)')).toBeLessThan(
      ws.indexOf('_approvalConnections.add(ws)'),
    )
    expect(ws.match(/_approvalConnections\.add\(ws\)/g)).toHaveLength(1)
    expect(ws.indexOf('verifyApprovalActor(approvalAuthorization)', ws.indexOf("msg.kind === 'human_gate_decide'"))).toBeLessThan(
      ws.indexOf('fetch(url', ws.indexOf("msg.kind === 'human_gate_decide'")),
    )
    expect(ws).not.toContain("detail: e.message")
  })
})
