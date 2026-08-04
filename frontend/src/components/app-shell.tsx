'use client'

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import { Code2, Search, Sparkles } from 'lucide-react'

import { AppSidebar, type WorkbenchNavigationEvent } from './app-sidebar'
import { BeginnerGuide } from './beginner-guide'
import { WorkbenchStateBadge, type WorkbenchViewState } from './workbench-state-badge'
import { isWorkbenchFlagEnabled } from '@/lib/workbench-flags'
import {
  resolveWorkbenchLocation,
  workbenchNavigationForMode,
  type WorkbenchGroupId,
  type WorkbenchMode,
} from '@/lib/workbench-ia'
import { cn } from '@/lib/utils'
import {
  EMPTY_WORKBENCH_CONTINUITY,
  parseWorkbenchOverviewObservation,
  WORKBENCH_OVERVIEW_REFRESH_MS,
  useWorkbenchStore,
} from '@/stores/workbenchStore'

const FULL_SCREEN_ROUTES = ['/chat', '/playground']
const WORKBENCH_SLOT_NAMES = ['assistant', 'blueprint', 'run-center', 'approval', 'artifact-drawer'] as const

function supportsMode(
  location: ReturnType<typeof resolveWorkbenchLocation>,
  mode: WorkbenchMode,
) {
  if (location.primary?.mode === mode) return true
  return location.contextualGroups.some((group) => group.mode === mode)
}

function systemHealthState(
  health: ReturnType<typeof useWorkbenchStore.getState>['systemHealth'],
  freshness: ReturnType<typeof useWorkbenchStore.getState>['systemFreshness'],
): WorkbenchViewState {
  if (health === 'healthy' && freshness === 'fresh') return 'success'
  if (health === 'degraded' || freshness === 'stale') return 'error'
  if (health === 'unavailable' && freshness === 'fresh') return 'error'
  return 'unknown'
}

function groupForMode(
  location: ReturnType<typeof resolveWorkbenchLocation>,
  mode: WorkbenchMode,
): WorkbenchGroupId | undefined {
  if (location.primary?.mode === mode) return location.primary.group
  return location.contextualGroups.find((group) => group.mode === mode)?.group
}

export interface AppShellProps {
  children: React.ReactNode
  unifiedShellEnabled?: boolean
}

function AppShellPending({ unifiedShellEnabled }: Pick<AppShellProps, 'unifiedShellEnabled'>) {
  const unified = unifiedShellEnabled ?? isWorkbenchFlagEnabled('unified_shell')

  if (!unified) {
    return (
      <div className="flex min-h-screen" data-testid="legacy-app-shell" aria-busy="true">
        <p className="sr-only" role="status">
          正在加载工作台
        </p>
      </div>
    )
  }

  return (
    <div
      className="flex h-[100dvh] min-h-0 overflow-hidden bg-slate-50"
      data-workbench-shell
      data-testid="unified-app-shell"
      aria-busy="true"
    >
      <p className="sr-only" role="status">
        正在加载工作台导航
      </p>
    </div>
  )
}

export function AppShell(props: AppShellProps) {
  return (
    <Suspense fallback={<AppShellPending unifiedShellEnabled={props.unifiedShellEnabled} />}>
      <AppShellContent {...props} />
    </Suspense>
  )
}

function AppShellContent({ children, unifiedShellEnabled }: AppShellProps) {
  const pathname = usePathname() || '/'
  const searchParams = useSearchParams()
  const queryString = searchParams.toString()
  const unified = unifiedShellEnabled ?? isWorkbenchFlagEnabled('unified_shell')
  const isFullScreen = FULL_SCREEN_ROUTES.some((route) => pathname.startsWith(route))
  const supportsWideRenderer = pathname === '/playground' || pathname.startsWith('/playground/')
  const [searchQuery, setSearchQuery] = useState('')
  const [sidebarExpanded, setSidebarExpanded] = useState(() => pathname.startsWith('/content-studio'))

  const mode = useWorkbenchStore((state) => state.mode)
  const preferenceHydrated = useWorkbenchStore((state) => state.preferenceHydrated)
  const preferenceError = useWorkbenchStore((state) => state.preferenceError)
  const contextRevision = useWorkbenchStore((state) => state.contextRevision)
  const contextLabel = useWorkbenchStore((state) => state.contextLabel)
  const contextStatus = useWorkbenchStore((state) => state.contextStatus)
  const resolvedProvider = useWorkbenchStore((state) => state.resolvedProvider)
  const providerStatus = useWorkbenchStore((state) => state.providerStatus)
  const systemHealth = useWorkbenchStore((state) => state.systemHealth)
  const systemFreshness = useWorkbenchStore((state) => state.systemFreshness)
  const hydrateMode = useWorkbenchStore((state) => state.hydrateMode)
  const setMode = useWorkbenchStore((state) => state.setMode)
  const bindContinuity = useWorkbenchStore((state) => state.bindContinuity)
  const openedLocationRef = useRef<string | null>(null)

  const location = useMemo(
    () => resolveWorkbenchLocation(pathname, queryString, mode),
    [mode, pathname, queryString],
  )
  const workspaceModeOverride = useMemo<WorkbenchMode | null>(() => {
    if (pathname !== '/workspace') return null
    const requestedMode = new URLSearchParams(queryString).get('mode')
    if (requestedMode === 'development' || requestedMode === 'execution') return 'development'
    if (requestedMode === 'business' || requestedMode === 'work') return 'work'
    return null
  }, [pathname, queryString])

  useEffect(() => {
    if (!unified || preferenceHydrated) return
    // An explicit workspace URL is navigation intent, not a storage fallback.
    // Apply it during the first hydration pass so a stale stored preference can
    // never render after the query-selected mode.
    if (workspaceModeOverride) {
      setMode(workspaceModeOverride)
      return
    }
    hydrateMode(location.effectiveMode || 'work')
  }, [hydrateMode, location.effectiveMode, preferenceHydrated, setMode, unified, workspaceModeOverride])

  useEffect(() => {
    if (!unified || !preferenceHydrated) return
    // Direct links to a mode-exclusive surface should select that mode. A
    // capability with a contextual placement in the current mode stays put.
    // Reading the current value here deliberately avoids re-running this route
    // synchronization when the user presses the mode switch on the same page.
    const currentMode = useWorkbenchStore.getState().mode
    if (workspaceModeOverride) {
      if (currentMode !== workspaceModeOverride) setMode(workspaceModeOverride)
      return
    }
    if (location.kind !== 'unregistered' && !supportsMode(location, currentMode)) {
      setMode(location.effectiveMode || 'work')
    }
  }, [location, preferenceHydrated, setMode, unified, workspaceModeOverride])

  useEffect(() => {
    if (!unified) return
    let active = true
    let activeRequest: AbortController | null = null

    const observeHealth = async () => {
      activeRequest?.abort()
      const request = new AbortController()
      activeRequest = request
      try {
        const response = await fetch('/api/omni/overview', {
          cache: 'no-store',
          credentials: 'same-origin',
          signal: request.signal,
        })
        if (!response.ok) throw new Error('overview unavailable')
        const observation = parseWorkbenchOverviewObservation(await response.json())
        if (!observation) throw new Error('overview schema invalid')
        if (active) bindContinuity(observation)
      } catch {
        if (active && !request.signal.aborted) {
          bindContinuity({
            systemHealth: EMPTY_WORKBENCH_CONTINUITY.systemHealth,
            systemFreshness: EMPTY_WORKBENCH_CONTINUITY.systemFreshness,
          })
        }
      }
    }

    void observeHealth()
    const refreshTimer = window.setInterval(() => void observeHealth(), WORKBENCH_OVERVIEW_REFRESH_MS)
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') void observeHealth()
    }
    document.addEventListener('visibilitychange', refreshWhenVisible)

    return () => {
      active = false
      window.clearInterval(refreshTimer)
      document.removeEventListener('visibilitychange', refreshWhenVisible)
      activeRequest?.abort()
    }
  }, [bindContinuity, unified])

  const reportNavigation = useCallback((event: WorkbenchNavigationEvent) => {
    void fetch('/api/omni/workbench/navigation-events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      keepalive: true,
      body: JSON.stringify({
        event_type: 'primary_navigation',
        requested_href: event.requestedHref,
        mode: event.mode,
        primary_group: event.primaryGroup,
        feature_id: event.featureId,
        canonical_href: event.canonicalHref,
        secondary_depth: event.secondaryDepth,
        result: event.result,
      }),
    }).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!unified || !preferenceHydrated || !location.featureId) return
    if (['alias', 'ambiguous', 'unregistered'].includes(location.kind)) return

    const locationKey = `${pathname}?${queryString}`
    if (openedLocationRef.current === locationKey) return
    const openedMode = location.effectiveMode
    const primaryGroup = groupForMode(location, openedMode)
    if (!primaryGroup) return
    const group = workbenchNavigationForMode(openedMode).find((candidate) => candidate.id === primaryGroup)
    const landing = group?.entries[0]
    if (!landing) return

    openedLocationRef.current = locationKey
    reportNavigation({
      mode: openedMode,
      primaryGroup,
      featureId: location.featureId,
      requestedHref: location.requestedHref,
      canonicalHref: location.canonicalHref,
      secondaryDepth: landing.featureId === location.featureId ? 0 : 1,
      result: 'opened',
    })
  }, [location, pathname, preferenceHydrated, queryString, reportNavigation, unified])

  if (!unified) {
    return (
      <div className="flex min-h-screen" data-testid="legacy-app-shell">
        <AppSidebar unified={false} />
        {isFullScreen ? (
          <div className="ml-[68px] min-h-screen flex-1">{children}</div>
        ) : (
          <main className="ml-[68px] min-h-screen flex-1">{children}</main>
        )}
        <BeginnerGuide />
      </div>
    )
  }

  const contextState: WorkbenchViewState = contextRevision && contextStatus === 'available' ? 'success' : 'unknown'
  const providerState: WorkbenchViewState = resolvedProvider && providerStatus === 'available' ? 'success' : 'unknown'

  return (
    <div
      className="flex h-[100dvh] min-h-0 overflow-hidden bg-slate-50"
      data-workbench-shell
      data-workbench-mode={mode}
      data-workbench-density={mode === 'development' ? 'compact' : 'comfortable'}
      data-testid="unified-app-shell"
    >
      <a
        href="#workbench-main"
        className={cn(
          'workbench-focusable fixed -top-20 z-[100] rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white focus:top-2',
          sidebarExpanded ? 'left-20 lg:left-[268px]' : 'left-20',
        )}
      >
        跳到主内容
      </a>

      <AppSidebar
        mode={mode}
        unified
        searchQuery={searchQuery}
        expanded={sidebarExpanded}
        onExpandedChange={setSidebarExpanded}
        onNavigate={reportNavigation}
      />

      <div
        className={cn(
          'ml-[68px] flex h-[100dvh] min-h-0 min-w-0 flex-1 flex-col overflow-hidden transition-[margin-left] duration-200',
          sidebarExpanded && 'lg:ml-64',
        )}
      >
        <header className="relative z-50 shrink-0 border-b border-slate-200 bg-white/95 shadow-sm backdrop-blur" aria-label="Omni 工作台顶栏">
          <div className="flex min-h-16 flex-wrap items-center gap-3 px-4 py-2 lg:flex-nowrap lg:px-6">
            <div className="flex shrink-0 rounded-xl border border-slate-200 bg-slate-50 p-1" role="group" aria-label="工作台模式">
              <button
                type="button"
                className={cn('workbench-focusable flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold transition-colors', mode === 'work' ? 'bg-white text-violet-800 shadow-sm' : 'text-slate-600 hover:text-slate-950')}
                aria-pressed={mode === 'work'}
                onClick={() => setMode('work')}
              >
                <Sparkles className="h-4 w-4" aria-hidden="true" />
                工作
              </button>
              <button
                type="button"
                className={cn('workbench-focusable flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold transition-colors', mode === 'development' ? 'bg-white text-violet-800 shadow-sm' : 'text-slate-600 hover:text-slate-950')}
                aria-pressed={mode === 'development'}
                onClick={() => setMode('development')}
              >
                <Code2 className="h-4 w-4" aria-hidden="true" />
                开发
              </button>
            </div>

            <label className="relative min-w-52 flex-1 lg:max-w-md">
              <span className="sr-only">全局搜索功能或命令</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
              <input
                type="search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="搜索功能或命令"
                className="workbench-focusable h-10 w-full rounded-xl border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm text-slate-900 placeholder:text-slate-400"
              />
            </label>

            <div className="flex min-w-0 flex-wrap items-center gap-2" aria-label="当前上下文与可用性">
              <WorkbenchStateBadge
                state={contextState}
                label="上下文"
                detail={contextLabel || contextRevision || (contextStatus === 'unknown' ? '状态未知' : '未选择')}
                testId="workbench-context-status"
              />
              <WorkbenchStateBadge
                state={providerState}
                label="Provider"
                detail={resolvedProvider || (providerStatus === 'unavailable' ? '不可用' : '未解析')}
                testId="workbench-provider-status"
              />
              <WorkbenchStateBadge
                state={systemHealthState(systemHealth, systemFreshness)}
                label="健康 / 新鲜度"
                detail={`${systemHealth} / ${systemFreshness}`}
                testId="workbench-health-status"
              />
            </div>
          </div>

          <div className="flex min-h-8 items-center justify-between gap-3 border-t border-slate-100 px-4 py-1 text-xs text-slate-500 lg:px-6">
            <nav aria-label="当前位置" className="min-w-0">
              <ol className="flex min-w-0 items-center gap-1">
                {location.breadcrumb.map((item, index) => (
                  <li key={`${item.href}:${index}`} className="flex min-w-0 items-center gap-1">
                    {index > 0 ? <span aria-hidden="true">/</span> : null}
                    <Link href={item.href} className="workbench-focusable truncate rounded px-1 hover:text-violet-700" aria-current={index === location.breadcrumb.length - 1 ? 'page' : undefined}>
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ol>
            </nav>
            <div className="flex shrink-0 items-center gap-2">
              {mode === 'development' ? (
                <details className="relative" data-testid="workbench-state-legend">
                  <summary className="workbench-focusable cursor-pointer rounded px-1 font-medium text-violet-700">状态语义</summary>
                  <div className="absolute right-0 top-7 z-[70] grid w-max grid-cols-2 gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-xl" aria-label="工作台状态语义图例">
                    <WorkbenchStateBadge state="loading" />
                    <WorkbenchStateBadge state="empty" />
                    <WorkbenchStateBadge state="error" />
                    <WorkbenchStateBadge state="success" />
                    <WorkbenchStateBadge state="pending-approval" />
                    <WorkbenchStateBadge state="unknown" />
                    <WorkbenchStateBadge state="planned" />
                  </div>
                </details>
              ) : null}
              <span>{mode === 'work' ? '工作模式 · 任务摘要' : '开发模式 · 调试密度'}</span>
            </div>
          </div>

          <p
            className={cn(
              preferenceError
                ? 'mx-3 mb-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900'
                : 'sr-only',
            )}
            role="status"
            aria-live="polite"
            data-testid="workbench-preference-status"
          >
            {preferenceError || ''}
          </p>
        </header>

        {supportsWideRenderer ? (
          <p
            className="border-t border-slate-100 bg-violet-50 px-4 py-1 text-xs text-violet-800 sm:hidden"
            role="status"
            data-testid="workbench-horizontal-scroll-hint"
          >
            宽内容可在内容区左右滑动查看
          </p>
        ) : null}
        <div
          id="workbench-main"
          tabIndex={-1}
          className={cn(
            'min-h-0 min-w-0 flex-1',
            isFullScreen
              ? cn('workbench-fullscreen-surface', supportsWideRenderer ? 'overflow-auto' : 'overflow-hidden')
              : 'overflow-auto',
          )}
          data-workbench-fullscreen={isFullScreen ? 'true' : undefined}
        >
          {isFullScreen ? children : <main>{children}</main>}
        </div>
      </div>

      {WORKBENCH_SLOT_NAMES.map((slot) => (
        <div key={slot} id={`workbench-slot-${slot}`} className="contents" data-workbench-slot={slot} />
      ))}

      <BeginnerGuide />
    </div>
  )
}
