import { describe, expect, it } from 'vitest'

import { FEATURE_REGISTRY } from '@/lib/feature-registry'
import { resolveWorkbenchLocation, workbenchNavigationForMode } from '@/lib/workbench-ia'

describe('workbench IA projection', () => {
  it('derives exactly five ordered primary groups for each mode from FeatureDefinition', () => {
    const work = workbenchNavigationForMode('work')
    const development = workbenchNavigationForMode('development')

    expect(work.map((group) => group.id)).toEqual(['today', 'products', 'operations', 'content', 'knowledge'])
    expect(development.map((group) => group.id)).toEqual(['agents', 'skills-tools', 'workflows', 'prompt-eval', 'runs-system'])
    for (const group of [...work, ...development]) {
      expect(group.entries.length).toBeGreaterThan(0)
      expect(group.href).toBe(group.entries[0].href)
      expect(group.entries.map((entry) => entry.order)).toEqual(
        [...group.entries].map((entry) => entry.order).sort((a, b) => a - b),
      )
    }
  })

  it('renders each active visible feature once as primary while keeping hidden routes classified', () => {
    const groups = [
      ...workbenchNavigationForMode('work'),
      ...workbenchNavigationForMode('development'),
    ]
    const primary = groups.flatMap((group) => group.entries.filter((entry) => entry.relationship === 'primary'))
    const visible = FEATURE_REGISTRY.filter((feature) => feature.lifecycle === 'active' && feature.visible)
    expect(primary).toHaveLength(visible.length)
    expect(new Set(primary.map((entry) => entry.featureId)).size).toBe(visible.length)
    expect(primary.map((entry) => entry.featureId)).not.toContain('task-management')
    expect(primary.map((entry) => entry.featureId)).not.toContain('tri-mind')
    expect(groups.filter((group) => group.mode === 'work')).toHaveLength(5)
    expect(groups.filter((group) => group.mode === 'development')).toHaveLength(5)

    expect(resolveWorkbenchLocation('/tasks')).toMatchObject({
      kind: 'canonical',
      featureId: 'task-management',
      primary: { mode: 'work', group: 'today' },
    })
    expect(resolveWorkbenchLocation('/tri-mind')).toMatchObject({
      kind: 'canonical',
      featureId: 'tri-mind',
      primary: { mode: 'development', group: 'skills-tools' },
    })

    const workflows = workbenchNavigationForMode('development').find((group) => group.id === 'workflows')
    expect(workflows?.entries).toContainEqual(expect.objectContaining({
      featureId: 'sku-pipeline',
      relationship: 'contextual',
      href: '/sku-pipeline',
    }))
  })

  it('resolves aliases, secondary and dynamic surfaces to one canonical location', () => {
    expect(resolveWorkbenchLocation('/qa')).toMatchObject({
      kind: 'alias',
      canonicalHref: '/chat',
      featureId: 'chat',
      effectiveMode: 'development',
      primary: { mode: 'development', group: 'agents' },
    })
    expect(resolveWorkbenchLocation('/ad-review/flywheel')).toMatchObject({
      kind: 'owned',
      canonicalHref: '/ad-review',
      featureId: 'ad-review',
    })
    expect(resolveWorkbenchLocation('/content-studio/avatars/avatar-1')).toMatchObject({
      kind: 'owned',
      canonicalHref: '/content-studio',
      featureId: 'content-studio',
    })
    expect(resolveWorkbenchLocation('/sku/sku-1')).toMatchObject({
      kind: 'owned',
      canonicalHref: '/products',
      matchedSurface: '/sku/[id]',
    })
  })

  it('maps legacy workspace development and execution query modes to one global development mode', () => {
    expect(resolveWorkbenchLocation('/workspace', 'mode=development', 'work').effectiveMode).toBe('development')
    expect(resolveWorkbenchLocation('/workspace', new URLSearchParams('mode=execution'), 'work').effectiveMode).toBe('development')
    expect(resolveWorkbenchLocation('/workspace', 'mode=business', 'development').effectiveMode).toBe('work')
    expect(resolveWorkbenchLocation('/workspace').effectiveMode).toBe('work')
  })

  it('uses an active contextual mode for location and breadcrumb when the feature supports it', () => {
    expect(resolveWorkbenchLocation('/sku-pipeline', undefined, 'development')).toMatchObject({
      effectiveMode: 'development',
      breadcrumb: [
        { label: '开发' },
        { label: 'Workflows' },
        { label: 'SKU 圈包链路', href: '/sku-pipeline' },
      ],
    })
    expect(resolveWorkbenchLocation('/sku-pipeline', undefined, 'work')).toMatchObject({
      effectiveMode: 'work',
      breadcrumb: [{ label: '工作' }, { label: '商品' }, { label: 'SKU 圈包链路' }],
    })
    expect(resolveWorkbenchLocation('/knowledge', undefined, 'development').effectiveMode).toBe('work')
  })

  it('fails closed for unknown paths without inventing a breadcrumb or owner', () => {
    expect(resolveWorkbenchLocation('/not-registered')).toEqual({
      kind: 'unregistered',
      requestedHref: '/not-registered',
      canonicalHref: '/not-registered',
      contextualGroups: [],
      breadcrumb: [],
      effectiveMode: 'work',
    })
  })
})
