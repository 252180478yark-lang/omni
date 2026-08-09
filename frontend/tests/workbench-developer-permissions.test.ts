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
    headers: { 'Content-Type': 'application/json', Origin: 'http://localhost', Host: 'localhost' },
    body,
  })
}

function upstreamFixture() {
  const upstream = vi.fn(async () => new Response('{}', {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }))
  vi.stubGlobal('fetch', upstream)
  return upstream
}

describe('single-user developer-mode boundaries', () => {
  it.each([
    ['models', () => getModels(new Request('http://localhost/api/omni/models'))],
    ['prompt node inventory', () => getPromptNodes(new Request('http://localhost/api/omni/prompt/nodes'))],
    ['prompt node details', () => getPromptNode(
      new Request('http://localhost/api/omni/prompt/nodes/node-1'),
      { params: { id: 'node-1' } },
    )],
    ['prompt rules', () => getPromptRules(new Request('http://localhost/api/omni/prompt/rules?node_id=node-1'))],
  ])('allows the local owner to read %s without a session', async (_label, invoke) => {
    const upstream = upstreamFixture()
    const response = await invoke()
    expect([401, 403]).not.toContain(response.status)
    expect(upstream, `${response.status} ${await response.clone().text()}`).toHaveBeenCalled()
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
        method: 'PATCH', headers: { 'Content-Type': 'application/json', Origin: 'http://localhost', Host: 'localhost' }, body: '{}',
      }),
      { params: { id: 'rule-1' } },
    )],
    ['prompt rule deletion', () => deletePromptRule(
      new Request('http://localhost/api/omni/prompt/rules/rule-1', {
        method: 'DELETE', headers: { Origin: 'http://localhost', Host: 'localhost' },
      }),
      { params: { id: 'rule-1' } },
    )],
  ])('allows same-origin local-owner %s without a session', async (_label, invoke) => {
    const upstream = upstreamFixture()
    const response = await invoke()
    expect([401, 403]).not.toContain(response.status)
    expect(upstream, `${response.status} ${await response.clone().text()}`).toHaveBeenCalled()
  })

  it('rejects a cross-origin developer mutation before upstream access', async () => {
    const upstream = upstreamFixture()
    const response = await mutateModels(new Request('http://localhost/api/omni/models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: 'https://attacker.example', Host: 'localhost' },
      body: JSON.stringify({ action: 'update-provider', providerId: 'openai', apiKey: 'not-forwarded' }),
    }))
    expect(response.status).toBe(403)
    expect(await response.json()).toEqual({ success: false, error: 'csrf_origin_mismatch' })
    expect(upstream).not.toHaveBeenCalled()
  })
})
