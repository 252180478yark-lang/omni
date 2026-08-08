'use client'

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { CircleDot, Search } from 'lucide-react'

import { AppSidebar, type WorkbenchNavigationEvent } from './app-sidebar'
import { BeginnerGuide } from './beginner-guide'
import { WorkbenchStateBadge, type WorkbenchViewState } from './workbench-state-badge'
import { WorkbenchDock } from './workbench/WorkbenchDock'
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
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryString = searchParams.toString()
  const unified = unifiedShellEnabled ?? isWorkbenchFlagEnabled('unified_shell')
  const isFullScreen = FULL_SCREEN_ROUTES.some((route) => pathname.startsWith(route))
  const supportsWideRenderer = pathname === '/playground' || pathname.startsWith('/playground/')
  const [searchQuery, setSearchQuery] = useState('')
  const [sidebarExpanded, setSidebarExpanded] = useState(true)

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
  const synchronizedLocationRef = useRef<string | null>(null)

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
  const handleModeChange = useCallback((nextMode: WorkbenchMode) => {
    setMode(nextMode)
    if (!supportsMode(location, nextMode) || (workspaceModeOverride && workspaceModeOverride !== nextMode)) {
      router.push('/workspace')
    }
  }, [location, router, setMode, workspaceModeOverride])

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
    const locationKey = `${pathname}?${queryString}`
    if (synchronizedLocationRef.current === locationKey) return
    synchronizedLocationRef.current = locationKey

    // Direct links to a mode-exclusive surface should select that mode. A
    // capability with a contextual placement in the current mode stays put.
    // Synchronize once per committed URL so a user-initiated mode switch is not
    // reverted while router.push is still committing its destination.
    const currentMode = useWorkbenchStore.getState().mode
    if (workspaceModeOverride) {
      if (currentMode !== workspaceModeOverride) setMode(workspaceModeOverride)
      return
    }
    if (location.kind !== 'unregistered' && !supportsMode(location, currentMode)) {
      setMode(location.effectiveMode || 'work')
    }
  }, [location, pathname, preferenceHydrated, queryString, setMode, unified, workspaceModeOverride])

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
          sidebarExpanded ? 'left-20 lg:left-[284px]' : 'left-20',
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
        onModeChange={handleModeChange}
        onNavigate={reportNavigation}
      />

      <div
        className={cn(
          'ml-[72px] flex h-[100dvh] min-h-0 min-w-0 flex-1 flex-col overflow-hidden transition-[margin-left] duration-200',
          sidebarExpanded && 'lg:ml-[272px]',
        )}
      >
        <header className="relative z-50 shrink-0 border-b border-slate-200 bg-white/95 backdrop-blur" aria-label="Omni 工作台顶栏">
          <div className="flex min-h-16 items-center gap-3 px-4 lg:px-6">
            <nav aria-label="当前位置" className="hidden min-w-0 flex-1 lg:block">
              <ol className="flex min-w-0 items-center gap-1 text-xs text-slate-500">
                {location.breadcrumb.map((item, index) => (
                  <li key={`${item.href}:${index}`} className="flex min-w-0 items-center gap-1">
                    {index > 0 ? <span className="text-slate-300" aria-hidden="true">/</span> : null}
                    <Link href={item.href} className="workbench-focusable truncate rounded px-1 hover:text-slate-950" aria-current={index === location.breadcrumb.length - 1 ? 'page' : undefined}>
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ol>
            </nav>

            <label className="relative min-w-44 flex-1 lg:max-w-sm">
              <span className="sr-only">全局搜索功能或命令</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
              <input
                type="search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="搜索页面或能力"
                className="workbench-focusable h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm text-slate-900 placeholder:text-slate-400"
              />
            </label>

            <details className="relative shrink-0" data-testid="workbench-runtime-details">
              <summary className="workbench-focusable flex cursor-pointer list-none items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                <CircleDot className={cn('h-3.5 w-3.5', systemHealthState(systemHealth, systemFreshness) === 'success' ? 'text-emerald-600' : 'text-amber-600')} aria-hidden="true" />
                运行状态
              </summary>
              <div className="absolute right-0 top-11 z-[70] w-max max-w-[calc(100vw-6rem)] space-y-2 rounded-xl border border-slate-200 bg-white p-3 shadow-xl" aria-label="当前上下文与可用性">
                <WorkbenchStateBadge state={contextState} label="上下文" detail={contextLabel || contextRevision || (contextStatus === 'unknown' ? '状态未知' : '未选择')} testId="workbench-context-status" />
                <WorkbenchStateBadge state={providerState} label="Provider" detail={resolvedProvider || (providerStatus === 'unavailable' ? '不可用' : '未解析')} testId="workbench-provider-status" />
                <WorkbenchStateBadge state={systemHealthState(systemHealth, systemFreshness)} label="健康 / 新鲜度" detail={`${systemHealth} / ${systemFreshness}`} testId="workbench-health-status" />
                {mode === 'development' ? (
                  <div className="border-t border-slate-100 pt-2" data-testid="workbench-state-legend">
                    <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-600">状态语义</p>
                    <div className="grid grid-cols-2 gap-2" aria-label="工作台状态语义图例">
                      <WorkbenchStateBadge state="loading" />
                      <WorkbenchStateBadge state="empty" />
                      <WorkbenchStateBadge state="error" />
                      <WorkbenchStateBadge state="success" />
                      <WorkbenchStateBadge state="pending-approval" />
                      <WorkbenchStateBadge state="unknown" />
                      <WorkbenchStateBadge state="planned" />
                    </div>
                  </div>
                ) : null}
              </div>
            </details>
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
            className="border-t border-slate-100 bg-cyan-50 px-4 py-1 text-xs text-cyan-900 sm:hidden"
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

      <WorkbenchDock />
      <div id="workbench-slot-artifact-drawer" className="contents" data-workbench-slot="artifact-drawer" />
    </div>
  )
}
