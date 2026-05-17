# omni 三端协同 (W6 multi-device) — 装机指南

> 2026-05-17 落地: PWA + 移动端响应式 + 企业微信推送通道 + Tailscale 网络层

## 你装完后的体验

- **Win 主机 (家)**: omni-desktop 直接打开 / 浏览器 `localhost/chat` / Claude Code CLI
- **Mac (出差)**: omni-desktop Mac 版 (npm run pack:mac 出 DMG) + Claude Code CLI / Mac 浏览器开 `http://<win-tailnet-ip>/chat`
- **OPPO Find N6**: Chrome 开 `http://<win-tailnet-ip>/chat` → "添加到主屏" 后像 app 一样用; 长任务跑完企业微信收到推送

## 架构图

```
[OPPO / Mac (外面)] ←─ Tailscale 加密 P2P ─→ [Win 主机 (家, 24h 不关)]
                                                     │
                                                     ├── nginx :80 (0.0.0.0 暴露)
                                                     │   └── /chat → frontend:3000 (Next.js)
                                                     │       └── ws → claude code subprocess
                                                     │           └── 任务完成时 fetch
                                                     │               KE:/api/v1/notify/task-done
                                                     │               → 企微 webhook → 你手机
                                                     │
                                                     └── KE / Hub / Scout (内部 127.0.0.1)
```

## 一次性装机 (Win 主机)

### 1. Tailscale (5 分钟,关键)

1. 下载 https://tailscale.com/download/windows 装到 Win
2. 启动 → 用 Google/Microsoft/邮箱 登录 (免费版 3 设备够用)
3. 系统托盘 Tailscale 图标 → 看到一个 100.x.x.x 的 IP — 这就是 Win 主机的 tailnet IP, **记下来**

### 2. 后端绑 0.0.0.0 (已做)

`docker-compose.yml` 里 nginx 端口绑定已改为 `${NGINX_PORT:-80}:80` (不带 127.0.0.1),`docker compose up -d nginx` 重启即可。

验证: 在 Win 上 `curl http://localhost/health` 应该返 `ok`。

### 3. (可选) OpenSSH server — 想 SSH 进 Win 跑 Claude Code 时用

PowerShell as Admin 一行命令:

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0; Set-Service sshd -StartupType Automatic; Start-Service sshd; New-NetFirewallRule -Name OpenSSH-Server-In-TCP -DisplayName 'OpenSSH SSH Server' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```

之后 Mac/OPPO Termius 可以 `ssh <你的-Win-用户名>@<win-tailnet-ip>` 进来跑 Claude Code。

### 4. 企业微信 webhook (5 分钟,出差关键)

让长任务跑完手机收到推送:

1. 用企业微信开个群 (自己一人也行)
2. 群设置 → 群机器人 → 添加 → 复制 webhook URL (形如 `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx`)
3. 编辑 `services/knowledge-engine/.env`,加一行:
   ```
   WECOM_WEBHOOKS=task_done=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key
   ```
4. 重启 KE: `docker restart omni-knowledge-engine`
5. 验证: `curl http://localhost:8002/api/v1/notify/health` 应返 `channels_configured:["task_done"]`

⚠️ 没配也不报错 — 长任务完成时 ws-handler fetch endpoint, KE 返 `skipped:true`,业务流程不受影响。

## 一次性装机 (Mac)

### 1. Tailscale

`brew install --cask tailscale` → 启动 → 同一个账号登录

### 2. Claude Code CLI

```bash
npm install -g @anthropic-ai/claude-code
claude login  # 用 Max 订阅登
```

### 3. omni-desktop Mac 版 (出差时用)

```bash
cd ~/agent/omni-desktop
npm install
npm run pack:mac
# 输出 release/0.1.0/omni-0.1.0.dmg → 拖到 Applications
# 第一次打开右键 → 打开 → 仍要打开 (绕未签名警告)
```

omni-desktop 启动后,settings 把"后端 URL"配成 `http://<win-tailnet-ip>` (你 Win Tailscale IP)。

### 4. 浏览器开 web 版 (备选)

任何 Mac 浏览器开 `http://<win-tailnet-ip>/chat`,跟 omni-desktop 同一份 UI。

## 一次性装机 (OPPO Find N6)

### 1. Tailscale Android

Play Store / 国内应用商店搜 "Tailscale" → 装 → 同一账号登录

### 2. 添加 omni 到主屏 (PWA)

1. Chrome 开 `http://<win-tailnet-ip>/chat`
2. 浏览器菜单 → "添加到主屏幕" → 名字填 "omni" → 确认
3. 桌面会出现一个 omni 几何 logo 图标
4. 点图标 → 全屏打开,像原生 app

支持的 PWA 特性:
- 全屏 (无浏览器地址栏)
- 启动屏幕用 omni logo
- 长按图标弹"新对话"快捷方式
- safe-area 适配 OPPO 全面屏 home indicator

### 3. 移动端用法

- 顶部 hamburger 按钮 → 打开会话列表抽屉
- 输入框底部 sticky,自适应 safe-area
- 长任务完成后企业微信 push (前提你配了 WECOM_WEBHOOKS)

## 日常使用流

### 出差路上 (Mac + OPPO 都在外面)

1. **OPPO 上想到啥任务**: 打开主屏 omni 图标 → 输入 "调研一下 SKU-376253 卖得咋样" → 发送 → 关掉屏幕
2. **任务跑 5-10 分钟** (Claude Code 在 Win 主机 omni-frontend 容器里跑)
3. **手机企业微信收到推送**: "✅ omni 任务完成 / 用时 8m 12s / 花费 $0.18"
4. **重新打开 omni 主屏图标** → 看完整对话流 + 工具调用细节
5. 或 **Mac 上同一对话接续**: 用 omni-desktop 打开,sessions 列表里能看到刚才那次 (postgres 已经存 `mcp.agent_sessions`)

### 在家 (Win 主机直连)

- 直接 omni-desktop Win 版
- 或 Win Chrome 开 `localhost/chat`

## 故障排查

| 症状 | 原因 + 修复 |
|---|---|
| OPPO 打不开 `http://<tailnet-ip>/chat` | Tailscale 没连上或者 nginx 没起; 验证 Win 上 `docker ps` 看 omni-nginx; 看 Tailscale 托盘是否 "Connected" |
| 长任务完成没推送 | `curl http://localhost:8002/api/v1/notify/health` 看 channels_configured 是不是 ["task_done"]; 不是就回去配 WECOM_WEBHOOKS |
| "添加到主屏" Chrome 没弹选项 | 需要 HTTPS 或者 localhost; 用 tailnet IP HTTP 时 Chrome 有时不允许 PWA 安装。fallback: 长按图标→"添加到主屏"也能用 |
| omni-desktop Mac 版第一次打开报"未签名" | 右键 → 打开 → 仍要打开 (绕苹果 Gatekeeper) |
| 手机推送内容乱码 | 企微 webhook 默认 text 格式; 检查 .env 里 WECOM_WEBHOOKS 等号两边没空格 |

## 安全建议

- **Tailscale 是 P2P + 端到端加密**,流量不走公网,只在你的 tailnet 内
- nginx 绑 0.0.0.0 暴露 80 端口给所有网络接口 — 在家庭 LAN/办公室 LAN 别人也能访问。如要严格隔离: 加 Win 防火墙规则限制 80 端口只允许 Tailscale 子网 (100.64.0.0/10):
  ```powershell
  New-NetFirewallRule -DisplayName "omni nginx (Tailscale only)" -Direction Inbound -Protocol TCP -LocalPort 80 -RemoteAddress 100.64.0.0/10 -Action Allow
  ```
- omni 后端没做认证 (个人自用) — 别把 tailnet IP/账号外泄

## 下一步 (W7+ 路线)

- 高级版 Telegram bot / iOS Shortcuts 触发 (跨"非 omni"项目 — 见 plan `2026-05-17-claude-orchestrator-plan.md`)
- omni computer-use MCP server (Claude Code 内置 GUI 操作 — 见 plan `2026-05-17-omni-computer-use-plan.md`)
- /chat 移动端语音输入 (Web Speech API)
- 任务历史按设备分类 (Win/Mac/手机 哪个端发的)
