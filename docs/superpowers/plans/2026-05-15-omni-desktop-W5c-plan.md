# W5-C: omni-desktop Electron App (Gemini 风) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 omni agent chat 独立做成跨平台桌面 app（Electron + Gemini 风 UI），消除"先 docker compose + npm run dev 才能用"的启动门槛，享受系统托盘 / 全局快捷键 / 原生通知等桌面优势。

**Architecture:** 新建独立项目 `E:\agent\omni-desktop\`，Electron main process 复用 W5-B 后端逻辑（claude-runner / session-manager / history-reader / mcp-config / pg pool）+ 通过 contextBridge IPC 暴露给 renderer。Renderer process 用 Vite + React + Tailwind 自己跑（不寄 Next.js），Gemini 风 layout 全新（welcome screen + 居中对话流 + floating 输入框 + 折叠侧栏），底层 hook 和小组件直接从 W5-B 复制。omni docker stack（postgres / KE / hub / redis）不动，桌面 app 通过 localhost 直连。

**Tech Stack:** Electron 33+ / electron-builder 25+ / Vite 5+ (renderer dev) / React 19 / TypeScript 5 / Tailwind 3 / pg 8 / ioredis 5 / electron-store 10 (settings 持久化) / lucide-react / react-markdown / vitest / Playwright（保留 e2e 框架）

---

## 关键决策（11 个开放问题 reasonable call）

| # | 问题 | 决策 | 理由 |
|---|---|---|---|
| 1 | Electron 进程结构 | contextIsolation + preload 标准模式 | 最安全；renderer 跑 isolated context，preload 通过 contextBridge 暴露窄 API |
| 2 | 打包工具 | electron-builder | 生态最成熟，NSIS Win 安装器 / DMG Mac 一键 |
| 3 | IPC 范式 | `window.api.openSession(id)` promise-based + ipcMain.handle | renderer 不知 ipc 协议，preload 抽象成 typed API |
| 4 | PG 连接 | main process 直连 `pg` lib，renderer 不连 | 安全 + 性能；W5-B PG pool 完全复用 |
| 5 | Claude CLI 路径 | 自动 detect (PATH / 常见路径)，找不到 Settings 页手填 | 用户友好兜底 |
| 6 | Auto-update | 起步**不做**，后续加 electron-updater + GitHub release | YAGNI；本机自用，老板手动构建即可 |
| 7 | 代码签名 | 起步**不签**，老板点"仍要安装"确认 | 个人用免成本 |
| 8 | 配置存储 | electron-store（封装 `app.getPath('userData')`） | 简单 + JSON schema 验证 |
| 9 | 多窗口 | 起步单窗口，Cmd+N = 新 session 不是新窗口 | YAGNI |
| 10 | 离线模式 | 启动时检查 omni 后端，离线时 UI 仍可加载历史 jsonl | 老板偶尔离线用 |
| 11 | 打包平台优先级 | Win 优先，Mac 后续 | 老板用 Win 11 |

---

## File Structure

```
E:\agent\omni-desktop\                          # 新独立项目，独立 git repo
├── package.json
├── pnpm-lock.yaml (或 package-lock.json)
├── tsconfig.main.json                          # main process tsconfig (target: ES2022, module: commonjs)
├── tsconfig.renderer.json                      # renderer tsconfig (target: ES2022, module: esnext, jsx)
├── vite.config.ts                              # renderer dev server + build
├── tailwind.config.ts
├── postcss.config.js
├── electron-builder.json                       # 打包配置
├── .gitignore
├── README.md
├── LICENSE (MIT)
├── build/                                      # app icon / installer assets
│   ├── icon.ico                                # Win
│   ├── icon.icns                               # Mac
│   ├── icon.png                                # Linux fallback
│   └── installer-script.nsh                    # NSIS 自定义脚本（可选）
├── src/
│   ├── main/                                   # Electron main process
│   │   ├── main.ts                             # entry：app.whenReady + BrowserWindow
│   │   ├── window.ts                           # createMainWindow helper
│   │   ├── ipc-handler.ts                      # ipcMain.handle 接 IPC 请求（替代 W5-B ws-handler）
│   │   ├── pg-client.ts                        # PG Pool 单例
│   │   ├── redis-subscriber.ts                 # subscribe mcp.human_gates.new → emit to renderer
│   │   ├── claude-runner.ts                    # 100% 复用 W5-B
│   │   ├── session-manager.ts                  # 100% 复用 W5-B
│   │   ├── mcp-config.ts                       # 100% 复用 W5-B
│   │   ├── history-reader.ts                   # 100% 复用 W5-B
│   │   ├── claude-cli-detector.ts              # 自动 detect claude CLI 路径
│   │   ├── settings-store.ts                   # electron-store wrapper
│   │   ├── tray.ts                             # tray icon + menu
│   │   ├── shortcut.ts                         # globalShortcut Ctrl+Shift+Space
│   │   └── autostart.ts                        # 开机自启
│   ├── preload/
│   │   └── preload.ts                          # contextBridge.exposeInMainWorld('api', {...})
│   ├── shared/
│   │   ├── types.ts                            # 100% 复用 W5-B types
│   │   └── ipc-channels.ts                     # IPC channel 常量
│   └── renderer/                               # React UI
│       ├── index.html                          # Vite entry
│       ├── main.tsx                            # ReactDOM.createRoot
│       ├── App.tsx                             # 根组件
│       ├── styles/
│       │   ├── globals.css                     # Tailwind directives + 全局样式
│       │   └── gemini-tokens.css               # Gemini 风设计 token（CSS variables）
│       ├── lib/
│       │   ├── api.ts                          # window.api 类型化 wrapper
│       │   └── cn.ts                           # clsx + tailwind-merge
│       ├── hooks/
│       │   ├── useAgentChat.ts                 # 改造 W5-B：用 window.api 替代 WebSocket
│       │   ├── useNotification.ts              # 100% 复用 W5-B
│       │   ├── useDarkMode.ts                  # dark mode toggle + 持久化
│       │   └── useGreeting.ts                  # 早安/午安/晚安 based on hour
│       └── components/
│           ├── ChatLayout.tsx                  # 重写：Gemini 整体布局
│           ├── Sidebar.tsx                     # 重写：折叠侧栏 (hover 展开)
│           ├── MessageStream.tsx               # 重写：居中 + welcome screen
│           ├── WelcomeScreen.tsx               # 新：Hello + prompt suggestions
│           ├── InputBar.tsx                    # 重写：floating 底部
│           ├── Logo.tsx                        # 新：几何 logo SVG
│           ├── DarkModeToggle.tsx              # 新：dark mode 按钮
│           ├── SettingsPanel.tsx               # 新：claude CLI 路径 / shortcut 配置
│           ├── MessageBubble.tsx               # 95% 复用 W5-B + 改 Gemini 样式
│           ├── HumanGateCard.tsx               # 90% 复用 + 改样式
│           ├── ToolCallChip.tsx                # 95% 复用 + 改样式
│           ├── ToolResultCard.tsx              # 100% 复用
│           └── attachments/                    # 100% 复用 W5-B 4 文件
│               ├── ImageAttachment.tsx
│               ├── VideoAttachment.tsx
│               ├── MarkdownAttachment.tsx
│               └── JsonAttachment.tsx
└── tests/
    ├── unit/                                   # vitest
    │   ├── claude-cli-detector.test.ts
    │   ├── settings-store.test.ts
    │   ├── pg-client.test.ts
    │   └── useAgentChat.test.tsx
    └── e2e/                                    # Playwright (打开 dist build)
        └── smoke.spec.ts
```

omni-vibe 仓库的改动（一个收尾切片做）：

```
E:\agent\omni\frontend\src\components\app-sidebar.tsx   # 改 /chat 标签为"Agent 对话（Web 版）"
E:\agent\omni\README.md                                  # 加桌面 app 链接
```

---

## 切片 1: Electron 骨架 + IPC + 后端逻辑移植（2-3 天）

**目标：** 项目搭起来，main process 能 spawn Claude CLI，IPC 通信通，renderer 能调 `window.api` 拿到 session 列表。

### Task 1.1: 新建 omni-desktop 项目骨架

**Files:**
- Create: `E:\agent\omni-desktop\` (新目录)
- Create: `E:\agent\omni-desktop\package.json`
- Create: `E:\agent\omni-desktop\.gitignore`
- Create: `E:\agent\omni-desktop\README.md`

- [ ] **Step 1: 创建目录 + git init**

```bash
cd E:/agent
mkdir omni-desktop
cd omni-desktop
git init
git checkout -b main
```

- [ ] **Step 2: 写 package.json**

```json
{
  "name": "omni-desktop",
  "version": "0.1.0",
  "description": "omni agent chat desktop app (Electron + Gemini-style UI)",
  "main": "dist-main/main.js",
  "type": "module",
  "scripts": {
    "dev": "concurrently -k \"npm:dev:renderer\" \"wait-on tcp:5173 && npm:dev:main\"",
    "dev:renderer": "vite",
    "dev:main": "tsc -p tsconfig.main.json -w & electron .",
    "build": "npm run build:renderer && npm run build:main",
    "build:renderer": "vite build",
    "build:main": "tsc -p tsconfig.main.json",
    "build:preload": "tsc -p tsconfig.preload.json",
    "pack": "npm run build && electron-builder",
    "pack:win": "npm run build && electron-builder --win",
    "pack:mac": "npm run build && electron-builder --mac",
    "test:unit": "vitest run",
    "test:e2e": "playwright test",
    "lint": "eslint src --ext .ts,.tsx"
  },
  "keywords": ["omni", "agent", "claude", "electron"],
  "author": "252180478yark",
  "license": "MIT"
}
```

- [ ] **Step 3: 写 .gitignore**

```
node_modules/
dist/
dist-main/
dist-preload/
dist-renderer/
*.log
.DS_Store
Thumbs.db
.env
.env.local
release/
out/
```

- [ ] **Step 4: 写最小 README.md**

```markdown
# omni-desktop

omni agent chat 桌面 app（Electron + Gemini 风 UI）。

## 前置依赖

- 本机装 [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)
- omni 后端 docker stack 在跑（参考 omni-vibe README）

## 开发

```bash
npm install
npm run dev
```

## 打包

```bash
npm run pack:win    # Windows NSIS 安装器
npm run pack:mac    # Mac DMG
```

## 架构

详见 `docs/architecture.md`（暂未写）。
```

- [ ] **Step 5: Initial commit**

```bash
git add package.json .gitignore README.md
git commit -m "chore: init omni-desktop project skeleton"
```

---

### Task 1.2: 装依赖 + tsconfig 双份

**Files:**
- Modify: `E:\agent\omni-desktop\package.json` (deps)
- Create: `E:\agent\omni-desktop\tsconfig.main.json`
- Create: `E:\agent\omni-desktop\tsconfig.preload.json`
- Create: `E:\agent\omni-desktop\tsconfig.renderer.json`
- Create: `E:\agent\omni-desktop\tsconfig.json` (root with project references)

- [ ] **Step 1: 装运行时依赖**

```bash
cd E:/agent/omni-desktop
npm install electron@^33 react@^19 react-dom@^19 pg@^8 ioredis@^5 electron-store@^10 lucide-react@^0.460 react-markdown@^9 remark-gfm@^4 clsx tailwind-merge
```

- [ ] **Step 2: 装 dev 依赖**

```bash
npm install --save-dev typescript@^5 @types/react @types/react-dom @types/node @types/pg @types/electron electron-builder@^25 vite@^5 @vitejs/plugin-react@^4 tailwindcss@^3 postcss autoprefixer concurrently wait-on vitest happy-dom @testing-library/react @playwright/test eslint @typescript-eslint/parser @typescript-eslint/eslint-plugin tsx
```

- [ ] **Step 3: 写 tsconfig.main.json (main process: CJS)**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "commonjs",
    "moduleResolution": "node",
    "rootDir": "src",
    "outDir": "dist-main",
    "esModuleInterop": true,
    "strict": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmitOnError": true,
    "sourceMap": true,
    "declaration": false
  },
  "include": ["src/main/**/*", "src/shared/**/*"]
}
```

- [ ] **Step 4: 写 tsconfig.preload.json (preload: CJS)**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "commonjs",
    "moduleResolution": "node",
    "rootDir": "src",
    "outDir": "dist-preload",
    "esModuleInterop": true,
    "strict": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "noEmitOnError": true,
    "sourceMap": true
  },
  "include": ["src/preload/**/*", "src/shared/**/*"]
}
```

- [ ] **Step 5: 写 tsconfig.renderer.json (renderer: ESM + JSX)**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "rootDir": "src/renderer",
    "outDir": "dist-renderer-tsc",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "jsx": "react-jsx",
    "esModuleInterop": true,
    "strict": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "noEmit": true,
    "resolveJsonModule": true,
    "useDefineForClassFields": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/renderer/*"],
      "@shared/*": ["src/shared/*"]
    }
  },
  "include": ["src/renderer/**/*", "src/shared/**/*"]
}
```

- [ ] **Step 6: 写 root tsconfig.json (project references)**

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.main.json" },
    { "path": "./tsconfig.preload.json" },
    { "path": "./tsconfig.renderer.json" }
  ]
}
```

- [ ] **Step 7: 验证三份 tsconfig 都能 compile（空目录暂时）**

```bash
mkdir -p src/main src/preload src/renderer src/shared
# 空文件保证 tsc 不报"no input"
echo "export {}" > src/main/_placeholder.ts
echo "export {}" > src/preload/_placeholder.ts
echo "export {}" > src/renderer/_placeholder.ts
echo "export {}" > src/shared/_placeholder.ts
npx tsc -p tsconfig.main.json
npx tsc -p tsconfig.preload.json
npx tsc -p tsconfig.renderer.json
```

Expected: 三个 command 都 exit 0，无 error。

- [ ] **Step 8: Commit**

```bash
git add package.json package-lock.json tsconfig*.json src/
git commit -m "chore: add deps + tsconfig 双份 (main/preload/renderer)"
```

---

### Task 1.3: Vite renderer dev 配置

**Files:**
- Create: `E:\agent\omni-desktop\vite.config.ts`
- Create: `E:\agent\omni-desktop\src\renderer\index.html`
- Create: `E:\agent\omni-desktop\src\renderer\main.tsx`
- Create: `E:\agent\omni-desktop\src\renderer\App.tsx`
- Delete: `src/renderer/_placeholder.ts`

- [ ] **Step 1: 写 vite.config.ts**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  root: 'src/renderer',
  base: './',
  build: {
    outDir: '../../dist-renderer',
    emptyOutDir: true,
    sourcemap: true,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src/renderer'),
      '@shared': path.resolve(__dirname, 'src/shared'),
    },
  },
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
})
```

- [ ] **Step 2: 写 src/renderer/index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>omni</title>
  </head>
  <body class="bg-white">
    <div id="root"></div>
    <script type="module" src="./main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 3: 写 src/renderer/main.tsx**

```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App'
import './styles/globals.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

- [ ] **Step 4: 写 src/renderer/App.tsx (hello world)**

```tsx
export function App() {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <h1 className="text-2xl font-semibold text-slate-900">omni-desktop is alive</h1>
    </div>
  )
}
```

- [ ] **Step 5: 创建占位 globals.css**

`src/renderer/styles/globals.css`:
```css
/* tailwind directives 后续 task 加 */
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
```

- [ ] **Step 6: 删除 placeholder**

```bash
rm src/renderer/_placeholder.ts
```

- [ ] **Step 7: 跑 vite dev server**

```bash
npx vite --config vite.config.ts
```

打开 `http://localhost:5173`，应该看到"omni-desktop is alive"。Ctrl+C 停掉。

- [ ] **Step 8: Commit**

```bash
git add vite.config.ts src/renderer/ -u
git rm src/renderer/_placeholder.ts
git commit -m "feat(W5-C 切片 1.3): vite renderer dev + hello world react app"
```

---

### Task 1.4: Tailwind 配置 + Gemini 风 design tokens

**Files:**
- Create: `E:\agent\omni-desktop\tailwind.config.ts`
- Create: `E:\agent\omni-desktop\postcss.config.js`
- Modify: `src/renderer/styles/globals.css`
- Create: `src/renderer/styles/gemini-tokens.css`

- [ ] **Step 1: 写 tailwind.config.ts**

```typescript
import type { Config } from 'tailwindcss'

export default {
  content: ['./src/renderer/**/*.{ts,tsx,html}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        gemini: {
          'gradient-start': '#6366f1',
          'gradient-end': '#a855f7',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
      },
      animation: {
        'cursor-blink': 'cursor-blink 1s steps(2) infinite',
        'spinner-rotate': 'spin 1.2s linear infinite',
      },
      keyframes: {
        'cursor-blink': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
} satisfies Config
```

- [ ] **Step 2: 装 @tailwindcss/typography**

```bash
npm install --save-dev @tailwindcss/typography
```

- [ ] **Step 3: 写 postcss.config.js**

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

- [ ] **Step 4: 改 globals.css 加 tailwind directives**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@import './gemini-tokens.css';

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: theme('colors.white');
  color: theme('colors.slate.900');
}

.dark body {
  background: theme('colors.slate.900');
  color: theme('colors.slate.100');
}

/* 平滑滚动 */
* {
  scroll-behavior: smooth;
}

/* 选中文字色 */
::selection {
  background: theme('colors.indigo.200');
}
.dark ::selection {
  background: theme('colors.indigo.700');
}
```

- [ ] **Step 5: 写 gemini-tokens.css (设计 token)**

```css
/* Gemini 风设计 token — 用 CSS variables 方便 dark mode 切换 */
:root {
  --gemini-bg: 255 255 255;
  --gemini-bg-soft: 248 250 252;
  --gemini-text: 15 23 42;
  --gemini-text-soft: 100 116 139;
  --gemini-text-weak: 148 163 184;
  --gemini-border: 226 232 240;
  --gemini-accent-from: 99 102 241;
  --gemini-accent-to: 168 85 247;
  --gemini-card-bg: 255 255 255;
  --gemini-card-border: 226 232 240;
  --gemini-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1);
}

.dark {
  --gemini-bg: 15 23 42;
  --gemini-bg-soft: 30 41 59;
  --gemini-text: 241 245 249;
  --gemini-text-soft: 148 163 184;
  --gemini-text-weak: 100 116 139;
  --gemini-border: 51 65 85;
  --gemini-accent-from: 129 140 248;
  --gemini-accent-to: 196 181 253;
  --gemini-card-bg: 30 41 59;
  --gemini-card-border: 51 65 85;
  --gemini-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.4);
}

.bg-gemini { background-color: rgb(var(--gemini-bg)); }
.bg-gemini-soft { background-color: rgb(var(--gemini-bg-soft)); }
.text-gemini { color: rgb(var(--gemini-text)); }
.text-gemini-soft { color: rgb(var(--gemini-text-soft)); }
.text-gemini-weak { color: rgb(var(--gemini-text-weak)); }
.border-gemini { border-color: rgb(var(--gemini-border)); }
.bg-gemini-card { background-color: rgb(var(--gemini-card-bg)); }
.shadow-gemini { box-shadow: var(--gemini-shadow); }

.text-gemini-gradient {
  background: linear-gradient(135deg, rgb(var(--gemini-accent-from)), rgb(var(--gemini-accent-to)));
  background-clip: text;
  -webkit-background-clip: text;
  color: transparent;
}

.bg-gemini-gradient {
  background: linear-gradient(135deg, rgb(var(--gemini-accent-from)), rgb(var(--gemini-accent-to)));
}
```

- [ ] **Step 6: 改 App.tsx 用 Gemini 配色测试**

```tsx
export function App() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gemini">
      <h1 className="text-2xl font-semibold text-gemini-gradient">omni-desktop</h1>
    </div>
  )
}
```

- [ ] **Step 7: 跑 vite 看效果**

```bash
npx vite
# 打开 localhost:5173，应该看到渐变文字 "omni-desktop"
```

- [ ] **Step 8: Commit**

```bash
git add tailwind.config.ts postcss.config.js src/renderer/styles/ src/renderer/App.tsx package.json package-lock.json
git commit -m "feat(W5-C 切片 1.4): tailwind + Gemini 风 design tokens (dark mode ready)"
```

---

### Task 1.5: 复用 W5-B types 到 shared

**Files:**
- Create: `E:\agent\omni-desktop\src\shared\types.ts`
- Create: `E:\agent\omni-desktop\src\shared\ipc-channels.ts`
- Delete: `src/shared/_placeholder.ts`

- [ ] **Step 1: 从 W5-B 复制 types.ts**

复制 `E:\agent\omni\frontend\src\lib\agent-chat\types.ts` 完整内容到 `E:\agent\omni-desktop\src\shared\types.ts`，**一字不改**。源文件参考 W5-B Task 1.2。

参考完整内容（与 W5-B types.ts 一致）：

```typescript
// === Claude Code stream-json 输出的 4 类 chunk ===
export interface ClaudeStreamChunk {
  type: 'system' | 'assistant' | 'user' | 'result'
  message?: {
    id: string
    type: 'message'
    role: 'assistant' | 'user'
    content: Array<
      | { type: 'text'; text: string }
      | { type: 'thinking'; thinking: string }
      | { type: 'tool_use'; id: string; name: string; input: Record<string, unknown> }
      | { type: 'tool_result'; tool_use_id: string; content: string | Array<{ type: string; text?: string }>; is_error?: boolean }
    >
    stop_reason?: string
    usage?: { input_tokens: number; output_tokens: number }
  }
  result?: string
  is_error?: boolean
  duration_ms?: number
  num_turns?: number
  session_id?: string
  total_cost_usd?: number
}

export interface ChatMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'tool_call' | 'tool_result' | 'human_gate' | 'system'
  text?: string
  tool_name?: string
  tool_args?: Record<string, unknown>
  tool_use_id?: string
  tool_status?: 'pending' | 'completed' | 'error'
  attachments?: ChatAttachment[]
  raw_result?: unknown
  gate_short_id?: string
  gate_summary?: string
  gate_decision?: 'pending' | 'approved' | 'rejected'
  created_at: string
}

export interface ChatAttachment {
  type: 'image' | 'video' | 'markdown' | 'json' | 'table' | 'link'
  url?: string
  thumbnail_url?: string
  alt?: string
  markdown?: string
  data?: unknown
  href?: string
  label?: string
}

export interface SessionState {
  id: string
  claude_session_id: string
  title: string
  sku_id: string | null
  last_message_preview: string | null
  message_count: number
  status: 'active' | 'archived' | 'deleted'
  created_at: string
  updated_at: string
}

// === IPC 消息（替代 W5-B 的 WsClientMessage / WsServerMessage）===
// Renderer → Main (request/response via ipcMain.handle)
export interface IpcListSessionsArg {}
export interface IpcCreateSessionArg { title?: string; sku_id?: string }
export interface IpcGetSessionArg { id: string }
export interface IpcDeleteSessionArg { id: string }
export interface IpcUpdateSessionArg { id: string; title?: string; sku_id?: string }
export interface IpcOpenSessionArg { id: string }
export interface IpcSendPromptArg { session_id: string; prompt: string; attachments?: ChatAttachment[] }
export interface IpcCancelArg { session_id: string }
export interface IpcDecideGateArg { short_id: string; decision: 'approved' | 'rejected'; note?: string }
export interface IpcUploadFileArg { session_id: string; file: { name: string; type: string; data: ArrayBuffer } }

// Main → Renderer (push via webContents.send)
export type RendererPushEvent =
  | { kind: 'session_opened'; session: SessionState; history: ChatMessage[] }
  | { kind: 'chunk'; session_id: string; message: ChatMessage }
  | { kind: 'task_done'; session_id: string; duration_ms: number; total_cost_usd: number; tokens: { input: number; output: number } }
  | { kind: 'error'; session_id?: string; error: string; detail?: string }
  | { kind: 'human_gate_new'; session_id: string; gate: { short_id: string; summary: string; tool_name: string } }
```

- [ ] **Step 2: 写 ipc-channels.ts**

```typescript
// src/shared/ipc-channels.ts
// IPC channel 命名规范：<domain>:<action>
// invoke (request/response):
export const IPC_LIST_SESSIONS = 'sessions:list'
export const IPC_CREATE_SESSION = 'sessions:create'
export const IPC_GET_SESSION = 'sessions:get'
export const IPC_DELETE_SESSION = 'sessions:delete'
export const IPC_UPDATE_SESSION = 'sessions:update'
export const IPC_OPEN_SESSION = 'sessions:open'         // 启动 subprocess + 拉历史
export const IPC_SEND_PROMPT = 'chat:send_prompt'
export const IPC_CANCEL = 'chat:cancel'
export const IPC_DECIDE_GATE = 'chat:decide_gate'
export const IPC_UPLOAD_FILE = 'chat:upload_file'
export const IPC_GET_SETTINGS = 'settings:get'
export const IPC_UPDATE_SETTINGS = 'settings:update'
export const IPC_DETECT_CLAUDE = 'system:detect_claude'

// push (main → renderer):
export const IPC_PUSH_EVENT = 'renderer:push'
```

- [ ] **Step 3: 删除 shared placeholder**

```bash
rm src/shared/_placeholder.ts
```

- [ ] **Step 4: tsc verify**

```bash
npx tsc -p tsconfig.main.json
npx tsc -p tsconfig.renderer.json
```

Expected: 都 0 error。

- [ ] **Step 5: Commit**

```bash
git add src/shared/
git rm src/shared/_placeholder.ts
git commit -m "feat(W5-C 切片 1.5): shared types + IPC channel 常量"
```

---

### Task 1.6: 移植 W5-B mcp-config / history-reader / claude-runner / session-manager

**Files:**
- Create: `E:\agent\omni-desktop\src\main\mcp-config.ts`
- Create: `E:\agent\omni-desktop\src\main\claude-runner.ts`
- Create: `E:\agent\omni-desktop\src\main\session-manager.ts`
- Create: `E:\agent\omni-desktop\src\main\history-reader.ts`
- Delete: `src/main/_placeholder.ts`

- [ ] **Step 1: 复制 mcp-config.ts**

把 `E:\agent\omni\frontend\src\lib\agent-chat\mcp-config.ts` 完整内容复制到 `E:\agent\omni-desktop\src\main\mcp-config.ts`，**不改任何代码**（导入路径已经是 fs/os/path，跟 Electron main 兼容）。

```typescript
// src/main/mcp-config.ts (W5-B 100% 复用)
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

export function getOmniMcpUrl(): string {
  const base = process.env.OMNI_KE_URL || 'http://localhost:8002'
  return `${base.replace(/\/$/, '')}/mcp`
}

export interface McpConfig {
  mcpServers: Record<string, { type: 'http' | 'stdio'; url?: string; command?: string; args?: string[] }>
}

export function buildMcpConfig(): McpConfig {
  return {
    mcpServers: {
      omni: {
        type: 'http',
        url: getOmniMcpUrl(),
      },
    },
  }
}

export async function writeTempMcpConfig(sessionId: string): Promise<string> {
  const dir = path.join(os.homedir(), '.claude', '.tmp')
  await fs.mkdir(dir, { recursive: true })
  const file = path.join(dir, `mcp-${sessionId}.json`)
  await fs.writeFile(file, JSON.stringify(buildMcpConfig(), null, 2), 'utf8')
  return file
}

export async function cleanupTempMcpConfig(sessionId: string): Promise<void> {
  const file = path.join(os.homedir(), '.claude', '.tmp', `mcp-${sessionId}.json`)
  await fs.unlink(file).catch(() => undefined)
}
```

- [ ] **Step 2: 复制 claude-runner.ts**

把 `E:\agent\omni\frontend\src\lib\agent-chat\claude-runner.ts` 完整内容复制到 `E:\agent\omni-desktop\src\main\claude-runner.ts`。

把 import 改为：
```typescript
import type { ClaudeStreamChunk } from '@shared/types'
```

（其他逻辑保持原样）

注：tsconfig.main.json 加 paths 让 `@shared/*` 解析：

```json
// tsconfig.main.json
{
  "compilerOptions": {
    ...,
    "baseUrl": ".",
    "paths": {
      "@shared/*": ["src/shared/*"]
    }
  },
  ...
}
```

- [ ] **Step 3: 复制 history-reader.ts**

同样复制 `E:\agent\omni\frontend\src\lib\agent-chat\history-reader.ts` 内容到 main，types import 改 `@shared/types`。

- [ ] **Step 4: 复制 session-manager.ts**

同样复制，把 imports 调整：

```typescript
import { EventEmitter } from 'node:events'
import { cleanupTempMcpConfig } from './mcp-config'
import { startClaudeRunner, type ClaudeRunner, type SpawnOptions } from './claude-runner'
// rest unchanged
```

- [ ] **Step 5: 删除 main placeholder**

```bash
rm src/main/_placeholder.ts
```

- [ ] **Step 6: tsc verify**

```bash
npx tsc -p tsconfig.main.json
```

Expected: 0 error。

- [ ] **Step 7: Commit**

```bash
git add src/main/mcp-config.ts src/main/claude-runner.ts src/main/history-reader.ts src/main/session-manager.ts tsconfig.main.json
git rm src/main/_placeholder.ts
git commit -m "feat(W5-C 切片 1.6): 移植 W5-B mcp-config / claude-runner / history-reader / session-manager 到 main"
```

---

### Task 1.7: pg-client main process 单例

**Files:**
- Create: `E:\agent\omni-desktop\src\main\pg-client.ts`

- [ ] **Step 1: 写 pg-client.ts**

```typescript
// src/main/pg-client.ts
import { Pool, type PoolClient } from 'pg'

let _pool: Pool | null = null

export function getPgPool(): Pool {
  if (!_pool) {
    _pool = new Pool({
      host: process.env.PGHOST || 'localhost',
      port: parseInt(process.env.PGPORT || '5432'),
      user: process.env.PGUSER || 'omni_user',
      password: process.env.PGPASSWORD || 'omni_pass',
      database: process.env.PGDATABASE || 'omni_vibe_db',
      max: 5,
      idleTimeoutMillis: 30000,
    })
    _pool.on('error', (err) => {
      // eslint-disable-next-line no-console
      console.error('[pg] pool error:', err)
    })
  }
  return _pool
}

export async function endPgPool(): Promise<void> {
  if (_pool) {
    await _pool.end()
    _pool = null
  }
}

export async function withClient<T>(fn: (client: PoolClient) => Promise<T>): Promise<T> {
  const client = await getPgPool().connect()
  try {
    return await fn(client)
  } finally {
    client.release()
  }
}
```

- [ ] **Step 2: tsc verify**

```bash
npx tsc -p tsconfig.main.json
```

- [ ] **Step 3: Commit**

```bash
git add src/main/pg-client.ts
git commit -m "feat(W5-C 切片 1.7): pg-client main process pool 单例"
```

---

### Task 1.8: claude-cli-detector

**Files:**
- Create: `E:\agent\omni-desktop\src\main\claude-cli-detector.ts`
- Create: `E:\agent\omni-desktop\tests\unit\claude-cli-detector.test.ts`

- [ ] **Step 1: 写测试**

```typescript
// tests/unit/claude-cli-detector.test.ts
import { describe, it, expect } from 'vitest'
import { getDefaultCandidates, isWindows } from '@/main/claude-cli-detector'

describe('claude-cli-detector', () => {
  it('returns Windows candidates on win32', () => {
    if (!isWindows()) return // skip on non-win
    const list = getDefaultCandidates()
    expect(list.some((p) => p.endsWith('claude.cmd'))).toBe(true)
  })

  it('returns unix candidates on non-win', () => {
    if (isWindows()) return
    const list = getDefaultCandidates()
    expect(list.some((p) => p.endsWith('claude'))).toBe(true)
  })
})
```

注：vitest config 需要解析 `@/main/*` → `src/main/*`。下个 step 加 vitest.config.ts。

- [ ] **Step 2: 写 vitest.config.ts**

```typescript
// vitest.config.ts
import { defineConfig } from 'vitest/config'
import path from 'node:path'

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      '@shared': path.resolve(__dirname, 'src/shared'),
    },
  },
  test: {
    environment: 'node',
  },
})
```

- [ ] **Step 3: 跑测试看失败**

```bash
npx vitest run tests/unit/claude-cli-detector.test.ts
```

Expected: FAIL (module not found)

- [ ] **Step 4: 写实现**

```typescript
// src/main/claude-cli-detector.ts
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { spawn } from 'node:child_process'

export function isWindows(): boolean {
  return process.platform === 'win32'
}

/**
 * 返回当前平台的 claude CLI 候选路径列表（按优先级）
 */
export function getDefaultCandidates(): string[] {
  const home = os.homedir()
  if (isWindows()) {
    return [
      path.join(home, 'AppData', 'Roaming', 'npm', 'claude.cmd'),
      path.join(home, '.npm-global', 'claude.cmd'),
      'C:\\Program Files\\nodejs\\claude.cmd',
      'claude.cmd', // 走 PATH
    ]
  }
  return [
    path.join(home, '.npm-global', 'bin', 'claude'),
    path.join(home, '.local', 'bin', 'claude'),
    '/usr/local/bin/claude',
    '/opt/homebrew/bin/claude',
    'claude', // 走 PATH
  ]
}

/**
 * 找到第一个真实存在 + 可执行的 claude CLI 路径，找不到返 null
 */
export async function detectClaudeCli(extra: string[] = []): Promise<string | null> {
  const candidates = [...extra, ...getDefaultCandidates()]
  for (const candidate of candidates) {
    if (candidate.includes(path.sep) || candidate.includes('/')) {
      // 绝对路径
      try {
        await fs.access(candidate)
        return candidate
      } catch {
        continue
      }
    } else {
      // PATH 上的名字，spawn 验证
      const ok = await trySpawnVersion(candidate)
      if (ok) return candidate
    }
  }
  return null
}

function trySpawnVersion(cmd: string): Promise<boolean> {
  return new Promise((resolve) => {
    try {
      const proc = spawn(cmd, ['--version'], {
        shell: isWindows(),
        stdio: 'ignore',
      })
      proc.on('exit', (code) => resolve(code === 0))
      proc.on('error', () => resolve(false))
      setTimeout(() => {
        proc.kill()
        resolve(false)
      }, 3000)
    } catch {
      resolve(false)
    }
  })
}
```

- [ ] **Step 5: 跑测试看通过**

```bash
npx vitest run tests/unit/claude-cli-detector.test.ts
```

Expected: PASS (2 tests, 1 effective on current platform + 1 skip)

- [ ] **Step 6: Commit**

```bash
git add src/main/claude-cli-detector.ts tests/unit/claude-cli-detector.test.ts vitest.config.ts
git commit -m "feat(W5-C 切片 1.8): 自动 detect claude CLI 路径 (Win + Unix candidates)"
```

---

### Task 1.9: settings-store (electron-store)

**Files:**
- Create: `E:\agent\omni-desktop\src\main\settings-store.ts`

- [ ] **Step 1: 写 settings-store.ts**

```typescript
// src/main/settings-store.ts
import Store from 'electron-store'

export interface AppSettings {
  claudeCliPath: string | null      // null 表示自动 detect
  globalShortcut: string             // 默认 'CommandOrControl+Shift+Space'
  autoStart: boolean                 // 开机自启
  theme: 'light' | 'dark' | 'system' // dark mode
  omniKeUrl: string                  // 默认 http://localhost:8002
  omniPgUrl: string                  // 默认 postgresql://omni_user:omni_pass@localhost:5432/omni_vibe_db
  omniRedisUrl: string               // 默认 redis://:changeme_redis@localhost:6379/1
  username: string                   // welcome 屏显示 "Hello, [name]"
}

const defaults: AppSettings = {
  claudeCliPath: null,
  globalShortcut: 'CommandOrControl+Shift+Space',
  autoStart: false,
  theme: 'system',
  omniKeUrl: 'http://localhost:8002',
  omniPgUrl: 'postgresql://omni_user:omni_pass@localhost:5432/omni_vibe_db',
  omniRedisUrl: 'redis://:changeme_redis@localhost:6379/1',
  username: 'Boss',
}

let _store: Store<AppSettings> | null = null

export function getSettingsStore(): Store<AppSettings> {
  if (!_store) {
    _store = new Store<AppSettings>({
      defaults,
      name: 'settings',
    })
  }
  return _store
}

export function getSettings(): AppSettings {
  const store = getSettingsStore()
  return {
    claudeCliPath: store.get('claudeCliPath'),
    globalShortcut: store.get('globalShortcut'),
    autoStart: store.get('autoStart'),
    theme: store.get('theme'),
    omniKeUrl: store.get('omniKeUrl'),
    omniPgUrl: store.get('omniPgUrl'),
    omniRedisUrl: store.get('omniRedisUrl'),
    username: store.get('username'),
  }
}

export function updateSettings(patch: Partial<AppSettings>): AppSettings {
  const store = getSettingsStore()
  for (const [k, v] of Object.entries(patch)) {
    store.set(k as keyof AppSettings, v as never)
  }
  return getSettings()
}
```

- [ ] **Step 2: tsc verify**

```bash
npx tsc -p tsconfig.main.json
```

- [ ] **Step 3: Commit**

```bash
git add src/main/settings-store.ts
git commit -m "feat(W5-C 切片 1.9): settings-store (electron-store) for claude path / shortcut / theme"
```

---

### Task 1.10: redis-subscriber main process

**Files:**
- Create: `E:\agent\omni-desktop\src\main\redis-subscriber.ts`

- [ ] **Step 1: 写 redis-subscriber.ts**

```typescript
// src/main/redis-subscriber.ts
import Redis from 'ioredis'
import { getSettings } from './settings-store'

type HumanGateNewHandler = (gate: { short_id: string; tool_name: string; summary: string }) => void

let _sub: Redis | null = null
const _handlers = new Set<HumanGateNewHandler>()

export function startRedisSubscriber(): void {
  if (_sub) return
  const url = getSettings().omniRedisUrl
  try {
    _sub = new Redis(url, { lazyConnect: false, maxRetriesPerRequest: 3 })
    _sub.subscribe('mcp.human_gates.new').catch((e) => {
      // eslint-disable-next-line no-console
      console.warn('[redis] subscribe failed:', e)
    })
    _sub.on('message', (channel, payload) => {
      if (channel !== 'mcp.human_gates.new') return
      try {
        const gate = JSON.parse(payload) as { short_id: string; tool_name: string; summary: string }
        for (const h of _handlers) {
          try { h(gate) } catch { /* swallow */ }
        }
      } catch {
        /* swallow */
      }
    })
    _sub.on('error', (e) => {
      // eslint-disable-next-line no-console
      console.warn('[redis] error:', e.message)
    })
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('[redis] init failed:', e)
    _sub = null
  }
}

export function onHumanGateNew(handler: HumanGateNewHandler): () => void {
  _handlers.add(handler)
  return () => _handlers.delete(handler)
}

export async function stopRedisSubscriber(): Promise<void> {
  if (_sub) {
    await _sub.quit().catch(() => undefined)
    _sub = null
  }
  _handlers.clear()
}
```

- [ ] **Step 2: tsc verify**

```bash
npx tsc -p tsconfig.main.json
```

- [ ] **Step 3: Commit**

```bash
git add src/main/redis-subscriber.ts
git commit -m "feat(W5-C 切片 1.10): redis-subscriber for human_gate notifications"
```

---

### Task 1.11: ipc-handler (替代 W5-B ws-handler)

**Files:**
- Create: `E:\agent\omni-desktop\src\main\ipc-handler.ts`

- [ ] **Step 1: 写 ipc-handler.ts**

```typescript
// src/main/ipc-handler.ts
import { ipcMain, type WebContents, BrowserWindow } from 'electron'
import crypto from 'node:crypto'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs/promises'
import {
  IPC_LIST_SESSIONS,
  IPC_CREATE_SESSION,
  IPC_GET_SESSION,
  IPC_DELETE_SESSION,
  IPC_UPDATE_SESSION,
  IPC_OPEN_SESSION,
  IPC_SEND_PROMPT,
  IPC_CANCEL,
  IPC_DECIDE_GATE,
  IPC_UPLOAD_FILE,
  IPC_GET_SETTINGS,
  IPC_UPDATE_SETTINGS,
  IPC_DETECT_CLAUDE,
  IPC_PUSH_EVENT,
} from '@shared/ipc-channels'
import type {
  IpcListSessionsArg, IpcCreateSessionArg, IpcGetSessionArg, IpcDeleteSessionArg,
  IpcUpdateSessionArg, IpcOpenSessionArg, IpcSendPromptArg, IpcCancelArg,
  IpcDecideGateArg, IpcUploadFileArg,
  SessionState, ChatMessage, ChatAttachment, ClaudeStreamChunk,
  RendererPushEvent,
} from '@shared/types'
import { getPgPool } from './pg-client'
import { writeTempMcpConfig } from './mcp-config'
import { readSessionHistory, encodeProjectDir } from './history-reader'
import { getSessionManager } from './session-manager'
import { onHumanGateNew } from './redis-subscriber'
import { getSettings, updateSettings, type AppSettings } from './settings-store'
import { detectClaudeCli } from './claude-cli-detector'

function pushToAllRenderers(event: RendererPushEvent): void {
  for (const win of BrowserWindow.getAllWindows()) {
    try {
      win.webContents.send(IPC_PUSH_EVENT, event)
    } catch { /* swallow */ }
  }
}

function chunkToMessages(chunk: ClaudeStreamChunk): ChatMessage[] {
  const out: ChatMessage[] = []
  const sessionId = chunk.session_id || ''
  const createdAt = new Date().toISOString()
  if (chunk.type === 'assistant' && chunk.message) {
    for (const block of chunk.message.content) {
      if (block.type === 'text') {
        out.push({
          id: `${chunk.message.id}-text-${out.length}`,
          session_id: sessionId,
          role: 'assistant',
          text: block.text,
          created_at: createdAt,
        })
      } else if (block.type === 'tool_use') {
        out.push({
          id: `${block.id}-call`,
          session_id: sessionId,
          role: 'tool_call',
          tool_name: block.name,
          tool_args: block.input,
          tool_use_id: block.id,
          tool_status: 'pending',
          created_at: createdAt,
        })
      }
    }
  } else if (chunk.type === 'user' && chunk.message) {
    for (const block of chunk.message.content) {
      if (block.type === 'tool_result') {
        out.push({
          id: `${block.tool_use_id}-result`,
          session_id: sessionId,
          role: 'tool_result',
          tool_use_id: block.tool_use_id,
          raw_result: block.content,
          attachments: extractAttachmentsFromResult(block.content),
          created_at: createdAt,
        })
      }
    }
  }
  return out
}

function extractAttachmentsFromResult(content: unknown): ChatAttachment[] {
  if (typeof content !== 'string') return []
  let parsed: unknown
  try { parsed = JSON.parse(content) } catch { return [] }
  if (typeof parsed !== 'object' || parsed === null) return []
  const obj = parsed as Record<string, unknown>
  const out: ChatAttachment[] = []
  const handleUrls = (val: unknown, type: 'image' | 'video') => {
    if (typeof val === 'string') out.push({ type, url: val })
    else if (Array.isArray(val)) {
      for (const v of val) {
        if (typeof v === 'string') out.push({ type, url: v })
        else if (typeof v === 'object' && v !== null && 'url' in v) {
          const u = (v as { url: unknown }).url
          if (typeof u === 'string') out.push({ type, url: u })
        }
      }
    }
  }
  if ('image_url' in obj) handleUrls(obj.image_url, 'image')
  if ('image_urls' in obj) handleUrls(obj.image_urls, 'image')
  if ('video_url' in obj) handleUrls(obj.video_url, 'video')
  if ('video_urls' in obj) handleUrls(obj.video_urls, 'video')
  if ('markdown' in obj && typeof obj.markdown === 'string') {
    out.push({ type: 'markdown', markdown: obj.markdown })
  }
  if ('script_md' in obj && typeof obj.script_md === 'string') {
    out.push({ type: 'markdown', markdown: obj.script_md })
  }
  return out
}

export function registerIpcHandlers(): void {
  const pool = getPgPool()
  const mgr = getSessionManager()

  // Redis pub/sub → push to renderers
  onHumanGateNew((gate) => {
    pushToAllRenderers({
      kind: 'human_gate_new',
      session_id: '',
      gate,
    })
  })

  // sessions:list
  ipcMain.handle(IPC_LIST_SESSIONS, async (_e, _arg: IpcListSessionsArg) => {
    const r = await pool.query(
      `SELECT id, claude_session_id, title, sku_id, last_message_preview, message_count, status, created_at, updated_at
         FROM mcp.agent_sessions
        WHERE status != 'deleted'
        ORDER BY updated_at DESC
        LIMIT 100`,
    )
    return r.rows
  })

  // sessions:create
  ipcMain.handle(IPC_CREATE_SESSION, async (_e, arg: IpcCreateSessionArg) => {
    const claudeSessionId = crypto.randomUUID()
    const r = await pool.query(
      `INSERT INTO mcp.agent_sessions (claude_session_id, title, sku_id)
       VALUES ($1, $2, $3) RETURNING *`,
      [claudeSessionId, arg.title || '新对话', arg.sku_id || null],
    )
    return r.rows[0]
  })

  // sessions:get
  ipcMain.handle(IPC_GET_SESSION, async (_e, arg: IpcGetSessionArg) => {
    const r = await pool.query(`SELECT * FROM mcp.agent_sessions WHERE id = $1`, [arg.id])
    if (r.rowCount === 0) throw new Error('not_found')
    return r.rows[0]
  })

  // sessions:delete (soft)
  ipcMain.handle(IPC_DELETE_SESSION, async (_e, arg: IpcDeleteSessionArg) => {
    await pool.query(`UPDATE mcp.agent_sessions SET status = 'deleted', updated_at = NOW() WHERE id = $1`, [arg.id])
    return { success: true }
  })

  // sessions:update
  ipcMain.handle(IPC_UPDATE_SESSION, async (_e, arg: IpcUpdateSessionArg) => {
    const r = await pool.query(
      `UPDATE mcp.agent_sessions
          SET title = COALESCE($2, title),
              sku_id = COALESCE($3, sku_id),
              updated_at = NOW()
        WHERE id = $1
        RETURNING *`,
      [arg.id, arg.title || null, arg.sku_id || null],
    )
    if (r.rowCount === 0) throw new Error('not_found')
    return r.rows[0]
  })

  // sessions:open → 拉 session + history，准备好 mcp config
  ipcMain.handle(IPC_OPEN_SESSION, async (_e, arg: IpcOpenSessionArg) => {
    const r = await pool.query<{
      id: string; claude_session_id: string; title: string; sku_id: string | null
      status: string; created_at: Date; updated_at: Date; message_count: number; last_message_preview: string | null
    }>(
      `SELECT id, claude_session_id, title, sku_id, status, created_at, updated_at, message_count, last_message_preview
         FROM mcp.agent_sessions WHERE id = $1`,
      [arg.id],
    )
    if (r.rowCount === 0) throw new Error('session_not_found')
    const row = r.rows[0]
    const mcpConfigPath = await writeTempMcpConfig(arg.id)
    const sess = mgr.open(arg.id, { mcpConfigPath })
    sess.claudeSessionId = row.claude_session_id
    const projectDir = process.env.OMNI_PROJECT_DIR || process.cwd()
    const sessionsDir = path.join(os.homedir(), '.claude', 'projects', encodeProjectDir(projectDir))
    const jsonlPath = path.join(sessionsDir, `${row.claude_session_id}.jsonl`)
    const history = await readSessionHistory(jsonlPath)
    const session: SessionState = {
      id: row.id,
      claude_session_id: row.claude_session_id,
      title: row.title,
      sku_id: row.sku_id,
      last_message_preview: row.last_message_preview,
      message_count: row.message_count,
      status: row.status as 'active' | 'archived' | 'deleted',
      created_at: row.created_at.toISOString(),
      updated_at: row.updated_at.toISOString(),
    }
    return { session, history }
  })

  // chat:send_prompt
  ipcMain.handle(IPC_SEND_PROMPT, async (_e, arg: IpcSendPromptArg) => {
    if (!mgr.has(arg.session_id)) throw new Error('session_not_open')
    const runner = mgr.spawn(arg.session_id, arg.prompt)
    runner.on('chunk', (chunk: ClaudeStreamChunk) => {
      const msgs = chunkToMessages(chunk)
      for (const m of msgs) {
        pushToAllRenderers({ kind: 'chunk', session_id: arg.session_id, message: m })
      }
      if (chunk.type === 'result') {
        const usage = chunk.message?.usage
        pushToAllRenderers({
          kind: 'task_done',
          session_id: arg.session_id,
          duration_ms: chunk.duration_ms || 0,
          total_cost_usd: chunk.total_cost_usd || 0,
          tokens: { input: usage?.input_tokens || 0, output: usage?.output_tokens || 0 },
        })
        updateSessionStats(arg.session_id, chunk).catch(() => undefined)
      }
    })
    runner.on('stderr', (data: string) => {
      // eslint-disable-next-line no-console
      console.error(`[claude-stderr ${arg.session_id}]`, data)
    })
    runner.on('error', (err: Error) => {
      pushToAllRenderers({
        kind: 'error', session_id: arg.session_id, error: 'runner_error', detail: err.message,
      })
    })
    return { ok: true }
  })

  // chat:cancel
  ipcMain.handle(IPC_CANCEL, async (_e, arg: IpcCancelArg) => {
    const sess = mgr.get(arg.session_id)
    if (sess?.runner) sess.runner.cancel()
    return { ok: true }
  })

  // chat:decide_gate → 调 KE HTTP endpoint
  ipcMain.handle(IPC_DECIDE_GATE, async (_e, arg: IpcDecideGateArg) => {
    const base = getSettings().omniKeUrl
    const resp = await fetch(`${base}/api/v1/mcp/human-gates/${arg.short_id}/${arg.decision}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: arg.note || '' }),
    })
    if (!resp.ok) {
      const text = await resp.text()
      throw new Error(`gate_decide_failed: ${text}`)
    }
    return { ok: true }
  })

  // chat:upload_file → 保存到 omni data/uploads + 返 url
  ipcMain.handle(IPC_UPLOAD_FILE, async (_e, arg: IpcUploadFileArg) => {
    const uploadBase = process.env.OMNI_UPLOAD_BASE || path.join(os.homedir(), '.omni-desktop', 'uploads')
    const dir = path.join(uploadBase, arg.session_id)
    await fs.mkdir(dir, { recursive: true })
    const ext = path.extname(arg.file.name) || '.bin'
    const uuid = crypto.randomUUID()
    const target = path.join(dir, `${uuid}${ext}`)
    await fs.writeFile(target, Buffer.from(arg.file.data))
    const url = `file://${target.replace(/\\/g, '/')}`
    return { url, filename: arg.file.name, size: arg.file.data.byteLength, mime: arg.file.type }
  })

  // settings:get / update
  ipcMain.handle(IPC_GET_SETTINGS, async () => getSettings())
  ipcMain.handle(IPC_UPDATE_SETTINGS, async (_e, patch: Partial<AppSettings>) => updateSettings(patch))

  // system:detect_claude
  ipcMain.handle(IPC_DETECT_CLAUDE, async () => {
    const extra = getSettings().claudeCliPath ? [getSettings().claudeCliPath!] : []
    return await detectClaudeCli(extra)
  })
}

async function updateSessionStats(sessionId: string, chunk: ClaudeStreamChunk): Promise<void> {
  const usage = chunk.message?.usage
  const pool = getPgPool()
  await pool.query(
    `UPDATE mcp.agent_sessions
        SET tokens_input_total = tokens_input_total + $1,
            tokens_output_total = tokens_output_total + $2,
            message_count = message_count + COALESCE($3, 0),
            updated_at = NOW()
      WHERE id = $4`,
    [usage?.input_tokens || 0, usage?.output_tokens || 0, chunk.num_turns || 0, sessionId],
  )
}
```

- [ ] **Step 2: tsc verify**

```bash
npx tsc -p tsconfig.main.json
```

Expected: 0 error

- [ ] **Step 3: Commit**

```bash
git add src/main/ipc-handler.ts
git commit -m "feat(W5-C 切片 1.11): ipc-handler 替代 W5-B ws-handler (ipcMain.handle + push events)"
```

---

### Task 1.12: window.ts + main.ts entry

**Files:**
- Create: `E:\agent\omni-desktop\src\main\window.ts`
- Create: `E:\agent\omni-desktop\src\main\main.ts`

- [ ] **Step 1: 写 window.ts**

```typescript
// src/main/window.ts
import { BrowserWindow, app } from 'electron'
import path from 'node:path'

const isDev = !app.isPackaged
const RENDERER_DEV_URL = 'http://localhost:5173'

export function createMainWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    backgroundColor: '#ffffff',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false, // preload 要用 ipcRenderer
    },
  })

  win.once('ready-to-show', () => win.show())

  if (isDev) {
    win.loadURL(RENDERER_DEV_URL)
    win.webContents.openDevTools({ mode: 'detach' })
  } else {
    win.loadFile(path.join(__dirname, '../renderer/index.html'))
  }

  return win
}
```

- [ ] **Step 2: 写 main.ts**

```typescript
// src/main/main.ts
import { app, BrowserWindow } from 'electron'
import { createMainWindow } from './window'
import { registerIpcHandlers } from './ipc-handler'
import { startRedisSubscriber, stopRedisSubscriber } from './redis-subscriber'
import { endPgPool } from './pg-client'

// 单实例 lock（多次双击 app 只起一个窗口）
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const wins = BrowserWindow.getAllWindows()
    if (wins.length > 0) {
      const win = wins[0]
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })

  app.whenReady().then(() => {
    registerIpcHandlers()
    startRedisSubscriber()
    createMainWindow()

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createMainWindow()
    })
  })

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })

  app.on('before-quit', async () => {
    await stopRedisSubscriber()
    await endPgPool()
  })
}
```

- [ ] **Step 3: tsc verify**

```bash
npx tsc -p tsconfig.main.json
```

Expected: 0 error

- [ ] **Step 4: Commit**

```bash
git add src/main/window.ts src/main/main.ts
git commit -m "feat(W5-C 切片 1.12): Electron main entry + BrowserWindow creation"
```

---

### Task 1.13: preload.ts contextBridge API

**Files:**
- Create: `E:\agent\omni-desktop\src\preload\preload.ts`
- Delete: `src/preload/_placeholder.ts`

- [ ] **Step 1: 写 preload.ts**

```typescript
// src/preload/preload.ts
import { contextBridge, ipcRenderer } from 'electron'
import {
  IPC_LIST_SESSIONS,
  IPC_CREATE_SESSION,
  IPC_GET_SESSION,
  IPC_DELETE_SESSION,
  IPC_UPDATE_SESSION,
  IPC_OPEN_SESSION,
  IPC_SEND_PROMPT,
  IPC_CANCEL,
  IPC_DECIDE_GATE,
  IPC_UPLOAD_FILE,
  IPC_GET_SETTINGS,
  IPC_UPDATE_SETTINGS,
  IPC_DETECT_CLAUDE,
  IPC_PUSH_EVENT,
} from '@shared/ipc-channels'
import type {
  SessionState, ChatMessage, ChatAttachment, RendererPushEvent,
  IpcCreateSessionArg, IpcUpdateSessionArg, IpcSendPromptArg,
  IpcDecideGateArg, IpcUploadFileArg,
} from '@shared/types'
import type { AppSettings } from '@shared/types' // 注：AppSettings 应该也搬到 shared，下个 step 处理

const api = {
  listSessions: (): Promise<SessionState[]> => ipcRenderer.invoke(IPC_LIST_SESSIONS, {}),
  createSession: (arg: IpcCreateSessionArg): Promise<SessionState> => ipcRenderer.invoke(IPC_CREATE_SESSION, arg),
  getSession: (id: string): Promise<SessionState> => ipcRenderer.invoke(IPC_GET_SESSION, { id }),
  deleteSession: (id: string): Promise<{ success: boolean }> => ipcRenderer.invoke(IPC_DELETE_SESSION, { id }),
  updateSession: (arg: IpcUpdateSessionArg): Promise<SessionState> => ipcRenderer.invoke(IPC_UPDATE_SESSION, arg),
  openSession: (id: string): Promise<{ session: SessionState; history: ChatMessage[] }> =>
    ipcRenderer.invoke(IPC_OPEN_SESSION, { id }),
  sendPrompt: (arg: IpcSendPromptArg): Promise<{ ok: boolean }> => ipcRenderer.invoke(IPC_SEND_PROMPT, arg),
  cancel: (sessionId: string): Promise<{ ok: boolean }> => ipcRenderer.invoke(IPC_CANCEL, { session_id: sessionId }),
  decideGate: (arg: IpcDecideGateArg): Promise<{ ok: boolean }> => ipcRenderer.invoke(IPC_DECIDE_GATE, arg),
  uploadFile: (arg: IpcUploadFileArg): Promise<{ url: string; filename: string; size: number; mime: string }> =>
    ipcRenderer.invoke(IPC_UPLOAD_FILE, arg),
  getSettings: (): Promise<AppSettings> => ipcRenderer.invoke(IPC_GET_SETTINGS),
  updateSettings: (patch: Partial<AppSettings>): Promise<AppSettings> => ipcRenderer.invoke(IPC_UPDATE_SETTINGS, patch),
  detectClaude: (): Promise<string | null> => ipcRenderer.invoke(IPC_DETECT_CLAUDE),
  onPush: (handler: (event: RendererPushEvent) => void): (() => void) => {
    const listener = (_e: unknown, event: RendererPushEvent) => handler(event)
    ipcRenderer.on(IPC_PUSH_EVENT, listener)
    return () => ipcRenderer.removeListener(IPC_PUSH_EVENT, listener)
  },
}

contextBridge.exposeInMainWorld('api', api)

export type OmniDesktopApi = typeof api
```

- [ ] **Step 2: 把 AppSettings 类型挪到 shared**

把 `src/main/settings-store.ts` 中的 `AppSettings` interface 复制到 `src/shared/types.ts`，然后 `settings-store.ts` 改成 `import type { AppSettings } from '@shared/types'`：

```typescript
// src/shared/types.ts 末尾追加：
export interface AppSettings {
  claudeCliPath: string | null
  globalShortcut: string
  autoStart: boolean
  theme: 'light' | 'dark' | 'system'
  omniKeUrl: string
  omniPgUrl: string
  omniRedisUrl: string
  username: string
}
```

`src/main/settings-store.ts` 顶部加 `import type { AppSettings } from '@shared/types'`，删除文件内的 `export interface AppSettings { ... }`。

- [ ] **Step 3: 删除 preload placeholder**

```bash
rm src/preload/_placeholder.ts
```

- [ ] **Step 4: tsc verify**

```bash
npx tsc -p tsconfig.preload.json
npx tsc -p tsconfig.main.json
```

Both should 0 error.

- [ ] **Step 5: 加 renderer 类型声明**

`src/renderer/global.d.ts`:
```typescript
import type { OmniDesktopApi } from '../preload/preload'

declare global {
  interface Window {
    api: OmniDesktopApi
  }
}

export {}
```

- [ ] **Step 6: Commit**

```bash
git add src/preload/preload.ts src/shared/types.ts src/main/settings-store.ts src/renderer/global.d.ts
git rm src/preload/_placeholder.ts
git commit -m "feat(W5-C 切片 1.13): preload contextBridge API + renderer global.d.ts types"
```

---

### Task 1.14: 跑通 dev mode

**Files:** 改 package.json dev script + verify

- [ ] **Step 1: 改 dev script 简化版**

```json
{
  "scripts": {
    "dev": "concurrently -k \"vite\" \"wait-on tcp:5173 && npm run dev:main\"",
    "dev:main": "npm run build:main && npm run build:preload && electron .",
    "build:main": "tsc -p tsconfig.main.json",
    "build:preload": "tsc -p tsconfig.preload.json"
  }
}
```

注意：dev:main 当前是 tsc 编译后 electron 一次性启动，不 watch。后续可以加 chokidar 重启。起步 manually restart 已够用。

- [ ] **Step 2: dev 跑通 smoke test**

```bash
cd E:/agent/omni-desktop
npm run dev
```

Expected:
- vite 起 http://localhost:5173
- tsc 编译 main + preload
- electron 弹一个窗口，标题"omni"，显示渐变文字"omni-desktop"

如果失败：根据 console error 排查（preload 路径 / IPC 注册 / pg 连接等）。

- [ ] **Step 3: 跳一次小测试 — 在 App.tsx 加按钮调 listSessions**

临时改 App.tsx：

```tsx
import { useEffect, useState } from 'react'

export function App() {
  const [count, setCount] = useState<number | null>(null)
  useEffect(() => {
    window.api.listSessions().then((arr) => setCount(arr.length)).catch(() => setCount(-1))
  }, [])
  return (
    <div className="min-h-screen flex items-center justify-center bg-gemini">
      <div>
        <h1 className="text-2xl font-semibold text-gemini-gradient">omni-desktop</h1>
        <p className="text-gemini-soft mt-4">PG sessions count: {count === null ? '...' : count}</p>
      </div>
    </div>
  )
}
```

重启 npm run dev (Ctrl+C 后再起)，看到 PG sessions count: 0（或非负数字）= IPC + PG 全通。

- [ ] **Step 4: Revert 临时 App.tsx**

把 App.tsx 改回最简版（不要 commit 调试代码）：

```tsx
export function App() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gemini">
      <h1 className="text-2xl font-semibold text-gemini-gradient">omni-desktop</h1>
    </div>
  )
}
```

- [ ] **Step 5: Commit dev script**

```bash
git add package.json
git commit -m "feat(W5-C 切片 1.14): dev script 跑通 (vite + electron + IPC + PG)"
```

---

### 切片 1 验收

- [ ] `npm run dev` 起 vite + electron，看到 "omni-desktop" 渐变文字
- [ ] 临时 IPC 测试通过（listSessions 返回 0 或更多）
- [ ] vitest 单测全 PASS (claude-cli-detector)
- [ ] tsc main / preload / renderer 三份都 0 error
- [ ] git log 显示 ~14 个 commit

---

## 切片 2: Gemini 风 UI（4-5 天）

**目标：** UI 全套就位 — 折叠侧栏 + welcome 屏 + 居中对话流 + floating 输入框 + 多模态附件渲染 + human gate 内嵌 + dark mode。

### Task 2.1: cn helper + useDarkMode hook

**Files:**
- Create: `E:\agent\omni-desktop\src\renderer\lib\cn.ts`
- Create: `E:\agent\omni-desktop\src\renderer\hooks\useDarkMode.ts`

- [ ] **Step 1: cn helper**

```typescript
// src/renderer/lib/cn.ts
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
```

- [ ] **Step 2: useDarkMode**

```typescript
// src/renderer/hooks/useDarkMode.ts
import { useEffect, useState, useCallback } from 'react'

export function useDarkMode() {
  const [theme, setThemeState] = useState<'light' | 'dark' | 'system'>('system')
  const [resolved, setResolved] = useState<'light' | 'dark'>('light')

  // 初始化：从 settings 读
  useEffect(() => {
    window.api.getSettings().then((s) => setThemeState(s.theme))
  }, [])

  // 计算实际 dark
  useEffect(() => {
    const compute = () => {
      if (theme === 'dark') return 'dark'
      if (theme === 'light') return 'light'
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    }
    setResolved(compute())
    if (theme !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setResolved(compute())
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [theme])

  // 应用到 <html class="dark">
  useEffect(() => {
    if (resolved === 'dark') document.documentElement.classList.add('dark')
    else document.documentElement.classList.remove('dark')
  }, [resolved])

  const setTheme = useCallback((t: 'light' | 'dark' | 'system') => {
    setThemeState(t)
    window.api.updateSettings({ theme: t })
  }, [])

  return { theme, resolved, setTheme }
}
```

- [ ] **Step 3: tsc verify**

```bash
npx tsc -p tsconfig.renderer.json
```

- [ ] **Step 4: Commit**

```bash
git add src/renderer/lib/cn.ts src/renderer/hooks/useDarkMode.ts
git commit -m "feat(W5-C 切片 2.1): cn helper + useDarkMode hook"
```

---

### Task 2.2: 几何 Logo 组件

**Files:**
- Create: `E:\agent\omni-desktop\src\renderer\components\Logo.tsx`

- [ ] **Step 1: Logo.tsx (4 几何形渐变 SVG)**

```tsx
// src/renderer/components/Logo.tsx
interface Props {
  size?: number
  className?: string
}

/**
 * Gemini 风几何 logo - 4 个不同几何形叠加渐变
 * - 圆 (左上, indigo)
 * - 三角 (右上, purple)
 * - 六边形 (左下, blue)
 * - 菱形 (右下, pink)
 */
export function Logo({ size = 32, className }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <defs>
        <linearGradient id="logo-grad-1" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#6366f1" />
          <stop offset="100%" stopColor="#8b5cf6" />
        </linearGradient>
        <linearGradient id="logo-grad-2" x1="1" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#a855f7" />
          <stop offset="100%" stopColor="#ec4899" />
        </linearGradient>
        <linearGradient id="logo-grad-3" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0%" stopColor="#3b82f6" />
          <stop offset="100%" stopColor="#6366f1" />
        </linearGradient>
        <linearGradient id="logo-grad-4" x1="1" y1="1" x2="0" y2="0">
          <stop offset="0%" stopColor="#ec4899" />
          <stop offset="100%" stopColor="#f97316" />
        </linearGradient>
      </defs>
      {/* 左上 圆 */}
      <circle cx="8" cy="8" r="6" fill="url(#logo-grad-1)" />
      {/* 右上 三角 */}
      <polygon points="24,2 30,14 18,14" fill="url(#logo-grad-2)" />
      {/* 左下 六边形 */}
      <polygon points="8,20 13,23 13,29 8,32 3,29 3,23" fill="url(#logo-grad-3)" transform="translate(0,-2)" />
      {/* 右下 菱形 */}
      <polygon points="24,18 30,24 24,30 18,24" fill="url(#logo-grad-4)" />
    </svg>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add src/renderer/components/Logo.tsx
git commit -m "feat(W5-C 切片 2.2): Logo 组件 (4 几何形渐变 SVG)"
```

---

### Task 2.3: 复用 W5-B attachments 4 子组件

**Files:**
- Create: `E:\agent\omni-desktop\src\renderer\components\attachments\ImageAttachment.tsx`
- Create: `E:\agent\omni-desktop\src\renderer\components\attachments\VideoAttachment.tsx`
- Create: `E:\agent\omni-desktop\src\renderer\components\attachments\MarkdownAttachment.tsx`
- Create: `E:\agent\omni-desktop\src\renderer\components\attachments\JsonAttachment.tsx`

- [ ] **Step 1: 从 W5-B 复制 4 文件**

把 `E:\agent\omni\frontend\src\components\agent-chat\attachments\*.tsx` 4 个文件**完整复制**到 `E:\agent\omni-desktop\src\renderer\components\attachments\`，**一字不改**。

W5-B 已实现：
- ImageAttachment: 点击放大模态
- VideoAttachment: poster + 点播
- MarkdownAttachment: react-markdown + remark-gfm
- JsonAttachment: 折叠展开

只需确认 4 文件路径正确 + import 路径继续工作（都用相对路径或 lucide-react 等，没有 @/ alias 依赖）。

- [ ] **Step 2: tsc verify**

```bash
npx tsc -p tsconfig.renderer.json
```

Expected: 0 error

- [ ] **Step 3: Commit**

```bash
git add src/renderer/components/attachments/
git commit -m "feat(W5-C 切片 2.3): 复用 W5-B attachments 4 子组件 (image/video/markdown/json)"
```

---

### Task 2.4: 复用 + 微调 ToolCallChip / ToolResultCard / MessageBubble / HumanGateCard

**Files:**
- Create: `E:\agent\omni-desktop\src\renderer\components\ToolCallChip.tsx`
- Create: `E:\agent\omni-desktop\src\renderer\components\ToolResultCard.tsx`
- Create: `E:\agent\omni-desktop\src\renderer\components\MessageBubble.tsx`
- Create: `E:\agent\omni-desktop\src\renderer\components\HumanGateCard.tsx`

- [ ] **Step 1: ToolCallChip (95% 复用 W5-B + 改 Gemini 渐变 spinner)**

```tsx
// src/renderer/components/ToolCallChip.tsx
import { Loader2, CheckCircle2, XCircle, Wrench } from 'lucide-react'
import { useState } from 'react'
import { JsonAttachment } from './attachments/JsonAttachment'
import { cn } from '@/lib/cn'

interface Props {
  toolName: string
  args: Record<string, unknown> | undefined
  status: 'pending' | 'completed' | 'error'
}

export function ToolCallChip({ toolName, args, status }: Props) {
  const [open, setOpen] = useState(false)
  return (
    <div className="inline-flex flex-col items-start gap-1 max-w-2xl">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          'inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs transition-colors',
          'bg-gemini-card border border-gemini hover:border-indigo-300',
          'text-gemini-soft',
        )}
      >
        <Wrench className="w-3 h-3 text-indigo-500" />
        <span className="font-medium text-gemini">{toolName}</span>
        {status === 'pending' && (
          <Loader2 className="w-3 h-3 animate-spinner-rotate text-indigo-500" />
        )}
        {status === 'completed' && <CheckCircle2 className="w-3 h-3 text-emerald-500" />}
        {status === 'error' && <XCircle className="w-3 h-3 text-red-500" />}
      </button>
      {open && args && <JsonAttachment data={args} />}
    </div>
  )
}
```

- [ ] **Step 2: ToolResultCard (100% 复用)**

```tsx
// src/renderer/components/ToolResultCard.tsx
import type { ChatAttachment } from '@shared/types'
import { ImageAttachment } from './attachments/ImageAttachment'
import { VideoAttachment } from './attachments/VideoAttachment'
import { MarkdownAttachment } from './attachments/MarkdownAttachment'
import { JsonAttachment } from './attachments/JsonAttachment'

interface Props {
  attachments: ChatAttachment[]
  rawResult: unknown
}

export function ToolResultCard({ attachments, rawResult }: Props) {
  if (attachments.length === 0) {
    return <JsonAttachment data={rawResult} />
  }
  return (
    <div className="flex flex-wrap gap-3 max-w-3xl">
      {attachments.map((att, idx) => {
        if (att.type === 'image' && att.url) return <ImageAttachment key={idx} url={att.url} alt={att.alt} />
        if (att.type === 'video' && att.url) return <VideoAttachment key={idx} url={att.url} poster={att.thumbnail_url} />
        if (att.type === 'markdown' && att.markdown) return <MarkdownAttachment key={idx} markdown={att.markdown} />
        if (att.type === 'json') return <JsonAttachment key={idx} data={att.data} />
        return null
      })}
    </div>
  )
}
```

- [ ] **Step 3: MessageBubble (Gemini 风 — assistant 没气泡，user 圆角小气泡)**

```tsx
// src/renderer/components/MessageBubble.tsx
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { User2 } from 'lucide-react'
import { Logo } from './Logo'
import { cn } from '@/lib/cn'

interface Props {
  role: 'user' | 'assistant'
  text: string
  streaming?: boolean   // 流式输出时尾部加光标
}

export function MessageBubble({ role, text, streaming }: Props) {
  if (role === 'user') {
    return (
      <div className="flex gap-3 max-w-3xl self-end flex-row-reverse">
        <div className="w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300 flex items-center justify-center shrink-0">
          <User2 className="w-4 h-4" />
        </div>
        <div className={cn(
          'rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm leading-relaxed',
          'bg-indigo-50 dark:bg-indigo-950 text-gemini border border-indigo-100 dark:border-indigo-900',
        )}>
          {text}
        </div>
      </div>
    )
  }

  // assistant: 无气泡，纯文档样式
  return (
    <div className="flex gap-3 max-w-3xl self-start">
      <div className="w-8 h-8 shrink-0 flex items-center justify-center">
        <Logo size={28} />
      </div>
      <div className="prose prose-sm dark:prose-invert max-w-none text-gemini leading-relaxed flex-1 min-w-0">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        {streaming && <span className="inline-block w-2 h-4 ml-0.5 bg-indigo-500 animate-cursor-blink" />}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: HumanGateCard (90% 复用 + 改 Gemini 配色)**

```tsx
// src/renderer/components/HumanGateCard.tsx
import { CheckCircle2, XCircle, Shield } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/cn'

interface Props {
  shortId: string
  summary: string
  decision: 'pending' | 'approved' | 'rejected'
  onDecide: (decision: 'approved' | 'rejected', note?: string) => void
}

export function HumanGateCard({ shortId, summary, decision, onDecide }: Props) {
  const [note, setNote] = useState('')
  return (
    <div className={cn(
      'max-w-2xl rounded-2xl border-2 p-4 self-start',
      'border-amber-300 dark:border-amber-700',
      'bg-amber-50/50 dark:bg-amber-950/30 backdrop-blur',
    )}>
      <div className="flex items-center gap-2 mb-2">
        <Shield className="w-4 h-4 text-amber-600 dark:text-amber-400" />
        <span className="text-sm font-semibold text-amber-900 dark:text-amber-100">需要你点头</span>
        <span className="text-[10px] text-amber-700 dark:text-amber-300 font-mono">{shortId}</span>
      </div>
      <p className="text-sm text-gemini mb-3 whitespace-pre-wrap">{summary}</p>
      {decision === 'pending' ? (
        <>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="备注（可选）"
            className={cn(
              'w-full px-2.5 py-1.5 text-xs rounded-md mb-2 focus:outline-none',
              'border border-amber-200 dark:border-amber-800',
              'bg-white dark:bg-slate-800 text-gemini',
              'focus:border-amber-400 dark:focus:border-amber-600',
            )}
          />
          <div className="flex gap-2">
            <button
              onClick={() => onDecide('approved', note)}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs hover:bg-emerald-700"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              通过
            </button>
            <button
              onClick={() => onDecide('rejected', note)}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-600 text-white text-xs hover:bg-red-700"
            >
              <XCircle className="w-3.5 h-3.5" />
              驳回
            </button>
          </div>
        </>
      ) : (
        <div className="text-xs">
          {decision === 'approved' ? (
            <span className="text-emerald-700 dark:text-emerald-400">✓ 已通过</span>
          ) : (
            <span className="text-red-700 dark:text-red-400">✗ 已驳回</span>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 5: tsc verify**

```bash
npx tsc -p tsconfig.renderer.json
```

- [ ] **Step 6: Commit**

```bash
git add src/renderer/components/ToolCallChip.tsx src/renderer/components/ToolResultCard.tsx src/renderer/components/MessageBubble.tsx src/renderer/components/HumanGateCard.tsx
git commit -m "feat(W5-C 切片 2.4): ToolCallChip + ToolResultCard + MessageBubble + HumanGateCard (Gemini 风微调)"
```

---

### Task 2.5: useAgentChat hook (IPC 版)

**Files:**
- Create: `E:\agent\omni-desktop\src\renderer\hooks\useAgentChat.ts`
- Create: `E:\agent\omni-desktop\src\renderer\hooks\useNotification.ts`

- [ ] **Step 1: useNotification (100% 复用 W5-B)**

把 `E:\agent\omni\frontend\src\hooks\useNotification.ts` 完整复制到 `E:\agent\omni-desktop\src\renderer\hooks\useNotification.ts`。

参考代码（不变）：

```typescript
// src/renderer/hooks/useNotification.ts
import { useEffect, useState } from 'react'

export function useNotification() {
  const [permission, setPermission] = useState<NotificationPermission>('default')

  useEffect(() => {
    if (typeof window === 'undefined' || !('Notification' in window)) return
    setPermission(Notification.permission)
  }, [])

  const requestPermission = async () => {
    if (typeof window === 'undefined' || !('Notification' in window)) return 'denied'
    const result = await Notification.requestPermission()
    setPermission(result)
    return result
  }

  const notify = (title: string, options: NotificationOptions = {}) => {
    if (typeof window === 'undefined' || !('Notification' in window)) return
    if (permission !== 'granted') return
    try {
      const n = new Notification(title, { icon: '/favicon.ico', ...options })
      n.onclick = () => {
        window.focus()
        n.close()
      }
    } catch {
      /* swallow */
    }
  }

  return { permission, requestPermission, notify }
}
```

- [ ] **Step 2: useAgentChat (IPC 版，替代 W5-B WebSocket)**

```typescript
// src/renderer/hooks/useAgentChat.ts
import { useEffect, useRef, useState, useCallback } from 'react'
import type {
  ChatMessage, SessionState, ChatAttachment,
  RendererPushEvent,
} from '@shared/types'

interface UseAgentChatOptions {
  onTaskDone?: (sessionId: string, durationMs: number) => void
  onGateNew?: (gate: { short_id: string; tool_name: string; summary: string }) => void
}

interface UseAgentChatResult {
  session: SessionState | null
  messages: ChatMessage[]
  running: boolean
  error: string | null
  sendPrompt: (prompt: string, attachments?: ChatAttachment[]) => void
  cancel: () => void
  decideGate: (shortId: string, decision: 'approved' | 'rejected', note?: string) => void
}

export function useAgentChat(
  sessionId: string | null,
  options: UseAgentChatOptions = {},
): UseAgentChatResult {
  const [session, setSession] = useState<SessionState | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const optionsRef = useRef(options)

  useEffect(() => { optionsRef.current = options }, [options])

  // open session 当 sessionId 变化
  useEffect(() => {
    if (!sessionId) {
      setSession(null)
      setMessages([])
      return
    }
    let cancelled = false
    window.api.openSession(sessionId).then(({ session: s, history }) => {
      if (cancelled) return
      setSession(s)
      setMessages(history)
    }).catch((e: Error) => setError(e.message))
    return () => {
      cancelled = true
    }
  }, [sessionId])

  // 全局 push event listener
  useEffect(() => {
    const off = window.api.onPush((event: RendererPushEvent) => {
      if (event.kind === 'chunk') {
        if (event.session_id !== sessionId) return
        setMessages((prev) => mergeMessage(prev, event.message))
      } else if (event.kind === 'task_done') {
        if (event.session_id === sessionId) setRunning(false)
        optionsRef.current.onTaskDone?.(event.session_id, event.duration_ms)
      } else if (event.kind === 'human_gate_new') {
        const gateMsg: ChatMessage = {
          id: `gate-${event.gate.short_id}`,
          session_id: event.session_id,
          role: 'human_gate',
          gate_short_id: event.gate.short_id,
          gate_summary: event.gate.summary,
          gate_decision: 'pending',
          created_at: new Date().toISOString(),
        }
        // 路由：暂时全广播；session 级路由由 broadcast/push 决定
        if (!event.session_id || event.session_id === sessionId) {
          setMessages((prev) => [...prev, gateMsg])
        }
        optionsRef.current.onGateNew?.(event.gate)
      } else if (event.kind === 'error') {
        setError(event.error + (event.detail ? `: ${event.detail}` : ''))
        setRunning(false)
      }
    })
    return off
  }, [sessionId])

  const sendPrompt = useCallback((prompt: string, attachments?: ChatAttachment[]) => {
    if (!sessionId) return
    setRunning(true)
    setError(null)
    setMessages((prev) => [
      ...prev,
      {
        id: `local-${Date.now()}`,
        session_id: sessionId,
        role: 'user',
        text: prompt,
        attachments,
        created_at: new Date().toISOString(),
      },
    ])
    window.api.sendPrompt({ session_id: sessionId, prompt, attachments }).catch((e: Error) => {
      setError(e.message)
      setRunning(false)
    })
  }, [sessionId])

  const cancel = useCallback(() => {
    if (!sessionId) return
    window.api.cancel(sessionId).catch(() => undefined)
    setRunning(false)
  }, [sessionId])

  const decideGate = useCallback((shortId: string, decision: 'approved' | 'rejected', note?: string) => {
    window.api.decideGate({ short_id: shortId, decision, note }).catch((e: Error) => setError(e.message))
    setMessages((prev) => prev.map((m) => (m.gate_short_id === shortId ? { ...m, gate_decision: decision } : m)))
  }, [])

  return { session, messages, running, error, sendPrompt, cancel, decideGate }
}

function mergeMessage(prev: ChatMessage[], incoming: ChatMessage): ChatMessage[] {
  if (incoming.role === 'tool_result' && incoming.tool_use_id) {
    const callIdx = prev.findIndex((m) => m.role === 'tool_call' && m.tool_use_id === incoming.tool_use_id)
    if (callIdx >= 0) {
      const next = [...prev]
      next[callIdx] = { ...next[callIdx], tool_status: 'completed' }
      return [...next, incoming]
    }
  }
  return [...prev, incoming]
}
```

- [ ] **Step 3: tsc verify**

```bash
npx tsc -p tsconfig.renderer.json
```

- [ ] **Step 4: Commit**

```bash
git add src/renderer/hooks/useAgentChat.ts src/renderer/hooks/useNotification.ts
git commit -m "feat(W5-C 切片 2.5): useAgentChat (IPC 版) + useNotification 复用"
```

---

### Task 2.6: Sidebar (折叠侧栏)

**Files:**
- Create: `E:\agent\omni-desktop\src\renderer\components\Sidebar.tsx`
- Create: `E:\agent\omni-desktop\src\renderer\hooks\useGreeting.ts`

- [ ] **Step 1: useGreeting hook**

```typescript
// src/renderer/hooks/useGreeting.ts
import { useEffect, useState } from 'react'

export function useGreeting(): string {
  const [greeting, setGreeting] = useState('你好')
  useEffect(() => {
    const compute = () => {
      const h = new Date().getHours()
      if (h < 6) return '熬夜呢'
      if (h < 11) return '早上好'
      if (h < 14) return '中午好'
      if (h < 18) return '下午好'
      return '晚上好'
    }
    setGreeting(compute())
    const timer = setInterval(() => setGreeting(compute()), 60_000)
    return () => clearInterval(timer)
  }, [])
  return greeting
}
```

- [ ] **Step 2: Sidebar 组件**

```tsx
// src/renderer/components/Sidebar.tsx
import { useEffect, useState } from 'react'
import { Plus, Settings, MessageSquare, Trash2, Sun, Moon } from 'lucide-react'
import { Logo } from './Logo'
import { cn } from '@/lib/cn'
import { useDarkMode } from '@/hooks/useDarkMode'
import type { SessionState } from '@shared/types'

interface Props {
  currentId: string | null
  onSelect: (id: string) => void
  onOpenSettings: () => void
}

export function Sidebar({ currentId, onSelect, onOpenSettings }: Props) {
  const [list, setList] = useState<SessionState[]>([])
  const [hovered, setHovered] = useState(false)
  const { resolved, setTheme } = useDarkMode()

  const refresh = async () => {
    const data = await window.api.listSessions()
    setList(data)
  }
  useEffect(() => { refresh() }, [])

  const createNew = async () => {
    const s = await window.api.createSession({})
    await refresh()
    onSelect(s.id)
  }

  const removeOne = async (id: string) => {
    if (!confirm('删除这个对话？')) return
    await window.api.deleteSession(id)
    await refresh()
    if (currentId === id) onSelect('')
  }

  const expanded = hovered

  return (
    <aside
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={cn(
        'h-screen flex flex-col bg-gemini-soft border-r border-gemini transition-all duration-200 ease-out z-10',
        expanded ? 'w-60' : 'w-16',
      )}
    >
      {/* Top: Logo + New */}
      <div className="px-3 h-14 flex items-center gap-3 border-b border-gemini shrink-0">
        <Logo size={28} />
        {expanded && <span className="text-sm font-medium text-gemini">omni</span>}
      </div>

      <div className="px-3 py-3">
        <button
          onClick={createNew}
          className={cn(
            'w-full h-9 inline-flex items-center gap-2 rounded-xl text-xs',
            'bg-gemini-gradient text-white shadow-gemini',
            'hover:opacity-90 transition-opacity',
            expanded ? 'px-3 justify-start' : 'justify-center',
          )}
        >
          <Plus className="w-4 h-4 shrink-0" />
          {expanded && <span>新对话</span>}
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-2 space-y-0.5">
        {list.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={cn(
              'w-full text-left px-2 py-2 rounded-lg flex items-center gap-2 group transition-colors',
              currentId === s.id
                ? 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300'
                : 'hover:bg-gemini-card text-gemini-soft',
            )}
            title={!expanded ? s.title : undefined}
          >
            <MessageSquare className="w-3.5 h-3.5 shrink-0" />
            {expanded && (
              <>
                <div className="flex-1 min-w-0">
                  <div className="text-xs truncate">{s.title}</div>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); removeOne(s.id) }}
                  className="opacity-0 group-hover:opacity-100 hover:text-red-500 shrink-0"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </>
            )}
          </button>
        ))}
      </div>

      {/* Bottom: Theme toggle + Settings */}
      <div className="px-3 py-3 border-t border-gemini space-y-1 shrink-0">
        <button
          onClick={() => setTheme(resolved === 'dark' ? 'light' : 'dark')}
          className={cn(
            'w-full h-9 inline-flex items-center gap-2 rounded-lg text-xs text-gemini-soft hover:bg-gemini-card',
            expanded ? 'px-3 justify-start' : 'justify-center',
          )}
          title={!expanded ? '切换主题' : undefined}
        >
          {resolved === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          {expanded && <span>{resolved === 'dark' ? '浅色' : '深色'}</span>}
        </button>
        <button
          onClick={onOpenSettings}
          className={cn(
            'w-full h-9 inline-flex items-center gap-2 rounded-lg text-xs text-gemini-soft hover:bg-gemini-card',
            expanded ? 'px-3 justify-start' : 'justify-center',
          )}
          title={!expanded ? '设置' : undefined}
        >
          <Settings className="w-4 h-4" />
          {expanded && <span>设置</span>}
        </button>
      </div>
    </aside>
  )
}
```

- [ ] **Step 3: tsc verify**

```bash
npx tsc -p tsconfig.renderer.json
```

- [ ] **Step 4: Commit**

```bash
git add src/renderer/components/Sidebar.tsx src/renderer/hooks/useGreeting.ts
git commit -m "feat(W5-C 切片 2.6): Sidebar 折叠侧栏 (hover 展开 240px) + useGreeting"
```

---

### Task 2.7: WelcomeScreen + prompt suggestions

**Files:**
- Create: `E:\agent\omni-desktop\src\renderer\components\WelcomeScreen.tsx`

- [ ] **Step 1: WelcomeScreen**

```tsx
// src/renderer/components/WelcomeScreen.tsx
import { useEffect, useState } from 'react'
import { Sparkles, Package, Store, Video, ChartBar } from 'lucide-react'
import { Logo } from './Logo'
import { useGreeting } from '@/hooks/useGreeting'
import { cn } from '@/lib/cn'

interface Props {
  onPickPrompt: (prompt: string) => void
}

interface PromptSuggestion {
  icon: React.ComponentType<{ className?: string }>
  title: string
  prompt: string
  bgClass: string
  iconClass: string
}

const SUGGESTIONS: PromptSuggestion[] = [
  {
    icon: Package,
    title: '诊断一个 SKU',
    prompt: '帮我诊断 SKU-367991-0002 当前的健康度（成本、利润、数据、历史决策）',
    bgClass: 'bg-indigo-50 dark:bg-indigo-950 hover:bg-indigo-100 dark:hover:bg-indigo-900',
    iconClass: 'text-indigo-500',
  },
  {
    icon: Store,
    title: '今天店铺怎么样',
    prompt: '看一下今天店铺的大盘数据，有什么异动吗',
    bgClass: 'bg-purple-50 dark:bg-purple-950 hover:bg-purple-100 dark:hover:bg-purple-900',
    iconClass: 'text-purple-500',
  },
  {
    icon: Video,
    title: '写一个 SKU 脚本',
    prompt: '帮 SKU-367991-0002 写一个种草视频脚本',
    bgClass: 'bg-blue-50 dark:bg-blue-950 hover:bg-blue-100 dark:hover:bg-blue-900',
    iconClass: 'text-blue-500',
  },
  {
    icon: ChartBar,
    title: '看投放复盘',
    prompt: '最近 7 天的投放复盘怎么样',
    bgClass: 'bg-pink-50 dark:bg-pink-950 hover:bg-pink-100 dark:hover:bg-pink-900',
    iconClass: 'text-pink-500',
  },
]

export function WelcomeScreen({ onPickPrompt }: Props) {
  const greeting = useGreeting()
  const [username, setUsername] = useState('Boss')
  useEffect(() => {
    window.api.getSettings().then((s) => setUsername(s.username || 'Boss'))
  }, [])

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 pb-8">
      <Logo size={64} className="mb-8" />
      <h1 className="text-4xl font-semibold mb-2">
        <span className="text-gemini-gradient">{greeting}，{username}</span>
      </h1>
      <p className="text-gemini-soft text-sm mb-12">今天想跟 omni 聊点啥？</p>

      <div className="grid grid-cols-2 gap-3 max-w-2xl w-full">
        {SUGGESTIONS.map((s, i) => {
          const Icon = s.icon
          return (
            <button
              key={i}
              onClick={() => onPickPrompt(s.prompt)}
              className={cn(
                'group flex items-start gap-3 px-4 py-4 rounded-2xl text-left',
                'border border-gemini transition-all',
                s.bgClass,
              )}
            >
              <Icon className={cn('w-5 h-5 shrink-0 mt-0.5', s.iconClass)} />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-gemini">{s.title}</div>
                <div className="text-xs text-gemini-soft mt-1 line-clamp-2">{s.prompt}</div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add src/renderer/components/WelcomeScreen.tsx
git commit -m "feat(W5-C 切片 2.7): WelcomeScreen Hello + 4 prompt suggestions 卡片"
```

---

### Task 2.8: MessageStream (居中对话流)

**Files:**
- Create: `E:\agent\omni-desktop\src\renderer\components\MessageStream.tsx`

- [ ] **Step 1: MessageStream**

```tsx
// src/renderer/components/MessageStream.tsx
import { useEffect, useRef } from 'react'
import type { ChatMessage } from '@shared/types'
import { MessageBubble } from './MessageBubble'
import { ToolCallChip } from './ToolCallChip'
import { ToolResultCard } from './ToolResultCard'
import { HumanGateCard } from './HumanGateCard'

interface Props {
  messages: ChatMessage[]
  onDecideGate: (shortId: string, decision: 'approved' | 'rejected', note?: string) => void
}

export function MessageStream({ messages, onDecideGate }: Props) {
  const bottomRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length])

  return (
    <div className="flex-1 overflow-y-auto px-6 pb-32 pt-8">
      <div className="max-w-3xl mx-auto flex flex-col gap-6">
        {messages.map((m, idx) => {
          const isLast = idx === messages.length - 1
          if (m.role === 'user' || m.role === 'assistant') {
            return (
              <MessageBubble
                key={m.id}
                role={m.role}
                text={m.text || ''}
                streaming={m.role === 'assistant' && isLast}
              />
            )
          }
          if (m.role === 'tool_call') {
            return (
              <div key={m.id} className="self-start ml-11">
                <ToolCallChip
                  toolName={m.tool_name || ''}
                  args={m.tool_args}
                  status={m.tool_status || 'pending'}
                />
              </div>
            )
          }
          if (m.role === 'tool_result') {
            return (
              <div key={m.id} className="self-start ml-11">
                <ToolResultCard
                  attachments={m.attachments || []}
                  rawResult={m.raw_result}
                />
              </div>
            )
          }
          if (m.role === 'human_gate' && m.gate_short_id) {
            return (
              <HumanGateCard
                key={m.id}
                shortId={m.gate_short_id}
                summary={m.gate_summary || ''}
                decision={m.gate_decision || 'pending'}
                onDecide={(d, n) => onDecideGate(m.gate_short_id!, d, n)}
              />
            )
          }
          return null
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add src/renderer/components/MessageStream.tsx
git commit -m "feat(W5-C 切片 2.8): MessageStream 居中对话流 (max-w-3xl + 流式光标)"
```

---

### Task 2.9: InputBar (floating 底部)

**Files:**
- Create: `E:\agent\omni-desktop\src\renderer\components\InputBar.tsx`

- [ ] **Step 1: InputBar (floating + 附件 + 发送 / 停止)**

```tsx
// src/renderer/components/InputBar.tsx
import { useState, useRef } from 'react'
import { Send, Paperclip, X, Square } from 'lucide-react'
import type { ChatAttachment } from '@shared/types'
import { cn } from '@/lib/cn'

interface Props {
  sessionId: string
  running: boolean
  onSend: (prompt: string, attachments?: ChatAttachment[]) => void
  onCancel: () => void
}

interface UploadedFile {
  url: string
  filename: string
  mime: string
}

export function InputBar({ sessionId, running, onSend, onCancel }: Props) {
  const [input, setInput] = useState('')
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  const handleSend = () => {
    if (!input.trim() && files.length === 0) return
    let prompt = input.trim()
    if (files.length > 0) {
      const fileList = files.map((f) => `- ${f.filename}: ${f.url}`).join('\n')
      prompt = `${prompt}\n\n附件：\n${fileList}`
    }
    const attachments: ChatAttachment[] = files.map((f) => ({
      type: f.mime.startsWith('image/') ? 'image' : f.mime.startsWith('video/') ? 'video' : 'link',
      url: f.url,
      label: f.filename,
    }))
    onSend(prompt, attachments)
    setInput('')
    setFiles([])
    // textarea reset height
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const list = e.target.files
    if (!list || list.length === 0) return
    setUploading(true)
    try {
      for (const f of Array.from(list)) {
        const buf = await f.arrayBuffer()
        const r = await window.api.uploadFile({
          session_id: sessionId,
          file: { name: f.name, type: f.type, data: buf },
        })
        setFiles((prev) => [...prev, { url: r.url, filename: r.filename, mime: r.mime }])
      }
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleTextareaInput = (e: React.FormEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }

  return (
    <div className="absolute bottom-0 left-0 right-0 px-6 pb-6 pointer-events-none">
      <div className="max-w-3xl mx-auto pointer-events-auto">
        {files.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-2">
            {files.map((f, idx) => (
              <span
                key={idx}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 text-xs text-gemini"
              >
                <Paperclip className="w-3 h-3 text-indigo-500" />
                {f.filename}
                <button onClick={() => setFiles(files.filter((_, i) => i !== idx))}>
                  <X className="w-3 h-3 text-gemini-weak hover:text-red-500" />
                </button>
              </span>
            ))}
          </div>
        )}

        <div className={cn(
          'flex items-end gap-2 px-3 py-2 rounded-2xl bg-gemini-card border border-gemini',
          'shadow-lg shadow-slate-200/30 dark:shadow-black/30',
          'focus-within:border-indigo-300 dark:focus-within:border-indigo-700 transition-colors',
        )}>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="shrink-0 w-9 h-9 rounded-lg flex items-center justify-center text-gemini-soft hover:bg-gemini-soft transition-colors"
            title="附件"
          >
            <Paperclip className="w-4 h-4" />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,video/*,.pdf,.md,.txt,.json"
            onChange={handleFileUpload}
            className="hidden"
          />
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onInput={handleTextareaInput}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
            placeholder="问点啥…（Enter 发送，Shift+Enter 换行）"
            rows={1}
            className="flex-1 resize-none bg-transparent border-0 focus:outline-none text-sm text-gemini placeholder:text-gemini-weak min-h-[24px] max-h-40 py-1"
          />
          {running ? (
            <button
              onClick={onCancel}
              className="shrink-0 w-9 h-9 rounded-lg bg-red-500 hover:bg-red-600 text-white flex items-center justify-center transition-colors"
              title="停止"
            >
              <Square className="w-3.5 h-3.5" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim() && files.length === 0}
              className={cn(
                'shrink-0 w-9 h-9 rounded-lg flex items-center justify-center transition-all',
                input.trim() || files.length > 0
                  ? 'bg-gemini-gradient text-white shadow-md hover:opacity-90'
                  : 'bg-gemini-soft text-gemini-weak cursor-not-allowed',
              )}
              title="发送"
            >
              <Send className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add src/renderer/components/InputBar.tsx
git commit -m "feat(W5-C 切片 2.9): InputBar floating 底部 + textarea 自适应高度 + 附件 IPC"
```

---

### Task 2.10: SettingsPanel

**Files:**
- Create: `E:\agent\omni-desktop\src\renderer\components\SettingsPanel.tsx`

- [ ] **Step 1: SettingsPanel modal**

```tsx
// src/renderer/components/SettingsPanel.tsx
import { useEffect, useState } from 'react'
import { X, CheckCircle2, AlertCircle } from 'lucide-react'
import type { AppSettings } from '@shared/types'
import { cn } from '@/lib/cn'

interface Props {
  open: boolean
  onClose: () => void
}

export function SettingsPanel({ open, onClose }: Props) {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [detected, setDetected] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    window.api.getSettings().then(setSettings)
    window.api.detectClaude().then(setDetected)
  }, [open])

  if (!open || !settings) return null

  const save = async (patch: Partial<AppSettings>) => {
    setSaving(true)
    try {
      const s = await window.api.updateSettings(patch)
      setSettings(s)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-6" onClick={onClose}>
      <div
        className="w-full max-w-2xl rounded-2xl bg-gemini-card border border-gemini shadow-2xl max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gemini flex items-center justify-between sticky top-0 bg-gemini-card">
          <h2 className="text-lg font-semibold text-gemini">设置</h2>
          <button onClick={onClose} className="text-gemini-soft hover:text-gemini">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-6 space-y-6">
          {/* Claude CLI path */}
          <section>
            <label className="block text-sm font-medium text-gemini mb-2">Claude CLI 路径</label>
            <div className="flex gap-2">
              <input
                value={settings.claudeCliPath || ''}
                onChange={(e) => setSettings({ ...settings, claudeCliPath: e.target.value || null })}
                onBlur={() => save({ claudeCliPath: settings.claudeCliPath })}
                placeholder="留空自动 detect"
                className="flex-1 px-3 py-2 text-sm rounded-lg bg-gemini border border-gemini focus:outline-none focus:border-indigo-300 text-gemini"
              />
            </div>
            {detected ? (
              <div className="mt-2 text-xs text-emerald-600 dark:text-emerald-400 flex items-center gap-1.5">
                <CheckCircle2 className="w-3 h-3" />
                自动 detect 到: {detected}
              </div>
            ) : (
              <div className="mt-2 text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1.5">
                <AlertCircle className="w-3 h-3" />
                没自动 detect 到 claude CLI，请手填绝对路径
              </div>
            )}
          </section>

          {/* Global shortcut */}
          <section>
            <label className="block text-sm font-medium text-gemini mb-2">全局快捷键</label>
            <input
              value={settings.globalShortcut}
              onChange={(e) => setSettings({ ...settings, globalShortcut: e.target.value })}
              onBlur={() => save({ globalShortcut: settings.globalShortcut })}
              className="w-full px-3 py-2 text-sm rounded-lg bg-gemini border border-gemini focus:outline-none focus:border-indigo-300 text-gemini font-mono"
            />
            <div className="mt-1 text-xs text-gemini-weak">
              格式：CommandOrControl+Shift+Space / CommandOrControl+Alt+A 等
            </div>
          </section>

          {/* Auto start */}
          <section className="flex items-center justify-between">
            <label className="text-sm font-medium text-gemini">开机自启</label>
            <button
              onClick={() => save({ autoStart: !settings.autoStart })}
              className={cn(
                'w-10 h-6 rounded-full relative transition-colors',
                settings.autoStart ? 'bg-indigo-500' : 'bg-slate-300 dark:bg-slate-700',
              )}
            >
              <div
                className={cn(
                  'absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform',
                  settings.autoStart ? 'left-[18px]' : 'left-0.5',
                )}
              />
            </button>
          </section>

          {/* Theme */}
          <section>
            <label className="block text-sm font-medium text-gemini mb-2">主题</label>
            <div className="flex gap-2">
              {(['light', 'dark', 'system'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => save({ theme: t })}
                  className={cn(
                    'flex-1 px-3 py-1.5 text-xs rounded-lg border transition-colors',
                    settings.theme === t
                      ? 'bg-indigo-500 text-white border-indigo-500'
                      : 'bg-gemini border-gemini text-gemini hover:bg-gemini-soft',
                  )}
                >
                  {t === 'light' ? '浅色' : t === 'dark' ? '深色' : '跟系统'}
                </button>
              ))}
            </div>
          </section>

          {/* Username */}
          <section>
            <label className="block text-sm font-medium text-gemini mb-2">显示名字（Welcome 屏用）</label>
            <input
              value={settings.username}
              onChange={(e) => setSettings({ ...settings, username: e.target.value })}
              onBlur={() => save({ username: settings.username })}
              className="w-full px-3 py-2 text-sm rounded-lg bg-gemini border border-gemini focus:outline-none focus:border-indigo-300 text-gemini"
            />
          </section>

          {/* Backend URLs (advanced) */}
          <section>
            <label className="block text-sm font-medium text-gemini mb-2">后端连接（高级）</label>
            <div className="space-y-2">
              <input
                value={settings.omniKeUrl}
                onChange={(e) => setSettings({ ...settings, omniKeUrl: e.target.value })}
                onBlur={() => save({ omniKeUrl: settings.omniKeUrl })}
                placeholder="omni KE URL"
                className="w-full px-3 py-2 text-xs font-mono rounded-lg bg-gemini border border-gemini focus:outline-none focus:border-indigo-300 text-gemini"
              />
              <input
                value={settings.omniPgUrl}
                onChange={(e) => setSettings({ ...settings, omniPgUrl: e.target.value })}
                onBlur={() => save({ omniPgUrl: settings.omniPgUrl })}
                placeholder="omni PG URL"
                className="w-full px-3 py-2 text-xs font-mono rounded-lg bg-gemini border border-gemini focus:outline-none focus:border-indigo-300 text-gemini"
              />
              <input
                value={settings.omniRedisUrl}
                onChange={(e) => setSettings({ ...settings, omniRedisUrl: e.target.value })}
                onBlur={() => save({ omniRedisUrl: settings.omniRedisUrl })}
                placeholder="omni Redis URL"
                className="w-full px-3 py-2 text-xs font-mono rounded-lg bg-gemini border border-gemini focus:outline-none focus:border-indigo-300 text-gemini"
              />
            </div>
          </section>

          {saving && (
            <div className="text-xs text-gemini-weak text-center">保存中...</div>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add src/renderer/components/SettingsPanel.tsx
git commit -m "feat(W5-C 切片 2.10): SettingsPanel modal (claude path / shortcut / theme / 后端 URL)"
```

---

### Task 2.11: ChatLayout 整合

**Files:**
- Create: `E:\agent\omni-desktop\src\renderer\components\ChatLayout.tsx`
- Modify: `E:\agent\omni-desktop\src\renderer\App.tsx`

- [ ] **Step 1: ChatLayout 主整合**

```tsx
// src/renderer/components/ChatLayout.tsx
import { useState, useEffect } from 'react'
import { Sidebar } from './Sidebar'
import { WelcomeScreen } from './WelcomeScreen'
import { MessageStream } from './MessageStream'
import { InputBar } from './InputBar'
import { SettingsPanel } from './SettingsPanel'
import { useAgentChat } from '@/hooks/useAgentChat'
import { useNotification } from '@/hooks/useNotification'
import { useDarkMode } from '@/hooks/useDarkMode'

export function ChatLayout() {
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)

  // 初始化 dark mode
  useDarkMode()

  const { permission, requestPermission, notify } = useNotification()
  useEffect(() => {
    if (permission === 'default') requestPermission()
  }, [permission, requestPermission])

  const { session, messages, running, error, sendPrompt, cancel, decideGate } = useAgentChat(currentId, {
    onTaskDone: (_sid, dur) => {
      if (typeof document !== 'undefined' && document.hidden) {
        notify('omni 任务完成', { body: `用时 ${(dur / 1000).toFixed(0)}s` })
      }
    },
    onGateNew: (gate) => {
      if (typeof document !== 'undefined' && document.hidden) {
        notify('需要你点头', { body: `${gate.tool_name}：${gate.summary.slice(0, 80)}` })
      }
    },
  })

  const pickPrompt = async (prompt: string) => {
    // Welcome 屏点 prompt 自动建 session + 发
    const s = await window.api.createSession({})
    setCurrentId(s.id)
    // 等 session opened 后发（useEffect 链路）
    setTimeout(() => sendPrompt(prompt), 100)
  }

  return (
    <div className="h-screen flex bg-gemini text-gemini">
      <Sidebar
        currentId={currentId}
        onSelect={(id) => setCurrentId(id || null)}
        onOpenSettings={() => setSettingsOpen(true)}
      />
      <main className="flex-1 flex flex-col min-w-0 relative">
        {currentId ? (
          <>
            <header className="h-14 px-6 flex items-center border-b border-gemini shrink-0">
              <h1 className="text-sm font-medium text-gemini truncate">
                {session?.title || '加载中...'}
              </h1>
            </header>
            <MessageStream messages={messages} onDecideGate={decideGate} />
            <InputBar
              sessionId={currentId}
              running={running}
              onSend={sendPrompt}
              onCancel={cancel}
            />
          </>
        ) : (
          <>
            <WelcomeScreen onPickPrompt={pickPrompt} />
          </>
        )}
        {error && (
          <div className="absolute top-16 left-1/2 -translate-x-1/2 max-w-md px-4 py-2 rounded-lg bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 text-xs text-red-700 dark:text-red-300">
            {error}
          </div>
        )}
      </main>
      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  )
}
```

- [ ] **Step 2: 改 App.tsx 用 ChatLayout**

```tsx
// src/renderer/App.tsx
import { ChatLayout } from './components/ChatLayout'

export function App() {
  return <ChatLayout />
}
```

- [ ] **Step 3: tsc + smoke test**

```bash
npx tsc -p tsconfig.renderer.json
npm run dev
```

打开桌面 app，应该看到：
- 左侧折叠侧栏（hover 展开）
- 主区 WelcomeScreen（greeting + 4 prompt 卡片）
- 底部 floating 输入框
- 点 prompt 卡片 → 自动建 session + 发

- [ ] **Step 4: Commit**

```bash
git add src/renderer/components/ChatLayout.tsx src/renderer/App.tsx
git commit -m "feat(W5-C 切片 2.11): ChatLayout 整合 (Sidebar + WelcomeScreen + MessageStream + InputBar + Settings)"
```

---

### 切片 2 验收

- [ ] dev mode 打开看到 Gemini 风 UI（折叠侧栏 + welcome 屏 + floating 输入框）
- [ ] hover 侧栏自动展开，点新对话建 session
- [ ] welcome 屏 4 个 prompt suggestion 可点击 → 建 session + 发
- [ ] dark mode 切换工作正常
- [ ] Settings 面板能开/关 + 修改 claude path / username 持久化
- [ ] tsc 0 error，vitest 全 PASS
- [ ] git log 显示切片 2 ~11 个 commit

---

## 切片 3: 系统级 features（1-2 天）

**目标：** Tray icon + 全局快捷键 + 自启动 + 桌面通知 action。

### Task 3.1: Tray icon

**Files:**
- Create: `E:\agent\omni-desktop\src\main\tray.ts`
- Modify: `src/main/main.ts` 调用 createTray

- [ ] **Step 1: tray.ts**

```typescript
// src/main/tray.ts
import { Tray, Menu, app, BrowserWindow, nativeImage } from 'electron'
import path from 'node:path'

let _tray: Tray | null = null

export function createTray(getMainWindow: () => BrowserWindow | null): void {
  if (_tray) return
  const iconPath = path.join(__dirname, '../../build/icon.ico') // Win
  // Mac 用 16x16 模板图标更合适，先复用一个图
  const icon = nativeImage.createFromPath(iconPath)
  _tray = new Tray(icon.isEmpty() ? nativeImage.createEmpty() : icon)
  _tray.setToolTip('omni desktop')

  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示窗口',
      click: () => {
        const win = getMainWindow()
        if (win) {
          if (win.isMinimized()) win.restore()
          win.show()
          win.focus()
        }
      },
    },
    { type: 'separator' },
    { label: '退出', click: () => { app.quit() } },
  ])
  _tray.setContextMenu(contextMenu)
  _tray.on('click', () => {
    const win = getMainWindow()
    if (win) {
      if (win.isVisible()) win.hide()
      else { win.show(); win.focus() }
    }
  })
}

export function destroyTray(): void {
  if (_tray) {
    _tray.destroy()
    _tray = null
  }
}
```

- [ ] **Step 2: main.ts 集成 createTray**

```typescript
// 在 src/main/main.ts 顶部加 import：
import { createTray, destroyTray } from './tray'
// ... 在 whenReady 内 createMainWindow 之后加：
//   const getMainWin = () => BrowserWindow.getAllWindows()[0] || null
//   createTray(getMainWin)
// 在 before-quit 内加：
//   destroyTray()
```

具体补丁：

`src/main/main.ts` 完整版（替换之前）：

```typescript
import { app, BrowserWindow } from 'electron'
import { createMainWindow } from './window'
import { registerIpcHandlers } from './ipc-handler'
import { startRedisSubscriber, stopRedisSubscriber } from './redis-subscriber'
import { endPgPool } from './pg-client'
import { createTray, destroyTray } from './tray'

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const wins = BrowserWindow.getAllWindows()
    if (wins.length > 0) {
      const win = wins[0]
      if (win.isMinimized()) win.restore()
      win.show()
      win.focus()
    }
  })

  app.whenReady().then(() => {
    registerIpcHandlers()
    startRedisSubscriber()
    createMainWindow()
    createTray(() => BrowserWindow.getAllWindows()[0] || null)

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createMainWindow()
    })
  })

  // 关闭窗口不退出（让 tray 常驻）— 用户从 tray 退出
  app.on('window-all-closed', () => {
    // Mac 默认不退；Win 也保持 tray 在
    // 如果想保持原本行为：if (process.platform !== 'darwin') app.quit()
  })

  app.on('before-quit', async () => {
    destroyTray()
    await stopRedisSubscriber()
    await endPgPool()
  })
}
```

- [ ] **Step 3: 加占位 icon**

把 `E:\agent\omni\frontend\public\favicon.ico` (如有) 或随便一个 .ico 文件复制到 `E:\agent\omni-desktop\build\icon.ico`。占位用，后续切片 4 再做真 icon。

- [ ] **Step 4: smoke test**

```bash
npm run dev
```

任务栏右下角应该看到 omni icon，右键弹菜单"显示窗口 / 退出"。

- [ ] **Step 5: Commit**

```bash
git add src/main/tray.ts src/main/main.ts build/
git commit -m "feat(W5-C 切片 3.1): tray icon + 右键菜单 (显示窗口 / 退出)"
```

---

### Task 3.2: 全局快捷键

**Files:**
- Create: `E:\agent\omni-desktop\src\main\shortcut.ts`
- Modify: `src/main/main.ts`

- [ ] **Step 1: shortcut.ts**

```typescript
// src/main/shortcut.ts
import { globalShortcut, BrowserWindow } from 'electron'
import { getSettings } from './settings-store'

let _registered: string | null = null

export function registerGlobalShortcut(getMainWindow: () => BrowserWindow | null): void {
  const key = getSettings().globalShortcut
  if (_registered === key) return
  unregisterGlobalShortcut()
  try {
    const ok = globalShortcut.register(key, () => {
      const win = getMainWindow()
      if (!win) return
      if (win.isVisible() && win.isFocused()) {
        win.hide()
      } else {
        if (win.isMinimized()) win.restore()
        win.show()
        win.focus()
      }
    })
    if (ok) {
      _registered = key
      // eslint-disable-next-line no-console
      console.log('[shortcut] registered:', key)
    } else {
      // eslint-disable-next-line no-console
      console.warn('[shortcut] register failed (可能被占用):', key)
    }
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('[shortcut] error:', e)
  }
}

export function unregisterGlobalShortcut(): void {
  if (_registered) {
    globalShortcut.unregister(_registered)
    _registered = null
  }
}

export function unregisterAllShortcuts(): void {
  globalShortcut.unregisterAll()
  _registered = null
}
```

- [ ] **Step 2: main.ts 集成**

`src/main/main.ts` 加 import + 调用：

```typescript
import { registerGlobalShortcut, unregisterAllShortcuts } from './shortcut'

// 在 whenReady 内 createTray 之后加：
registerGlobalShortcut(() => BrowserWindow.getAllWindows()[0] || null)

// 在 before-quit 内加：
unregisterAllShortcuts()
```

- [ ] **Step 3: smoke test**

```bash
npm run dev
```

按 Ctrl+Shift+Space → 窗口 toggle 显示/隐藏。

- [ ] **Step 4: Commit**

```bash
git add src/main/shortcut.ts src/main/main.ts
git commit -m "feat(W5-C 切片 3.2): 全局快捷键 (Ctrl+Shift+Space toggle 窗口)"
```

---

### Task 3.3: 开机自启

**Files:**
- Create: `E:\agent\omni-desktop\src\main\autostart.ts`
- Modify: `src/main/main.ts`

- [ ] **Step 1: autostart.ts**

```typescript
// src/main/autostart.ts
import { app } from 'electron'
import { getSettings } from './settings-store'

export function applyAutostart(): void {
  const enabled = getSettings().autoStart
  app.setLoginItemSettings({
    openAtLogin: enabled,
    openAsHidden: true,  // 静默启动到 tray
  })
}

export function isAutostartEnabled(): boolean {
  return app.getLoginItemSettings().openAtLogin
}
```

- [ ] **Step 2: main.ts 集成**

```typescript
import { applyAutostart } from './autostart'

// 在 whenReady 内 registerGlobalShortcut 之后加：
applyAutostart()
```

- [ ] **Step 3: 让 settings IPC 改 autostart 时也调 applyAutostart**

`src/main/ipc-handler.ts` 的 `IPC_UPDATE_SETTINGS` handler 改成：

```typescript
import { applyAutostart } from './autostart'
import { registerGlobalShortcut } from './shortcut'

// ... 在 IPC_UPDATE_SETTINGS handler 改：
ipcMain.handle(IPC_UPDATE_SETTINGS, async (_e, patch: Partial<AppSettings>) => {
  const newSettings = updateSettings(patch)
  if ('autoStart' in patch) applyAutostart()
  if ('globalShortcut' in patch) {
    registerGlobalShortcut(() => BrowserWindow.getAllWindows()[0] || null)
  }
  return newSettings
})
```

- [ ] **Step 4: Commit**

```bash
git add src/main/autostart.ts src/main/main.ts src/main/ipc-handler.ts
git commit -m "feat(W5-C 切片 3.3): 开机自启 + settings 改时实时生效"
```

---

### Task 3.4: 关窗口 → 隐藏到 tray（不退出）

**Files:**
- Modify: `src/main/window.ts`

- [ ] **Step 1: 改 close 行为为 hide**

```typescript
// src/main/window.ts 改 createMainWindow:
import { BrowserWindow, app } from 'electron'
import path from 'node:path'

const isDev = !app.isPackaged
const RENDERER_DEV_URL = 'http://localhost:5173'

let _quitting = false

export function setQuitting(v: boolean): void { _quitting = v }

export function createMainWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    backgroundColor: '#ffffff',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })

  win.once('ready-to-show', () => win.show())

  // close → hide, 真退出 quit 行为通过 setQuitting + app.quit() 之前 setQuitting(true)
  win.on('close', (e) => {
    if (!_quitting) {
      e.preventDefault()
      win.hide()
    }
  })

  if (isDev) {
    win.loadURL(RENDERER_DEV_URL)
    win.webContents.openDevTools({ mode: 'detach' })
  } else {
    win.loadFile(path.join(__dirname, '../renderer/index.html'))
  }

  return win
}
```

- [ ] **Step 2: main.ts before-quit 触发 setQuitting**

```typescript
// src/main/main.ts 改 before-quit handler:
import { setQuitting } from './window'

app.on('before-quit', async () => {
  setQuitting(true)
  destroyTray()
  await stopRedisSubscriber()
  await endPgPool()
})
```

- [ ] **Step 3: tray "退出" 也走 app.quit() (已是)**

不用改，tray.ts 的"退出" click 调 `app.quit()` 会触发 before-quit → setQuitting(true) → 后续 close 不阻止 → 真退出。

- [ ] **Step 4: smoke test**

```bash
npm run dev
```

点窗口右上角 X → 窗口隐藏（不退出），tray icon 还在。点 tray 或按全局快捷键 → 重新显示。tray 右键退出 → 真退出。

- [ ] **Step 5: Commit**

```bash
git add src/main/window.ts src/main/main.ts
git commit -m "feat(W5-C 切片 3.4): 关窗口 = 隐藏到 tray，tray 退出才真退"
```

---

### 切片 3 验收

- [ ] tray icon 显示，右键菜单工作
- [ ] Ctrl+Shift+Space 全局快捷键工作
- [ ] settings 改 shortcut 后实时更新
- [ ] settings 改 autostart 后开机自启注册
- [ ] 关窗口 → 隐藏到 tray
- [ ] tray "退出" → 真退出
- [ ] git log 显示切片 3 ~4 commit

---

## 切片 4: 跨平台打包（1-2 天）

**目标：** electron-builder 配置好，能 `npm run pack:win` 出一个 NSIS 安装器，老板双击装。

### Task 4.1: electron-builder 配置

**Files:**
- Create: `E:\agent\omni-desktop\electron-builder.json`
- Modify: `package.json`

- [ ] **Step 1: electron-builder.json**

```json
{
  "appId": "com.omni-desktop.app",
  "productName": "omni",
  "directories": {
    "output": "release/${version}"
  },
  "files": [
    "dist-main/**/*",
    "dist-preload/**/*",
    "dist-renderer/**/*",
    "package.json",
    "node_modules/**/*",
    "!node_modules/**/test/**",
    "!node_modules/**/tests/**",
    "!node_modules/**/example/**",
    "!node_modules/**/.bin/**"
  ],
  "win": {
    "target": [
      { "target": "nsis", "arch": ["x64"] }
    ],
    "icon": "build/icon.ico"
  },
  "nsis": {
    "oneClick": false,
    "perMachine": false,
    "allowToChangeInstallationDirectory": true,
    "createDesktopShortcut": true,
    "createStartMenuShortcut": true,
    "shortcutName": "omni"
  },
  "mac": {
    "target": [
      { "target": "dmg", "arch": ["x64", "arm64"] }
    ],
    "icon": "build/icon.icns",
    "category": "public.app-category.productivity"
  }
}
```

- [ ] **Step 2: package.json 加打包 script**

```json
{
  "scripts": {
    "pack:win": "npm run build && electron-builder --win",
    "pack:mac": "npm run build && electron-builder --mac"
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add electron-builder.json package.json
git commit -m "feat(W5-C 切片 4.1): electron-builder 配置 (Win NSIS + Mac DMG)"
```

---

### Task 4.2: app icon 资源

**Files:**
- Create: `E:\agent\omni-desktop\build\icon.ico` (Win 256×256)
- Create: `E:\agent\omni-desktop\build\icon.png` (Linux fallback 512×512)
- (Optional) Create: `E:\agent\omni-desktop\build\icon.icns` (Mac, 后续做)

- [ ] **Step 1: 用 Logo SVG 导出图标**

Logo.tsx 的 SVG 内容用工具导出（如 https://cloudconvert.com/svg-to-ico）成：
- icon.ico (Win, 256×256 + 128×128 + 64×64 + 32×32 + 16×16 multi-size)
- icon.png (Linux fallback)

或者老板手动用 Figma / Sketch 设计 icon 直接生成。

**起步**：先随便复制一个 .ico 占位（如 `E:\agent\omni\frontend\public\favicon.ico`，如果存在）：

```bash
cp E:/agent/omni/frontend/public/favicon.ico E:/agent/omni-desktop/build/icon.ico
```

实际打包前手动替换为正式 icon。

- [ ] **Step 2: Commit 占位 icon**

```bash
git add build/icon.ico
git commit -m "chore(W5-C 切片 4.2): 占位 icon (后续替换为正式)"
```

---

### Task 4.3: build + pack:win

**Files:** 无新建，跑命令

- [ ] **Step 1: build**

```bash
cd E:/agent/omni-desktop
npm run build
```

Expected:
- `dist-main/main.js` 等存在
- `dist-preload/preload.js` 存在
- `dist-renderer/` Vite 构建产物

如果有 error：通常是 tsconfig path 问题或 import 路径错。修后重跑。

- [ ] **Step 2: pack:win**

```bash
npm run pack:win
```

Expected:
- 输出在 `release/0.1.0/`
- 文件：`omni Setup 0.1.0.exe` (NSIS 安装器)

第一次跑会下载 electron binaries（~80MB）。

- [ ] **Step 3: 双击安装器测试**

打开 `release/0.1.0/omni Setup 0.1.0.exe` → 走安装向导 → 装完桌面 + 开始菜单都有 omni 快捷方式 → 点开应用启动 → 看到 Welcome 屏。

- [ ] **Step 4: 卸载验证**

控制面板"程序与功能" 找到 omni → 卸载 → 双击 confirm → 完成。

- [ ] **Step 5: Commit 任何配置 fix**

如果上面跑通需要调 electron-builder.json 或修 build issue，commit fix：

```bash
git add electron-builder.json package.json src/
git commit -m "chore(W5-C 切片 4.3): 打包 pack:win 跑通 + bug fix"
```

---

### 切片 4 验收

- [ ] `npm run pack:win` 出 NSIS 安装器
- [ ] 安装器双击安装成功
- [ ] 装完启动看到 omni Welcome 屏
- [ ] 卸载干净
- [ ] git log 显示切片 4 ~3 commit

---

## 切片 5: 收尾 + 文档（1 天）

**目标：** omni-vibe 仓库的 /chat 改名 + omni-desktop README 完善 + e2e smoke 通过。

### Task 5.1: omni-vibe sidebar /chat 改名

**Files:**
- Modify: `E:\agent\omni\frontend\src\components\app-sidebar.tsx`

- [ ] **Step 1: 找 sidebar 中的 /chat 项**

Run: `grep -n "Agent 对话\|/chat" E:/agent/omni/frontend/src/components/app-sidebar.tsx`

应该看到 W5-B 切片 2.9 改过的那行：
```tsx
{ href: '/chat', icon: Brain, label: 'Agent 对话', hint: '跟 Claude 自然语言聊天，自动调 omni tool 出结果' },
```

- [ ] **Step 2: 改 label / hint**

```tsx
{ href: '/chat', icon: Brain, label: 'Agent 对话（Web 版）', hint: '备用 web 入口；主用桌面 app（omni-desktop）' },
```

- [ ] **Step 3: Commit**

```bash
cd E:/agent/omni
git add frontend/src/components/app-sidebar.tsx
git commit -m "chore(W5-C 切片 5.1): sidebar /chat 改名 Agent 对话 (Web 版) — 主用 omni-desktop"
```

---

### Task 5.2: omni-desktop README 完善

**Files:**
- Modify: `E:\agent\omni-desktop\README.md`

- [ ] **Step 1: 写完整 README**

```markdown
# omni-desktop

omni agent chat 桌面 app（Electron + Gemini 风 UI），是 [omni-vibe](https://github.com/252180478yark-lang/omni) AI 工作台的本机入口。

## 截图

(后续补)

## 装机前置

1. **本机装 Claude Code CLI**：[官方文档](https://docs.anthropic.com/en/docs/claude-code)
   - 装完 `claude --version` 能跑
   - 已用 Max 订阅登录 (`claude login`)
2. **omni 后端在跑**：参考 omni-vibe 项目 `dev-start.ps1` 或 `docker compose up -d`
   - postgres:5432 / knowledge-engine:8002 / redis:6379

## 装机

### Windows

下载 `omni Setup x.y.z.exe` (从 release/ 或 GitHub release) → 双击 → 装到默认路径 / 自定义路径都行 → 完成。

桌面 + 开始菜单有 omni 快捷方式。

### Mac

下载 `omni-x.y.z.dmg` → 拖 omni.app 到 Applications。

第一次打开提示"未签名"：右键 → 打开 → 仍要打开。

## 用法

### 启动

- 双击桌面快捷方式 / 应用列表
- 装完默认自启（可在 settings 关）
- 全局快捷键 `Ctrl+Shift+Space`（默认）随时召出 / 隐藏窗口
- tray 右键 → 退出

### 首次配置

1. 第一次打开 → settings 面板
2. **Claude CLI 路径**：通常自动 detect。检测失败时手填 `claude.cmd` 绝对路径
3. **后端 URL**：默认 `localhost`。omni 装在别处改成对应 host
4. **主题 / 用户名 / 全局快捷键** 按需

### 使用

- 左侧折叠侧栏（hover 展开）
- 「+ 新对话」开始一段 session
- Welcome 屏点 prompt 卡片或自己打字
- 附件按钮上传图 / 视频 / PDF
- Tool 调用过程实时可见（chip + 多模态附件）
- Human Gate（require_approval）的 tool 触发时对话流弹卡片，点通过 / 驳回

## 开发

### 环境

- Node 20+
- npm 10+
- 本机装好 Claude CLI（dev mode 也要 spawn）

### 跑 dev

```bash
git clone <repo> omni-desktop
cd omni-desktop
npm install
npm run dev
```

vite 跑在 5173，electron 自动连。改 renderer 代码 HMR；改 main 代码要重启 (Ctrl+C 后 `npm run dev`)。

### 打包

```bash
npm run pack:win    # Win NSIS
npm run pack:mac    # Mac DMG
```

输出在 `release/x.y.z/`。

### 测试

```bash
npm run test:unit
npm run test:e2e
```

## 架构

```
┌─────────────────────────────────────────────┐
│ Electron App (omni-desktop)                 │
│ ┌─────────────────────────────────────────┐ │
│ │ Renderer Process (Chromium + React)     │ │
│ │ • Gemini 风 UI                          │ │
│ │ • useAgentChat hook via IPC             │ │
│ └─────────────────────────────────────────┘ │
│         ↕ Electron IPC                      │
│ ┌─────────────────────────────────────────┐ │
│ │ Main Process (Node)                     │ │
│ │ • Claude CLI subprocess spawn           │ │
│ │ • Session manager (LRU + ttl)           │ │
│ │ • PG 直连 (mcp.agent_sessions)         │ │
│ │ • Redis subscribe (human gate)          │ │
│ │ • Tray + global shortcut + autostart    │ │
│ └─────────────────────────────────────────┘ │
└──────────────────┬──────────────────────────┘
                   │ HTTP + MCP
                   ▼
        omni docker stack (不动)
        - omni-postgres :5432
        - omni-knowledge-engine :8002 (MCP server)
        - omni-redis :6379
```

详见 `docs/architecture.md`（暂未写）。

## 许可

MIT
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(W5-C 切片 5.2): 完善 README (装机 / 用法 / 开发 / 架构)"
```

---

### Task 5.3: e2e smoke test (Playwright + Electron)

**Files:**
- Create: `E:\agent\omni-desktop\tests\e2e\smoke.spec.ts`
- Create: `E:\agent\omni-desktop\playwright.config.ts`

- [ ] **Step 1: playwright.config.ts**

```typescript
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  timeout: 60000,
})
```

- [ ] **Step 2: smoke.spec.ts (Electron e2e)**

```typescript
import { test, expect, _electron as electron } from '@playwright/test'
import path from 'node:path'

test('omni-desktop launches and shows welcome screen', async () => {
  const app = await electron.launch({
    args: [path.join(__dirname, '../..')],
    timeout: 30000,
  })
  const window = await app.firstWindow()
  // 等 React 渲染
  await window.waitForSelector('text=/早上好|中午好|下午好|晚上好|你好/', { timeout: 30000 })
  await expect(window.locator('text=/今天想跟 omni 聊点啥/')).toBeVisible()
  await app.close()
})

test('omni-desktop can open settings panel', async () => {
  const app = await electron.launch({ args: [path.join(__dirname, '../..')], timeout: 30000 })
  const window = await app.firstWindow()
  await window.waitForSelector('aside', { timeout: 30000 })
  // hover sidebar 展开
  await window.locator('aside').hover()
  // 点 settings 图标
  await window.locator('button[title="设置"]').click()
  await expect(window.locator('text=设置')).toBeVisible()
  await app.close()
})
```

- [ ] **Step 3: 跑 e2e**

```bash
cd E:/agent/omni-desktop
npm run build  # 先 build，e2e 跑 dist
npx playwright test
```

Expected: 2 测试 PASS。

注：第一次跑可能需要 `npx playwright install chromium`。

如果 build mode e2e 失败，可以改 dev mode 跑（修改 args 指向 vite dev URL）。但 dev mode e2e 依赖 vite 起着，复杂。

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/ playwright.config.ts
git commit -m "feat(W5-C 切片 5.3): Playwright e2e smoke (Electron launch + welcome screen + settings)"
```

---

### Task 5.4: omni-vibe memory 更新 W5-C 状态

**Files:**
- Modify: `C:\Users\Administrator\.claude\projects\E--agent-omni\memory\project_omni_agent_uplift_status.md`
- Modify: `C:\Users\Administrator\.claude\projects\E--agent-omni\memory\MEMORY.md`

- [ ] **Step 1: 在 project_omni_agent_uplift_status.md 末尾追加 §四十五 W5-C 切片**

参考 W5-B 切片 §四十四 的格式，追加：

```markdown
## 四十五、W5-C: omni-desktop Electron App（2026-05-15-2026-05-XX）

W5-B 的 web 版 /chat 完工后老板拍板"单独拎出来做桌面 app（Gemini 风）"，新建独立 git repo `E:\agent\omni-desktop\`。

### 关键决策

- 技术栈：Electron + TS + React + Vite（renderer dev）+ Tailwind
- 复用率：W5-B 25 commit 约 70% 移植到 main process 和 renderer 底层组件
- UI 风格：Gemini 风（克制几何 + 冷调 + 折叠侧栏 + welcome quick prompts + floating 输入框）
- 项目位置：独立 git repo，跟 omni-vibe 解耦
- omni 后端不动：docker compose 继续跑

### 5 切片完成

- 切片 1: Electron 骨架 + IPC + 后端逻辑移植 (~14 commit)
- 切片 2: Gemini 风 UI (~11 commit)
- 切片 3: 系统级 features (tray + shortcut + autostart) (~4 commit)
- 切片 4: 跨平台打包 (Win NSIS + Mac DMG) (~3 commit)
- 切片 5: 收尾 + 文档 + e2e (~4 commit)

总计 ~36 commit。

### 老板下一步

- 装 release/0.1.0/omni Setup 0.1.0.exe 到 Win 11，双击启动
- 配 settings (claude CLI 路径自动 detect)
- Welcome 屏点 prompt 卡片或自己打字开始
- 全局快捷键 Ctrl+Shift+Space 召出

### /clear 后老板话术 → 找位置

- "桌面 app 打包不出来" → §四十五 切片 4 / electron-builder.json
- "全局快捷键不工作" → §四十五 切片 3.2 / src/main/shortcut.ts
- "Welcome 屏 4 个 prompt 怎么改" → §四十五 切片 2.7 / src/renderer/components/WelcomeScreen.tsx 中 SUGGESTIONS 数组
- "Gemini 风设计 token 在哪改" → §四十五 切片 1.4 / src/renderer/styles/gemini-tokens.css
```

- [ ] **Step 2: 更新 MEMORY.md 索引**

把 project_omni_agent_uplift_status.md 那条 hook 更新指向 §四十五：

```markdown
- [Omni Agent 化升级 (X 方案) 当前状态](project_omni_agent_uplift_status.md) — W1→W5-C omni-desktop 桌面 app 完成（HEAD `xxxxx` clean）。... (按之前 W5-B 描述追加 W5-C: Electron + Gemini 风 + 36 commit 独立 repo `E:\agent\omni-desktop\`)；/clear 后查 §四十五
```

- [ ] **Step 3: 不 commit（memory 文件，~/.claude/projects 下不是 git tracked）**

---

### 切片 5 验收

- [ ] omni-vibe sidebar /chat 改名"Agent 对话（Web 版）"
- [ ] omni-desktop README 完整（装机 / 用法 / 开发 / 架构）
- [ ] Playwright e2e smoke 通过
- [ ] memory 状态档 §四十五 写完
- [ ] git log（omni-desktop 仓库）显示总 ~36 commit
- [ ] git log（omni-vibe 仓库）多 1 个 commit（sidebar 改名）

---

## 整体验收（5 切片全完）

- [ ] Win 装机：双击 `omni Setup 0.1.0.exe` → 装到桌面 → 双击启动 → 看到 Gemini 风 Welcome 屏
- [ ] Welcome 屏 4 个 prompt 卡片可点 → 自动建 session + 触发
- [ ] 侧栏默认折叠为图标条，hover 展开 240px 显示 session list
- [ ] dark mode toggle 工作（settings 内 / sidebar 底部按钮）
- [ ] Settings 面板可改 claude CLI 路径 / 全局快捷键 / 主题 / 后端 URL
- [ ] 全局 Ctrl+Shift+Space 工作（窗口 toggle）
- [ ] tray icon 右键菜单（显示窗口 / 退出）+ 点击 toggle 工作
- [ ] 关窗口 → 隐藏到 tray（不退出）
- [ ] 一段完整对话跑通：「跑通 SKU-367991-0002 全链路」→ tool_call chip 多个 + tool_result 多模态附件 + human gate 卡片 + 完成时桌面通知
- [ ] 切换 session 历史完整恢复（读 Claude jsonl）
- [ ] 关 app 重开 session list 还在（PG 持久化）
- [ ] 单测全 PASS (claude-cli-detector + settings-store + pg-client + useAgentChat)
- [ ] Playwright e2e smoke 全 PASS

---

## 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| 1 | Electron app 启动慢（首次 1-2s） | 加 splash screen 改善感知；Electron 9 后启动已优化 |
| 2 | Claude CLI 不在 PATH，自动 detect 失败 | 切片 1.8 detector 多候选路径 + settings 手填兜底 |
| 3 | omni 后端没启动（postgres / KE 不在） | app 启动时 health check + 提示老板先 `docker compose up` |
| 4 | electron-builder Win 打包卡在 native 依赖（pg / ioredis）| pg / ioredis 都是 pure JS，无 native binary，无需 rebuild |
| 5 | 全局快捷键被其他 app 占用 | settings 改 shortcut + 注册失败 console.warn |
| 6 | Tray icon 在 Win/Mac/Linux 行为不一致 | Mac 用 template icon；Win 用彩色 ico；Linux 起步不测 |
| 7 | macOS 沙箱限制 spawn claude CLI | Mac 走 hardened runtime 时需 com.apple.security.cs.disable-library-validation entitlement，先不做（用户自己签 / 关沙箱） |
| 8 | 安装包体积 ~200MB | Electron 天生大，无解（除非换 Tauri 但 plan 已定 Electron）|
| 9 | dev mode HMR 主进程不 hot reload | 改 main 代码要 Ctrl+C + 重启；用 nodemon 可改善但先不做 |
| 10 | IPC 序列化大 ArrayBuffer（上传大视频）慢 | 起步 file size limit 50MB；后续可改 file path 传递（避免 buffer copy） |
| 11 | 多窗口未支持 | YAGNI，单窗口 + 多 session 已够 |
| 12 | omni 后端 URL 改了 / port 冲突 | settings 暴露 omniKeUrl / omniPgUrl / omniRedisUrl 三个可改 |

---

## Self-Review

**Spec coverage:**
- ✅ 技术栈 Electron + TS + React → 切片 1.1 + 1.2
- ✅ Gemini 风 UI（几何 logo / 折叠侧栏 / welcome / floating / 冷调 / dark mode）→ 切片 2.2-2.11
- ✅ 项目位置独立 repo → 切片 1.1
- ✅ omni 后端不动 → 整个 plan 不改 omni-vibe 后端
- ✅ /chat 改名"Web 版" → 切片 5.1
- ✅ contextIsolation + preload → 切片 1.12 + 1.13
- ✅ electron-builder → 切片 4.1
- ✅ IPC promise-based → 切片 1.11 + 1.13
- ✅ PG 直连 → 切片 1.7
- ✅ Claude CLI auto detect → 切片 1.8
- ✅ 不做 auto-update → plan 跳过，留风险表
- ✅ 不签代码 → plan 跳过
- ✅ electron-store settings → 切片 1.9
- ✅ 单窗口 → 切片 1.12
- ✅ 离线模式 → 风险表 #3 mention，UI 已能加载历史 jsonl
- ✅ Win 优先 → 切片 4.1 + 4.3
- ✅ 复用 W5-B 后端 → 切片 1.6
- ✅ 复用 W5-B 底层组件 → 切片 2.3 + 2.4 + 2.5
- ✅ 重写 layout 顶层 → 切片 2.6-2.11
- ✅ Tray + 全局快捷键 + 自启动 → 切片 3.1-3.3

**Placeholder scan:** 无 TBD / TODO / "implement later" / "Similar to Task N"。每个 step 含完整代码或完整命令。

**Type consistency:**
- `OmniDesktopApi`（preload）签名跟 ipc-handler 一致
- `AppSettings` 统一在 `@shared/types`，settings-store 和 preload 共用
- `RendererPushEvent` 5 kind（session_opened / chunk / task_done / error / human_gate_new）跟 useAgentChat hook 处理逻辑一致
- W5-B 复用文件（claude-runner / session-manager / history-reader / mcp-config）import 路径调整为 `@shared/types`，签名不变

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-15-omni-desktop-W5c-plan.md`. 两种 execution 选项：**

**1. Subagent-Driven（推荐）** — 每个 task 起 fresh subagent + task 之间停下来 review；快速迭代，主上下文不被工程细节淹没

**2. Inline Execution** — 在当前会话里跑，executing-plans skill 批量执行 + 检查点暂停

**选哪个？**
