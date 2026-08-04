import axe from 'axe-core'
import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    if (!window.sessionStorage.getItem('workbench-e2e-initialized')) {
      window.localStorage.clear()
      window.localStorage.setItem('omni_beginner_guide_seen_v1', '1')
      window.sessionStorage.setItem('workbench-e2e-initialized', '1')
    }
  })
  await page.route('**/api/omni/overview', (route) => route.fulfill({ status: 200, json: { success: false } }))
  await page.route('**/api/omni/workbench/navigation-events', (route) => route.fulfill({ status: 202, json: { success: true } }))
  await page.route('**/api/omni/scout/**', (route) => route.fulfill({ status: 200, json: { data: [] } }))
  await page.route('**/api/omni/knowledge/bases', (route) => route.fulfill({ status: 200, json: { success: true, data: [] } }))
  await page.route('**/api/omni/models', (route) => route.fulfill({
    status: 200,
    json: {
      success: true,
      data: {
        providers: [
          {
            id: 'ollama',
            name: 'OLLAMA',
            status: 'connected',
            capabilities: ['chat'],
            defaultChatModel: 'qwen-local',
            defaultEmbeddingModel: null,
            models: ['qwen-local'],
            apiKeySet: false,
          },
          {
            id: 'openai',
            name: 'OPENAI',
            status: 'connected',
            capabilities: ['chat', 'embedding'],
            defaultChatModel: 'gpt-test',
            defaultEmbeddingModel: 'embedding-test',
            models: ['gpt-test', 'embedding-test'],
            apiKeySet: true,
          },
        ],
      },
    },
  }))
})

test('migrated developer pages expose keyboard controls and pass main-content accessibility checks', async ({ page }) => {
  await page.goto('/models')
  const openAiProvider = page.getByRole('button', { name: /OPENAI/ })
  await openAiProvider.focus()
  await expect(openAiProvider).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(openAiProvider).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByLabel('API Key')).toBeDisabled()
  await expect(page.getByLabel('默认对话模型', { exact: true })).toBeDisabled()

  const shell = page.getByTestId('unified-app-shell')
  const firstCard = page.locator('[data-slot="card"]').first()
  await expect(shell).toHaveAttribute('data-workbench-density', 'compact')
  await expect.poll(() => shell.evaluate((element) =>
    getComputedStyle(element).getPropertyValue('--workbench-card-padding-block').trim(),
  )).toBe('0.75rem')
  const compactPadding = await firstCard.evaluate((element) => Number.parseFloat(getComputedStyle(element).paddingTop))
  expect(compactPadding).toBe(12)
  await page.goto('/sku-pipeline')
  await expect(shell).toHaveAttribute('data-workbench-density', 'comfortable')
  await expect.poll(() => shell.evaluate((element) =>
    getComputedStyle(element).getPropertyValue('--workbench-card-padding-block').trim(),
  )).toBe('1rem')
  const comfortablePadding = await firstCard.evaluate((element) => Number.parseFloat(getComputedStyle(element).paddingTop))
  expect(comfortablePadding).toBe(16)
  expect(comfortablePadding).toBeGreaterThan(compactPadding)

  for (const route of ['/models', '/knowledge/evaluate']) {
    await page.goto(route)
    await page.addScriptTag({ content: axe.source })
    const violations = await page.evaluate(async () => {
      const result = await window.axe.run({ include: [['#workbench-main']] })
      return result.violations.map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        nodes: violation.nodes.map((node) => node.target),
      }))
    })
    expect(violations).toEqual([])
  }

  await expect(page.getByLabel('知识库')).toBeDisabled()
  await expect(page.getByRole('textbox', { name: '测试查询 1' })).toBeVisible()
  await page.getByRole('button', { name: '添加查询' }).click()
  await expect(page.getByRole('button', { name: '删除查询 2' })).toBeVisible()
})

test('Prompt node details use a trapped keyboard dialog and restore the invoking focus', async ({ page }) => {
  const node = {
    id: 'checkout-helper',
    title: '结账提示',
    description: '只读检查结账提示规则',
    page: '/checkout',
    category: 'analysis',
    enabled: true,
    rule_count: 0,
    hits_7d: 0,
    fb_total_7d: 0,
    fb_negative_7d: 0,
    fb_total_prev_7d: 0,
    fb_negative_prev_7d: 0,
    neg_rate_7d: null,
    neg_rate_prev_7d: null,
    last_hit_at: null,
  }
  await page.unroute('**/api/omni/prompt/nodes')
  await page.route('**/api/omni/prompt/nodes', (route) => route.fulfill({
    status: 200,
    json: { success: true, data: { nodes: [node] } },
  }))
  await page.route('**/api/omni/prompt/nodes/checkout-helper', (route) => route.fulfill({
    status: 200,
    json: { success: true, data: { node, rules: [], recent_feedbacks: [] } },
  }))

  await page.goto('/prompt-lab')
  const trigger = page.getByRole('button', { name: /结账提示/ })
  await trigger.focus()
  await trigger.click()

  const dialog = page.getByRole('dialog', { name: '结账提示' })
  await expect(dialog).toHaveAttribute('aria-modal', 'true')
  const close = dialog.getByRole('button', { name: '关闭' })
  await expect(close).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(close).toBeFocused()

  await page.addScriptTag({ content: axe.source })
  const violations = await page.evaluate(async () => {
    const result = await window.axe.run({ include: [['[role="dialog"]']] })
    return result.violations.map((violation) => violation.id)
  })
  expect(violations).toEqual([])

  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

test('Models load failures are announced without exposing configuration details', async ({ page }) => {
  await page.unroute('**/api/omni/models')
  await page.route('**/api/omni/models', (route) => route.fulfill({
    status: 503,
    json: { success: false, error: '模型服务暂不可用' },
  }))

  await page.goto('/models')
  await expect(page.getByRole('alert').filter({ hasText: '模型服务暂不可用' })).toBeVisible()
  await expect(page.getByLabel('API Key')).toHaveCount(0)
})

test('shell navigation, status semantics and focus pass accessibility checks', async ({ page }, testInfo) => {
  await page.goto('/sku-pipeline')

  await page.keyboard.press('Tab')
  const skipLink = page.getByRole('link', { name: '跳到主内容' })
  await expect(skipLink).toBeFocused()
  await expect(skipLink).toBeVisible()
  await page.keyboard.press('Enter')
  await expect(page.locator('#workbench-main')).toBeFocused()

  await page.getByRole('button', { name: '展开侧边导航' }).click()
  const rendererBounds = await page.evaluate(() => {
    const tabList = document.querySelector('#workbench-main [data-slot="tabs-list"]')?.getBoundingClientRect()
    const activePanel = document.querySelector('#workbench-main [data-slot="tabs-content"]')?.getBoundingClientRect()
    return { tabListRight: tabList?.right || 0, activePanelLeft: activePanel?.left || 0 }
  })
  expect(rendererBounds.tabListRight).toBeLessThanOrEqual(rendererBounds.activePanelLeft)
  const shellGeometry = await page.evaluate(() => {
    const sidebar = document.querySelector('[data-testid="workbench-sidebar"]')?.getBoundingClientRect()
    const header = document.querySelector('header[aria-label="Omni 工作台顶栏"]')?.getBoundingClientRect()
    return { sidebarRight: sidebar?.right || 0, headerLeft: header?.left || 0 }
  })
  expect(shellGeometry.headerLeft).toBeGreaterThanOrEqual(shellGeometry.sidebarRight)
  await page.getByRole('button', { name: '开发', exact: true }).click()
  await page.getByText('状态语义', { exact: true }).click()
  await expect(page.getByLabel('工作台状态语义图例')).toBeVisible()

  await page.addScriptTag({ content: axe.source })
  const violations = await page.evaluate(async () => {
    const result = await window.axe.run({
      include: [['header[aria-label="Omni 工作台顶栏"]'], ['[data-testid="workbench-sidebar"]']],
    })
    return result.violations.map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      nodes: violation.nodes.map((node) => node.target),
    }))
  })
  expect(violations).toEqual([])

  const pending = page.locator('[data-state="pending-approval"]')
  const unknown = page.locator('[data-state="unknown"]').last()
  const planned = page.locator('[data-state="planned"]')
  const colors = await Promise.all([
    pending.evaluate((element) => ({ color: getComputedStyle(element).color, background: getComputedStyle(element).backgroundColor })),
    unknown.evaluate((element) => ({ color: getComputedStyle(element).color, background: getComputedStyle(element).backgroundColor })),
  ])
  expect(colors[0]).not.toEqual(colors[1])
  await expect(planned).toContainText('计划中')
  expect(await planned.evaluate((element) => getComputedStyle(element).borderStyle)).toBe('dashed')

  await page.evaluate(() => {
    window.scrollTo(0, 0)
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
  })
  const skipBounds = await skipLink.boundingBox()
  expect((skipBounds?.y || 0) + (skipBounds?.height || 0)).toBeLessThanOrEqual(0)
  await page.screenshot({ path: testInfo.outputPath('workbench-development-states.png') })
  await page.getByRole('button', { name: '收起侧边导航' }).click()
  await page.getByRole('button', { name: '工作', exact: true }).click()
  await page.screenshot({ path: testInfo.outputPath('workbench-work-mode.png') })
})

declare global {
  interface Window {
    axe: typeof axe
  }
}
