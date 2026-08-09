import type { WorkbenchMode } from '@/lib/feature-registry'

export const LEGACY_WORKBENCH_IA_VERSION = 'workbench-ia-v1' as const

export type LegacyWorkbenchGroupId =
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

interface LegacyWorkbenchPlacement {
  featureId: string
  href: string
  mode: WorkbenchMode
  group: LegacyWorkbenchGroupId
  order: number
}

export interface LegacyWorkbenchNavigationInput {
  featureId: string
  requestedHref: string
  canonicalHref?: string
  mode: WorkbenchMode
  primaryGroup: LegacyWorkbenchGroupId
  secondaryDepth?: number
}

export interface LegacyWorkbenchNavigationContract {
  version: typeof LEGACY_WORKBENCH_IA_VERSION
  exclusive: true
  expectedDepth: number
}

// Frozen v1 navigation projection. This intentionally does not read the current
// FeatureDefinition registry: rolling clients must be validated against the IA
// contract they emitted, even after canonical ownership or group names change.
const LEGACY_PLACEMENTS = Object.freeze([
  { featureId: 'ad-review', href: '/ad-review', mode: 'work', group: 'operations', order: 10 },
  { featureId: 'agent-log', href: '/agent-log', mode: 'development', group: 'agents', order: 10 },
  { featureId: 'approval-inbox', href: '/inbox', mode: 'work', group: 'today', order: 10 },
  { featureId: 'approval-inbox', href: '/inbox', mode: 'work', group: 'operations', order: 30 },
  { featureId: 'chat', href: '/chat', mode: 'development', group: 'agents', order: 0 },
  { featureId: 'chat', href: '/chat', mode: 'development', group: 'prompt-eval', order: 10 },
  { featureId: 'commerce-feedback', href: '/ad-metrics', mode: 'work', group: 'operations', order: 20 },
  { featureId: 'content-studio', href: '/content-studio', mode: 'work', group: 'content', order: 0 },
  { featureId: 'cost-management', href: '/cost', mode: 'work', group: 'products', order: 10 },
  { featureId: 'knowledge-evaluation', href: '/knowledge/evaluate', mode: 'development', group: 'prompt-eval', order: 20 },
  { featureId: 'knowledge-harvester', href: '/knowledge/harvester', mode: 'work', group: 'knowledge', order: 10 },
  { featureId: 'knowledge', href: '/knowledge', mode: 'work', group: 'knowledge', order: 0 },
  { featureId: 'livestream-analysis', href: '/livestream-analysis', mode: 'work', group: 'content', order: 30 },
  { featureId: 'model-management', href: '/models', mode: 'development', group: 'prompt-eval', order: 30 },
  { featureId: 'news', href: '/news', mode: 'work', group: 'knowledge', order: 20 },
  { featureId: 'playground', href: '/playground', mode: 'development', group: 'skills-tools', order: 0 },
  { featureId: 'product-management', href: '/products', mode: 'work', group: 'products', order: 0 },
  { featureId: 'prompt-lab', href: '/prompt-lab', mode: 'development', group: 'prompt-eval', order: 0 },
  { featureId: 'reverse-engineer', href: '/reverse-engineer', mode: 'work', group: 'content', order: 10 },
  { featureId: 'scout-monitoring', href: '/scout', mode: 'work', group: 'operations', order: 0 },
  { featureId: 'sku-pipeline', href: '/sku-pipeline', mode: 'work', group: 'products', order: 20 },
  { featureId: 'sku-pipeline', href: '/sku-pipeline', mode: 'development', group: 'workflows', order: 0 },
  { featureId: 'system-console', href: '/', mode: 'development', group: 'runs-system', order: 10 },
  { featureId: 'system-convergence-runtime-execution', href: '/workspace/execution', mode: 'development', group: 'runs-system', order: 0 },
  { featureId: 'system-convergence-s4-s6', href: '/system-graph', mode: 'development', group: 'workflows', order: 10 },
  { featureId: 'system-convergence-s4-s6', href: '/system-graph', mode: 'development', group: 'skills-tools', order: 10 },
  { featureId: 'video-analysis', href: '/video-analysis', mode: 'work', group: 'content', order: 20 },
  { featureId: 'workspace-operations', href: '/workspace', mode: 'work', group: 'today', order: 0 },
] satisfies readonly LegacyWorkbenchPlacement[])

const LEGACY_GROUPS = new Set<LegacyWorkbenchGroupId>(
  LEGACY_PLACEMENTS.map((placement) => placement.group),
)

export function isLegacyWorkbenchGroupId(value: string): value is LegacyWorkbenchGroupId {
  return LEGACY_GROUPS.has(value as LegacyWorkbenchGroupId)
}

export function resolveLegacyWorkbenchNavigation(
  input: LegacyWorkbenchNavigationInput,
): LegacyWorkbenchNavigationContract | null {
  const placement = LEGACY_PLACEMENTS.find((candidate) =>
    candidate.featureId === input.featureId &&
    candidate.href === input.requestedHref &&
    candidate.mode === input.mode &&
    candidate.group === input.primaryGroup,
  )
  if (!placement || input.canonicalHref !== placement.href) return null

  const landing = LEGACY_PLACEMENTS
    .filter((candidate) => candidate.mode === placement.mode && candidate.group === placement.group)
    .sort((left, right) => left.order - right.order || left.featureId.localeCompare(right.featureId))[0]
  const expectedDepth = landing?.featureId === placement.featureId ? 0 : 1
  if (!landing || input.secondaryDepth !== expectedDepth) return null

  return {
    version: LEGACY_WORKBENCH_IA_VERSION,
    exclusive: true,
    expectedDepth,
  }
}
