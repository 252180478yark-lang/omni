# PRD：Omni FDE 活体图谱、单一前端与全链路收敛总实施方案

- 状态：READY
- 版本：v1.2
- 日期：2026-07-29
- 需求方 / 决策人：老板（Omni 个人自用环境）
- 系统基线：Omni `e534655124387655d6528960c67616269f68771c`；分支 `feat/audience-portrait-brief`；工作树 dirty；审计快照 `audit:system-convergence:2026-07-29T22:46:59+08:00`。文中的工作树、worktree、服务、Tool 和数据量数字只描述该快照，不作为运行真源
- 关联需求：把新功能开发固定成“候选功能安放 → 老板与 Codex 共判接入方案 → 开发合同 → 计划虚线 → 受控实施 → 全链路扫描 → CI 门禁 → 绿色事实节点”；运行任务时把真实模型、工具、服务、数据与状态叠加到同一图上，以可回放微动画解释执行过程并提示漏洞、偏差和未考虑项；同时整理过载前端、判断桌面客户端去留、收敛后端重复入口与多数据真源
- 统筹关系：本 PRD 是唯一可开工总控文档；v1.1 与 `2026-07-28-omni-living-system-graph-prd.md`、`2026-07-29-omni-surface-and-backend-rationalization-prd.md` 均为 `SUPERSEDED / REFERENCE_ONLY`，只能作历史设计参考，不能单独决定施工或完成状态
- 实施真值：同目录 `implementation-status.yaml` 是未来由合同、Git 和运行证据生成的进度投影；初始化快照只登记现状，不手工冒充任何阶段已完成

## 1. 落地结论

### 一句话方案

[设计决策][DES-001] 先完成 S0.5 交付真值收口，把“工作树里存在、测试过”与“已经进入可复现提交、能被新 Codex 任务和运行环境读取”分开；再以 R0-R3 风险分级、并发运行隔离、单一 migration runner、真实健康注册和非阻塞 Human Gate 消除开发阻塞与环境串扰，随后建设确定性活体图谱、候选功能共创、运行数字孪生和旧客户端安全退役。

### 决策摘要

| 项目 | 结论 |
|---|---|
| 解决的问题 | 页面、BFF/API、MCP、service、数据库、migration、外部数据源和测试经常局部存在但整体接不上；前端与桌面、旧链与新链、多个 writer 和执行入口并行，开发者难以判断应该改哪里、缺哪一层、何时才算完成 |
| 主要复用 | 已精简的根 `AGENTS.md`、`omni-feature-development`、开发合同 CLI/模板/测试、AGENTS policy gate、feature-contract CI gate、FastAPI OpenAPI、MCP `TOOL_REGISTRY`/doctor、migration baseline、Scout endpoint catalog、现有 SKU 血缘与 `OutputFeedback` |
| 主要修改 | 合同升级 schema v3 并绑定外部交付回执；Hooks/CI 按 R0-R3 风险分级；migration 启动路径收敛；服务与数据源按真实探针和 freshness 聚合；Human Gate 改为持久待批与可恢复执行；现有 WebSocket/tool audit 接入统一 trace/span；Electron 从第二套业务前端缩为可选薄壳 |
| 拟新增 | DeliveryReceipt 与机器生成进度账本、RuntimeAllocation/WorkspaceLease、健康与 build identity 注册、统一错误合同、FeatureDefinition、system graph、候选功能计划、planned/fact/runtime 差异、issue 修复卡、trace/span/event、中文微动画、漏洞雷达、Host Bridge、provider session/附件真源、metric/source ownership 与退役 telemetry |
| V1 不做 | 不让 LLM 猜事实血缘、伪造运行事件或直接决定 CI；不在图上手工改绿或硬删事实；不自动执行 migration、发布、外部平台写入或物理删除；不把漏洞雷达宣传为完整安全审计；不一次性重写全部页面；不立即删除 `omni-desktop`、历史表或用户数据 |
| first_blocker | 无产品决策阻塞；工程首个必做切片是 S0.5：当前治理资产和已验证清理仍未进入 `HEAD`，且当前分支相对本地 `origin/main` 远端跟踪基线已累计 326 个提交，必须先形成最小不可变候选并明确目标分支的历史收口方式，不能把本地候选或整段历史直接冒充已交付 |

### 当前完成度

| 能力 | 当前状态 | 本 PRD 处理 |
|---|---|---|
| 精简 AGENTS、实施 Skill、Hooks 与开发硬闸 | 本地候选实现已验证，但关键文件仍 staged/untracked，当前 `HEAD` 不包含它们 | S0.5 形成 DeliveryReceipt 并验证新任务从交付提交加载 |
| 影响合同、完成合同、状态机 | schema v2 候选实现存在；可在未提交状态被写成 `COMPLETE` | S0.5/S1 升级 schema v3，增加交付回执、风险等级和机器进度投影 |
| AGENTS policy CI、feature-contract CI | 本地候选存在；当前合同覆盖比真实集成测试更强 | S1/S2 调整为风险感知 gate，合同不能替代真实验证 |
| 交付分支基线 | 当前分支相对本地 `origin/main` 为 ahead 326 / behind 0；直接按默认分支 merge-base 计算会把大量历史变更卷入一次候选 | S0.5 先生成以当前审计 HEAD 为 base 的最小候选提交；PR/功能分支只验证 candidate，只有受信默认分支 post-merge push 才能签发 COMPLETE receipt；历史收口单独留证 |
| 本地 Hook | 仅 SessionStart advisory | S2 增加写入前检查与停止前验证；先 warning，试点后 block |
| 活体图谱 scanner/service/API/UI | 尚不存在 | S3-S7 新增 |
| 候选功能接入共创 | 尚不存在 | S5 在事实快照上新增候选计划、证据化选项和用户确认 |
| 虚线计划链自动转绿色事实链 | 合同字段存在，未接真实 scanner | S3-S6 实现并以证据守卫状态变化 |
| 任务运行数字孪生与微动画 | 已有会话 WebSocket、tool-use 列表与审计碎片，没有系统级 trace/span | S8-S9 先补统一关联与事件合同，再做实时/回放动画 |
| 漏洞与遗漏雷达 | 尚无 planned/fact/runtime/delivery 四层对比 | S9 新增确定性发现与 AI 建议分层 |
| 单一 Web 业务前端与 Host Bridge | 目标已明确，尚未完成 | S10-S12 迁移与收敛 |
| 客户端退役 | 当前不具备安全删除条件 | S13 满足退出证据后再卸载/归档 |
| Migration baseline | 当前主运行库 preflight 为 `ready`、无 blocker；但 dev-start、Docker、CI 尚未证明使用同一 runner | S1.5 收敛唯一执行路径并隔离并发数据库 |
| 并发运行隔离 | 审计快照有 35 个 worktree、31 个本地分支；额外 8003 服务共享主 DB、volume 与 cron | S1.5 引入 RuntimeAllocation/WorkspaceLease，禁止可写运行时串用资源 |
| 运行健康与数据新鲜度 | 多个可见服务停止，overview 仍可能只看部分服务；Cookie 存在被当作可用 | S2.5 建立服务/source/build/freshness 真健康与前端降级 |
| Human Gate | 兼容 wrapper 同步轮询最长 6 小时，过期项可继续出现在 pending 列表 | S2.5 改为立即返回待批、批准后恰好恢复一次 |

### 统一后的架构决策

1. [设计决策][DES-002] `FeatureDefinition` 是功能身份、入口、能力、期望链路、检查规则和生命周期的唯一 Git 真源；前端 Feature Registry 与图谱 Manifest 都是它的投影，不维护两份同名配置。
2. [设计决策][DES-003] 图谱事实层只能由静态/运行时 collector 生成；合同只声明预期，UI 不允许手工修改事实、删除事实或改健康状态。
3. [设计决策][DES-004] 图谱不增加常驻一级导航：开发视图进入 `/workspace` 高级模式；SKU 业务图进入 `/sku/[id]`；允许保留内部深链接。
4. [设计决策][DES-005] Web/PWA 是唯一业务 UI；Host Bridge 只承载 Codex/Claude、本地文件、可见扫码、续跑等宿主能力；Electron 最多保留薄壳，不保留第二套业务实现。
5. [设计决策][DES-006] scanner 的 `unknown` 不等于 `missing`；依赖不可用时不得生成“删除”结论。只有静态可证明、manifest 标为 required、证据完整的断链才能阻断。
6. [设计决策][DES-007] 当前 migration baseline 已 ready，但只有顶层 `migrations/` 与 `scripts/apply_migrations.py` 可作为演进与执行真源；dev-start、一次性 Docker migration service 与 CI 必须调用同一 runner，业务服务启动不得私自迁移。
7. [设计决策][DES-008] 用户所说“先把功能安上去”在 V1 中定义为创建 `candidate/planned` 候选功能节点，不等于部署代码；系统基于当前 snapshot 给出“复用 / 修改 / 拟新增 / 不做”接入选项，必须由老板确认后才能写入 impact 合同。
8. [设计决策][DES-009] 运行视图采用 OpenTelemetry 兼容的 trace/span/event 语义，动画只消费真实事件；缺失、乱序或未埋点的段落显示 trace gap，绝不补画一条看似完整的链。
9. [设计决策][DES-010] 漏洞雷达将“确定性观察”与“Codex 假设/建议”分层：可复现的 required-edge、schema、owner、权限与运行偏差可以阻断；启发式遗漏只能告警并提供验证方法，不能冒充事实或安全证明。
10. [设计决策][DES-011] 前端只建设一个“Omni 系统中台”，同一事实图按需切换“开发模式 / 执行模式 / 业务血缘模式”，共用搜索、证据、中文解释和雷达；最小观测单元是可稳定关联的 span/event 与字段级 schema/血缘，敏感值只显示脱敏摘要，不能以“最小颗粒度”为由暴露原文、秘密或个人数据。
11. [设计决策][DES-012] 新开发合同使用 schema v3：`GRAPH_DIFF_READY` 可表示“已验证未交付”，只有 DeliveryReceipt 证明 `subject_commit` 可从集成分支到达且承载真实 diff 时才进入 `COMPLETE`；历史 v1/v2 合同不倒改。
12. [设计决策][DES-013] 采用 R0-R3 风险分级和个人老板模式：普通只读、本地可恢复和明确的内部开发由 Codex 自动推进；仅产品含义关键歧义或外部发布、真实付费、密钥、共享库 migration 执行、用户数据硬删等 R3 动作暂停确认。
13. [设计决策][DES-014] 工作树不是普通任务的强制仪式；仅在并发开发或独立运行时启用 WorkspaceLease/RuntimeAllocation。非 canonical 环境默认隔离 DB/schema、端口、volume、Redis namespace，并关闭 cron。
14. [设计决策][DES-015] 功能可用性来自 FeatureDefinition 依赖、主动健康探针、真实读取和 freshness；Cookie、容器存在或 HTTP 200 均不能单独证明健康。运行版本必须暴露 build identity，源码与镜像不一致显示 stale。
15. [设计决策][DES-016] Human Gate 采用非阻塞 `request → pending → approve/reject/expire → resume`；通知不等于授权，批准只恢复冻结 payload 一次，不长时间占用 HTTP/MCP 请求。

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
- [用户确认][USR-011] Omni 全部代码由老板自行开发；普通开发、整理和可恢复重构不应被重复评审或人工审批卡住，只有真实连接问题、关键产品歧义或高风险副作用需要暂停。
- [用户确认][USR-012] PRD 必须补齐交付真值、分级门禁、并发隔离、真实健康、migration 单路径、非阻塞审批和客户端数据退出条件，用来直接解决后续开发混乱。

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
| 数据演进安全 | migration baseline 与 runner 一致性 | preflight + MigrationReceipt | 主运行库 `ready`，启动路径尚未统一 | dev/Docker/CI 使用同一 runner，且空库与存量库的 head/checksum 一致 | 每次 migration |
| canonical 指标无覆盖 | 非 owner 尝试写 canonical metric 的次数 | ownership/collision audit | 当前两个 writer 可更新同一唯一键 | 非 owner 成功写入为 0，碰撞全部留痕 | 每日 |
| 旧客户端安全退出 | Electron 独占调用、回退事件与 Host smoke | Host/desktop telemetry | 当前仍有 7777、续跑、扫码、本地文件依赖 | 连续 14 天无 Electron 独占调用且 Host smoke 全绿后才允许退役 | 退出观察期 |
| 接入方案证据完整 | 候选功能每个 reuse/modify/add/not_do 决策是否带当前事实、风险与验证 | integration plan artifact | 尚无该能力 | 用户确认前零产品副作用；锁定后每项均可追到 snapshot/evidence | 每个候选功能 |
| 运行路径可解释 | 有权查看的已观测 span 中，可映射节点/边或明确标为 gap/unmapped 的比例 | runtime trace artifact | 只有 tool-use/审计碎片，尚无统一 trace | 不允许“无解释消失”；不能映射的事件必须显式进入 gap/雷达 | 每个任务 |
| 动画忠于事实 | UI 播放顺序、状态、输入输出摘要与 immutable trace 是否一致 | trace replay E2E | 尚无动画 | 回放与原 trace 事件序列一致；缺事件不补画 | 每次相关发布 |
| 漏洞建议可行动 | 雷达 finding 是否含事实/假设分类、影响、修复位置和验证 | finding schema/feedback | 尚无统一雷达 | 每个 finding 均可验证；启发式建议不作事实阻断 | 每次 scan/任务 |
| 已验证成果真实交付 | `COMPLETE` change 中 DeliveryReceipt 可验证且 `subject_commit` 可从集成分支到达的比例 | delivery checker / Git | 当前治理与清理候选仍有仅在 index/worktree 的资产 | 新 schema v3 change 必须全部满足；未交付保持 `verified_not_delivered` | 每次完成 |
| 并发资源零串扰 | 非 canonical worktree 复用 canonical DB/volume/cron 或冲突端口的成功启动次数 | RuntimeAllocation audit | 审计快照已发现额外服务共享主资源 | 成功启动为 0；冲突均在启动前报告 owner | 每次启动 |
| 可见功能不假健康 | 可见功能被显示 healthy 但 required 依赖 down/stale/unknown 的次数 | HealthRegistry / UI contract | 当前 overview 只覆盖部分服务 | 为 0；未知必须显示 unknown，不能折算为正常 | 每次探针/发布 |
| 运行版本一致 | 前端、BFF、service 的 build identity 与交付提交不一致但仍作为完成证据的次数 | runtime manifest / release gate | 当前运行前端可落后源码 | 为 0；不一致显示 stale 并阻断发布完成 | 每次发布 |
| 审批不占连接 | Gate 等待期间持续占用 HTTP/MCP 请求数 | operation/gate audit | 兼容 wrapper 最长轮询 6 小时 | 新路径为 0；批准后同一 operation 恰好恢复一次 | 每次 R3 操作 |
| 历史债务不制造新阻塞 | 本次变更新增的 lint/type/test 回归与无关历史债务分开计数 | changed-path CI + debt baseline | 全量 lint 有既有债务 | 新增回归为 0；旧债务显式登记但不阻断无关 R1/R2 | 每次变更 |

## 3. 当前系统事实

### 证据台账

| ID | 标签 | 原子事实 | 证据 | 核查级别 | 设计影响 |
|---|---|---|---|---|---|
| SYS-001 | `[现状事实]` | 根 `AGENTS.md` 已将跨页面/API/MCP/service/DB/source 的开发路由到实施 Skill，并规定断链不得 `COMPLETE` | `AGENTS.md:23,50-60` | 代码已核 | 复用为 Codex 入口，不再继续堆长 SOP |
| SYS-002 | `[现状事实]` | `omni-feature-development` 已实现六态流程和 impact/completion 严格校验 | `.agents/skills/omni-feature-development/SKILL.md:8-91`；`scripts/dev_contract.py` | 代码已核 | 复用合同，不另造第二套开发状态机 |
| SYS-003 | `[现状事实]` | 当前 AGENTS policy 与开发合同候选实现已有通过证据，但关键治理资产未进入当前 `HEAD` | 2026-07-29 审计快照；`git cat-file -e HEAD:<path>` | Git + 本地运行已核 | 测试通过只能证明候选实现，S0.5 必须再证明交付 |
| SYS-004 | `[现状事实]` | 项目 Hook 目前只有 SessionStart advisory；没有写入前或停止前合同阻断 | `.codex/hooks.json:1-19`；策略测试明确 `hook_mode_warns_but_never_blocks` | 代码已核 | 用户描述的实时拦截尚未实现 |
| SYS-005 | `[现状事实]` | CI 已有 AGENTS policy gate 和 feature-contract gate，但全量测试仍 `continue-on-error` | `.github/workflows/ci.yml:35-103,210-211` | 代码已核 | 不能宣称 CI 已验证全部真实链路 |
| SYS-006 | `[现状事实]` | system-graph page/schema/service/router/MCP 目标文件当前均不存在 | 2026-07-29 `Test-Path` 检查 | 代码已核 | 图谱扫描、虚线转绿和 UI 均为拟新增 |
| SYS-007 | `[现状事实]` | Web 当前有 42 个页面、121 个 Next route；SKU Pipeline 单页 7,563 行并有 43 个 BFF route | 2026-07-29 只读文件统计；`frontend/src/app/sku-pipeline/page.tsx` | 代码已核 | 必须建立 FeatureDefinition、typed operation registry 并纵向拆分 |
| SYS-008 | `[现状事实]` | `/chat` 当前渲染 Agent Chat，但首页与新手引导仍按知识库问答描述 | `frontend/src/app/chat/page.tsx:2-5`；`frontend/src/app/page.tsx:159-166,499-500`；`frontend/src/components/beginner-guide.tsx:140-186` | 代码已核 | 同一入口的产品语义已经漂移 |
| SYS-009 | `[现状事实]` | Electron 启动 IPC、Redis、托盘、快捷键、HTTP 服务、续跑和本地文件协议，不是可直接删除的网页壳 | `E:/agent/omni-desktop/src/main/main.ts:167-206` | 代码已核 | 先拆 Host Bridge，后退役业务 renderer |
| SYS-010 | `[现状事实]` | 企业微信 Codex 默认依赖宿主 `host.docker.internal:7777` | `services/knowledge-engine/app/services/wecom_remote_router.py:44,67`；`docker-compose.yml:252` | 代码已核 | 直接删除 desktop 会断远程 Agent |
| SYS-011 | `[现状事实]` | Web 上传写 frontend 进程目录，却返回 KE 静态 URL；两者当前没有被证明为同一持久真源 | `frontend/src/app/api/agent-chat/upload/route.ts:9-27`；`docker-compose.yml:120-164,282` | 代码已核 | 附件必须改为 ID 与共享存储合同 |
| SYS-012 | `[现状事实]` | 审计快照中 MCP doctor 为 162/162 全绿，但 `CLAUDE.md` 手工计数仍写 115 | 2026-07-29 doctor 运行结果 | 运行时已核 | Tool 数量是动态快照；只以 live catalog/doctor 为真源 |
| SYS-013 | `[现状事实]` | 主运行库 migration preflight 当前 `ready`、`blockers=[]`；但 Docker compose 只挂 init.sql，CI 尚未 bootstrap 顶层 migrations，dev-start 另行调用 runner | `p0_preflight_video_production` 2026-07-29 返回；`docker-compose.yml`；`dev-start.ps1`；CI | 运行时+代码已核 | 不再修 091/092 历史；改为统一所有启动路径和隔离数据库 |
| SYS-014 | `[现状事实]` | `metric_ingest` 与 `runbook_executor` 均可对 `mvp_daily_metric` 同一唯一键执行 `ON CONFLICT DO UPDATE` | `services/scout-agent/app/services/metric_ingest.py:575-607`；`runbook_executor.py:395-399,525-529` | 代码已核 | 需要 canonical owner 与 collision gate |
| SYS-015 | `[现状事实]` | KE 有 `/mcp/exec/{tool_name}` 与 `/mcp/catalog/exec` 两套通用 dispatcher，二者都从 `TOOL_REGISTRY` bind 并执行 | `services/knowledge-engine/app/routers/mcp_exec.py:991-1016`；`mcp_catalog.py:58-84` | 代码已核 | 抽唯一执行内核，URL 只做兼容适配 |
| SYS-016 | `[现状事实]` | 现有 SKU 血缘、OpenAPI、MCP catalog、migration baseline 和 Scout catalog 都可作为 collector 输入，但没有共同 Node/Edge/Snapshot/Issue 契约 | 现有两份子 PRD列明的源码与本轮文件核查 | 代码已核 | 复用事实源，新增统一图模型而非复制业务逻辑 |
| SYS-017 | `[现状事实]` | `AGENTS.md`、实施 Skill、`.codex/hooks.json` 在 index 中，PRD registry 与 Codex runner 等仍 untracked；这些路径均不存在于当前 `HEAD` | 2026-07-29 `git status --short` 与 `git cat-file -e HEAD:<path>` | Git 已核 | S0.5 必须先把治理入口变成可复现交付提交 |
| SYS-018 | `[现状事实]` | FDE Skill 文档给出的 `python scripts/validate_prd.py` 在仓库根不存在，真实脚本位于 Skill 内部 | `.agents/skills/omni-fde-prd/SKILL.md:25`；`Test-Path scripts/validate_prd.py = false` | 代码已核 | S1 必须提供稳定根入口或修正文档，防止照流程执行仍断链 |
| SYS-019 | `[现状事实]` | Agent Chat 已通过 WebSocket 发送 session-scoped `chunk`、tool call/result 与 `task_done`，前端可按 `tool_use_id` 配对调用与结果 | `frontend/src/lib/agent-chat/types.ts:117-124`；`ws-handler.ts:254-281`；`useAgentChat.ts:46-64,113-121` | 代码已核 | 可复用流式通道和事件解析，但不能直接当系统级 trace |
| SYS-020 | `[现状事实]` | Playground `TracePane` 当前展示 tool 调用列表、输入输出、LLM trace、耗时和成本，不是页面→接口→Tool→service→表/源的图形运行孪生 | `frontend/src/components/playground/TracePane.tsx:7-34,104-156` | 代码已核 | 复用明细交互，不复用为完整运行图结论 |
| SYS-021 | `[现状事实]` | `@tool_with_audit` 与 `mcp.tool_calls` 已留存 tool、参数、结果、状态和时长，`mcp.client_logs` 另存客户端事件 | `app/mcp/audit.py:79-166`；`migrations/016_mcp_audit.sql:5-24`；`032_bug_memory_and_logs.sql:6-25` | 代码已核 | 可作为 trace adapter 输入，需补统一 correlation/parent-child/脱敏合同 |
| SYS-022 | `[现状事实]` | Claude `tool_use_id` 与 KE 审计行当前按 tool_name+时间窗回填，源码明确称为近似匹配；尚无贯穿所有层的 `trace_id/span_id/parent_span_id` 证据 | `app/routers/tool_uses.py:1-11,37-41,70-91`；`migrations/035_toolcalls_tooluseid.sql` | 代码已核 | 数字孪生前必须先补确定性关联，旧事件无法映射时标 unmapped/gap |
| SYS-023 | `[现状事实]` | SKU `LineageTree` 是写死六类节点的嵌套卡片树，生成后通过 `lineageKey` remount/refetch；不是可扩展通用节点—边画布或实时增量覆盖层 | `frontend/src/app/sku-pipeline/LineageTree.tsx:66-93,236-321`；`page.tsx:753,7487,7536` | 代码已核 | 保留为业务适配器/无障碍降级，不能作为统一图模型 |
| SYS-024 | `[现状事实]` | 任务页每5秒轮询并展示进度/旋转状态；Agent Chat WebSocket断线只置为未连接，当前协议没有图节点、sequence或replay cursor | `frontend/src/app/tasks/page.tsx:79,146,340-349`；`frontend/src/hooks/useAgentChat.ts:41,74`；`frontend/server.ts:28-34` | 代码已核 | 可复用状态样式和流式基础，需新增持久事件、续传、去重与回放 |
| SYS-025 | `[现状事实]` | 审计快照中 `mcp.tool_calls` 有9,682行，但 `tool_use_id` 与 `claude_session_id` 非空仍均为0；Codex runner名称与audit函数名也不统一 | 2026-07-29 只读SQL；`frontend/src/lib/agent-chat/codex-runner.ts`；`app/mcp/audit.py`；`app/routers/tool_uses.py` | 运行时+代码已核 | 行数只作快照；S8必须先建立确定性关联与规范化 identity |
| SYS-026 | `[现状事实]` | 运行库 `mcp.client_logs` 当前有85,049行但 `session_id` 非空为0；Human Gate WebSocket事件广播给全部连接且 `session_id=''` | 2026-07-29 只读SQL；`frontend/src/lib/agent-chat/ws-handler.ts:34-66` | 运行时+代码已核 | 客户端/审批事件必须补session/execution路由后才能支持并发任务归因 |
| SYS-027 | `[现状事实]` | 当前分支有大量已验证但未交付资产；某些 completion 可在合同文件本身仍 untracked 时标 `COMPLETE` | Git 状态；2026-07-29 repository-hygiene 工作树审计快照 | Git 已核 | schema v3 必须增加外部 DeliveryReceipt，避免合同自证完成 |
| SYS-028 | `[现状事实]` | 审计快照有 35 个 worktree、31 个本地分支，现有合同没有 path lease 或运行资源所有权 | `git worktree list --porcelain`；`git for-each-ref`；合同 schema v2 | Git + 代码已核 | 并发任务可能覆盖同路径或共享运行资源 |
| SYS-029 | `[现状事实]` | `omni-knowledge-engine-v4-ecommerce` 从另一 worktree 运行在 8003，并与主 KE 共享数据库、knowledge volume 和 cron | Docker inspect / compose labels，2026-07-29 审计快照 | 运行时已核 | 必须在服务启动前分配并验证 DB/volume/port/cron owner |
| SYS-030 | `[现状事实]` | 运行中的 frontend image 早于当前源码修改，运行 bundle 未包含源码已经要求的 `audience_pack_id` 交互 | image created time、源码 mtime、容器 bundle grep、BFF 502 | 运行时已核 | 必须把 build identity 和运行新鲜度纳入完成/发布证据 |
| SYS-031 | `[现状事实]` | identity、news、video-analysis、livestream-analysis、ad-review 与 nginx 当前未运行，但前端仍暴露入口，overview 仅检查部分服务并可能报告 100% | Docker/port/API 探针与 overview 实现 | 运行时+代码已核 | 可见功能必须绑定完整依赖与真实降级状态 |
| SYS-032 | `[现状事实]` | Scout 可找到多个平台 Cookie，但真实会话探针并非全部成功，且 JD 最新数据已过 freshness 窗口 | Scout 会话/数据只读探针，2026-07-29 审计快照 | 运行时已核 | Cookie 存在不能作为 source healthy |
| SYS-033 | `[现状事实]` | `request_approval` 最长同步轮询 21600 秒；已有 `create_pending_gate` 非阻塞基础，但 pending 列表未在读取前结算过期项 | `app/mcp/audit.py`、`app/mcp/human_gate.py:75-202`、`inbox_service.py:22-56` | 代码已核 | 复用 durable gate，改成立即返回和可恢复执行 |
| SYS-034 | `[现状事实]` | CI 阻断合同/策略/runner/typecheck，但完整 KE job 仍 `continue-on-error`；合同可通过而交付提交、运行版本和真实 DB 未被证明 | `.github/workflows/ci.yml`；合同 validator | 代码已核 | 调整 gate 优先级并使用外部 attestation |
| SYS-035 | `[现状事实]` | 前端完整 lint 存在历史债务，Docker build 又使用跳过 lint 的路径 | 2026-07-29 lint/build 审计 | 本地运行已核 | 使用 changed-path/debt ratchet，避免旧债务卡死无关开发，也不能宣称全绿 |
| SYS-036 | `[现状事实]` | desktop 仍承载 runner、本地文件、BrowserView、扫码/登录、resume、7777、托盘和快捷键；TriMind 仍有 SQLite 与 keytar 用户状态 | `E:/agent/omni-desktop` 与 `apps/tri-mind-synthesizer` 审计 | 代码/本地数据已核 | 不能先删客户端，必须逐项迁能力、数据和秘密引用 |
| SYS-037 | `[现状事实]` | 当前 `feat/audience-portrait-brief` 相对本地远端跟踪 `origin/main` 的 merge-base 为 `33c5728a...`，ahead 326 / behind 0；若直接以默认分支 merge-base 作为本次小改动范围，会混入长期历史差异 | `git merge-base HEAD origin/main`；`git rev-list --left-right --count origin/main...HEAD`，2026-07-29 只读核查 | Git 已核（远端跟踪快照） | S0.5 需要独立最小候选提交和明确 target-ref 收口；feature push/PR 只能验证候选，外部 COMPLETE 只允许默认分支 post-merge 生成 |

### 当前端到端链路

```text
当前 Codex：
新任务 → AGENTS 路由 → 实施 Skill → impact/completion YAML
       └→ SessionStart policy 提醒
Git diff → feature-contract CI
缺口：治理入口不在HEAD；没有交付回执、风险分级、PreToolUse/Stop强闸或真实graph snapshot/collector

当前交付与并发：
工作树/index候选实现 ──X──> HEAD/集成分支/新worktree
多个worktree/container ──> 可能共享DB、volume、port与cron
缺口：没有DeliveryReceipt、WorkspaceLease或RuntimeAllocation

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

当前健康与审批：
部分service probe → overview；Cookie存在 → source available
require_approval → 创建gate → 同一请求DB poll最长6小时
缺口：可见功能依赖未全量注册；无build/freshness真值；审批未异步恢复
```

### 事实冲突或运行时未核项

- migration baseline 在主运行库已为 `ready`，历史 SQL/checksum 必须继续冻结；尚未证明 dev-start、Docker、CI 和所有 worktree 使用同一 runner/隔离库。
- 当前治理候选、清理结果和 Codex runner 没有统一 delivered commit；在 S0.5 前不能把本地存在写成全局可用。
- 当前 8003 容器可能属于仍在进行的并发任务；S1.5 先登记 owner、隔离和迁移，不在本 PRD 中直接停止或删除。
- 当前服务、source 与前端 build 健康是 2026-07-29 快照，随运行变化；实施必须重新采集，不可把本表当持续监控。
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
| 开发完成 | completion YAML 可由同一工作树填写 | 新任务/CI/运行环境从提交读取 | 否 | schema v3 + 外部 DeliveryReceipt + 机器进度账本 |
| 运行环境身份 | Docker labels、端口和人工命名 | 前端/overview/开发者 | 否 | RuntimeAllocation + build identity，启动前拒绝资源冲突 |
| 功能健康 | 部分服务health与Cookie存在 | 导航、overview和功能页面 | 否 | FeatureDefinition dependencies + HealthRegistry + freshness |
| Human Gate | DB gate行 + 同步poll | inbox/调用方 | 部分同源 | 非阻塞operation状态与一次性resume |

## 4. 范围与非目标

### P0 / V1

- 建立 S0.5 交付真值：新合同 schema v3、DeliveryReceipt 与机器生成 `implementation-status.yaml`；未进入可到达提交的成果不得标 `COMPLETE`。
- 建立 R0-R3 风险分级和老板模式自动推进；普通本地可恢复开发不需要人工审批，只有关键歧义或 R3 副作用暂停。
- 建立 WorkspaceLease/RuntimeAllocation；并发工作树的 DB/schema、端口、volume、Redis namespace 和 cron owner 隔离。
- 让 dev-start、Docker migration service 与 CI 共用 `scripts/apply_migrations.py`，并在隔离空库/存量库验证同一 head/checksum。
- 建立所有可见功能的 service/source/freshness/build identity 注册、typed error 与降级 UI；消除假 100% 和静默吞错。
- 把 Human Gate 改成立即返回 pending、服务端一次性恢复；过期项及时结算，不占用长连接。
- 把当前规则资产、Skill、合同、Hooks 与 CI 纳入版本控制并证明新 Codex 任务能够自动加载。
- 增加写入前和停止前本地门禁；合同外关键变更必须先更新 impact。
- 建立唯一 `FeatureDefinition` 与确定性的 system graph schema、collectors、snapshot、diff 和 issue。
- 建立统一“Omni 系统中台”：同一思维导图支持开发、执行和业务血缘三种投影，不再新增两个互相漂移的中台。
- 允许先创建无副作用的候选功能节点，由 Codex 基于当前事实提出复用/修改/拟新增/不做方案，老板逐项确认后才生成 impact 合同。
- 把 impact 中的计划链显示为虚线；完成后仅凭当前事实与测试证据转成绿色。
- CI 检查页面/BFF/API/MCP/service/migration/table/source/test 的 required edge；静态断链阻断完成。
- 在工作台高级模式与 SKU 详情提供开发图和业务图，不增加新的一级导航。
- 建立统一 trace/span/event 合同，把任务真实经过的 Skill、模型、页面、接口、Tool、service、表/字段和数据源叠加到事实图；提供实时高亮、暂停、逐步、倍速和历史回放。
- 点击任一步时用中文解释“为什么到这里、输入什么、输出什么、下一步去哪、读写什么、是否失败/重试”，并让 planned/fact/runtime/delivery 四层雷达提示确定性漏洞、运行偏差、交付偏差和未考虑项。
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
- V1 不强制每个普通任务创建独立 worktree、进行人工评审、头脑风暴或全量测试；只按风险和受影响边界选择最小充分验证。
- V1 不用合同自带字段证明自身已经交付；DeliveryReceipt 必须由独立 Git/CI checker 对已存在提交生成并签名/哈希。

## 5. 目标流程与状态机

### 前置条件与入口

- Codex 从 Omni Git 根目录启动，根 `AGENTS.md`、目标 Skill 和 `.codex/hooks.json` 必须存在于任务所基于的提交，而不只是另一个工作树或 index。
- migration baseline 当前为 `ready`；涉及持久化时还必须获得该 change 的隔离 DB/runtime allocation，并通过唯一 runner preflight。
- 任何跨层功能有唯一 `change_id`，并引用一个或多个 `feature_id`。
- 用户可以从对话提出需求，也可以在统一系统中台安放候选功能或从雷达 issue 创建草稿 change；三者最终走同一实施 Skill。

### 主路径

1. Codex 识别需求是否需要 PRD，并确定 R0-R3 风险等级；R0不建合同，R1自动轻合同，R2自动完整合同，只有关键产品歧义或R3副作用请求老板确认。
2. scanner 生成当前 before snapshot。老板在系统中台创建候选功能节点，或由对话创建同一类 candidate draft；此动作只写计划，不写产品代码、数据库或外部系统。
3. Codex 读取事实图、FeatureDefinition、OpenAPI、MCP catalog、migration/source/test，逐层给出 `reuse / modify / add / not_do / unknown` 建议；每项标明事实、建议或假设，并让老板确认。
4. 需要共创的 plan revision 经老板确认，或明确的 R1/R2 需求由 Codex自动锁定后，生成 schema v3 `impact.yaml`/`completion.yaml`，记录风险等级、base commit、scope、FeatureDefinition、required edges、测试、迁移、运行分配、风险和回滚。
5. impact 中未来节点和边形成 planned layer，以虚线显示；严格校验通过后进入 `IMPACT_LOCKED`。此前只允许只读调查、计划和合同写入。
6. PreToolUse 检查写入路径和风险等级。同级且确定的新增路径由Codex先写 contract delta再继续；风险升级、并发lease冲突或确定性断链才阻止。
7. Codex 实施代码；发现新依赖时更新 plan/impact、理由和 required edge，再继续。
8. 进入 `VERIFYING` 后先运行changed-path/窄测试，再运行受影响的集成、OpenAPI、MCP doctor、migration/data source、health/build identity 与 graph scan；历史债务单列，不得伪装通过或阻断无关层。
9. scanner 生成 after snapshot 与语义 diff；Stop hook 与 CI 检查计划/实际、required edges、orphan、测试和运行时 unknown。
10. 有静态 blocking issue 时保持当前状态，输出修复卡；不得宣布完成。
11. 所有 required edge 与验证通过后，合同进入 `GRAPH_DIFF_READY`；此时只表示本地候选已验证，不得对外宣称完成。
12. 候选提交进入目标集成分支后，CI 从 Git 对象、实际 diff、合同与测试 artifact 生成外部 `DeliveryReceipt`。Receipt 存在于 CI artifact/attestation store，不写回被证明的提交，从而避免 commit 自引用。
13. 只有外部 attestation 证明 `subject_commit` 可从目标 ref 到达、scope diff吻合、关键路径存在且所有 required checks通过，机器进度账本才把 effective state置为 `COMPLETE`，UI 才把相应 planned节点转为绿色事实。
14. 功能被真实调用时，runtime adapters 生成统一 trace/span/event；系统中台按事件顺序高亮已走路径，中文解释器只基于事实与脱敏摘要说明每一跳。
15. 任务结束或运行中出现偏差时，雷达比较 planned、fact 与 runtime；确定性缺陷进入 issue/CI，假设进入待验证建议，必要时一键创建新的 plan draft。

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
| `VERIFYING` | 测试与扫描完成 | 证据属于当前 change和候选tree | `GRAPH_DIFF_READY` | 写 after snapshot、测试退出码、graph diff与delivery intent | blocking 留在本状态；依赖不可用写 unknown |
| `GRAPH_DIFF_READY` | 提交并由CI外部证明 | 无缺失required edge/orphan；subject commit可达；DeliveryReceipt验证通过 | `COMPLETE` | Receipt写入外部attestation store，进度账本投影effective state | 未提交、不可达、diff漂移或CI失败均保持verified_not_delivered |
| `COMPLETE` | 新发现回归或目标ref撤销 | 新snapshot出现blocking issue或receipt失效 | 新 change / `delivery_state=stale` | 原合同与receipt不可改，创建修复change | 保留历史证据，不倒改旧记录 |

Schema v3 把 Git 中的 `contract_state` 与外部投影的 `effective_state` 分开。合同只声明 `base_commit`、`target_ref`、scope manifest 和 `delivery_attestation_required=true`，不得预写尚不存在的自身 `delivered_commit`；CI 生成的 DeliveryReceipt 才包含 `subject_commit`、tree/diff hash、check run、attester 和时间。历史 schema v1/v2 仍按旧 validator 读取，但不会被自动升级或倒改。

### 开发风险分级

| 等级 | 典型范围 | Codex流程 | Human Gate / 阻断 |
|---|---|---|---|
| `R0` | 只读调查、解释、状态查看 | 不建合同，直接读取并汇报 | 无 |
| `R1` | 本地可恢复、单层、无公开契约或持久化语义变化 | 自动轻合同、changed-path验证、外部交付attestation | 无人工审批；仅确定性越界阻断 |
| `R2` | 跨层功能、内部接口变化、加法migration文件、架构重构、tracked旧代码删除 | 自动完整合同、graph/CI/回滚；需求明确时自动锁定 | 无人工审批；风险升级或关键歧义暂停 |
| `R3` | 外部发布/消息、真实付费、密钥、共享/正式DB执行migration、用户数据硬删、客户端物理退役 | 完整合同、冻结payload、审计、恢复方案 | 老板一次显式确认；批准只授权冻结范围 |

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

### 非阻塞审批执行状态机

| 当前状态 | 事件/守卫 | 下一状态 | 请求行为 | 失败处理 |
|---|---|---|---|---|
| `QUEUED/RUNNING` | operation命中R3且冻结payload成功 | `WAITING_APPROVAL` | 立即返回202、operation_id、gate_id和状态URL | 冻结失败则FAILED，不创建可批准gate |
| `WAITING_APPROVAL` | 老板批准且gate未过期/撤销 | `RESUMING` | worker CAS领取，原HTTP/MCP连接不保持 | 重复批准返回原决定，不重复执行 |
| `WAITING_APPROVAL` | 驳回、撤销或到期 | `CANCELLED/EXPIRED` | 不执行副作用 | pending查询先结算到期项 |
| `RESUMING` | request_id、payload hash、权限和目标复核通过 | `SUCCEEDED/FAILED` | 恰好执行一次并关联原trace | 崩溃后按lease恢复；不重新使用过期授权 |

### 退出、重试与人工确认

- scanner refresh 使用输入指纹幂等；同一 commit、FeatureDefinition revision 和 collector 版本复用结果。
- 单个 collector 超时只把对应来源标为 partial/unknown，不删除旧事实；允许局部重试。
- Hook 无法运行时必须显式报告降级；R1可由CI补验，R2/R3确定性检查缺失时不得宣称完成。
- tracked代码的可恢复整理属于R1/R2；用户数据硬删、共享库migration执行、卸载Electron、旋转凭证、发布或外部写操作属于R3，必须建立独立change与非阻塞Human Gate。

## 6. 功能需求

### FR-001 [P0] 治理资产版本化与可靠加载

- 角色：使用 Codex 开发 Omni 的老板与 Agent
- 触发：新建、恢复或压缩一个 Omni Codex 任务
- 前置：任务工作目录属于受信任的 Omni Git 仓库
- 规则：根 `AGENTS.md` 保持精简；详细流程放 Skill；机械约束放 Hook/CI；启动时验证 repo root、base commit、AGENTS、Skill、Hooks 和版本；关键资产必须存在于本次任务的base commit和最终DeliveryReceipt，不以index/工作树存在代替
- 输出：可审计的加载结果、repo root、规则版本、base commit和可用gate；相关资产进入可到达交付提交
- 异常：文件只在别的worktree/index、路径错误、未信任项目、编码异常或大小超限时拒绝产品写入并指向S0.5修复卡
- 来源：USR-004、USR-011、SYS-001、SYS-003、SYS-017、SYS-027、DES-001、DES-012

### FR-002 [P0] 开发合同与状态机

- 角色：实施新功能或跨层修改的 Codex
- 触发：任务涉及页面、API、IPC、MCP、service、DB、source、状态、权限、审计或自动化
- 前置：已有 READY PRD，或任务不需要 PRD且影响范围可直接锁定
- 规则：新change使用schema v3并复用六态；impact声明risk tier、feature/snapshot、base commit、target ref、scope manifest、运行分配、required edges、测试、迁移、回滚和权限；completion来自真实候选tree/diff和真实命令；外部DeliveryReceipt决定effective COMPLETE
- 输出：版本化impact/completion、contract state、delivery state、path scope和外部receipt引用
- 异常：空合同、倒退状态、重复change_id、实际diff未覆盖、证据不属于候选tree、未提交或receipt不可验证时拒绝effective COMPLETE；历史v1/v2保持原样
- 来源：SYS-001、SYS-002、SYS-027、SYS-034、DES-001、DES-012

### FR-003 [P0] 本地开发过程 Hooks

- 角色：在本地修改 Omni 的 Codex
- 触发：SessionStart、关键文件写入前、任务准备停止或宣布完成前
- 前置：项目已信任 Hooks；当前 change 可解析
- 规则：SessionStart校验交付规则链；PreToolUse按R0-R3、path lease与contract delta判定；同风险范围内Codex自动补合同，只有风险升级、关键并发冲突或确定性断链block；Stop运行最小充分验证并生成候选交付清单
- 输出：允许、自动补合同、提醒或阻断结果；包含risk tier、change_id、路径、lease owner和修复动作
- 异常：Hook超时或collector不可用不得静默标绿；R1可记录降级并交CI补验，R2/R3保持未完成；外部依赖unknown不误判missing
- 来源：USR-003、USR-004、USR-011、SYS-004、SYS-028、DES-006、DES-013、DES-014

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
- 规则：按risk tier选择changed-path、contract、FeatureDefinition、graph、OpenAPI、MCP doctor、唯一migration runner、health/source、类型与目标测试；DB bootstrap接通后移除相关`continue-on-error`；CI从Git对象和artifact生成外部DeliveryReceipt，不能由completion自证subject commit；历史lint/test债务用versioned baseline ratchet
- 输出：明确通过/阻断、失败edge、新增回归、历史债务、命令/退出码和带hash的外部attestation
- 异常：CI缺依赖、DB未bootstrap或外部运行时不可用时区分infrastructure/product/unknown；不得因合同存在、HTTP 200或旧artifact标通过
- 来源：USR-003、USR-011、SYS-005、SYS-013、SYS-034、SYS-035、DES-012、DES-013

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
- 规则：业务UI只存在于Next Web；Host Bridge承载runner、本地文件、可见扫码、续跑和可选系统能力；Electron壳只加载Web并调用Host；Web/Host/Core Backend分别暴露build sha、image digest、worktree/runtime allocation、config hash、migration head和capabilities
- 输出：清晰能力边界、health/build identity/capabilities、运行新鲜度与迁移兼容层
- 异常：Host离线或版本不匹配时Web明确降级/stale，不显示假成功；第二实例不得抢占allocation；无权限不得调用宿主能力
- 来源：USR-005、SYS-009、SYS-010、SYS-030、SYS-031、DES-005、DES-015

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
- 前置：当前ledger reconciliation为ready；目标change具有隔离数据库allocation
- 规则：已执行migration文件名、SQL与checksum保持冻结；顶层`migrations/`是唯一演进真源，`scripts/apply_migrations.py`是唯一执行入口；dev-start、一次性Docker migration service与CI均调用该runner；应用uvicorn启动不自动迁移；空库和存量库验证相同head/checksum；新字段优先加法兼容
- 输出：baseline/runner/runtime allocation/migration receipt、source catalog diff与可回滚发布步骤
- 异常：runner旁路、共享DB被非canonical worktree写入、checksum漂移、未知source或缺rollback时阻断实体变更；主库ready不掩盖隔离环境失败
- 来源：SYS-013、SYS-028、SYS-029、DES-007、DES-014

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
- 规则：先建立旧入口/能力/数据清单、deprecation telemetry和ID映射；desktop的runner、本地文件、BrowserView、扫码/登录、resume、7777、托盘/快捷键逐项迁到Host/Web；TriMind SQLite按记录数与checksum导入持久真源，keytar秘密不得明文导出，只能重新授权/安全迁移；连续14天零独占调用、数据/附件/设置对账与恢复演练通过后，才创建R3物理退役change
- 输出：能力覆盖矩阵、调用清单、SQLite/附件/设置对账、秘密重新授权状态、退出报告、备份与回滚点
- 异常：发现活跃调用、历史ID无法映射、数据checksum不一致、keytar未重新授权、Host smoke或恢复演练失败时停止删除并保留客户端
- 来源：USR-005、SYS-009、SYS-010、SYS-036、DES-005、DES-013

### FR-016 [P0] 真实功能试点与分级推广

- 角色：老板与维护 FDE 的开发者
- 触发：S1-S4 基础能力完成
- 前置：S0.5交付真值、S1.5运行隔离与S2.5真健康/非阻塞Gate已完成；选定小型真实纵向功能
- 规则：分别用一个R1与一个R2样例执行自动合同、planned layer、Hook、隔离运行、scan、CI外部attestation和转绿；用R3 fixture验证非阻塞审批但不触发真实外部副作用；规则按issue code逐项升级block
- 输出：完整change与DeliveryReceipt、运行allocation、误报/漏报、block allowlist和推广决策
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
- 规则：比较 planned、fact、runtime、delivery 四层，P0检测 required node/edge 缺失、schema/参数漂移、REST/MCP分裂、orphan、双writer/未知owner、source freshness、migration runner旁路、未审计mutation、未认证入口、任意tool proxy、敏感信息命中、unmapped event、计划外真实调用、必需路径未到达、未交付COMPLETE、共享运行资源、build不一致、假健康、吞错200、过期pending Gate、缺合同/集成/Gate/失败测试
- 规则：每个 finding 必须有稳定 fingerprint、detector version、严重度、事实/建议/假设分类、证据、影响路径、可能修复位置、验证方法和历史；确定性 `observed_fact` 可以在试点后阻断，Codex `hypothesis` 只能告警，不得自动改图、改代码、关问题或作为安全证明
- 输出：按功能/SKU/层/严重度筛选的雷达、blocking/degraded/unknown计数、中文修复卡和“一键加入候选计划”入口；该入口只建 plan draft
- 幂等/解决：同 fingerprint只更新 last_seen/evidence revision；collector失败时旧问题保持 stale/open，不清零；只有同 detector成功重扫且证据消失才自动 resolved；ignore/snooze不能修改事实或绕过不可豁免门禁
- 权限/安全：detector只能运行白名单只读检查；秘密命中只显示位置和脱敏摘要；未授权用户不得读取受限路径或创建修复计划
- 异常：证据冲突显示 `conflicting_evidence`；source失败显示 partial/unknown；修复尝试失败保持 open并记录 attempt；任何自动修复在P0禁止
- 来源：USR-001、USR-009、USR-010、USR-012、SYS-006、SYS-014、SYS-022、SYS-027-SYS-035、DES-006、DES-010-DES-016

### FR-022 [P0] 交付真值、外部 Attestation 与机器进度账本

- 角色：Codex、CI、集成人与查看项目进度的老板
- 触发：change进入GRAPH_DIFF_READY、候选提交进入目标ref、目标ref移动或用户查看阶段进度
- 前置：schema v3合同包含base commit、target ref、scope manifest、required checks和`delivery_attestation_required=true`
- 规则：合同不得预写尚不存在的自身commit；CI基于已存在Git对象生成外部DeliveryReceipt，包含subject commit/tree、base、实际diff hash、合同/artifact hash、target ref可达性、required checks、attester和UTC；PR、功能分支 push 与手动任务只能验证 candidate，只有受信默认分支的 post-merge push 才可签发 COMPLETE；当目标分支与审计 base 存在长期历史分叉时必须先独立收口，不能把整段旧历史算作一个新功能 diff；进度账本仅从合同、receipt和运行证据生成，不接受手工完成值
- 输出：`verified_not_delivered / delivered / stale / blocked` delivery state、外部receipt定位、机器生成stage projection和中文修复卡
- 异常：文件只在index/worktree、subject不可达、实际diff越界、receipt哈希失配、CI重跑失败或target ref撤销时不得effective COMPLETE；历史receipt不可倒改
- 来源：USR-003、USR-004、USR-011、SYS-017、SYS-027、SYS-034、SYS-037、DES-012

### FR-023 [P0] R0-R3 风险分级与老板模式自动推进

- 角色：持续开发Omni的老板与Codex
- 触发：新需求、scope delta、写入、运行副作用或删除请求
- 前置：仓库规则与风险策略版本可读
- 规则：R0只读不建合同；R1本地可恢复单层改动自动轻合同；R2跨层/内部契约/加法migration文件/可恢复重构自动完整合同；R3外部发布/消息、真实付费、密钥、共享库migration执行、用户数据硬删和客户端物理退役需要一次显式确认；同级确定性delta由Codex自动补合同
- 输出：risk tier、判定理由、自动/人工gate、最小验证集与升级历史
- 异常：分类证据不足时取更高一级但给出降级验证；不得把普通测试、review、worktree或历史lint债务伪装成Human Gate
- 来源：USR-004、USR-011、USR-012、SYS-035、DES-013

### FR-024 [P0] Worktree、路径与运行资源隔离

- 角色：同时运行多个Codex任务、容器或分支的开发者
- 触发：创建并发change、启动非canonical服务、申请数据库/端口/volume/cron或写入重叠关键路径
- 前置：repo/worktree/change identity可解析；单任务无并发时允许使用canonical allocation
- 规则：WorkspaceLease登记path scope，RuntimeAllocation登记compose project、host ports、DB/schema、volumes、Redis namespace、cron owner、build sha和expiry；非canonical环境默认隔离持久资源并关闭cron；启动preflight拒绝可写共享DB、端口/volume/cron冲突；普通任务不强制额外worktree
- 输出：唯一allocation/lease、owner、冲突说明、启动环境和可恢复清理状态
- 异常：发现未知owner、过期lease、共享资源或部分启动时保持现有运行环境不变，只阻止冲突的新启动，不擅自停止其他任务
- 来源：USR-011、SYS-028、SYS-029、DES-014

### FR-025 [P0] 功能健康、数据新鲜度、Build Identity 与错误真值

- 角色：使用功能和判断系统是否可开发/可运行的老板、Codex与前端
- 触发：服务启动/发布、功能入口展示、source refresh、依赖调用或overview查询
- 前置：FeatureDefinition声明可见功能及required/optional依赖
- 规则：HealthRegistry按主动服务探针、认证探针、真实读取、latest_data_at/freshness和build identity计算`healthy/degraded/unavailable/stale/unknown`；Cookie、容器存在或HTTP 200不能单独判healthy；所有可见功能均参与overview；单操作依赖失败返回typed HTTP错误，聚合partial列明失败源
- 输出：feature availability、dependency evidence、build/runtime manifest、freshness、错误ID/层/可重试性/trace和中文降级说明
- 异常：probe超时为unknown、数据过期为stale、build与交付提交不一致为runtime stale；不得吞异常返回空成功或把unknown计入100%
- 来源：USR-001、USR-009、SYS-030-SYS-032、DES-015

### FR-026 [P0] 非阻塞 Human Gate 与可恢复执行

- 角色：发起R3动作并可能稍后批准的老板、调用方与worker
- 触发：operation在执行副作用前命中R3
- 前置：operation、payload hash、目标、权限、有效期、request/trace ID可冻结
- 规则：创建gate后立即返回202 pending与operation/gate/status标识，不保持原HTTP/MCP请求；批准后worker以CAS/lease领取并复核冻结授权，恰好恢复一次；拒绝、撤销、过期、重放和重启幂等；pending读取前结算到期项
- 输出：QUEUED/RUNNING/WAITING_APPROVAL/RESUMING/SUCCEEDED/FAILED/CANCELLED/EXPIRED状态、决定、执行结果与统一trace
- 异常：通知失败不等于未授权或已授权；过期/撤销后不得执行；重复批准返回原结果；worker失败按同一operation恢复而不新建副作用
- 来源：USR-011、USR-012、SYS-033、DES-016

## 7. 系统落点、复用与差距

| 分类 | 能力 | 现有证据 | 设计落点 | 兼容/不复用原因 |
|---|---|---|---|---|
| 复用 | Codex 路由与开发硬闸 | SYS-001 | 根 `AGENTS.md` | 保持短入口，不塞动态清单 |
| 复用/修改 | 六态合同与 validator | SYS-002、SYS-003、SYS-027 | `.agents/skills/omni-feature-development/` | 新schema v3增加risk/delivery intent；effective completion由外部receipt投影 |
| 修改 | Project Hooks | SYS-004 | `.codex/hooks.json` + `scripts/hooks/` | 从启动提醒升级为受控写入和停止检查 |
| 修改 | CI gates | SYS-005、SYS-034、SYS-035 | `.github/workflows/ci.yml`、`scripts/check_*` | 增加外部attestation与真实测试优先级，历史债务ratchet |
| 拟新增 | DeliveryReceipt/进度账本 | SYS-017、SYS-027 | CI checker + attestation store + 本目录`implementation-status.yaml` | 避免合同/commit自引用和手工冒充完成 |
| 拟新增 | WorkspaceLease/RuntimeAllocation | SYS-028、SYS-029 | `.codex/`/scripts/运行manifest | 单任务不强制worktree，并发时隔离path/DB/port/volume/cron |
| 拟新增 | HealthRegistry/build identity | SYS-030-SYS-032 | FeatureDefinition dependencies + health service/API/UI | 取代部分overview、Cookie可用性和旧镜像假健康 |
| 修改 | Human Gate | SYS-033 | operation repository/worker + 现有gate/inbox | 复用pending表和通知，移除请求内长轮询 |
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
| 修改 | Migration执行路径 | SYS-013、SYS-029 | 顶层migrations + `scripts/apply_migrations.py` + one-shot service/CI | baseline已ready；必须消除启动路径与并发DB分叉 |
| 修改 | Tool 执行和指标写入 | SYS-014、SYS-015 | shared executor、metric owner/observation | 当前重复逻辑和 writer 会继续漂移 |
| 不做 | LLM 自动推断事实边或运行事件 | — | — | 不确定且不可复现，不能作为 CI 依据；Codex只做有证据的建议与中文解释 |
| 不做 | 图上直接删事实或自动修复 | — | — | 绕过代码、migration、Human Gate 和审计 |

### 影响面

| 层 | 目标模块/文件 | 动作 | 合同变化 | 测试影响 |
|---|---|---|---|---|
| Agent policy | `AGENTS.md`、`.agents/skills/omni-feature-development/` | 复用/修改 | 增加 feature/snapshot 入口说明 | policy、Skill eval、new-session smoke |
| Hooks | `.codex/hooks.json`、`scripts/hooks/*` | 修改/拟新增 | SessionStart/PreToolUse/Stop 输入输出 | Hook fixture、timeout、Windows/Linux |
| Contracts | `docs/dev-changes/*`、合同 schema/template/CLI | 修改 | before/after snapshot、feature refs、deviation | validator/transition/Git fixture |
| Delivery | CI checker、attestation artifact、`implementation-status.yaml` | 拟新增 | subject commit、tree/diff/check hashes、delivery state | Git DAG/diff/tamper/stale tests |
| Risk/lease | policy schema、Hook、RuntimeAllocation/WorkspaceLease | 拟新增/修改 | R0-R3、owner、path/resource allocation | classifier、overlap、parallel compose fixtures |
| Feature config | `services/knowledge-engine/config/features/*` | 拟新增 | FeatureDefinition v1 | schema、duplicate、projection snapshot |
| Graph backend | `services/knowledge-engine/app/schemas/system_graph.py`、`app/services/system_graph/*` | 拟新增 | Node/Edge/Issue/Snapshot | unit/integration/property tests |
| Graph REST/MCP | router、MCP tools、doctor | 拟新增/修改 | refresh/get/search/diff/issues | OpenAPI、tool contract、doctor |
| Graph UI | workspace advanced mode、SKU detail、`components/system-graph/*` | 拟新增/修改 | typed graph API、四态、feedback | RTL/Playwright/a11y/mobile |
| Plan/解释 | `app/services/system_graph/plans*`、`components/system-command-center/*` | 拟新增 | plan revision、evidence class、用户确认、中文解释 | schema、权限、CAS、无副作用、grounding tests |
| Runtime trace | Agent WS、MCP audit、Host/KE/Scout adapters、trace repository | 修改/拟新增 | trace/span/event、cursor、redaction、mapping | event contract、reconnect、dedupe、乱序、性能 |
| Radar | graph diff/issues、runtime detector、repair cards | 拟新增/修改 | finding fingerprint、fact/recommendation/hypothesis | detector fixtures、partial source、CI negative |
| CI | `.github/workflows/ci.yml`、graph/feature/delivery checker | 修改 | artifact、外部DeliveryReceipt与阻断码 | CI self-test、Git DAG、empty/existing DB |
| Host | 独立 Host Bridge、desktop main adapters | 拟新增/修改 | health/session/event/file/login | Windows smoke、single-instance、auth |
| Web Agent | session API、WS、uploads、settings | 修改 | provider-neutral session/attachment | restart/resume/auth/path traversal |
| Frontend | registry、navigation、sku-pipeline | 修改 | canonical feature/operation schema | typecheck、contract、component/e2e |
| DB | migrations、agent session、system_graph、metric ownership | 修改/拟新增 | 纯加法后兼容迁移 | preflight、empty/existing DB、rollback |
| Scout/data | ingest/runbook/catalog | 修改 | owner、observation、collision | deterministic ownership tests |
| Health/error | FeatureDefinition dependencies、health registry、overview/BFF/UI | 拟新增/修改 | service/source/freshness/build identity、typed error | down/stale/unknown/partial/build mismatch E2E |
| Approval | audit/human_gate/inbox + operation worker | 修改/拟新增 | pending/resume/expire/revoke、frozen payload | request release、CAS、restart、duplicate/expiry |
| Legacy | MCP aliases、content_studio、desktop/TriMind renderer与数据 | 修改/退役 | telemetry/deprecation/bridge/SQLite与keytar迁移 | usage query、checksum、reauthorize、restore drill |

## 8. 数据、接口、工具与 AI 契约

### 数据与血缘

| 实体/字段 | 现有或拟新增 | 类型/单位/时区/null | 唯一性/版本/关系 | 保留与迁移 |
|---|---|---|---|---|
| `FeatureDefinition` | `[拟新增][DES-002]` | YAML/JSON；schema_version、feature_id、domain、routes、capabilities、owner、lifecycle、expected_edges、checks、aliases、dependencies | feature_id 与 canonical href 全局唯一；dependency引用service/source health ID | 前端registry、graph expectation与可用性投影由build生成，禁止手改派生物 |
| `impact.yaml`/`completion.yaml` schema v3 | `[现有][SYS-002]` 修改 | YAML UTF-8；change_id、contract_state、risk_tier、base_commit、target_ref、scope_manifest、runtime_allocation_ref、snapshot/edge/evidence、delivery_attestation_required | change_id唯一；状态单向；不得包含尚不存在的自身subject commit | v1/v2历史合同只读兼容；v3 effective state由外部receipt投影 |
| `DeliveryReceipt` | `[拟新增][DES-012]` | 外部JSON/attestation；change_id、subject_commit/tree、base、target_ref、reachable、scope/diff/contract/artifact hashes、checks、attester、UTC | `subject_commit+policy_version`唯一；不可原地改 | CI在commit存在后生成，存artifact/attestation store，不写回subject commit |
| `implementation-status.yaml` | `[拟新增][DES-012]` | schema、prd/version、generated_at/by、audit_snapshot、current_slice、slices、contract/receipt/runtime evidence | 纯派生；source hash/refresh generation | 初始化只登记observed/unknown；未来仅生成器更新，不手工改完成 |
| `WorkspaceLease` | `[拟新增][DES-014]` | repo/worktree/change、path globs、mode、owner、created/expires UTC | active关键路径不可冲突；单任务可无lease | 超期仅标stale，清理前复核owner |
| `RuntimeAllocation` | `[拟新增][DES-014]` | allocation_id、worktree/change、compose project、ports、DB/schema、volumes、Redis namespace、cron owner、build sha、state | 每项资源在active范围唯一；canonical owner唯一 | 非canonical默认隔离；终止后可回收，不删业务数据 |
| `HealthRegistration/ProbeResult` | `[拟新增][DES-015]` | service/source ID、feature deps、required、probe kind、auth/read status、latest_data_at、freshness policy、build identity、observed UTC | result append-only；状态由policy确定性派生 | Cookie/HTTP 200只作证据之一；旧overview转adapter |
| `OperationError` | `[拟新增][DES-015]` | error_id、code、HTTP status、layer、dependency、retryable、trace_id、redacted detail、partial sources | error_id唯一；code版本化 | BFF/REST/MCP统一映射；旧`ok:false`适配期告警 |
| `ApprovalOperation` | `[拟新增][DES-016]` | operation/gate/request/trace ID、risk、payload hash、target、state、expiry、decision、worker lease、result | request ID幂等；一次有效决定；一次执行claim | 复用human_gates并加operation关联；不保存秘密原文 |
| `MigrationReceipt` | `[拟新增][DES-007]` | runner version、allocation、before/after head、checksums、empty/existing DB、exit code、UTC | allocation+target head唯一 | 所有入口由同一runner生成；历史SQL/checksum冻结 |
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
| delivery attestation CLI/CI | 拟新增 | change、subject commit、target ref、contract/artifacts | DeliveryReceipt、effective state、exit code | unreachable、scope_drift、hash_mismatch、required_check_failed | 同subject+policy幂等；每次CI重算 | CI身份签发；合同作者不能自证 |
| runtime allocation preflight | 拟新增 | repo/worktree/change、requested resources、risk | allocation或conflict owner | path/port/db/volume/cron_conflict | CAS/lease；短timeout | 本地审计；不自动停止其他环境 |
| `GET /api/v1/system-health/features` | 拟新增 | feature/filter/cursor | availability、dependencies、freshness、build、partial sources | unknown_feature、probe_unavailable | GET；探针独立timeout | 只读脱敏审计 |
| service `/health/build` | 拟新增/修改 | 无或本机认证 | service、version、build sha/image digest、allocation、config hash、migration head、started UTC | unavailable、redacted | 短timeout | 不暴露env/secret |
| approval operation create/status/resume | 拟新增/修改 | typed operation、frozen payload hash、target、request ID、expiry | 202 pending/status URL或最终result | forbidden、expired、revoked、claim_conflict | request幂等；worker CAS/lease恢复 | R3显式确认；全链审计 |
| canonical migration runner | 修改 | DB target/allocation、dry-run/verify | MigrationReceipt、exit code | checksum_drift、runner_bypass、shared_target | 单runner；失败停止；不自动重试不可逆SQL | 共享/正式DB执行为R3 |

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
- 通知不等于授权。普通tracked代码整理、加法migration文件和本地隔离库验证属于R1/R2；外部发布、真实付费、共享/正式库migration执行、用户数据硬删、客户端物理退役、外部写入或凭证旋转属于R3。

### 风险与 Gate 决策矩阵

| 动作 | 默认等级 | Codex是否自动推进 | 是否Human Gate | 最小证据 |
|---|---|---|---|---|
| 只读诊断、图谱/健康查询 | R0 | 是 | 否 | audit/trace |
| 文档、测试、单层可恢复代码修改 | R1 | 是，自动轻合同 | 否 | changed-path验证+DeliveryReceipt |
| 跨层功能、内部API、tracked旧代码删除、加法migration文件 | R2 | 需求明确时是，自动完整合同 | 否 | graph/兼容/回滚/CI attestation |
| 产品含义关键歧义 | R2→暂停 | 否，先向老板说明选项影响 | 决策确认，不是副作用Gate | frozen plan revision |
| 外部发布/消息、真实付费、秘密、共享库migration执行 | R3 | 先冻结请求，不执行 | 是 | payload/target/hash/expiry/rollback |
| 用户数据硬删、客户端/历史表物理退役 | R3 | 先完成telemetry/对账/恢复演练 | 是 | 精确目标、备份、14天证据、restore |

### Human Gate 与审计

- graph refresh、search、diff 是只读采集，不需要 Human Gate，但必须审计 trigger、scope、source result 和耗时。
- 创建/编辑候选计划草稿不需要业务Gate；老板主动共创的candidate从draft锁定需要确认。对话中已经明确且属于R1/R2的需求由Codex自动锁定，不重复索要确认；这不替代R3副作用Gate。
- 查看、暂停、单步和回放 trace 不需要 Gate；从运行节点发起重试/取消/修复仍调用原 operation，不得借动画绕过权限、幂等和 Gate。
- issue ignore/snooze 需要 actor、理由、到期时间；不能改变 CI 对 blocking事实的判断，除非按受控 policy 明确接受有期限例外。
- R3 operation创建gate后立即返回pending，不保持请求轮询；通知只提示有待批项。批准时服务端复核未过期/未撤销状态、payload hash、目标和权限，由worker CAS领取并只执行一次。
- 物理删除客户端、历史表、用户文件或兼容入口必须单独请求确认，列出精确目标、备份、调用telemetry、数据/秘密对账、回滚和不可逆项。
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
| 候选实现已验证但未交付 | 保持GRAPH_DIFF_READY/verified_not_delivered | 不生成绿色事实 | 提交到目标ref并由CI生成外部receipt | “已验证，尚未交付”与缺失条件 |
| DeliveryReceipt失败/陈旧 | effective state不为COMPLETE或转stale | 不倒改历史合同 | 修复提交后生成新receipt | subject、target、diff/check失败项 |
| 并发runtime资源冲突 | 阻止冲突的新环境启动 | 不停止现有owner、不写共享DB | 申请新allocation或等待lease释放 | 资源、owner、expiry和建议配置 |
| build identity不一致 | 页面/服务显示runtime stale | 不把运行探针当当前源码E2E | 重建并部署subject commit | 源码/镜像build与started_at |
| required服务down/source stale | 功能显示degraded/unavailable/stale，overview不得100% | 单操作返回typed错误；聚合可partial | 恢复依赖或刷新source | dependency/error/trace/freshness |
| Gate等待审批 | 立即返回202 pending | 只写operation/gate/audit，不占请求 | 批准后worker一次性resume | operation/gate/status URL |
| Gate过期/重复批准 | 转EXPIRED或返回原决定 | 不执行或重复副作用 | 新授权需新operation | 明确过期/幂等状态 |
| migration runner旁路或共享目标 | 阻止实体变更/非canonical启动 | 不执行SQL | 改用唯一runner与隔离allocation | runner/DB owner/checksum差异 |
| migration baseline blocked（未来回归） | 禁止新增生产实体 | 不执行migration | 修复ledger/runner后重试 | 展示具体blocker；当前快照不处于此状态 |
| Host 离线 | Web 业务页面可用，宿主功能禁用 | 不创建假任务 | 恢复 Host 后重试 | “宿主服务未连接” |
| 旧入口仍有流量 | 停止退役 | 只记 telemetry | 延长兼容并迁移调用方 | 展示调用来源与最后使用时间 |

### 兼容、migration 与历史数据

- S0/S0.5 保留当前dirty worktree，建立路径归属、scope提交和外部交付回执；不清理用户无关文件。
- 091/092与其他已执行migration不重命名、不改SQL/checksum；当前baseline ready作为起点，不重复历史修复。
- dev-start、一次性Docker migration service和CI只调用`scripts/apply_migrations.py`；业务service启动不迁移；并发worktree使用隔离DB/schema。
- system_graph、provider session、attachment、metric owner/observation 均采用纯加法 migration；读取先兼容旧字段/表，验证后再停止旧写入。
- `FeatureDefinition` v1带schema version；开发合同v1/v2只读兼容，v3新增risk/delivery intent，外部receipt避免commit自引用。
- 旧 BFF URL、MCP URL、7777 和 content_studio 在兼容期保留薄适配/只读；新功能不得继续写旧链。
- 历史snapshot、合同和DeliveryReceipt不可倒改；修复使用新change/snapshot/receipt。TriMind SQLite与附件先checksum对账，keytar只安全重新授权，不明文迁移。

### 灰度、发布与回滚

1. Delivery：S0.5先对当前治理候选生成首个外部receipt；未交付只显示verified_not_delivered。
2. Risk/Hooks：R0/R1自动推进；advisory → warning → selected deterministic R2/R3 codes block；不把普通流程仪式变成门禁。
3. Runtime/migration：先RuntimeAllocation与隔离DB → dev-start/Docker/CI统一runner → 并发资源冲突block。
4. Health/Gate：先health/build/source registry与typed error → 再切非阻塞gate worker；旧同步wrapper只作短期兼容并记录telemetry。
5. Graph：先CLI/file artifact → API/DB snapshot → 工作台开发图 → SKU业务图。
6. Plan：先确定性影响表 + 按需确认 → Codex有证据建议 → stale/rebase与计划深链；始终不自动执行R3副作用。
7. Trace：先execution/trace关联与append-only事件 → 单样板路径高亮 → 断线续传/回放 → 中文解释与雷达。
8. CI：先artifact/receipt warning → 单样板阻断 → 新变更阻断 → 全仓基线逐步治理。
9. Host/Web：Desktop与Host Bridge双运行 → 能力/SQLite/附件/设置/秘密迁移 → 14天观察 → 可选薄壳或R3退役。
10. Backend：shared executor/owner shadow mode → 新调用切canonical → 旧URL/非owner写入告警 → block → 退役。

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
| `delivery_attestation_status` | CI/audit | delivery checker | change、subject、target、policy | effective COMPLETE要求passed且subject可达 | Git DAG/artifact verify |
| `verified_not_delivered_total` | metric/UI | progress generator | slice/change/owner/reason | 不得以COMPLETE汇报；显示修复条件 | status YAML/CI |
| `workspace_resource_conflict` | audit/gate | allocation preflight | path/port/db/volume/cron、owner | 新冲突环境启动次数为0 | parallel fixture |
| `runtime_build_mismatch` | health/release | service manifests | feature/service/expected/observed sha | 非零显示stale并阻断发布完成 | health E2E |
| `feature_availability` | health/UI | HealthRegistry | healthy/degraded/unavailable/stale/unknown | required unknown/down不得计入100% | API/UI contract |
| `source_freshness_age` | health | source probes | source、latest_data_at、policy | 超policy为stale，不以Cookie替代 | probe fixture/query |
| `operation_waiting_approval` | audit | operation repository | risk、age、expiry、entry | 到期自动结算；请求占用数为0 | API/SQL/restart test |
| `operation_resume_claim_total` | audit | worker | operation、claim、result | 同operation成功claim/副作用最多一次 | duplicate/crash fixture |
| `migration_runner_parity` | gate | runner receipts | dev/Docker/CI、head/checksum | 结果必须一致 | empty/existing DB CI |
| `changed_path_regression` | CI | debt ratchet | path、rule、new/existing | new=0；existing单列不冒充通过 | baseline diff |
| `metric_write_collision` | audit | owner gate | metric/grain/platform/source | 成功的非 owner写入为0 | SQL/test |
| `legacy_entry_usage` | telemetry | aliases/desktop/Host | caller、feature、version | 退出观察期要求零独占调用 | dashboard/query |
| `agent_resume_smoke` | test | Web/Host/DB | provider、entry、restart | 每次相关发布通过 | integration smoke |
| `output_feedback` | feedback | graph UI/任务汇报 | snapshot/node/issue/tool call | 进入现有反馈飞轮 | exact id查询 |

实施完成后，Codex 必须输出一张完成卡：change_id、feature_id、contract/effective delivery state、risk tier、subject commit/DeliveryReceipt、runtime allocation/build identity、changed paths、tests/exit codes、before/after snapshot、required edge、accepted unknowns、trace/gap、radar finding、rollback 和产物链接。无外部receipt时必须写“已验证未交付”，不能写“完成”。

## 12. 验收标准

### AC-FR001-01

- Given：治理资产已经进入目标提交并有通过的DeliveryReceipt，项目被标记为受信任
- When：从 Omni 根目录新建一个 Codex 任务并直接要求开发跨层功能
- Then：任务自动路由到实施 Skill，并在产品写入前创建/继续 change contract
- And：启动记录包含repo root、base commit、AGENTS/Skill/Hook版本；只在其他worktree/index存在的文件不算加载成功
- Evidence：新任务 transcript + SessionStart log + `git cat-file` + DeliveryReceipt

### AC-FR002-01

- Given：一个schema v3 change处于`DISCOVERED`且impact缺risk tier、required edge、测试或delivery intent
- When：请求进入 `IMPLEMENTING`
- Then：validator 拒绝状态推进
- And：目标产品文件保持未修改，错误指向具体缺失字段
- Evidence：contract v1/v2 compatibility + v3 unit test + Git diff fixture

### AC-FR003-01

- Given：R2 change已锁定，但准备写入一个未列入impact且会改变公开API的关键文件
- When：PreToolUse 收到该写入
- Then：Hook先让Codex更新contract delta并重新分类；若仍为R2且确定则自动继续，若升级R3或存在lease冲突才暂停
- And：记录change_id、risk、目标路径、lease owner和匹配规则；R1无关历史债务不得触发Human Gate
- Evidence：Windows/Linux Hook fixture + R0-R3 classifier + audit log

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
- Then：对应真实链路gate失败且不能生成DeliveryReceipt或effective COMPLETE
- And：artifact包含失败edge、证据、检查命令和退出码；合同字段自身不能伪造通过
- Evidence：CI self-test fixture + external attestation negative + uploaded artifact

### AC-FR008-02

- Given：全仓lint有既有baseline债务，但本次R1修改没有新增错误
- When：运行changed-path/debt-ratchet CI
- Then：本次gate通过并单列历史债务，不要求先清完全仓
- And：若修改新增错误则阻断；跳过lint的Docker build不能替代该证据
- Evidence：baseline fixture + changed-file lint positive/negative

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
- And：启动第二Host实例不会抢占allocation；Host离线或build sha与交付提交不一致时Web显示degraded/stale
- Evidence：Windows deployment smoke + allocation test + health/build response

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

- Given：当前主运行库baseline为ready，历史migration文件名、SQL和checksum已冻结
- When：重新运行preflight并检查仓库/运行ledger
- Then：仍返回ready且没有历史checksum漂移
- And：任何未来回归都阻断实体变更，但不把旧blocked事实写回当前状态
- Evidence：preflight JSON + ledger/checksum diff

### AC-FR013-02

- Given：隔离空库和存量库，以及dev-start、一次性Docker migration service和CI三种入口
- When：全部调用`scripts/apply_migrations.py`执行/验证
- Then：三种入口产生相同migration head和checksum集合
- And：非canonical worktree尝试指向共享可写DB时在执行SQL前失败
- Evidence：MigrationReceipt + empty/existing DB CI + allocation negative test

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

### AC-FR015-02

- Given：计划退役desktop或TriMind，仍存在SQLite、附件、设置或keytar引用
- When：运行退出对账
- Then：能力覆盖、记录数和checksum必须全部匹配新真源，keytar通过安全重新授权而非明文导出
- And：连续14天仍有独占调用、Host smoke失败或任何数据不一致时保持客户端可恢复，不创建物理删除任务
- Evidence：capability matrix + SQLite/checksum report + reauthorization receipt + 14-day telemetry

### AC-FR016-01

- Given：S0.5/S1.5/S2.5通过，并选择一个R1和一个R2小功能及一个无真实副作用的R3 fixture
- When：从需求开始完成一次合同、planned graph、实施、Hook、scan、CI和修复
- Then：无需额外流程提示即可自动建合同、隔离运行、验证并由外部receipt转绿；R3请求立即返回pending
- And：误报/漏报和历史债务有清单；只有验证过的确定性issue code升级block
- Evidence：完整change + allocation + before/after snapshot + DeliveryReceipt + gate fixture + session transcript

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

- Given：fixture同时包含缺required BFF edge、REST/MCP分裂、双writer、未交付COMPLETE、共享DB/cron、build mismatch、假健康、吞错200、过期pending Gate和计划外runtime调用
- When：雷达比较planned、fact、runtime与delivery
- Then：生成稳定可去重的finding；每项包含分类、证据、影响路径、修复位置、中文说明和验证方法
- And：allowlist内确定性问题可阻断，Codex hypothesis只告警；任何finding都不自动改代码、migration、图事实或外部系统
- Evidence：detector fixtures + finding schema + CI negative + snapshot hash

### AC-FR021-02

- Given：上次存在open finding，本次对应collector超时，另有敏感payload与未授权查看请求
- When：刷新雷达并访问详情
- Then：旧finding保持open/stale，来源标partial，不产生“全部正常”或假resolved；敏感值在API/UI/log均不可见
- And：未授权用户不能读受限证据或创建计划；collector恢复并成功证明缺口消失后才能自动resolved
- Evidence：two-snapshot resolution test + permission negative + redaction scan + audit query

### AC-FR022-01

- Given：schema v3 change通过全部本地测试，但相关文件只在index/worktree且没有已存在subject commit
- When：请求effective COMPLETE
- Then：系统保持`GRAPH_DIFF_READY/verified_not_delivered`，不生成绿色事实或完成汇报
- And：提交进入target ref后，CI从Git对象生成外部DeliveryReceipt才可转effective COMPLETE
- Evidence：Git index/commit fixture + CI attestation + progress projection

### AC-FR022-02

- Given：治理资产staged但在base/subject commit中缺失，或receipt被篡改/target ref撤销
- When：新worktree启动或刷新进度账本
- Then：启动/进度明确显示missing/stale并列出路径或哈希，不沿用旧完成状态
- And：receipt不写回subject commit，重新交付产生新receipt而非修改历史
- Evidence：`git cat-file` + DAG/tamper test + immutable artifact hash

### AC-FR023-01

- Given：一个本地可恢复、单层且不改公开契约的R1修改
- When：Codex实施并触及同风险范围的新测试文件
- Then：自动创建/补充轻合同并运行changed-path验证，全程不请求老板审批
- And：无新增回归且receipt通过后完成；无关历史lint债务只登记
- Evidence：classifier/Hook fixture + changed-path CI + no-gate audit

### AC-FR023-02

- Given：操作从加法migration文件升级为在共享数据库执行，或将向外部平台发布
- When：准备产生副作用
- Then：风险升级R3，冻结payload/target并创建一次pending Gate，未批准不执行
- And：普通review、完整TDD或新worktree不被当作审批条件
- Evidence：risk transition test + operation/gate audit + negative side-effect check

### AC-FR024-01

- Given：已有canonical KE占用主DB/volume/cron，第二worktree申请可写同一资源和冲突端口
- When：运行allocation preflight
- Then：第二环境在启动前失败并显示现有owner、冲突资源和expiry
- And：不停止或修改现有容器，不对共享DB执行migration/cron
- Evidence：parallel compose fixture + Docker/DB negative probe + allocation audit

### AC-FR024-02

- Given：两个并发change路径和运行资源不重叠
- When：分别申请allocation/lease并启动
- Then：获得独立compose project、port、DB/schema、volume、Redis namespace，非canonical cron默认关闭
- And：单任务无并发时允许canonical模式，不强制额外worktree
- Evidence：parallel positive fixture + resource manifest comparison

### AC-FR025-01

- Given：一个可见功能的required service停止，另一个source认证存在但数据已过freshness
- When：请求overview并打开两个功能
- Then：状态分别为unavailable和stale，overview不得显示100%，页面显示中文原因/修复入口
- And：单操作失败返回typed 502/503错误；聚合partial列出成功与失败源，不返回空成功
- Evidence：health registry/API/UI E2E + HTTP contract test

### AC-FR025-02

- Given：运行frontend/service的build sha与目标DeliveryReceipt subject commit不一致
- When：进行发布验收或采集运行证据
- Then：对应runtime显示stale且该证据不能证明当前源码E2E
- And：重建部署后build identity匹配才允许作为完成证据；敏感config值不可见
- Evidence：container/build fixture + release gate negative/positive + redaction scan

### AC-FR026-01

- Given：R3 operation具有冻结payload hash、目标、request/trace ID和有效期
- When：调用创建审批
- Then：短请求立即返回202、operation_id、gate_id和status URL，原连接释放
- And：批准后worker CAS领取并恰好执行一次，结果关联原trace/request
- Evidence：API latency/connection test + worker claim SQL + duplicate side-effect fixture

### AC-FR026-02

- Given：一个gate已经过期，另一个收到重复批准且worker在执行中重启
- When：列pending、批准并恢复worker
- Then：过期项先转EXPIRED并从pending移除；重复批准返回原决定；重启恢复同operation
- And：过期/撤销授权不执行，成功副作用最多一次
- Evidence：clock/expiry test + approve idempotency + crash/restart integration

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
| FR-008 | P0 | AC-FR008-01、02 | 阻断/环境失败/历史债务 | CI self-test/ratchet |
| FR-009 | P0 | AC-FR009-01 | 四态+分页/orphan | RTL/Playwright/a11y |
| FR-010 | P0 | AC-FR010-01 | Host正常/离线/重复实例 | Windows smoke |
| FR-011 | P0 | AC-FR011-01 | 重启恢复+无权限 | integration/security |
| FR-012 | P0 | AC-FR012-01 | 正常+类型/未注册 | type/contract/E2E |
| FR-013 | P0 | AC-FR013-01、02 | ready保持+runner旁路/共享DB | DB integration/CI/allocation |
| FR-014 | P0 | AC-FR014-01、02 | dispatcher parity+writer冲突 | API/DB integration |
| FR-015 | P0 | AC-FR015-01、02 | 活跃调用/数据秘密对账失败 | telemetry/checksum/restore |
| FR-016 | P0 | AC-FR016-01 | 全流程试点 | E2E/CI/session |
| FR-017 | P1 | AC-FR017-01 | 正常+并发/权限 | E2E |
| FR-018 | P1 | AC-FR018-01 | 两种部署+离线 | bundle/PWA/integration |
| FR-019 | P0 | AC-FR019-01、02 | 正常+partial/stale/模型失败 | schema/API/E2E |
| FR-020 | P0 | AC-FR020-01、02 | 实时+断线/乱序/gap/无障碍 | event/replay/Playwright |
| FR-021 | P0 | AC-FR021-01、02 | 多类漏洞+partial/权限/脱敏 | detector/CI/security |
| FR-022 | P0 | AC-FR022-01、02 | 未提交/不可达/篡改/stale | Git DAG/CI attestation |
| FR-023 | P0 | AC-FR023-01、02 | 自动推进+风险升级 | classifier/Hook/gate |
| FR-024 | P0 | AC-FR024-01、02 | 资源冲突+正常并发 | allocation/parallel runtime |
| FR-025 | P0 | AC-FR025-01、02 | down/stale/partial/build mismatch | API/UI/release E2E |
| FR-026 | P0 | AC-FR026-01、02 | pending/过期/重复/重启 | API/worker/DB integration |

## 13. 实施切片

| Slice | 可独立验收的结果 | 依赖 | 目标模块/文件 | 主要任务 | 测试 | Done 条件 |
|---|---|---|---|---|---|---|
| S0 安全与基线复核 | migration ready状态和旧代码卫生有可复现证据 | 无 | 两仓Git状态、migrations、敏感脚本、旧产物 | 复核当前ready ledger；冻结历史checksum；路径归属；高确定性缓存/无引用旧物可恢复归档；不删除客户端/数据 | secret scan、preflight、status inventory、restore | baseline仍ready，dirty路径有owner/候选change，清理可恢复 |
| S0.5 交付真值收口 | 治理候选真正进入可复现提交，未交付不再冒充完成 | S0 | AGENTS/Skills/Hooks/runner、合同schema v3、delivery checker、本目录status | 以审计HEAD为base生成最小scope提交；记录默认分支长期分叉并单独收口；新任务加载；schema v3 delivery intent；PR/feature仅candidate；默认分支post-merge CI外部attestation；初始化机器进度账本；历史v1/v2兼容 | policy/contract/new-session、Git DAG/diff/tamper、branch provenance、receipt/status projection | 关键资产存在subject commit；candidate与delivered不混淆；外部receipt仅由受信默认分支生成；其余候选明确verified_not_delivered/owned |
| S1 治理底座与风险分级 | 新Codex任务按R0-R3自动选择最小流程 | S0.5 | AGENTS、实施Skill、contract CLI/schema/tests、risk policy、CI | R0-R3分类；轻/完整合同；同级delta自动补；历史债务ratchet；稳定PRD validator入口 | classifier、policy、contract兼容、changed-path CI、新任务smoke | R0/R1/R2无需重复审批；R3/关键歧义准确停下 |
| S1.5 并发运行隔离与Migration单路径 | 并发任务不共享可写资源，所有环境用同一runner | S1 | WorkspaceLease/RuntimeAllocation、compose/dev-start/CI、`scripts/apply_migrations.py` | path/resource allocation；隔离DB/port/volume/Redis；非canonical cron关闭；one-shot migration service；现有8003登记owner/迁移 | overlap/parallel compose、empty/existing DB、runner parity、checksum | 冲突启动前失败；主环境不受影响；dev/Docker/CI head/checksum一致 |
| S2 风险感知本地过程闸门 | 越界自动补合同，真正风险才阻断 | S1-S1.5 | `.codex/hooks.json`、Hook runner/fixtures | SessionStart/PreToolUse/Stop；risk/lease/path分类；timeout/unknown；warning校准 | Windows/Linux Hook、R0-R3、失败注入 | 同级delta自动继续；risk升级/lease冲突/确定性断链不静默 |
| S2.5 真健康、错误语义与非阻塞审批 | 前端不假健康，审批不占长连接且可恢复 | S2 | Feature dependencies、HealthRegistry、overview/BFF/UI、build manifest、gate operation/worker | service/auth/read/freshness/build探针；typed error/partial；202 pending、expire/revoke/CAS resume；旧poll telemetry | down/stale/unknown/build mismatch E2E、HTTP错误、expiry/duplicate/restart | 可见功能状态可信；unknown不计100%；新R3路径请求立即释放且副作用最多一次 |
| S3 FeatureDefinition与静态图核心 | 一个样板feature可生成稳定事实图 | S0-S2.5 | config/schema/build、graph model/collectors/CLI | 统一功能定义；采集route/OpenAPI/MCP/service/migration/source/test/health/delivery；文件snapshot与diff | schema、collector、determinism、redaction | 两次扫描hash稳定，证据可打开 |
| S4 Planned/fact、Issue与CI warning | 计划虚线、断链修复卡和CI artifact跑通 | S3 | dev contract、diff/issues、CI jobs | impact转planned；required edge判定；repair card；上传artifact；全量测试bootstrap | Git fixtures、OpenAPI/doctor/migration/source、CI self-test | 样板缺边能定位且CI清楚报告，不误删unknown |
| S5 候选功能接入共创 | 老板可先安放功能并与Codex证据化决定接法 | S3-S4 | plan schema/service/API/MCP、impact adapter、中台开发模式 | plan revision；reuse/modify/add/not_do/unknown；事实/建议/假设；用户确认；stale/rebase；零副作用 | schema、CAS、权限、partial、模型fallback、impact projection | 关键unknown未清不锁定；确认前产品零写入；确认后合同可执行 |
| S6 真实小功能试点与block校准 | R1/R2自动闭环、R3异步fixture并确定block规则 | S2.5、S5 | 真实纵向feature、change/receipt/allocation | warning试跑；修误报/漏报；issue allowlist；外部receipt；R3无副作用fixture；selected block | 完整E2E、attestation、gate、session transcript、rollback | 无额外提示完成；未交付/确定性断链无法effective COMPLETE |
| S7 图谱API与统一系统中台静态面 | 同一中台可查看开发/业务图和中文证据 | S1.5、S2.5、S3-S6 | graph migration/repository/router/MCP、GraphModel/NodeRegistry、workspace/SKU UI | 用唯一runner落DB；REST/MCP；通用nodes/edges；lineage adapter；思维导图/可访问树/解释抽屉/雷达静态面 | migration、router、doctor、normalizer、RTL/Playwright/a11y | planned/healthy/broken/unknown/deprecated/verified_not_delivered正确显示 |
| S8 运行追踪事件脊柱 | 每轮任务具备可续传、可关联、可回放的真实事件 | S0.5-S3 | Agent WS/runner、MCP audit ContextVar、Host/KE/Scout middleware、trace repository | 生成execution/trace；规范化tool identity；span父子；append-only event；HTTP/WS传播；session/gate归属；脱敏/retention；cursor | event contract、DB、propagation、dedupe、乱序、reconnect、security | tool/audit不再近似焊接；页面→source已埋点段可确定性关联，gap可计数 |
| S9 执行微动画、中文解释与四层雷达 | 老板可实时看懂路径并发现缺陷 | S7-S8 | RuntimeOverlay/event reducer、Playback、explain service、detectors/findings | 实时/延迟/回放；线路高亮；span/字段级解释；reduced motion；planned/fact/runtime/delivery 比较；一键建 plan draft | event-to-UI E2E、replay、grounding、detector、perf/a11y、redaction | 动画与 trace 一致；缺段不补画；确定性/建议分层；中台不产生第二真源 |
| S10 Host Bridge与Agent合同 | 关闭Electron后Web/企微仍能执行并恢复 | S2.5、S8 | Host service、Web/KE session/auth/upload、desktop adapters | 单实例Host；provider session；auth；统一附件；企微/续跑/扫码切换；build/health/trace一致 | Windows smoke、restart/resume、security、checksum、trace continuity | Web/企微可执行，cwd/历史/附件/trace一致，Electron仍可回退 |
| S11 前端收敛 | 入口同源，SKU Pipeline可分步维护 | S3、S7、S10 | Feature registry projections、导航、chat语义、sku-pipeline | 一级入口收敛；chat/RAG分义；typed operation；model/api/hooks/panels拆分；旧URL alias | registry、typecheck、component、one-step E2E | 新功能只改一套UI；operation一一对应 |
| S12 后端单真源 | executor、metric、旧/新链边界明确 | S1.5、S3-S6、S8 | MCP routers/audit、Scout ingest/runbook、pipeline/content_studio bridges | shared executor；canonical URL；owner/observation/collision；旧链只读映射；trace context共用 | parity、collision、doctor、lineage/trace regression | 非owner不覆盖，新调用只走canonical，新功能只写pipeline |
| S13 兼容面与客户端退役 | 每项旧能力和数据可独立安全退出 | S2.5、S7-S12 | aliases、desktop/TriMind、Host、SQLite/keytar、installer、旧服务/表 | telemetry；能力矩阵；14天观察；SQLite/附件/设置checksum；keytar重新授权；恢复演练；R3独立退役合同 | usage query、Host/exit smoke、checksum、reauthorize、restore | 无独占调用/回退；数据全对账；秘密安全迁移；删除目标精确可恢复 |
| S14 全仓推广 | 新跨层功能默认受完整FDE与运行观测保护 | S6-S13 | CI policy、docs、templates、onboarding、trace coverage | selected block扩大到全部确定性P0 code；清理临时warning；生成图谱/trace/finding健康基线 | regression、full CI、sample changes、trace replay | 静态断链不能合并或完成；运行盲区显式；图谱持续更新 |

### 推荐顺序

1. 先复核S0，然后立即做S0.5：migration已ready，先从审计HEAD切出最小不可变候选；当前分支相对`origin/main`的326提交历史分叉必须作为独立收口问题处理，不能混进一次新功能合同或伪造外部交付。
2. 完成S1与S1.5：建立低摩擦R0-R3、DeliveryReceipt、并发资源隔离和migration单路径。
3. 完成S2与S2.5：只阻断真实风险，让前端/overview显示真健康，并把Human Gate改为非阻塞恢复。
4. 完成S3-S6：先有确定性事实图、候选共创和R1/R2/R3试点，再把验证过的issue code升级block。
5. 完成S7：在真实图、健康和交付合同上做统一中台静态面，而不是手工画图。
6. 完成S8-S9：先修execution/trace/span/event关联，再做微动画、中文解释和四层雷达。
7. 完成S10：迁出客户端独占能力，让Web/企微/Host共用session、附件、trace和build identity。
8. 完成S11-S12：借助图谱与运行证据整理前后端，避免盲删和平行真源。
9. 完成S13-S14：能力、SQLite、附件、设置与keytar全部迁移且14天退出证据满足后，再以R3合同退役旧客户端并全仓推广。

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
| RSK-016 | 合同把未提交候选或自身声明当交付证据 | 高/高 | schema v3只声明delivery intent；CI对已存在commit生成外部attestation | receipt位于subject commit内、subject不可达或diff不符 |
| RSK-017 | 并发worktree共享DB/volume/cron污染主环境 | 高/高 | RuntimeAllocation启动前检查；非canonical默认隔离且cron关闭 | 两个可写owner连接canonical资源 |
| RSK-018 | 容器/HTTP200/Cookie造成假健康 | 高/高 | required dependency、主动读探针、freshness与build identity | required down/stale/unknown仍显示healthy/100% |
| RSK-019 | 风险分级过重再次卡慢普通开发 | 中/高 | R0/R1/R2自动推进、同级delta自动补、changed-path债务ratchet | 普通本地修改频繁等待人工或无关全仓债务 |
| RSK-020 | 非阻塞Gate重复执行或使用过期授权 | 中/高 | payload hash、expiry/revoke、CAS worker lease、request幂等、一次性claim | 同operation副作用超过一次或过期后执行 |
| RSK-021 | 客户端退役丢失SQLite/keytar/附件/设置 | 中/高 | 能力矩阵、checksum、秘密重新授权、14天telemetry、restore drill | 任一数据不一致、独占调用或恢复失败 |

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
| ASM-010 | 个人老板模式下R1/R2明确需求可由Codex自动锁定 | 用户明确不需要重复评审，且Git/合同/回滚可恢复 | 降低流程摩擦 | S6 R1/R2试点的误报/漏报与人工暂停次数 | 将特定issue code升一级，不全局恢复重审批 |
| ASM-011 | CI外部attestation比在合同中写自身commit更可靠 | commit hash在commit创建前不存在，内嵌会自引用 | effective完成需查询artifact/store | S0.5 Git DAG/tamper/replay测试 | 保留schema v3 intent，替换attestation后端 |
| ASM-012 | 并发时隔离、单任务时canonical是最低摩擦方案 | 全量强制worktree会增加负担，共享可写资源又会串扰 | RuntimeAllocation按需启用 | S1.5 parallel/single fixtures | 只扩大强制隔离的资源类别 |
| ASM-013 | 服务健康必须同时表达availability、freshness与build | 当前假100%和旧镜像问题来自单一health布尔值 | 导航/overview/API统一五态 | S2.5 down/stale/mismatch E2E | 保留五态合同，调整具体probe adapter |

### 待决策

#### 阻塞开工

- 无。

#### 不阻塞开工

- 图画布库选择可在 S7 前通过小型技术 spike 决定；Node/Edge/API合同不依赖具体库，现有lineage树保留为可访问降级。
- Electron 最终完全卸载还是保留托盘薄壳，在 S13 观察数据出来后决定；不影响 S0-S12。
- 一级导航最终中文命名可在 S11 可用性评审中调整；canonical feature_id和route保持稳定。
- HealthRegistry各source freshness阈值在S2.5从已有业务口径或实测制定；未定阈值时状态为unknown，不阻塞S0.5-S1.5。
- CI外部attestation可先使用本地/CI artifact目录，未来是否接远程provenance服务不影响schema与验收。

### Definition of Ready

- [x] 使用者、现场问题、失败成本和目标结果明确
- [x] P0、P1、非目标和成功指标口径明确
- [x] 当前规则、Hook、CI、图谱、前端、客户端、后端与migration状态有代码或运行时证据
- [x] 当前动态数字均绑定 `audit:system-convergence:2026-07-29T22:46:59+08:00`，并明确不是持续真源
- [x] 两份既有PRD的入口、runner、Feature Registry/Manifest和migration顺序冲突已统一
- [x] 每个P0 FR至少有一个可执行AC，失败矩阵覆盖空数据、无权限、超时、重复提交和部分失败
- [x] FeatureDefinition、graph、plan revision、trace/span/event、finding、session、attachment、metric ownership的数据合同明确
- [x] REST、MCP、SSE/WS、CLI、Host与Hook输入输出、错误、幂等、顺序、续传、超时、权限和审计明确
- [x] schema v3、外部DeliveryReceipt、effective state和避免commit自引用的CI流程明确；v1/v2兼容边界明确
- [x] R0-R3、老板模式自动推进、风险升级和Human Gate边界明确
- [x] WorkspaceLease/RuntimeAllocation的path、DB/schema、port、volume、Redis与cron隔离明确
- [x] FeatureDefinition dependencies、HealthRegistry、source freshness、build identity和typed error明确
- [x] dev-start、Docker与CI共用唯一migration runner及隔离空库/存量库验收明确
- [x] 开发状态机、图节点状态、版本、父子关系和血缘明确
- [x] 统一系统中台入口、三种模式、中文解释、微动画、loading、empty、error、success、分页、orphan、gap、回放、无障碍与反馈明确
- [x] AI只做有证据的接入建议和中文解释，不参与事实/运行事件/CI判定；grounding、分类、脱敏与fallback明确
- [x] migration、历史兼容、灰度、回滚和物理删除边界明确
- [x] Host执行、文件、认证、秘密隔离和Human Gate边界明确
- [x] 非阻塞Gate的冻结payload、202 pending、过期/撤销、CAS resume、重启与恰好一次副作用明确
- [x] desktop/TriMind能力、SQLite、附件、设置、keytar重新授权、14天观察和恢复条件明确
- [x] `implementation-status.yaml`仅作为机器生成目标格式初始化，不手工宣称切片完成
- [x] 日志、指标、反馈、告警和执行后人话汇报明确
- [x] 测试环境、样板功能、验收证据和纵向实施切片明确
- [x] 无阻塞P0的待决策或未接受假设
- [x] `validate_prd.py --strict` 通过
