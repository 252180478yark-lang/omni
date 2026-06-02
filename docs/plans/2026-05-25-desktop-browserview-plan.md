# Desktop BrowserView 整合工作台 — 一个 app 看完所有 omni 资产

> 2026-05-25 老板拍板路径 C（不是 B 外链浏览器,也不是 A 不整合）
> 取代 sidebar 外链方案,把 omni frontend 35 个工作台页面拉进 omni-desktop

## 一句话目标

omni-desktop 桌面端用 Electron BrowserView 嵌入 omni frontend 的 35 个工作台
页面,左侧固定 agent 对话(现有 ChatLayout 不动),右侧 tab 区按需打开任意
omni 工作台页(知识库 / 内容工坊 / SKU pipeline / 投放复盘 等),老板**一个
app 看完所有东西**,不用在浏览器跟桌面端之间来回切。

## 背景 + 设计哲学

omni-desktop 0.1.0 现在是个纯 agent 对话 app(Sidebar + WelcomeScreen +
MessageStream + InputBar 占满整个 BrowserWindow)。omni frontend 那 35 个
Next.js 页面只能在浏览器开 localhost:3000 看,跟桌面端 agent 对话物理隔离。

老板的真实工作流是 "agent 对话改东西 → 立刻切到 /content-studio 看效果 →
再回 agent 改一版"。来回 alt-tab 切窗口噪音大,放一个屏幕里左右看才顺手。

### 布局 C-a 左右并列(最终方案)

```
┌──────────────────────────────────────────────────────────┐
│ [Agent] [知识库] [工坊] [SKU pipe] [复盘] [+ 新 tab]    │ ← TabBar
├──────────────┬───────────────────────────────────────────┤
│              │                                           │
│  Agent 对话  │  active tab 的 BrowserView                │
│  (左侧固定)  │  (加载 http://localhost:3000/<path>)      │
│              │                                           │
│  ChatLayout  │                                           │
│  Sidebar +   │  随 tab 切换实例,关闭即销毁              │
│  Message     │                                           │
│  Stream +    │                                           │
│  InputBar    │                                           │
│              │                                           │
│  480px 宽    │  flex-1                                   │
│  可拖动      │                                           │
│              │                                           │
└──────────────┴───────────────────────────────────────────┘
```

- 左侧 agent 对话宽度默认 480px,中缝可拖 360-720px
- 右侧 TabBar + BrowserView area,无 tab 时整个右侧 collapse,agent 对话占满
  全宽(向后兼容现有 0.1.0 UI,老板不开 tab 时跟之前一样)
- BrowserView 是 Electron 内置 API,**不是 iframe**,所以不受 X-Frame-Options
  限制,加载性能跟独立 Chrome 标签一样
- 设计哲学:**一个 app 看完所有 omni 资产** —— agent 在左实时对话,数据/工坊
  在右实时看,不用脑子记当前在哪个窗口

## 9 个预设 tab

按老板使用频率排序,sidebar 工作台区直接出 9 个固定快捷:

| # | label | path | icon | 说明 |
|---|---|---|---|---|
| 1 | 知识库 | `/knowledge` | book | 翻 KB / role 管理 / 上传文档 |
| 2 | 内容工坊 | `/content-studio` | wand | 单点生成图/视频/文案 |
| 3 | SKU pipeline | `/sku-pipeline` | flow | 5 步全链路出片 |
| 4 | SKU 列表 | `/products` | box | 重点池管理 + 状态查看 |
| 5 | 投放复盘 | `/ad-review` | bar | ad_metrics + 视频血缘反查 |
| 6 | cost 管理 | `/cost` | yuan | 成本录入 + 真实/员工双版 |
| 7 | agent-log | `/agent-log` | history | mcp.tool_calls 审计 |
| 8 | scout 任务 | `/scout` | radar | 罗盘/抖店/云图 runbook |
| 9 | decisions | `/decisions` | check | 保存的决策 + observation |

老板可点 "+ 新 tab" 输入任意 omni frontend 路径(如 `/playground` /
`/some-debug-page`)自定义打开,label 默认取 path 末段。

### tab 持久化

关 omni-desktop 时把当前打开的 tab list(id / path / label / icon / 顺序)
+ active tab id 写入 `settings.openTabs` / `settings.activeTabId`。下次开
app restore,老板上次的工作上下文不丢。

## 5 切片拆分

### 切片 1 — main process BrowserViewManager + IPC + 持久化骨架(1 天)

**目的**:main process 持有所有 BrowserView 实例,renderer 通过 IPC 远程管理。

**新文件**:
- `src/main/browser-view-manager.ts`
  - class `BrowserViewManager` 持 `Map<tabId, BrowserView>`
  - 方法 `createTab(path)` / `activateTab(tabId)` / `closeTab(tabId)` /
    `resizeActive(bounds)` / `reloadTab(tabId)` / `pingFrontend()`
  - 用 `contentView.addChildView(view)` (Electron 33 新 API),fallback
    `mainWindow.setBrowserView` 兼容
- `src/main/tab-store.ts`
  - 读写 `settings.openTabs` / `settings.activeTabId`(沿用现有 settings-store)
  - `loadOpenTabs()` / `saveOpenTabs(tabs)` / `getActiveTabId()` /
    `setActiveTabId(id)`

**修改**:
- `src/main/ipc-handler.ts` 加 5 个 channel:
  - `IPC_TAB_CREATE` { path, label?, icon? } → 返 `{ tabId }`
  - `IPC_TAB_ACTIVATE` { tabId }
  - `IPC_TAB_CLOSE` { tabId }
  - `IPC_TAB_LIST` → 返当前持久化的 tab list
  - `IPC_TAB_RESIZE` { bounds: {x,y,width,height} }
- `src/main/main.ts` 启动期 `new BrowserViewManager(mainWindow)` 挂 module-level
- settings schema 加 `openTabs: TabState[]` / `activeTabId: string | null`

**验证**:
- DevTools console 调 `electronAPI.tabCreate({path: '/knowledge'})` 能开
  BrowserView 显示 omni frontend 知识库页
- `tabActivate({tabId})` 切换正常
- 关 app 重开,`tabList()` 返上次的 tab 数据(此时还没 UI,先验 IPC 通路)

### 切片 2 — renderer TabBar + sidebar 工作台区 + ChatLayout 左右分栏(1.5 天)

**目的**:把 main process 的 tab 能力暴露给 renderer UI。

**修改**:
- `src/renderer/components/AppShell.tsx`(新):
  - flex row container,左 `<ChatLayout className="w-[480px]" />` 右 `<WorkbenchPane />`
  - 中缝 `<Divider onDrag={..}>` 改 agent 区宽度,settings 持久化
- `src/renderer/components/WorkbenchPane.tsx`(新):
  - 顶部 `<TabBar tabs={...} activeId={...} onSelect onClose onAddNew />`
  - 主体一个空 div(让出位置给 BrowserView,main process 把 BrowserView 摆这)
  - 用 ResizeObserver 监听 div bounds,变化时 `electronAPI.tabResize(bounds)`
- `src/renderer/components/TabBar.tsx`(新):
  - chrome-like 横向 tab,关闭按钮 hover 出
  - "+ 新 tab" 按钮点 → 弹 modal 输入 path / label
- `src/renderer/components/ChatLayout.tsx`:
  - sidebar 新增"工作台"区块,9 个预设按钮点开对应 tab(active 状态高亮)
  - "工作台" 区块下方"+ 新 tab" 按钮

**验证**:
- 点 sidebar "知识库" → 右侧出 BrowserView 显示 `/knowledge`
- TabBar 切到 "内容工坊" → BrowserView 切换
- 点 tab 关闭按钮 → BrowserView 销毁,无 tab 时右侧 collapse,agent 全宽

### 切片 3 — BrowserView 位置 / 大小自动跟随(1 天)

**目的**:BrowserView 不在 DOM 里,位置完全靠 main process setBounds 控制;
窗口 resize / agent 拖宽 / DevTools 开关都得跟。

**修改**:
- `WorkbenchPane.tsx` 主体 div 加 `useEffect` 注册 ResizeObserver
  - debounce 16ms(下一帧)调 `electronAPI.tabResize(bounds)`
  - bounds 取 `div.getBoundingClientRect()` + window.devicePixelRatio 换算
- `browser-view-manager.ts`:
  - `resizeActive(bounds)` → 当前 active view `view.setBounds(bounds)`
  - 切 tab 时把上一个 view setBounds 到 `{x:0,y:0,width:0,height:0}` 隐藏
- main.ts 监听 `mainWindow.on('resize')` → 推一个 IPC 让 renderer 重测
  (兜底:有些 resize 场景 ResizeObserver 触发不及时)
- DevTools 打开:`mainWindow.webContents.on('devtools-opened')` 同样推 IPC

**验证**:
- 鼠标拖窗口边缘 resize → BrowserView 跟着改大小,无卡顿
- 拖中缝改 agent 宽 → BrowserView width 跟着减
- F12 开 DevTools → BrowserView 区不被 DevTools 挡住(主进程感知到 devtools-opened
  事件,触发 renderer 重测 bounds)

### 切片 4 — tab 持久化 + 关 app 保存(0.5 天)

**目的**:重启 app 恢复上次的 tab 上下文。

**修改**:
- `main.ts`:
  - 启动期 `loadOpenTabs()` → 依次 `mgr.createTab(...)` 重建 + 激活 activeTabId
  - `mainWindow.on('close')` → `saveOpenTabs(mgr.snapshot())`
- `browser-view-manager.ts`:
  - `snapshot()` → 返 `TabState[]`(id / path / label / icon / 顺序)
  - tab 创建/关闭/切换时自动调 `tab-store.saveOpenTabs` 增量写
- renderer `WorkbenchPane` 初始化时调 `tabList()` 拿持久化数据渲染 TabBar
  (不需要重新触发 createTab,main 已经创建好了)

**验证**:
- 开 3 个 tab(知识库/工坊/SKU 列表)→ 关 app → 重开 → 3 个 tab 都在,
  active 是上次的
- 浏览器历史(BrowserView 内 webContents)是否 restore?**v1 不做**,每个
  BrowserView restore 后回到根 path,老板能接受

### 切片 5 — frontend 未启动检测 + 启动按钮 overlay(1 天)

**目的**:omni frontend 没起来时不让 BrowserView 显示空白,给个明确恢复路径。

**修改**:
- `browser-view-manager.ts`:
  - `pingFrontend()` → fetch `http://localhost:3000` with 2s timeout,
    返 boolean
  - `createTab(path)` 时先 ping;不通 → 创建 BrowserView 加载本地
    `error.html`(file://) 而非 omni path
- 新文件 `src/renderer/public/error.html`:
  - 黑底,中央大字 "omni frontend 没启动"
  - 子标题 "点下面按钮起后端 + 前端,5-15 秒后这个页自动 reload"
  - 大按钮 "启动 omni" → `<script>window.location.href='omni-restart://start'</script>`
    或者用 postMessage 走 preload bridge 调 `IPC_OMNI_START`
- 主进程注册 `protocol.registerHttpProtocol('omni-restart', ...)` 拦截
  → 调现有 `IPC_OMNI_START` handler(omni-desktop 0.1.0 已有"启动后端"功能)
- 启动成功后 main process push 一个 `frontend-ready` 事件,
  `browser-view-manager` 接到 → 把所有 error 状态的 BrowserView 重新
  `loadURL` 到 `http://localhost:3000/<path>`

**验证**:
- 杀掉 omni docker + frontend dev server → 开 tab 显示 "omni frontend 没启动"
  + 大按钮
- 点按钮 → 起 docker,前端就绪后 tab 自动 reload 到 `/knowledge`
- 后端起着但前端没起 → 同样的 error 页(ping 检测的是 :3000 不是 :8002)

## 文件清单

**新建**(7 个):
- `src/main/browser-view-manager.ts`
- `src/main/tab-store.ts`
- `src/renderer/components/AppShell.tsx`
- `src/renderer/components/WorkbenchPane.tsx`
- `src/renderer/components/TabBar.tsx`
- `src/renderer/components/Divider.tsx`(中缝拖动条)
- `src/renderer/public/error.html`

**修改**(5 个):
- `src/main/main.ts`(挂 BrowserViewManager + restore tabs + protocol)
- `src/main/ipc-handler.ts`(+5 个 tab channel + frontend-ready event)
- `src/main/settings-store.ts`(+ openTabs / activeTabId schema)
- `src/preload/index.ts`(暴露 tab* API + 监听 frontend-ready)
- `src/renderer/components/ChatLayout.tsx`(sidebar 加工作台区 + 改宽度可配)

## 工期

| 切片 | 工期 | 关键产出 |
|---|---|---|
| 1 BrowserViewManager + IPC + 持久化骨架 | 1 天 | main process 能开关 BrowserView |
| 2 TabBar + 工作台区 + 左右分栏 | 1.5 天 | renderer UI 完整 |
| 3 位置/大小自动跟随 | 1 天 | resize / 中缝拖 / DevTools 都顺 |
| 4 持久化 + restore | 0.5 天 | 重启恢复上次 tab |
| 5 frontend 未启动检测 + overlay | 1 天 | 错误页 + 启动按钮 |
| **合计** | **5 天** | |

## 不做项

- **tab 拖拽重排**:v2 再加,MVP 用"关 + 重开"凑合
- **BrowserView 内嵌 DevTools**:debug 用桌面端整体 Ctrl+Shift+I 看 renderer;
  BrowserView 内的 webContents debug 用独立 Chrome 开 `localhost:3000/<path>`
- **cross-origin 路径**:严格限定 `http://localhost:3000/*`,外部 URL 一律不允许
  打开(防 BrowserView 变浏览器,这是工作台不是浏览器)
- **手机端 mirror**:老板明确说先不做手机端,W6 PWA 路径继续作手机入口
- **cookie / session 跟主窗口同步**:omni frontend 当前没 auth,后续加了 auth
  再说
- **BrowserView 内浏览历史 restore**:重启后每个 tab 回到根 path,不复原内部
  路由栈
- **tab unload 释放**:不实现"后台 tab 5min 没看自动 unload",老板少开几个 tab
  比这个机制简单

## 风险 / 已知坑

- **BrowserView 不在标准 webContents API surface**:`view.setBounds` /
  `addChildView` 出问题时 stack trace 不直观;首次开发遇 hang 先看
  `electron --enable-logging` 输出
- **resize 节流不当卡顿**:ResizeObserver 不 debounce 直接调 setBounds 会
  造成滚动条/拖拽期间 BrowserView 闪烁,实测 16ms debounce 够流畅,
  32ms 也能接受
- **Electron 33 API 转换**:`mainWindow.setBrowserView` 在 33 已标
  deprecated 但仍可用,`contentView.addChildView` 是新推荐 API;两个都试,
  以能用为准
- **多 tab 内存爆**:每个 BrowserView 是独立 Chromium 渲染进程,5 个 tab
  约占 600-1200MB 额外内存。文档(README / 设置页 tooltip)说明老板别开
  超过 5 个 tab,超了会卡。不做"自动 kill 不活跃 tab",留给老板手动关
- **frontend 路由变更**:omni frontend 加新页 / 改 path 时,9 个预设 tab 的
  path 可能过时;预设清单写代码里(`PRESET_TABS` 常量)不写 DB,改路径直接
  改代码 push 新版 desktop
- **error.html 跟 preload 通信路径**:`protocol.registerHttpProtocol` 拦截
  custom scheme 是个偏门套路,如果通不过用 BrowserView 内塞个简单 JS
  postMessage 给 main 走 IPC 也行;切片 5 实现期遇坑再选

## 跟其他面关系

- **跟 /playground 完全不同**:playground 是 omni frontend 内一个调试场页面
  (一个 React 组件),本 plan 是 omni-desktop 桌面端整体窗口架构改造
  (Electron main process 级)。两个完全独立,playground 也会作为一个
  可开的 tab(`/playground`)出现在 + 新 tab 选项里
- **跟 sidebar 工作台快捷链接(B 路径)关系**:B 是 sidebar 加链接点了在
  默认浏览器开 omni frontend 页面 / C 是嵌入桌面端 BrowserView 内。本 plan
  实现 C 后 B 就没必要存在(默认走 C);如果未来某天发现某些页面 BrowserView
  装不下(如全屏视频播放体验),可回头加个 "在浏览器打开" 二级菜单
- **跟 W7 跨项目 cwd / usage_limit 续跑独立**:那俩是 main process 后台
  跑的(claude-runner + resume-scheduler),跟前台 UI 架构不耦合;BrowserView
  改造完全不影响 W7 已有逻辑
- **跟 W5-B web 版 /chat 共存**:omni frontend `/chat` 是 fallback 路径
  (sidebar 上标 "Agent 对话 (Web 版)"),桌面端 C 上来后老板可两个都开,
  甚至在桌面端 + 新 tab 加 `/chat` 都能跑(虽然没意义,因为左侧 agent 对话
  就是它)

## 落到老板话术 → 操作

| 话术 | 操作 |
|---|---|
| "打开知识库" | TabBar 点 "知识库" / sidebar 点工作台 → 知识库 |
| "我要看下投放复盘" | sidebar 工作台 → 投放复盘 |
| "新开个 X 页面" | TabBar "+ 新 tab" 输入 `/X` |
| "关掉这个 tab" | TabBar 当前 tab 鼠标 hover → ×  |
| "agent 区窄一点" | 中缝拖左,settings 自动保存 |
| "omni 没起" | 错误页大按钮点一下,等 10 秒自动恢复 |
| "我只想看 agent 对话不看工作台" | 关掉所有 tab → 右侧 collapse,agent 全宽 |
