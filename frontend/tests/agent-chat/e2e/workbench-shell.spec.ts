import { expect, test } from '@playwright/test'

const WORK_GROUPS = ['today', 'products', 'operations', 'content', 'knowledge']
const DEVELOPMENT_GROUPS = ['agents', 'skills-tools', 'workflows', 'prompt-eval', 'runs-system']

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    if (!window.sessionStorage.getItem('workbench-e2e-initialized')) {
      window.localStorage.clear()
      window.localStorage.setItem('omni_beginner_guide_seen_v1', '1')
      window.sessionStorage.setItem('workbench-e2e-initialized', '1')
    }
  })
  await page.route('**/api/omni/overview', (route) => route.fulfill({ status: 200, json: { success: false } }))
  await page.route('**/api/omni/prompt/nodes', (route) => route.fulfill({ status: 200, json: { success: true, data: { nodes: [] } } }))
  await page.route('**/api/omni/knowledge/bases', (route) => route.fulfill({ status: 200, json: { success: true, data: [] } }))
  await page.route('**/api/omni/models', (route) => route.fulfill({
    status: 200,
    json: {
      success: true,
      data: {
        providers: [{
          id: 'ollama',
          name: 'OLLAMA',
          status: 'connected',
          capabilities: ['chat'],
          defaultChatModel: 'qwen-local',
          defaultEmbeddingModel: null,
          models: ['qwen-local'],
          apiKeySet: false,
        }],
      },
    },
  }))
  await page.route('**/api/omni/workbench/navigation-events', (route) => route.fulfill({ status: 202, json: { success: true } }))
  await page.route('**/api/omni/scout/**', (route) => route.fulfill({ status: 200, json: { data: [] } }))
  await page.route('**/api/omni/ad-review/**', (route) => route.fulfill({ status: 200, json: { success: true, data: [] } }))
  await page.route('**/api/omni/runtime-traces/active', (route) => route.fulfill({ status: 200, json: { runs: [] } }))
  await page.route('**/api/omni/host-bridge/health', (route) => route.fulfill({ status: 200, json: { state: 'unavailable' } }))
  await page.route('**/api/omni/inbox', (route) => route.fulfill({ status: 200, json: { success: true, data: [], total: 0 } }))
  await page.route('**/api/omni/system-graph/integration-plans', (route) => route.fulfill({ status: 200, json: { plans: [], summaries: {} } }))
  await page.route('**/api/omni/system-graph/snapshot', (route) => route.fulfill({
    status: 200,
    json: {
      snapshot_id: 'w1-e2e-empty',
      generated_at_utc: '2026-08-02T00:00:00.000Z',
      content: { nodes: [], edges: [], source_results: [] },
    },
  }))
  await page.route(/\/api\/omni\/system-graph\/snapshots\/[^/]+\/graph(?:\?.*)?$/, (route) => route.fulfill({
    status: 200,
    json: {
      snapshot_id: 'w1-e2e-empty',
      generated_at_utc: '2026-08-02T00:00:00.000Z',
      nodes: [],
      edges: [],
      source_results: [],
    },
  }))
  await page.route('**/api/agent-chat/sessions', (route) => {
    if (route.request().method() === 'POST') {
      return route.fulfill({ status: 200, json: { success: true, data: { id: 'w1-e2e-sandbox' } } })
    }
    return route.fulfill({ status: 200, json: { success: true, data: [] } })
  })
  await page.routeWebSocket('**/ws/agent-chat', (socket) => {
    socket.onMessage((message) => {
      try {
        const request = JSON.parse(String(message)) as { kind?: string; session_id?: string }
        if (request.kind === 'open_session') {
          socket.send(JSON.stringify({ kind: 'session_opened', session: { id: request.session_id }, history: [] }))
        }
      } catch {
        // Ignore malformed client frames in this isolated shell/navigation test.
      }
    })
  })
})

async function primaryGroups(page: import('@playwright/test').Page) {
  return page.locator('[data-workbench-primary-group]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-workbench-primary-group')))
}

async function expectUniqueCurrentPlacement(
  page: import('@playwright/test').Page,
  expected: { mode: '工作' | '开发'; activeGroup: string; duplicateGroup: string },
) {
  await expect(page.getByRole('button', { name: expected.mode, exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: '展开侧边导航' }).click()

  const navigation = page.getByRole('navigation', { name: `${expected.mode}模式一级导航` })
  const groupCurrents = navigation.locator('[data-workbench-primary-group] > div:first-child > a[aria-current="page"]')
  await expect(groupCurrents).toHaveCount(1)
  await expect(navigation.locator(`[data-workbench-primary-group="${expected.activeGroup}"] > div:first-child > a`)).toHaveAttribute('aria-current', 'page')

  const duplicate = navigation.locator(`[data-workbench-primary-group="${expected.duplicateGroup}"]`)
  const duplicateToggle = duplicate.getByRole('button')
  if (await duplicateToggle.getAttribute('aria-expanded') === 'false') await duplicateToggle.click()

  const secondaryCurrents = navigation.locator('[id^="workbench-group-"] > a[aria-current="page"]')
  await expect(secondaryCurrents).toHaveCount(1)
  await expect(navigation.locator(`[data-workbench-primary-group="${expected.activeGroup}"] [id^="workbench-group-"] > a[aria-current="page"]`)).toHaveCount(1)
  await expect(duplicate.locator('[id^="workbench-group-"] > a[aria-current="page"]')).toHaveCount(0)
}

test('real SKU page uses one persistent 5+5 shell and honest unavailable bindings', async ({ page }) => {
  await page.goto('/sku-pipeline')
  await expect(page.getByTestId('unified-app-shell')).toBeVisible()
  await expect.poll(() => primaryGroups(page)).toEqual(WORK_GROUPS)
  await expect(page.getByTestId('workbench-context-status')).toContainText('未选择')
  await expect(page.getByTestId('workbench-provider-status')).toContainText('未解析')
  await expect(page.getByTestId('workbench-health-status')).toContainText('unavailable / unknown')

  await page.getByRole('button', { name: '展开侧边导航' }).click()
  await expect(page.getByText('SKU 圈包链路', { exact: true }).first()).toBeVisible()

  await page.getByRole('button', { name: '开发', exact: true }).click()
  await expect.poll(() => primaryGroups(page)).toEqual(DEVELOPMENT_GROUPS)
  await expect(page.getByRole('navigation', { name: '开发模式一级导航' })).toBeVisible()
  await expect(page.getByText('SKU 圈包链路', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('navigation', { name: '当前位置' })).toContainText('开发')
  await expect(page.getByRole('navigation', { name: '当前位置' })).toContainText('Workflows')

  for (const slot of ['assistant', 'blueprint', 'run-center', 'approval', 'artifact-drawer']) {
    await expect(page.locator(`[data-workbench-slot="${slot}"]`)).toHaveCount(1)
  }

  await page.reload()
  await expect(page.getByRole('button', { name: '开发', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(() => primaryGroups(page)).toEqual(DEVELOPMENT_GROUPS)
})

test('same-mode contextual placements expose exactly one current group and secondary link', async ({ page }) => {
  const cases = [
    ['/chat', { mode: '开发', activeGroup: 'agents', duplicateGroup: 'prompt-eval' }],
    ['/inbox', { mode: '工作', activeGroup: 'today', duplicateGroup: 'operations' }],
    ['/system-graph?legacy_plan=1', { mode: '开发', activeGroup: 'workflows', duplicateGroup: 'skills-tools' }],
  ] as const

  for (const [href, expected] of cases) {
    await page.goto(href)
    await expectUniqueCurrentPlacement(page, expected)
  }
})

test('Development IA opens the owned System Graph surface without redirecting away from its shared view', async ({ page }) => {
  const browserErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' && !message.text().includes('/_next/webpack-hmr')) browserErrors.push(message.text())
  })
  page.on('pageerror', (error) => browserErrors.push(error.message))

  await page.goto('/sku-pipeline')
  await page.getByRole('button', { name: '开发', exact: true }).click()
  await page.getByRole('button', { name: '展开侧边导航' }).click()
  const skillsAndTools = page.locator('[data-workbench-primary-group="skills-tools"]')
  const toggle = skillsAndTools.getByRole('button')
  if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click()

  const systemGraphLink = skillsAndTools.getByRole('link', { name: 'System graph planning and pilot controls' })
  await expect(systemGraphLink).toHaveAttribute('href', '/system-graph')
  await systemGraphLink.click()

  await expect(page).toHaveURL(/\/system-graph$/)
  const breadcrumb = page.getByRole('navigation', { name: '当前位置' })
  await expect(breadcrumb).toContainText('开发')
  await expect(breadcrumb).toContainText('Workflows')
  await expect(breadcrumb).toContainText('System graph planning and pilot controls')
  await expect(page.getByTestId('system-graph-empty')).toBeVisible()
  expect(browserErrors).toEqual([])
})

test('global search opens and reports a non-first registry entry instead of the original group landing', async ({ page }) => {
  const events: Array<Record<string, unknown>> = []
  await page.unroute('**/api/omni/workbench/navigation-events')
  await page.route('**/api/omni/workbench/navigation-events', async (route) => {
    events.push(JSON.parse(route.request().postData() || '{}') as Record<string, unknown>)
    await route.fulfill({ status: 202, json: { success: true } })
  })
  await page.goto('/sku-pipeline')
  await page.getByRole('button', { name: '开发', exact: true }).click()
  const search = page.getByRole('searchbox', { name: '全局搜索功能或命令' })
  await search.fill('知识评估')
  await expect(page.locator('[data-workbench-primary-group="prompt-eval"]')).toHaveCount(1)
  await expect(page.locator('[data-workbench-primary-group]')).toHaveCount(1)
  const landing = page.getByRole('link', { name: 'Prompt & Eval', exact: true })
  await expect(landing).toHaveAttribute('href', '/knowledge/evaluate')
  await landing.click()
  await expect(page).toHaveURL(/\/knowledge\/evaluate$/)
  await expect.poll(() => events.some((event) => event.result === 'selected' && event.feature_id === 'knowledge-evaluation')).toBe(true)
  expect(events.some((event) => event.result === 'selected' && event.feature_id === 'prompt-lab')).toBe(false)
  await search.fill('')
  await expect(page.locator('[data-workbench-primary-group]')).toHaveCount(5)
})

test('legacy workspace submodes canonicalize into the single Development IA', async ({ page }) => {
  await page.goto('/workspace')
  await expect(page.getByRole('navigation', { name: '工作台模式' })).toHaveCount(0)
  for (const [requestedMode, canonicalPath] of [
    ['development', '/system-graph'],
    ['execution', '/workspace/execution'],
  ] as const) {
    await page.evaluate(() => window.localStorage.setItem('omni.workbench.mode.v1', 'work'))
    await page.goto(`/workspace?mode=${requestedMode}&source=w1-legacy`)
    await expect(page).toHaveURL(new RegExp(`${canonicalPath.replace('/', '\\/')}\\?source=w1-legacy$`))
    await expect(page.getByRole('button', { name: '开发', exact: true })).toHaveAttribute('aria-pressed', 'true')
  }
})

test('owned flywheel and compatibility aliases retain their query without a redirect loop', async ({ page }) => {
  await page.goto('/ad-review/flywheel?source=w1-e2e')
  await expect(page).toHaveURL(/\/ad-review\/flywheel\?source=w1-e2e$/)
  await expect(page.getByTestId('unified-app-shell')).toBeVisible()
  await expect(page.getByRole('navigation', { name: '当前位置' })).toBeVisible()

  await page.goto('/marketing/review?source=w1-ad-review-alias')
  await expect(page).toHaveURL(/\/ad-review\?source=w1-ad-review-alias$/)
  await expect(page.getByTestId('unified-app-shell')).toBeVisible()
  await expect(page.getByRole('navigation', { name: '当前位置' })).toContainText('投放复盘')

  await page.goto('/qa?source=w1-alias')
  await expect(page).toHaveURL(/\/chat\?source=w1-alias$/)
  await expect(page.getByTestId('unified-app-shell')).toBeVisible()
  await expect(page.getByRole('navigation', { name: '当前位置' })).toBeVisible()
})

test('all five Development group landings open sequentially and Prompt Lab exposes its truthful empty state', async ({ page }, testInfo) => {
  const browserErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' && !message.text().includes('/_next/webpack-hmr')) {
      browserErrors.push(message.text())
    }
  })
  page.on('pageerror', (error) => browserErrors.push(error.message))

  const landings = [
    ['agents', '/chat'],
    ['skills-tools', '/playground'],
    ['workflows', '/sku-pipeline'],
    ['prompt-eval', '/prompt-lab'],
    ['runs-system', '/workspace/execution'],
  ] as const

  await page.goto('/sku-pipeline')
  await page.getByRole('button', { name: '开发', exact: true }).click()
  for (const [group, href] of landings) {
    const landing = page.locator(`[data-workbench-primary-group="${group}"]`).getByRole('link').first()
    await expect(landing).toHaveAttribute('href', href)
    await landing.click()
    await expect(page).toHaveURL(new RegExp(`${href.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`))
    await expect(page.getByTestId('unified-app-shell')).toBeVisible()
    await expect(page.getByRole('button', { name: '开发', exact: true })).toHaveAttribute('aria-pressed', 'true')
    if (group === 'prompt-eval') {
      const empty = page.getByRole('status', { name: '暂无已登记的 Prompt 节点' })
      await expect(empty).toContainText('不会临时生成假节点')
      await expect(empty).toContainText('P0 数据库迁移')
      await expect(empty.getByRole('button', { name: '重新读取节点' })).toBeVisible()
      await page.screenshot({ path: testInfo.outputPath('prompt-lab-empty-state.png') })
    }
  }

  await page.goto('/knowledge/evaluate')
  await expect(page.getByTestId('knowledge-eval-empty-state')).toContainText('暂无已登记的评估集')
  await expect(page.getByTestId('knowledge-eval-empty-state')).toContainText('不会把高级实验')

  await page.goto('/models')
  await expect(page.getByTestId('models-read-only-status')).toContainText('仅展示已解析的模型状态')
  await expect(page.getByRole('button', { name: '保存当前供应商配置' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '同步模型列表 (Refresh Models)' })).toBeDisabled()

  await page.goto('/prompt-lab')
  await expect(page.getByTestId('prompt-lab-read-only-status')).toContainText('只读')
  expect(browserErrors).toEqual([])
})

test('Knowledge Eval fails closed when the permission boundary denies mutations', async ({ page }) => {
  await page.unroute('**/api/omni/knowledge/bases')
  await page.route('**/api/omni/knowledge/bases', (route) => route.fulfill({
    status: 200,
    json: { success: true, data: [{ id: 'kb-denied', name: '受控知识库' }] },
  }))
  await page.route('**/api/omni/knowledge/bases/kb-denied/rebuild', (route) => route.fulfill({
    status: 403,
    json: { success: false, error: 'approval_admin_required' },
  }))
  await page.route('**/api/omni/knowledge/rag/evaluate', (route) => route.fulfill({
    status: 403,
    json: { success: false, error: 'approval_admin_required' },
  }))

  await page.goto('/knowledge/evaluate')
  await page.getByRole('button', { name: '重建索引' }).click()
  await expect(page.getByRole('status').filter({ hasText: '重建未执行：请求未获授权或服务不可用（HTTP 403）' })).toBeVisible()

  await page.getByPlaceholder('查询 1...').fill('权限边界验证')
  await page.getByRole('button', { name: '开始评估' }).click()
  await expect(page.getByRole('alert').filter({ hasText: '评估未执行：请求未获授权或服务不可用（HTTP 403）' })).toBeVisible()
  await expect(page.getByText(/优化后平均分|质量提升/)).toHaveCount(0)
})

test('mobile chat and playground consume the actual wrapped-header remainder without outer double scroll', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const route of ['/chat', '/playground']) {
    await page.goto(route)
    const surface = page.locator('[data-workbench-fullscreen="true"]')
    await expect(surface).toBeVisible()
    const geometry = await page.evaluate(() => {
      const header = document.querySelector('header[aria-label="Omni 工作台顶栏"]')?.getBoundingClientRect()
      const main = document.querySelector('[data-workbench-fullscreen="true"]')
      const surface = main?.getBoundingClientRect()
      const child = main?.firstElementChild?.getBoundingClientRect()
      return {
        headerBottom: header?.bottom || 0,
        surfaceTop: surface?.top || 0,
        surfaceBottom: surface?.bottom || 0,
        surfaceHeight: surface?.height || 0,
        childHeight: child?.height || 0,
        viewportHeight: window.innerHeight,
        viewportWidth: window.innerWidth,
        documentHeight: document.documentElement.scrollHeight,
        documentWidth: document.documentElement.scrollWidth,
        bodyHeight: document.body.scrollHeight,
      }
    })
    expect(Math.abs(geometry.surfaceTop - geometry.headerBottom)).toBeLessThanOrEqual(1)
    expect(geometry.surfaceHeight).toBeGreaterThan(200)
    expect(geometry.surfaceBottom).toBeLessThanOrEqual(geometry.viewportHeight + 1)
    expect(Math.abs(geometry.childHeight - geometry.surfaceHeight)).toBeLessThanOrEqual(1)
    expect(geometry.documentHeight).toBeLessThanOrEqual(geometry.viewportHeight)
    expect(geometry.bodyHeight).toBeLessThanOrEqual(geometry.viewportHeight)
    expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth)
    await page.screenshot({ path: testInfo.outputPath(`mobile-${route.slice(1)}.png`) })
  }
})

test('client navigation to an unknown route stays in the shared shell and reports one route gap', async ({ page }) => {
  const events: Array<Record<string, unknown>> = []
  await page.unroute('**/api/omni/workbench/navigation-events')
  await page.route('**/api/omni/workbench/navigation-events', async (route) => {
    events.push(JSON.parse(route.request().postData() || '{}') as Record<string, unknown>)
    await route.fulfill({ status: 202, json: { success: true } })
  })

  await page.goto('/sku-pipeline')
  await expect(page.getByTestId('unified-app-shell')).toBeVisible()
  const pushed = await page.evaluate(() => {
    const nextWindow = window as typeof window & {
      next?: { router?: { push: (href: string) => void } }
    }
    if (!nextWindow.next?.router) return false
    nextWindow.next.router.push('/not-registered-client-e2e')
    return true
  })
  expect(pushed).toBe(true)

  await expect(page).toHaveURL(/\/not-registered-client-e2e$/)
  await expect(page.getByTestId('unified-app-shell')).toBeVisible()
  const gap = page.getByTestId('workbench-route-gap')
  await expect(gap).toHaveAttribute('data-gap-kind', 'unregistered')
  await expect(page.getByRole('heading', { name: '此入口尚未登记' })).toBeVisible()
  await expect.poll(() => events.filter((event) => event.event_type === 'route_gap').length).toBe(1)
  await page.waitForTimeout(100)
  expect(events.filter((event) => event.event_type === 'route_gap')).toEqual([{
    event_type: 'route_gap',
    requested_href: '/not-registered-client-e2e',
    result: 'unregistered',
  }])
  await expect(page.getByRole('link', { name: '返回工作台' })).toHaveAttribute('href', '/workspace')
})
