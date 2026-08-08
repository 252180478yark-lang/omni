# Host Bridge 本地运行与多入口接入

Host Bridge 是宿主能力边界，不承载业务页面。Next Web 仍是唯一业务 UI；Host 只负责 provider-neutral 会话、Codex/Claude runner、本地附件、可见登录/扫码和取消/续跑。

## 安全边界

- 默认只监听 `127.0.0.1:7777`，仅供同机 Web BFF 使用；不设置账号、密码或内部 Bearer 令牌。
- `project_dir` 必须位于 `OMNI_HOST_ALLOWED_PROJECT_ROOTS` 中且包含 `AGENTS.md`。runner 使用参数数组和固定 cwd，不通过 shell。
- 可见登录只接受 `OMNI_HOST_VISIBLE_AUTH_ORIGINS` 中精确配置的 HTTPS origin。请求 URL 不进入响应、持久化或 trace；相同 `request_id` 不会重复打开浏览器。
- 第二个 Host 实例遇到现存 singleton lease 会返回阻断；它不会杀死或替换已有实例。
- Host 离线或 build/worktree/allocation 不一致时，Web health 返回 `unavailable` 或 `stale`，不会显示成功。

## 启动

显式配置允许访问的项目根和 CLI 可执行文件路径，然后在 PowerShell 中设置：

```powershell
$env:OMNI_HOST_ALLOWED_PROJECT_ROOTS = 'E:\agent'
$env:OMNI_HOST_EXECUTION_ENABLED = 'true'
$env:OMNI_HOST_VISIBLE_AUTH_ORIGINS = 'https://login.example.com,https://open.example.com'
$env:CODEX_CLI_PATH = 'C:\path\to\codex.exe'
$env:OMNI_KE_URL = 'http://127.0.0.1:8002'
./services/host-bridge/run.ps1
```

Host Bridge、Web 和 Knowledge Engine 通过本机回环地址通信，不再生成或转发内部认证令牌。默认 `OMNI_AGENT_RUNNER_MODE=auto`：只在 run 请求发出前确认 Host 不可用时回退本地 runner；run 提交一旦开始，响应丢失也不会冒险双执行。`host` 禁止回退，`local` 只作为显式兼容/回滚模式。

## Web 与企业微信

Web 的 Agent Session Manager 调用 `/api/v1/host-bridge/sessions` 和游标 run event API；附件通过 `/api/omni/host-bridge/sessions/.../attachments` 上传、下载。可见登录通过 `/api/omni/host-bridge/sessions/{session_id}/visible-auth` 请求 Host 打开已列入白名单的 provider 登录页。浏览器不需要 Omni 身份会话；草稿、上传、可见登录等写操作仍要求同源请求。

现有企业微信编排调用形状由 `/api/sessions`、`/open`、`/prompt` 兼容。兼容层只委托统一 session/run 内核，不创建 placeholder runner ID；首次真实 provider ID 会持久化。

## 恢复与回退

停止 Host 后 lease 正常释放；session 元数据和按 SHA-256 存放的附件保留在仓库外 `OMNI_HOST_STATE_DIR`。如 Host 不可用，把 Web 的 `OMNI_AGENT_RUNNER_MODE` 改回 `local` 即可回退，Electron 不需要移除。
