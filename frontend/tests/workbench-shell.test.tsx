// @vitest-environment happy-dom

import { StrictMode, useState } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import PromptLabPage from '@/app/prompt-lab/page'
import NotFound from '@/app/not-found'
import { AppShell } from '@/components/app-shell'
import { WorkbenchStateBadge, type WorkbenchViewState } from '@/components/workbench-state-badge'
import {
  WORKBENCH_MODE_STORAGE_KEY,
  WORKBENCH_OVERVIEW_REFRESH_MS,
  WORKBENCH_PREFERENCE_ERROR,
  useWorkbenchStore,
} from '@/stores/workbenchStore'

const searchParams = new URLSearchParams()
const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>()
let testPathname = '/workspace'

vi.mock('next/navigation', () => ({
  usePathname: () => testPathname,
  useSearchParams: () => searchParams,
}))

vi.mock('@/components/beginner-guide', () => ({ BeginnerGuide: () => null }))
vi.mock('@/components/prompt-node-drawer', () => ({ PromptNodeDrawer: () => null }))

vi.mock('@/lib/feature-registry', () => ({
  featuresForPlacement: () => [{
    feature_id: 'workspace-operations',
    title: '工作台',
    domain: 'workspace',
    href: '/workspace',
    visible: true,
    placements: ['sidebar'],
    lifecycle: 'active',
    aliases: [],
    capabilities: [],
  }],
}))

const groupDefinitions = {
  work: [
    ['today', '今日'],
    ['products', '商品'],
    ['operations', '经营'],
    ['content', '内容'],
    ['knowledge', '知识'],
  ],
  development: [
    ['agents', 'Agents'],
    ['skills-tools', 'Skills & Tools'],
    ['workflows', 'Workflows'],
    ['prompt-eval', 'Prompt & Eval'],
    ['runs-system', 'Runs & System'],
  ],
} as const

vi.mock('@/lib/workbench-ia', () => ({
  workbenchNavigationForMode: (mode: 'work' | 'development') => groupDefinitions[mode].map(([id, label], index) => {
    const href = index === 0 ? '/workspace' : `/${id}`
    const entries: Array<{
      featureId: string
      title: string
      href: string
      relationship: 'primary'
      order: number
      phase: 'retain'
      flag: null
    }> = [{
      featureId: `${mode}-${id}`,
      title: label,
      href,
      relationship: 'primary' as const,
      order: index,
      phase: 'retain' as const,
      flag: null,
    }]
    if (id === 'prompt-eval') {
      entries.push({
        featureId: 'quality-assurance',
        title: 'QA 与质量检查',
        href: '/qa',
        relationship: 'primary' as const,
        order: 10,
        phase: 'retain' as const,
        flag: null,
      })
    }
    return { id, mode, label, href, entries }
  }),
  resolveWorkbenchLocation: (pathname: string, params?: string, activeMode: 'work' | 'development' = 'work') => {
    if (pathname.startsWith('/not-registered')) {
      return {
        kind: 'unregistered',
        requestedHref: pathname,
        canonicalHref: pathname,
        contextualGroups: [],
        breadcrumb: [],
        effectiveMode: activeMode,
      }
    }
    if (pathname.startsWith('/ambiguous-route')) {
      return {
        kind: 'ambiguous',
        requestedHref: pathname,
        canonicalHref: pathname,
        contextualGroups: [],
        breadcrumb: [],
        effectiveMode: activeMode,
      }
    }
    const requestedMode = new URLSearchParams(params).get('mode')
    const effectiveMode = requestedMode === 'development' || requestedMode === 'execution'
      ? 'development'
      : requestedMode === 'business' ? 'work' : activeMode
    const sku = pathname === '/sku-pipeline'
    return {
      kind: 'canonical',
      requestedHref: pathname,
      canonicalHref: pathname,
      matchedSurface: pathname,
      featureId: sku ? 'sku-pipeline' : 'work-today',
      primary: { mode: 'work', group: sku ? 'products' : 'today' },
      contextualGroups: [{ mode: 'development', group: sku ? 'workflows' : 'runs-system', order: 10 }],
      breadcrumb: sku && effectiveMode === 'development'
        ? [
            { label: '开发', href: '/workspace?mode=development' },
            { label: 'Workflows', href: '/sku-pipeline' },
            { label: 'SKU 圈包链路', href: '/sku-pipeline' },
          ]
        : [{ label: sku ? 'SKU 圈包链路' : '今日', href: pathname }],
      effectiveMode,
    }
  },
}))

function StatefulChild() {
  const [value, setValue] = useState('keep-me')
  return <input aria-label="child-state" value={value} onChange={(event) => setValue(event.target.value)} />
}

beforeEach(() => {
  window.localStorage.clear()
  searchParams.delete('mode')
  testPathname = '/workspace'
  useWorkbenchStore.getState().reset()
  fetchMock.mockReset()
  fetchMock.mockImplementation(async (input) => String(input) === '/api/omni/overview'
    ? new Response(JSON.stringify({ success: false }), { status: 503 })
    : new Response('{}', { status: 202 }))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('unified workbench shell', () => {
  it('renders exactly five registry-driven entries per mode without remounting child or continuity state', async () => {
    useWorkbenchStore.getState().bindContinuity({
      contextRevision: 'context:sku-001:rev-3',
      contextLabel: 'SKU-001',
      contextStatus: 'available',
      resolvedProvider: 'codex',
      providerStatus: 'available',
      systemHealth: 'healthy',
      systemFreshness: 'fresh',
      operationId: 'operation:001',
      agentSessionId: 'session:001',
    })

    render(<AppShell unifiedShellEnabled><StatefulChild /></AppShell>)
    await waitFor(() => expect(useWorkbenchStore.getState().preferenceHydrated).toBe(true))
    expect(screen.getByTestId('unified-app-shell').getAttribute('data-workbench-density')).toBe('comfortable')
    expect(document.querySelectorAll('[data-workbench-primary-group]')).toHaveLength(5)
    expect(screen.getByRole('navigation', { name: '工作模式一级导航' })).toBeTruthy()

    fireEvent.change(screen.getByLabelText('child-state'), { target: { value: 'still-mounted' } })
    fireEvent.click(screen.getByRole('button', { name: '开发' }))

    expect(await screen.findByRole('navigation', { name: '开发模式一级导航' })).toBeTruthy()
    expect(screen.getByTestId('unified-app-shell').getAttribute('data-workbench-density')).toBe('compact')
    expect(document.querySelectorAll('[data-workbench-primary-group]')).toHaveLength(5)
    expect((screen.getByLabelText('child-state') as HTMLInputElement).value).toBe('still-mounted')
    expect(useWorkbenchStore.getState()).toMatchObject({
      contextRevision: 'context:sku-001:rev-3',
      contextStatus: 'available',
      operationId: 'operation:001',
      agentSessionId: 'session:001',
    })
    expect(screen.getByTestId('workbench-context-status').textContent).toContain('SKU-001')
    expect(screen.getByTestId('workbench-provider-status').textContent).toContain('codex')
  })

  it('uses honest unavailable defaults and exposes stable extension slots', async () => {
    render(<AppShell unifiedShellEnabled><div>内容</div></AppShell>)
    await waitFor(() => expect(useWorkbenchStore.getState().preferenceHydrated).toBe(true))

    expect(screen.getByTestId('workbench-context-status').textContent).toContain('未选择')
    expect(screen.getByTestId('workbench-provider-status').textContent).toContain('未解析')
    expect(screen.getByTestId('workbench-health-status').textContent).toContain('unavailable / unknown')
    for (const slot of ['assistant', 'blueprint', 'run-center', 'approval', 'artifact-drawer']) {
      expect(document.querySelector(`[data-workbench-slot="${slot}"]`)).toBeTruthy()
    }
  })

  it('shows storage degradation to sighted users while keeping the current session usable', async () => {
    render(<AppShell unifiedShellEnabled><div>内容</div></AppShell>)
    await waitFor(() => expect(useWorkbenchStore.getState().preferenceHydrated).toBe(true))

    act(() => useWorkbenchStore.setState({ preferenceError: WORKBENCH_PREFERENCE_ERROR }))

    const status = screen.getByTestId('workbench-preference-status')
    expect(status.textContent).toContain('当前会话仍可继续使用')
    expect(status.className).not.toContain('sr-only')
    expect(status.className).toContain('border-amber-300')
  })

  it('emits opened only after a mounted location and keeps an uncommitted click as selected intent', async () => {
    render(<AppShell unifiedShellEnabled><div>内容</div></AppShell>)
    await waitFor(() => expect(useWorkbenchStore.getState().preferenceHydrated).toBe(true))

    await waitFor(() => expect(fetchMock.mock.calls.some(([, request]) => {
      if (!request?.body) return false
      return JSON.parse(String(request.body)).result === 'opened'
    })).toBe(true))
    const openedCall = fetchMock.mock.calls.find(([, request]) => request?.body && JSON.parse(String(request.body)).result === 'opened')
    expect(JSON.parse(String(openedCall?.[1]?.body))).toMatchObject({
      event_type: 'primary_navigation',
      requested_href: '/workspace',
      canonical_href: '/workspace',
      feature_id: 'work-today',
      mode: 'work',
      primary_group: 'today',
      secondary_depth: 0,
      result: 'opened',
    })

    fetchMock.mockClear()

    fireEvent.click(within(screen.getByTestId('workbench-sidebar')).getByRole('link', { name: '今日' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input) === '/api/omni/workbench/navigation-events')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([input]) => String(input) === '/api/omni/workbench/navigation-events') || []
    expect(JSON.parse(String(request?.body))).toMatchObject({
      event_type: 'primary_navigation',
      requested_href: '/workspace',
      canonical_href: '/workspace',
      feature_id: 'work-today',
      mode: 'work',
      primary_group: 'today',
      secondary_depth: 0,
      result: 'selected',
    })
    expect(fetchMock.mock.calls.some(([, init]) => init?.body && JSON.parse(String(init.body)).result === 'opened')).toBe(false)
  })

  it('uses the filtered non-first entry as the group landing and telemetry identity', async () => {
    render(<AppShell unifiedShellEnabled><div>内容</div></AppShell>)
    await waitFor(() => expect(useWorkbenchStore.getState().preferenceHydrated).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: '开发' }))
    fireEvent.change(screen.getByRole('searchbox', { name: '全局搜索功能或命令' }), { target: { value: 'QA' } })

    const qaLanding = within(screen.getByTestId('workbench-sidebar')).getByRole('link', { name: 'Prompt & Eval' })
    expect(qaLanding.getAttribute('href')).toBe('/qa')
    fetchMock.mockClear()
    fireEvent.click(qaLanding)

    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input) === '/api/omni/workbench/navigation-events')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([input]) => String(input) === '/api/omni/workbench/navigation-events') || []
    expect(JSON.parse(String(request?.body))).toMatchObject({
      requested_href: '/qa',
      canonical_href: '/qa',
      feature_id: 'quality-assurance',
      mode: 'development',
      primary_group: 'prompt-eval',
      secondary_depth: 0,
      result: 'selected',
    })
  })

  it.each(['development', 'execution'])('lets an explicit workspace %s query override a stored work preference', async (requestedMode) => {
    window.localStorage.setItem(WORKBENCH_MODE_STORAGE_KEY, 'work')
    searchParams.set('mode', requestedMode)

    render(<AppShell unifiedShellEnabled><div>开发入口</div></AppShell>)

    await waitFor(() => expect(useWorkbenchStore.getState().mode).toBe('development'))
    expect(screen.getByRole('button', { name: '开发' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('binds only observed overview health and freshness while leaving context and provider unknown', async () => {
    fetchMock.mockImplementation(async (input) => String(input) === '/api/omni/overview'
      ? new Response(JSON.stringify({
          success: true,
          data: {
            health: {
              summary: 'healthy',
              partial: false,
              generatedAt: new Date().toISOString(),
            },
          },
        }), { status: 200 })
      : new Response('{}', { status: 202 }))

    render(<AppShell unifiedShellEnabled><div>内容</div></AppShell>)

    await waitFor(() => expect(useWorkbenchStore.getState()).toMatchObject({ systemHealth: 'healthy', systemFreshness: 'fresh' }))
    expect(useWorkbenchStore.getState()).toMatchObject({
      contextRevision: null,
      contextStatus: 'unavailable',
      resolvedProvider: null,
      providerStatus: 'unknown',
    })
    expect(screen.getByTestId('workbench-health-status').textContent).toContain('healthy / fresh')
    expect(screen.getByTestId('workbench-context-status').textContent).toContain('未选择')
    expect(screen.getByTestId('workbench-provider-status').textContent).toContain('未解析')
  })

  it('fails closed to unavailable and unknown when the overview schema is invalid', async () => {
    useWorkbenchStore.getState().bindContinuity({ systemHealth: 'healthy', systemFreshness: 'fresh' })
    fetchMock.mockImplementation(async (input) => String(input) === '/api/omni/overview'
      ? new Response(JSON.stringify({ success: true, data: { health: { summary: 'healthy' } } }), { status: 200 })
      : new Response('{}', { status: 202 }))

    render(<AppShell unifiedShellEnabled><div>内容</div></AppShell>)

    await waitFor(() => expect(useWorkbenchStore.getState()).toMatchObject({ systemHealth: 'unavailable', systemFreshness: 'unknown' }))
    expect(screen.getByTestId('workbench-health-status').textContent).toContain('unavailable / unknown')
  })

  it('shows the active Development breadcrumb for a contextual SKU surface', async () => {
    testPathname = '/sku-pipeline'
    render(<AppShell unifiedShellEnabled><div>SKU 内容</div></AppShell>)
    await waitFor(() => expect(useWorkbenchStore.getState().preferenceHydrated).toBe(true))

    fireEvent.click(screen.getByRole('button', { name: '开发' }))

    const breadcrumb = screen.getByRole('navigation', { name: '当前位置' })
    expect(breadcrumb.textContent).toContain('开发')
    expect(breadcrumb.textContent).toContain('Workflows')
    expect(breadcrumb.textContent).toContain('SKU 圈包链路')
  })

  it('refreshes overview on a bounded interval and visibility without coupling context or provider', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-02T10:00:00.000Z'))
    useWorkbenchStore.getState().bindContinuity({
      contextRevision: 'context:sku-002:rev-1',
      contextLabel: 'SKU-002',
      contextStatus: 'available',
      resolvedProvider: 'codex',
      providerStatus: 'available',
    })
    let overviewCalls = 0
    fetchMock.mockImplementation(async (input) => {
      if (String(input) !== '/api/omni/overview') return new Response('{}', { status: 202 })
      overviewCalls += 1
      return new Response(JSON.stringify({
        success: true,
        data: {
          health: {
            summary: overviewCalls === 1 ? 'degraded' : 'healthy',
            partial: overviewCalls === 1,
            generatedAt: new Date().toISOString(),
          },
        },
      }), { status: 200 })
    })

    render(<AppShell unifiedShellEnabled><div>内容</div></AppShell>)
    await act(async () => { await Promise.resolve() })
    expect(overviewCalls).toBe(1)

    await act(async () => { await vi.advanceTimersByTimeAsync(WORKBENCH_OVERVIEW_REFRESH_MS) })
    expect(overviewCalls).toBe(2)
    expect(useWorkbenchStore.getState()).toMatchObject({
      systemHealth: 'healthy',
      systemFreshness: 'fresh',
      contextRevision: 'context:sku-002:rev-1',
      contextStatus: 'available',
      resolvedProvider: 'codex',
      providerStatus: 'available',
    })

    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
      await Promise.resolve()
    })
    expect(overviewCalls).toBe(3)
  })

  it('restores the legacy shell when the unified flag is disabled', () => {
    render(<AppShell unifiedShellEnabled={false}><div>经典内容</div></AppShell>)
    expect(screen.getByTestId('legacy-app-shell')).toBeTruthy()
    expect(screen.getByTestId('legacy-sidebar')).toBeTruthy()
    expect(screen.queryByTestId('unified-app-shell')).toBeNull()
  })
})

describe('workbench state semantics', () => {
  it('keeps all six view states and adds a text-and-icon planned state', () => {
    const states: WorkbenchViewState[] = ['loading', 'empty', 'error', 'success', 'pending-approval', 'unknown', 'planned']
    render(<div>{states.map((state) => <WorkbenchStateBadge key={state} state={state} testId={`state-${state}`} />)}</div>)

    for (const state of states) {
      const badge = screen.getByTestId(`state-${state}`)
      expect(badge.textContent?.trim()).not.toBe('')
      expect(badge.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
      expect(badge.className).toContain(`workbench-state--${state}`)
    }
    expect(screen.getByTestId('state-unknown').className).not.toContain('success')
    expect(screen.getByTestId('state-pending-approval').className).toContain('pending-approval')
    expect(screen.getByTestId('state-planned').textContent).toContain('计划中')
    expect(screen.getByTestId('state-planned').className).toContain('workbench-state--planned')
  })
})

describe('Prompt Lab truthful empty state', () => {
  it('starts initialized as loading, then explains a successful empty response without flashing a false empty state', async () => {
    let promptNodeCalls = 0
    let releaseInitialResponse: (() => void) | undefined
    fetchMock.mockImplementation(async (input) => {
      if (String(input) === '/api/omni/prompt/nodes') {
        promptNodeCalls += 1
        if (promptNodeCalls === 1) {
          await new Promise<void>((resolve) => { releaseInitialResponse = resolve })
        }
        return new Response(JSON.stringify({ success: true, data: { nodes: [] } }), { status: 200 })
      }
      return new Response('{}', { status: 202 })
    })

    render(<PromptLabPage />)

    expect(screen.getByText('加载中…')).toBeTruthy()
    expect(screen.queryByTestId('prompt-lab-empty-state')).toBeNull()
    await act(async () => {
      releaseInitialResponse?.()
      await Promise.resolve()
    })

    const empty = await screen.findByRole('status', { name: '暂无已登记的 Prompt 节点' })
    expect(empty.textContent).toContain('不会临时生成假节点')
    expect(empty.textContent).toContain('不代表高级评测后端已经就绪')
    expect(empty.textContent).toContain('P0 数据库迁移')
    fireEvent.click(within(empty).getByRole('button', { name: '重新读取节点' }))
    await waitFor(() => expect(promptNodeCalls).toBe(2))
  })
})

describe('workbench route-gap compatibility page', () => {
  it('renders an accessible unregistered entry and reports it once under StrictMode without a client token', async () => {
    testPathname = '/not-registered-unit'

    render(<StrictMode><NotFound /></StrictMode>)

    const gap = screen.getByTestId('workbench-route-gap')
    expect(gap.getAttribute('data-gap-kind')).toBe('unregistered')
    expect(screen.getByRole('heading', { name: '此入口尚未登记' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '返回工作台' }).getAttribute('href')).toBe('/workspace')
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))

    const [input, request] = fetchMock.mock.calls[0]
    expect(String(input)).toBe('/api/omni/workbench/navigation-events')
    expect(request).toMatchObject({
      method: 'POST',
      credentials: 'same-origin',
      keepalive: true,
    })
    expect(request?.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(String(request?.body))).toEqual({
      event_type: 'route_gap',
      requested_href: '/not-registered-unit',
      result: 'unregistered',
    })
    expect(JSON.stringify(request)).not.toMatch(/authorization|token/i)
  })

  it('distinguishes an ambiguous registry entry and reports the matching outcome', async () => {
    testPathname = '/ambiguous-route-unit'

    render(<NotFound />)

    const gap = screen.getByTestId('workbench-route-gap')
    expect(gap.getAttribute('data-gap-kind')).toBe('ambiguous')
    expect(screen.getByRole('heading', { name: '入口归属冲突' })).toBeTruthy()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      event_type: 'route_gap',
      requested_href: '/ambiguous-route-unit',
      result: 'ambiguous',
    })
  })
})
