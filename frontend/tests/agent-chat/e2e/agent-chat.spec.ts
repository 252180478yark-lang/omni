import { test, expect } from '@playwright/test'

test('chat: create session + send simple prompt', async ({ page }) => {
  await page.goto('/chat')
  // 新建 session
  await page.click('button:has-text("新建")')
  // 等左侧出现新对话
  await expect(page.locator('aside button').filter({ hasText: '新对话' }).first()).toBeVisible()
  // 输入 prompt
  await page.fill('textarea', '说一句你好')
  await page.keyboard.press('Enter')
  // 等 assistant 气泡出现（最长 60s）
  await expect(page.locator('text=/你好|hi/').first()).toBeVisible({ timeout: 60000 })
})

test('chat: list_skus tool invocation renders chip + result', async ({ page }) => {
  await page.goto('/chat')
  await page.click('button:has-text("新建")')
  await page.fill('textarea', '列下我所有的 SKU')
  await page.keyboard.press('Enter')
  // 等 tool_call chip
  await expect(page.locator('text=list_skus').first()).toBeVisible({ timeout: 60000 })
  // 等结果
  await expect(page.locator('text=/SKU-\\d+/').first()).toBeVisible({ timeout: 90000 })
})
