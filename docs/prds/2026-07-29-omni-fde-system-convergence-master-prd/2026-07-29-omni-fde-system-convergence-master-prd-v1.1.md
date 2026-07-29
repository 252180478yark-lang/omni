# PRD：Omni FDE 活体图谱、单一前端与全链路收敛总实施方案

- 状态：READY
- 版本：v1.1
- 日期：2026-07-29
- 需求方 / 决策人：老板（Omni 个人自用环境）
- 系统基线：Omni `2cf161f812866a2706975c312522c60a2753bcde`；工作树 dirty；本 PRD 只新增文档产物，不吸收、覆盖或删除既有未提交改动
- 关联需求：把新功能开发固定成“候选功能安放 → 老板与 Codex 共判接入方案 → 开发合同 → 计划虚线 → 受控实施 → 全链路扫描 → CI 门禁 → 绿色事实节点”；运行任务时把真实模型、工具、服务、数据与状态叠加到同一图上，以可回放微动画解释执行过程并提示漏洞、偏差和未考虑项；同时整理过载前端、判断桌面客户端去留、收敛后端重复入口与多数据真源
- 统筹关系：本 PRD 是总控实施文档，统一并覆盖 `2026-07-28-omni-living-system-graph-prd.md` 与 `2026-07-29-omni-surface-and-backend-rationalization-prd.md` 的冲突；两份原 PRD 保留为详细设计参考

## 1. 落地结论

### 一句话方案

[设计决策][DES-001] 先把现有 `AGENTS.md + 实施 Skill + 开发合同 + Hooks + CI` 从“规则存在”升级为真正可阻断的工程闸门，再建设由代码与运行契约确定性扫描生成的活体系统图谱；在其上增加“候选功能接入共创”和“任务运行数字孪生”，让老板与 Codex 先共同决定新功能应复用、修改或新增哪些接口/数据，再用真实事件微动画说明任务怎样运行并暴露偏差，随后以图谱证据完成 Web 单一业务前端、Host Bridge、前端模块化、后端单真源和旧客户端安全退役。

### 决策摘要

| 项目 | 结论 |
|---|---|
| 解决的问题 | 页面、BFF/API、MCP、service、数据库、migration、外部数据源和测试经常局部存在但整体接不上；前端与桌面、旧链与新链、多个 writer 和执行入口并行，开发者难以判断应该改哪里、缺哪一层、何时才算完成 |
| 主要复用 | 已精简的根 `AGENTS.md`、`omni-feature-development`、开发合同 CLI/模板/测试、AGENTS policy gate、feature-contract CI gate、FastAPI OpenAPI、MCP `TOOL_REGISTRY`/doctor、migration baseline、Scout endpoint catalog、现有 SKU 血缘与 `OutputFeedback` |
| 主要修改 | SessionStart 提醒升级为开发过程 Hooks；开发合同接入真实 before/after graph snapshot；CI 从合同覆盖扩展到静态链路与可运行测试；导航与图谱期望边统一由 `FeatureDefinition` 派生；现有 WebSocket/tool audit 接入统一 trace/span 关联；Electron 从第二套业务前端缩为可选薄壳 |
| 拟新增 | 统一 FeatureDefinition、system-graph schema/service/API/MCP/CLI/collectors、候选功能接入方案、planned/fact/runtime 三层差异、issue 修复卡、任务 trace/span/event、实时与回放微动画、漏洞与遗漏雷达、工作台高级开发视图、SKU 详情业务图、Host Bridge、provider session 契约、附件真源、metric/source ownership 与退役 telemetry |
| V1 不做 | 不让 LLM 猜事实血缘、伪造运行事件或直接决定 CI；不在图上手工改绿或硬删事实；不自动执行 migration、发布、外部平台写入或物理删除；不把漏洞雷达宣传为完整安全审计；不一次性重写全部页面；不立即删除 `omni-desktop`、历史表或用户数据 |
| first_blocker | 无；S0 将当前 migration baseline、脏工作树和敏感配置作为首个必须完成的实施切片，而不是 PRD 开工阻塞项 |

### 当前完成度

| 能力 | 当前状态 | 本 PRD 处理 |
|---|---|---|
| 精简 AGENTS 与开发硬闸 | 已存在于本地工作树，策略检查通过 | S0/S1 纳入版本控制并在新 Codex 任务验证加载 |
| 实施 Skill、影响合同、完成合同、状态机 | 已存在，44 项合同测试通过 | S1 复用并补真实 snapshot、FeatureDefinition 与 Hook 上下文 |
| AGENTS policy CI、feature-contract CI | 已存在 | S1/S4 保留并扩展为全链路 gate |
| 本地 Hook | 仅 SessionStart advisory | S2 增加写入前检查与停止前验证；先 warning，试点后 block |
| 活体图谱 scanner/service/API/UI | 尚不存在 | S3-S7 新增 |
| 候选功能接入共创 | 尚不存在 | S5 在事实快照上新增候选计划、证据化选项和用户确认 |
| 虚线计划链自动转绿色事实链 | 合同字段存在，未接真实 scanner | S3-S6 实现并以证据守卫状态变化 |
| 任务运行数字孪生与微动画 | 已有会话 WebSocket、tool-use 列表与审计碎片，没有系统级 trace/span | S8-S9 先补统一关联与事件合同，再做实时/回放动画 |
| 漏洞与遗漏雷达 | 尚无 planned/fact/runtime 三层对比 | S9 新增确定性发现与 AI 建议分层 |
| 单一 Web 业务前端与 Host Bridge | 目标已明确，尚未完成 | S10-S12 迁移与收敛 |
| 客户端退役 | 当前不具备安全删除条件 | S13 满足退出证据后再卸载/归档 |

### 统一后的架构决策

1. [设计决策][DES-002] `FeatureDefinition` 是功能身份、入口、能力、期望链路、检查规则和生命周期的唯一 Git 真源；前端 Feature Registry 与图谱 Manifest 都是它的投影，不维护两份同名配置。
2. [设计决策][DES-003] 图谱事实层只能由静态/运行时 collector 生成；合同只声明预期，UI 不允许手工修改事实、删除事实或改健康状态。
3. [设计决策][DES-004] 图谱不增加常驻一级导航：开发视图进入 `/workspace` 高级模式；SKU 业务图进入 `/sku/[id]`；允许保留内部深链接。
4. [设计决策][DES-005] Web/PWA 是唯一业务 UI；Host Bridge 只承载 Codex/Claude、本地文件、可见扫码、续跑等宿主能力；Electron 最多保留薄壳，不保留第二套业务实现。
5. [设计决策][DES-006] scanner 的 `unknown` 不等于 `missing`；依赖不可用时不得生成“删除”结论。只有静态可证明、manifest 标为 required、证据完整的断链才能阻断。
6. [设计决策][DES-007] 当前 migration baseline 未 ready 前不新增生产表或字段；图谱可先以文件 snapshot 验证合同，数据库持久化必须排在账本收敛之后。
7. [设计决策][DES-008] 用户所说“先把功能安上去”在 V1 中定义为创建 `candidate/planned` 候选功能节点，不等于部署代码；系统基于当前 snapshot 给出“复用 / 修改 / 拟新增 / 不做”接入选项，必须由老板确认后才能写入 impact 合同。
8. [设计决策][DES-009] 运行视图采用 OpenTelemetry 兼容的 trace/span/event 语义，动画只消费真实事件；缺失、乱序或未埋点的段落显示 trace gap，绝不补画一条看似完整的链。
9. [设计决策][DES-010] 漏洞雷达将“确定性观察”与“Codex 假设/建议”分层：可复现的 required-edge、schema、owner、权限与运行偏差可以阻断；启发式遗漏只能告警并提供验证方法，不能冒充事实或安全证明。
10. [设计决策][DES-011] 前端只建设一个“Omni 系统中台”，同一事实图按需切换“开发模式 / 执行模式 / 业务血缘模式”，共用搜索、证据、中文解释和雷达；最小观测单元是可稳定关联的 span/event 与字段级 schema/血缘，敏感值只显示脱敏摘要，不能以“最小颗粒度”为由暴露原文、秘密或个人数据。

## 2. 背景、现场问题与目标

### 用户与场景

- [用户确认][USR-001] 老板开发新功能时经常遇到前端已有但接口没有、接口有但数据库/字段没有、数据库有但数据源没有，或者参数名称与类型不一致。
- [用户确认][USR-002] 老板需要开发时可视化查看“这次改哪一部分、接在哪条链、是否开发到正确位置”，并在使用时从店铺与 SKU 展开业务血缘。
- [用户确认][USR-003] 计划中的页面、接口、Tool、service、表和测试应先以虚线显示；完成后只有通过扫描和测试才能转成绿色事实节点。
- [用户确认][USR-004] 开发流程必须植入 Codex，不再要求老板每次重复输入提示词。
- [用户确认][USR-005] 前端入口过多，需要整理；桌面客户端若没有独立价值应退役；后端重复功能、重复内容和多真源需要梳理。
- [用户确认][USR-006] 本轮交付一份覆盖全部待实现事项、可直接开工的 PRD PDF；PRD 交付本身不授权实施产品代码或删除资产。
- [用户确认][USR-007] 开发新功能时，老板希望先在图中安放候选功能，再与 Codex 一起判断应连接哪些现有数据和接口、是否需要新增接口/数据，以及怎样接进整套系统。
- [用户确认][USR-008] 使用功能、模型或完成任务时，老板希望在同一图上实时看到实际走过的模块、模型、工具、服务与数据链，并通过可控微动画看懂运行逻辑、数据流动和执行流程。
- [用户确认][USR-009] 系统需要主动暴露计划与实际的偏差、运行漏洞、观测盲区和未考虑项，同时明确哪些是事实、哪些只是 Codex 建议。
- [用户确认][USR-010] 开发中台与执行中台必须合并成一个系统中台；同一思维导图按真实运行高亮线路，旁侧以中文解释任务经过的 Skill、模型、页面、接口、Tool、service、表/字段和数据源，以及每一跳的输入、输出和下一跳去向。

### 当前流程、绕行方式与失败成本

当前每一层都有局部工具，但缺少一套共同完成定义：开发者通过搜索页面、接口、MCP catalog、migration 和数据库来拼链路；测试常常只覆盖局部；旧入口和新入口继续并行。结果包括：

- 页面请求一个不存在或已改名的 BFF，直到联调才发现 404。
- REST 已有但 MCP 未注册，Web 能调用而 Codex 不能调用，或反之。
- service 使用新字段，但 migration ledger、运行库和 reader 没有同步。
- 外部端点与指标关系散落在代码中，同一 canonical metric 被两个任务覆盖。
- Electron、Web 与企业微信各自持有会话或 runner 逻辑，会话 ID、历史目录和工作目录发生漂移。
- 前端巨页与几十个模板式代理使一次字段改名要跨很多文件，漏改概率持续增加。
- “文件创建、页面可打开、局部单测通过”被误认为完成，真实静态链路仍然断裂。
- 新功能只能先写代码再联调，缺少一个在施工前共同判断“复用什么、根基改什么、是否真要新增接口/表”的安全规划层。
- 任务运行时只能看到聊天消息、局部tool调用或轮询进度，无法可靠解释页面、模型、Tool、service、数据库和数据源怎样串联，也无法区分真实路径与猜测。
- 运行失败、计划外调用、未埋点、双writer、权限/测试遗漏没有在同一处对比，用户难以及时发现系统漏洞和自己未想到的环节。

失败成本包括返工、错误数据、平行实现、无法恢复的历史删除，以及在没有安全边界时把宿主机执行能力暴露给 Web。

### 目标与成功指标

| 目标 | 指标口径 | 数据源 | 当前基线 | 目标/判定 | 观察窗口 |
|---|---|---|---|---|---|
| 开发合同覆盖 | 契约敏感 Git diff 中被有效 impact/completion 合同覆盖的路径占比 | feature-contract CI artifact | 当前 gate 已能检查合同，但资产尚未全部入 Git | block 模式下全部敏感变更均被合同覆盖 | 每次变更 |
| 静态断链归零 | 当前 change 的 required edge 中状态为 missing 且无受控例外的数量 | graph diff/issues | 尚无真实 scanner | 进入 `COMPLETE` 前为 0 | 每次变更 |
| 计划转事实可证 | 由 planned 转 observed/healthy 的节点和边均带当前 commit、collector 与测试证据 | snapshot/evidence | 尚无统一口径 | 每个绿色节点和边均可打开证据 | 每次 snapshot |
| 功能入口单真源 | 导航、首页、引导和图谱中同一 `feature_id` 的定义数量 | FeatureDefinition build/test | 当前导航多处维护 | 每个功能只有一个 canonical definition，无重复 ID/href | 每次 CI |
| 单一业务前端 | 同一业务能力需要维护的业务 renderer 数 | FeatureDefinition + repo scan | Electron renderer 与 Next 并行 | 业务 UI 只在 Next；Host Bridge/Electron 壳不含业务页面 | 每次发布 |
| 会话与附件可恢复 | Web/企业微信跨进程重启后续聊和附件读取是否通过 | 集成 smoke | provider/session/upload 合同仍分散 | Claude/Codex 会话、cwd、历史、附件保持一致 | 每次 Host/Web 发布 |
| 数据演进安全 | migration baseline 状态 | `p0_preflight_video_production` | 当前 `blocked` | `ready`，空库与存量库升级均通过 | 每次 migration |
| canonical 指标无覆盖 | 非 owner 尝试写 canonical metric 的次数 | ownership/collision audit | 当前两个 writer 可更新同一唯一键 | 非 owner 成功写入为 0，碰撞全部留痕 | 每日 |
| 旧客户端安全退出 | Electron 独占调用、回退事件与 Host smoke | Host/desktop telemetry | 当前仍有 7777、续跑、扫码、本地文件依赖 | 连续 14 天无 Electron 独占调用且 Host smoke 全绿后才允许退役 | 退出观察期 |
| 接入方案证据完整 | 候选功能每个 reuse/modify/add/not_do 决策是否带当前事实、风险与验证 | integration plan artifact | 尚无该能力 | 用户确认前零产品副作用；锁定后每项均可追到 snapshot/evidence | 每个候选功能 |
| 运行路径可解释 | 有权查看的已观测 span 中，可映射节点/边或明确标为 gap/unmapped 的比例 | runtime trace artifact | 只有 tool-use/审计碎片，尚无统一 trace | 不允许“无解释消失”；不能映射的事件必须显式进入 gap/雷达 | 每个任务 |
| 动画忠于事实 | UI 播放顺序、状态、输入输出摘要与 immutable trace 是否一致 | trace replay E2E | 尚无动画 | 回放与原 trace 事件序列一致；缺事件不补画 | 每次相关发布 |
| 漏洞建议可行动 | 雷达 finding 是否含事实/假设分类、影响、修复位置和验证 | finding schema/feedback | 尚无统一雷达 | 每个 finding 均可验证；启发式建议不作事实阻断 | 每次 scan/任务 |

## 3. 当前系统事实

### 证据台账

| ID | 标签 | 原子事实 | 证据 | 核查级别 | 设计影响 |
|---|---|---|---|---|---|
| SYS-001 | `[现状事实]` | 根 `AGENTS.md` 已将跨页面/API/MCP/service/DB/source 的开发路由到实施 Skill，并规定断链不得 `COMPLETE` | `AGENTS.md:23,50-60` | 代码已核 | 复用为 Codex 入口，不再继续堆长 SOP |
| SYS-002 | `[现状事实]` | `omni-feature-development` 已实现六态流程和 impact/completion 严格校验 | `.agents/skills/omni-feature-development/SKILL.md:8-91`；`scripts/dev_contract.py` | 代码已核 | 复用合同，不另造第二套开发状态机 |
| SYS-003 | `[现状事实]` | 当前 AGENTS policy 检查通过，相关策略测试 16 项、开发合同测试 44 项通过 | 2026-07-29 本轮命令记录 | 本地运行已核 | 当前规则底座可作为 S1 起点，但尚未提交 |
| SYS-004 | `[现状事实]` | 项目 Hook 目前只有 SessionStart advisory；没有写入前或停止前合同阻断 | `.codex/hooks.json:1-19`；策略测试明确 `hook_mode_warns_but_never_blocks` | 代码已核 | 用户描述的实时拦截尚未实现 |
| SYS-005 | `[现状事实]` | CI 已有 AGENTS policy gate 和 feature-contract gate，但全量测试仍 `continue-on-error` | `.github/workflows/ci.yml:35-103,210-211` | 代码已核 | 不能宣称 CI 已验证全部真实链路 |
| SYS-006 | `[现状事实]` | system-graph page/schema/service/router/MCP 目标文件当前均不存在 | 2026-07-29 `Test-Path` 检查 | 代码已核 | 图谱扫描、虚线转绿和 UI 均为拟新增 |
| SYS-007 | `[现状事实]` | Web 当前有 42 个页面、121 个 Next route；SKU Pipeline 单页 7,563 行并有 43 个 BFF route | 2026-07-29 只读文件统计；`frontend/src/app/sku-pipeline/page.tsx` | 代码已核 | 必须建立 FeatureDefinition、typed operation registry 并纵向拆分 |
| SYS-008 | `[现状事实]` | `/chat` 当前渲染 Agent Chat，但首页与新手引导仍按知识库问答描述 | `frontend/src/app/chat/page.tsx:2-5`；`frontend/src/app/page.tsx:159-166,499-500`；`frontend/src/components/beginner-guide.tsx:140-186` | 代码已核 | 同一入口的产品语义已经漂移 |
| SYS-009 | `[现状事实]` | Electron 启动 IPC、Redis、托盘、快捷键、HTTP 服务、续跑和本地文件协议，不是可直接删除的网页壳 | `E:/agent/omni-desktop/src/main/main.ts:167-206` | 代码已核 | 先拆 Host Bridge，后退役业务 renderer |
| SYS-010 | `[现状事实]` | 企业微信 Codex 默认依赖宿主 `host.docker.internal:7777` | `services/knowledge-engine/app/services/wecom_remote_router.py:44,67`；`docker-compose.yml:252` | 代码已核 | 直接删除 desktop 会断远程 Agent |
| SYS-011 | `[现状事实]` | Web 上传写 frontend 进程目录，却返回 KE 静态 URL；两者当前没有被证明为同一持久真源 | `frontend/src/app/api/agent-chat/upload/route.ts:9-27`；`docker-compose.yml:120-164,282` | 代码已核 | 附件必须改为 ID 与共享存储合同 |
| SYS-012 | `[现状事实]` | MCP doctor 当前 154/154 全绿，但 `CLAUDE.md` 手工计数仍写 115 | 2026-07-29 doctor 运行结果 | 运行时已核 | 注册成功不等于端到端唯一，手工总数不能作为真源 |
| SYS-013 | `[现状事实]` | migration preflight 当前 `blocked`，运行 ledger 的 091/092 各有双前缀，且有两条 runtime-only migration | `p0_preflight_video_production` 2026-07-29 返回 | 运行时已核 | 新增图谱表或会话字段前必须先收敛 migration 真源 |
| SYS-014 | `[现状事实]` | `metric_ingest` 与 `runbook_executor` 均可对 `mvp_daily_metric` 同一唯一键执行 `ON CONFLICT DO UPDATE` | `services/scout-agent/app/services/metric_ingest.py:575-607`；`runbook_executor.py:395-399,525-529` | 代码已核 | 需要 canonical owner 与 collision gate |
| SYS-015 | `[现状事实]` | KE 有 `/mcp/exec/{tool_name}` 与 `/mcp/catalog/exec` 两套通用 dispatcher，二者都从 `TOOL_REGISTRY` bind 并执行 | `services/knowledge-engine/app/routers/mcp_exec.py:991-1016`；`mcp_catalog.py:58-84` | 代码已核 | 抽唯一执行内核，URL 只做兼容适配 |
| SYS-016 | `[现状事实]` | 现有 SKU 血缘、OpenAPI、MCP catalog、migration baseline 和 Scout catalog 都可作为 collector 输入，但没有共同 Node/Edge/Snapshot/Issue 契约 | 现有两份子 PRD列明的源码与本轮文件核查 | 代码已核 | 复用事实源，新增统一图模型而非复制业务逻辑 |
| SYS-017 | `[现状事实]` | `AGENTS.md`、`.agents/`、`.codex/` 及部分 gate 脚本仍未跟踪，CI workflow 处于修改状态 | 2026-07-29 `git status --short` | Git 已核 | S0/S1 必须先做路径级审查与版本化 |
| SYS-018 | `[现状事实]` | FDE Skill 文档给出的 `python scripts/validate_prd.py` 在仓库根不存在，真实脚本位于 Skill 内部 | `.agents/skills/omni-fde-prd/SKILL.md:25`；`Test-Path scripts/validate_prd.py = false` | 代码已核 | S1 必须提供稳定根入口或修正文档，防止照流程执行仍断链 |
| SYS-019 | `[现状事实]` | Agent Chat 已通过 WebSocket 发送 session-scoped `chunk`、tool call/result 与 `task_done`，前端可按 `tool_use_id` 配对调用与结果 | `frontend/src/lib/agent-chat/types.ts:117-124`；`ws-handler.ts:254-281`；`useAgentChat.ts:46-64,113-121` | 代码已核 | 可复用流式通道和事件解析，但不能直接当系统级 trace |
| SYS-020 | `[现状事实]` | Playground `TracePane` 当前展示 tool 调用列表、输入输出、LLM trace、耗时和成本，不是页面→接口→Tool→service→表/源的图形运行孪生 | `frontend/src/components/playground/TracePane.tsx:7-34,104-156` | 代码已核 | 复用明细交互，不复用为完整运行图结论 |
| SYS-021 | `[现状事实]` | `@tool_with_audit` 与 `mcp.tool_calls` 已留存 tool、参数、结果、状态和时长，`mcp.client_logs` 另存客户端事件 | `app/mcp/audit.py:79-166`；`migrations/016_mcp_audit.sql:5-24`；`032_bug_memory_and_logs.sql:6-25` | 代码已核 | 可作为 trace adapter 输入，需补统一 correlation/parent-child/脱敏合同 |
| SYS-022 | `[现状事实]` | Claude `tool_use_id` 与 KE 审计行当前按 tool_name+时间窗回填，源码明确称为近似匹配；尚无贯穿所有层的 `trace_id/span_id/parent_span_id` 证据 | `app/routers/tool_uses.py:1-11,37-41,70-91`；`migrations/035_toolcalls_tooluseid.sql` | 代码已核 | 数字孪生前必须先补确定性关联，旧事件无法映射时标 unmapped/gap |
| SYS-023 | `[现状事实]` | SKU `LineageTree` 是写死六类节点的嵌套卡片树，生成后通过 `lineageKey` remount/refetch；不是可扩展通用节点—边画布或实时增量覆盖层 | `frontend/src/app/sku-pipeline/LineageTree.tsx:66-93,236-321`；`page.tsx:753,7487,7536` | 代码已核 | 保留为业务适配器/无障碍降级，不能作为统一图模型 |
| SYS-024 | `[现状事实]` | 任务页每5秒轮询并展示进度/旋转状态；Agent Chat WebSocket断线只置为未连接，当前协议没有图节点、sequence或replay cursor | `frontend/src/app/tasks/page.tsx:79,146,340-349`；`frontend/src/hooks/useAgentChat.ts:41,74`；`frontend/server.ts:28-34` | 代码已核 | 可复用状态样式和流式基础，需新增持久事件、续传、去重与回放 |
| SYS-025 | `[现状事实]` | 运行库 `mcp.tool_calls` 当前有9,608行，但 `tool_use_id` 与 `claude_session_id` 非空均为0；Codex runner上报的名称形如 `mcp__server__tool`，而audit记录函数名，现有精确同名回填无法形成可靠关联 | 2026-07-29 只读SQL；`frontend/src/lib/agent-chat/codex-runner.ts:159-178`；`app/mcp/audit.py:65-91`；`app/routers/tool_uses.py:70-91` | 运行时+代码已核 | S8必须先建立execution/trace上下文与规范化tool identity，动画不能依赖现有回填 |
| SYS-026 | `[现状事实]` | 运行库 `mcp.client_logs` 当前有85,049行但 `session_id` 非空为0；Human Gate WebSocket事件广播给全部连接且 `session_id=''` | 2026-07-29 只读SQL；`frontend/src/lib/agent-chat/ws-handler.ts:34-66` | 运行时+代码已核 | 客户端/审批事件必须补session/execution路由后才能支持并发任务归因 |

### 当前端到端链路

```text
当前 Codex：
新任务 → AGENTS 路由 → 实施 Skill → impact/completion YAML
       └→ SessionStart policy 提醒
Git diff → feature-contract CI
缺口：没有 PreToolUse/Stop 强闸，没有真实 graph snapshot/collector

当前业务入口：
Electron renderer ─┬→ IPC / Host runner / 7777 / resume / file
                  └→ 嵌入或跳转 Web
Browser/PWA → Next Web → 121 个 BFF route → KE/Scout/其他服务

当前数据与后端：
多个 BFF/REST dispatcher → TOOL_REGISTRY/service
旧 runbook ─┐
            ├→ 同一 mvp_daily_metric canonical 行
新 ingest ──┘
旧 content_studio 与新 pipeline 仍并行存在

当前运行观测：
Agent runner → WebSocket chunk/tool_use/task_done → 聊天/Playground TracePane
MCP Tool → mcp.tool_calls audit；Desktop → mcp.client_logs
缺口：runner tool name 与audit identity未规范化，tool/session关联为0；无统一execution/trace/span、跨服务传播、事件账本、cursor重放或planned/fact/runtime比较
```

### 事实冲突或运行时未核项

- migration baseline 的 blocker 已由运行时 tool 复核；修复方式必须保留已执行 SQL 与 checksum，不能直接重命名历史迁移。
- TriMind、Roundtable、旧 RAG、若干未导航详情页和 `face_mesh.py` 的真实使用量尚无统一 telemetry；本 PRD将它们放入“观测后退役”，不直接删除。
- Products/SKU Pipeline 与广告/旧 Brief 的 product reader 是否表达同一业务实体尚未证明；合并前必须定义主键和映射。
- 当前工作树包含他人或既有未提交改动；任何实施必须按 path scope 建合同，禁止清理无关改动。

### 同概念读写真源核对

| 业务概念 | writer 写到哪里 | reader / 页面从哪里读 | 是否同源 | 处理 |
|---|---|---|---|---|
| 功能定义 | sidebar、首页、引导、未来 graph manifest 分散 | 多处 UI 与 CI | 否 | 拟新增唯一 `FeatureDefinition`，其余生成 |
| 开发状态 | `impact.yaml`/`completion.yaml` | Skill、CI、未来 UI | 基本同源 | 复用现有合同，接入 snapshot 和 Hook |
| Agent 会话身份 | `mcp.agent_sessions.claude_session_id` 等 | Web/Host/企业微信 | 否 | 迁移为 provider-neutral session 合同 |
| 附件 | frontend 临时路径、KE 静态目录、desktop uploads | Web/KE/Codex | 否 | 统一 attachment ID、持久存储和授权读取 |
| canonical 指标 | old runbook 与 metric ingest 均可 upsert | 经营分析与问数 | 否 | owner registry + append-only observation + collision gate |
| MCP 执行 | 两个 REST dispatcher | 前端、企业微信、Codex | 逻辑重复 | 抽唯一 executor，URL 保留薄适配 |
| 内容血缘 | `content_studio.*` 与 `pipeline.*` | 不同页面和历史记录 | 否 | 新功能只写 `pipeline.*`，旧链只读桥接后退役 |

## 4. 范围与非目标

### P0 / V1

- 把当前规则资产、Skill、合同、Hooks 与 CI 纳入版本控制并证明新 Codex 任务能够自动加载。
- 增加写入前和停止前本地门禁；合同外关键变更必须先更新 impact。
- 建立唯一 `FeatureDefinition` 与确定性的 system graph schema、collectors、snapshot、diff 和 issue。
- 建立统一“Omni 系统中台”：同一思维导图支持开发、执行和业务血缘三种投影，不再新增两个互相漂移的中台。
- 允许先创建无副作用的候选功能节点，由 Codex 基于当前事实提出复用/修改/拟新增/不做方案，老板逐项确认后才生成 impact 合同。
- 把 impact 中的计划链显示为虚线；完成后仅凭当前事实与测试证据转成绿色。
- CI 检查页面/BFF/API/MCP/service/migration/table/source/test 的 required edge；静态断链阻断完成。
- 在工作台高级模式与 SKU 详情提供开发图和业务图，不增加新的一级导航。
- 建立统一 trace/span/event 合同，把任务真实经过的 Skill、模型、页面、接口、Tool、service、表/字段和数据源叠加到事实图；提供实时高亮、暂停、逐步、倍速和历史回放。
- 点击任一步时用中文解释“为什么到这里、输入什么、输出什么、下一步去哪、读写什么、是否失败/重试”，并让 planned/fact/runtime 三层雷达提示确定性漏洞、运行偏差和未考虑项。
- 建立 Web 单一业务前端、Host Bridge 边界、统一 Agent session/auth/upload 契约。
- 收敛 SKU Pipeline 的 typed operation registry、migration ledger、metric writer 和 MCP executor。
- 建立兼容入口和旧客户端的 telemetry、deprecation、回滚和安全退役流程。
- 用一个真实小功能完整试跑，再由 warning 升级为 block。

### P1 / 后续

- 扩展 planned layer 的自由拖拽、批量布局版本、撤销/重做和多人协作；P0 已包含表单化候选计划、逐项确认及从 issue 创建计划草稿。
- 可选薄 Electron 壳、PWA service worker/Web Push、统一设置中心。
- 在流量归零与恢复演练后物理删除旧 alias、旧业务 renderer、孤立服务与过期安装包。
- 扩展跨仓库、跨分支和历史版本的图谱比较。

### 明确不做

- V1 允许 Codex 基于事实骨架提出接入方案和中文解释，但不让 LLM 参与 CI 事实判定、伪造节点/边/事件或自动把建议转成事实；原因是链路门禁必须确定性、可重复。
- V1 不从图谱直接执行修复、migration、发布、采纳或外部平台写操作；原因是这些动作需要独立合同与 Human Gate。
- V1 不把“运行时服务暂不可用”判定为节点删除；原因是可能制造假断链。
- V1 不一次性删除 `omni-desktop`、旧 content_studio 表、旧 RAG、TriMind 或 Roundtable；只有 telemetry 与迁移证据满足退出条件后再纳入独立删除合同。
- V1 不承诺业务 ROI 或投放效果；系统图谱只证明技术链路与证据完整性。

## 5. 目标流程与状态机

### 前置条件与入口

- Codex 从 Omni Git 根目录启动，根 `AGENTS.md`、目标 Skill 和 `.codex/hooks.json` 已被受信任项目加载。
- migration baseline 相关变更在 S0 后为 `ready`；S0 之前不新增生产实体。
- 任何跨层功能有唯一 `change_id`，并引用一个或多个 `feature_id`。
- 用户可以从对话提出需求，也可以在统一系统中台安放候选功能或从雷达 issue 创建草稿 change；三者最终走同一实施 Skill。

### 主路径

1. Codex 识别需求是否需要 PRD；若需要，先完成 READY PRD。
2. scanner 生成当前 before snapshot。老板在系统中台创建候选功能节点，或由对话创建同一类 candidate draft；此动作只写计划，不写产品代码、数据库或外部系统。
3. Codex 读取事实图、FeatureDefinition、OpenAPI、MCP catalog、migration/source/test，逐层给出 `reuse / modify / add / not_do / unknown` 建议；每项标明事实、建议或假设，并让老板确认。
4. 用户确认的 plan revision 生成 `impact.yaml`/`completion.yaml`，记录 baseline commit、scope、FeatureDefinition、复用/修改/拟新增/不做、required edges、测试、迁移、风险和回滚。
5. impact 中未来节点和边形成 planned layer，以虚线显示；严格校验通过后进入 `IMPACT_LOCKED`。此前只允许只读调查、计划和合同写入。
6. PreToolUse 检查写入路径。若关键路径不在 impact 中，阻止写入并要求先更新合同。
7. Codex 实施代码；发现新依赖时更新 plan/impact、理由和 required edge，再继续。
8. 进入 `VERIFYING` 后运行窄测试、集成测试、OpenAPI、MCP doctor、migration/data source 检查及 graph scan。
9. scanner 生成 after snapshot 与语义 diff；Stop hook 与 CI 检查计划/实际、required edges、orphan、测试和运行时 unknown。
10. 有静态 blocking issue 时保持当前状态，输出修复卡；不得宣布完成。
11. 所有 required edge 为 present/healthy，测试证据属于当前 change，completion 严格校验通过后进入 `COMPLETE`；UI 才将相应 planned 节点转为 observed/healthy 绿色事实。
12. 功能被真实调用时，runtime adapters 生成统一 trace/span/event；系统中台按事件顺序高亮已走路径，中文解释器只基于事实与脱敏摘要说明每一跳。
13. 任务结束或运行中出现偏差时，雷达比较 planned、fact 与 runtime；确定性缺陷进入 issue/CI，假设进入待验证建议，必要时一键创建新的 plan draft。

### 候选功能规划状态机

| 当前状态 | 事件/守卫 | 下一状态 | 副作用边界 | 失败处理 |
|---|---|---|---|---|
| `DRAFT` | 绑定base snapshot并形成逐层影响项 | `REVIEWING` | 只写plan artifact，不写产品/DB/外部系统 | snapshot partial项标unknown，可继续补证据 |
| `REVIEWING` | Codex建议完成；老板逐项接受/拒绝/改写 | `FROZEN` | 只有显式确认后生成impact草稿 | 关键unknown、非法edge、无权限或CAS冲突时不冻结 |
| `FROZEN` | impact严格校验并锁定 | 进入既有`IMPACT_LOCKED` | plan revision不可改；实施受合同/Hook/CI约束 | 后续变化创建新revision，不倒改历史 |
| `DRAFT/REVIEWING/FROZEN` | base snapshot hash变化 | `STALE` | 不自动套用旧决定 | rebase显示事实差异，老板重新确认受影响项 |
| 任意非实施状态 | 老板归档 | `ARCHIVED` | 保留历史和审计，不删除事实 | 重开时创建新revision |

### 开发状态机

| 当前状态 | 事件/动作 | 守卫 | 下一状态 | 持久化/副作用 | 失败处理 |
|---|---|---|---|---|---|
| `DISCOVERED` | 初始化 change | change_id、baseline、scope 可解析 | `IMPACT_LOCKED` | 写 impact/completion 草稿和 before snapshot 引用 | 保持状态，只允许调查与合同写入 |
| `IMPACT_LOCKED` | 开始实施 | 影响面、required edges、测试、回滚完整 | `IMPLEMENTING` | 记录锁定 revision | 越界路径被 Hook 拒绝 |
| `IMPLEMENTING` | 请求验证 | 实际 diff 已同步进 completion | `VERIFYING` | 冻结本轮候选 diff | 新依赖则返回更新 impact |
| `VERIFYING` | 测试与扫描完成 | 证据属于当前 commit/change | `GRAPH_DIFF_READY` | 写 after snapshot、测试退出码、graph diff | blocking 留在本状态；依赖不可用写 unknown |
| `GRAPH_DIFF_READY` | 完成校验 | 无缺失 required edge、无 unowned orphan、完成合同严格通过 | `COMPLETE` | 写完成身份、时间、证据索引与人话汇报 | Stop/CI 阻断并给修复卡 |
| `COMPLETE` | 新发现回归 | 新 snapshot 出现 blocking issue | 新 change | 原完成合同不可改，创建修复 change | 保留历史证据，不倒改旧完成记录 |

### 图节点状态维度

| 维度 | 值 | 说明 |
|---|---|---|
| existence | `planned / observed / removed / unknown` | 是否计划、实际发现、可靠确认删除或无法判断 |
| health | `healthy / warning / broken / unknown` | 当前链路健康状态，不与存在状态混用 |
| lifecycle | `active / deprecated / archived` | 业务生命周期；归档不是物理删除 |
| evidence | `static / runtime / both / none` | 结论的证据级别 |

### 运行追踪状态机

| 状态 | 进入条件 | 图上表现 | 中文解释 | 退出/异常 |
|---|---|---|---|---|
| `live` | 已认证事件流持续到达且在配置延迟窗内 | 当前边流动高亮，已完成上游保留完成标记 | 说明正在执行的模块、输入 schema/脱敏摘要、预期输出 | finish 后进入 completed；断流进入 disconnected |
| `delayed` | 事件到达但超过版本化延迟阈值 | 高亮保留并显示“延迟”而非假装实时 | 说明最新观测时间和缺失窗口 | 恢复后追帧；不可跳过未确认段 |
| `replaying` | 用户播放 immutable 历史 trace | 按原 sequence/cursor 重放 | 逐步解释当时实际输入输出和状态 | 播放完进入 completed；不触发真实副作用 |
| `partial` | 某来源失败、未埋点或无法映射 | 已证实路径正常显示，断点显示 gap/unmapped | 明确“这里没有足够证据”，列出需补的埋点/关联 | 补证据后生成新 trace/映射，不倒改原始事件 |
| `failed/cancelled` | 真实 span 报错或任务取消 | 停在对应节点，未执行后续不高亮 | 说明错误、重试、补偿与影响；不把假设写成原因 | 重试生成新 attempt/span，并关联原 trace |
| `completed` | 结束事件存在且必需 span 已闭合，或明确列出 gap | 路径固定，可逐步回放 | 汇总经过的 Skill/模型/模块、读写数据和结果 | 发现新偏差进入雷达；不得修改业务结果 |

### 退出、重试与人工确认

- scanner refresh 使用输入指纹幂等；同一 commit、FeatureDefinition revision 和 collector 版本复用结果。
- 单个 collector 超时只把对应来源标为 partial/unknown，不删除旧事实；允许局部重试。
- Hook 无法运行时必须显式报告降级；CI 仍是最终强制边界。
- 物理删除、迁移历史、卸载 Electron、旋转凭证、发布或外部写操作必须建立独立 change，并在需要时走 Human Gate。

## 6. 功能需求

### FR-001 [P0] 治理资产版本化与可靠加载

- 角色：使用 Codex 开发 Omni 的老板与 Agent
- 触发：新建、恢复或压缩一个 Omni Codex 任务
- 前置：任务工作目录属于受信任的 Omni Git 仓库
- 规则：根 `AGENTS.md` 保持精简；详细流程放 Skill；机械约束放 Hook/CI；启动时验证 repo root、AGENTS、Skill、Hooks 和版本；Skill 对外命令必须指向真实存在的稳定入口；当前会话不假装热加载已修改规则
- 输出：可审计的加载结果、repo root、规则版本和可用 gate；相关资产进入 Git
- 异常：文件缺失、路径错误、未信任项目、编码异常或大小超限时 fail closed，不进入产品写入
- 来源：USR-004、SYS-001、SYS-003、SYS-017、DES-001

### FR-002 [P0] 开发合同与状态机

- 角色：实施新功能或跨层修改的 Codex
- 触发：任务涉及页面、API、IPC、MCP、service、DB、source、状态、权限、审计或自动化
- 前置：已有 READY PRD，或任务不需要 PRD且影响范围可直接锁定
- 规则：复用现有六态合同；impact 必须声明 feature_id、before snapshot、复用/修改/拟新增/不做、required edges、测试、迁移、回滚和权限；completion 必须来自真实 diff和真实命令
- 输出：版本化 impact/completion、状态变更记录和 path scope
- 异常：空合同、倒退状态、重复 change_id、实际 diff 未覆盖或证据不属于当前 change 时拒绝推进
- 来源：SYS-001、SYS-002、DES-001

### FR-003 [P0] 本地开发过程 Hooks

- 角色：在本地修改 Omni 的 Codex
- 触发：SessionStart、关键文件写入前、任务准备停止或宣布完成前
- 前置：项目已信任 Hooks；当前 change 可解析
- 规则：SessionStart 校验规则链；PreToolUse 对关键写入做 path/contract 检查；Stop 运行 completion、scanner 和必要测试；warning 阶段记录误报，试点通过后对确定性错误 block
- 输出：允许、提醒或阻断结果；命中规则、change_id、路径和修复动作
- 异常：Hook 超时、脚本缺失、合同不可读或 collector 不可用时不得静默放行；不可用来源标 unknown 并交 CI 复核
- 来源：USR-003、USR-004、SYS-004、DES-006

### FR-004 [P0] 唯一 FeatureDefinition

- 角色：开发者、前端导航、图谱 scanner 与 CI
- 触发：新增、修改、隐藏、归档或退役一个功能
- 前置：功能有稳定 `feature_id`
- 规则：同一 Git 定义声明身份、领域、canonical route、入口可见性、能力、owner、lifecycle、expected edges、checks 和兼容 alias；前端 registry 与 graph manifest 均由它生成；重复 ID/href、无 owner 或循环 alias 阻断
- 输出：版本化定义、生成的前端 registry、图谱 expectation 与 CI fixture
- 异常：空数据、schema 版本不兼容、无权限修改受保护定义、重复提交或部分生成失败时不更新任何派生物
- 来源：USR-002、SYS-007、SYS-008、DES-002

### FR-005 [P0] 确定性系统图谱采集与不可变快照

- 角色：Codex、CI、开发视图和业务视图
- 触发：建立 impact、请求 refresh、进入验证或 CI 检查
- 前置：FeatureDefinition 可解析；至少一个 collector 可用
- 规则：采集前端 route/fetch、BFF/API/OpenAPI、MCP registry/doctor、service、migration/table/view、外部 source/metric 和 test；输出稳定 Node/Edge ID、来源、置信度与证据；不使用 LLM 猜边；snapshot 内容寻址且不可原地修改
- 输出：snapshot、nodes、edges、source results、hash 与生成时间
- 异常：空仓库、无权限、collector 超时、重复 refresh 或部分失败时返回明确状态；部分失败保留成功来源并把失败来源标 unknown
- 来源：USR-001、SYS-006、SYS-012、SYS-016、DES-003、DES-006

### FR-006 [P0] 计划链与事实链差异

- 角色：开发中的老板与 Codex
- 触发：impact 锁定、after snapshot 生成或 completion 校验
- 前置：before snapshot、impact required edges 与 FeatureDefinition expectation 可用
- 规则：impact 新增/修改映射为 planned nodes/edges；UI 以虚线显示；after scan 只有发现对应事实且所有 required checks 通过时才能转 observed/healthy；实际超出计划则生成 deviation/orphan
- 输出：added、changed、removed、unknown、required-edge status 和计划偏差
- 异常：snapshot schema 不兼容、来源不可用、同一计划映射多个事实或删除证据不足时不转绿
- 来源：USR-003、SYS-002、SYS-006、DES-003

### FR-007 [P0] 断链 Issue 与修复卡

- 角色：老板、Codex 与 CI
- 触发：required edge missing、参数/schema 漂移、未注册 Tool、缺 migration/source/test、孤立节点或兼容 alias 失配
- 前置：issue 有事实证据与 expectation 来源
- 规则：按稳定 fingerprint 去重；区分 blocking/warning/unknown；每张修复卡必须包含观察事实、期望关系、影响面、证据、建议修改位置和验证方法；ignored/snoozed 不得伪造健康
- 输出：可搜索 issue、状态历史、修复卡和关联 change
- 异常：证据不足只允许 warning/unknown；依赖超时不得生成 removed issue；重复提交幂等
- 来源：USR-001、USR-003、DES-006

### FR-008 [P0] CI 全链路门禁与证据制品

- 角色：提交变更的开发者与代码审查者
- 触发：PR、受保护分支 push 或本地严格完成检查
- 前置：仓库可 checkout，FeatureDefinition 与 change contract 可读取
- 规则：依次检查 AGENTS policy、合同覆盖、FeatureDefinition、静态图、OpenAPI、MCP doctor contract、migration baseline、source ownership、类型与目标测试；产出机器可读 artifact；全量测试环境具备后移除 `continue-on-error`；受保护分支把关键 gate 配成 required checks
- 输出：明确通过/阻断、失败 edge、证据文件、命令和退出码
- 异常：CI 环境缺依赖、DB 未 bootstrap、外部运行时不可用时区分 infrastructure failure 与 product failure，不把未知标成通过
- 来源：USR-003、SYS-005、SYS-012、SYS-013

### FR-009 [P0] 嵌入式开发图与 SKU 业务图

- 角色：开发时和日常经营时的老板
- 触发：打开工作台高级模式、SKU 详情或 issue/feature 深链接
- 前置：至少有一份 snapshot；无 snapshot 时允许触发只读 refresh
- 规则：同一图模型提供开发投影与业务投影；支持搜索、筛选、展开/收起、最短路径、状态颜色、证据抽屉和修复卡；planned 虚线、healthy 绿色、broken 红色、unknown 黄色、deprecated 灰色；不增加一级导航
- 输出：当前 snapshot 时间、节点/边、问题、证据和关联 change；每个产物区带反馈入口
- 异常：loading、empty、error、success 四态完整；分页、orphan 和 partial source 不得静默隐藏
- 来源：USR-002、USR-003、DES-004

### FR-010 [P0] Web 单一业务前端与 Host Bridge 边界

- 角色：浏览器/PWA、可选 Electron 壳与宿主服务
- 触发：访问业务页面或调用宿主能力
- 前置：Web、Core Backend 与 Host Bridge 可分别健康检查
- 规则：业务 UI 只存在于 Next Web；Host Bridge 承载 runner、本地文件、可见扫码、续跑和可选系统能力；Electron 壳只加载 Web并调用 Host Bridge；Core Backend 不依赖 Electron 生命周期
- 输出：清晰能力边界、health/capabilities 与迁移兼容层
- 异常：Host 离线时 Web 明确降级，不显示假成功；第二 Host 实例不得抢占端口；无权限不得调用宿主能力
- 来源：USR-005、SYS-009、SYS-010、DES-005

### FR-011 [P0] Agent 会话、认证与附件统一合同

- 角色：Web、企业微信、Host Bridge、Codex/Claude 和 Core Backend
- 触发：创建/恢复会话、发送消息、上传附件、读取本地文件或续跑
- 前置：身份已认证，project_dir 在白名单且包含有效项目规则
- 规则：使用 provider-neutral `session_id/runner_provider/runner_session_id/project_dir/model/effort/status`；真实 runner ID 首次返回即持久化；HTTP/WS/Host 强制认证；附件使用稳定 ID、元数据、SHA-256 和统一存储；禁止任意 cwd、shell 参数和路径穿越
- 输出：跨入口一致会话、历史、事件流、附件与审计
- 异常：空数据、无权限、token 过期、runner 超时、重复发送、部分附件失败或 Host 离线时返回确定状态，禁止 placeholder ID resume
- 来源：SYS-008、SYS-010、SYS-011、DES-005

### FR-012 [P0] 前端注册表、typed operation 与 SKU Pipeline 模块化

- 角色：Web 前端开发者与使用 SKU Pipeline 的老板
- 触发：渲染导航、调用后端操作或修改 Pipeline 某一步
- 前置：FeatureDefinition 和 operation schema 可生成
- 规则：sidebar、首页、引导均读取同一 registry；SKU Pipeline 拆为 model/api/hooks/panels/page；operation 采用闭合白名单映射 MCP tool；旧 URL 保留 alias 并记录流量；禁止任意 tool 转发
- 输出：稳定入口、typed client、每步独立 UI 与契约测试
- 异常：未注册 operation、参数类型不匹配、旧 alias 无目标、部分批量失败时显示逐项状态，不让失败互相连坐
- 来源：USR-001、USR-005、SYS-007、SYS-008

### FR-013 [P0] Migration、表与数据源演进基线

- 角色：修改数据库、会话字段、图谱实体或数据源契约的开发者
- 触发：impact 涉及表、字段、索引、view、migration 或 external source
- 前置：当前 ledger reconciliation 可读取
- 规则：先保留已执行 migration 文件名、SQL 与 checksum并建立 canonical mapping；顶层 migrations 是唯一演进真源；空库和存量库使用同一 runner；新表/字段只允许纯加法起步并有 rollback/compatibility 说明；source 必须有稳定 ID、owner 和状态
- 输出：`ready` baseline、migration 证据、source catalog diff 与可回滚发布步骤
- 异常：重复数字前缀、runtime-only、checksum 漂移、未知 source 或缺 rollback 时阻断生产实体变更
- 来源：SYS-013、DES-007

### FR-014 [P0] 后端唯一执行内核与数据写入所有权

- 角色：前端、企业微信、MCP、定时任务和分析服务
- 触发：执行注册 Tool 或写入 canonical metric
- 前置：Tool 已注册；metric/source owner 可解析
- 规则：两套 REST URL 调用同一 `execute_registered_tool` 内核；新客户端只使用 canonical URL；metric observation 先 append-only，owner 确定性选出 canonical 值；非 owner 不得静默覆盖；全部动作留 audit
- 输出：执行一致性、source_run/evidence、collision 记录和兼容 telemetry
- 异常：未注册 Tool、bind 失败、无权限、timeout、重复请求、writer 冲突或部分抓取失败时返回统一错误与审计
- 来源：SYS-012、SYS-014、SYS-015

### FR-015 [P0] 旧入口、旧链与客户端安全退役

- 角色：系统维护者与仍使用旧入口的调用方
- 触发：功能被标记 deprecated 或计划删除 alias/client/table/code
- 前置：FeatureDefinition 有 owner、替代路径和 telemetry
- 规则：先加 deprecation header/日志和 ID 映射，再迁移读写方；旧 content_studio 先只读；Electron 保留回退；只有连续观察期零独占调用、数据对账和恢复演练通过后才允许独立删除 change
- 输出：调用清单、迁移状态、退出报告、备份/归档与回滚点
- 异常：发现活跃调用、无法映射历史 ID、附件/设置对账失败、恢复演练失败或部分迁移时停止删除
- 来源：USR-005、SYS-009、SYS-010、DES-005

### FR-016 [P0] 真实功能试点与分级推广

- 角色：老板与维护 FDE 的开发者
- 触发：S1-S4 基础能力完成
- 前置：选定一个范围小但覆盖页面→BFF→Tool→service→DB/source→test 的真实功能
- 规则：完整执行合同、planned layer、Hook、scan、CI、修复和转绿；先 warning 记录误报；规则按 issue code逐项升级 block；试点不得使用额外口头提示绕过默认流程
- 输出：完整 change 证据包、误报清单、block allowlist 与推广决策
- 异常：试点中出现错误阻断、漏报、collector 超时、重复提交或部分失败时保持 warning并修正，不直接全仓强制
- 来源：USR-003、USR-004、DES-001、DES-006

### FR-017 [P1] Planned layer 高级编辑与受控修复任务

- 角色：老板
- 触发：在开发图中调整计划或从 issue 发起修复
- 前置：有权限且当前事实 snapshot 不可变
- 规则：P0 已支持表单化候选计划和逐项确认；本项只扩展自由拖拽布局、批量操作、撤销/重做和复杂计划比较；始终只允许编辑计划与期望合同；发起任务只创建 impact 草稿，不直接改代码
- 输出：版本化计划和可追踪修复 change
- 异常：并发冲突、无权限、过期 snapshot 或非法事实修改时拒绝保存
- 来源：USR-002、DES-003

### FR-018 [P1] 薄 Electron、PWA 与统一设置中心

- 角色：需要托盘、快捷键、开机启动或后台通知的老板
- 触发：S10 退役评审后仍确认需要系统壳能力
- 前置：业务 UI 与 Host Bridge 已分离
- 规则：薄壳不含业务页面和 runner；PWA 增加更新提示、离线状态和可选 Push；模型、effort、project root、通知和 Host 状态统一由 Web 设置中心管理；秘密使用安全存储
- 输出：可选薄壳/PWA 能力和单一设置真源
- 异常：Host 离线、Push 不可用、设置冲突或安全存储失败时可回退 Web/企业微信通知
- 来源：USR-005、DES-005

### FR-019 [P0] 候选功能接入共创与影响模拟

- 角色：准备开发新功能的老板与 Codex
- 触发：老板在系统中台创建候选功能、从雷达问题创建规划，或在对话提出跨层功能需求
- 前置：存在可读取的 base snapshot；partial snapshot 可以建草稿，但缺失来源必须可见
- 规则：创建独立、不可覆盖的 plan revision；按页面/Skill/模型/API/BFF/MCP/Tool/service/表/字段/source/test/权限逐层生成《影响判断表》，每项使用 `reuse / modify / add / not_do / unknown`；`observed_fact` 必须带 snapshot/evidence，`recommendation` 必须给理由和验证，`hypothesis` 必须说明缺失证据；Codex 不得替老板确认修改/新增，也不得因名称相似自动判为可复用
- 规则：老板可逐项接受、拒绝或改写；确认前不得修改产品代码、数据库或外部系统；确认后冻结 revision并生成 impact、expected graph diff、测试、migration、权限、风险与回滚；base snapshot变化时先标 stale并重新比对
- 输出：思维导图中的候选节点/虚线、影响判断表、事实/建议/假设计数、确认状态、plan revision、impact 草稿和预期证据
- 幂等/权限：相同 feature、base hash 与需求指纹复用 active draft；保存使用乐观锁；只读角色不得修改或查看受限证据；重复确认返回同一 frozen revision/change_id
- 异常：collector 超时、schema 无效、悬空 required edge、无权限、并发冲突或仍有关键 unknown 时不得进入 `IMPACT_LOCKED`；Codex 解释失败时保留确定性事实和人工规划
- Human Gate：确认规划只授权进入实施合同，不授权 migration、删除、发布、外部写入或凭证操作
- 来源：USR-001、USR-003、USR-007、USR-010、SYS-016、DES-008、DES-010、DES-011

### FR-020 [P0] 统一执行中台、运行数字孪生与中文微动画

- 角色：正在使用功能、模型或任务并希望理解系统的老板
- 触发：打开系统中台“执行模式”、启动任务，或按 trace_id 回放历史任务
- 前置：当前事实 snapshot 可读；至少一个受信任 runtime event source 可用；事件流通过认证
- 规则：使用统一 `trace_id / span_id / parent_span_id / event_id / correlation_id` 把 Skill、模型、页面、operation、BFF/API、MCP/Tool、service、表/字段和外部 source 映射到稳定事实节点/边；只有真实事件允许高亮，无法映射的事件进入 `unmapped/gap`，不自动造边
- 规则：以可稳定关联的 span/event 为最小执行颗粒度，以字段级 schema/血缘为最小数据颗粒度；每一步展示状态、开始/结束、耗时、重试/取消、输入 schema与脱敏摘要、输出 schema与脱敏摘要、读写方向、下一跳和证据，不回显 prompt正文、秘密、原始SQL参数、附件原文或越权路径
- 规则：画布提供实时高亮、暂停、继续、单步、倍速、跳转、重放；running/成功/失败/partial/unknown同时用中文、图标和线型表达；`prefers-reduced-motion` 或移动端降级为事件序列与节点高亮
- 中文解释：右侧解释区按当前高亮边回答“这一步为什么发生、经过什么模块、输入什么、输出什么、输出去哪里、是否读写数据、哪一步失败、证据在哪里”；解释只能引用已观测事实，缺证据明确说“不知道/未埋点”
- 输出：active runs、实际路径、事件序列、中文逐步解释、持续时间、失败位置、gap/unmapped/dropped/redacted计数、可复制 trace/correlation ID与历史回放
- 幂等/顺序：`source+event_id` 去重；cursor断线续传不重复动画；乱序按 sequence/observed_at重排，无法确定则标 `ordering_unknown`；重放不触发真实业务副作用
- 异常：流中断保留最后确认状态并显示 disconnected；超出版本化延迟阈值显示 delayed；finish缺失不得显示成功；某来源失败只把该段标 partial
- Human Gate：查看、暂停和重放无需 Gate；从节点发起重试、取消、修复、migration或外部写入时回到原 operation 的权限、幂等和 Gate
- 来源：USR-002、USR-008、USR-010、SYS-019、SYS-020、SYS-021、SYS-022、DES-009、DES-011

### FR-021 [P0] Planned/Fact/Runtime 漏洞与遗漏雷达

- 角色：希望发现断链、缺陷、根基问题和未考虑项的老板、Codex 与 CI
- 触发：snapshot/diff/trace生成、runtime event 无法映射、change进入验证/完成，或用户手动刷新
- 前置：至少一个静态或运行 detector 成功；detector与severity policy有版本
- 规则：比较 planned、fact、runtime 三层，P0检测 required node/edge 缺失、schema/参数漂移、REST/MCP分裂、orphan、双writer/未知owner、source freshness、migration drift、未审计mutation、未认证入口、任意tool proxy、敏感信息命中、unmapped event、计划外真实调用、必需路径未到达、缺合同/集成/Gate/失败测试
- 规则：每个 finding 必须有稳定 fingerprint、detector version、严重度、事实/建议/假设分类、证据、影响路径、可能修复位置、验证方法和历史；确定性 `observed_fact` 可以在试点后阻断，Codex `hypothesis` 只能告警，不得自动改图、改代码、关问题或作为安全证明
- 输出：按功能/SKU/层/严重度筛选的雷达、blocking/degraded/unknown计数、中文修复卡和“一键加入候选计划”入口；该入口只建 plan draft
- 幂等/解决：同 fingerprint只更新 last_seen/evidence revision；collector失败时旧问题保持 stale/open，不清零；只有同 detector成功重扫且证据消失才自动 resolved；ignore/snooze不能修改事实或绕过不可豁免门禁
- 权限/安全：detector只能运行白名单只读检查；秘密命中只显示位置和脱敏摘要；未授权用户不得读取受限路径或创建修复计划
- 异常：证据冲突显示 `conflicting_evidence`；source失败显示 partial/unknown；修复尝试失败保持 open并记录 attempt；任何自动修复在P0禁止
- 来源：USR-001、USR-009、USR-010、SYS-006、SYS-014、SYS-022、DES-006、DES-010、DES-011

## 7. 系统落点、复用与差距

| 分类 | 能力 | 现有证据 | 设计落点 | 兼容/不复用原因 |
|---|---|---|---|---|
| 复用 | Codex 路由与开发硬闸 | SYS-001 | 根 `AGENTS.md` | 保持短入口，不塞动态清单 |
| 复用 | 六态合同与 validator | SYS-002、SYS-003 | `.agents/skills/omni-feature-development/` | 扩展 snapshot/feature 字段，不另建状态机 |
| 修改 | Project Hooks | SYS-004 | `.codex/hooks.json` + `scripts/hooks/` | 从启动提醒升级为受控写入和停止检查 |
| 修改 | CI gates | SYS-005 | `.github/workflows/ci.yml`、`scripts/check_*` | 保留现有 gate，增加 graph/source/migration/test artifact |
| 拟新增 | FeatureDefinition | SYS-007、SYS-008 | `services/knowledge-engine/config/features/` + schema/build | 防止导航 registry 与 graph manifest 再成两套真源 |
| 拟新增 | System Graph | SYS-006、SYS-016 | KE schema/service/router/MCP、CLI、frontend projections | 当前没有统一图合同与 snapshot |
| 拟新增 | 候选功能接入共创 | USR-007、DES-008 | system-graph plan service/API/MCP + impact adapter | 当前只能先写合同，不能在事实图上共同做接入判断 |
| 修改/拟新增 | 运行事件与数字孪生 | SYS-019-SYS-022 | 复用 Agent WS、tool audit/client logs，新增统一 trace/span adapter、event stream 与 replay | 现有 tool_use 焊接是近似匹配，不能直接宣称端到端路径 |
| 拟新增 | 漏洞与遗漏雷达 | DES-010 | planned/fact/runtime detector、finding repository与repair card | 当前问题检查分散，缺运行偏差与事实/假设分层 |
| 拟新增 | 统一系统中台 | USR-010、DES-011 | workspace高级模式 + `components/system-command-center/*` | 只建一个中台，三种投影共用事实、解释和雷达 |
| 修改 | SKU 血缘/UI | SYS-007、SYS-016 | SKU detail + pipeline adapters | 复用现有业务实体，补 orphan/pagination/更多节点 |
| 修改 | Web/Host/Desktop 边界 | SYS-009-SYS-011 | `frontend/`、独立 Host Bridge、可选 desktop shell | 当前不能直接删 desktop，需先迁独占能力 |
| 修改 | Agent sessions/uploads | SYS-008、SYS-011 | Core Backend session/attachment API | 现有字段和路径不是 provider-neutral 真源 |
| 修改 | SKU Pipeline BFF | SYS-007 | operation registry、typed client、panel 拆分 | 43 个 route 不能继续复制维护 |
| 修改 | Migration baseline | SYS-013 | canonical ledger/reconcile/runner | 当前 blocked，必须先修历史映射 |
| 修改 | Tool 执行和指标写入 | SYS-014、SYS-015 | shared executor、metric owner/observation | 当前重复逻辑和 writer 会继续漂移 |
| 不做 | LLM 自动推断事实边或运行事件 | — | — | 不确定且不可复现，不能作为 CI 依据；Codex只做有证据的建议与中文解释 |
| 不做 | 图上直接删事实或自动修复 | — | — | 绕过代码、migration、Human Gate 和审计 |

### 影响面

| 层 | 目标模块/文件 | 动作 | 合同变化 | 测试影响 |
|---|---|---|---|---|
| Agent policy | `AGENTS.md`、`.agents/skills/omni-feature-development/` | 复用/修改 | 增加 feature/snapshot 入口说明 | policy、Skill eval、new-session smoke |
| Hooks | `.codex/hooks.json`、`scripts/hooks/*` | 修改/拟新增 | SessionStart/PreToolUse/Stop 输入输出 | Hook fixture、timeout、Windows/Linux |
| Contracts | `docs/dev-changes/*`、合同 schema/template/CLI | 修改 | before/after snapshot、feature refs、deviation | validator/transition/Git fixture |
| Feature config | `services/knowledge-engine/config/features/*` | 拟新增 | FeatureDefinition v1 | schema、duplicate、projection snapshot |
| Graph backend | `services/knowledge-engine/app/schemas/system_graph.py`、`app/services/system_graph/*` | 拟新增 | Node/Edge/Issue/Snapshot | unit/integration/property tests |
| Graph REST/MCP | router、MCP tools、doctor | 拟新增/修改 | refresh/get/search/diff/issues | OpenAPI、tool contract、doctor |
| Graph UI | workspace advanced mode、SKU detail、`components/system-graph/*` | 拟新增/修改 | typed graph API、四态、feedback | RTL/Playwright/a11y/mobile |
| Plan/解释 | `app/services/system_graph/plans*`、`components/system-command-center/*` | 拟新增 | plan revision、evidence class、用户确认、中文解释 | schema、权限、CAS、无副作用、grounding tests |
| Runtime trace | Agent WS、MCP audit、Host/KE/Scout adapters、trace repository | 修改/拟新增 | trace/span/event、cursor、redaction、mapping | event contract、reconnect、dedupe、乱序、性能 |
| Radar | graph diff/issues、runtime detector、repair cards | 拟新增/修改 | finding fingerprint、fact/recommendation/hypothesis | detector fixtures、partial source、CI negative |
| CI | `.github/workflows/ci.yml`、graph/feature checker | 修改 | artifact 与阻断码 | CI self-test、empty/existing DB |
| Host | 独立 Host Bridge、desktop main adapters | 拟新增/修改 | health/session/event/file/login | Windows smoke、single-instance、auth |
| Web Agent | session API、WS、uploads、settings | 修改 | provider-neutral session/attachment | restart/resume/auth/path traversal |
| Frontend | registry、navigation、sku-pipeline | 修改 | canonical feature/operation schema | typecheck、contract、component/e2e |
| DB | migrations、agent session、system_graph、metric ownership | 修改/拟新增 | 纯加法后兼容迁移 | preflight、empty/existing DB、rollback |
| Scout/data | ingest/runbook/catalog | 修改 | owner、observation、collision | deterministic ownership tests |
| Legacy | MCP aliases、content_studio、desktop renderer | 修改/退役 | telemetry/deprecation/bridge | usage query、restore drill |

## 8. 数据、接口、工具与 AI 契约

### 数据与血缘

| 实体/字段 | 现有或拟新增 | 类型/单位/时区/null | 唯一性/版本/关系 | 保留与迁移 |
|---|---|---|---|---|
| `FeatureDefinition` | `[拟新增][DES-002]` | YAML/JSON；schema_version、feature_id、domain、routes、capabilities、owner、lifecycle、expected_edges、checks、aliases | feature_id 与 canonical href 全局唯一；Git revision | 前端 registry/graph expectation 由 build 生成，禁止手改派生物 |
| `impact.yaml`/`completion.yaml` | `[现有][SYS-002]` 修改 | YAML；UTF-8；change_id、state、scope、feature refs、snapshot refs、edges、evidence | change_id 唯一；revision 递增；状态单向 | 兼容现有字段，新增字段先可选后必填 |
| graph snapshot | `[拟新增][DES-003]` | content hash、commit、collector versions、source results、UTC 时间 | hash 唯一；immutable；可引用 base snapshot | S3 可先文件 artifact；migration baseline ready 后落独立 schema |
| graph node/edge | `[拟新增]` | stable id、kind/type、四维状态、attrs、evidence JSON | snapshot+id 唯一；边引用 node id | 敏感值写前脱敏；不原地改历史 |
| graph issue/resolution | `[拟新增]` | fingerprint、code、severity、state、evidence、remediation、actor、UTC | snapshot+fingerprint 唯一；resolution 另表 | ignore/snooze 只改处理状态，不改事实健康 |
| integration plan/revision | `[拟新增][DES-008]` | plan_id、feature_id、base_snapshot_id/hash、intent_hash、revision、state、items、actor、UTC | active draft按feature+base+intent条件唯一；revision不可覆盖 | S5先文件artifact；确认后冻结并投影impact，历史revision保留 |
| plan decision item | `[拟新增]` | layer、target_ref、decision、evidence_class、evidence_refs、Codex建议、用户决定、expected_diff、verification、risk/gate | plan_revision+item_id唯一 | `observed_fact/recommendation/hypothesis`严格分层；敏感证据脱敏 |
| execution trace | `[拟新增][DES-009]` | trace_id、feature_id、session/change/sku refs nullable、state、started/ended UTC、root span、gap counters | trace_id唯一；原始事实不可覆盖；attempt另trace/span | 复用tool_calls/client_logs作adapter输入，不把近似历史映射改写真事实 |
| execution span/event | `[拟新增]` | span_id、parent_span_id、event_id、correlation_id、node/edge或unmapped、kind、phase、status、sequence、observed/ingested UTC、input/output schema refs、redacted summary、evidence | source+event_id唯一；span属于trace；parent可null | retention可配置；原始敏感payload不进入图谱；支持cursor重放 |
| runtime finding | `[拟新增][DES-010]` | fingerprint、detector/version、subjects、severity、classification、evidence、impact、remediation、verification、first/last seen、state | detector+code+subjects+scope稳定唯一 | collector失败时stale不resolve；假设永不自动block |
| provider session | `[拟新增兼容迁移]` | session_id、runner_provider、runner_session_id nullable、project_dir、model、effort、status、UTC | session_id 唯一；provider+runner id 条件唯一 | 读取旧 `claude_session_id` 兼容；回填核对后再弃用旧列 |
| attachment | `[拟新增兼容迁移]` | attachment_id、session_id、name、size bytes、MIME、sha256、storage key、created_at UTC | attachment_id 与 sha256 可索引 | 对账 desktop/frontend/KE 文件后切换；临时路径不作外部合同 |
| metric source owner | `[拟新增]` | metric、grain、platform、owner source、priority、effective range | 同时段同 key 只允许一个 owner | 先审计碰撞，再阻断非 owner |
| metric observation | `[拟新增]` | source、run id、raw ref、value、unit、observed_at UTC | append-only id；可追到 canonical | canonical 表保留现有 reader，确定性选择值 |

### API / MCP / 自动化

| 合同 | 现有或拟新增 | 输入 | 输出 | 错误 | 幂等/超时/重试 | 审批/审计 |
|---|---|---|---|---|---|---|
| `POST /api/v1/system-graph/refresh` | 拟新增 | scope、root refs、include_runtime、idempotency_key | 202、refresh_id、status URL | invalid_definition、collector_unavailable、rate_limited | 输入指纹复用；collector 独立 timeout/retry | 只读采集但写 snapshot，记录 actor/trigger |
| `GET /api/v1/system-graph/refreshes/{id}` | 拟新增 | refresh_id | state、source_results、snapshot_id、error | not_found | GET 幂等 | 只读审计 |
| `GET /api/v1/system-graph/snapshots/{id}/graph` | 拟新增 | root、direction、depth、cursor、filters | nodes、edges、issues、page_info | invalid_cursor、redacted | cursor 稳定 | attrs/evidence 脱敏 |
| `GET /api/v1/system-graph/search` | 拟新增 | q、view、scope、filters、cursor | 分组结果与路径 | query_too_large | 可取消旧请求 | 只读 |
| `GET /api/v1/system-graph/diff` | 拟新增 | from、to 或 change_id | 语义 diff 与 required edge status | incompatible_schema | 按 hash 缓存 | 作为 completion/CI 证据 |
| `POST /api/v1/system-graph/issues/{fingerprint}/resolve` | 拟新增 | action、reason、expiry、request id | resolution | invalid_action、conflict | request id 幂等 | 记录 actor；不能绕过 blocking事实 |
| `POST /api/v1/system-graph/integration-plans` | 拟新增 | feature/intent、base snapshot、idempotency key | draft plan、事实骨架、建议任务状态 | snapshot_partial、forbidden、invalid_intent | feature+base+intent幂等；Codex解释独立timeout | 只写计划；记录事实/建议/假设来源 |
| `PATCH /api/v1/system-graph/integration-plans/{id}` | 拟新增 | expected revision、item decisions、reason | 新revision、diff、unresolved unknown | version_conflict、stale_snapshot、forbidden | CAS；不覆盖旧revision | 老板确认锁定；不授权产品副作用 |
| `POST /api/v1/system-graph/integration-plans/{id}/confirm` | 拟新增 | revision、confirmation、request id | frozen plan、change_id、impact artifact | unresolved_unknown、invalid_edge、stale | request id幂等 | 显式用户确认；独立业务Gate仍保留 |
| `GET /api/v1/system-graph/traces/{trace_id}` | 拟新增 | trace_id、include spans、cursor、filters | trace、spans、events、gaps、page_info | not_found、forbidden、redacted | GET/cursor幂等 | 只读、字段级脱敏审计 |
| `GET /api/v1/system-graph/traces/{trace_id}/events` | 拟新增 SSE/WS | trace_id、last-event cursor、auth | ordered event stream、heartbeat、delay state | disconnected、cursor_expired、schema_error | source+event去重；可断线续传/受控轮询 | 认证、授权、retention与访问审计 |
| `GET /api/v1/system-graph/traces/{trace_id}/explain` | 拟新增 | span/edge、language=`zh-CN`、detail level | 事实骨架、中文解释、未知项、evidence refs | no_evidence、model_unavailable | 同trace/span+解释器版本缓存 | 不返回敏感原文；解释不改事实 |
| `GET /api/v1/system-graph/findings` | 拟新增 | feature/sku/trace/change、severity、classification、cursor | findings、counts、partial sources | invalid_filter、redacted | GET幂等 | 只读；精确证据授权 |
| `system_graph_refresh/get/diff/plan_feature/explain_trace/list_findings` | 拟新增 MCP | 与 REST 共用 Pydantic schema | snapshot/子图/diff/计划/解释/问题摘要 | 同 REST | 共用 service；计划确认另端点 | `@tool_with_audit`；读取无Gate，确认/副作用按原规则 |
| FeatureDefinition build/check CLI | 拟新增 | repo、definition path、mode | registry、expectation、诊断、exit code | schema/duplicate/projection error | 确定性 | CI artifact，不读取秘密 |
| Host Bridge `/health` | 拟新增 | 无或本机认证 | version、build、runner、project roots、capabilities | unavailable | 短 timeout | 不暴露秘密或任意路径 |
| Host session/event/file/login APIs | 拟新增 | 认证身份、白名单项目/文件、session payload | 状态、事件流、授权句柄 | 401/403/timeout/conflict | idempotency key、断线恢复 | 宿主动作全部审计；外部写入另走 Gate |
| canonical Tool exec | 修改 | tool name、typed args、request id | 统一 data/error/trace | not_registered、invalid_args、gate_required、timeout | request id；按 tool timeout | 共用 `@tool_with_audit` |

### AI / Prompt / RAG

V1 的图谱发现、运行事件、状态判定、diff、detector 和 CI 仍全部来自确定性扫描、受信任事件与 schema 校验，LLM 永远不是真源。Codex 只参与两处：一是基于当前 snapshot/catalog/schema 生成候选功能的接入建议，二是把选中 span/edge 的事实骨架解释成中文。

- Grounding：输入只包含授权后的 graph facts、FeatureDefinition、OpenAPI/MCP schema、source/migration/test catalog、选中 trace/span 的脱敏输入输出 schema与状态；不得让模型自由搜猜系统结构。
- 输出合同：每条内容必须标为 `observed_fact / recommendation / hypothesis`；事实引用 evidence ID，建议带验证方法，假设说明缺失证据；模型输出不能创建事实节点、运行事件、绿色状态或 blocking finding。
- Prompt 与反馈：prompt 外置并版本化；LLM调用返回 model/params/final grounded input hash/trace，接现有 `OutputFeedback` 和 prompt flywheel；不得把秘密、完整prompt、业务原文或越权证据送入模型。
- Fallback：模型不可用、超时、输出无效或 grounding不足时，接入规划仍显示确定性影响清单并允许老板人工决定；运行解释退回规则模板“模块、输入schema、输出schema、读写、状态、下一跳、证据”，雷达继续工作。
- 语言：默认 `zh-CN`，术语首次出现给中文说明并保留必要的稳定ID；不得使用笼统“系统自动处理”掩盖未知路径。

## 9. 交互、权限、安全与审计

### 入口与 UI / 对话四态

| 状态 | 用户看到什么 | 可执行动作 | 审计/反馈 |
|---|---|---|---|
| loading | 当前 snapshot 时间、正在运行的 collector 和进度；旧图标记 stale | 取消本次 refresh、继续浏览旧图 | refresh trigger、耗时、取消原因 |
| empty | 尚无 snapshot 或当前筛选无结果；区分二者 | 首次扫描、清除筛选、打开说明 | empty 原因与用户反馈 |
| error | 失败来源、是否影响事实完整性、可重试范围 | 局部重试、打开修复卡、复制证据 | error code、source、trace id |
| success | 开发图或 SKU 图、状态图例、问题数、证据抽屉 | 搜索、筛选、展开、深链、反馈 | exact snapshot/node/issue id |

### 统一系统中台布局

系统中台不是新增两个产品入口，而是 `/workspace` 高级模式中的同一工作区；SKU详情可深链到相同画布的业务投影。桌面端采用四区，移动端按同一数据折叠为大纲：

| 区域 | 开发模式 | 执行模式 | 共用能力 |
|---|---|---|---|
| 顶部上下文栏 | feature、plan revision、change、snapshot、当前阶段 | active trace、模型、session、live/delayed/replay、耗时 | 搜索、模式切换、时间/证据新鲜度、权限状态 |
| 中央思维导图 | observed事实节点 + candidate/planned虚线 + required gap | 同一事实图叠加当前/历史运行路径，高亮真实 traversed edge | 缩放、折叠、最短路径、按层/SKU/状态筛选、稳定深链 |
| 右侧中文解释器 | 根基影响、复用/修改/新增/不做、理由、风险和验证 | 当前一步的模块/Skill/模型、输入、输出、读写、下一跳、状态和证据 | 事实/建议/假设标签、复制ID、反馈、未知项 |
| 底部时间线/雷达 | plan revision、实施状态、blocking issue | event/span序列、暂停/单步/倍速/回放、失败/gap | planned/fact/runtime偏差、创建计划草稿、审计历史 |

通用前端模型采用 `nodes[] + edges[] + NodeTypeRegistry + RuntimeOverlay`。现有六层 SKU lineage 通过 adapter 归一化，保留可访问树视图作为降级；运行状态只覆盖节点/边，不触发整图重建，也不成为第二份事实。

### 图谱交互原则

- planned 使用虚线；observed/healthy 使用绿色实线；broken 红色；unknown/partial 黄色；deprecated/archived 灰色。
- running 路径使用受控流动高亮，已成功上游保留完成标记，失败停在真实节点，未发生的后续边不播放；状态同时用文字和图标表达，不只靠颜色。
- 事实节点只允许筛选、隐藏和查看，不允许在 UI 改名、删掉或手工改绿。
- 点击节点展示 owner、定义来源、代码位置、调用方/被调用方、最近验证、测试与 change；执行模式再展示当前span、输入/输出schema与脱敏摘要、读写对象、耗时、重试和下一跳。
- 点击断边展示六项修复卡；“创建修复任务”在 P1 只生成 impact 草稿。
- 点击运行边时右侧用中文逐步解释；用户可继续追问，回答必须引用当前 snapshot/trace evidence，缺证据直说“未观测/未埋点”。
- 画布支持播放、暂停、单步、0.5x/1x/2x、跳转和回放；动画只是 event log 的投影，不决定状态。开启 `prefers-reduced-motion` 时使用静态高亮和 `aria-live` 事件列表。
- 全键盘可展开、选择和打开抽屉；提供 `aria-expanded/selected/current` 与焦点环。桌面与移动端共用数据；移动端使用大纲/树视图，不强制完整自由画布。

### 权限与敏感数据

- 图谱读取按现有本地老板环境授权；未来多用户时按 feature/domain 限制。
- collector 禁止读取 `.env`、cookie、token、口令、附件内容和不相关用户目录；只收集 schema、路径、哈希和脱敏元数据。
- Host Bridge 默认绑定本机或明确 Tailnet；HTTP/WS 要求短期、最小范围的认证；项目根、命令、文件根使用白名单。
- 浏览器不得传任意绝对路径、任意 shell 命令或绕过 project root；路径穿越和 symlink 越界必须拒绝。
- 通知不等于授权。任何发布、删除、migration、外部平台写入或凭证旋转仍需独立 Human Gate。

### Human Gate 与审计

- graph refresh、search、diff 是只读采集，不需要 Human Gate，但必须审计 trigger、scope、source result 和耗时。
- 创建/编辑候选计划草稿不需要业务 Gate；从 draft 锁定为 impact 必须由老板显式确认，但这只授权进入实施流程，不替代 migration、删除、发布、凭证或外部写入各自的 Gate。
- 查看、暂停、单步和回放 trace 不需要 Gate；从运行节点发起重试/取消/修复仍调用原 operation，不得借动画绕过权限、幂等和 Gate。
- issue ignore/snooze 需要 actor、理由、到期时间；不能改变 CI 对 blocking事实的判断，除非按受控 policy 明确接受有期限例外。
- 物理删除客户端代码、历史表、用户文件或兼容入口必须单独请求确认，列出精确目标、备份、调用 telemetry、回滚和不可逆项。
- 每次 Codex 执行完成必须用人话汇报：改了哪条链、关键结果、测试/图谱证据、产物路径和剩余事项。

## 10. 异常、兼容、发布与回滚

### 异常矩阵

| 场景 | 预期行为 | 是否写入/副作用 | 重试/补偿 | 用户提示 |
|---|---|---|---|---|
| 空数据 | 说明是无 snapshot、无匹配结果还是业务确实无记录 | 可写 empty refresh 结果，不造节点 | 首次 scan 或清筛选 | “当前无快照”与“筛选无结果”分开 |
| 无权限 | 拒绝 Hook bypass、Host 调用、文件读取或受保护定义修改 | 只写安全审计 | 获得授权后重试 | 不回显敏感路径和 token |
| 依赖超时/失败 | 对应 collector 标 partial/unknown，保留其他来源和旧事实 | 写 source result，不写 removed | 指数退避或局部重试 | 明确哪一层未验证，不能声称全绿 |
| 重复提交 | refresh、resolution、Host session、Tool exec按 idempotency key复用 | 不重复创建 snapshot/副作用 | 返回已有结果 | 显示复用的 request/change id |
| 部分失败 | 成功来源可浏览，失败来源不能参与删除或健康判定 | snapshot 标 partial | 修复后生成新 snapshot | 列出成功/失败来源和影响范围 |
| 候选计划依赖 stale/partial snapshot | 草稿可保存，相关项标 unknown/stale；禁止锁定impact | 只写新plan revision | refresh/rebase后重新确认 | 列出变动事实和待确认项 |
| Codex接入建议或中文解释失败 | 保留确定性事实表/规则模板，不丢计划或trace | 不写事实、不自动决定 | 允许重试模型或人工决定 | 明确“解释不可用”，不能隐藏链路 |
| runtime事件重复/乱序 | 按source+event去重并按sequence重排；无法确定标ordering_unknown | 只追加事件事实，不重复业务副作用 | 从cursor重放或刷新trace | 不重复动画，不伪造顺序 |
| runtime事件流断开 | 保留最后确认状态，显示disconnected/delayed | 不补成功、不清空已证实路径 | last-event cursor续传；必要时受控轮询 | 显示最新观测时间和未覆盖窗口 |
| span无法映射/finish丢失 | 进入gap/unmapped与雷达，不自动造节点/边或成功终态 | 写脱敏finding/evidence | 补埋点或关联后产生新映射revision | 中文说明“未观测”，列修复位置 |
| 计划路径与实际路径偏离 | 保留两层并高亮deviation；确定性越界生成issue | 不反向改plan/fact | 创建plan change或修代码后重验 | 展示计划、实际和影响差异 |
| 敏感payload或越权事件 | 隔离/脱敏并拒绝显示 | 写安全审计，不写原始秘密 | 修正producer/权限后重试 | 只显示规则、位置和脱敏摘要 |
| 合同外写入 | PreToolUse 阻断 | 不修改目标文件 | 先更新 impact revision | 展示缺少的 scope/edge/test |
| 静态 required edge 缺失 | Stop 与 CI 阻断 `COMPLETE` | 写 issue/completion失败证据 | 修复后重新 scan/test | 展示修复卡 |
| migration baseline blocked | 禁止新增生产实体 | 不执行 migration | 完成 canonical mapping 后重试 | 展示具体 ledger blocker |
| Host 离线 | Web 业务页面可用，宿主功能禁用 | 不创建假任务 | 恢复 Host 后重试 | “宿主服务未连接” |
| 旧入口仍有流量 | 停止退役 | 只记 telemetry | 延长兼容并迁移调用方 | 展示调用来源与最后使用时间 |

### 兼容、migration 与历史数据

- S0 保留当前 dirty worktree，使用 path-scoped commit/归档；不清理用户未提交文件。
- 091/092 已执行 migration 不重命名、不改 SQL；通过 canonical mapping、原始文件与 checksum 收敛 runtime ledger。
- system_graph、provider session、attachment、metric owner/observation 均采用纯加法 migration；读取先兼容旧字段/表，验证后再停止旧写入。
- `FeatureDefinition` v1 带 schema version；生成器可读取前一版本并给迁移诊断。
- 旧 BFF URL、MCP URL、7777 和 content_studio 在兼容期保留薄适配/只读；新功能不得继续写旧链。
- 历史 snapshot 和完成合同不可倒改；修复使用新 change 与新 snapshot。

### 灰度、发布与回滚

1. Hooks：advisory → warning → selected issue codes block → 全部确定性 P0 code block。
2. Graph：先 CLI/file artifact → API/DB snapshot → 工作台开发图 → SKU 业务图。
3. Plan：先确定性影响表 + 人工确认 → Codex有证据建议 → stale/rebase与计划深链；始终不自动施工。
4. Runtime：先execution/trace关联与append-only事件 → 单样板路径高亮 → 断线续传/回放 → 中文解释与雷达；未建立可靠关联前不开放“完整链路”宣传。
5. CI：先上传 artifact不阻断 → 单样板 feature阻断 → 新变更阻断 → 全仓基线逐步治理。
6. Host/Web：Desktop 与 Host Bridge 双运行 → 企业微信/续跑/上传切换 → 14 天观察 → 可选薄壳或退役。
7. Backend：shared executor/owner shadow mode → 新调用切 canonical → 旧 URL/非 owner写入告警 → block → 退役。

每一阶段保留 feature flag、旧入口和恢复脚本。出现误阻断、数据对账失败、Host smoke失败、活跃旧流量或 migration不一致时回滚到上一阶段；不可通过删除历史或忽略 unknown 来制造“通过”。

## 11. 可观测性与成功指标

| 信号 | 类型 | 采集位置 | 口径/维度 | 告警或判定 | 验证方式 |
|---|---|---|---|---|---|
| `fde_contract_coverage` | metric/CI | feature-contract checker | protected paths、change、feature | block 阶段必须全覆盖 | CI artifact |
| `hook_decision_total` | audit | Hook runner | event、decision、rule、path | 统计误报与绕行尝试 | 本地日志 fixture |
| `graph_refresh_total` | metric/audit | graph service | status、scope、trigger | failed/partial 分布先建基线 | API/SQL |
| `graph_collector_duration` | metric | collector | source、result | 先实测再配置 timeout | log/test |
| `graph_issue_open` | metric | issue repository | code、severity、feature | `COMPLETE` 前 blocking=0 | snapshot/CI |
| `graph_snapshot_age` | metric/UI | latest snapshot | scope/source | UI必须显示 stale/unknown | UI/API |
| `planned_to_fact` | audit | diff service | change、node/edge、evidence | 无证据不得转绿 | completion artifact |
| `integration_plan_item_total` | audit/metric | plan service | decision、classification、layer、confirmed | 关键unknown未清不得锁定 | plan artifact/API |
| `integration_plan_side_effect_before_confirm` | safety metric | Hook/plan service | plan、actor、target | 必须为0 | negative E2E/audit |
| `runtime_trace_span_total` | metric | trace repository | source、kind、status、mapped | 分层建立埋点基线 | SQL/event fixture |
| `runtime_trace_gap_total` | metric/radar | mapping/detector | source、node kind、reason | 所有未映射事件必须显式计数 | trace/finding query |
| `runtime_event_lag_ms` | histogram/UI | event ingest→render | source、mode、P50/P95 | 先实测后版本化SLO；超阈显示delayed | integration/perf test |
| `runtime_event_sequence_gap` | audit | event reducer/repository | trace、source、expected/actual seq | 非零触发续传或partial | reconnect fixture |
| `runtime_path_deviation` | finding | planned/fact/runtime detector | feature/change/trace、severity | 确定性计划外关键调用进入issue | detector E2E |
| `trace_explanation_grounding` | audit/feedback | 中文解释器 | span、evidence refs、classification、fallback | 无证据句不得作为fact输出 | schema/grounding eval |
| `runtime_finding_open` | metric | radar | detector、severity、classification、feature | COMPLETE前确定性blocking=0；hypothesis只告警 | finding API/CI |
| `feature_definition_drift` | CI | definition builder | duplicate/missing projection | 非零阻断 | schema/projection test |
| `migration_baseline_status` | gate | baseline service | blocker code | 新生产实体要求 ready | MCP/API/CI |
| `metric_write_collision` | audit | owner gate | metric/grain/platform/source | 成功的非 owner写入为0 | SQL/test |
| `legacy_entry_usage` | telemetry | aliases/desktop/Host | caller、feature、version | 退出观察期要求零独占调用 | dashboard/query |
| `agent_resume_smoke` | test | Web/Host/DB | provider、entry、restart | 每次相关发布通过 | integration smoke |
| `output_feedback` | feedback | graph UI/任务汇报 | snapshot/node/issue/tool call | 进入现有反馈飞轮 | exact id查询 |

实施完成后，Codex 必须输出一张完成卡：change_id、feature_id、状态、changed paths、tests/exit codes、before/after snapshot、required edge summary、accepted unknowns、运行trace/gap摘要、雷达finding、rollback 和产物链接。

## 12. 验收标准

### AC-FR001-01

- Given：治理资产已经提交，项目被标记为受信任
- When：从 Omni 根目录新建一个 Codex 任务并直接要求开发跨层功能
- Then：任务自动路由到实施 Skill，并在产品写入前创建/继续 change contract
- And：启动记录包含 repo root、AGENTS/Skill/Hook版本；无需用户重复输入流程提示词
- Evidence：新任务 transcript + SessionStart log + Git tracked files

### AC-FR002-01

- Given：一个 change 处于 `DISCOVERED` 且 impact 缺 required edge或测试
- When：请求进入 `IMPLEMENTING`
- Then：validator 拒绝状态推进
- And：目标产品文件保持未修改，错误指向具体缺失字段
- Evidence：contract unit test + Git diff fixture

### AC-FR003-01

- Given：change 已锁定，但准备写入一个未列入 impact 的关键 API 文件
- When：PreToolUse 收到该写入
- Then：Hook 阻断并要求先更新 impact
- And：记录 change_id、目标路径和匹配规则；更新合同后同一写入可通过
- Evidence：Windows/Linux Hook fixture + audit log

### AC-FR004-01

- Given：两个 FeatureDefinition 使用相同 feature_id或 canonical href
- When：运行 definition build/check
- Then：生成失败且返回冲突位置
- And：sidebar、首页、引导和 graph expectation 均不更新
- Evidence：schema/unit test + generated artifact hash

### AC-FR005-01

- Given：样板功能具有页面、BFF、MCP、service、table/source和测试
- When：对同一 commit与 definition revision连续扫描两次
- Then：两次 snapshot content hash与稳定 node/edge ID一致
- And：每个事实节点均可打开源码/OpenAPI/catalog/migration/test证据
- Evidence：collector fixture + snapshot diff = empty

### AC-FR005-02

- Given：运行时 collector 超时，但静态 collector成功
- When：生成 snapshot
- Then：snapshot状态为 partial，相应运行时证据为 unknown
- And：不产生 removed节点，不丢失静态事实，允许局部重试
- Evidence：timeout integration test + snapshot JSON

### AC-FR006-01

- Given：impact 声明新增页面→BFF→Tool→service→table required chain
- When：开发前查看图谱并在开发后完成扫描
- Then：开发前显示虚线 planned链；完成后只有实际链与检查全部存在的部分转为绿色事实
- And：任一 missing edge保留虚线/红色断点并阻止 completion
- Evidence：before/after UI截图 + graph diff + completion validator

### AC-FR007-01

- Given：前端参数类型与 OpenAPI/MCP schema不一致
- When：scanner生成 issue
- Then：issue标明观察值、期望值、调用方、影响、证据、建议文件和验证命令
- And：相同 fingerprint重复扫描不创建重复问题
- Evidence：issue fixture + API response + dedupe test

### AC-FR008-01

- Given：PR包含受保护代码、有效合同，但仍缺一个 required MCP registration或 migration
- When：运行 CI
- Then：对应 gate失败且不能合并
- And：artifact包含失败 edge、证据、检查命令和退出码；不得只返回笼统红叉
- Evidence：CI self-test fixture + uploaded artifact

### AC-FR009-01

- Given：latest snapshot包含 healthy、broken、unknown、deprecated与planned元素
- When：老板打开工作台高级模式和某 SKU详情
- Then：两个投影视图读取同一 snapshot并按统一图例显示
- And：loading/empty/error/success、搜索、分页、orphan、证据抽屉与反馈入口均可操作
- Evidence：RTL + Playwright + mobile/a11y screenshot

### AC-FR010-01

- Given：Electron 完全关闭，Host Bridge与Web/Core Backend运行
- When：从Web发起 Codex任务、文件授权或平台登录
- Then：业务 UI不依赖 Electron，宿主动作由 Host Bridge完成
- And：启动第二个 Host实例不会产生端口冲突；Host离线时Web显示明确降级
- Evidence：Windows deployment smoke + single-instance test + health response

### AC-FR011-01

- Given：用户从Web创建 Codex会话并上传附件
- When：Host与Web进程重启后从企业微信或Web继续该会话
- Then：使用相同真实 runner_session_id、project_dir、model/effort和历史
- And：附件SHA-256一致、可重新下载；无 token、越界路径和 placeholder resume均被拒绝并审计
- Evidence：双入口重启集成测试 + attachment checksum + security tests

### AC-FR012-01

- Given：一个 SKU Pipeline operation在唯一 registry中定义 typed input与 MCP tool
- When：UI调用该 operation并修改一个字段类型
- Then：页面→BFF→Tool映射一一对应，类型漂移在CI阶段失败
- And：旧URL alias继续可用并记录流量，未注册任意tool请求被拒绝
- Evidence：registry contract test + typecheck + one-step E2E

### AC-FR013-01

- Given：当前运行 ledger存在091/092双前缀和runtime-only记录
- When：S0完成 canonical reconciliation并分别验证空库与存量库
- Then：baseline返回`ready`且生产实体变更允许
- And：已执行文件名、SQL与checksum未被重写，回滚/兼容证据已保存
- Evidence：preflight JSON + empty/existing DB CI + ledger diff

### AC-FR014-01

- Given：前端URL与企业微信URL分别调用同一个注册Tool
- When：传入相同合法和非法参数
- Then：两者经过同一 executor并返回等价的成功/错误合同
- And：审计、timeout与Gate行为一致；旧URL流量被记录
- Evidence：dispatcher parity test + audit query

### AC-FR014-02

- Given：非 owner writer尝试更新某 canonical metric
- When：写入请求到达 ownership gate
- Then：canonical值不被覆盖
- And：原始 observation和collision包含source/run/metric/grain/platform并可追溯
- Evidence：DB integration test + collision audit query

### AC-FR015-01

- Given：某旧客户端能力或alias已标记 deprecated
- When：仍存在活跃调用、历史ID无法映射或附件对账失败
- Then：退役流程停止，不删除代码、表、安装包或用户数据
- And：退出报告列明阻塞调用、替代路径和下一次复核条件
- Evidence：telemetry query + deletion gate test + restore drill

### AC-FR016-01

- Given：选择一个真实小功能并启用 warning模式
- When：从需求开始完成一次合同、planned graph、实施、Hook、scan、CI和修复
- Then：无需额外流程提示即可完成，最终 required edges为present且转绿
- And：误报与漏报有清单；只有验证过的issue code被升级为block
- Evidence：完整 change目录 + before/after snapshot + CI run + session transcript

### AC-FR017-01

- Given：老板打开某 blocking issue并创建修复任务
- When：编辑 planned layer并保存
- Then：只生成新revision和impact草稿，不修改事实节点或产品代码
- And：并发版本冲突可见且支持撤销/重做
- Evidence：permission/concurrency/E2E test

### AC-FR018-01

- Given：业务UI和Host Bridge已经完成迁移
- When：选择保留薄Electron壳或仅使用PWA
- Then：两种入口都加载同一Web业务页面和统一设置
- And：薄壳不含第二套Chat/BI/runner；PWA离线时不把宿主功能显示为可用
- Evidence：bundle scan + PWA/offline test + settings contract test

### AC-FR019-01

- Given：一个候选功能已有页面和MCP Tool，但缺BFF、数据writer和端到端测试
- When：老板在系统中台安放候选功能，Codex读取当前snapshot生成逐层影响判断，老板逐项确认
- Then：已存在页面/Tool标`observed_fact+reuse`，缺失BFF/writer/test标planned `add`，每项带证据、风险和验证
- And：确认前产品文件、数据库和外部系统零写入；确认后生成frozen plan revision、impact与expected graph diff
- Evidence：plan schema/API test + graph fixture + audit + impact validator

### AC-FR019-02

- Given：数据源collector不可用、base snapshot已变化，且Codex怀疑可复用一个同名接口
- When：创建或重新打开候选计划
- Then：数据源显示partial/unknown，计划显示stale并要求rebase；同名接口只能标hypothesis，不能自动reuse
- And：关键unknown未补证据且老板未重新确认前不得进入`IMPACT_LOCKED`；Codex不可用时仍显示确定性影响表
- Evidence：partial/stale fixture + classification/transition negative test + fallback test

### AC-FR020-01

- Given：一次任务真实经过Skill→模型→Web operation→BFF→MCP Tool→service→数据库writer，并产生统一trace/span事件
- When：老板打开执行模式并运行任务
- Then：同一思维导图按真实sequence高亮对应节点/边；点击每一步可见中文说明、输入/输出schema与脱敏摘要、读写、耗时、下一跳和evidence
- And：任务结束后用同一immutable event log回放得到相同顺序/终态，runtime overlay前后snapshot hash不变
- Evidence：event contract + SSE/WS E2E + trace replay hash + UI/a11y截图

### AC-FR020-02

- Given：事件流断线后重复并乱序重发，外部source超时，且中间一个span无法映射
- When：客户端从last cursor恢复并继续播放
- Then：重复事件不重复动画，能确定的事件按sequence归位；已成功上游保留，动画停在真实失败节点，后续未执行边不高亮
- And：无法映射段显示gap/unmapped和`ordering_unknown`/delayed，不补画；reduced-motion模式使用静态高亮与事件列表
- Evidence：reconnect/dedupe/out-of-order fixture + timeout UI test + reduced-motion test

### AC-FR021-01

- Given：fixture同时包含缺required BFF edge、REST/MCP分裂、双writer、缺失败测试、未认证入口和计划外runtime调用
- When：雷达比较planned、fact与runtime
- Then：生成稳定可去重的finding；每项包含分类、证据、影响路径、修复位置、中文说明和验证方法
- And：allowlist内确定性问题可阻断，Codex hypothesis只告警；任何finding都不自动改代码、migration、图事实或外部系统
- Evidence：detector fixtures + finding schema + CI negative + snapshot hash

### AC-FR021-02

- Given：上次存在open finding，本次对应collector超时，另有敏感payload与未授权查看请求
- When：刷新雷达并访问详情
- Then：旧finding保持open/stale，来源标partial，不产生“全部正常”或假resolved；敏感值在API/UI/log均不可见
- And：未授权用户不能读受限证据或创建计划；collector恢复并成功证明缺口消失后才能自动resolved
- Evidence：two-snapshot resolution test + permission negative + redaction scan + audit query

### 需求—验收追踪

| FR | 优先级 | AC | 正常/失败 | 自动化层级 |
|---|---|---|---|---|
| FR-001 | P0 | AC-FR001-01 | 正常+加载失败 | integration/new-session |
| FR-002 | P0 | AC-FR002-01 | 失败 | unit/Git fixture |
| FR-003 | P0 | AC-FR003-01 | 正常+越界 | Hook integration |
| FR-004 | P0 | AC-FR004-01 | 重复/部分生成 | unit/contract |
| FR-005 | P0 | AC-FR005-01、02 | 正常+超时/部分失败 | collector/integration |
| FR-006 | P0 | AC-FR006-01 | 正常+断链 | integration/E2E |
| FR-007 | P0 | AC-FR007-01 | schema漂移+重复 | unit/API |
| FR-008 | P0 | AC-FR008-01 | 阻断/环境失败 | CI self-test |
| FR-009 | P0 | AC-FR009-01 | 四态+分页/orphan | RTL/Playwright/a11y |
| FR-010 | P0 | AC-FR010-01 | Host正常/离线/重复实例 | Windows smoke |
| FR-011 | P0 | AC-FR011-01 | 重启恢复+无权限 | integration/security |
| FR-012 | P0 | AC-FR012-01 | 正常+类型/未注册 | type/contract/E2E |
| FR-013 | P0 | AC-FR013-01 | 账本阻断→ready | DB integration/CI |
| FR-014 | P0 | AC-FR014-01、02 | dispatcher parity+writer冲突 | API/DB integration |
| FR-015 | P0 | AC-FR015-01 | 活跃调用/对账失败 | telemetry/restore |
| FR-016 | P0 | AC-FR016-01 | 全流程试点 | E2E/CI/session |
| FR-017 | P1 | AC-FR017-01 | 正常+并发/权限 | E2E |
| FR-018 | P1 | AC-FR018-01 | 两种部署+离线 | bundle/PWA/integration |
| FR-019 | P0 | AC-FR019-01、02 | 正常+partial/stale/模型失败 | schema/API/E2E |
| FR-020 | P0 | AC-FR020-01、02 | 实时+断线/乱序/gap/无障碍 | event/replay/Playwright |
| FR-021 | P0 | AC-FR021-01、02 | 多类漏洞+partial/权限/脱敏 | detector/CI/security |

## 13. 实施切片

| Slice | 可独立验收的结果 | 依赖 | 目标模块/文件 | 主要任务 | 测试 | Done 条件 |
|---|---|---|---|---|---|---|
| S0 安全与基线收口 | 后续可安全施工且不丢现有改动 | 无 | 两仓Git状态、migrations、敏感脚本、CI DB | 路径级归档/提交治理资产；修091/092 canonical ledger；清理并旋转已跟踪凭证；明确migration唯一真源 | secret scan、preflight、空库/存量库、restore | baseline ready，dirty改动有归属，生产实体解锁 |
| S1 治理底座入库 | 新Codex任务自动进入合同流程 | S0 | `AGENTS.md`、两类Skill、合同CLI/模板/tests、现有CI | 提交资产；修复PRD validator稳定入口；固定cwd；验证指令大小/编码/skill引用；扩展合同feature/snapshot字段兼容；登记required checks | policy 16项、合同44项、命令存在性、新任务smoke | 不重复提示也先建合同，所有资产tracked且文档命令可执行 |
| S2 本地过程闸门 | 合同外写入和无证据停止被本地识别 | S1 | `.codex/hooks.json`、Hook runner/fixtures | 增加PreToolUse/Stop；path分类；timeout/unknown策略；warning日志 | Windows/Linux Hook fixture、失败注入 | 越界写入先更新合同；Hook失败不静默 |
| S3 FeatureDefinition与静态图核心 | 一个样板feature可生成稳定事实图 | S0-S2 | config/schema/build、graph model/collectors/CLI | 统一功能定义；采集route/OpenAPI/MCP/service/migration/source/test；文件snapshot与diff | schema、collector、determinism、redaction | 两次扫描hash稳定，证据可打开 |
| S4 Planned/fact、Issue与CI warning | 计划虚线、断链修复卡和CI artifact跑通 | S3 | dev contract、diff/issues、CI jobs | impact转planned；required edge判定；repair card；上传artifact；全量测试bootstrap | Git fixtures、OpenAPI/doctor/migration/source、CI self-test | 样板缺边能定位且CI清楚报告，不误删unknown |
| S5 候选功能接入共创 | 老板可先安放功能并与Codex证据化决定接法 | S3-S4 | plan schema/service/API/MCP、impact adapter、中台开发模式 | plan revision；reuse/modify/add/not_do/unknown；事实/建议/假设；用户确认；stale/rebase；零副作用 | schema、CAS、权限、partial、模型fallback、impact projection | 关键unknown未清不锁定；确认前产品零写入；确认后合同可执行 |
| S6 真实小功能试点与block校准 | 默认开发流程完整闭环并确定block规则 | S5 | 一个真实纵向feature及其change目录 | 从候选计划开始warning试跑；修误报/漏报；issue allowlist；Stop/CI selected block | 完整E2E、session transcript、rollback | 无额外提示完成；确定性断链无法COMPLETE |
| S7 图谱API与统一系统中台静态面 | 同一中台可查看开发/业务图和中文证据 | S0、S3-S6 | graph migration/repository/router/MCP、GraphModel/NodeRegistry、workspace/SKU UI | baseline ready后落DB；REST/MCP；通用nodes/edges；现有lineage adapter；思维导图/可访问树/解释抽屉/雷达静态面 | migration、router、doctor、normalizer、RTL/Playwright/a11y | planned/healthy/broken/unknown/deprecated正确显示；新增节点无需改画布核心 |
| S8 运行追踪事件脊柱 | 每轮任务具备可续传、可关联、可回放的真实事件 | S0-S3 | Agent WS/runner、MCP audit ContextVar、Host/KE/Scout middleware、trace repository | 生成execution/trace；规范化tool identity；span父子；append-only event；HTTP/WS传播；session/gate归属；脱敏/retention；cursor | event contract、DB、propagation、dedupe、乱序、reconnect、security | tool/audit不再近似焊接；页面→source已埋点段可确定性关联，gap可计数 |
| S9 执行微动画、中文解释与三层雷达 | 老板可实时看懂路径并发现缺陷 | S7-S8 | RuntimeOverlay/event reducer、Playback、explain service、detectors/findings | 实时/延迟/回放；线路高亮；span/字段级解释；reduced motion；planned/fact/runtime比较；一键建plan draft | event-to-UI E2E、replay、grounding、detector、perf/a11y、redaction | 动画与trace一致；缺段不补画；确定性/建议分层；中台不产生第二真源 |
| S10 Host Bridge与Agent合同 | 关闭Electron后Web/企微仍能执行并恢复 | S0-S2、S8 | Host service、Web/KE session/auth/upload、desktop adapters | 单实例Host；provider session；auth；统一附件；企微/续跑/扫码切换；接统一trace | Windows smoke、restart/resume、security、checksum、trace continuity | Web/企微可执行，cwd/历史/附件/trace一致，Electron仍可回退 |
| S11 前端收敛 | 入口同源，SKU Pipeline可分步维护 | S3、S7、S10 | Feature registry projections、导航、chat语义、sku-pipeline | 一级入口收敛；chat/RAG分义；typed operation；model/api/hooks/panels拆分；旧URL alias | registry、typecheck、component、one-step E2E | 新功能只改一套UI；operation一一对应 |
| S12 后端单真源 | executor、metric、旧/新链边界明确 | S0、S3-S6、S8 | MCP routers/audit、Scout ingest/runbook、pipeline/content_studio bridges | shared executor；canonical URL；owner/observation/collision；旧链只读映射；trace context共用 | parity、collision、doctor、lineage/trace regression | 非owner不覆盖，新调用只走canonical，新功能只写pipeline |
| S13 兼容面与客户端退役 | 每项旧能力可独立安全退出 | S7-S12 | aliases、desktop renderer/installer、旧服务/表 | telemetry；deprecation；14天观察；数据/附件/设置对账；恢复演练；按独立合同归档/删除 | usage query、exit smoke、restore drill | 无独占调用和回退；Host全绿；删除目标精确可恢复 |
| S14 全仓推广 | 新跨层功能默认受完整FDE与运行观测保护 | S6-S13 | CI policy、docs、templates、onboarding、trace coverage | selected block扩大到全部确定性P0 code；清理临时warning；生成图谱/trace/finding健康基线 | regression、full CI、sample changes、trace replay | 静态断链不能合并或完成；运行盲区显式；图谱持续更新 |

### 推荐顺序

1. 先做 S0：当前 migration baseline仍阻断，治理资产也未全部入Git；这一步之前不应新增图谱表或删除客户端。
2. 完成 S1-S2：让“必须建合同、越界先补合同、结束必须验证”真正自动执行。
3. 完成 S3-S6：先有确定性事实图、候选功能共创和一条真实试点，再把门禁从 warning升级block。
4. 完成 S7：在已有真实图合同上做统一系统中台静态面，而不是先画一张手工图。
5. 完成 S8：先修 `execution/trace/span/event` 和现有零关联问题；这一步以前不宣称完整运行数字孪生。
6. 完成 S9：再用真实事件做微动画、中文解释和planned/fact/runtime雷达。
7. 完成 S10：迁出客户端独占能力，并让Web/企业微信/Host共用session、附件和trace。
8. 完成 S11-S12：借助图谱与运行证据整理前端和后端，避免盲删和重复造轮子。
9. 完成 S13-S14：满足退出门槛后退役旧客户端/alias，并把FDE、运行观测和雷达推广到所有新功能。

## 14. 风险、假设、待决策与 Definition of Ready

### 风险

| ID | 风险 | 概率/影响（定性） | 缓解 | 触发回滚条件 |
|---|---|---|---|---|
| RSK-001 | 图谱变成第二份手工文档 | 中/高 | FeatureDefinition只写期望；事实必须scanner生成；派生物不可手改 | 出现同feature多真源或手工健康状态 |
| RSK-002 | Hook误阻断影响开发 | 中/中 | warning试点、按issue code升级、CI最终兜底、明确unknown | 正常写入频繁被错误阻止 |
| RSK-003 | collector漏边或把超时当删除 | 中/高 | 证据置信度、partial/unknown、删除需before/after成功来源 | 运行时不可用导致大量removed |
| RSK-004 | migration历史被重写 | 中/高 | S0保留文件名/SQL/checksum，做canonical mapping与双环境验证 | checksum变化或存量库升级失败 |
| RSK-005 | Host Bridge扩大远程执行面 | 中/高 | 先认证、最小绑定、项目/命令/文件白名单，再挂workspace | 未认证WS/API可触发宿主动作 |
| RSK-006 | 大规模前端拆分引入行为回归 | 中/高 | 按纵向step迁移、旧URL alias、typed contract、E2E | 核心Pipeline步骤无法完成或历史入口404 |
| RSK-007 | 旧客户端或旧链仍有隐藏调用 | 高/高 | telemetry、14天观察、ID桥接、恢复演练，最后物理删除 | 发现活跃独占调用或无法对账数据 |
| RSK-008 | metric owner切换丢数据 | 中/高 | append-only observation先行、shadow comparison、canonical reader兼容 | canonical值与双写观察不一致 |
| RSK-009 | dirty worktree误纳入或覆盖他人改动 | 高/高 | path-scoped合同、禁止清理无关文件、S0归属清单 | diff出现合同外用户文件 |
| RSK-010 | CI因外部依赖抖动频繁红 | 中/中 | 静态block与runtime unknown分层；外部探针不判missing | 外部服务波动阻断无关PR |
| RSK-011 | 先做动画后补关联，产生“看起来完整”的假链路 | 高/高 | S8先建立统一execution/trace/span/event；unmapped/gap显式；动画只消费事实事件 | UI出现无event/evidence的高亮边 |
| RSK-012 | 细粒度trace泄露prompt、SQL、附件、秘密或个人数据 | 中/高 | schema/字段名+脱敏摘要；producer与API双重redaction；retention/权限审计 | API/UI/log出现禁止字段或原始秘密 |
| RSK-013 | 埋点开销、事件基数或动画重排影响任务性能 | 中/中 | 只记录稳定业务span；append-only批写；状态覆盖不重排全图；先基线后SLO | 任务延迟/资源使用超版本化预算 |
| RSK-014 | Codex把同名接口当可复用或过度建议新接口/表 | 中/高 | facts/recommendation/hypothesis分层；每项证据与验证；老板逐项确认；零副作用计划 | 未确认建议进入impact或真实变更 |
| RSK-015 | 局部未埋点导致雷达漏报或错误宣称无漏洞 | 高/高 | trace coverage/gap计数；partial来源不清零；明确“不等于渗透测试/业务正确性” | 存在gap却显示“全链路正常” |

### 假设

| ID | 假设 | 采用原因 | 影响 | 验证 | 回退 |
|---|---|---|---|---|---|
| ASM-001 | Web是唯一业务前端，Host Bridge保留宿主能力 | 当前业务UI已向Web集中，但宿主能力未迁 | 决定客户端目标形态 | S7真实部署smoke | 保留Electron薄壳，不恢复第二套业务UI |
| ASM-002 | FeatureDefinition放Git并由生成器投影最稳妥 | 功能入口和期望链均需版本审查 | 新增schema/build流程 | S3重复/投影测试 | 保持schema，替换存储adapter |
| ASM-003 | 静态链路可作为首批blocking，运行时失败先unknown | 可降低误报并保持CI确定性 | 分阶段上线 | S5误报基线 | 回退warning，不删除规则证据 |
| ASM-004 | 14天零独占调用足以进入客户端退役评审 | 覆盖日常与周节奏，且可逆 | 推迟物理删除 | S10 telemetry与恢复演练 | 延长观察，不强删 |
| ASM-005 | 图谱UI嵌工作台/SKU详情优于新增一级菜单 | 用户要求整理前端并减少入口 | 影响信息架构 | S7可用性验收 | 保留内部深链接，调整入口不改API |
| ASM-006 | 一个统一系统中台用模式切换优于开发/执行两个产品 | 用户要求两者结合且需要同一事实背景 | 共享GraphModel、证据与雷达 | S7-S9跨模式可用性/E2E | 保留同路由下独立tab，不拆数据真源 |
| ASM-007 | OpenTelemetry兼容trace语义可渐进落地，不必首日引入完整平台 | 现有audit/WS/run_id可做adapter，先解决关联真值 | 新增traceparent或Omni headers与append-only事件 | S8跨服务propagation fixture | 保持语义/ID合同，替换具体collector/存储 |
| ASM-008 | “实时”应由实测后版本化延迟SLO定义 | 当前无统一事件基线，直接承诺毫秒值会编造 | UI必须显示live/delayed和最新观测时间 | S8-S9 perf基线与用户验收 | 降级受控轮询并明确delayed |
| ASM-009 | 最小安全颗粒度是span/event与字段级schema/血缘，不是原始值全文 | 既要解释细节又不能泄露秘密/个人数据 | 输入输出默认摘要与证据引用 | S8 redaction/授权测试 | 受限节点只显示存在性与脱敏占位 |

### 待决策

#### 阻塞开工

- 无。推荐架构、先后顺序、安全边界和V1非目标已经明确；S0可以直接建立实施合同。

#### 不阻塞开工

- 图画布库选择可在 S7 前通过小型技术 spike 决定；Node/Edge/API合同不依赖具体库，现有lineage树保留为可访问降级。
- Electron 最终完全卸载还是保留托盘薄壳，在 S13 观察数据出来后决定；不影响 S0-S12。
- 一级导航最终中文命名可在 S11 可用性评审中调整；canonical feature_id和route保持稳定。

### Definition of Ready

- [x] 使用者、现场问题、失败成本和目标结果明确
- [x] P0、P1、非目标和成功指标口径明确
- [x] 当前规则、Hook、CI、图谱、前端、客户端、后端与migration状态有代码或运行时证据
- [x] 两份既有PRD的入口、runner、Feature Registry/Manifest和migration顺序冲突已统一
- [x] 每个P0 FR至少有一个可执行AC，失败矩阵覆盖空数据、无权限、超时、重复提交和部分失败
- [x] FeatureDefinition、graph、plan revision、trace/span/event、finding、session、attachment、metric ownership的数据合同明确
- [x] REST、MCP、SSE/WS、CLI、Host与Hook输入输出、错误、幂等、顺序、续传、超时、权限和审计明确
- [x] 开发状态机、图节点状态、版本、父子关系和血缘明确
- [x] 统一系统中台入口、三种模式、中文解释、微动画、loading、empty、error、success、分页、orphan、gap、回放、无障碍与反馈明确
- [x] AI只做有证据的接入建议和中文解释，不参与事实/运行事件/CI判定；grounding、分类、脱敏与fallback明确
- [x] migration、历史兼容、灰度、回滚和物理删除边界明确
- [x] Host执行、文件、认证、秘密隔离和Human Gate边界明确
- [x] 日志、指标、反馈、告警和执行后人话汇报明确
- [x] 测试环境、样板功能、验收证据和纵向实施切片明确
- [x] 无阻塞P0的待决策或未接受假设
- [x] `validate_prd.py --strict` 通过
