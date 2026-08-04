import {
  FEATURE_REGISTRY,
  featureById,
  resolveFeatureSurface,
  type FeatureRegistryEntry,
  type FeatureSurfaceKind,
  type WorkbenchMode,
  type WorkbenchPhase,
} from '@/lib/feature-registry'

export type { WorkbenchMode } from '@/lib/feature-registry'

export type WorkbenchGroupId =
  | 'today'
  | 'products'
  | 'operations'
  | 'content'
  | 'knowledge'
  | 'agents'
  | 'skills-tools'
  | 'workflows'
  | 'prompt-eval'
  | 'runs-system'

export interface WorkbenchNavigationEntry {
  featureId: string
  title: string
  href: string
  relationship: 'primary' | 'contextual'
  order: number
  phase: WorkbenchPhase
  flag: string | null
}

export interface WorkbenchNavigationGroup {
  id: WorkbenchGroupId
  mode: WorkbenchMode
  label: string
  href: string
  entries: readonly WorkbenchNavigationEntry[]
}

export interface WorkbenchBreadcrumb {
  label: string
  href: string
}

export interface WorkbenchLocation {
  kind: FeatureSurfaceKind
  requestedHref: string
  canonicalHref: string
  matchedSurface?: string
  featureId?: string
  primary?: { mode: WorkbenchMode; group: WorkbenchGroupId }
  contextualGroups: ReadonlyArray<{ mode: WorkbenchMode; group: WorkbenchGroupId }>
  breadcrumb: readonly WorkbenchBreadcrumb[]
  effectiveMode: WorkbenchMode
}

type SearchParamsLike = string | URLSearchParams | { get(name: string): string | null }

const GROUPS: Readonly<Record<WorkbenchMode, ReadonlyArray<{ id: WorkbenchGroupId; label: string }>>> = {
  work: [
    { id: 'today', label: '今日' },
    { id: 'products', label: '商品' },
    { id: 'operations', label: '经营' },
    { id: 'content', label: '内容' },
    { id: 'knowledge', label: '知识' },
  ],
  development: [
    { id: 'agents', label: 'Agents' },
    { id: 'skills-tools', label: 'Skills & Tools' },
    { id: 'workflows', label: 'Workflows' },
    { id: 'prompt-eval', label: 'Prompt & Eval' },
    { id: 'runs-system', label: 'Runs & System' },
  ],
}

const GROUP_IDS = new Set<WorkbenchGroupId>(
  Object.values(GROUPS).flatMap((groups) => groups.map((group) => group.id)),
)

function isGroupId(value: string): value is WorkbenchGroupId {
  return GROUP_IDS.has(value as WorkbenchGroupId)
}

function navigationEntry(
  feature: FeatureRegistryEntry,
  relationship: WorkbenchNavigationEntry['relationship'],
  order: number,
): WorkbenchNavigationEntry {
  return {
    featureId: feature.feature_id,
    title: feature.title,
    href: feature.href,
    relationship,
    order,
    phase: feature.ia.phase,
    flag: feature.ia.flag,
  }
}

export function workbenchNavigationForMode(mode: WorkbenchMode): readonly WorkbenchNavigationGroup[] {
  return GROUPS[mode].map((group) => {
    const entries = FEATURE_REGISTRY
      .filter((feature) => feature.lifecycle === 'active' && feature.visible)
      .flatMap((feature) => {
        const result: WorkbenchNavigationEntry[] = []
        if (feature.ia.mode === mode && feature.ia.primary_group === group.id) {
          result.push(navigationEntry(feature, 'primary', feature.ia.primary_order))
        }
        for (const contextual of feature.ia.contextual_groups) {
          if (contextual.mode === mode && contextual.group === group.id) {
            result.push(navigationEntry(feature, 'contextual', contextual.order))
          }
        }
        return result
      })
      .sort((a, b) => a.order - b.order || a.featureId.localeCompare(b.featureId))
    if (entries.length === 0) {
      throw new Error(`workbench group has no registry entry: ${mode}/${group.id}`)
    }
    return {
      id: group.id,
      mode,
      label: group.label,
      href: entries[0].href,
      entries: Object.freeze(entries),
    }
  })
}

function searchParam(input: SearchParamsLike | undefined, name: string): string | null {
  if (!input) return null
  if (typeof input === 'string') return new URLSearchParams(input.startsWith('?') ? input.slice(1) : input).get(name)
  return input.get(name)
}

function workspaceMode(pathname: string, input?: SearchParamsLike): WorkbenchMode | undefined {
  if (pathname !== '/workspace') return undefined
  const mode = searchParam(input, 'mode')
  if (mode === 'development' || mode === 'execution') return 'development'
  if (mode === 'business' || mode === 'work') return 'work'
  return undefined
}

function supportsMode(feature: FeatureRegistryEntry, mode: WorkbenchMode): boolean {
  return feature.ia.mode === mode || feature.ia.contextual_groups.some((group) => group.mode === mode)
}

function breadcrumbFor(feature: FeatureRegistryEntry, mode: WorkbenchMode): WorkbenchBreadcrumb[] {
  const navigation = workbenchNavigationForMode(mode)
  const primaryGroup = feature.ia.mode === mode
    ? feature.ia.primary_group
    : feature.ia.contextual_groups.find((group) => group.mode === mode)?.group
  const group = navigation.find((candidate) => candidate.id === primaryGroup)
  if (!group) return [{ label: feature.title, href: feature.href }]
  return [
    { label: mode === 'work' ? '工作' : '开发', href: navigation[0].href },
    { label: group.label, href: group.href },
    { label: feature.title, href: feature.href },
  ]
}

export function resolveWorkbenchLocation(
  pathname: string,
  searchParams?: SearchParamsLike,
  activeMode?: WorkbenchMode,
): WorkbenchLocation {
  const resolution = resolveFeatureSurface(pathname)
  const feature = resolution.featureId ? featureById(resolution.featureId) : undefined
  if (!feature) {
    return {
      ...resolution,
      contextualGroups: [],
      breadcrumb: [],
      effectiveMode: 'work',
    }
  }

  const queryMode = workspaceMode(resolution.canonicalHref, searchParams)
  const effectiveMode = queryMode || (activeMode && supportsMode(feature, activeMode) ? activeMode : feature.ia.mode)
  const primaryGroup = isGroupId(feature.ia.primary_group)
    ? { mode: feature.ia.mode, group: feature.ia.primary_group }
    : undefined
  const contextualGroups = feature.ia.contextual_groups
    .filter((group): group is typeof group & { group: WorkbenchGroupId } => isGroupId(group.group))
    .map((group) => ({ mode: group.mode, group: group.group }))

  return {
    ...resolution,
    primary: primaryGroup,
    contextualGroups,
    breadcrumb: breadcrumbFor(feature, effectiveMode),
    effectiveMode,
  }
}
