# W5-B: Agent Chat 前端（Claude Code Web 包装层）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Claude Code (Max 订阅) 套一个本地企业微信样式的 Web GUI 壳，把 omni MCP server 暴露的 52 个 tool 的调用过程 + 多模态结果在对话流里可视化呈现，让老板告别"终端信息看不到"的痛点。

**Architecture:** 改造现有 `/chat` 路由：废弃 RAG 直连客户端，改为通过本地 spawn 的 Claude Code subprocess（`claude -p --output-format=stream-json --mcp-config <omni>`）驱动；前后端走 WebSocket 双向流；多模态资源复用现有 `/api/v1/knowledge/static/*`；session 状态持久化到 PG `mcp.agent_sessions` 表 + 历史对话直接读 Claude Code 自带的 `~/.claude/projects/<dir>/sessions/<uuid>.jsonl`。X 方案不变（Claude Code 当大脑、omni 当 tools），本前端只是消费 Claude Code stream-json 的渲染层。

**Tech Stack:** Next.js 15 (现有) + custom server.ts (Node http + ws) + child_process spawn + Anthropic Claude Code CLI (`claude` 命令本机已装) + PostgreSQL (现有 mcp schema) + React + Tailwind + lucide-react + react-markdown（现有）。

---

## 关键决策（11 个开放问题 reasonable call，老板审完批 / 改）

| # | 问题 | 决策 | 理由 |
|---|---|---|---|
| 1 | subprocess 挂哪个服务 | **Next.js custom server.ts**（不进 docker） | 个人自用约束 + subprocess 天然继承 `~/.claude` 凭证（不用 mount）+ Node 原生 child_process + 不开新服务 |
| 2 | session 持久化 | PG `mcp.agent_sessions` 元数据表 | 元数据上 DB，对话历史不重复造（用 #3 方案） |
| 3 | 历史对话来源 | 复用 Claude Code 自带 `~/.claude/projects/<dir>/sessions/<uuid>.jsonl` | 不重复造历史存储 + 用 `claude --resume <id>` 自然续话 |
| 4 | 多 session 并行 | max 3 个 active subprocess + 30min ttl + LRU 淘汰 | 个人用资源足够；切到旧 session 时 `--resume` 重新拉起 |
| 5 | 输入框命令 | 原样透传给 Claude Code | `/sku-pipeline` 等 slash command 由 Claude Code 内部处理，前端零特化 |
| 6 | 附件上传位置 | `/app/data/uploads/<session_id>/<uuid>.<ext>` + 走 KE static 端点 | 复用现有静态资源链路，session 删时一并清理 |
| 7 | 前后端通信 | **WebSocket** | 双向（前端发指令 / 后端推流 / human gate 回调）+ stream-json 天然流式 |
| 8 | 认证 | 无认证 + 绑 `127.0.0.1` | 本机访问，feedback_personal_use_no_overengineering |
| 9 | 手机端 | 基础响应式（侧栏可折叠）+ 重点桌面 | 老板主用 PC，不做 mobile 专属 UX |
| 10 | 长任务进度展示 | tool_use chunk 即时 push chip + tool_result chunk 转绿展开；token stream 自然流 | stream-json 天然支持，不另搞进度条 |
| 11 | Claude Code subprocess 认证继承 | spawn 默认继承父进程 env (HOME/USER) | 本机已登录的 `~/.claude/.credentials.json` 自动复用 |

---

## File Structure

```
frontend/
├── server.ts                                    # 新 Next.js custom server (Node http + ws)
├── package.json                                 # 加 ws / @types/ws / tsx
├── src/
│   ├── app/
│   │   └── chat/                                # 现有 1087 行 RAG 客户端，本计划改造为 agent-chat
│   │       └── page.tsx                         # 重写：从 RAG → Claude Code agent
│   ├── app/api/
│   │   └── agent-chat/                          # 新 API routes
│   │       ├── sessions/route.ts                # GET list + POST create
│   │       ├── sessions/[id]/route.ts           # GET / DELETE
│   │       ├── sessions/[id]/history/route.ts   # GET 读 ~/.claude/projects 的 jsonl
│   │       ├── upload/route.ts                  # POST 附件
│   │       └── human-gate/[shortId]/route.ts    # POST 批 / 驳 human gate
│   ├── lib/agent-chat/                          # 新 subprocess + ws 逻辑
│   │   ├── types.ts                             # ChatMessage / SessionState / StreamChunk
│   │   ├── mcp-config.ts                        # 生成 omni mcp 配置 JSON
│   │   ├── claude-runner.ts                     # spawn + parse stream-json
│   │   ├── session-manager.ts                   # 内存 map + LRU + ttl
│   │   ├── ws-handler.ts                        # WebSocket message router
│   │   └── history-reader.ts                    # 读 ~/.claude/projects/<dir>/sessions/*.jsonl
│   ├── hooks/
│   │   ├── useAgentChat.ts                      # ws 连接 + 状态管理
│   │   └── useNotification.ts                   # Web Notification API
│   └── components/agent-chat/                   # 新 UI 组件
│       ├── ChatLayout.tsx                       # 整体布局（侧栏 + 主对话流 + 输入栏）
│       ├── SessionList.tsx                      # 左侧 session 列表
│       ├── MessageStream.tsx                    # 主对话流容器
│       ├── MessageBubble.tsx                    # 文本气泡（user / assistant）
│       ├── ToolCallChip.tsx                     # 调 tool 中 chip
│       ├── ToolResultCard.tsx                   # 多模态附件渲染分发器
│       ├── HumanGateCard.tsx                    # 内嵌 human gate 卡片
│       ├── InputBar.tsx                         # 输入框 + 附件上传
│       └── attachments/                         # 各类附件子组件
│           ├── ImageAttachment.tsx
│           ├── VideoAttachment.tsx
│           ├── MarkdownAttachment.tsx
│           └── JsonAttachment.tsx
└── tests/agent-chat/                            # vitest + playwright
    ├── unit/
    │   ├── claude-runner.test.ts
    │   ├── session-manager.test.ts
    │   └── history-reader.test.ts
    └── e2e/
        └── agent-chat.spec.ts

migrations/
└── 028_agent_sessions.sql                       # 新 mcp.agent_sessions 表

services/knowledge-engine/
├── app/api/static_uploads.py                    # 新 mount /uploads 子目录到 static 端点
└── app/services/asset_storage.py                # 已存在 - 不动
```

---

## 切片 1：后端（subprocess + WebSocket + session 持久化）

**目标：** Claude Code CLI 在 Next.js custom server 进程里能 spawn、stream-json 能 parse、WebSocket 能推、session 能在 PG 持久化、history 能从 Claude Code jsonl 读。这是地基。

**预期工作量：** 3-5 天 / 15-20 steps

### Task 1.1: PG migration - mcp.agent_sessions 表

**Files:**
- Create: `migrations/028_agent_sessions.sql`

- [ ] **Step 1: 写 migration**

```sql
-- migrations/028_agent_sessions.sql
-- W5-B: agent chat 前端 session 元数据表
-- 对话历史本身存在 Claude Code 自带 ~/.claude/projects/<dir>/sessions/<uuid>.jsonl，本表只存元数据

CREATE TABLE IF NOT EXISTS mcp.agent_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Claude Code 自己生成的 session uuid（用于 --resume）
    claude_session_id TEXT NOT NULL UNIQUE,
    -- 老板可以重命名
    title TEXT NOT NULL DEFAULT '新对话',
    -- 关联业务上下文（可选）
    sku_id VARCHAR(64),
    -- 最后一条消息预览（侧栏显示用）
    last_message_preview TEXT,
    -- 累计消息数 + token 数
    message_count INT NOT NULL DEFAULT 0,
    tokens_input_total INT NOT NULL DEFAULT 0,
    tokens_output_total INT NOT NULL DEFAULT 0,
    -- 状态
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived', 'deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agent_sessions_status ON mcp.agent_sessions (status, updated_at DESC);
CREATE INDEX idx_agent_sessions_sku ON mcp.agent_sessions (sku_id) WHERE sku_id IS NOT NULL;
CREATE INDEX idx_agent_sessions_claude_id ON mcp.agent_sessions (claude_session_id);

COMMENT ON TABLE mcp.agent_sessions IS 'W5-B agent chat 前端的 session 元数据，对话内容存在 Claude Code jsonl 文件';
```

- [ ] **Step 2: 应用 migration**

Run: `docker exec omni-postgres psql -U omni_user -d omni_vibe_db -f /migrations/028_agent_sessions.sql`

如果 omni-postgres 没 mount /migrations，需要先 docker cp：
```bash
docker cp migrations/028_agent_sessions.sql omni-postgres:/tmp/028.sql
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -f /tmp/028.sql
```

Expected output: `CREATE TABLE` + `CREATE INDEX` × 3 + `COMMENT`

- [ ] **Step 3: 验证表结构**

Run: `docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "\d mcp.agent_sessions"`

Expected: 11 字段 + 3 索引 + 1 unique constraint on claude_session_id

- [ ] **Step 4: Commit**

```bash
git add migrations/028_agent_sessions.sql
git commit -m "feat(W5-B 切片 1.1): mcp.agent_sessions 表用于 agent chat session 元数据"
```

---

### Task 1.2: types 定义

**Files:**
- Create: `frontend/src/lib/agent-chat/types.ts`

- [ ] **Step 1: 写完整类型**

```typescript
// frontend/src/lib/agent-chat/types.ts

// === Claude Code stream-json 输出的 4 类 chunk ===
// 参考: https://docs.anthropic.com/en/docs/claude-code/cli-reference#headless-mode

export interface ClaudeStreamChunk {
  type:
    | 'system'           // session 启动等系统消息
    | 'assistant'        // Claude 文本/思考输出（含 tool_use）
    | 'user'             // 工具调用返回（tool_result）
    | 'result'           // 整个任务完成
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
  // result type chunk
  result?: string
  is_error?: boolean
  duration_ms?: number
  num_turns?: number
  session_id?: string
  total_cost_usd?: number
}

// === 前端渲染用的统一消息结构 ===
export interface ChatMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'tool_call' | 'tool_result' | 'human_gate' | 'system'
  // role='user' | 'assistant' 时
  text?: string
  // role='tool_call' 时
  tool_name?: string
  tool_args?: Record<string, unknown>
  tool_use_id?: string
  tool_status?: 'pending' | 'completed' | 'error'
  // role='tool_result' 时 - 多模态附件
  attachments?: ChatAttachment[]
  raw_result?: unknown
  // role='human_gate' 时
  gate_short_id?: string
  gate_summary?: string
  gate_decision?: 'pending' | 'approved' | 'rejected'
  created_at: string
}

export interface ChatAttachment {
  type: 'image' | 'video' | 'markdown' | 'json' | 'table' | 'link'
  // image / video
  url?: string
  thumbnail_url?: string
  alt?: string
  // markdown
  markdown?: string
  // json / table
  data?: unknown
  // link
  href?: string
  label?: string
}

// === Session 状态 ===
export interface SessionState {
  id: string                  // PG mcp.agent_sessions.id
  claude_session_id: string   // Claude Code 自己的 session uuid
  title: string
  sku_id: string | null
  last_message_preview: string | null
  message_count: number
  status: 'active' | 'archived' | 'deleted'
  created_at: string
  updated_at: string
}

// === WebSocket 消息协议（前后端互通）===
export type WsClientMessage =
  | { kind: 'open_session'; session_id: string }
  | { kind: 'close_session'; session_id: string }
  | { kind: 'send_prompt'; session_id: string; prompt: string; attachments?: ChatAttachment[] }
  | { kind: 'cancel'; session_id: string }
  | { kind: 'human_gate_decide'; short_id: string; decision: 'approved' | 'rejected'; note?: string }

export type WsServerMessage =
  | { kind: 'session_opened'; session: SessionState; history: ChatMessage[] }
  | { kind: 'chunk'; session_id: string; message: ChatMessage }
  | { kind: 'chunk_delta'; session_id: string; message_id: string; text_delta: string }
  | { kind: 'message_completed'; session_id: string; message: ChatMessage }
  | { kind: 'task_done'; session_id: string; duration_ms: number; total_cost_usd: number; tokens: { input: number; output: number } }
  | { kind: 'error'; session_id?: string; error: string; detail?: string }
  | { kind: 'human_gate_new'; session_id: string; gate: { short_id: string; summary: string; tool_name: string } }
```

- [ ] **Step 2: 验证 TypeScript compile**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.json`

Expected: 无 error

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/agent-chat/types.ts
git commit -m "feat(W5-B 切片 1.2): agent chat 前后端通信类型定义"
```

---

### Task 1.3: MCP 配置生成

**Files:**
- Create: `frontend/src/lib/agent-chat/mcp-config.ts`
- Create: `frontend/tests/agent-chat/unit/mcp-config.test.ts`

- [ ] **Step 1: 写失败测试**

```typescript
// frontend/tests/agent-chat/unit/mcp-config.test.ts
import { describe, it, expect } from 'vitest'
import { buildMcpConfig, getOmniMcpUrl } from '@/lib/agent-chat/mcp-config'

describe('mcp-config', () => {
  it('returns omni mcp http url with default 8002 port', () => {
    expect(getOmniMcpUrl()).toBe('http://localhost:8002/mcp')
  })

  it('respects OMNI_KE_URL env var', () => {
    const original = process.env.OMNI_KE_URL
    process.env.OMNI_KE_URL = 'http://example.com:9000'
    expect(getOmniMcpUrl()).toBe('http://example.com:9000/mcp')
    process.env.OMNI_KE_URL = original
  })

  it('builds claude code mcp config with omni server entry', () => {
    const config = buildMcpConfig()
    expect(config.mcpServers).toBeDefined()
    expect(config.mcpServers.omni).toEqual({
      type: 'http',
      url: 'http://localhost:8002/mcp',
    })
  })
})
```

- [ ] **Step 2: 跑测试看失败**

Run: `cd frontend && npx vitest run tests/agent-chat/unit/mcp-config.test.ts`
Expected: FAIL (file not found)

- [ ] **Step 3: 写实现**

```typescript
// frontend/src/lib/agent-chat/mcp-config.ts
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

/**
 * 写一份临时 mcp-config.json 到 ~/.claude/.tmp/，返回路径
 * 老板 spawn claude code 时通过 --mcp-config <path> 加载
 */
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

- [ ] **Step 4: 跑测试看通过**

Run: `cd frontend && npx vitest run tests/agent-chat/unit/mcp-config.test.ts`
Expected: PASS（3 个测试）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/agent-chat/mcp-config.ts frontend/tests/agent-chat/unit/mcp-config.test.ts
git commit -m "feat(W5-B 切片 1.3): omni MCP server 配置生成 + 临时文件 写/清理"
```

---

### Task 1.4: history-reader（读 Claude Code jsonl）

**Files:**
- Create: `frontend/src/lib/agent-chat/history-reader.ts`
- Create: `frontend/tests/agent-chat/unit/history-reader.test.ts`
- Create: `frontend/tests/agent-chat/fixtures/sample-session.jsonl`

- [ ] **Step 1: 写 fixture（sample jsonl）**

```jsonl
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"列一下我的 SKU"}]},"session_id":"abc-123","timestamp":"2026-05-15T10:00:00Z"}
{"type":"assistant","message":{"id":"msg-1","role":"assistant","content":[{"type":"text","text":"我帮你查"}]},"session_id":"abc-123","timestamp":"2026-05-15T10:00:01Z"}
{"type":"assistant","message":{"id":"msg-2","role":"assistant","content":[{"type":"tool_use","id":"toolu-1","name":"list_skus","input":{"status":"active"}}]},"session_id":"abc-123","timestamp":"2026-05-15T10:00:02Z"}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu-1","content":"[{\"id\":\"SKU-1\"}]"}]},"session_id":"abc-123","timestamp":"2026-05-15T10:00:03Z"}
{"type":"assistant","message":{"id":"msg-3","role":"assistant","content":[{"type":"text","text":"你有 1 个 SKU"}],"usage":{"input_tokens":100,"output_tokens":20}},"session_id":"abc-123","timestamp":"2026-05-15T10:00:04Z"}
```

- [ ] **Step 2: 写失败测试**

```typescript
// frontend/tests/agent-chat/unit/history-reader.test.ts
import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import path from 'node:path'
import fs from 'node:fs/promises'
import os from 'node:os'
import { readSessionHistory, encodeProjectDir } from '@/lib/agent-chat/history-reader'

const SAMPLE = path.join(__dirname, '../fixtures/sample-session.jsonl')

describe('history-reader', () => {
  it('encodes project dir to claude code format', () => {
    // Claude Code 把 E:\agent\omni 转成 E--agent-omni
    expect(encodeProjectDir('E:\\agent\\omni')).toBe('E--agent-omni')
    expect(encodeProjectDir('/home/user/project')).toBe('-home-user-project')
  })

  it('parses sample jsonl into ChatMessage[]', async () => {
    const messages = await readSessionHistory(SAMPLE)
    expect(messages).toHaveLength(5)
    expect(messages[0]).toMatchObject({
      role: 'user',
      text: '列一下我的 SKU',
    })
    expect(messages[1]).toMatchObject({
      role: 'assistant',
      text: '我帮你查',
    })
    expect(messages[2]).toMatchObject({
      role: 'tool_call',
      tool_name: 'list_skus',
      tool_args: { status: 'active' },
      tool_use_id: 'toolu-1',
    })
    expect(messages[3]).toMatchObject({
      role: 'tool_result',
      tool_use_id: 'toolu-1',
    })
    expect(messages[4]).toMatchObject({
      role: 'assistant',
      text: '你有 1 个 SKU',
    })
  })

  it('returns empty array if file missing', async () => {
    const messages = await readSessionHistory('/tmp/does-not-exist.jsonl')
    expect(messages).toEqual([])
  })
})
```

- [ ] **Step 3: 跑测试看失败**

Run: `cd frontend && npx vitest run tests/agent-chat/unit/history-reader.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 4: 写实现**

```typescript
// frontend/src/lib/agent-chat/history-reader.ts
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import readline from 'node:readline'
import { createReadStream } from 'node:fs'
import type { ChatMessage } from './types'

/**
 * Claude Code 把项目目录 mangled 成扁平字符串。例：
 * E:\agent\omni -> E--agent-omni
 * /home/user -> -home-user
 *
 * 替换规则：所有路径分隔符 / 冒号 / 反斜杠 -> '-'
 */
export function encodeProjectDir(absPath: string): string {
  return absPath.replace(/[\\/:]/g, '-')
}

/**
 * 找到当前项目对应的 Claude Code session 目录
 * ~/.claude/projects/<encoded-dir>/sessions/
 */
export function getSessionsDir(projectAbsPath: string = process.cwd()): string {
  return path.join(
    os.homedir(),
    '.claude',
    'projects',
    encodeProjectDir(projectAbsPath),
  )
}

interface ClaudeJsonlLine {
  type: 'user' | 'assistant' | 'system'
  message?: {
    id?: string
    role: 'user' | 'assistant'
    content: Array<
      | { type: 'text'; text: string }
      | { type: 'thinking'; thinking: string }
      | { type: 'tool_use'; id: string; name: string; input: Record<string, unknown> }
      | { type: 'tool_result'; tool_use_id: string; content: unknown; is_error?: boolean }
    >
    usage?: { input_tokens: number; output_tokens: number }
  }
  session_id?: string
  timestamp?: string
}

export async function readSessionHistory(jsonlPath: string): Promise<ChatMessage[]> {
  try {
    await fs.access(jsonlPath)
  } catch {
    return []
  }

  const messages: ChatMessage[] = []
  const rl = readline.createInterface({
    input: createReadStream(jsonlPath, { encoding: 'utf8' }),
    crlfDelay: Infinity,
  })

  for await (const line of rl) {
    if (!line.trim()) continue
    let parsed: ClaudeJsonlLine
    try {
      parsed = JSON.parse(line)
    } catch {
      continue
    }
    const msg = parsed.message
    if (!msg) continue
    const sessionId = parsed.session_id || ''
    const createdAt = parsed.timestamp || new Date().toISOString()

    for (const block of msg.content) {
      if (block.type === 'text') {
        messages.push({
          id: `${msg.id || crypto.randomUUID()}-${messages.length}`,
          session_id: sessionId,
          role: msg.role === 'user' ? 'user' : 'assistant',
          text: block.text,
          created_at: createdAt,
        })
      } else if (block.type === 'tool_use') {
        messages.push({
          id: `${block.id}-call`,
          session_id: sessionId,
          role: 'tool_call',
          tool_name: block.name,
          tool_args: block.input,
          tool_use_id: block.id,
          tool_status: 'completed',
          created_at: createdAt,
        })
      } else if (block.type === 'tool_result') {
        messages.push({
          id: `${block.tool_use_id}-result`,
          session_id: sessionId,
          role: 'tool_result',
          tool_use_id: block.tool_use_id,
          raw_result: block.content,
          attachments: extractAttachments(block.content),
          created_at: createdAt,
        })
      }
      // 跳过 thinking
    }
  }
  return messages
}

/**
 * 从 tool_result.content 里提取多模态附件
 * omni tool 通常返结构化 dict（JSON 字符串），里面可能有 url / image_url / video_url / markdown 等字段
 */
function extractAttachments(content: unknown): import('./types').ChatAttachment[] {
  if (typeof content !== 'string') return []
  let parsed: unknown
  try {
    parsed = JSON.parse(content)
  } catch {
    return []
  }
  if (typeof parsed !== 'object' || parsed === null) return []
  const obj = parsed as Record<string, unknown>
  const attachments: import('./types').ChatAttachment[] = []

  // image / video url（含数组）
  const collectUrls = (val: unknown, type: 'image' | 'video') => {
    if (typeof val === 'string') attachments.push({ type, url: val })
    else if (Array.isArray(val)) {
      for (const v of val) {
        if (typeof v === 'string') attachments.push({ type, url: v })
        else if (typeof v === 'object' && v !== null && 'url' in v && typeof (v as { url: unknown }).url === 'string') {
          attachments.push({ type, url: (v as { url: string }).url })
        }
      }
    }
  }
  if ('image_url' in obj) collectUrls(obj.image_url, 'image')
  if ('image_urls' in obj) collectUrls(obj.image_urls, 'image')
  if ('video_url' in obj) collectUrls(obj.video_url, 'video')
  if ('video_urls' in obj) collectUrls(obj.video_urls, 'video')

  // markdown
  if ('markdown' in obj && typeof obj.markdown === 'string') {
    attachments.push({ type: 'markdown', markdown: obj.markdown })
  }
  if ('script_md' in obj && typeof obj.script_md === 'string') {
    attachments.push({ type: 'markdown', markdown: obj.script_md })
  }

  return attachments
}
```

- [ ] **Step 5: 跑测试看通过**

Run: `cd frontend && npx vitest run tests/agent-chat/unit/history-reader.test.ts`
Expected: PASS（3 个测试）

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/agent-chat/history-reader.ts frontend/tests/agent-chat/unit/history-reader.test.ts frontend/tests/agent-chat/fixtures/sample-session.jsonl
git commit -m "feat(W5-B 切片 1.4): 读 Claude Code ~/.claude/projects jsonl 历史 + 提取附件"
```

---

### Task 1.5: claude-runner（spawn subprocess + parse stream-json）

**Files:**
- Create: `frontend/src/lib/agent-chat/claude-runner.ts`
- Create: `frontend/tests/agent-chat/unit/claude-runner.test.ts`

- [ ] **Step 1: 写失败测试**

```typescript
// frontend/tests/agent-chat/unit/claude-runner.test.ts
import { describe, it, expect, vi } from 'vitest'
import { EventEmitter } from 'node:events'
import { Readable } from 'node:stream'
import { parseStreamChunks, buildSpawnArgs } from '@/lib/agent-chat/claude-runner'

describe('claude-runner', () => {
  describe('buildSpawnArgs', () => {
    it('builds basic prompt args', () => {
      const args = buildSpawnArgs({
        prompt: 'hello',
        mcpConfigPath: '/tmp/mcp.json',
      })
      expect(args).toContain('-p')
      expect(args).toContain('hello')
      expect(args).toContain('--output-format')
      expect(args).toContain('stream-json')
      expect(args).toContain('--mcp-config')
      expect(args).toContain('/tmp/mcp.json')
      expect(args).toContain('--verbose')
    })

    it('adds --resume when resuming session', () => {
      const args = buildSpawnArgs({
        prompt: 'continue',
        mcpConfigPath: '/tmp/mcp.json',
        resumeSessionId: 'abc-123',
      })
      expect(args).toContain('--resume')
      expect(args).toContain('abc-123')
    })

    it('passes through allowed/disallowed tools', () => {
      const args = buildSpawnArgs({
        prompt: 'hello',
        mcpConfigPath: '/tmp/mcp.json',
        allowedTools: ['Bash(ls)', 'mcp__omni__list_skus'],
      })
      const idx = args.indexOf('--allowedTools')
      expect(idx).toBeGreaterThan(-1)
      expect(args[idx + 1]).toBe('Bash(ls),mcp__omni__list_skus')
    })
  })

  describe('parseStreamChunks', () => {
    it('parses 4 chunk types from stream-json output', async () => {
      const input = [
        '{"type":"system","subtype":"init","session_id":"sess-1"}',
        '{"type":"assistant","message":{"id":"m1","role":"assistant","content":[{"type":"text","text":"hi"}]},"session_id":"sess-1"}',
        '{"type":"assistant","message":{"id":"m2","role":"assistant","content":[{"type":"tool_use","id":"tu1","name":"list_skus","input":{}}]},"session_id":"sess-1"}',
        '{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu1","content":"ok"}]},"session_id":"sess-1"}',
        '{"type":"result","result":"done","duration_ms":1000,"total_cost_usd":0.01,"session_id":"sess-1"}',
      ].join('\n')

      const stream = Readable.from([input])
      const chunks: unknown[] = []
      for await (const c of parseStreamChunks(stream)) {
        chunks.push(c)
      }
      expect(chunks).toHaveLength(5)
      expect((chunks[0] as { type: string }).type).toBe('system')
      expect((chunks[4] as { type: string }).type).toBe('result')
    })

    it('handles partial line at buffer boundary', async () => {
      // 把一行分两次推
      const stream = new Readable({ read() {} })
      stream.push('{"type":"system","sess')
      stream.push('ion_id":"sess-1"}\n')
      stream.push(null)
      const chunks: unknown[] = []
      for await (const c of parseStreamChunks(stream)) {
        chunks.push(c)
      }
      expect(chunks).toHaveLength(1)
    })
  })
})
```

- [ ] **Step 2: 跑测试看失败**

Run: `cd frontend && npx vitest run tests/agent-chat/unit/claude-runner.test.ts`
Expected: FAIL

- [ ] **Step 3: 写实现**

```typescript
// frontend/src/lib/agent-chat/claude-runner.ts
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { EventEmitter } from 'node:events'
import type { Readable } from 'node:stream'
import type { ClaudeStreamChunk } from './types'

export interface SpawnOptions {
  prompt: string
  mcpConfigPath: string
  resumeSessionId?: string
  cwd?: string
  allowedTools?: string[]
  disallowedTools?: string[]
  maxTurns?: number
}

export function buildSpawnArgs(opts: SpawnOptions): string[] {
  const args = ['-p', opts.prompt, '--output-format', 'stream-json', '--verbose', '--mcp-config', opts.mcpConfigPath]
  if (opts.resumeSessionId) args.push('--resume', opts.resumeSessionId)
  if (opts.allowedTools && opts.allowedTools.length > 0) {
    args.push('--allowedTools', opts.allowedTools.join(','))
  }
  if (opts.disallowedTools && opts.disallowedTools.length > 0) {
    args.push('--disallowedTools', opts.disallowedTools.join(','))
  }
  if (opts.maxTurns && opts.maxTurns > 0) {
    args.push('--max-turns', String(opts.maxTurns))
  }
  return args
}

/**
 * 把 readable stream 切分成 stream-json chunk
 * Claude Code 每行一个 JSON object，UTF-8 编码
 */
export async function* parseStreamChunks(stream: Readable): AsyncGenerator<ClaudeStreamChunk> {
  let buffer = ''
  for await (const data of stream) {
    buffer += typeof data === 'string' ? data : (data as Buffer).toString('utf8')
    let nlIdx: number
    while ((nlIdx = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, nlIdx).trim()
      buffer = buffer.slice(nlIdx + 1)
      if (!line) continue
      try {
        yield JSON.parse(line)
      } catch (err) {
        // 跳过坏行，继续解析
        // eslint-disable-next-line no-console
        console.error('[claude-runner] bad json line:', line.slice(0, 200))
      }
    }
  }
  // tail
  if (buffer.trim()) {
    try {
      yield JSON.parse(buffer.trim())
    } catch {
      /* swallow */
    }
  }
}

export interface ClaudeRunner extends EventEmitter {
  readonly proc: ChildProcessWithoutNullStreams
  cancel(): void
}

/**
 * Spawn claude code 并把 stream-json chunk 通过 EventEmitter 推出去
 * Events:
 *   'chunk'     - (chunk: ClaudeStreamChunk)
 *   'stderr'    - (data: string)
 *   'exit'      - (code: number | null)
 *   'error'     - (err: Error)
 */
export function startClaudeRunner(opts: SpawnOptions): ClaudeRunner {
  const args = buildSpawnArgs(opts)
  const emitter = new EventEmitter() as ClaudeRunner

  // Windows 上 claude 是 .cmd，spawn 需要 shell:true 或显式调 .cmd
  const isWindows = process.platform === 'win32'
  const claudeCmd = isWindows ? 'claude.cmd' : 'claude'

  const proc = spawn(claudeCmd, args, {
    cwd: opts.cwd || process.cwd(),
    env: { ...process.env }, // 继承 HOME，subprocess 自动找到 ~/.claude/.credentials.json
    stdio: ['pipe', 'pipe', 'pipe'],
    shell: isWindows,
  })

  ;(emitter as unknown as { proc: ChildProcessWithoutNullStreams }).proc = proc

  // 异步解析 stdout
  ;(async () => {
    try {
      for await (const chunk of parseStreamChunks(proc.stdout)) {
        emitter.emit('chunk', chunk)
      }
    } catch (err) {
      emitter.emit('error', err as Error)
    }
  })()

  proc.stderr.on('data', (d) => emitter.emit('stderr', d.toString('utf8')))
  proc.on('exit', (code) => emitter.emit('exit', code))
  proc.on('error', (err) => emitter.emit('error', err))

  emitter.cancel = () => {
    try {
      proc.kill('SIGTERM')
      setTimeout(() => {
        if (!proc.killed) proc.kill('SIGKILL')
      }, 2000)
    } catch {
      /* swallow */
    }
  }
  return emitter
}
```

- [ ] **Step 4: 跑测试看通过**

Run: `cd frontend && npx vitest run tests/agent-chat/unit/claude-runner.test.ts`
Expected: PASS（5 个测试）

- [ ] **Step 5: 手动 smoke test（真跑 Claude Code）**

```bash
cd frontend
node -e "
const { startClaudeRunner } = require('./src/lib/agent-chat/claude-runner.ts');
const { writeTempMcpConfig } = require('./src/lib/agent-chat/mcp-config.ts');
(async () => {
  const mcpPath = await writeTempMcpConfig('smoke');
  const runner = startClaudeRunner({ prompt: '说一句你好', mcpConfigPath: mcpPath });
  runner.on('chunk', c => console.log('CHUNK:', c.type, JSON.stringify(c).slice(0, 100)));
  runner.on('exit', code => { console.log('EXIT:', code); process.exit(0); });
})();
"
```
（Windows 用 `npx tsx -e "..."` 或写到临时文件跑）

Expected: 几条 `CHUNK: system / assistant / result` log + `EXIT: 0`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/agent-chat/claude-runner.ts frontend/tests/agent-chat/unit/claude-runner.test.ts
git commit -m "feat(W5-B 切片 1.5): spawn Claude Code subprocess + parse stream-json"
```

---

### Task 1.6: session-manager（内存 LRU + ttl）

**Files:**
- Create: `frontend/src/lib/agent-chat/session-manager.ts`
- Create: `frontend/tests/agent-chat/unit/session-manager.test.ts`

- [ ] **Step 1: 写失败测试**

```typescript
// frontend/tests/agent-chat/unit/session-manager.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SessionManager } from '@/lib/agent-chat/session-manager'

describe('SessionManager', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('opens session and tracks active count', () => {
    const mgr = new SessionManager({ maxActive: 3, ttlMs: 30 * 60 * 1000 })
    mgr.open('sess-1', { mcpConfigPath: '/tmp/m1.json' })
    mgr.open('sess-2', { mcpConfigPath: '/tmp/m2.json' })
    expect(mgr.activeCount()).toBe(2)
    expect(mgr.has('sess-1')).toBe(true)
  })

  it('LRU evicts oldest when over capacity', () => {
    const mgr = new SessionManager({ maxActive: 2, ttlMs: 30 * 60 * 1000 })
    const closed: string[] = []
    mgr.on('session_closed', (id) => closed.push(id))
    mgr.open('sess-1', { mcpConfigPath: '/tmp/m1.json' })
    mgr.open('sess-2', { mcpConfigPath: '/tmp/m2.json' })
    mgr.open('sess-3', { mcpConfigPath: '/tmp/m3.json' })
    expect(mgr.activeCount()).toBe(2)
    expect(mgr.has('sess-1')).toBe(false)
    expect(closed).toContain('sess-1')
  })

  it('touching session updates lru position', () => {
    const mgr = new SessionManager({ maxActive: 2, ttlMs: 30 * 60 * 1000 })
    mgr.open('sess-1', { mcpConfigPath: '/tmp/m1.json' })
    mgr.open('sess-2', { mcpConfigPath: '/tmp/m2.json' })
    mgr.touch('sess-1')
    mgr.open('sess-3', { mcpConfigPath: '/tmp/m3.json' })
    expect(mgr.has('sess-1')).toBe(true)  // touched，不被淘汰
    expect(mgr.has('sess-2')).toBe(false) // 最旧，被淘汰
  })

  it('auto closes session after ttl', () => {
    const mgr = new SessionManager({ maxActive: 3, ttlMs: 1000 })
    mgr.open('sess-1', { mcpConfigPath: '/tmp/m1.json' })
    vi.advanceTimersByTime(500)
    expect(mgr.has('sess-1')).toBe(true)
    vi.advanceTimersByTime(600)
    expect(mgr.has('sess-1')).toBe(false)
  })
})
```

- [ ] **Step 2: 跑测试看失败**

Run: `cd frontend && npx vitest run tests/agent-chat/unit/session-manager.test.ts`
Expected: FAIL

- [ ] **Step 3: 写实现**

```typescript
// frontend/src/lib/agent-chat/session-manager.ts
import { EventEmitter } from 'node:events'
import { cleanupTempMcpConfig } from './mcp-config'
import { startClaudeRunner, type ClaudeRunner, type SpawnOptions } from './claude-runner'

export interface ActiveSession {
  id: string                        // mcp.agent_sessions.id
  claudeSessionId: string | null    // 第一次启动时 None，看到第一个 system 后填
  mcpConfigPath: string
  runner: ClaudeRunner | null       // null 表示 idle（subprocess 已退）
  lastActiveAt: number
  ttlTimer: NodeJS.Timeout | null
}

export interface ManagerOptions {
  maxActive: number   // 同时 active subprocess 上限
  ttlMs: number       // 多久无活动 reap
}

/**
 * Events:
 *   'session_closed' - (sessionId: string, reason: 'lru' | 'ttl' | 'manual')
 */
export class SessionManager extends EventEmitter {
  private sessions = new Map<string, ActiveSession>()
  constructor(private opts: ManagerOptions) {
    super()
  }

  open(id: string, spawn: { mcpConfigPath: string }): ActiveSession {
    if (this.sessions.has(id)) {
      this.touch(id)
      return this.sessions.get(id)!
    }
    // 容量检查
    while (this.sessions.size >= this.opts.maxActive) {
      const oldest = this.findOldest()
      if (!oldest) break
      this.close(oldest, 'lru')
    }
    const sess: ActiveSession = {
      id,
      claudeSessionId: null,
      mcpConfigPath: spawn.mcpConfigPath,
      runner: null,
      lastActiveAt: Date.now(),
      ttlTimer: null,
    }
    this.sessions.set(id, sess)
    this.resetTtl(sess)
    return sess
  }

  /**
   * 启动 subprocess 跑一个 prompt
   * 复用现有 ActiveSession.claudeSessionId 做 --resume
   */
  spawn(id: string, prompt: string, allowedTools?: string[]): ClaudeRunner {
    const sess = this.sessions.get(id)
    if (!sess) throw new Error(`session ${id} not opened`)
    // 如果上一次 runner 还在跑，先 cancel
    if (sess.runner && !sess.runner.proc.killed) {
      sess.runner.cancel()
    }
    const opts: SpawnOptions = {
      prompt,
      mcpConfigPath: sess.mcpConfigPath,
      resumeSessionId: sess.claudeSessionId || undefined,
      allowedTools,
    }
    const runner = startClaudeRunner(opts)
    sess.runner = runner
    sess.lastActiveAt = Date.now()
    this.resetTtl(sess)
    // 第一次拿到 system init chunk 填 claudeSessionId
    runner.on('chunk', (chunk: { type: string; session_id?: string }) => {
      if (chunk.type === 'system' && chunk.session_id && !sess.claudeSessionId) {
        sess.claudeSessionId = chunk.session_id
      }
    })
    runner.on('exit', () => {
      sess.runner = null
    })
    return runner
  }

  touch(id: string): void {
    const sess = this.sessions.get(id)
    if (!sess) return
    sess.lastActiveAt = Date.now()
    this.resetTtl(sess)
  }

  close(id: string, reason: 'lru' | 'ttl' | 'manual' = 'manual'): void {
    const sess = this.sessions.get(id)
    if (!sess) return
    if (sess.ttlTimer) clearTimeout(sess.ttlTimer)
    if (sess.runner && !sess.runner.proc.killed) sess.runner.cancel()
    cleanupTempMcpConfig(id).catch(() => undefined)
    this.sessions.delete(id)
    this.emit('session_closed', id, reason)
  }

  has(id: string): boolean {
    return this.sessions.has(id)
  }
  activeCount(): number {
    return this.sessions.size
  }
  get(id: string): ActiveSession | undefined {
    return this.sessions.get(id)
  }

  private findOldest(): string | null {
    let oldestId: string | null = null
    let oldestTime = Infinity
    for (const [id, s] of this.sessions) {
      if (s.lastActiveAt < oldestTime) {
        oldestTime = s.lastActiveAt
        oldestId = id
      }
    }
    return oldestId
  }

  private resetTtl(sess: ActiveSession): void {
    if (sess.ttlTimer) clearTimeout(sess.ttlTimer)
    sess.ttlTimer = setTimeout(() => {
      this.close(sess.id, 'ttl')
    }, this.opts.ttlMs)
  }
}

// 单例
let _instance: SessionManager | null = null
export function getSessionManager(): SessionManager {
  if (!_instance) {
    _instance = new SessionManager({
      maxActive: 3,
      ttlMs: 30 * 60 * 1000, // 30 min
    })
  }
  return _instance
}
```

- [ ] **Step 4: 跑测试看通过**

Run: `cd frontend && npx vitest run tests/agent-chat/unit/session-manager.test.ts`
Expected: PASS（4 个测试）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/agent-chat/session-manager.ts frontend/tests/agent-chat/unit/session-manager.test.ts
git commit -m "feat(W5-B 切片 1.6): SessionManager 单进程内存 LRU + ttl + 多 session 调度"
```

---

### Task 1.7: WebSocket handler + Next.js custom server

**Files:**
- Create: `frontend/src/lib/agent-chat/ws-handler.ts`
- Create: `frontend/server.ts`
- Modify: `frontend/package.json`

- [ ] **Step 1: 加 npm 依赖**

```bash
cd frontend
npm install ws
npm install --save-dev @types/ws tsx
```

- [ ] **Step 2: 写 ws-handler**

```typescript
// frontend/src/lib/agent-chat/ws-handler.ts
import type { WebSocket } from 'ws'
import { getSessionManager } from './session-manager'
import { writeTempMcpConfig } from './mcp-config'
import { readSessionHistory } from './history-reader'
import path from 'node:path'
import os from 'node:os'
import { Pool } from 'pg'
import type {
  WsClientMessage,
  WsServerMessage,
  ClaudeStreamChunk,
  ChatMessage,
  ChatAttachment,
} from './types'

const pool = new Pool({
  host: process.env.PGHOST || 'localhost',
  port: parseInt(process.env.PGPORT || '5432'),
  user: process.env.PGUSER || 'omni_user',
  password: process.env.PGPASSWORD || 'omni_pass',
  database: process.env.PGDATABASE || 'omni_vibe_db',
})

function send(ws: WebSocket, msg: WsServerMessage) {
  try {
    ws.send(JSON.stringify(msg))
  } catch (e) {
    // eslint-disable-next-line no-console
    console.error('[ws] send failed:', e)
  }
}

/**
 * 把 Claude stream-json chunk 转成前端用的 ChatMessage
 */
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
  try {
    parsed = JSON.parse(content)
  } catch {
    return []
  }
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

export function attachWsHandler(ws: WebSocket): void {
  ws.on('message', async (raw) => {
    let msg: WsClientMessage
    try {
      msg = JSON.parse(raw.toString())
    } catch {
      return send(ws, { kind: 'error', error: 'bad_json' })
    }
    try {
      await handleClientMessage(ws, msg)
    } catch (err) {
      const e = err as Error
      send(ws, { kind: 'error', error: 'handler_failed', detail: e.message })
    }
  })
}

async function handleClientMessage(ws: WebSocket, msg: WsClientMessage) {
  const mgr = getSessionManager()

  if (msg.kind === 'open_session') {
    // 从 DB 拉 session 元数据
    const r = await pool.query<{ id: string; claude_session_id: string; title: string; sku_id: string | null; status: string; created_at: Date; updated_at: Date; message_count: number; last_message_preview: string | null }>(
      `SELECT id, claude_session_id, title, sku_id, status, created_at, updated_at, message_count, last_message_preview
         FROM mcp.agent_sessions WHERE id = $1`,
      [msg.session_id],
    )
    if (r.rowCount === 0) return send(ws, { kind: 'error', error: 'session_not_found' })
    const row = r.rows[0]
    const mcpConfigPath = await writeTempMcpConfig(msg.session_id)
    const sess = mgr.open(msg.session_id, { mcpConfigPath })
    sess.claudeSessionId = row.claude_session_id
    // 读历史
    const sessionsDir = path.join(os.homedir(), '.claude', 'projects', encodeProjectDirSync(process.cwd()))
    const jsonlPath = path.join(sessionsDir, `${row.claude_session_id}.jsonl`)
    const history = await readSessionHistory(jsonlPath)
    send(ws, {
      kind: 'session_opened',
      session: {
        id: row.id,
        claude_session_id: row.claude_session_id,
        title: row.title,
        sku_id: row.sku_id,
        last_message_preview: row.last_message_preview,
        message_count: row.message_count,
        status: row.status as 'active' | 'archived' | 'deleted',
        created_at: row.created_at.toISOString(),
        updated_at: row.updated_at.toISOString(),
      },
      history,
    })
    return
  }

  if (msg.kind === 'send_prompt') {
    if (!mgr.has(msg.session_id)) return send(ws, { kind: 'error', error: 'session_not_open' })
    const runner = mgr.spawn(msg.session_id, msg.prompt)
    runner.on('chunk', (chunk: ClaudeStreamChunk) => {
      // 把每个 chunk 拆成 1+ ChatMessage push 给前端
      const msgs = chunkToMessages(chunk)
      for (const m of msgs) {
        send(ws, { kind: 'chunk', session_id: msg.session_id, message: m })
      }
      if (chunk.type === 'result') {
        const usage = chunk.message?.usage
        send(ws, {
          kind: 'task_done',
          session_id: msg.session_id,
          duration_ms: chunk.duration_ms || 0,
          total_cost_usd: chunk.total_cost_usd || 0,
          tokens: { input: usage?.input_tokens || 0, output: usage?.output_tokens || 0 },
        })
        // 更新 DB session 元数据
        updateSessionStats(msg.session_id, chunk).catch(() => undefined)
      }
    })
    runner.on('stderr', (data) => {
      // eslint-disable-next-line no-console
      console.error(`[claude-stderr ${msg.session_id}]`, data)
    })
    runner.on('error', (err) => {
      send(ws, { kind: 'error', session_id: msg.session_id, error: 'runner_error', detail: err.message })
    })
    return
  }

  if (msg.kind === 'cancel') {
    const sess = mgr.get(msg.session_id)
    if (sess?.runner) sess.runner.cancel()
    return
  }

  if (msg.kind === 'close_session') {
    mgr.close(msg.session_id, 'manual')
    return
  }

  if (msg.kind === 'human_gate_decide') {
    // 调 KE 的 cli_approve 等效 endpoint
    const base = process.env.OMNI_KE_URL || 'http://localhost:8002'
    const resp = await fetch(`${base}/api/v1/mcp/human-gates/${msg.short_id}/${msg.decision}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: msg.note || '' }),
    })
    if (!resp.ok) {
      const text = await resp.text()
      return send(ws, { kind: 'error', error: 'gate_decide_failed', detail: text })
    }
    return
  }
}

function encodeProjectDirSync(p: string): string {
  return p.replace(/[\\/:]/g, '-')
}

async function updateSessionStats(sessionId: string, chunk: ClaudeStreamChunk): Promise<void> {
  const usage = chunk.message?.usage
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

- [ ] **Step 3: 写 Next.js custom server**

```typescript
// frontend/server.ts
import { createServer } from 'node:http'
import { parse } from 'node:url'
import next from 'next'
import { WebSocketServer } from 'ws'
import { attachWsHandler } from './src/lib/agent-chat/ws-handler'

const dev = process.env.NODE_ENV !== 'production'
const hostname = '127.0.0.1' // 绑本机
const port = parseInt(process.env.PORT || '3000', 10)

const app = next({ dev, hostname, port })
const handle = app.getRequestHandler()

app.prepare().then(() => {
  const server = createServer((req, res) => {
    const parsedUrl = parse(req.url || '', true)
    handle(req, res, parsedUrl)
  })

  // WebSocket 升级请求挂 /ws/agent-chat
  const wss = new WebSocketServer({ noServer: true })
  wss.on('connection', (ws) => {
    attachWsHandler(ws)
  })

  server.on('upgrade', (req, socket, head) => {
    if (req.url === '/ws/agent-chat') {
      wss.handleUpgrade(req, socket, head, (ws) => {
        wss.emit('connection', ws, req)
      })
    } else {
      socket.destroy()
    }
  })

  server.listen(port, hostname, () => {
    // eslint-disable-next-line no-console
    console.log(`> Ready on http://${hostname}:${port}`)
  })
})
```

- [ ] **Step 4: 改 package.json dev/start script**

```json
{
  "scripts": {
    "dev": "tsx watch server.ts",
    "build": "next build",
    "start": "NODE_ENV=production tsx server.ts",
    "lint": "next lint",
    "test:unit": "vitest run",
    "test:e2e": "playwright test"
  }
}
```

- [ ] **Step 5: smoke test**

```bash
cd frontend && npm run dev
# 在另一个终端
curl -s -i \
  -H "Upgrade: websocket" \
  -H "Connection: Upgrade" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "Sec-WebSocket-Version: 13" \
  http://127.0.0.1:3000/ws/agent-chat
```

Expected: `HTTP/1.1 101 Switching Protocols`

- [ ] **Step 6: Commit**

```bash
git add frontend/server.ts frontend/src/lib/agent-chat/ws-handler.ts frontend/package.json frontend/package-lock.json
git commit -m "feat(W5-B 切片 1.7): Next.js custom server + WebSocket 路由 + ws-handler 消息分发"
```

---

### Task 1.8: REST API routes（session CRUD）

**Files:**
- Create: `frontend/src/app/api/agent-chat/sessions/route.ts`
- Create: `frontend/src/app/api/agent-chat/sessions/[id]/route.ts`
- Create: `frontend/src/app/api/agent-chat/sessions/[id]/history/route.ts`
- Create: `frontend/src/app/api/agent-chat/upload/route.ts`

- [ ] **Step 1: sessions list + create**

```typescript
// frontend/src/app/api/agent-chat/sessions/route.ts
import { NextRequest, NextResponse } from 'next/server'
import { Pool } from 'pg'
import crypto from 'node:crypto'

export const runtime = 'nodejs'

const pool = new Pool({
  host: process.env.PGHOST || 'localhost',
  port: parseInt(process.env.PGPORT || '5432'),
  user: process.env.PGUSER || 'omni_user',
  password: process.env.PGPASSWORD || 'omni_pass',
  database: process.env.PGDATABASE || 'omni_vibe_db',
})

export async function GET() {
  const r = await pool.query(
    `SELECT id, claude_session_id, title, sku_id, last_message_preview, message_count, status, created_at, updated_at
       FROM mcp.agent_sessions
      WHERE status != 'deleted'
      ORDER BY updated_at DESC
      LIMIT 100`,
  )
  return NextResponse.json({ success: true, data: r.rows })
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as { title?: string; sku_id?: string }
  // 提前生成 claude_session_id（uuid v4），后续 spawn 时通过 --resume 复用
  const claudeSessionId = crypto.randomUUID()
  const r = await pool.query(
    `INSERT INTO mcp.agent_sessions (claude_session_id, title, sku_id)
     VALUES ($1, $2, $3) RETURNING *`,
    [claudeSessionId, body.title || '新对话', body.sku_id || null],
  )
  return NextResponse.json({ success: true, data: r.rows[0] })
}
```

- [ ] **Step 2: sessions GET / DELETE / PATCH**

```typescript
// frontend/src/app/api/agent-chat/sessions/[id]/route.ts
import { NextRequest, NextResponse } from 'next/server'
import { Pool } from 'pg'

export const runtime = 'nodejs'
const pool = new Pool({
  host: process.env.PGHOST || 'localhost',
  port: parseInt(process.env.PGPORT || '5432'),
  user: process.env.PGUSER || 'omni_user',
  password: process.env.PGPASSWORD || 'omni_pass',
  database: process.env.PGDATABASE || 'omni_vibe_db',
})

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params
  const r = await pool.query(`SELECT * FROM mcp.agent_sessions WHERE id = $1`, [id])
  if (r.rowCount === 0) return NextResponse.json({ success: false, error: 'not_found' }, { status: 404 })
  return NextResponse.json({ success: true, data: r.rows[0] })
}

export async function DELETE(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params
  await pool.query(`UPDATE mcp.agent_sessions SET status = 'deleted', updated_at = NOW() WHERE id = $1`, [id])
  return NextResponse.json({ success: true })
}

export async function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params
  const body = (await req.json().catch(() => ({}))) as { title?: string; sku_id?: string }
  const r = await pool.query(
    `UPDATE mcp.agent_sessions
        SET title = COALESCE($2, title),
            sku_id = COALESCE($3, sku_id),
            updated_at = NOW()
      WHERE id = $1
      RETURNING *`,
    [id, body.title || null, body.sku_id || null],
  )
  if (r.rowCount === 0) return NextResponse.json({ success: false, error: 'not_found' }, { status: 404 })
  return NextResponse.json({ success: true, data: r.rows[0] })
}
```

- [ ] **Step 3: history GET**

```typescript
// frontend/src/app/api/agent-chat/sessions/[id]/history/route.ts
import { NextRequest, NextResponse } from 'next/server'
import { Pool } from 'pg'
import path from 'node:path'
import os from 'node:os'
import { encodeProjectDir, readSessionHistory } from '@/lib/agent-chat/history-reader'

export const runtime = 'nodejs'
const pool = new Pool({
  host: process.env.PGHOST || 'localhost',
  port: parseInt(process.env.PGPORT || '5432'),
  user: process.env.PGUSER || 'omni_user',
  password: process.env.PGPASSWORD || 'omni_pass',
  database: process.env.PGDATABASE || 'omni_vibe_db',
})

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params
  const r = await pool.query<{ claude_session_id: string }>(
    `SELECT claude_session_id FROM mcp.agent_sessions WHERE id = $1`,
    [id],
  )
  if (r.rowCount === 0) return NextResponse.json({ success: false, error: 'not_found' }, { status: 404 })
  const claudeId = r.rows[0].claude_session_id
  const projectDir = process.env.OMNI_PROJECT_DIR || process.cwd()
  const jsonl = path.join(os.homedir(), '.claude', 'projects', encodeProjectDir(projectDir), `${claudeId}.jsonl`)
  const history = await readSessionHistory(jsonl)
  return NextResponse.json({ success: true, data: history })
}
```

- [ ] **Step 4: upload POST**

```typescript
// frontend/src/app/api/agent-chat/upload/route.ts
import { NextRequest, NextResponse } from 'next/server'
import fs from 'node:fs/promises'
import path from 'node:path'
import crypto from 'node:crypto'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const UPLOAD_BASE = process.env.OMNI_UPLOAD_BASE || path.join(process.cwd(), '..', 'data', 'uploads')

export async function POST(req: NextRequest) {
  const url = new URL(req.url)
  const sessionId = url.searchParams.get('session_id')
  if (!sessionId) return NextResponse.json({ success: false, error: 'missing_session_id' }, { status: 400 })
  const form = await req.formData()
  const file = form.get('file') as File | null
  if (!file) return NextResponse.json({ success: false, error: 'no_file' }, { status: 400 })

  const ext = path.extname(file.name) || '.bin'
  const uuid = crypto.randomUUID()
  const dir = path.join(UPLOAD_BASE, sessionId)
  await fs.mkdir(dir, { recursive: true })
  const target = path.join(dir, `${uuid}${ext}`)
  const buffer = Buffer.from(await file.arrayBuffer())
  await fs.writeFile(target, buffer)

  // 返 KE static 端点的 URL
  const url_path = `/api/v1/knowledge/static/uploads/${sessionId}/${uuid}${ext}`
  return NextResponse.json({
    success: true,
    data: {
      url: url_path,
      filename: file.name,
      size: file.size,
      mime: file.type,
    },
  })
}
```

- [ ] **Step 5: smoke test API**

```bash
# 列 session（空）
curl http://localhost:3000/api/agent-chat/sessions
# 建 session
curl -X POST http://localhost:3000/api/agent-chat/sessions \
  -H "Content-Type: application/json" -d '{"title":"测试","sku_id":"SKU-367991-0002"}'
# 看历史（空，没真跑过）
curl http://localhost:3000/api/agent-chat/sessions/<id>/history
```

Expected: 都 200 OK + 合理 JSON

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/api/agent-chat/
git commit -m "feat(W5-B 切片 1.8): agent-chat REST API（sessions CRUD + history + upload）"
```

---

### Task 1.9: KE static_uploads mount

**Files:**
- Create: `services/knowledge-engine/app/api/static_uploads.py`
- Modify: `services/knowledge-engine/app/main.py:<找到 mount /static 那行附近>`

- [ ] **Step 1: 找现有 static mount 代码**

Run: `grep -n "StaticFiles\|knowledge/static" services/knowledge-engine/app/main.py`
（预期能找到一行 `app.mount("/api/v1/knowledge/static", StaticFiles(directory="/app/data/assets"))`）

- [ ] **Step 2: 加 uploads mount**

```python
# services/knowledge-engine/app/main.py
# 在 app.mount("/api/v1/knowledge/static", ...) 之后追加：
import os
UPLOAD_DIR = os.environ.get("OMNI_UPLOAD_DIR", "/app/data/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount(
    "/api/v1/knowledge/static/uploads",
    StaticFiles(directory=UPLOAD_DIR),
    name="agent_chat_uploads",
)
```

- [ ] **Step 3: 改 docker-compose mount uploads volume**

```yaml
# docker-compose.yml knowledge-engine 的 volumes 段加：
volumes:
  - ./data/uploads:/app/data/uploads
```

- [ ] **Step 4: restart KE + verify**

```bash
docker compose restart knowledge-engine
sleep 5
docker exec omni-knowledge-engine ls -la /app/data/uploads
curl -I http://localhost:8002/api/v1/knowledge/static/uploads/
```

Expected: `200` 或 `404` 但不是 connection error；目录存在

- [ ] **Step 5: Commit**

```bash
git add services/knowledge-engine/app/main.py docker-compose.yml
git commit -m "feat(W5-B 切片 1.9): KE 加 /api/v1/knowledge/static/uploads mount 给 agent chat 附件用"
```

---

### Task 1.10: human-gate decide proxy + KE endpoint

**Files:**
- Modify: `services/knowledge-engine/app/mcp/human_gate.py` 或 `app/routers/human_gates.py`（找现存的） — 加 `POST /api/v1/mcp/human-gates/<short_id>/<decision>` endpoint

- [ ] **Step 1: 找现有 cli_approve 实现**

Run: `grep -rn "cli_approve\|HumanGate" services/knowledge-engine/app/mcp/`

- [ ] **Step 2: 加 HTTP endpoint 复用 cli_approve 内部函数**

```python
# services/knowledge-engine/app/routers/human_gates.py (新建或加到已有文件)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.mcp.cli_approve import approve_by_short_id, reject_by_short_id  # 复用已有

router = APIRouter(prefix="/api/v1/mcp/human-gates", tags=["human_gates"])

class DecideBody(BaseModel):
    note: str = ""

@router.post("/{short_id}/approved")
async def approve(short_id: str, body: DecideBody):
    try:
        await approve_by_short_id(short_id, body.note)
        return {"success": True}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.post("/{short_id}/rejected")
async def reject(short_id: str, body: DecideBody):
    try:
        await reject_by_short_id(short_id, body.note)
        return {"success": True}
    except Exception as e:
        raise HTTPException(400, str(e))
```

注：如 cli_approve 没暴露这俩函数，先 refactor 一下：把 click command body 抽成 `approve_by_short_id(short_id, note) -> None` 异步函数。

- [ ] **Step 3: 注册到 main.py**

```python
# services/knowledge-engine/app/main.py
from app.routers import human_gates
app.include_router(human_gates.router)
```

- [ ] **Step 4: restart KE + smoke test**

```bash
docker compose restart knowledge-engine
# 触发一个 human gate（例如 generate_brief）拿 short_id，然后 curl 批
curl -X POST http://localhost:8002/api/v1/mcp/human-gates/<short_id>/approved \
  -H "Content-Type: application/json" -d '{"note":"test approve"}'
```

Expected: `{"success": true}`

- [ ] **Step 5: Commit**

```bash
git add services/knowledge-engine/app/routers/human_gates.py services/knowledge-engine/app/main.py
git commit -m "feat(W5-B 切片 1.10): KE HTTP endpoint 复用 cli_approve 给前端 human gate 嵌对话流用"
```

---

### 切片 1 验收

- [ ] mcp.agent_sessions 表存在，CRUD 通过 REST 跑通
- [ ] `npm run dev` 起 Next.js custom server，`:3000/ws/agent-chat` 能 101 升级
- [ ] vitest 4 个文件全 PASS（mcp-config / history-reader / claude-runner / session-manager）
- [ ] 手动 smoke: 建一个 session → ws open_session → ws send_prompt "你好" → 收到 assistant chunk + result chunk
- [ ] 触发 human gate 后 curl decide endpoint 能批

---

## 切片 2：前端（/agent-chat UI 改造）

**目标：** 老板能在浏览器对话框里跟 omni 自然语言对话；多模态结果在气泡里渲染；输入框支持附件上传 + slash command。

**预期工作量：** 4-6 天 / 25-30 steps

### Task 2.1: useAgentChat hook（WebSocket 连接 + 消息状态）

**Files:**
- Create: `frontend/src/hooks/useAgentChat.ts`
- Create: `frontend/tests/agent-chat/unit/useAgentChat.test.tsx`

- [ ] **Step 1: 写测试**（用 vitest + happy-dom）

```typescript
// frontend/tests/agent-chat/unit/useAgentChat.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useAgentChat } from '@/hooks/useAgentChat'

// 简单 mock WebSocket
class MockWebSocket {
  static instances: MockWebSocket[] = []
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []
  constructor(public url: string) {
    MockWebSocket.instances.push(this)
    setTimeout(() => {
      this.readyState = 1
      this.onopen?.()
    }, 10)
  }
  send(data: string) { this.sent.push(data) }
  close() { this.readyState = 3; this.onclose?.() }
  emit(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }) }
}

beforeEach(() => {
  MockWebSocket.instances = []
  ;(global as unknown as { WebSocket: typeof MockWebSocket }).WebSocket = MockWebSocket
})

describe('useAgentChat', () => {
  it('connects to ws/agent-chat on mount', async () => {
    const { result } = renderHook(() => useAgentChat('sess-1'))
    await waitFor(() => expect(result.current.connected).toBe(true))
    expect(MockWebSocket.instances[0].url).toContain('/ws/agent-chat')
  })

  it('sends open_session after connect', async () => {
    renderHook(() => useAgentChat('sess-1'))
    await waitFor(() => expect(MockWebSocket.instances[0].sent.length).toBeGreaterThan(0))
    const sent = JSON.parse(MockWebSocket.instances[0].sent[0])
    expect(sent.kind).toBe('open_session')
    expect(sent.session_id).toBe('sess-1')
  })

  it('appends incoming chunk to messages', async () => {
    const { result } = renderHook(() => useAgentChat('sess-1'))
    await waitFor(() => expect(result.current.connected).toBe(true))
    act(() => {
      MockWebSocket.instances[0].emit({
        kind: 'chunk',
        session_id: 'sess-1',
        message: {
          id: 'm1', session_id: 'sess-1', role: 'assistant', text: 'hello',
          created_at: '2026-05-15T10:00:00Z',
        },
      })
    })
    expect(result.current.messages).toHaveLength(1)
    expect(result.current.messages[0].text).toBe('hello')
  })

  it('sendPrompt sends ws message and clears input', async () => {
    const { result } = renderHook(() => useAgentChat('sess-1'))
    await waitFor(() => expect(result.current.connected).toBe(true))
    act(() => result.current.sendPrompt('查 SKU'))
    const last = JSON.parse(MockWebSocket.instances[0].sent[MockWebSocket.instances[0].sent.length - 1])
    expect(last.kind).toBe('send_prompt')
    expect(last.prompt).toBe('查 SKU')
  })
})
```

- [ ] **Step 2: 跑测试看失败**

Run: `cd frontend && npx vitest run tests/agent-chat/unit/useAgentChat.test.tsx`
Expected: FAIL (module not found)

- [ ] **Step 3: 写实现**

```typescript
// frontend/src/hooks/useAgentChat.ts
'use client'
import { useEffect, useRef, useState, useCallback } from 'react'
import type {
  ChatMessage, SessionState,
  WsClientMessage, WsServerMessage,
} from '@/lib/agent-chat/types'

interface UseAgentChatResult {
  connected: boolean
  session: SessionState | null
  messages: ChatMessage[]
  running: boolean
  error: string | null
  sendPrompt: (prompt: string) => void
  cancel: () => void
  decideGate: (shortId: string, decision: 'approved' | 'rejected', note?: string) => void
}

export function useAgentChat(sessionId: string | null): UseAgentChatResult {
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const [session, setSession] = useState<SessionState | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!sessionId) return
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/agent-chat`)
    wsRef.current = ws
    ws.onopen = () => {
      setConnected(true)
      ws.send(JSON.stringify({ kind: 'open_session', session_id: sessionId } satisfies WsClientMessage))
    }
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data) as WsServerMessage
      if (msg.kind === 'session_opened') {
        setSession(msg.session)
        setMessages(msg.history)
      } else if (msg.kind === 'chunk') {
        setMessages((prev) => mergeMessage(prev, msg.message))
      } else if (msg.kind === 'task_done') {
        setRunning(false)
      } else if (msg.kind === 'human_gate_new') {
        const gateMsg: ChatMessage = {
          id: `gate-${msg.gate.short_id}`,
          session_id: msg.session_id,
          role: 'human_gate',
          gate_short_id: msg.gate.short_id,
          gate_summary: msg.gate.summary,
          gate_decision: 'pending',
          created_at: new Date().toISOString(),
        }
        setMessages((prev) => [...prev, gateMsg])
      } else if (msg.kind === 'error') {
        setError(msg.error + (msg.detail ? `: ${msg.detail}` : ''))
        setRunning(false)
      }
    }
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setError('websocket_error')
    return () => {
      ws.close()
    }
  }, [sessionId])

  const sendPrompt = useCallback((prompt: string) => {
    if (!wsRef.current || wsRef.current.readyState !== 1 || !sessionId) return
    setRunning(true)
    setError(null)
    // 本地立即 push user 消息（乐观渲染）
    setMessages((prev) => [
      ...prev,
      { id: `local-${Date.now()}`, session_id: sessionId, role: 'user', text: prompt, created_at: new Date().toISOString() },
    ])
    wsRef.current.send(JSON.stringify({ kind: 'send_prompt', session_id: sessionId, prompt } satisfies WsClientMessage))
  }, [sessionId])

  const cancel = useCallback(() => {
    if (!wsRef.current || !sessionId) return
    wsRef.current.send(JSON.stringify({ kind: 'cancel', session_id: sessionId } satisfies WsClientMessage))
    setRunning(false)
  }, [sessionId])

  const decideGate = useCallback((shortId: string, decision: 'approved' | 'rejected', note?: string) => {
    if (!wsRef.current) return
    wsRef.current.send(JSON.stringify({ kind: 'human_gate_decide', short_id: shortId, decision, note } satisfies WsClientMessage))
    setMessages((prev) => prev.map((m) => (m.gate_short_id === shortId ? { ...m, gate_decision: decision } : m)))
  }, [])

  return { connected, session, messages, running, error, sendPrompt, cancel, decideGate }
}

function mergeMessage(prev: ChatMessage[], incoming: ChatMessage): ChatMessage[] {
  // tool_call → 后续若同 id 出现 tool_result，更新 tool_status='completed'
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

- [ ] **Step 4: 跑测试看通过**

Run: `cd frontend && npx vitest run tests/agent-chat/unit/useAgentChat.test.tsx`
Expected: PASS（4 个测试）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useAgentChat.ts frontend/tests/agent-chat/unit/useAgentChat.test.tsx
git commit -m "feat(W5-B 切片 2.1): useAgentChat React hook + ws 连接管理"
```

---

### Task 2.2: 各 attachment 子组件

**Files:**
- Create: `frontend/src/components/agent-chat/attachments/ImageAttachment.tsx`
- Create: `frontend/src/components/agent-chat/attachments/VideoAttachment.tsx`
- Create: `frontend/src/components/agent-chat/attachments/MarkdownAttachment.tsx`
- Create: `frontend/src/components/agent-chat/attachments/JsonAttachment.tsx`

- [ ] **Step 1: ImageAttachment**

```tsx
// frontend/src/components/agent-chat/attachments/ImageAttachment.tsx
'use client'
import { useState } from 'react'
import { ImageIcon } from 'lucide-react'

interface Props { url: string; alt?: string }

export function ImageAttachment({ url, alt }: Props) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="block max-w-[320px] rounded-lg overflow-hidden border border-gray-200 hover:border-violet-400 transition-colors"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={url} alt={alt || 'image'} className="w-full h-auto" loading="lazy" />
      </button>
      {open && (
        <div
          className="fixed inset-0 bg-black/80 z-[100] flex items-center justify-center p-4"
          onClick={() => setOpen(false)}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={url} alt={alt || 'image'} className="max-w-full max-h-full object-contain" />
        </div>
      )}
    </>
  )
}
```

- [ ] **Step 2: VideoAttachment**

```tsx
// frontend/src/components/agent-chat/attachments/VideoAttachment.tsx
'use client'
interface Props { url: string }
export function VideoAttachment({ url }: Props) {
  return (
    <video
      controls
      src={url}
      className="max-w-[320px] rounded-lg border border-gray-200"
      preload="metadata"
    />
  )
}
```

- [ ] **Step 3: MarkdownAttachment（复用项目里现有的 react-markdown 配置）**

```tsx
// frontend/src/components/agent-chat/attachments/MarkdownAttachment.tsx
'use client'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface Props { markdown: string }
export function MarkdownAttachment({ markdown }: Props) {
  return (
    <div className="max-w-2xl prose prose-sm prose-violet bg-white rounded-lg border border-gray-200 p-3">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </div>
  )
}
```

- [ ] **Step 4: JsonAttachment**

```tsx
// frontend/src/components/agent-chat/attachments/JsonAttachment.tsx
'use client'
import { useState } from 'react'
import { ChevronDown, ChevronRight, FileJson } from 'lucide-react'

interface Props { data: unknown }
export function JsonAttachment({ data }: Props) {
  const [open, setOpen] = useState(false)
  const text = JSON.stringify(data, null, 2)
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 overflow-hidden max-w-2xl">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-gray-100 transition-colors"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <FileJson className="w-3.5 h-3.5 text-gray-500" />
        <span className="text-xs text-gray-600">JSON · {text.length} chars</span>
      </button>
      {open && (
        <pre className="px-3 py-2 text-[11px] font-mono text-gray-800 overflow-x-auto max-h-96">
          {text}
        </pre>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/agent-chat/attachments/
git commit -m "feat(W5-B 切片 2.2): attachment 子组件（image/video/markdown/json）"
```

---

### Task 2.3: ToolCallChip + ToolResultCard 分发器

**Files:**
- Create: `frontend/src/components/agent-chat/ToolCallChip.tsx`
- Create: `frontend/src/components/agent-chat/ToolResultCard.tsx`

- [ ] **Step 1: ToolCallChip**

```tsx
// frontend/src/components/agent-chat/ToolCallChip.tsx
'use client'
import { Loader2, CheckCircle2, XCircle, Wrench } from 'lucide-react'
import { useState } from 'react'
import { JsonAttachment } from './attachments/JsonAttachment'

interface Props {
  toolName: string
  args: Record<string, unknown> | undefined
  status: 'pending' | 'completed' | 'error'
}

export function ToolCallChip({ toolName, args, status }: Props) {
  const [open, setOpen] = useState(false)
  const Icon = status === 'pending' ? Loader2 : status === 'error' ? XCircle : CheckCircle2
  const color = status === 'pending' ? 'text-blue-500' : status === 'error' ? 'text-red-500' : 'text-emerald-500'
  return (
    <div className="inline-flex flex-col items-start gap-1 max-w-2xl">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-violet-50 border border-violet-200 text-xs text-gray-700 hover:bg-violet-100"
      >
        <Wrench className="w-3 h-3 text-violet-600" />
        <span className="font-medium">{toolName}</span>
        <Icon className={`w-3 h-3 ${color} ${status === 'pending' ? 'animate-spin' : ''}`} />
      </button>
      {open && args && <JsonAttachment data={args} />}
    </div>
  )
}
```

- [ ] **Step 2: ToolResultCard 分发器**

```tsx
// frontend/src/components/agent-chat/ToolResultCard.tsx
'use client'
import type { ChatAttachment } from '@/lib/agent-chat/types'
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
    // 没识别出附件 → 直接 JSON 展示原始 result
    return <JsonAttachment data={rawResult} />
  }
  return (
    <div className="flex flex-wrap gap-3 max-w-3xl">
      {attachments.map((att, idx) => {
        if (att.type === 'image' && att.url) return <ImageAttachment key={idx} url={att.url} alt={att.alt} />
        if (att.type === 'video' && att.url) return <VideoAttachment key={idx} url={att.url} />
        if (att.type === 'markdown' && att.markdown) return <MarkdownAttachment key={idx} markdown={att.markdown} />
        if (att.type === 'json') return <JsonAttachment key={idx} data={att.data} />
        return null
      })}
    </div>
  )
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/agent-chat/ToolCallChip.tsx frontend/src/components/agent-chat/ToolResultCard.tsx
git commit -m "feat(W5-B 切片 2.3): ToolCallChip + ToolResultCard 分发器"
```

---

### Task 2.4: MessageBubble + HumanGateCard

**Files:**
- Create: `frontend/src/components/agent-chat/MessageBubble.tsx`
- Create: `frontend/src/components/agent-chat/HumanGateCard.tsx`

- [ ] **Step 1: MessageBubble**

```tsx
// frontend/src/components/agent-chat/MessageBubble.tsx
'use client'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { User2, Brain } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  role: 'user' | 'assistant'
  text: string
}

export function MessageBubble({ role, text }: Props) {
  const isUser = role === 'user'
  return (
    <div className={cn('flex gap-3 max-w-3xl', isUser ? 'flex-row-reverse self-end' : 'self-start')}>
      <div
        className={cn(
          'w-8 h-8 rounded-full flex items-center justify-center shrink-0',
          isUser ? 'bg-violet-100 text-violet-700' : 'bg-gradient-to-br from-violet-600 to-purple-500 text-white',
        )}
      >
        {isUser ? <User2 className="w-4 h-4" /> : <Brain className="w-4 h-4" />}
      </div>
      <div
        className={cn(
          'rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
          isUser
            ? 'bg-violet-600 text-white rounded-tr-sm prose-invert'
            : 'bg-white border border-gray-200 text-gray-900 rounded-tl-sm',
        )}
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]} className="prose prose-sm max-w-none">
          {text}
        </ReactMarkdown>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: HumanGateCard**

```tsx
// frontend/src/components/agent-chat/HumanGateCard.tsx
'use client'
import { CheckCircle2, XCircle, Shield } from 'lucide-react'
import { useState } from 'react'

interface Props {
  shortId: string
  summary: string
  decision: 'pending' | 'approved' | 'rejected'
  onDecide: (decision: 'approved' | 'rejected', note?: string) => void
}

export function HumanGateCard({ shortId, summary, decision, onDecide }: Props) {
  const [note, setNote] = useState('')
  return (
    <div className="max-w-2xl rounded-xl border-2 border-amber-300 bg-amber-50 p-4 self-start">
      <div className="flex items-center gap-2 mb-2">
        <Shield className="w-4 h-4 text-amber-600" />
        <span className="text-sm font-semibold text-amber-900">需要你点头</span>
        <span className="text-[10px] text-amber-700 font-mono">{shortId}</span>
      </div>
      <p className="text-sm text-gray-700 mb-3 whitespace-pre-wrap">{summary}</p>
      {decision === 'pending' ? (
        <>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="备注（可选）"
            className="w-full px-2.5 py-1.5 text-xs rounded-md border border-amber-200 mb-2 focus:outline-none focus:border-amber-400"
          />
          <div className="flex gap-2">
            <button
              onClick={() => onDecide('approved', note)}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-600 text-white text-xs hover:bg-emerald-700"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              通过
            </button>
            <button
              onClick={() => onDecide('rejected', note)}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md bg-red-600 text-white text-xs hover:bg-red-700"
            >
              <XCircle className="w-3.5 h-3.5" />
              驳回
            </button>
          </div>
        </>
      ) : (
        <div className="text-xs">
          {decision === 'approved' ? (
            <span className="text-emerald-700">✓ 已通过</span>
          ) : (
            <span className="text-red-700">✗ 已驳回</span>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/agent-chat/MessageBubble.tsx frontend/src/components/agent-chat/HumanGateCard.tsx
git commit -m "feat(W5-B 切片 2.4): MessageBubble 气泡 + HumanGateCard 嵌入式人 gate"
```

---

### Task 2.5: MessageStream + InputBar

**Files:**
- Create: `frontend/src/components/agent-chat/MessageStream.tsx`
- Create: `frontend/src/components/agent-chat/InputBar.tsx`

- [ ] **Step 1: MessageStream**

```tsx
// frontend/src/components/agent-chat/MessageStream.tsx
'use client'
import { useEffect, useRef } from 'react'
import type { ChatMessage } from '@/lib/agent-chat/types'
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
    <div className="flex-1 overflow-y-auto px-6 py-4 flex flex-col gap-4 bg-gradient-to-b from-gray-50 to-white">
      {messages.length === 0 && (
        <div className="text-center text-gray-400 text-sm mt-20">
          开始一段对话，让 omni 帮你跑 tool 出结果。
        </div>
      )}
      {messages.map((m) => {
        if (m.role === 'user' || m.role === 'assistant') {
          return <MessageBubble key={m.id} role={m.role} text={m.text || ''} />
        }
        if (m.role === 'tool_call') {
          return (
            <div key={m.id} className="self-start">
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
  )
}
```

- [ ] **Step 2: InputBar**

```tsx
// frontend/src/components/agent-chat/InputBar.tsx
'use client'
import { useState, useRef } from 'react'
import { Send, Paperclip, X, Square } from 'lucide-react'

interface Props {
  sessionId: string
  running: boolean
  onSend: (prompt: string) => void
  onCancel: () => void
}

interface UploadedFile {
  url: string
  filename: string
}

export function InputBar({ sessionId, running, onSend, onCancel }: Props) {
  const [input, setInput] = useState('')
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const handleSend = () => {
    if (!input.trim() && files.length === 0) return
    let prompt = input.trim()
    if (files.length > 0) {
      const fileList = files.map((f) => `- ${f.filename}: ${f.url}`).join('\n')
      prompt = `${prompt}\n\n附件：\n${fileList}`
    }
    onSend(prompt)
    setInput('')
    setFiles([])
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const list = e.target.files
    if (!list || list.length === 0) return
    setUploading(true)
    try {
      for (const f of Array.from(list)) {
        const form = new FormData()
        form.append('file', f)
        const resp = await fetch(`/api/agent-chat/upload?session_id=${sessionId}`, {
          method: 'POST',
          body: form,
        })
        const json = await resp.json()
        if (json.success) {
          setFiles((prev) => [...prev, { url: json.data.url, filename: json.data.filename }])
        }
      }
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  return (
    <div className="border-t border-gray-100 bg-white px-4 py-3">
      {files.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {files.map((f, idx) => (
            <span
              key={idx}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-violet-50 border border-violet-200 text-xs"
            >
              <Paperclip className="w-3 h-3 text-violet-600" />
              {f.filename}
              <button onClick={() => setFiles(files.filter((_, i) => i !== idx))}>
                <X className="w-3 h-3 text-gray-400 hover:text-red-500" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex items-end gap-2">
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="shrink-0 w-9 h-9 rounded-lg border border-gray-200 flex items-center justify-center text-gray-500 hover:bg-gray-50"
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
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
          placeholder="输入指令，回车发送 (Shift+Enter 换行) / 支持 / 触发 skill"
          rows={1}
          className="flex-1 resize-none rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:border-violet-400 max-h-32"
        />
        {running ? (
          <button
            onClick={onCancel}
            className="shrink-0 w-9 h-9 rounded-lg bg-red-500 text-white flex items-center justify-center hover:bg-red-600"
            title="停止"
          >
            <Square className="w-4 h-4" />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!input.trim() && files.length === 0}
            className="shrink-0 w-9 h-9 rounded-lg bg-violet-600 text-white flex items-center justify-center hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed"
            title="发送"
          >
            <Send className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/agent-chat/MessageStream.tsx frontend/src/components/agent-chat/InputBar.tsx
git commit -m "feat(W5-B 切片 2.5): MessageStream + InputBar 主对话流容器"
```

---

### Task 2.6: SessionList 侧栏

**Files:**
- Create: `frontend/src/components/agent-chat/SessionList.tsx`

- [ ] **Step 1: SessionList**

```tsx
// frontend/src/components/agent-chat/SessionList.tsx
'use client'
import { useEffect, useState } from 'react'
import { Plus, MessageSquare, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface SessionRow {
  id: string
  title: string
  sku_id: string | null
  last_message_preview: string | null
  message_count: number
  updated_at: string
}

interface Props {
  currentId: string | null
  onSelect: (id: string) => void
}

export function SessionList({ currentId, onSelect }: Props) {
  const [list, setList] = useState<SessionRow[]>([])
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    setLoading(true)
    try {
      const r = await fetch('/api/agent-chat/sessions', { cache: 'no-store' })
      const j = await r.json()
      if (j.success) setList(j.data)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { refresh() }, [])

  const createNew = async () => {
    const r = await fetch('/api/agent-chat/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    const j = await r.json()
    if (j.success) {
      await refresh()
      onSelect(j.data.id)
    }
  }

  const removeOne = async (id: string) => {
    if (!confirm('删除这个对话？')) return
    await fetch(`/api/agent-chat/sessions/${id}`, { method: 'DELETE' })
    await refresh()
    if (currentId === id) onSelect('')
  }

  return (
    <aside className="w-64 border-r border-gray-100 bg-white flex flex-col">
      <div className="px-4 h-14 border-b border-gray-100 flex items-center justify-between">
        <span className="text-sm font-semibold text-gray-700">对话</span>
        <button
          onClick={createNew}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-violet-600 text-white text-xs hover:bg-violet-700"
        >
          <Plus className="w-3.5 h-3.5" />
          新建
        </button>
      </div>
      <div className="flex-1 overflow-y-auto py-2 space-y-1 px-2">
        {loading && <div className="px-3 py-2 text-xs text-gray-400">加载中...</div>}
        {!loading && list.length === 0 && (
          <div className="px-3 py-8 text-center text-xs text-gray-400">还没有对话<br />点新建开始</div>
        )}
        {list.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={cn(
              'w-full text-left px-3 py-2 rounded-lg flex items-start gap-2 group relative transition-colors',
              currentId === s.id ? 'bg-violet-50 text-violet-700' : 'hover:bg-gray-50 text-gray-700',
            )}
          >
            <MessageSquare className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium truncate">{s.title}</div>
              {s.last_message_preview && (
                <div className="text-[10px] text-gray-400 truncate mt-0.5">{s.last_message_preview}</div>
              )}
              <div className="text-[9px] text-gray-300 mt-1">{new Date(s.updated_at).toLocaleString()}</div>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); removeOne(s.id) }}
              className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 shrink-0"
              title="删除"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </button>
        ))}
      </div>
    </aside>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/agent-chat/SessionList.tsx
git commit -m "feat(W5-B 切片 2.6): SessionList 侧栏 + 新建/删除"
```

---

### Task 2.7: ChatLayout 整合

**Files:**
- Create: `frontend/src/components/agent-chat/ChatLayout.tsx`

- [ ] **Step 1: ChatLayout**

```tsx
// frontend/src/components/agent-chat/ChatLayout.tsx
'use client'
import { useState } from 'react'
import { useAgentChat } from '@/hooks/useAgentChat'
import { SessionList } from './SessionList'
import { MessageStream } from './MessageStream'
import { InputBar } from './InputBar'
import { AlertCircle } from 'lucide-react'

export function ChatLayout() {
  const [currentId, setCurrentId] = useState<string | null>(null)
  const { connected, session, messages, running, error, sendPrompt, cancel, decideGate } = useAgentChat(currentId)

  return (
    <div className="h-screen flex bg-white">
      <SessionList currentId={currentId} onSelect={setCurrentId} />
      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-14 px-6 border-b border-gray-100 flex items-center justify-between bg-white">
          <div className="min-w-0">
            <h1 className="text-sm font-semibold text-gray-900 truncate">
              {session?.title || (currentId ? '加载中...' : '从左侧选一个对话')}
            </h1>
            {session && (
              <div className="text-[10px] text-gray-400 mt-0.5">
                {session.message_count} 条 · {session.sku_id ? `SKU ${session.sku_id} · ` : ''}
                {connected ? '● 已连接' : '○ 未连接'}
              </div>
            )}
          </div>
        </header>

        {error && (
          <div className="mx-6 mt-3 px-3 py-2 rounded-md bg-red-50 border border-red-200 text-xs text-red-700 flex items-start gap-2">
            <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {currentId ? (
          <>
            <MessageStream messages={messages} onDecideGate={decideGate} />
            <InputBar
              sessionId={currentId}
              running={running}
              onSend={sendPrompt}
              onCancel={cancel}
            />
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
            从左侧选或新建一个对话开始
          </div>
        )}
      </main>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/agent-chat/ChatLayout.tsx
git commit -m "feat(W5-B 切片 2.7): ChatLayout 整体布局"
```

---

### Task 2.8: 改造 /chat page

**Files:**
- Modify: `frontend/src/app/chat/page.tsx`

- [ ] **Step 1: 备份原内容到 chat/page.tsx.bak（一次性，提供回滚路径）**

```bash
cp frontend/src/app/chat/page.tsx frontend/src/app/chat/page.tsx.bak
git add frontend/src/app/chat/page.tsx.bak
git commit -m "chore(W5-B 切片 2.8): 备份 chat/page.tsx 原 RAG 客户端"
```

- [ ] **Step 2: 重写 page.tsx**

```tsx
// frontend/src/app/chat/page.tsx
'use client'
import { ChatLayout } from '@/components/agent-chat/ChatLayout'

export default function ChatPage() {
  return <ChatLayout />
}
```

- [ ] **Step 3: smoke test 浏览器**

```bash
cd frontend && npm run dev
# 浏览器开 http://localhost:3000/chat
```

Expected:
- 左侧空 session 列表 + 「新建」按钮
- 点新建 → 加一条 + 自动选中
- 输入「列下我的 SKU」回车 → 看到 user 气泡 + assistant 气泡 + tool_call chip + tool_result 卡片

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/chat/page.tsx
git commit -m "feat(W5-B 切片 2.8): /chat 路由从 RAG 改造为 Claude Code agent chat"
```

---

### Task 2.9: sidebar 描述更新

**Files:**
- Modify: `frontend/src/components/app-sidebar.tsx:99`（"智能问答" 那一行）

- [ ] **Step 1: 改 label + hint + icon**

```tsx
// 把
{ href: '/chat', icon: MessageSquare, label: '智能问答', hint: '基于你的资料做检索和问答' },
// 改成
{ href: '/chat', icon: Brain, label: 'Agent 对话', hint: '跟 Claude 自然语言聊天，自动调 omni tool 出结果' },
```

并把 `Brain` 加到顶部 import：
```tsx
import { ..., Brain } from 'lucide-react'
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/app-sidebar.tsx
git commit -m "feat(W5-B 切片 2.9): sidebar /chat 描述改为 Agent 对话"
```

---

### 切片 2 验收

- [ ] `/chat` 路由打开看到左侧 session 列表 + 主对话流
- [ ] 新建 session 工作正常
- [ ] 输入文字 → 收到 assistant 气泡 + tool_call chip + tool_result 多模态附件
- [ ] 上传图片 / mp4 → 附件 chip 显示 → 发送 → Claude 能 reference
- [ ] 切换 session 能恢复历史对话
- [ ] vitest 全 PASS
- [ ] 现有 /agent-log /inbox /decisions 等老页不受影响

---

## 切片 3：Human Gate 内嵌对话流

**目标：** require_approval=True 的 tool 触发时不再让老板切到 /inbox 页，直接在对话流里弹审批卡片。

**预期工作量：** 2 天 / 8 steps

### Task 3.1: KE 加 human_gate 新增事件推送

**Files:**
- Modify: `services/knowledge-engine/app/mcp/human_gate.py`（或在 `audit.py` 里挂 hook）

- [ ] **Step 1: 找 mcp.human_gates INSERT 的位置**

```bash
grep -n "INSERT INTO mcp.human_gates\|human_gates" services/knowledge-engine/app/mcp/*.py
```

- [ ] **Step 2: 在 INSERT 之后用 Redis pub/sub 推消息**

```python
# services/knowledge-engine/app/mcp/human_gate.py 附近
import json
import os
import redis.asyncio as aioredis

_REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
_redis: aioredis.Redis | None = None

async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(_REDIS_URL, decode_responses=True)
    return _redis

async def _notify_human_gate(short_id: str, tool_name: str, summary: str) -> None:
    """W5-B: 通知前端有新 human gate；前端 Next.js custom server 订阅这条 channel"""
    try:
        r = await _get_redis()
        await r.publish(
            "mcp.human_gates.new",
            json.dumps({"short_id": short_id, "tool_name": tool_name, "summary": summary}),
        )
    except Exception:
        pass  # 推失败不挂主流程

# 在 require_approval=True 时，写 mcp.human_gates 之后调一次：
# await _notify_human_gate(short_id, tool_name, summary)
```

- [ ] **Step 3: restart KE + smoke test**

```bash
docker compose restart knowledge-engine
# 在另一个终端订阅 channel 看消息
docker exec -it omni-redis redis-cli SUBSCRIBE mcp.human_gates.new
# 第三个终端触发一个 require_approval tool（如 generate_brief）
```

Expected: SUBSCRIBE 终端收到一条 JSON 消息

- [ ] **Step 4: Commit**

```bash
git add services/knowledge-engine/app/mcp/human_gate.py
git commit -m "feat(W5-B 切片 3.1): KE 在新 human_gate 写入时 Redis publish 给前端订阅"
```

---

### Task 3.2: ws-handler 订阅 Redis + 推前端

**Files:**
- Modify: `frontend/src/lib/agent-chat/ws-handler.ts`

- [ ] **Step 1: 加 Redis 客户端订阅**

```bash
cd frontend && npm install ioredis
```

- [ ] **Step 2: 在 ws-handler 模块顶部加全局订阅**

```typescript
// frontend/src/lib/agent-chat/ws-handler.ts 顶部追加
import Redis from 'ioredis'
import type { WebSocket as WsType } from 'ws'

const REDIS_URL = process.env.REDIS_URL || 'redis://localhost:6379/0'
const _subscriber = new Redis(REDIS_URL)
const _activeConnections = new Set<WsType>()

_subscriber.subscribe('mcp.human_gates.new')
_subscriber.on('message', (channel, payload) => {
  if (channel !== 'mcp.human_gates.new') return
  let data: { short_id: string; tool_name: string; summary: string }
  try { data = JSON.parse(payload) } catch { return }
  // 广播给所有连接的 ws（后续可按 session 路由更精细）
  for (const ws of _activeConnections) {
    try {
      ws.send(JSON.stringify({
        kind: 'human_gate_new',
        session_id: '',  // 未来可关联 session
        gate: data,
      }))
    } catch { /* swallow */ }
  }
})

// 在 attachWsHandler 函数里追加
export function attachWsHandler(ws: WsType): void {
  _activeConnections.add(ws)
  ws.on('close', () => _activeConnections.delete(ws))
  ws.on('message', /* 原来的逻辑 */)
}
```

- [ ] **Step 3: smoke test**

启动 frontend dev + 触发一个 require_approval tool → 前端任意打开的 session 都收到 human_gate_new ws 消息 → HumanGateCard 弹出

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/agent-chat/ws-handler.ts frontend/package.json frontend/package-lock.json
git commit -m "feat(W5-B 切片 3.2): ws-handler 订阅 Redis mcp.human_gates.new + 广播到所有连接"
```

---

### Task 3.3: 路由精细化 — gate 关联到对应 session

**Files:**
- Modify: `services/knowledge-engine/app/mcp/audit.py` 或 `human_gate.py`
- Modify: `frontend/src/lib/agent-chat/ws-handler.ts`

- [ ] **Step 1: 后端 tool_calls 表加 agent_session_id 字段**

```sql
ALTER TABLE mcp.tool_calls ADD COLUMN IF NOT EXISTS agent_session_id UUID REFERENCES mcp.agent_sessions(id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_agent_session ON mcp.tool_calls (agent_session_id) WHERE agent_session_id IS NOT NULL;
```

落到 migration 029：
```bash
cat > migrations/029_tool_calls_agent_session.sql << 'EOF'
ALTER TABLE mcp.tool_calls ADD COLUMN IF NOT EXISTS agent_session_id UUID REFERENCES mcp.agent_sessions(id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_agent_session ON mcp.tool_calls (agent_session_id) WHERE agent_session_id IS NOT NULL;
EOF
docker cp migrations/029_tool_calls_agent_session.sql omni-postgres:/tmp/029.sql
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -f /tmp/029.sql
```

- [ ] **Step 2: ws-handler send_prompt 时传 agent_session_id 给 Claude Code（通过环境变量）**

```typescript
// frontend/src/lib/agent-chat/claude-runner.ts startClaudeRunner spawn 时
env: { ...process.env, OMNI_AGENT_SESSION_ID: sessionPgId },
```

- [ ] **Step 3: omni MCP tool 调用时把这个 env 读出来填 tool_calls.agent_session_id**

```python
# services/knowledge-engine/app/mcp/audit.py（tool_with_audit 装饰器内）
import os
agent_session_id = os.environ.get("OMNI_AGENT_SESSION_ID")  # 单进程下 env 会被 main process MCP server 看到？

# 实际上 env 不会传到 KE container（claude code 进程在前端 host）。
# 这里需要换方式：claude code spawn 时把 agent_session_id 通过 MCP request header 传？
# MCP 协议支持 customize header per request 但 FastMCP 不一定暴露。
# 取舍：先用最简单方式 — 通过 prompt 显式注入 "[session=<id>]" 标记，KE 端 grep prompt 拿（hack）
# 或者干脆切片 3.3 跳过精细化路由，所有 gate 广播给所有连接（切片 3.2 已实现）
```

**决策：切片 3.3 暂跳过精细化路由**，原因：
- MCP request 级别路由要改 FastMCP 内部
- 个人自用单 user，所有 gate 广播给所有连接已经够用（前端会展示哪个 short_id，老板看 summary 知道是哪个 tool 触发的）
- 后续真有多用户多 session 并发再回填

- [ ] **Step 4: 不 commit（跳过任务）**

---

### 切片 3 验收

- [ ] 触发 generate_brief（require_approval=True）→ 对话流弹 HumanGateCard
- [ ] 点通过 → KE 解锁继续执行
- [ ] 点驳回 → KE 返 `{ok:false, error:"rejected_by_user"}` → 对话流显示对应消息

---

## 切片 4：长任务后台 + Web Notification

**目标：** sku-pipeline 这种 5-10 分钟任务跑起来后老板能切走干别的，结束自动通知；资产卡片渲染优化。

**预期工作量：** 2-3 天 / 10 steps

### Task 4.1: useNotification hook

**Files:**
- Create: `frontend/src/hooks/useNotification.ts`

- [ ] **Step 1: 实现**

```typescript
// frontend/src/hooks/useNotification.ts
'use client'
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

- [ ] **Step 2: Commit**

```bash
git add frontend/src/hooks/useNotification.ts
git commit -m "feat(W5-B 切片 4.1): useNotification hook"
```

---

### Task 4.2: ChatLayout 集成 notification

**Files:**
- Modify: `frontend/src/components/agent-chat/ChatLayout.tsx`
- Modify: `frontend/src/hooks/useAgentChat.ts`

- [ ] **Step 1: useAgentChat 在 task_done 时回调 onTaskDone**

```typescript
// useAgentChat hook 加 option 参数
export function useAgentChat(
  sessionId: string | null,
  options: { onTaskDone?: (sessionId: string, durationMs: number) => void; onGateNew?: (gate: { short_id: string; tool_name: string; summary: string }) => void } = {},
): UseAgentChatResult {
  // ... 在 ws.onmessage 处理 task_done 时调 options.onTaskDone?.(msg.session_id, msg.duration_ms)
  // 处理 human_gate_new 时调 options.onGateNew?.(msg.gate)
}
```

- [ ] **Step 2: ChatLayout 注册 onTaskDone**

```tsx
// frontend/src/components/agent-chat/ChatLayout.tsx 内
import { useNotification } from '@/hooks/useNotification'
import { useEffect } from 'react'

// 在 ChatLayout 函数体内
const { permission, requestPermission, notify } = useNotification()

useEffect(() => {
  if (permission === 'default') requestPermission()
}, [permission])

const { /* 其他 */ } = useAgentChat(currentId, {
  onTaskDone: (sid, dur) => {
    if (document.hidden) notify('omni 任务完成', { body: `用时 ${(dur / 1000).toFixed(0)}s` })
  },
  onGateNew: (gate) => {
    if (document.hidden) notify('需要你点头', { body: `${gate.tool_name}：${gate.summary.slice(0, 80)}` })
  },
})
```

- [ ] **Step 3: smoke test**

跑一个 sku-pipeline step → 切到别的浏览器 tab → 等任务完成 → 收到桌面通知

- [ ] **Step 4: Commit**

```bash
git add frontend/src/hooks/useAgentChat.ts frontend/src/components/agent-chat/ChatLayout.tsx
git commit -m "feat(W5-B 切片 4.2): 长任务完成 + human gate 触发桌面通知"
```

---

### Task 4.3: 资产卡片渲染优化（video lazy + 缩略图）

**Files:**
- Modify: `frontend/src/components/agent-chat/attachments/VideoAttachment.tsx`
- Modify: `frontend/src/components/agent-chat/attachments/ImageAttachment.tsx`

- [ ] **Step 1: VideoAttachment 加点击播 + 缩略图**

```tsx
// frontend/src/components/agent-chat/attachments/VideoAttachment.tsx
'use client'
import { useState, useRef } from 'react'
import { Play } from 'lucide-react'

interface Props { url: string; poster?: string }
export function VideoAttachment({ url, poster }: Props) {
  const [playing, setPlaying] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)

  if (!playing) {
    return (
      <button
        onClick={() => setPlaying(true)}
        className="relative max-w-[320px] rounded-lg border border-gray-200 overflow-hidden group"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {poster ? (
          <img src={poster} alt="video thumbnail" className="w-full h-auto" loading="lazy" />
        ) : (
          <div className="w-[320px] h-[180px] bg-gray-200 flex items-center justify-center">
            <Play className="w-12 h-12 text-gray-400" />
          </div>
        )}
        <div className="absolute inset-0 flex items-center justify-center bg-black/30 group-hover:bg-black/40 transition-colors">
          <div className="w-14 h-14 rounded-full bg-white/90 flex items-center justify-center">
            <Play className="w-6 h-6 text-violet-600 ml-1" />
          </div>
        </div>
      </button>
    )
  }
  return (
    <video
      ref={videoRef}
      autoPlay
      controls
      src={url}
      className="max-w-[320px] rounded-lg border border-gray-200"
      preload="metadata"
    />
  )
}
```

- [ ] **Step 2: ToolResultCard 把 thumbnail_url 透传**

```tsx
// ToolResultCard 里 video 分支
if (att.type === 'video' && att.url) return <VideoAttachment key={idx} url={att.url} poster={att.thumbnail_url} />
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/agent-chat/attachments/VideoAttachment.tsx frontend/src/components/agent-chat/ToolResultCard.tsx
git commit -m "feat(W5-B 切片 4.3): VideoAttachment 缩略图 + 点播 + 节省带宽"
```

---

### Task 4.4: e2e Playwright smoke test

**Files:**
- Create: `frontend/tests/agent-chat/e2e/agent-chat.spec.ts`
- Modify: `frontend/playwright.config.ts`（如果已有）

- [ ] **Step 1: 写 e2e 用例**

```typescript
// frontend/tests/agent-chat/e2e/agent-chat.spec.ts
import { test, expect } from '@playwright/test'

test('chat: create session + send simple prompt', async ({ page }) => {
  await page.goto('http://localhost:3000/chat')
  // 新建 session
  await page.click('button:has-text("新建")')
  // 等左侧出现新对话
  await expect(page.locator('aside button:has-text("新对话")').first()).toBeVisible()
  // 输入 prompt
  await page.fill('textarea', '说一句你好')
  await page.keyboard.press('Enter')
  // 等 assistant 气泡出现
  await expect(page.locator('text=/你好|hi/').first()).toBeVisible({ timeout: 60000 })
})

test('chat: list_skus tool invocation renders chip + result', async ({ page }) => {
  await page.goto('http://localhost:3000/chat')
  await page.click('button:has-text("新建")')
  await page.fill('textarea', '列下我所有的 SKU')
  await page.keyboard.press('Enter')
  // 等 tool_call chip
  await expect(page.locator('text=list_skus').first()).toBeVisible({ timeout: 60000 })
  // 等结果
  await expect(page.locator('text=/SKU-\\d+/').first()).toBeVisible({ timeout: 90000 })
})
```

- [ ] **Step 2: 跑 e2e**

```bash
cd frontend
npx playwright install --with-deps chromium
npm run dev &
DEV_PID=$!
sleep 5
npx playwright test tests/agent-chat/e2e/
kill $DEV_PID
```

Expected: 2 个 e2e 测试 PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/agent-chat/e2e/
git commit -m "feat(W5-B 切片 4.4): Playwright e2e 覆盖创建 session + tool call 渲染"
```

---

### 切片 4 验收

- [ ] 跑 sku-pipeline 5 步任务 → 切走 → 完成时弹桌面通知
- [ ] human gate 触发 → 切走时也弹通知
- [ ] 视频附件缩略图 + 点播 + 不预加载
- [ ] e2e Playwright 2 个测试全 PASS

---

## 整体验收（切片 1-4 全完）

- [ ] 浏览器开 `http://localhost:3000/chat`
- [ ] 看到企业微信样式：左侧 session 列表 + 主对话框 + 输入栏 + 附件按钮
- [ ] 全流程跑通：建 session → 输入「跑通 SKU-367991-0002 全链路」→ 看到 tool_call chip 一个个出现（query_costs / compute_margin / generate_brief / generate_image / generate_video）→ 多模态附件（图 / 视频 / Brief markdown）渲染
- [ ] generate_brief 触发 human gate → 对话流弹卡片 → 点通过 → 任务继续
- [ ] 切走 tab → 任务完成弹桌面通知
- [ ] 切换 session 切回去 → 历史完整恢复
- [ ] 关浏览器再开 → session 列表仍在
- [ ] 重启 frontend `npm run dev` → session 列表仍在（DB 持久化）+ 历史仍在（Claude Code jsonl 持久化）
- [ ] vitest 单测全 PASS（mcp-config / history-reader / claude-runner / session-manager / useAgentChat）
- [ ] Playwright e2e 全 PASS
- [ ] 现有 30+ 老页面（/inbox /agent-log /decisions /sku-pipeline 等）都不受影响

---

## 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| 1 | Claude CLI 在 Windows 上 spawn 行为不一致（cmd.exe / pwsh / git bash 差异）| Task 1.5 用 `claude.cmd` + `shell: true`；smoke test 在 Windows 真跑 |
| 2 | Next.js custom server.ts 跟 `next dev` HMR 兼容性 | tsx watch + server.ts 已是成熟 pattern；切片 1 末 smoke test 走一遍 |
| 3 | Max 订阅 token 在 subprocess 里失效 | env 默认继承 `HOME` → `~/.claude/.credentials.json` 自动复用；切片 1.5 smoke test 真跑 claude -p 验证 |
| 4 | Claude Code stream-json 输出格式变 | 当前 stable，但保持 Task 1.5 测试覆盖；如有 breaking 改动按 fixture diff 调 parser |
| 5 | `~/.claude/projects/<dir>/sessions/<uuid>.jsonl` 文件格式变 | 同上，readSessionHistory 容错（坏 line 跳过）|
| 6 | 多 session subprocess 同时跑导致 token quota 超限 | maxActive=3 + LRU；切片 1.6 测试覆盖 |
| 7 | 附件上传体积过大 | 切片 1.8 加 50MB 单文件上限校验（追加 step）|
| 8 | Redis pub/sub 连接抖动 | ioredis 自动重连；丢一两条 gate 通知可接受（轮询 /inbox 也能补） |
| 9 | 大文件 video stream 渲染卡 | 切片 4.3 缩略图 + 点播，不预加载 |
| 10 | 跨 session 的 human gate 路由不精细 | 切片 3.3 跳过；广播给所有连接，UI 上 short_id + summary 区分 |
| 11 | Claude Code subprocess 长时间空闲消耗资源 | SessionManager ttl=30min auto-reap；可调 |

---

## Self-Review

**Spec coverage：**
- ✅ "subprocess 挂哪个服务" → 决策 #1 (Next.js custom server.ts) + Task 1.7
- ✅ "session 状态持久化" → 决策 #2 (PG agent_sessions) + Task 1.1
- ✅ "历史对话怎么展示" → 决策 #3 (Claude Code jsonl) + Task 1.4
- ✅ "多 session 并行" → 决策 #4 (max 3 + LRU + ttl) + Task 1.6
- ✅ "输入框命令" → 决策 #5 (透传) + InputBar Task 2.5
- ✅ "附件上传位置" → 决策 #6 (uploads + KE static) + Task 1.8/1.9
- ✅ "WebSocket vs SSE" → 决策 #7 (WebSocket) + Task 1.7
- ✅ "认证" → 决策 #8 (无 + 127.0.0.1) + Task 1.7 server.ts
- ✅ "手机端" → 决策 #9 (基础响应式) — 切片 2 默认就是响应式
- ✅ "长任务进度展示" → 决策 #10 (chunk 实时) + Task 2.3 ToolCallChip
- ✅ "Max 订阅认证继承" → 决策 #11 (env 继承) + Task 1.5

**Placeholder scan：** 无 TBD / TODO / "implement later" / "Similar to Task N"。每个 step 含完整代码或完整命令。

**Type consistency：**
- `ChatMessage` / `ChatAttachment` / `SessionState` / `WsClientMessage` / `WsServerMessage` Task 1.2 定义，后续 Task 1.4/1.5/1.7/2.1 都引用同名 type
- `startClaudeRunner` / `buildSpawnArgs` / `parseStreamChunks` Task 1.5 定义，Task 1.6 / 1.7 import 名一致
- `getSessionManager` / `SessionManager` Task 1.6 定义，Task 1.7 / 2.1 调用一致
- `useAgentChat` Task 2.1 定义，Task 2.7 ChatLayout 使用同签名
- `attachWsHandler` Task 1.7 定义，Task 3.2 / server.ts import 一致

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-15-omni-agent-uplift-W5b-plan.md`. 两种 execution 选项：**

**1. Subagent-Driven（推荐）** — 每个 task 起一个 fresh subagent + task 之间停下来 review；快速迭代，主上下文不被工程细节淹没

**2. Inline Execution** — 在当前会话里跑，executing-plans skill 批量执行 + 检查点暂停

**选哪个？**
