# Mobile Orchestrator MVP — 手机控制家里 Claude Code

> 2026-05-17 老板出差路上的真实痛点驱动写的 plan
> 取代当时一并被 revert 的 `2026-05-17-claude-orchestrator-plan.md` 方向

## 一句话目标

老板在外面（OPPO Find N6 / Mac），能通过手机/Mac 远程**让家里 Win 上的 Claude
Code 在任意项目目录跑开发任务**，实时看到结果（文字 + 图片），撞 Claude
usage limit 时手机点"定时几点续跑"自动恢复。

## 现状盘点（不用从零做）

- omni-desktop (`E:\agent\omni-desktop\`) 已经是一个 Claude Code 桥:
  - `src/main/claude-runner.ts` 已 spawn `claude.cmd -p <prompt>
    --output-format stream-json --verbose --mcp-config <path>
    [--resume <session_id>] [--allowedTools] [--max-turns]`，**cwd 参数自由**
  - `src/main/session-manager.ts` 已管 session（LRU 3 并发 + 30min TTL）
  - chunk 解析已抽 image/video/markdown attachment（ipc-handler line 100-122）
- omni frontend `/chat` (agent-chat) 已有完整 UI（session list / message stream /
  tool call chip / human gate card / 移动响应式 W6 已复活）
- W6 PWA + Tailscale/cloudflared 路径已就绪（commit 1d371c6）

**缺的就 4 件**：① cwd 跨项目 ② HTTP/WS server（让手机能远程调，不只 Electron
IPC）③ usage_limit 检测 + 续跑 ④ 手机端 UI shell

## MVP 拆 5 切片

### 切片 1 — DB migration + cwd 跨项目支持（0.5 天）

**目的**：让 omni-desktop 跑任意目录的 Claude Code，不锁死 omni 自己。

**改**：
- `migrations/029_orch_lineage.sql` (028 已被 W5-B agent_sessions 占了):
  ```sql
  ALTER TABLE mcp.agent_sessions ADD COLUMN project_dir TEXT;

  CREATE SCHEMA IF NOT EXISTS orch;

  CREATE TABLE orch.paused_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES mcp.agent_sessions(id),
    claude_session_id TEXT NOT NULL,
    paused_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retry_at_hint TEXT,            -- claude stderr 解析到的 "try again at 3pm" 原文
    reason TEXT DEFAULT 'usage_limit'
  );

  CREATE TABLE orch.scheduled_resumes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES mcp.agent_sessions(id),
    scheduled_at TIMESTAMPTZ NOT NULL,
    resume_prompt TEXT NOT NULL DEFAULT '继续',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending / completed / failed
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX idx_sched_resumes_pending ON orch.scheduled_resumes(scheduled_at)
    WHERE status='pending';
  ```

- omni-desktop:
  - `IpcCreateSessionArg` 加 `project_dir?: string`
  - `IPC_CREATE_SESSION` 落库时写 project_dir
  - `IPC_OPEN_SESSION` 从 DB 读 project_dir，传给 `mgr.open()` 作 `cwd`
  - `SessionManager.spawn(id, prompt, allowedTools, cwd?)` 新增 cwd 参数
  - `startClaudeRunner({cwd, ...})` 已支持，不用改

### 切片 2 — main process HTTP/WS server（1 天）

**目的**：让外部（手机浏览器 / APK）能远程调 omni-desktop，不只 Electron IPC。

**改 omni-desktop**：
- npm install `express ws` + types
- 新文件 `src/main/http-server.ts`，main.ts 启动时调 `startHttpServer(7777, token)`
- 路由 1:1 映射现有 IPC handler（共用底层 mgr / pool）：
  - `POST /api/sessions` { title, project_dir, sku_id? }
  - `GET /api/sessions` → list
  - `POST /api/sessions/:id/open` → 拉 history
  - `POST /api/sessions/:id/prompt` { prompt }
  - `POST /api/sessions/:id/cancel`
  - `POST /api/sessions/:id/schedule-resume` { scheduled_at, resume_prompt? }
  - `GET /api/paused-sessions`
  - `GET /api/scheduled-resumes`
  - `WS /ws/events?session_id=...&token=...` → 广播 chunk/task_done/error/usage_limit
- 认证：Bearer token，settings-store 第一次启动 `crypto.randomBytes(32).toString('base64url')`
  自动生成并保存；新加 settings UI 显示 token + 一键复制
- CORS：允许 `*`（个人自用，由 cloudflared 边缘 + token 双保险）

### 切片 3 — Usage Limit 检测 + 续跑 daemon（0.5 天）

**改 claude-runner.ts**：
- stderr 监听里加 regex：
  ```ts
  const USAGE_LIMIT_RE = /Claude AI usage limit reached.*?try again at\s*([\d:]+\s*[APap][Mm]?)/i
  ```
- 匹配到 → emit `'usage_limit'` event with `{retry_at_hint: m[1]}`

**改 ipc-handler.ts**：
- 新 IPC `IPC_SCHEDULE_RESUME` { session_id, scheduled_at, resume_prompt }
  → INSERT orch.scheduled_resumes
- runner 'usage_limit' handler → INSERT orch.paused_sessions + pushToAllRenderers
  `{kind: 'usage_limit', session_id, retry_at_hint}`

**新文件 `src/main/resume-scheduler.ts`**：
- main.ts 启动时调 `startResumeScheduler()`
- setInterval 60s 扫 `orch.scheduled_resumes WHERE scheduled_at <= NOW()
  AND status='pending' LIMIT 5`
- 每条 → 拉 mcp.agent_sessions 拿 claude_session_id + project_dir →
  spawn claude --resume → 标 status='completed'
- 失败标 'failed' 写 last_error，不重试（老板手动再设）

### 切片 4 — 手机端 Web UI（1 天）

**优先级 4A：复用 omni frontend agent-chat（最快）**：
- 在 omni frontend `/orch` 新增路由
- 复用 ChatLayout / MessageStream / InputBar 组件
- 加：
  - 顶部 project_dir 选择器（DataList 历史用过的目录 + 自由输入）
  - session 卡片显示 `project_dir` badge
  - 撞 usage_limit 时 MessageBubble 旁出现 "⏰ 设定时续跑" 按钮 → 弹时间选择器
  - 设置页：填 omni-desktop HTTP server URL + Token
- 改 ws-handler.ts 改为连 omni-desktop HTTP server 的 `WS /ws/events`，**不是
  omni frontend 自己的 /api/agent-chat/ws**

**优先级 4B：Capacitor APK（次要，老板 toolchain 装好再做）**：
- E:\agent\omni-mobile\ 新 repo
- Capacitor + Next.js export OR WebView shell 直接加载 cloudflared URL
- 前置：JDK 17 + Android SDK CLI（winget install，约 2.5GB）
- 实质：APK 95% = PWA + 加主屏，剩 5% = FCM 推送 + 后台保活

**MVP 范围内只做 4A**。4B 等老板装好 toolchain 后另开 plan。

### 切片 5 — 网络层 + 老板手动 SOP（5 分钟）

**老板做**（W6 setup.md 已写大部分）：
1. `winget install cloudflare.cloudflared`
2. `cloudflared tunnel --url http://localhost:7777`（暴露 omni-desktop HTTP server）
   → 拿一个 `https://xxx.trycloudflare.com` URL
3. 同时 `cloudflared tunnel --url http://localhost:80` → 暴露 omni frontend（手机
   PWA 入口）
4. OPPO Chrome 开 `https://<omni-frontend-url>/orch` → 添加到主屏
5. 主屏 PWA 设置页填 omni-desktop URL + token（一次性）→ 完事

**注意：trycloudflare 临时 URL 每次重启变**。要稳定 URL 需要绑老板自己的域名
（CF 一年 $10）。MVP 阶段先临时 URL 凑合。

## 工期 + 老板出差时间窗

| | 工期 | 说明 |
|---|---|---|
| 切片 1 DB + cwd | 0.5 天 | migration 029 + omni-desktop type 改 |
| 切片 2 HTTP/WS server | 1 天 | 新文件 + npm install + 1:1 映射 IPC |
| 切片 3 usage_limit + 续跑 | 0.5 天 | stderr regex + scheduler interval |
| 切片 4A web UI | 1 天 | omni frontend `/orch` 路由 + 项目选择器 + 续跑按钮 |
| 切片 5 网络层（你做） | 5 分钟 | cloudflared 两个 tunnel + 配置 |
| **总计** | **3 天我做 + 5 分钟你做** | 出差 7 天回家前能用上 |

## 出差路上短期凑合方案（今天就能用）

W6 复活了 SSH+Termius 路径（commit 1d371c6 + docs/multi-device/setup.md）：
- OPPO 装 Termius，ssh 进家里 Win
- `cd E:\agent\<任意项目>` + `claude` 直接跑
- 长任务跑完企微推送
- 手机 PWA `/chat` 看 omni 自己的 SKU 数据

这条路 30 分钟装机能用上，是 MVP 没出来前的桥梁。

## 后置 / 不做

- **iOS APK / Capacitor iOS**：等 Android 跑通再说，老板没说要 iOS
- **多用户认证**：个人自用，单 token 够（[[feedback-personal-use-no-overengineering]]）
- **omni 跨项目 MCP server 复用**：每个 cwd 自己 MCP config；MVP 先只 omni 项目挂
  MCP，其他项目用裸 Claude Code（这条要老板出差回来确认是否要扩）
- **FCM 推送**：先用企微推送（W6 已实现），FCM 等 APK 做时再加
- **WebRTC / WebSocket 心跳重连优化**：本 plan 不解决"实时流断"，只解决"任务该跑
  不断"。详情见上文我跟老板对话："通信稳定靠架构不靠协议"

## 落到老板话术 → tool

| 话术 | 处理 |
|---|---|
| "在 X 目录跑 Y" | POST /api/sessions {project_dir: X} → POST /api/sessions/:id/prompt {prompt: Y} |
| "撞 limit 了，3 点继续" | POST /api/sessions/:id/schedule-resume {scheduled_at: '15:00', resume_prompt: '继续'} |
| "看下还有几个任务在挂起" | GET /api/paused-sessions |
| "改成 4 点续跑" | DELETE 老 scheduled_resumes + 新 POST |
