'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import {
  Activity,
  Bot,
  BrainCircuit,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleGauge,
  FlaskConical,
  Inbox,
  LineChart,
  Network,
  Package,
  Palette,
  SearchX,
  Wrench,
  Workflow,
  BookOpen,
  Calculator,
  ClipboardCheck,
  ScanSearch,
  Send,
  Sparkles,
  Wand2,
  type LucideIcon,
} from 'lucide-react'

import { featuresForPlacement, type FeatureRegistryEntry } from '@/lib/feature-registry'
import {
  resolveWorkbenchLocation,
  workbenchNavigationForMode,
  type WorkbenchGroupId,
  type WorkbenchMode,
  type WorkbenchNavigationEntry,
  type WorkbenchNavigationGroup,
} from '@/lib/workbench-ia'
import { cn } from '@/lib/utils'

const GROUP_ICONS: Record<WorkbenchGroupId, LucideIcon> = {
  today: CalendarDays,
  products: Package,
  operations: LineChart,
  content: Palette,
  knowledge: BookOpen,
  agents: Bot,
  'skills-tools': Wrench,
  workflows: Workflow,
  'prompt-eval': FlaskConical,
  'runs-system': Activity,
}

const LEGACY_PRESENTATION: Record<string, { icon: LucideIcon; hint: string; section: string; order: number }> = {
  'workspace-operations': { icon: Inbox, hint: '经营、开发与执行共用的统一入口', section: '工作流', order: 10 },
  'product-management': { icon: Package, hint: 'SKU 数据、资产、动作与诊断', section: '工作流', order: 20 },
  'scout-monitoring': { icon: ScanSearch, hint: '自动采集与异动检测', section: '数据与采集', order: 30 },
  'sku-pipeline': { icon: Sparkles, hint: 'SKU → 卖点矩阵 → 人群匹配 → 圈包 SOP', section: '内容生产', order: 40 },
  'reverse-engineer': { icon: Wand2, hint: '把素材拆成可复用镜头和提示词', section: '内容生产', order: 50 },
  'cost-management': { icon: Calculator, hint: '结构化成本与利润核算', section: '投放与复盘', order: 60 },
  'commerce-feedback': { icon: Send, hint: '把投后真实指标写回血缘', section: '投放与复盘', order: 70 },
  'approval-inbox': { icon: ClipboardCheck, hint: '查看和处理显式审批 Gate', section: '投放与复盘', order: 80 },
  'system-console': { icon: CircleGauge, hint: '系统服务、指标与健康监控', section: '系统', order: 90 },
}

export interface WorkbenchNavigationEvent {
  mode: WorkbenchMode
  primaryGroup: WorkbenchGroupId
  featureId: string
  requestedHref: string
  canonicalHref: string
  secondaryDepth: number
  result: 'selected' | 'opened'
}

export interface AppSidebarProps {
  mode?: WorkbenchMode
  unified?: boolean
  searchQuery?: string
  onNavigate?: (event: WorkbenchNavigationEvent) => void
  expanded?: boolean
  onExpandedChange?: (expanded: boolean) => void
}

function normalizeQuery(value: string) {
  return value.trim().toLocaleLowerCase('zh-CN')
}

function entryMatches(entry: WorkbenchNavigationEntry, query: string) {
  if (!query) return true
  return normalizeQuery(`${entry.title} ${entry.href} ${entry.featureId}`).includes(query)
}

function filteredGroups(groups: readonly WorkbenchNavigationGroup[], searchQuery: string) {
  const query = normalizeQuery(searchQuery)
  if (!query) return groups

  return groups.flatMap((group) => {
    if (normalizeQuery(`${group.label} ${group.id}`).includes(query)) return [group]
    const entries = group.entries.filter((entry) => entryMatches(entry, query))
    return entries.length ? [{ ...group, href: entries[0].href, entries }] : []
  })
}

export function AppSidebar({
  mode = 'work',
  unified = true,
  searchQuery = '',
  onNavigate,
  expanded: controlledExpanded,
  onExpandedChange,
}: AppSidebarProps) {
  const pathname = usePathname() || '/'
  const searchParams = useSearchParams()
  const [internalExpanded, setInternalExpanded] = useState(() => pathname.startsWith('/content-studio'))
  const expanded = controlledExpanded ?? internalExpanded
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({})
  const location = useMemo(
    () => resolveWorkbenchLocation(pathname, searchParams, mode),
    [mode, pathname, searchParams],
  )
  const activeGroupId = useMemo<WorkbenchGroupId | undefined>(() => {
    if (location.primary?.mode === mode) return location.primary.group
    return location.contextualGroups.find((group) => group.mode === mode)?.group
  }, [location.contextualGroups, location.primary, mode])
  const groups = useMemo(
    () => filteredGroups(workbenchNavigationForMode(mode), searchQuery),
    [mode, searchQuery],
  )

  const toggleGroup = (group: WorkbenchNavigationGroup) => {
    setOpenGroups((current) => ({ ...current, [group.id]: !(current[group.id] ?? group.id === activeGroupId) }))
  }

  const renderUnifiedEntry = (group: WorkbenchNavigationGroup, entry: WorkbenchNavigationEntry) => {
    const active = group.id === activeGroupId && location.featureId === entry.featureId && location.canonicalHref === entry.href
    return (
      <Link
        key={`${group.id}:${entry.featureId}:${entry.relationship}`}
        href={entry.href}
        aria-current={active ? 'page' : undefined}
        className={cn(
          'workbench-focusable flex items-start gap-2 rounded-lg py-2 pl-9 pr-2 text-xs transition-colors',
          active ? 'bg-violet-100 text-violet-800' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950',
        )}
        onClick={() => onNavigate?.({ mode, primaryGroup: group.id, featureId: entry.featureId, requestedHref: entry.href, canonicalHref: entry.href, secondaryDepth: 1, result: 'selected' })}
      >
        <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" />
        <span className="min-w-0">
          <span className="block truncate font-medium">{entry.title}</span>
          {entry.relationship === 'contextual' ? <span className="block text-[10px] text-slate-600">上下文入口 · 回到同一页面</span> : null}
        </span>
      </Link>
    )
  }

  const renderUnifiedGroup = (group: WorkbenchNavigationGroup) => {
    const Icon = GROUP_ICONS[group.id]
    const landing = group.entries[0]
    const active = group.id === activeGroupId
    const open = openGroups[group.id] ?? active

    return (
      <div key={group.id} data-workbench-primary-group={group.id}>
        <div className="flex items-center gap-1">
          <Link
            href={group.href}
            aria-label={group.label}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'workbench-focusable group relative flex min-w-0 flex-1 items-center gap-3 rounded-xl px-2.5 py-2.5 transition-colors',
              active ? 'bg-violet-50 text-violet-800' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-950',
            )}
            onClick={() => {
              if (landing) {
                onNavigate?.({ mode, primaryGroup: group.id, featureId: landing.featureId, requestedHref: group.href, canonicalHref: group.href, secondaryDepth: 0, result: 'selected' })
              }
            }}
          >
            {active ? <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-violet-600" aria-hidden="true" /> : null}
            <span className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-lg', active ? 'bg-violet-600 text-white' : 'bg-slate-100 text-slate-600')}>
              <Icon className="h-4 w-4" aria-hidden="true" />
            </span>
            {expanded ? <span className="truncate text-sm font-semibold">{group.label}</span> : null}
            {!expanded ? <span className="sr-only">{group.label}</span> : null}
          </Link>
          {expanded ? (
            <button
              type="button"
              className="workbench-focusable rounded-lg p-2 text-slate-500 hover:bg-slate-100"
              aria-label={`${open ? '收起' : '展开'}${group.label}二级入口`}
              aria-expanded={open}
              aria-controls={`workbench-group-${group.id}`}
              onClick={() => toggleGroup(group)}
            >
              {open ? <ChevronDown className="h-4 w-4" aria-hidden="true" /> : <ChevronRight className="h-4 w-4" aria-hidden="true" />}
            </button>
          ) : null}
        </div>
        {expanded && open ? (
          <div id={`workbench-group-${group.id}`} className="mt-1 space-y-0.5">
            {group.entries.map((entry) => renderUnifiedEntry(group, entry))}
          </div>
        ) : null}
      </div>
    )
  }

  const legacyEntries = useMemo(
    () => featuresForPlacement('sidebar').slice().sort((a, b) => (LEGACY_PRESENTATION[a.feature_id]?.order ?? 999) - (LEGACY_PRESENTATION[b.feature_id]?.order ?? 999)),
    [],
  )

  const renderLegacyEntry = (feature: FeatureRegistryEntry, index: number) => {
    const presentation = LEGACY_PRESENTATION[feature.feature_id] || { icon: Network, hint: feature.domain, section: '其他', order: 999 }
    const previous = index > 0 ? LEGACY_PRESENTATION[legacyEntries[index - 1].feature_id]?.section || '其他' : ''
    const showSection = previous !== presentation.section
    const active = location.featureId === feature.feature_id || pathname === feature.href
    const Icon = presentation.icon

    return (
      <div key={feature.feature_id}>
        {showSection && expanded ? <p className="px-3 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">{presentation.section}</p> : null}
        {showSection && !expanded && index > 0 ? <div className="mx-3 my-1.5 h-px bg-slate-200" /> : null}
        <Link
          href={feature.href}
          aria-label={feature.title}
          aria-current={active ? 'page' : undefined}
          className={cn(
            'workbench-focusable group relative flex items-center gap-3 rounded-xl px-2.5 py-2.5 transition-colors',
            active ? 'bg-violet-50 text-violet-800' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-950',
          )}
        >
          <span className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-lg', active ? 'bg-violet-600 text-white' : 'bg-slate-100')}>
            <Icon className="h-4 w-4" aria-hidden="true" />
          </span>
          {expanded ? <span className="min-w-0"><span className="block truncate text-sm font-medium">{feature.title}</span><span className="block truncate text-[10px] text-slate-400">{presentation.hint}</span></span> : null}
        </Link>
      </div>
    )
  }

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-[60] flex h-[100dvh] flex-col border-r border-slate-200 bg-white shadow-sm transition-[width] duration-200',
        expanded ? 'w-64' : 'w-[68px]',
      )}
      aria-label={unified ? `Omni ${mode === 'work' ? '工作' : '开发'}模式导航` : 'Omni 经典导航'}
      data-testid={unified ? 'workbench-sidebar' : 'legacy-sidebar'}
    >
      <div className="flex h-16 shrink-0 items-center border-b border-slate-100 px-3">
        <Link href="/workspace" className="workbench-focusable flex min-w-0 items-center gap-3 rounded-xl" aria-label="Omni 首页">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-700 to-purple-500 shadow-lg shadow-purple-200/60">
            <BrainCircuit className="h-5 w-5 text-white" aria-hidden="true" />
          </span>
          {expanded ? <span className="min-w-0"><span className="block truncate text-sm font-bold text-slate-950">Omni</span><span className="block truncate text-[10px] text-slate-500">{unified ? '智能蓝图工作台' : '经典导航'}</span></span> : null}
        </Link>
      </div>

      <nav
        className="scrollbar-hide flex-1 space-y-1 overflow-y-auto overflow-x-hidden px-2.5 py-3"
        aria-label={unified ? `${mode === 'work' ? '工作' : '开发'}模式一级导航` : '经典主导航'}
      >
        {unified ? groups.map(renderUnifiedGroup) : legacyEntries.map(renderLegacyEntry)}
        {unified && groups.length === 0 ? (
          <div className="mx-1 rounded-xl border border-dashed border-slate-300 p-3 text-center text-xs text-slate-500" role="status">
            <SearchX className="mx-auto mb-2 h-5 w-5" aria-hidden="true" />
            {expanded ? '没有匹配的功能或命令' : <span className="sr-only">没有匹配的功能或命令</span>}
          </div>
        ) : null}
      </nav>

      <div className="shrink-0 border-t border-slate-100 px-2.5 py-3">
        <button
          type="button"
          className="workbench-focusable flex w-full items-center justify-center gap-2 rounded-xl px-2.5 py-2 text-slate-500 hover:bg-slate-50 hover:text-slate-800"
          aria-label={expanded ? '收起侧边导航' : '展开侧边导航'}
          aria-expanded={expanded}
          onClick={() => {
            const nextExpanded = !expanded
            if (controlledExpanded === undefined) setInternalExpanded(nextExpanded)
            onExpandedChange?.(nextExpanded)
          }}
        >
          {expanded ? <ChevronLeft className="h-4 w-4" aria-hidden="true" /> : <ChevronRight className="h-4 w-4" aria-hidden="true" />}
          {expanded ? <span className="text-xs font-medium">收起导航</span> : null}
        </button>
      </div>
    </aside>
  )
}
