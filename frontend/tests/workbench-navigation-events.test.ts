import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { POST } from '@/app/api/omni/workbench/navigation-events/route'

let directory = ''
let tokenPath = ''
let actorSerial = 0

beforeAll(() => {
  directory = mkdtempSync(join(tmpdir(), 'omni-workbench-telemetry-'))
  tokenPath = join(directory, 'token')
  writeFileSync(tokenPath, 'test-compatibility-token-value-long-enough', 'utf8')
})

afterAll(() => {
  rmSync(directory, { recursive: true, force: true })
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

function request(
  body: unknown,
  options: { withOrigin?: boolean; authenticated?: boolean; host?: string } = {},
): Request {
  const withOrigin = options.withOrigin ?? true
  const authenticated = options.authenticated ?? true
  const host = options.host ?? 'localhost'
  return new Request(`http://${host}/api/omni/workbench/navigation-events`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Host: host,
      ...(withOrigin ? { Origin: `http://${host}` } : {}),
      ...(authenticated ? { Cookie: 'omni_approval_session=test-browser-session' } : {}),
    },
    body: JSON.stringify(body),
  })
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function enableServices(options: {
  actorId?: string
  identityUnavailable?: boolean
  role?: string
  knowledgeStatus?: number
} = {}) {
  actorSerial += 1
  const actorId = options.actorId ?? `user-${actorSerial}`
  const knowledgeBodies: Array<Record<string, unknown>> = []
  vi.stubEnv('IDENTITY_SERVICE_URL', 'http://identity.test')
  vi.stubEnv('KNOWLEDGE_ENGINE_URL', 'http://knowledge.test')
  vi.stubEnv('OMNI_COMPATIBILITY_TOKEN_FILE', tokenPath)
  const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input)
    if (url === 'http://identity.test/api/v1/auth/verify') {
      if (options.identityUnavailable) throw new Error('identity unavailable')
      return json({ data: { valid: true, sub: actorId, role: options.role ?? 'user' } })
    }
    if (url === 'http://knowledge.test/api/v1/compatibility/telemetry') {
      knowledgeBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
      return json({}, options.knowledgeStatus ?? 200)
    }
    throw new Error(`unexpected fetch destination: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, knowledgeBodies }
}

const aliasPayload = (result: 'redirected' | 'recovered' | 'failed') => ({
  event_type: 'legacy_alias',
  requested_href: '/qa',
  canonical_href: '/chat',
  feature_id: 'chat',
  result,
})

describe('workbench navigation telemetry BFF', () => {
  it('requires a verified browser actor after same-origin validation', async () => {
    const { fetchMock, knowledgeBodies } = enableServices()
    const anonymous = await POST(request(aliasPayload('redirected'), { authenticated: false }))
    expect(anonymous.status).toBe(401)
    expect(await anonymous.json()).toMatchObject({
      error: { code: 'authentication_required', retryable: false },
    })
    expect(fetchMock).not.toHaveBeenCalled()
    expect(knowledgeBodies).toHaveLength(0)

    const originless = await POST(request(aliasPayload('redirected'), { withOrigin: false }))
    expect(originless.status).toBe(403)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('returns typed identity-unavailable before reading the service token or writing telemetry', async () => {
    const { fetchMock, knowledgeBodies } = enableServices({ identityUnavailable: true })
    vi.stubEnv('OMNI_COMPATIBILITY_TOKEN_FILE', join(directory, 'missing'))
    const response = await POST(request(aliasPayload('redirected')))
    expect(response.status).toBe(503)
    expect(await response.json()).toMatchObject({
      error: { code: 'identity_verification_unavailable', retryable: true },
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(knowledgeBodies).toHaveLength(0)
  })

  it('accepts and registry-revalidates redirected, recovered and failed alias outcomes', async () => {
    const { fetchMock, knowledgeBodies } = enableServices()
    for (const result of ['redirected', 'recovered', 'failed'] as const) {
      const response = await POST(request(aliasPayload(result)))
      expect(response.status).toBe(202)
      expect(await response.json()).toEqual({ success: true, accepted: true })
    }

    expect(fetchMock).toHaveBeenCalledTimes(6)
    expect(knowledgeBodies).toHaveLength(3)
    const results = ['redirected', 'recovered', 'failed']
    for (let index = 0; index < results.length; index += 1) {
      const result = results[index]
      expect(knowledgeBodies[index]).toMatchObject({
        client_id: 'web-workbench',
        capability_id: 'legacy-alias:qa:chat',
        route_family: 'workbench-alias:chat',
        exclusive: false,
        metadata: { state: result, reason_code: 'legacy_alias' },
      })
      expect(JSON.stringify(knowledgeBodies[index])).not.toContain('test-compatibility-token')
    }
  })

  it('accepts the current Identity user role for non-privileged navigation evidence', async () => {
    const { knowledgeBodies } = enableServices({ role: 'user', actorId: 'normal-user@example.test' })

    const response = await POST(request(aliasPayload('redirected')))

    expect(response.status).toBe(202)
    expect(await response.json()).toEqual({ success: true, accepted: true })
    expect(knowledgeBodies).toHaveLength(1)
  })

  it('accepts selected intent and opened mount only when registry mode/group placement matches', async () => {
    const { knowledgeBodies } = enableServices()
    for (const result of ['selected', 'opened'] as const) {
      const response = await POST(request({
        event_type: 'primary_navigation',
        requested_href: '/sku-pipeline',
        canonical_href: '/sku-pipeline',
        feature_id: 'sku-pipeline',
        mode: 'development',
        primary_group: 'workflows',
        secondary_depth: 0,
        result,
      }))
      expect(response.status).toBe(202)
    }
    expect(knowledgeBodies.map((body) => (body.metadata as Record<string, unknown>).state)).toEqual([
      'selected', 'opened',
    ])
    expect(knowledgeBodies[0]).toMatchObject({
      capability_id: 'navigation:sku-pipeline',
      route_family: 'workbench-nav:development:workflows:depth-0',
    })

    const pollutedDepth = await POST(request({
      event_type: 'primary_navigation',
      requested_href: '/sku-pipeline',
      canonical_href: '/sku-pipeline',
      feature_id: 'sku-pipeline',
      mode: 'development',
      primary_group: 'workflows',
      secondary_depth: 1,
      result: 'selected',
    }))
    expect(pollutedDepth.status).toBe(400)

    const mismatch = await POST(request({
      event_type: 'primary_navigation',
      requested_href: '/sku-pipeline',
      canonical_href: '/sku-pipeline',
      feature_id: 'sku-pipeline',
      mode: 'development',
      primary_group: 'agents',
      secondary_depth: 1,
      result: 'selected',
    }))
    expect(mismatch.status).toBe(400)
    expect(knowledgeBodies).toHaveLength(2)
  })

  it('hashes authenticated route gaps rather than persisting arbitrary path content', async () => {
    const { knowledgeBodies } = enableServices()
    const response = await POST(request({
      event_type: 'route_gap',
      requested_href: '/customer/private-object-123',
      result: 'unregistered',
    }))
    expect(response.status).toBe(202)
    expect(knowledgeBodies).toHaveLength(1)
    expect(knowledgeBodies[0].capability_id).toMatch(/^route-gap:sha256-[0-9a-f]{16}$/)
    expect(JSON.stringify(knowledgeBodies[0])).not.toContain('private-object-123')
  })

  it('rejects tampered alias identities and the six real pages as alias evidence', async () => {
    const { knowledgeBodies } = enableServices()
    for (const payload of [
      { ...aliasPayload('recovered'), canonical_href: '/workspace' },
      {
        event_type: 'legacy_alias', requested_href: '/ad-review/flywheel',
        canonical_href: '/ad-review', feature_id: 'ad-review', result: 'redirected',
      },
      { ...aliasPayload('failed'), observed_at: 'forged' },
    ]) {
      expect((await POST(request(payload))).status).toBe(400)
    }
    expect(knowledgeBodies).toHaveLength(0)
  })

  it('deduplicates identical per-actor outcomes in one minute and uses a minute-bucket timestamp', async () => {
    const fixedNow = Date.parse('2026-08-02T10:37:42.999Z')
    vi.spyOn(Date, 'now').mockReturnValue(fixedNow)
    const { knowledgeBodies } = enableServices()
    const payload = aliasPayload('recovered')
    const first = await POST(request(payload))
    const duplicate = await POST(request(payload))

    expect(first.status).toBe(202)
    expect(await first.json()).toEqual({ success: true, accepted: true })
    expect(duplicate.status).toBe(202)
    expect(await duplicate.json()).toEqual({ success: true, accepted: true, deduplicated: true })
    expect(knowledgeBodies).toHaveLength(1)
    expect(knowledgeBodies[0].observed_at).toBe('2026-08-02T10:37:00.000Z')
  })

  it('applies a bounded per-actor minute rate limit before any extra upstream write', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-08-02T10:38:15.000Z'))
    const { knowledgeBodies } = enableServices()
    const payload = aliasPayload('redirected')
    for (let index = 0; index < 60; index += 1) {
      expect((await POST(request(payload))).status).toBe(202)
    }
    const limited = await POST(request(payload))
    expect(limited.status).toBe(429)
    expect(await limited.json()).toMatchObject({
      error: { code: 'navigation_event_rate_limited', retryable: true },
    })
    expect(knowledgeBodies).toHaveLength(1)
  })

  it('returns typed retryable unavailable when the secret or compatibility service is down', async () => {
    const missingSecretServices = enableServices()
    vi.stubEnv('OMNI_COMPATIBILITY_TOKEN_FILE', join(directory, 'missing'))
    const missingSecret = await POST(request(aliasPayload('redirected')))
    expect(missingSecret.status).toBe(503)
    expect(await missingSecret.json()).toEqual({
      success: false,
      error: { code: 'compatibility_telemetry_unavailable', retryable: true },
    })
    expect(missingSecretServices.knowledgeBodies).toHaveLength(0)

    const upstreamDownServices = enableServices({ knowledgeStatus: 503 })
    const upstreamDown = await POST(request(aliasPayload('failed')))
    expect(upstreamDown.status).toBe(503)
    expect((await upstreamDown.json()).error).toMatchObject({
      code: 'compatibility_telemetry_unavailable',
      retryable: true,
    })
    expect(upstreamDownServices.knowledgeBodies).toHaveLength(1)
  })
})
