import bundle from '@/generated/feature-registry.v1.json'

export type FeaturePlacement = 'sidebar' | 'home' | 'onboarding' | 'direct'

export interface FeatureRegistryEntry {
  feature_id: string
  title: string
  domain: string
  href: string
  visible: boolean
  placements: FeaturePlacement[]
  lifecycle: 'active' | 'deprecated' | 'archived'
  aliases: Array<{ href: string; target: string }>
  capabilities: Array<{ capability_id: string; kind: 'read' | 'write' | 'generate' | 'admin' }>
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
  for (const entry of FEATURE_REGISTRY) {
    if (entry.href === href) return { href, deprecated: false, featureId: entry.feature_id }
    const alias = entry.aliases.find((candidate) => candidate.href === href)
    if (alias) return { href: alias.target, deprecated: true, featureId: entry.feature_id }
  }
  return { href, deprecated: false }
}
