# Host Bridge 本地运行与多入口接入

Host Bridge 是宿主能力边界，不承载业务页面。Next Web 仍是唯一业务 UI；Host 只负责 provider-neutral 会话、Codex/Claude runner、本地附件、可见登录/扫码和取消/续跑。

## 安全边界

- 默认只监听 `127.0.0.1:7777`，所有会话、run、附件及企业微信兼容接口都必须使用同一 Bearer 服务身份。
- `OMNI_HOST_TOKEN_FILE` 只接受仓库外文件路径；令牌不进入 `.env`、日志、数据库或 API 响应。
- `project_dir` 必须位于 `OMNI_HOST_ALLOWED_PROJECT_ROOTS` 中且包含 `AGENTS.md`。runner 使用参数数组和固定 cwd，不通过 shell。
- 可见登录只接受 `OMNI_HOST_VISIBLE_AUTH_ORIGINS` 中精确配置的 HTTPS origin。请求 URL 不进入响应、持久化或 trace；相同 `request_id` 不会重复打开浏览器。
- 第二个 Host 实例遇到现存 singleton lease 会返回阻断；它不会杀死或替换已有实例。
- Host 离线或 build/worktree/allocation 不一致时，Web health 返回 `unavailable` 或 `stale`，不会显示成功。

## 启动

先在仓库外创建至少 24 字符的随机 token 文件，并显式配置 CLI 的可执行文件路径。然后在 PowerShell 中设置：

```powershell
$env:OMNI_HOST_TOKEN_FILE = 'C:\path\outside-repo\host.token'
$env:OMNI_HOST_ALLOWED_PROJECT_ROOTS = 'E:\agent'
$env:OMNI_HOST_EXECUTION_ENABLED = 'true'
$env:OMNI_HOST_VISIBLE_AUTH_ORIGINS = 'https://login.example.com,https://open.example.com'
$env:CODEX_CLI_PATH = 'C:\path\to\codex.exe'
$env:OMNI_KE_URL = 'http://127.0.0.1:8002'
$env:OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE = 'C:\path\outside-repo\runtime-trace.token'
./services/host-bridge/run.ps1
```

Knowledge Engine 使用 `OMNI_RUNTIME_TRACE_TOKEN_FILE` 验证 trace/Agent 合同请求；Web 与 Host 使用 `OMNI_RUNTIME_TRACE_SERVICE_TOKEN_FILE` 读取同一个仓库外 token 文件。Web 服务同时使用相同的 `OMNI_HOST_TOKEN_FILE`。默认 `OMNI_AGENT_RUNNER_MODE=auto`：只在 run 请求发出前确认 Host 不可用时回退本地 runner；run 提交一旦开始，响应丢失也不会冒险双执行。`host` 禁止回退，`local` 只作为显式兼容/回滚模式。

## Web 与企业微信

Web 的 Agent Session Manager 调用 `/api/v1/host-bridge/sessions` 和游标 run event API；附件通过 `/api/omni/host-bridge/sessions/.../attachments` 上传、下载。可见登录通过 `/api/omni/host-bridge/sessions/{session_id}/visible-auth` 请求 Host 打开已列入白名单的 provider 登录页。浏览器必须先建立有效的 Omni 身份会话；运行 trace、事实图、计划草稿、附件和可见登录 BFF 不接受匿名请求，草稿/上传/可见登录还要求同源请求。

现有企业微信编排调用形状由 `/api/sessions`、`/open`、`/prompt` 兼容，但必须附加相同 Bearer 服务身份。兼容层只委托统一 session/run 内核，不创建 placeholder runner ID；首次真实 provider ID 会持久化。

## 恢复与回退

停止 Host 后 lease 正常释放；session 元数据和按 SHA-256 存放的附件保留在仓库外 `OMNI_HOST_STATE_DIR`。如 Host 不可用，把 Web 的 `OMNI_AGENT_RUNNER_MODE` 改回 `local` 即可回退，Electron 不需要移除。
