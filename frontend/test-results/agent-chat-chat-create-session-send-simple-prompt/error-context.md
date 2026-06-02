# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: agent-chat.spec.ts >> chat: create session + send simple prompt
- Location: tests\agent-chat\e2e\agent-chat.spec.ts:3:5

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('aside button').filter({ hasText: '新对话' }).first()
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for locator('aside button').filter({ hasText: '新对话' }).first()

```

```yaml
- complementary:
  - link:
    - /url: /workspace
  - navigation:
    - link:
      - /url: /workspace
    - link:
      - /url: /products
    - link:
      - /url: /scout
    - link:
      - /url: /news
    - link:
      - /url: /knowledge/harvester
    - link:
      - /url: /knowledge
    - link:
      - /url: /chat
    - link:
      - /url: /content-studio
    - link:
      - /url: /sku-pipeline
    - link:
      - /url: /video-analysis
    - link:
      - /url: /reverse-engineer
    - link:
      - /url: /livestream-analysis
    - link:
      - /url: /cost
    - link:
      - /url: /ad-review
    - link:
      - /url: /ad-review/flywheel
    - link:
      - /url: /decisions
    - link:
      - /url: /inbox
    - link:
      - /url: /agent-log
    - link:
      - /url: /review
    - link:
      - /url: /models
    - link:
      - /url: /tasks
    - link:
      - /url: /prompt-lab
    - link:
      - /url: /
  - link:
    - /url: /chat
  - button
- complementary:
  - text: 对话
  - button "新建"
  - text: 还没有对话 点新建开始
- main:
  - heading "从左侧选一个对话" [level=1]
  - text: 从左侧选或新建一个对话开始
- button "打开新手指南": 新手指南
- button
- heading "欢迎使用 Omni-Vibe，这是写给新手的说明书" [level=2]
- paragraph: 不需要懂技术，跟着看 3 分钟就能上手
- button "它是什么？"
- button "能干什么？"
- button "怎么开始？"
- button "常见疑问"
- paragraph: 一句话讲：这是一个"AI 万能小助理"——你把工作里要看的资料、要分析的视频、要回的问题、要投的广告数据都丢给它，它帮你做完。
- paragraph: 用人话讲：想象你雇了一个 24 小时不睡觉、读过所有资料、会做表的实习生。Omni 就是这个实习生的"工作台"，左边菜单里每个功能都是它的一项技能。
- paragraph: 谁适合用？电商运营、内容创作者、产品经理、销售、老板……只要你每天要"看资料 + 做分析 + 写东西"，就能省一半时间。
- text: 不用装东西 打开浏览器就能用，不需要你写代码、配环境 数据在你电脑上 上传的资料只存本地，不会被别的公司看到 按需付费 只在你向 AI 提问时花钱，每次几分钱级别
- heading "现在该做什么？" [level=4]
- paragraph: 点上面的"怎么开始？"标签，跟着 4 步走一遍，10 分钟内就能完整跑通。
- paragraph: 以后想再看这份指南，点页面右下角紫色"新手指南"按钮即可
- button "我懂了，开始使用"
- alert
- img
- text: 3 errors
- button "Hide Errors":
  - img
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test'
  2  | 
  3  | test('chat: create session + send simple prompt', async ({ page }) => {
  4  |   await page.goto('/chat')
  5  |   // 新建 session
  6  |   await page.click('button:has-text("新建")')
  7  |   // 等左侧出现新对话
> 8  |   await expect(page.locator('aside button').filter({ hasText: '新对话' }).first()).toBeVisible()
     |                                                                                 ^ Error: expect(locator).toBeVisible() failed
  9  |   // 输入 prompt
  10 |   await page.fill('textarea', '说一句你好')
  11 |   await page.keyboard.press('Enter')
  12 |   // 等 assistant 气泡出现（最长 60s）
  13 |   await expect(page.locator('text=/你好|hi/').first()).toBeVisible({ timeout: 60000 })
  14 | })
  15 | 
  16 | test('chat: list_skus tool invocation renders chip + result', async ({ page }) => {
  17 |   await page.goto('/chat')
  18 |   await page.click('button:has-text("新建")')
  19 |   await page.fill('textarea', '列下我所有的 SKU')
  20 |   await page.keyboard.press('Enter')
  21 |   // 等 tool_call chip
  22 |   await expect(page.locator('text=list_skus').first()).toBeVisible({ timeout: 60000 })
  23 |   // 等结果
  24 |   await expect(page.locator('text=/SKU-\\d+/').first()).toBeVisible({ timeout: 90000 })
  25 | })
  26 | 
```