import { describe, expect, it } from 'vitest'

import {
  approvalServiceHeaders,
  requireSameOrigin,
  verifyAuthenticatedActor,
} from '@/app/api/omni/_shared'

describe('single-user local trust', () => {
  it('resolves the local owner without a product login or bearer token', async () => {
    await expect(verifyAuthenticatedActor(null)).resolves.toEqual({ id: 'local-owner', role: 'owner' })
    expect(approvalServiceHeaders('POST', '/api/v1/approval-operations', { id: 'local-owner', role: 'owner' }))
      .toEqual({ 'X-Omni-Actor-Id': 'local-owner', 'X-Omni-Actor-Role': 'owner' })
  })

  it('still rejects cross-origin browser mutations', () => {
    const request = new Request('http://127.0.0.1:3000/api/omni/runtime-plan-drafts', {
      method: 'POST', headers: { origin: 'https://attacker.example' },
    })
    expect(() => requireSameOrigin(request)).toThrowError(/same-origin request required/)
  })
})
