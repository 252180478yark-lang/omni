import { describe, expect, it } from 'vitest'

import {
  FEATURE_DEFINITION_REVISION,
  FEATURE_REGISTRY,
  featuresForPlacement,
  resolveFeatureHref,
  resolveFeatureSurface,
} from '@/lib/feature-registry'

describe('generated FeatureDefinition projection', () => {
  it('drives visible sidebar and home identities without duplicate hrefs', () => {
    expect(FEATURE_DEFINITION_REVISION).toMatch(/^sha256:[0-9a-f]{64}$/)
    for (const placement of ['sidebar', 'home', 'onboarding'] as const) {
      const entries = featuresForPlacement(placement)
      expect(new Set(entries.map((entry) => entry.href)).size).toBe(entries.length)
      expect(entries.every((entry) => entry.visible && entry.lifecycle === 'active')).toBe(true)
    }
    expect(FEATURE_REGISTRY).toHaveLength(26)
    expect(FEATURE_REGISTRY.every((entry) => entry.owner.id && entry.owned_surfaces.includes(entry.href))).toBe(true)
    expect(FEATURE_REGISTRY.every((entry) => entry.ia.primary_order >= 0)).toBe(true)
  })

  it('keeps real capability pages as owned renderers and registers genuine compatibility aliases', () => {
    for (const [href, featureId] of [
      ['/ad-review/flywheel', 'ad-review'],
      ['/content-leaderboard', 'commerce-feedback'],
      ['/decisions', 'workspace-operations'],
      ['/insights', 'workspace-operations'],
      ['/review', 'workspace-operations'],
    ] as const) {
      expect(resolveFeatureSurface(href)).toMatchObject({ kind: 'owned', featureId })
    }
    expect(resolveFeatureSurface('/system-graph')).toMatchObject({
      kind: 'canonical',
      canonicalHref: '/system-graph',
      featureId: 'system-convergence-s4-s6',
    })
    expect(resolveFeatureHref('/qa')).toEqual({ href: '/chat', deprecated: true, featureId: 'chat' })
    expect(resolveFeatureSurface('/qa')).toMatchObject({
      kind: 'alias',
      canonicalHref: '/chat',
      featureId: 'chat',
    })
    expect(resolveFeatureHref('/marketing/review')).toEqual({
      href: '/ad-review',
      deprecated: true,
      featureId: 'ad-review',
    })
    expect(resolveFeatureSurface('/marketing/review')).toMatchObject({
      kind: 'alias',
      canonicalHref: '/ad-review',
      featureId: 'ad-review',
    })
  })

  it('keeps real developer renderers canonical instead of swallowing them as console aliases', () => {
    for (const [href, featureId] of [
      ['/agent-log', 'agent-log'],
      ['/playground', 'playground'],
      ['/prompt-lab', 'prompt-lab'],
      ['/knowledge/evaluate', 'knowledge-evaluation'],
      ['/models', 'model-management'],
    ] as const) {
      expect(resolveFeatureSurface(href)).toMatchObject({
        kind: 'canonical',
        canonicalHref: href,
        featureId,
      })
    }
  })

  it('resolves dynamic and exact owned surfaces without prefix swallowing', () => {
    expect(resolveFeatureSurface('/sku/sku-123')).toMatchObject({
      kind: 'owned',
      canonicalHref: '/products',
      matchedSurface: '/sku/[id]',
      featureId: 'product-management',
    })
    expect(resolveFeatureSurface('/ad-review/flywheel')).toMatchObject({
      kind: 'owned',
      canonicalHref: '/ad-review',
      featureId: 'ad-review',
    })
    expect(resolveFeatureSurface('/ad-review/flywheel/details').kind).toBe('unregistered')
  })
})
