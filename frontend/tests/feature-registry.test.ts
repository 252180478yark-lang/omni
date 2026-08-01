import { describe, expect, it } from 'vitest'

import { FEATURE_DEFINITION_REVISION, FEATURE_REGISTRY, featuresForPlacement, resolveFeatureHref } from '@/lib/feature-registry'

describe('generated FeatureDefinition projection', () => {
  it('drives visible sidebar and home identities without duplicate hrefs', () => {
    expect(FEATURE_DEFINITION_REVISION).toMatch(/^sha256:[0-9a-f]{64}$/)
    for (const placement of ['sidebar', 'home', 'onboarding'] as const) {
      const entries = featuresForPlacement(placement)
      expect(new Set(entries.map((entry) => entry.href)).size).toBe(entries.length)
      expect(entries.every((entry) => entry.visible && entry.lifecycle === 'active')).toBe(true)
    }
    expect(FEATURE_REGISTRY.length).toBeGreaterThan(10)
  })

  it('resolves the former top-level graph as a deprecated workspace alias', () => {
    expect(resolveFeatureHref('/system-graph')).toEqual({ href: '/workspace/development', deprecated: true, featureId: 'system-convergence-s4-s6' })
    expect(featuresForPlacement('sidebar').some((entry) => entry.href === '/system-graph')).toBe(false)
  })
})

