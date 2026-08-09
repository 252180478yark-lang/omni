// @vitest-environment happy-dom

import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import Home from '@/app/page'
import { GET } from '@/app/api/omni/overview/route'

const { redirectMock } = vi.hoisted(() => ({
  redirectMock: vi.fn((target: string) => {
    throw new Error(`redirect:${target}`)
  }),
}))

vi.mock('next/navigation', () => ({ redirect: redirectMock }))

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function dependency(dependencyId: string, state = 'unknown') {
  return {
    dependency_id: dependencyId,
    ref: `health_registration:service:${dependencyId}`,
    required: true,
    state,
    reason_codes: state === 'healthy' ? [] : ['build_identity_unknown'],
    latest_data_at: null,
    freshness_seconds: null,
    build_identity: {
      expected_commit: 'new',
      observed_commit: state === 'healthy' ? 'new' : null,
      expected_source_fingerprint: null,
      source_fingerprint: null,
      worktree_id: null,
      allocation_id: null,
      runtime_id: null,
    },
    observed_at: '2026-07-30T08:00:00Z',
  }
}

function registryHealth(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 1,
    state: 'unknown',
    healthy_percentage: 0,
    partial: true,
    generated_at: '2026-07-30T08:00:00Z',
    build_identity: {
      expected_commit: 'new',
      observed_commit: null,
      expected_source_fingerprint: 'sha256:abc',
      source_fingerprint: 'sha256:abc',
      worktree_id: 'wt-1',
      allocation_id: 'alloc-1',
      runtime_id: 'runtime-1',
    },
    features: [
      {
        feature_id: 'cost-management',
        title: '成本管理',
        href: '/cost',
        state: 'unknown',
        reason_codes: ['knowledge-engine:build_identity_unknown'],
        dependencies: [dependency('knowledge-engine')],
      },
    ],
    errors: [],
    ...overrides,
  }
}

const validStats = {
  code: 200,
  message: 'success',
  data: { knowledge_bases: 1, documents: 3, tasks_by_status: {} },
}

const validBases = { code: 200, message: 'success', data: [{ id: 'kb-1' }] }

function stubOverviewSources(
  values: { health?: Response; stats?: Response; bases?: Response } = {},
) {
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
    const url = String(input)
    if (url.endsWith('/api/v1/system/health')) return values.health || json(registryHealth())
    if (url.endsWith('/api/v1/knowledge/stats')) return values.stats || json(validStats)
    if (url.endsWith('/api/v1/knowledge/bases')) return values.bases || json(validBases)
    throw new Error('unexpected URL')
  }))
}

function stubMatchingFrontendBuild() {
  vi.stubEnv('OMNI_EXPECTED_COMMIT', 'frontend-new')
  vi.stubEnv('OMNI_BUILD_COMMIT', 'frontend-new')
  vi.stubEnv('OMNI_SOURCE_FINGERPRINT', 'sha256:frontend-new')
  vi.stubEnv('OMNI_BUILD_SOURCE_FINGERPRINT', 'sha256:frontend-new')
  vi.stubEnv('OMNI_WORKTREE_ID', 'wt-frontend')
}

beforeEach(() => {
  redirectMock.mockClear()
  stubMatchingFrontendBuild()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  window.localStorage.clear()
})

describe('overview BFF health truth', () => {
  it('preserves partial errors, redacts upstream messages, and never converts failed metrics to zero', async () => {
    vi.stubEnv('KNOWLEDGE_ENGINE_URL', 'http://knowledge.test')
    stubOverviewSources({
      stats: json({ error: { code: 'stats_down', message: 'secret-token=do-not-leak' } }, 503),
    })

    const response = await GET()
    const body = await response.json()

    expect(response.status).toBe(200)
    expect(body.data.health.summary).toBe('unknown')
    expect(body.data.health.partial).toBe(true)
    expect(body.data.health.errors[0]).toMatchObject({ code: 'stats_down', status: 503 })
    expect(JSON.stringify(body)).not.toContain('do-not-leak')
    expect(body.data.metrics.knowledgeDocuments).toBeNull()
    expect(body.data.metrics.runningTasks).toBeNull()
    expect(body.data.metrics.knowledgeBases).toBe(1)
    expect(body.data.metrics.infraUptime).toBeNull()
  })

  it('returns a typed, redacted 503 when the registry itself is unavailable', async () => {
    vi.stubEnv('KNOWLEDGE_ENGINE_URL', 'http://knowledge.test')
    stubOverviewSources({
      health: json({ error: { code: 'readiness_down', message: 'db_password=secret' } }, 503),
    })

    const response = await GET()
    const body = await response.json()

    expect(response.status).toBe(503)
    expect(body.success).toBe(false)
    expect(body.error).toMatchObject({ code: 'readiness_down', status: 503 })
    expect(JSON.stringify(body)).not.toContain('db_password')
  })

  it('rejects malformed HTTP 200 health payloads as typed 502 schema errors', async () => {
    vi.stubEnv('KNOWLEDGE_ENGINE_URL', 'http://knowledge.test')
    stubOverviewSources({ health: json({ schema_version: 1, state: 'healthy' }) })

    const response = await GET()
    const body = await response.json()

    expect(response.status).toBe(502)
    expect(body.error).toMatchObject({ code: 'upstream_schema_invalid', status: 502 })
  })

  it('degrades a healthy registry and hides 100 percent when an auxiliary source is partial', async () => {
    vi.stubEnv('KNOWLEDGE_ENGINE_URL', 'http://knowledge.test')
    stubOverviewSources({
      health: json(registryHealth({
        state: 'healthy',
        healthy_percentage: 100,
        partial: false,
        features: [{
          feature_id: 'knowledge',
          title: '知识库',
          href: '/knowledge',
          state: 'healthy',
          reason_codes: [],
          dependencies: [dependency('knowledge-engine', 'healthy')],
        }],
      })),
      stats: json({ code: 200, message: 'success', data: { documents: 'three' } }),
    })

    const response = await GET()
    const body = await response.json()

    expect(body.data.health.summary).toBe('degraded')
    expect(body.data.health.partial).toBe(true)
    expect(body.data.metrics.infraUptime).toBeNull()
    expect(body.data.health.errors[0].code).toBe('upstream_schema_invalid')
  })

  it('uses the worst repeated dependency state instead of the first one', async () => {
    vi.stubEnv('KNOWLEDGE_ENGINE_URL', 'http://knowledge.test')
    const healthyAi = dependency('ai-provider-hub', 'healthy')
    const staleAi = { ...dependency('ai-provider-hub', 'healthy'), state: 'stale', reason_codes: ['build_identity_mismatch'] }
    stubOverviewSources({
      health: json(registryHealth({
        state: 'stale',
        partial: false,
        features: [
          { feature_id: 'chat', title: '智能问答', href: '/chat', state: 'healthy', reason_codes: [], dependencies: [healthyAi] },
          { feature_id: 'news', title: '资讯中心', href: '/news', state: 'stale', reason_codes: [], dependencies: [staleAi] },
        ],
      })),
    })

    const response = await GET()
    const body = await response.json()
    expect(body.data.health.aiHub).toBe('stale')
  })

  it('bounds a hung registry request with a typed timeout', async () => {
    vi.stubEnv('KNOWLEDGE_ENGINE_URL', 'http://knowledge.test')
    vi.stubEnv('OMNI_OVERVIEW_TIMEOUT_MS', '25')
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/v1/system/health')) {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            const error = new Error('timed out with secret')
            error.name = 'TimeoutError'
            reject(error)
          })
        })
      }
      if (url.endsWith('/api/v1/knowledge/stats')) return Promise.resolve(json(validStats))
      if (url.endsWith('/api/v1/knowledge/bases')) return Promise.resolve(json(validBases))
      return Promise.reject(new Error('unexpected URL'))
    }))

    const response = await GET()
    const body = await response.json()
    expect(response.status).toBe(503)
    expect(body.error.code).toBe('upstream_timeout')
    expect(JSON.stringify(body)).not.toContain('secret')
  })

  it('marks an old frontend image stale against a newer runtime target', async () => {
    vi.stubEnv('KNOWLEDGE_ENGINE_URL', 'http://knowledge.test')
    vi.stubEnv('OMNI_EXPECTED_COMMIT', 'frontend-new')
    vi.stubEnv('OMNI_BUILD_COMMIT', 'frontend-old')
    stubOverviewSources({
      health: json(registryHealth({
        state: 'healthy',
        healthy_percentage: 100,
        partial: false,
        features: [{
          feature_id: 'knowledge',
          title: '知识库',
          href: '/knowledge',
          state: 'healthy',
          reason_codes: [],
          dependencies: [dependency('knowledge-engine', 'healthy')],
        }],
      })),
    })

    const response = await GET()
    const body = await response.json()

    expect(body.data.health.summary).toBe('stale')
    expect(body.data.health.frontendBuild).toMatchObject({
      state: 'stale',
      reasonCodes: ['frontend_build_identity_mismatch'],
    })
    expect(body.data.health.frontendBuild.buildIdentity.observed_commit).toBe('frontend-old')
    expect(body.data.metrics.infraUptime).toBeNull()
  })
})

describe('root surface convergence', () => {
  it('redirects the retired marketing dashboard to the canonical workspace', () => {
    expect(() => Home()).toThrow('redirect:/workspace')
    expect(redirectMock).toHaveBeenCalledWith('/workspace')
  })
})
