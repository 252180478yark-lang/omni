# omni-desktop UI 完整重写 — claude.ai 风格 + 多模态 first-class

> 2026-05-25 老板测 0.1.0/0.1.1/0.1.2/0.1.3 连改 8+ bug 后定下来的重写 plan
> 范围只覆盖 renderer/，main / preload / IPC / shared types / migrations 全部不动

## 一句话目标

把 omni-desktop 的 renderer UI 完整重写成 Anthropic claude.ai 风格的桌面 agent
工作台，把 image/video/JSON/markdown 4 类多模态做成跟文本平级的 first-class 渲染，
配 4 状态明确的输入栏 + 顶部累计 cost/latency/tokens status bar，解决老板今天测
4 个版本积累下来的"前端难看 + 用起来不方便"7 大痛点。

## 现状盘点

omni-desktop 主进程链路在过去 5 天 W5-C → 0.1.3 已经跑通：
- `src/main/*.ts` 全套已稳：claude-runner spawn / session-manager LRU 3 并发 /
  pg-client / browser-view-manager (W7 BrowserView) / orch http server / migrations 029
- `src/preload/preload.ts` + `src/shared/types.ts` + `src/shared/ipc-channels.ts`
  已稳，renderer ↔ main 协议成熟
- electron-store 已有 claudeCliPath / omniKeUrl / omniPgUrl / defaultProjectDir /
  openTabs / activeTabId 全部 settings 字段
- renderer 端 12 个 component + 4 个 hook + 1 个 store 的 UI 凑合能用但烂

**这次只重写 renderer/**，main 一行不改，确保后端不引入回归。

## 7 个痛点（重写要解决）

| # | 痛点 | 应该改成 |
|---|------|---------|
| 1 | Sidebar 折叠态 8 个空白 MessageSquare 图标分不清 session | 折叠态显示 session 首字 / 最近 message 预览前 4 字；空 session (message_count=0 且 >1h) 进入 app 时自动软删 |
| 2 | WelcomeScreen 4 张死卡片永远同一组 | 动态：最近常用 prompt（从 mcp.tool_calls 算）+ 当前重点池 SKU 一键入口 |
| 3 | 消息流没多模态：image/video/JSON 显示为链接字符串 | image inline 大图 + lightbox 放大；video 内嵌 player；JSON 折叠表格；markdown 富渲染 |
| 4 | Tool call chip 太简略 | 默认折叠看 tool_name + summary；展开看 input/output raw JSON；LLM tool 多层显示 trace 字段 |
| 5 | 没有 thinking 流式渲染 | 淡灰斜体 + 折叠区显示 thinking block |
| 6 | 没有 cost / latency / token 显示 | 顶部 status bar 加累计 cost / latency / tokens（参考 playground TracePane） |
| 7 | InputBar 状态混乱 | 4 状态独立 UI：idle / thinking / tool_running / waiting_gate；输入框可输入但发送按 disabled |

## 7 个设计原则

1. **Anthropic claude.ai 风格** — 干净 / 留白多 / 信息层级清晰 / 米白 + 浅灰
   + Claude 橙红 #c96442 作 accent；不是 Gemini 渐变也不是聊天软件风
2. **多模态 first-class** — image / video / JSON 表格 / markdown 跟文本平级渲染，
   不藏在折叠里要直接铺开
3. **agent 透明** — 每个 tool 调用可展开 raw input/output + 多层 trace；老板要看
   final_prompt / retrieved_sources 调 prompt
4. **状态明确** — 4 态独立 UI；用户永远知道现在 Claude 在干啥（思考中 / 正在调
   query_costs / 等老板审批 / 空闲）
5. **保留 BrowserView 整合** — TabBar (W7 加的) + Sidebar 工作台区不动，BrowserView
   bounds sync 这套已经能用
6. **保留所有 main 后端** — W7 跨项目 cwd / usage_limit 续跑 / orch http server /
   pg-client / claude-runner / session-manager 全部一行不改
7. **空 session 自动清理** — 启动期把 `message_count=0 AND created_at < now-1h`
   的 session 软删 (status='deleted')，根治堆积问题

## ASCII wireframe — claude.ai 风格 mockup

```
┌────────────────────────────────────────────────────────────────────────┐
│ [📋 Agent] [📚 知识库] [🎬 工坊] [+]   ⚡ 78s · 1245→387 tok · $0.27   │
├──────┬─────────────────────────────────────────────────────────────────┤
│      │ ▼ 诊断 SKU-376253-0012  (5 min · 3 tools · $0.12)              │
│ 🟣   │ ─────────────────────────────────────────────                  │
│      │ 你: 诊断一下 SKU-376253-0012                                    │
│ 诊   │                                                                 │
│ 投   │ ⠋ Claude 思考中...                                              │
│ SKU  │                                                                 │
│ 脚   │ 让我先查成本                                                    │
│      │                                                                 │
│ ─── │ ▼ 🔧 query_costs   0.4s                                          │
│ 📚   │ ┌─ input ─────────────┐ ┌─ output ────────────┐                │
│ 🎬   │ │ {sku_id: "..."}    │ │ 物流5 包装3         │                │
│ 📦   │ └────────────────────┘ └─────────────────────┘                  │
│ 📊   │                                                                 │
│ 💰   │ ▼ 🔧 generate_brief  gemini-2.5-flash · 8.4s · $0.0023          │
│ 📋   │ └─ trace · final_prompt · retrieved_sources                    │
│ 📋   │                                                                 │
│ 📋   │ Claude:                                                         │
│ 📋   │ 健康度 **78/100**                                               │
│ 📋   │ | 维度 | 分 |                                                   │
│      │ |---|---|                                                       │
│ ─── │ | 成本 | 82 |                                                   │
│ 🟢   │                                                                 │
│ 🌙   │ ┌──────┐ ┌──────┐ ┌──────┐                                     │
│ ⚙️   │ │ image│ │ image│ │ image│ ← inline 缩略图, 点击 lightbox      │
│      │ └──────┘ └──────┘ └──────┘                                     │
│      │ [▶ 复盘视频 12s]              ← 内嵌 video player              │
├──────┴─────────────────────────────────────────────────────────────────┤
│ ⠋ 思考中...                                                            │
│ 📎  问点啥... [Enter 发送 · ⌘K 命令]                              ⏎   │
└────────────────────────────────────────────────────────────────────────┘
```

左侧 Sidebar：上半部 session 列表（折叠态显示首字 / 展开态显示标题），下半部
工作台快捷入口（知识库 / 工坊 / 重点池 / 数据 / 成本 / 决策档案），最底主题切换
+ 设置；顶 TabBar 是 W7 加的 BrowserView tab 不动；中间消息流是这次重写主战场。

## 6 切片拆分

| 切片 | 内容 | 工期 |
|------|------|------|
| 1 | claude.ai 设计 tokens + 基础布局（新 ChatLayout 主框架 + Tailwind config 加新色板 + claude-tokens.ts 导出色 / 字 / 圆角 / 阴影） | 0.5 天 |
| 2 | Sidebar 重设：折叠态信息密度 + session preview 渲染 + 空 session 启动自动清理 hook + 工作台区保留 | 1 天 |
| 3 | MessageStream + 4 状态机 + thinking 渲染 + 状态切换淡入淡出动画 | 1.5 天 |
| 4 | 多模态附件 4 类组件（ImageAttachment inline + Lightbox 放大 / VideoAttachment 内嵌 player / JsonAttachment 折叠表格 + raw / MarkdownAttachment 富渲染 with react-markdown） | 1.5 天 |
| 5 | Tool chip 重设：折叠状态 + 展开 input/output raw + LLM tool 多层 trace（复用 playground TracePane 学到的） | 1 天 |
| 6 | InputBar 4 状态独立 UI + status bar 顶部累计 cost/latency/tokens + ⌘K 命令面板（可选最后做） | 1 天 |

**工期合计 5-7 天**。每个切片自己一个 commit，跑通 dev 模式确认无回归再进下一片。

## 文件清单

### 新建（renderer/components/）

- `MessageStream.tsx` — 重写，4 状态机驱动消息流渲染
- `MessageBubble.tsx` — claude.ai 风格 user/assistant bubble
- `ToolCallChip.tsx` — 折叠展开 + trace 多层
- `ThinkingBlock.tsx` — thinking 流式渲染（淡灰斜体 + 折叠）
- `StatusBar.tsx` — 顶部累计 cost / latency / tokens 显示
- `attachments/ImageAttachment.tsx` — inline 缩略图 + 点击 lightbox 放大
- `attachments/VideoAttachment.tsx` — HTML5 `<video>` 内嵌 player
- `attachments/JsonAttachment.tsx` — 折叠表格 view + raw JSON toggle
- `attachments/MarkdownAttachment.tsx` — react-markdown + remark-gfm 富渲染
- `attachments/Lightbox.tsx` — fixed inset-0 + portal 自实现图片放大 modal
- `CommandPalette.tsx` — ⌘K 命令面板（切片 6 可选）

### 改造（renderer/components/）

- `ChatLayout.tsx` — 主框架，保留 TabBar / BrowserViewBoundsSync 整合层
- `Sidebar.tsx` — session 列表渲染重设，保留工作台快捷入口区
- `WelcomeScreen.tsx` — 动态 prompt（从 mcp.tool_calls 拉）+ 重点池 SKU 入口
- `InputBar.tsx` — 4 状态独立 UI（idle / thinking / tool_running / waiting_gate）

### 改造 / 新增（renderer/hooks/）

- `useAgentChat.ts` — 加 4 状态机 state（agent_status: idle | thinking |
  tool_running | waiting_gate）
- `useTabStore.tsx` — 不动
- `useEmptySessionCleanup.ts` — 新，启动期清空 session 的 hook

### 新建（renderer/lib/）

- `claude-tokens.ts` — 颜色 / 字体 / spacing / radius / shadow 等 design tokens
  TypeScript 常量导出
- `recent-prompts.ts` — 从 mcp.tool_calls 拉最近常用 prompt 的查询函数

### 一行不动

- `src/main/*.ts` 全部（claude-runner / session-manager / pg-client /
  browser-view-manager / http-server / ipc-handler / ...）
- `src/preload/preload.ts`
- `src/shared/types.ts` / `src/shared/ipc-channels.ts`
- `migrations/*.sql`

## claude.ai 风格 design tokens

```ts
// src/renderer/lib/claude-tokens.ts
export const COLORS = {
  bg: '#fafaf8',              // 主背景，米白
  bgSoft: '#f6f5f1',          // 次背景
  card: '#ffffff',
  border: '#e8e6e1',          // 浅米色边
  borderSoft: '#f0eee7',
  text: '#2c2c2c',            // 主文本
  textSoft: '#7a7a7a',
  textWeak: '#a3a3a3',
  accent: '#c96442',          // Claude 橙红 (logo 色)
  accentSoft: '#e8a78a',
  accentBg: '#fef4ef',        // 强调底色
  success: '#5b8b5b',         // 沉稳绿
  warning: '#c4904a',
  error: '#c0584b',
}

export const RADIUS = {
  sm: '6px',
  md: '10px',
  lg: '14px',
  xl: '20px',                  // claude.ai 大圆角
}

export const FONTS = {
  sans: '"Söhne", "Inter", system-ui, sans-serif',
  mono: '"JetBrains Mono", "Fira Code", monospace',
}

// 暗色模式同步加 dark.* 字段，用 tailwind dark: 前缀切换
```

`tailwind.config.js` 同步加 `theme.extend.colors.claude.*` 引用上面常量，让组件
可写 `bg-claude-accent` `text-claude-textSoft` 之类。

## 4 状态机定义

`useAgentChat.ts` state field `agentStatus`:

| 状态 | 触发条件 | InputBar UI |
|------|---------|-------------|
| `idle` | 无活跃 task，等用户输入 | 📎 附件 button + 输入框 + 发送箭头亮起 |
| `thinking` | 收到 thinking chunk，未收到 tool_use | "⠋ Claude 思考中..." + 输入框可输入但发送 disabled |
| `tool_running` | 收到 tool_use chunk，未收到对应 tool_result | "⠋ 正在调 query_costs..." + 显示当前 tool name + 发送 disabled |
| `waiting_gate` | task_done 但有 human_gate_card 未批 | "⏸ 等老板审批 record_cost..." + 输入框 disabled + 显示 Gate ID 提示 |

状态切换由 ws-handler chunk 分发自动驱动，淡入淡出动画 200ms。

## 不做项

- 不引入新 npm 包（除非绝对必要 — image lightbox / react-markdown / video.js 等
  逐一检查 package.json，已有就直接用，没有要加先权衡）
- 不改 main process / preload / IPC / migrations 任何一行
- 不做手机端响应式（老板桌面端用，手机走 /chat PWA 那条线）
- 不做多用户（个人自用）
- 不做 i18n（老板只用中文）
- 不集成新 framework（保持 React + Tailwind + Vite，不上 shadcn / mui / ant）
- 不重写 TabBar / BrowserView 整合层（W7 已稳，碰它就出回归）

## 风险 / 已知坑

- **Söhne 字体是 Anthropic 私有**，免费替代 "Inter" 视觉接近 90%；不要尝试盗版
  Söhne 包进 app
- **react-markdown + remark-gfm**：检查 omni frontend 已用过，可直接复用版本号；
  没装就加 2 个包，跟"不引入新包"约束权衡——markdown 富渲染是核心痛点 3 解法，
  必须加
- **video player**：用 HTML5 `<video>` 不引入 video.js；火山方舟 / Veo 返的 mp4
  url 直接喂 src 即可
- **Lightbox**：用 `fixed inset-0` + React portal 自实现，不引入 yet-another-react-
  lightbox 之类的库；50 行内能搞定
- **空 session 清理时机**：放 `useEmptySessionCleanup` hook，在 ChatLayout mount
  期跑一次 UPDATE `mcp.agent_sessions SET status='deleted' WHERE message_count=0
  AND created_at < now() - interval '1 hour' AND status='active'`；走 IPC 调
  main 的 pg-client，不在 renderer 直连 DB
- **dynamic prompt 数据源**：`recent-prompts.ts` 查 `mcp.tool_calls` 表过去 30
  天 user_prompt 频次 top 5；查询走 IPC 不直连 DB
- **status bar 数据累计**：cost / latency / tokens 从 ws chunk 的 usage 字段累
  加；session 切换时归零
- **设计 token 应用一致性**：先切片 1 把 tokens 立完，后续切片所有新组件强制
  引用 `COLORS.*` 而非 hardcode hex；防止后期色板碎片化

## 切片完成验收

每个切片 commit 前必跑：
1. `npm run dev` 起 Electron + Vite hot reload
2. 跑老板今天测过的 8 个 bug 复现路径（PG 密码 / claude.exe / playground race /
   migration / 空 session / 消息流 / Sidebar 折叠 / sidebar 工作台）确认无回归
3. 切片 3-6 各自跑 4 状态 UI 截图对照 wireframe
4. 切片 6 完成后跑 e2e（参考 W5-C playwright 脚本）跑通典型对话 "诊断 SKU-X"

最终交付：`omni Setup 0.2.0.exe` NSIS 安装包，老板装上直观感受 UI 差别。
