import bundle from '@/generated/feature-registry.v1.json'

export type FeaturePlacement = 'sidebar' | 'home' | 'onboarding' | 'direct'
export type WorkbenchMode = 'work' | 'development'
export type WorkbenchPhase = 'retain' | 'merge' | 'degrade' | 'host_only' | 'retirement_candidate'

export interface FeatureOwner {
  kind: 'team' | 'service' | 'person'
  id: string
}

export interface FeatureContextualGroup {
  mode: WorkbenchMode
  group: string
  order: number
}

export interface FeatureIaProjection {
  mode: WorkbenchMode
  primary_group: string
  primary_order: number
  contextual_groups: FeatureContextualGroup[]
  phase: WorkbenchPhase
  flag: string | null
}

export interface FeatureRegistryEntry {
  feature_id: string
  title: string
  domain: string
  href: string
  visible: boolean
  placements: FeaturePlacement[]
  owner: FeatureOwner
  lifecycle: 'active' | 'deprecated' | 'archived'
  aliases: Array<{ href: string; target: string }>
  owned_surfaces: string[]
  ia: FeatureIaProjection
  capabilities: Array<{ capability_id: string; kind: 'read' | 'write' | 'generate' | 'admin' }>
}

export type FeatureSurfaceKind = 'canonical' | 'owned' | 'alias' | 'unregistered' | 'ambiguous'

export interface FeatureSurfaceResolution {
  kind: FeatureSurfaceKind
  requestedHref: string
  canonicalHref: string
  matchedSurface?: string
  featureId?: string
}

const entries = (bundle.frontend_registry as FeatureRegistryEntry[])
  .slice()
  .sort((a, b) => a.feature_id.localeCompare(b.feature_id))

export const FEATURE_DEFINITION_REVISION = bundle.definition_revision
export const FEATURE_REGISTRY: readonly FeatureRegistryEntry[] = Object.freeze(entries)

export function featureById(featureId: string): FeatureRegistryEntry | undefined {
  return FEATURE_REGISTRY.find((entry) => entry.feature_id === featureId)
}

export function featuresForPlacement(placement: FeaturePlacement): FeatureRegistryEntry[] {
  return FEATURE_REGISTRY.filter((entry) => entry.visible && entry.lifecycle === 'active' && entry.placements.includes(placement))
}

export function resolveFeatureHref(href: string): { href: string; deprecated: boolean; featureId?: string } {
  const requestedHref = normalizeFeaturePath(href)
  for (const entry of FEATURE_REGISTRY) {
    if (entry.href === requestedHref) return { href: requestedHref, deprecated: false, featureId: entry.feature_id }
    const alias = entry.aliases.find((candidate) => candidate.href === requestedHref)
    if (alias) return { href: alias.target, deprecated: true, featureId: entry.feature_id }
  }
  return { href: requestedHref, deprecated: false }
}

export function normalizeFeaturePath(value: string): string {
  const withoutQuery = value.split(/[?#]/, 1)[0] || '/'
  const withLeadingSlash = withoutQuery.startsWith('/') ? withoutQuery : `/${withoutQuery}`
  return withLeadingSlash.length > 1 ? withLeadingSlash.replace(/\/+$/, '') : '/'
}

function templateSegments(value: string): string[] {
  return normalizeFeaturePath(value).split('/').filter(Boolean)
}

function matchesSurfaceTemplate(template: string, pathname: string): boolean {
  const expected = templateSegments(template)
  const actual = templateSegments(pathname)
  let expectedIndex = 0
  let actualIndex = 0

  while (expectedIndex < expected.length) {
    const segment = expected[expectedIndex]
    if (/^\[\[\.\.\..+\]\]$/.test(segment)) return true
    if (/^\[\.\.\..+\]$/.test(segment)) return actualIndex < actual.length
    if (actualIndex >= actual.length) return false
    if (!/^\[[^\]]+\]$/.test(segment) && segment !== actual[actualIndex]) return false
    expectedIndex += 1
    actualIndex += 1
  }
  return actualIndex === actual.length
}

function templateSpecificity(template: string): number {
  return templateSegments(template).reduce((score, segment) => {
    if (/^\[\[\.\.\..+\]\]$/.test(segment)) return score + 1
    if (/^\[\.\.\..+\]$/.test(segment)) return score + 2
    if (/^\[[^\]]+\]$/.test(segment)) return score + 5
    return score + 100
  }, 0)
}

/**
 * Resolve the single FeatureDefinition that owns a page surface. Aliases are
 * exact-only and fail closed if a malformed projection overlaps a renderer.
 */
export function resolveFeatureSurface(pathname: string): FeatureSurfaceResolution {
  const requestedHref = normalizeFeaturePath(pathname)
  const aliases = FEATURE_REGISTRY.flatMap((entry) =>
    entry.aliases
      .filter((alias) => normalizeFeaturePath(alias.href) === requestedHref)
      .map((alias) => ({ entry, alias })),
  )
  const owned = FEATURE_REGISTRY.flatMap((entry) =>
    entry.owned_surfaces
      .filter((surface) => matchesSurfaceTemplate(surface, requestedHref))
      .map((surface) => ({ entry, surface, specificity: templateSpecificity(surface) })),
  ).sort((a, b) => b.specificity - a.specificity || a.entry.feature_id.localeCompare(b.entry.feature_id))

  if (
    aliases.length > 1 ||
    (aliases.length === 1 && owned.some((candidate) => candidate.entry.feature_id !== aliases[0].entry.feature_id))
  ) {
    return { kind: 'ambiguous', requestedHref, canonicalHref: requestedHref }
  }
  if (aliases.length === 1) {
    const { entry, alias } = aliases[0]
    const targetOwner = FEATURE_REGISTRY.find((candidate) => candidate.href === alias.target)
    if (!targetOwner || targetOwner.feature_id !== entry.feature_id) {
      return { kind: 'ambiguous', requestedHref, canonicalHref: requestedHref }
    }
    return {
      kind: 'alias',
      requestedHref,
      canonicalHref: alias.target,
      matchedSurface: alias.href,
      featureId: entry.feature_id,
    }
  }
  if (owned.length === 0) {
    return { kind: 'unregistered', requestedHref, canonicalHref: requestedHref }
  }

  const bestSpecificity = owned[0].specificity
  const best = owned.filter((candidate) => candidate.specificity === bestSpecificity)
  if (best.length !== 1) {
    return { kind: 'ambiguous', requestedHref, canonicalHref: requestedHref }
  }
  const match = best[0]
  return {
    kind: requestedHref === match.entry.href ? 'canonical' : 'owned',
    requestedHref,
    canonicalHref: match.entry.href,
    matchedSurface: match.surface,
    featureId: match.entry.feature_id,
  }
}
