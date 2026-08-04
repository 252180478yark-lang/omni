import { afterEach, describe, expect, it, vi } from 'vitest'

import { POST as rebuildKnowledgeBase } from '@/app/api/omni/knowledge/bases/[kbId]/rebuild/route'
import { POST as evaluateKnowledge } from '@/app/api/omni/knowledge/rag/evaluate/route'
import { GET as getModels, POST as mutateModels } from '@/app/api/omni/models/route'
import { GET as getPromptNode } from '@/app/api/omni/prompt/nodes/[id]/route'
import { GET as getPromptNodes } from '@/app/api/omni/prompt/nodes/route'
import { DELETE as deletePromptRule, PATCH as patchPromptRule } from '@/app/api/omni/prompt/rules/[id]/route'
import { GET as getPromptRules, POST as createPromptRule } from '@/app/api/omni/prompt/rules/route'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function sameOriginPost(path: string, body = '{}'): Request {
  return new Request(`http://localhost${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Origin: 'http://localhost' },
    body,
  })
}

describe('developer-mode permission boundaries', () => {
  it('does not expose model configuration details without an owner/admin session', async () => {
    const upstream = vi.fn()
    vi.stubGlobal('fetch', upstream)

    const response = await getModels(new Request('http://localhost/api/omni/models'))

    expect(response.status).toBe(401)
    expect(await response.json()).toEqual({ success: false, error: 'authentication_required' })
    expect(upstream).not.toHaveBeenCalled()
  })

  it('does not promote a normal authenticated user into the owner/admin developer boundary', async () => {
    vi.stubEnv('IDENTITY_SERVICE_URL', 'http://identity.test')
    const upstream = vi.fn(async (input: string | URL | Request) => {
      expect(String(input)).toBe('http://identity.test/api/v1/auth/verify')
      return new Response(JSON.stringify({
        data: { valid: true, sub: 'normal-user@example.test', role: 'user' },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', upstream)

    const response = await getModels(new Request('http://localhost/api/omni/models', {
      headers: { Cookie: 'omni_approval_session=normal-user-session' },
    }))

    expect(response.status).toBe(403)
    expect(await response.json()).toEqual({ success: false, error: 'approval_admin_required' })
    expect(upstream).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['prompt node inventory', () => getPromptNodes(new Request('http://localhost/api/omni/prompt/nodes'))],
    ['prompt node details', () => getPromptNode(
      new Request('http://localhost/api/omni/prompt/nodes/node-1'),
      { params: { id: 'node-1' } },
    )],
    ['prompt rule details', () => getPromptRules(new Request('http://localhost/api/omni/prompt/rules?node_id=node-1'))],
  ])('does not expose %s without an owner/admin session', async (_label, invoke) => {
    const upstream = vi.fn()
    vi.stubGlobal('fetch', upstream)

    const response = await invoke()

    expect(response.status).toBe(401)
    expect(await response.json()).toEqual({ success: false, error: 'authentication_required' })
    expect(upstream).not.toHaveBeenCalled()
  })

  it.each([
    ['model mutation', () => mutateModels(sameOriginPost('/api/omni/models', JSON.stringify({ action: 'refresh' })))],
    ['knowledge evaluation', () => evaluateKnowledge(sameOriginPost('/api/omni/knowledge/rag/evaluate'))],
    ['knowledge rebuild', () => rebuildKnowledgeBase(
      sameOriginPost('/api/omni/knowledge/bases/kb-1/rebuild'),
      { params: { kbId: 'kb-1' } },
    )],
    ['prompt rule creation', () => createPromptRule(sameOriginPost('/api/omni/prompt/rules'))],
    ['prompt rule update', () => patchPromptRule(
      new Request('http://localhost/api/omni/prompt/rules/rule-1', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Origin: 'http://localhost' },
        body: '{}',
      }),
      { params: { id: 'rule-1' } },
    )],
    ['prompt rule deletion', () => deletePromptRule(
      new Request('http://localhost/api/omni/prompt/rules/rule-1', {
        method: 'DELETE',
        headers: { Origin: 'http://localhost' },
      }),
      { params: { id: 'rule-1' } },
    )],
  ])('rejects anonymous %s before any upstream request', async (_label, invoke) => {
    const upstream = vi.fn()
    vi.stubGlobal('fetch', upstream)

    const response = await invoke()

    expect(response.status).toBe(401)
    expect(await response.json()).toEqual({ success: false, error: 'authentication_required' })
    expect(upstream).not.toHaveBeenCalled()
  })

  it('rejects a cross-origin developer mutation before identity or upstream access', async () => {
    const upstream = vi.fn()
    vi.stubGlobal('fetch', upstream)
    const request = new Request('http://localhost/api/omni/models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: 'https://attacker.example' },
      body: JSON.stringify({ action: 'update-provider', providerId: 'openai', apiKey: 'not-forwarded' }),
    })

    const response = await mutateModels(request)

    expect(response.status).toBe(403)
    expect(await response.json()).toEqual({ success: false, error: 'csrf_origin_mismatch' })
    expect(upstream).not.toHaveBeenCalled()
  })
})
