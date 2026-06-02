# /playground 路由实现 plan — 多层 LLM 验证场

> 2026-05-25 老板"先不做手机端,先做 playground 验证场"决策驱动写的 plan

## 一句话目标

omni frontend 加一个 `/playground` 路由,做 DEV 写代码 → PROD 桌面端实战 之间
的**验证夹层**:隔离测刚写的 tool / SKILL.md / MCP,看到主 Claude + 次级
LLM 调用的完整套娃 trace,实测真 tool 真写库但不污染生产 session。

## 现状盘点 — 缺的就是这一层

omni 现有三处可以跟 agent 对话:

| 入口 | 实质 | 缺点 |
|---|---|---|
| `claude` terminal（DEV） | 在 `E:\agent\omni` 跟 Claude Code 写代码 | 看不到 raw trace,改完 tool 想验证得手动改话术触发 |
| `/chat` web 版 | 桌面端的 fallback 双胞胎 | 没有 config 面板,没多层 trace,session 全混在一起 |
| omni-desktop（PROD） | Gemini 风全局快捷键,跑日常业务 | 实战环境,不适合一边改一边验证,失败污染生产 history |

agent 内部其实是套娃架构:

```
Claude（主大脑,spawn claude.cmd,走 Max 订阅）
  --tool_use--> omni KE MCP tool（如 generate_brief）
                --HTTP--> ai-provider-hub :8001
                          --route--> OpenAI / Gemini / Anthropic / DeepSeek / Seedance / Kling
```

CLAUDE.md 已硬约束"LLM tool 必返 trace 字段",所以次级 LLM 调用信息都塞进了
tool_result.trace。**playground 不动后端,只做 UI 把这层套娃渲染出来**——这是
本 plan 的 90% 价值。

## 三阶段工作流定位

```
阶段 1 DEV   : terminal 跑 claude 在 omni 项目对话写代码（加 tool / SKILL / MCP）
阶段 2 VERIFY: 新 /playground 路由 ← 本 plan 解决这一阶段
阶段 3 PROD  : omni-desktop 桌面端,Cmd+Shift+Space 唤起日常用
```

playground 不取代任何一个,夹在中间。

## 3 个核心决策记录

### 决策 1 = b:复用 spawn claude.cmd,不引 Anthropic SDK 直调

**理由**:SDK 直调要重做 agent loop + skill loader + MCP client + tool 调度,
工程量 2-3 个月。spawn claude.cmd 走 Max 订阅 0 额外 API cost,已有
`lib/agent-chat/claude-runner.ts` 跑通。

**副作用**:主 Claude 那层算不出具体 USD(Max 订阅按月固定),UI 标"Max 订阅"
即可。次级 LLM 通过 ai-provider-hub 走的还是真 API,cost 能算出来。

### 决策 2 = a+b:共享数据库 + 共享 KE MCP,但 sandbox 标记

**a 部分**:playground 调真 tool 真写 `mvp_sku` / `cost_items` / `pipeline.*`
等所有表——最贴近生产,复用已有基建。

**b 部分**:playground 创建的 `mcp.agent_sessions` 行加 `sandbox=true` 字段,
`/chat` 的 SessionList 默认 `WHERE sandbox=false` 过滤掉,不污染生产 session
列表。

不为 playground 起独立 KE 容器/独立 DB schema,过度工程
([[feedback-personal-use-no-overengineering]])。

### 决策 3 = a:加在 omni frontend 当 /playground 路由

**不做独立 Electron app**:新仓库 + 双轨打包维护成本高。
**不嵌入桌面端 BrowserView**:桌面端是 PROD,塞个 VERIFY 进去定位混乱。
**直接复用 Next.js + Tailwind + Zustand**:36 个页面里加 1 个,工程量最低。

## 关键设计:多层 LLM trace 渲染

UI 目标长这样:

```
[主 Claude] sonnet-4.6 · 3.2s · 1245 tok in / 387 out · Max 订阅
└─ tool_use #1: generate_brief
   ├─ input  : { sku_id: "SKU-375753-0001", channel: "douyin" }
   ├─ output : { brief: "...", sources: [...] }
   └─ trace  :
      ├─ provider       : ai-provider-hub
      ├─ model          : gemini-2.5-flash
      ├─ final_prompt   : "..."（点击展开 full text）
      ├─ retrieved_sources: 3 条 KB chunks（点击看每条 score + content）
      ├─ latency        : 8.4s
      └─ cost           : $0.0023 ← 真实 API 钱
─────────────────────────────────────────────
[主 Claude] 续轮 sonnet-4.6 · 1.8s · ...
└─ tool_use #2: generate_image
   └─ trace.cost: $0.045
─────────────────────────────────────────────
汇总 : 主 Claude 5 轮 / 3 次 tool_use
真实 API cost: $0.27（不含 Max 订阅主 Claude 层）
总 latency  : 28.4s
```

至少这些 omni tool 内部调外部 LLM,所有都已落 trace:

- `generate_brief` / `generate_image` / `generate_video` / `generate_image_compare`
- `generate_selling_points_matrix` / `generate_audience_match` / `generate_audience_pack`
- `generate_keyword_pack` / `generate_creative_pack`
- `gather_brief_context` / `parse_long_doc_with_gemini` / `summarize_text`
- `query_template_chunks`

playground 的 TracePane 拿到 tool_result 后,递归渲染 `trace` 字段下的 prompt /
model / cost / latency / sources,折叠展开。

## 5 切片拆分

### 切片 1 — migration + sidebar 入口 + 三栏骨架(0.5 天)

**migration 030**:

```sql
ALTER TABLE mcp.agent_sessions ADD COLUMN sandbox BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX idx_sessions_sandbox ON mcp.agent_sessions(sandbox) WHERE sandbox = TRUE;
```

`/chat` SessionList 的 list 查询加 `WHERE sandbox = FALSE`(切片 5 再改,这里
只先加字段)。

**前端骨架**:

- `frontend/src/app/playground/layout.tsx` + `page.tsx`
- 三栏 grid:`ConfigPanel`(左,280px) + `ConvPane`(中,flex-1) + `TracePane`
  (右,420px)
- 主 nav / Sidebar 加 "Playground" 入口,标 badge "VERIFY"
- 移动端响应:< md 自动折叠成 tab 切换(同 `/chat` 套路,但优先级低)

### 切片 2 — ConfigPanel + Zustand store(1 天)

`frontend/src/stores/playground.ts` Zustand store:

```ts
interface PlaygroundState {
  modelOverride: string | null      // null = 用默认 sonnet-4.6
  allowedTools: string[] | null     // null = 全开;数组 = 白名单
  extraSystemPrompt: string         // append 到 system prompt
  maxTurns: number                  // 默认 25
  currentSessionId: string | null
  setConfig: (patch: Partial<PlaygroundState>) => void
}
```

`ConfigPanel.tsx` 元素:

| 控件 | 实现 |
|---|---|
| Model 选择 | `<select>` 列 `sonnet-4.6` / `opus-4.7` / `haiku-4`(从 KE `/api/models` 拉) |
| Tool 多选 | 46 个 tool 复选框 + "全选 / 全关 / 默认"快捷按钮,折叠按 W4-B 分组(查询/算账/生成/编排/...) |
| Extra system prompt | `<textarea>` 5 行,实时字数,本地存 localStorage |
| Max turns | `<input type=number>` 默认 25,范围 1-50 |
| 启动新 sandbox session | 按钮,POST 创建 `agent_sessions` row sandbox=true,落 store |

**关键**:这一切只是前端态,提交时通过 ws message 透传给后端。

### 切片 3 — ConvPane 复用 /chat handler(1 天)

`ConvPane.tsx` 直接复用 `frontend/src/lib/agent-chat/ws-handler.ts` +
`MessageBubble` 组件,**不重写流式解析**。改造点:

- `lib/playground/api.ts` 包一层,WS 连接 URL 改成 `/api/playground/ws` 而非
  `/api/agent-chat/ws`,handshake 时多带 `{model_override, allowed_tools,
  extra_system_prompt, max_turns}` 4 个 config
- 新建 `frontend/src/app/api/playground/ws/route.ts`:大体抄 agent-chat/ws,
  spawn claude 时把 config 翻译成 CLI flag:
  - `model_override` → `--model <id>`
  - `allowed_tools` → `--allowedTools <csv>`
  - `extra_system_prompt` → 拼到 prompt 头部 (Claude Code CLI 没原生 system
    override flag,只能 prompt prepend)
  - `max_turns` → `--max-turns <n>`
- ConvPane 渲染 message stream:user / assistant / tool_use chip /
  tool_result。tool_use chip 点击 → 选中态,联动 TracePane 高亮对应那一层

**复用清单**(不动):

- `lib/agent-chat/session-manager.ts`(LRU 跟 spawn 管理)
- `lib/agent-chat/claude-runner.ts`(spawn 子进程)
- `lib/agent-chat/history-reader.ts`(读 jsonl history)
- `lib/agent-chat/ws-handler.ts`(handshake / chunk 转发)

只在 ws/route.ts 入口加 config 透传,底层零改动。

### 切片 4 — TracePane 多层 trace 树(1 天)

`TracePane.tsx` 数据源:`ConvPane` 收到的每个 `tool_result` chunk 里
`content` 数组扫 `trace` 字段。

渲染逻辑:

```
foreach assistant message in conversation:
  render "主 Claude 第 N 轮" header(model / latency / tok in/out)
  foreach tool_use in message:
    render tool name + input
    if 对应 tool_result.trace 存在:
      render trace tree(provider / model / final_prompt / sources / latency / cost)
汇总区: sum(trace.cost) + sum(latency)
```

trace 字段结构 omni tool 内部已统一:

```json
{
  "provider": "ai-provider-hub",
  "model": "gemini-2.5-flash",
  "final_prompt": "...",
  "retrieved_sources": [{"kb_role": "authoritative", "score": 0.83, "content": "..."}],
  "latency_ms": 8400,
  "cost_usd": 0.0023,
  "raw_response_preview": "..."
}
```

UI 细节:

- `final_prompt` 长 → 折叠,默认显前 200 字 + "展开"按钮
- `retrieved_sources` 表格化:role / score / preview / 跳 KB 详情链接
- `cost_usd` null(LLM 没返用量) → 显 "N/A"
- tool 内部没调外部 LLM(如 `query_costs` 纯查库)→ trace 段缩成 "纯查询,无
  LLM 调用"

切换 tool_use chip 选中态 → TracePane 滚到对应那块并高亮 1s。

### 切片 5 — sandbox 隔离收尾 + smoke 测试(0.5 天)

**改 `/chat` SessionList 查询**:

```ts
// frontend/src/lib/agent-chat/session-manager.ts 的 listSessions()
WHERE sandbox = FALSE
ORDER BY updated_at DESC
```

playground 自己的 session 列表(可选,MVP 不一定做):`ConfigPanel` 顶部
"历史 sandbox session" dropdown,query `WHERE sandbox = TRUE LIMIT 20`,点击
切回旧 session resume。

**smoke 测试**(Playwright,沿用 omni-desktop W5-C 测套路):

1. 开 `/playground`,断言三栏渲染
2. 点 "启动新 session" → 断言 ws 连接成功
3. 输入 "查 SKU-375753-0001 成本" → 断言出现 tool_use chip
4. 断言 TracePane 出现至少 1 层 trace 节点
5. 关闭后,SQL 验证 `mcp.agent_sessions WHERE sandbox = TRUE LIMIT 1` 命中

## 文件清单

**新建**:

- `frontend/src/app/playground/page.tsx`
- `frontend/src/app/playground/layout.tsx`
- `frontend/src/app/api/playground/ws/route.ts`
- `frontend/src/components/playground/PlaygroundLayout.tsx`
- `frontend/src/components/playground/ConfigPanel.tsx`
- `frontend/src/components/playground/ConvPane.tsx`
- `frontend/src/components/playground/TracePane.tsx`
- `frontend/src/components/playground/MessageBubble.tsx`(轻封装 /chat 的版本)
- `frontend/src/components/playground/ToolCallChip.tsx`
- `frontend/src/stores/playground.ts`
- `frontend/src/lib/playground/api.ts`
- `migrations/030_playground_sandbox.sql`

**改动**:

- `frontend/src/lib/agent-chat/session-manager.ts`:listSessions 加
  `WHERE sandbox = FALSE`
- 主 nav / Sidebar 组件:加 `/playground` 入口

**零改动**(纯复用):

- `lib/agent-chat/{claude-runner,ws-handler,history-reader}.ts`
- 9 个 FastAPI 微服务 / KE MCP server / 46 个 tool / 7 个 skill

## 工期估算

| 切片 | 工期 | 关键产出 |
|---|---|---|
| 1 migration + 骨架 | 0.5 天 | 字段 + 三栏空架 + 入口 |
| 2 ConfigPanel | 1 天 | 4 个 config 控件 + store + sandbox session 创建 |
| 3 ConvPane | 1 天 | ws 路由 + config 透传 + 复用 /chat 流式 |
| 4 TracePane | 1 天 | 多层 trace 树 + cost 汇总 |
| 5 sandbox 隔离 + 测试 | 0.5 天 | /chat 过滤 + Playwright smoke |
| **合计** | **4 天** | |

## 后置 / 不做

- **Anthropic SDK 直调主 Claude 层**:工程量 2-3 月,Max 订阅已经够用
- **多用户**:个人自用([[feedback-personal-use-no-overengineering]])
- **session 永久存档**:sandbox 行可周期清理,UI 不做存档面板
- **嵌入桌面端 BrowserView**:决策 3 = a 已排除
- **手机端 PWA**:老板明确说先不做手机端,本 plan 不含移动响应优化(基础响应够用即可)
- **playground 跑独立 KE 容器/DB schema**:沙箱过度工程,sandbox 字段够用
- **trace 历史回放**:每次 sandbox session 重跑即可,不做"昨天那次 trace 再看一遍"

## 跟其他面的关系

| | 关系 |
|---|---|
| omni-desktop(PROD) | playground 是验证场,桌面端跑日常 — 不取代不冲突 |
| `/chat`(web 版) | `/chat` 是桌面端的 fallback 双胞胎;`/playground` 走完全不同分支,验证用 |
| KE MCP server(46 tool) | 直接复用,playground 不重写 tool |
| skill(`.claude/skills/` 7 个) | 直接复用,playground 也能触发 skill |
| W6 三端协同(PWA) | 不相干,playground 是桌面浏览器场景 |
| W7 omni-orch | 不相干,orch 是跨项目远程编排,playground 只验证 omni 自己 |
