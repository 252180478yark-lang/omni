# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: agent-chat.spec.ts >> chat: list_skus tool invocation renders chip + result
- Location: tests\agent-chat\e2e\agent-chat.spec.ts:16:5

# Error details

```
TimeoutError: page.fill: Timeout 10000ms exceeded.
Call log:
  - waiting for locator('textarea')

```

# Page snapshot

```yaml
- generic [ref=e1]:
  - generic [ref=e2]:
    - complementary [ref=e3]:
      - link [ref=e5] [cursor=pointer]:
        - /url: /workspace
        - img [ref=e7]
      - navigation [ref=e19]:
        - link [ref=e21] [cursor=pointer]:
          - /url: /workspace
          - img [ref=e23]
        - link [ref=e26] [cursor=pointer]:
          - /url: /products
          - img [ref=e28]
        - link [ref=e33] [cursor=pointer]:
          - /url: /scout
          - img [ref=e35]
        - link [ref=e42] [cursor=pointer]:
          - /url: /news
          - img [ref=e44]
        - link [ref=e47] [cursor=pointer]:
          - /url: /knowledge/harvester
          - img [ref=e49]
        - link [ref=e53] [cursor=pointer]:
          - /url: /knowledge
          - img [ref=e55]
        - link [ref=e59] [cursor=pointer]:
          - /url: /chat
          - img [ref=e62]
        - link [ref=e71] [cursor=pointer]:
          - /url: /content-studio
          - img [ref=e73]
        - link [ref=e79] [cursor=pointer]:
          - /url: /sku-pipeline
          - img [ref=e81]
        - link [ref=e84] [cursor=pointer]:
          - /url: /video-analysis
          - img [ref=e86]
        - link [ref=e91] [cursor=pointer]:
          - /url: /reverse-engineer
          - img [ref=e93]
        - link [ref=e96] [cursor=pointer]:
          - /url: /livestream-analysis
          - img [ref=e98]
        - link [ref=e105] [cursor=pointer]:
          - /url: /cost
          - img [ref=e107]
        - link [ref=e109] [cursor=pointer]:
          - /url: /ad-review
          - img [ref=e111]
        - link [ref=e114] [cursor=pointer]:
          - /url: /ad-review/flywheel
          - img [ref=e116]
        - link [ref=e121] [cursor=pointer]:
          - /url: /decisions
          - img [ref=e123]
        - link [ref=e127] [cursor=pointer]:
          - /url: /inbox
          - img [ref=e129]
        - link [ref=e132] [cursor=pointer]:
          - /url: /agent-log
          - img [ref=e134]
        - link [ref=e136] [cursor=pointer]:
          - /url: /review
          - img [ref=e138]
        - link [ref=e141] [cursor=pointer]:
          - /url: /models
          - img [ref=e143]
        - link [ref=e146] [cursor=pointer]:
          - /url: /tasks
          - img [ref=e148]
        - link [ref=e151] [cursor=pointer]:
          - /url: /prompt-lab
          - img [ref=e153]
        - link [ref=e156] [cursor=pointer]:
          - /url: /
          - img [ref=e158]
      - link [ref=e162] [cursor=pointer]:
        - /url: /chat
        - img [ref=e164]
      - button [ref=e168] [cursor=pointer]:
        - img [ref=e169]
    - generic [ref=e172]:
      - complementary [ref=e173]:
        - generic [ref=e174]:
          - generic [ref=e175]: 对话
          - button "新建" [active] [ref=e176] [cursor=pointer]:
            - img [ref=e177]
            - text: 新建
        - generic [ref=e179]:
          - text: 还没有对话
          - text: 点新建开始
      - main [ref=e180]:
        - heading "从左侧选一个对话" [level=1] [ref=e183]
        - generic [ref=e184]: 从左侧选或新建一个对话开始
    - button "打开新手指南" [ref=e185] [cursor=pointer]:
      - img [ref=e186]
      - generic [ref=e189]: 新手指南
    - generic [ref=e191]:
      - generic [ref=e192]:
        - button [ref=e193] [cursor=pointer]:
          - img [ref=e194]
        - generic [ref=e197]:
          - img [ref=e199]
          - generic [ref=e202]:
            - heading "欢迎使用 Omni-Vibe，这是写给新手的说明书" [level=2] [ref=e203]
            - paragraph [ref=e204]: 不需要懂技术，跟着看 3 分钟就能上手
        - generic [ref=e205]:
          - button "它是什么？" [ref=e206] [cursor=pointer]
          - button "能干什么？" [ref=e207] [cursor=pointer]
          - button "怎么开始？" [ref=e208] [cursor=pointer]
          - button "常见疑问" [ref=e209] [cursor=pointer]
      - generic [ref=e211]:
        - generic [ref=e213]:
          - img [ref=e215]
          - generic [ref=e217]:
            - paragraph [ref=e218]: 一句话讲：这是一个"AI 万能小助理"——你把工作里要看的资料、要分析的视频、要回的问题、要投的广告数据都丢给它，它帮你做完。
            - paragraph [ref=e219]: 用人话讲：想象你雇了一个 24 小时不睡觉、读过所有资料、会做表的实习生。Omni 就是这个实习生的"工作台"，左边菜单里每个功能都是它的一项技能。
            - paragraph [ref=e220]: 谁适合用？电商运营、内容创作者、产品经理、销售、老板……只要你每天要"看资料 + 做分析 + 写东西"，就能省一半时间。
        - generic [ref=e221]:
          - generic [ref=e222]:
            - img [ref=e223]
            - generic [ref=e226]: 不用装东西
            - generic [ref=e227]: 打开浏览器就能用，不需要你写代码、配环境
          - generic [ref=e228]:
            - img [ref=e229]
            - generic [ref=e232]: 数据在你电脑上
            - generic [ref=e233]: 上传的资料只存本地，不会被别的公司看到
          - generic [ref=e234]:
            - img [ref=e235]
            - generic [ref=e238]: 按需付费
            - generic [ref=e239]: 只在你向 AI 提问时花钱，每次几分钱级别
        - generic [ref=e241]:
          - img [ref=e243]
          - generic [ref=e248]:
            - heading "现在该做什么？" [level=4] [ref=e249]
            - paragraph [ref=e250]: 点上面的"怎么开始？"标签，跟着 4 步走一遍，10 分钟内就能完整跑通。
      - generic [ref=e251]:
        - paragraph [ref=e252]: 以后想再看这份指南，点页面右下角紫色"新手指南"按钮即可
        - button "我懂了，开始使用" [ref=e253] [cursor=pointer]:
          - text: 我懂了，开始使用
          - img
  - alert [ref=e254]
  - generic [ref=e257] [cursor=pointer]:
    - img [ref=e258]
    - generic [ref=e260]: 2 errors
    - button "Hide Errors" [ref=e261]:
      - img [ref=e262]
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
  8  |   await expect(page.locator('aside button').filter({ hasText: '新对话' }).first()).toBeVisible()
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
> 19 |   await page.fill('textarea', '列下我所有的 SKU')
     |              ^ TimeoutError: page.fill: Timeout 10000ms exceeded.
  20 |   await page.keyboard.press('Enter')
  21 |   // 等 tool_call chip
  22 |   await expect(page.locator('text=list_skus').first()).toBeVisible({ timeout: 60000 })
  23 |   // 等结果
  24 |   await expect(page.locator('text=/SKU-\\d+/').first()).toBeVisible({ timeout: 90000 })
  25 | })
  26 | 
```