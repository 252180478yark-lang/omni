# omni computer-use: Claude Code 内置 GUI tool (模拟 Codex CLI computer use) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 模拟 **Codex CLI 的 computer use** —— 给 Claude Code（CLI 本身）加一组 GUI tool（截图 / 点击 / 打字 / 按键 / 滚动），让在 CLI 里跑着的 Claude 能像调 Bash 一样直接接管本机屏幕，模拟人类操作**任何 Win 桌面 app**（千牛 / 抖店伴侣 / Win 微信 / Excel）**和任何网页**（在浏览器里看），目标是**获取信息**。**不搞独立 service / HTTP API / iOS Shortcuts**，就是一个 lightweight MCP server 跑老板本机，Claude Code 通过 `claude mcp add` 接入即可。

**Key Insight:** Codex CLI 的 computer use 不是独立的 daemon，是 CLI 内部直接 invoke 的能力。复刻它最干净的路径是**写一个跑在本机的 MCP server，暴露 5-6 个原子 tool 给 Claude Code**，决策权在 Claude（我）这边，不在某个独立 agent loop 里。这样我可以**把 GUI tool 跟其他 tool 混着用**（Read 文件 + screenshot 看 UI + click + Bash 写脚本），跟 Codex 那种"在 chat 里直接控制电脑"的体验一致。

**Architecture:**

```
[Claude Code (CLI session)] —— 你在终端 / omni-desktop 跑的 Claude
        ↓ "调研一下千牛今天的客服消息"
        ↓ Claude (我) 决定调 screenshot
        ↓
[MCP server: mcp-computer-use] —— 本机进程,stdio 通讯
        ↓ pyautogui / mss / pywin32
        ↓
[Win GUI: 千牛 / 浏览器 / 任何 app]
        ↓
[截图 base64 回 Claude] —— 我看完截图决定下一步: 再 screenshot? click? type? extract?
        ↓ 循环到 done
        ↓ 我直接在 chat 里给你 markdown 报告
```

**Tech Stack:**

- Python 3.11 / MCP Python SDK (`mcp` 1.0+) / stdio transport
- pyautogui 0.9.54 (键鼠) / mss 9.0+ (截图,比 pyautogui 快 4x) / Pillow 11+ (图像处理) / pywin32 (Win 专属:进程/窗口/UAC)
- 老板已经在 KE 配的 ai-provider-hub Anthropic 通道仅用于 vision (Claude Sonnet 4.6 看截图)；这个 MCP server 本身不调 LLM,LLM 决策在 Claude Code 这边自然发生

---

## 关键决策（10 个开放问题 reasonable call）

| # | 问题 | 决策 | 理由 |
|---|---|---|---|
| 1 | 内核形态: 独立 daemon / MCP server / Claude Code 插件 | **MCP server (stdio)** | 模拟 Codex CLI 体验; Claude Code 已支持 MCP,无需改 CLI 本身 |
| 2 | Tool 粒度: 高阶 (`browse(goal)`) / 原子 (`click,type,screenshot`) | **原子 5 个 tool** | Codex 风格,决策权交回 Claude; 我能跟 Read/Bash 混用; 高阶 tool 后续 W7 再加 |
| 3 | 实现语言 | Python (MCP server) | pyautogui / mss / pywin32 生态在 Python 最成熟; Node 也有但稳定性差 |
| 4 | 截图传输: base64 inline / 文件路径 / hybrid | **base64 inline (压缩 PNG)** | MCP 多模态原生支持,我直接看到; 单张缩放后约 100-300 KB; 不依赖文件系统 |
| 5 | 决策模型 | **Claude Sonnet 4.6 / Opus 4.7** (老板的 Claude Code 当前) | 由 Claude Code 自己跑,MCP server 不挑模型 |
| 6 | 写操作 (click 发送 / 提交 / 删除) | **不做硬黑名单**,改"Claude 自我审查"prompt 注入 + dangerous_action confirm prompt 在 MCP server 内层 | 老板要 read 主用例; 真要写操作时 Claude 自己会犹豫并问老板 |
| 7 | 多屏 / DPI 缩放 | mss 自动检测主屏 + screenshot tool 参数 `monitor=1` 默认 + 截图时已经按屏物理像素 | 老板 Win 11 多屏 + 高 DPI 是已知坑,mss 处理 |
| 8 | 跨平台 | Win 优先 (老板主用); Mac fallback 用 `pyobjc` + Quartz 截图,后续支持 | 切片 1-3 先 Win,Mac 留 W6 切片 4 |
| 9 | 失败兜底 (UAC 弹窗 / 找不到 app) | tool 返 `{"status":"blocked","reason":"UAC elevation required"}`,Claude 自然停下来问老板 | 不让 MCP server 自动提权 (安全) |
| 10 | 老板手机端能不能用 | **不能,这版只支持 PC Claude Code** | 老板要手机用属于 W7 (单独搭 HTTP gateway + Tailscale,复杂度高); 先把 PC 跑通验证价值 |

---

## File Structure

```
services/mcp-computer-use/                  # 新独立 mini-project,不进 docker
├── pyproject.toml                          # uv / poetry 都行
├── README.md
├── server.py                               # MCP server 主入口 (stdio)
├── tools/
│   ├── __init__.py
│   ├── screenshot.py                       # screenshot(monitor=1, region=None) → base64 PNG
│   ├── click.py                            # click(x, y, button='left', clicks=1) / click_text(text) (用 OCR)
│   ├── type.py                             # type_text(text, interval=0.01) 支持中文 (pyautogui+pyperclip 兜底)
│   ├── key.py                              # key_press(key) / hotkey('ctrl','s') / key_down/up
│   └── scroll.py                           # scroll(direction='down', amount=3) / drag(x1,y1,x2,y2)
├── win_adapter/
│   ├── __init__.py
│   ├── window.py                           # find_window(title) / focus_window / list_windows
│   ├── process.py                          # launch_app(path) / kill_process / list_processes
│   └── uac.py                              # is_uac_elevated() / detect_admin_window
├── safety.py                               # 在 MCP server 内层做基础 sanity check (坐标越界 / 坐标在 Win 任务栏关机区 等)
├── config.py
└── tests/
    ├── test_screenshot.py
    ├── test_click.py
    ├── test_type_chinese.py
    └── test_e2e_notepad.py                 # 跑通 "打开记事本,输 hello world,Ctrl+S 保存"

# 老板装机 (在 Claude Code 里挂载这个 MCP):
~/.claude/mcp.json                          # 或老板自定义路径
{
  "mcpServers": {
    "computer-use": {
      "command": "uv",
      "args": ["run", "--directory", "E:/agent/omni/services/mcp-computer-use", "python", "server.py"]
    }
  }
}

docs/computer-use/
├── architecture.md                         # MCP server 架构 + tool 调用流
├── prompt-tips.md                          # Claude (我) 用这套 tool 的 best practice (先 list_windows 找 focus / 截图前 wait 1s 等动画 / OCR click_text 比 click(x,y) 鲁棒)
├── safety.md                               # 写操作 / UAC / 屏幕越界保护
└── win-setup.md                            # 老板 Win 主机环境准备 (Python + uv + pyautogui 权限)
```

---

## 切片清单（3 切片 / 估计 1-1.5 天工期）

### 切片 1：MCP server 骨架 + 5 个原子 tool + Win 适配（半天）

**Goal:** MCP server 跑起来,Claude Code 能通过 `claude mcp` 调到 5 个 tool,跑通 "打开记事本输入 hello world 截图保存" 端到端 demo。

- [ ] 1.1 新建 `services/mcp-computer-use/` + pyproject.toml (依赖 mcp/pyautogui/mss/pillow/pyperclip/pywin32)
- [ ] 1.2 写 `server.py`: MCP stdio server + 注册 5 个 tool (screenshot/click/type_text/key_press/scroll)
- [ ] 1.3 写 `tools/screenshot.py`: mss 截图主屏 + 压缩 PNG (quality 85) + base64 编码; 参数 `monitor` (默认 1) / `region=(x,y,w,h)` / `max_dim=1280` (按比例缩); 返 `ImageContent`
- [ ] 1.4 写 `tools/click.py`: pyautogui.click(x,y,button,clicks); 加 `click_text(text)` 用 pytesseract OCR 找文本坐标点击 (更鲁棒,适合 Claude 看截图后说"点'选品'两个字")
- [ ] 1.5 写 `tools/type.py`: pyautogui.write 默认; 中文用 pyperclip.copy + pyautogui.hotkey('ctrl','v') 兜底 (pyautogui 不支持非 ASCII 直接输入)
- [ ] 1.6 写 `tools/key.py` + `tools/scroll.py`: hotkey / key_press / scroll 直接 pyautogui 封装
- [ ] 1.7 写 `win_adapter/window.py` + `process.py`: list_windows() 返所有可见窗口 (title + hwnd + 进程名); launch_app(path 或 .lnk 路径); focus_window(title 精确或 fuzzy)
- [ ] 1.8 加 `safety.py` 基础 sanity: 坐标越界 reject + 任务栏关机区 (右下 100x40) reject + UAC 检测时拒绝
- [ ] 1.9 老板装 `~/.claude/mcp.json` 配置 + 重启 Claude Code + `claude mcp list` 看到 `computer-use`
- [ ] 1.10 端到端测试: 在 Claude Code 里跟我说 "打开记事本,输 hello world,Ctrl+S 保存到桌面 hello.txt",看我能不能用 5 个 tool 完成 (期望 5-8 个 tool call 完成)

**验收:** Claude Code 里我能用 screenshot+click+type+key 完成"记事本写文件并保存"任务,全过程截图清晰,中文输入 OK

---

### 切片 2：真实任务验证 (千牛 / 罗盘 / 抖店) + 文档（半天）

**Goal:** 用切片 1 的能力跑 3 个真实任务,沉淀 best practice 写进 prompt-tips.md，CLAUDE.md 加入。

- [ ] 2.1 任务 A: 老板 Claude Code 里跟我说 "去千牛 PC 客户端,看今天有几条未读客服消息,截图给我列表" → 我用 list_windows 找千牛 → focus → screenshot → click_text "客服" 进 tab → screenshot → 解析数字
- [ ] 2.2 任务 B: "打开 Chrome → 罗盘 → 看今日 GMV 数字" → launch_app("chrome") → type URL → screenshot → 解析数字 (复用 scout-agent cookie 不在这切片做,这步靠老板已登录的浏览器 session)
- [ ] 2.3 任务 C: "去抖店后台 → 选品广场 → 列出前 10 个热销品名" → 类似 B + scroll + extract
- [ ] 2.4 写 `docs/computer-use/prompt-tips.md`: 我用这套 tool 时的 best practice (e.g. 截图前 sleep 1s 等动画 / click_text 比 click(x,y) 鲁棒 / 找窗口先 list_windows 别瞎截 / 截 region 而不是全屏省 token)
- [ ] 2.5 写 `docs/computer-use/architecture.md` + `safety.md` + `win-setup.md`
- [ ] 2.6 CLAUDE.md 加一节 "## omni computer-use (W6 切片 1) — Claude Code 内置 GUI tool":
    - 5 个 tool 用法
    - 老板触发话术 (e.g. "去千牛看 X" / "调研罗盘 Y")
    - 安全约束 (写操作要犹豫 + 二次问老板)
    - 跟 scout-agent 区别 (scout 是 Playwright 自动化 runbook 周期跑,本套是老板 ad-hoc 让我现场跑)
- [ ] 2.7 在 omni MCP server 计数里写明这是**外部 MCP 不进 KE 内的 46 tool 计数**,但老板 Claude Code 用时跟 KE tool 同等待遇

**验收:** 3 个真实任务全跑通 (我能完成 + 报告给老板) + 文档进 git + CLAUDE.md 已更新

---

### 切片 3：写操作安全 + Mac fallback (后置,看老板反馈再做)

**Goal:** 切片 1-2 验证完老板真用且喜欢之后再做。

- [ ] 3.1 写操作 confirm prompt: 在 click/type/key tool 里加 LLM 自检 hint "你这步是 write 操作吗? 如是,先问老板再 tool call"
- [ ] 3.2 Mac fallback: `mac_adapter/` (pyobjc + Quartz 截图 + AppleScript 焦点); 切片 1 所有 tool 加 Mac branch
- [ ] 3.3 Mac e2e: 任务 A (千牛 Mac 版) + 任务 B (Mac Chrome + 罗盘)
- [ ] 3.4 高阶 tool `browse(goal, max_steps=30)` 包装切片 1 5 个 tool 进一个 agent loop (跟 plan v1 原方案靠拢; 老板想"一句话扔 + 跑完通知" 时用)
- [ ] 3.5 HTTP gateway + Tailscale + 手机端触发 (从 plan v1 拿)

**Out of scope (W7+):** 上述切片 3 全部

---

## 风险 + 已知坑

| 风险 | 缓解 |
|---|---|
| 多屏 + 高 DPI 坐标偏 | mss 自动检测物理像素 + screenshot 返尺寸标注 + click 用绝对像素 (Claude 看截图能算对) |
| UAC 弹窗 / 管理员窗口 pyautogui 无效 | win_adapter/uac.py 检测 → tool 返 blocked, Claude 报告老板 |
| 千牛 / 罗盘有反自动化检测 | pyautogui 是真用户输入级别 OS API, 检测不到 (跟 Playwright 反自动化 flag 不一样) |
| 中文输入 pyautogui.write 不支持 | type_text 内部用 pyperclip.copy + Ctrl+V 兜底中文 |
| 截图 token 消耗 | 默认 max_dim=1280 缩放 + PNG 压缩 quality=85,单张 100-300KB; Claude 看完即丢 (不存 conversation history 全量) |
| Claude 误点 write 按钮 | 切片 3 加 LLM 自检 prompt; 切片 1-2 主要是 read 任务,老板自己审 tool 调用 |
| Win 任务栏 / 锁屏覆盖 | safety.py 拦右下角关机区; 锁屏状态截图返黑屏老板能看出 |
| 多 monitor 老板想要看副屏 | screenshot 参数 `monitor=2` 老板说哪屏我截哪屏 |
| MCP server 异常崩溃 Claude Code 卡死 | tool 内异常包装成 error result 不抛; server 单进程重启快 |

---

## 跟现有 omni 体系对接

✅ **复用 (轻):**
- 老板 ai-provider-hub Anthropic 通道 (Claude Sonnet/Opus 模型) — 自然复用 (Claude Code 本来就在调)
- omni 的反 AI 化套话 / 反幻觉 / 说人话 约束 — 通过 CLAUDE.md 注入

❌ **新增 (轻):**
- `services/mcp-computer-use/` 新 mini-project (不进 docker, host 跑)
- 老板 `~/.claude/mcp.json` 加 1 行配置
- 3 个 docs

**不动:**
- KE 46 tool 不动
- scout-agent 不动 (它跟本套互补: scout 周期自动化 / 本套老板 ad-hoc)
- omni-desktop 不动 (omni-desktop 是 web/desktop UI,本套是给 Claude Code CLI 加 tool)

---

## 老板真实使用流 (切片 1-2 完成后)

```
老板 cd 任意目录 → claude → 跟我说话:

老板: "去千牛看今天的客服消息,有几条未回的,主题是啥"

我 (Claude Code 里): 
  → 调 list_windows() 看千牛在没在跑
  → 没跑 → launch_app("C:/Program Files/AliWangwang/qianniu.exe")
  → 截图 → 我看到千牛主界面 (描述: "顶部 4 个 tab,'消息'tab 有红点 '3'")
  → click_text("消息") → 截图 → 看到对话列表
  → 解析每个未读对话主题 + 时间 → 报告给老板:
    "你今天千牛有 3 条未回客服:
    1. 14:32 用户'小明': '请问这款酱油保质期多久?'
    2. 15:15 用户'美食爱好者': '可以现货吗?'
    3. 16:48 用户'妈妈帮帮我': '我下错单了能退吗?'
    
    建议优先回 #3 (有损失风险)。要不要我帮你回复? (写操作要你批)"

老板: "回 #3 说可以,我已经在抖店后台改了"
  → 我犹豫 (写操作) → 反问老板确认一次 → 老板 OK → click conversation #3 → type 回复内容 → click 发送
```

---

## 启动指引（老板回来后）

1. 读本文档
2. `cd services/ && mkdir mcp-computer-use && cd mcp-computer-use`
3. `uv init && uv add mcp pyautogui mss pillow pyperclip pywin32 pytesseract`
4. 按切片 1 顺序写代码,每子步骤一个 commit
5. 在 Claude Code 里测 `claude mcp add computer-use ...` + 跟我说"打开记事本测试" 验证切片 1
6. 跑切片 2 三个真实任务,有问题反馈
7. 切片 3 等切片 1-2 验证完老板真喜欢用再做

**总工期: 1-1.5 天** (相比 v1 plan 的 2-3 天,因为砍掉了 HTTP API + Tailscale + iOS Shortcuts + 独立 service 那些)

---

## 对比 v1 plan (已被本文档覆盖)

| 项 | v1 plan (废弃) | v2 plan (本文档) |
|---|---|---|
| 形态 | 独立 service (services/computer-use-agent) + HTTP API + Tailscale + iOS Shortcuts | 单一 MCP server (services/mcp-computer-use) 跑本机, Claude Code 直接调 |
| Tool 粒度 | 高阶 `browse(goal)` 内含 agent loop | 原子 `screenshot/click/type/key/scroll` |
| 决策权 | 独立 agent loop (在 service 内) | Claude Code 里的 Claude (我) |
| 触发方式 | iOS Shortcuts / HTTP / Telegram | Claude Code 对话 |
| 复杂度 | 5 切片 / 2-3 天 | 3 切片 / 1-1.5 天 (切片 3 后置) |
| 老板手机用 | 支持 (Tailscale + iOS Shortcuts) | 不支持 (PC 端 Claude Code only) — 后置切片 3.5 |
| 像谁 | 没有合适对标 | **Codex CLI computer use** |

v1 的高阶 `browse(goal)` agent loop 不是错,但**先做 v2 (codex 风格原子 tool) 验证价值**,老板真的用爽了再考虑要不要包一层高阶 agent loop。
