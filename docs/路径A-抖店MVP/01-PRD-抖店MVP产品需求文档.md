# 路径 A · PRD：抖店 MVP 产品需求文档

> **核心定位**：用 2 周时间，跑通"巡店 → 数据 → 诊断 → 动作 → 验证"完整闭环，验证使用习惯是否成立。
>
> **路径 A 是路径 B（中台底座）的前置验证**：先用最简单方式跑通核心使用流，验证后数据无缝迁移到路径 B 的正式底座。

---

## 文档信息

| 项 | 值 |
|---|---|
| 文档版本 | v1.0 |
| 文档状态 | 待评审 |
| 编写依据 | 使用逻辑 v2 优化架构（详见 `docs/SYSTEM_ARCHITECTURE.md`） |
| 编写日期 | 2026-04-30 |
| 目标读者 | 老板（业务侧）+ 1-2 个研发 |
| 预计工期 | 14 个工作日 |

---

## 一、概述

### 1.1 业务背景

老板（你）经营调味品工厂，主营线上电商业务，已开设抖店、天猫、京东三个店铺。当前面临的核心痛点：

1. **多店铺数据散落在各平台后台**：每天要切换登录罗盘 / 生意参谋 / 商智，手动看数据，效率极低
2. **动作与效果之间没有可追溯链路**：今天改了主图、明天换了详情页、后天调了人群包——一周后看到 GMV 跌了，但**不知道是哪个动作导致的**
3. **AI 输出"用完即丢"**：圆桌讨论给的策略、知识库问出的人群洞察、投放复盘的迭代建议——结果出来你点关掉就消失了，没人跟进、没有命中率追踪
4. **没有"今天该干嘛"的明确指引**：每天打开系统不知道从哪开始看，只能凭经验找问题，等发现往往晚了 7 天

### 1.2 当前系统现状

Omni-Vibe OS 已具备 7 个独立模块（chat / knowledge / ad-review / content-studio / video-analysis / livestream-analysis / news），但模块间无数据流转、无统一业务对象、无决策记录层。

技术上没有缺失能力，**问题在于"使用逻辑"层面缺乏组织**——这是路径 A MVP 要解决的核心问题。

### 1.3 项目目标

**核心目标**：32 个工作日内（v1.4，约 4.5 周），交付一个**最小但完整**的闭环 MVP，覆盖 **1 个店（抖店）× 全店 SKU 主数据 + 规则化重点池**（v1.5），实现 4 条核心使用流：

1. **早晨 5 分钟巡店流**：自动抓取数据 → 异动检测 → 推送"今天值得关注"
2. **单 SKU 深聊流**：在 SKU 详情页一站式查看数据/动作/AI 诊断
3. **动作执行登记流**：极简表单登记你做的变更
4. **效果验证流**：动作执行后 7 天自动产出"前后对比卡"

### 1.4 与路径 B 的关系

**路径 A 是路径 B 的前置验证**：

| 维度 | 路径 A（本文档） | 路径 B（中台底座） |
|---|---|---|
| 目标 | 验证使用习惯成立 | 建立长期中台 |
| 范围 | 1 店 × 5 SKU × 抖店 | 多店 × 全 SKU × 三平台 |
| 工期 | 2 周 | 4-6 周 |
| 数据库 | 临时 `mvp_*` 表（结构是路径 B 的子集） | 正式 `omni_core / omni_data / omni_decision` schema |
| 验收 | "你能回答出过去 7 天哪些动作有效" | "中台跑得动，飞轮转得起来" |

**关键设计**：路径 A 的临时数据表结构**严格作为路径 B 数据模型的子集**——路径 A 跑完后，数据通过 SQL 迁移直接进入路径 B 的正式表，**零浪费、零返工**。

### 1.5 项目范围

> **2026-05-02 v1.4 更新**：完成 3 平台调研后（罗盘 83 张 + 抖店后台 19 张 + 云图 26 张截图取证），范围 / runbook / 工期 / 数据模型全面修订。详见 `00-调研-抖店数据与动作全景.md` §13.4。

#### ✅ 在范围（必交付）

| 类别 | 具体内容 |
|---|---|
| **店铺** | 1 个：你的抖店主店 |
| **品牌** | 1 个：WADAKAN/和田宽（食品饮料/食品饮料） |
| **SKU** | **全店 SKU**（系统首次跑 g-list runbook 后**自动同步全部 41 SKU**到 mvp_sku 表，无需老板手动填）|
| **重点池**（v1.5 新增）| **每周自动选 ~9 个 SKU 跑深度抓取**（罗盘 product-detail 7 Tab + 云图 SPU 5A）。规则：GMV TOP 5 + 衰退 TOP 2（连续 3 天 GMV 下行）+ 新品 TOP 2（上架 ≤30 天）。规则透明、每周日自动重排，无需老板配置。其他 SKU 仅在老板点开 SKU 详情页时按需触发 |
| **数据平台** | **3 个**：抖店罗盘（compass.jinritemai.com）+ 抖店后台（fxg.jinritemai.com）+ 巨量云图（yuntu.oceanengine.com） |
| **数据抓取** | **8 份 runbook** 自动抓取（A 全店日报 / B SKU 详情 / C 客服与原声 / D 搜索与流量与营销 / E 人群与机会 / F 物流与履约 / G 品牌心智 / H 品牌资产+触点效能，详见 §4.1） |
| **核心页面** | 工作台首页（5A 心电图 + 6 待办数 + 异动告警）/ SKU 详情页（3 Tab）/ 动作登记表单 / 决策日志列表（极简）/ 6 场景化策略卡 |
| **核心能力** | 异动检测 / AI 诊断（圆桌升级版）/ 前后对比卡 / 失败通知 / **5A 流转 + 品牌心智趋势** |
| **动作日志** | **双轨**：用户登记（轨 A）+ 平台被动抓取（轨 B：抖店后台库存变更/评价回复/活动报名/内容发布 + 云图 5A 人群包变更/触点结构调整 + 罗盘极少量） |
| **通知**（v1.5 改）| **NotificationChannel 抽象**——MVP 默认用前端站内通知 + 浏览器原生通知；企微 webhook 留 `.env` 端口（`WECOM_WEBHOOK_URL` 可空），后续补齐 |

#### ❌ 不在范围（明确不做）

| 类别 | 说明 |
|---|---|
| 天猫、京东接入 | 路径 B 第 3-6 周分阶段处理 |
| 巨量千川 | 老板 2026-05-02 决策移出 MVP；投放结构由云图触点效能 + 罗盘渠道占比反推 |
| 巨量百应 / 联盟 | 老板 2026-05-02 决策移出 MVP；达人合作动作仅手登（不抓数据） |
| 巨量算数 / 飞瓜 / 蝉妈妈 | 移出 MVP；类目机会和榜单由罗盘自带功能覆盖 |
| 抖音 App 内观察 | 移出 MVP（老板自己看） |
| 完整 SKU 详情页 7 Tab | MVP 只做 3 Tab（概览 / 动作 / AI 诊断），路径 B 完整 |
| 资产版本管理（asset_version 表） | MVP 用极简的"截图存证"代替版本树 |
| content-studio 与 SKU 深度联动 | 路径 B 处理 |
| 决策日志中心的批量管理 / 筛选 / 状态机完整流转 | MVP 只做列表展示和"采纳"动作 |
| 客服会话深度抓取与情感分析 | 路径 B 处理（MVP 仅抓评价管理 4 Tab + 罗盘客服分析） |
| 周度 dashboard（多张图表的可视化复盘） | 路径 B 处理 |
| 多人 / 团队协作 | 单用户 |
| 移动端 | Web 桌面端为主 |
| 完整的 SPU + platform_instance 双层抽象 | MVP 表结构预留扩展字段 |
| 云图 AIMars / 创意实验室 / 数据工厂 | 高级版功能，MVP 不抓 |

---

## 二、用户与场景

### 2.1 用户画像

| 维度 | 内容 |
|---|---|
| 用户身份 | 调味品工厂老板（你），同时是抖店操盘手 |
| 主要使用场景 | 早晨 8:30-9:30 打开系统看异动 / 全天遇到问题随时查单 SKU / 周日晚上复盘 |
| 设备 | Windows PC，使用 Chrome 浏览器，本地或可信内网 |
| 技术能力 | 看 dashboard 无障碍、能填表单、能上传截图，不写代码 |
| 数据敏感度 | 抖店登录态 / 销售数据均为敏感信息，必须本机加密保存 |

### 2.2 关键使用场景

#### 场景 1：早晨 5 分钟巡店

```
8:30 ─── scout-agent 自动跑完三平台 8 份 runbook 抓取
8:35 ─── 异动检测引擎完成（13 类规则），生成"今天值得关注"清单
8:40 ─── 通知（NotificationChannel）：默认前端站内通知；企微/邮件留端口可后补
9:00 ─── 你打开系统 → 工作台首页 → 看到 5A 心电图 + 6 待办 + 3-5 条异动卡片 + 6 场景策略卡
9:01 ─── 点击 🔴 异动卡片 → 跳到对应 SKU 详情页
9:03 ─── 浏览数据曲线 + 最近动作（双轨）+ AI 初步诊断
9:05 ─── 决定本日重点（要么采纳建议，要么开"深度诊断"）
```

#### 场景 2：单 SKU 深聊诊断

```
你：进入 SKU 详情页 → 切到「AI 诊断」Tab
你：点击「启动深度诊断」按钮
系统：自动拉取该 SKU 的：
       - 最近 14 天数据
       - 最近 14 天的动作日志
       - 知识库相关人群报告（如调味品/酱油类）
       - 同类 SKU 对比数据
系统：调用圆桌讨论模块（运营/数据/内容/客服 4 个视角）
系统：生成诊断报告 → 自动落入 decision_log
你：审阅报告，对每条建议选择「采纳」「拒绝」「延后」
你：采纳的建议 → 系统自动建一条 change_event（待执行）
```

#### 场景 3：动作执行登记

```
你：在抖店后台改了 SKU-A001 的主图（v2 → v3）
你：回到 omni 系统 → SKU 详情页 → 「+ 登记动作」
你：填写极简表单：
       - 资产类型：主图（下拉）
       - 变更描述："新主图突出零添加场景"（一句话）
       - 截图：上传 v3 截图（拖拽上传）
       - 优化意图："提升点击率"（下拉）
       - 期望影响：[CTR, CVR]（多选）
你：点击保存 → 系统记录 change_event
系统：7 天后自动跑前后对比 → 生成验证报告
```

#### 场景 4：周末复盘

```
周日晚上 21:00
你：进入「决策与复盘」页面
你：看到本周决策状态：
       - 已执行 8 / 已验证 5 / 待执行 3
       - AI 建议命中率 67%（5 正向 / 3 待验证 / 2 无显著）
你：逐个查看 5 条已验证的动作 → 看前后对比卡
你：把成功案例归档（"主图零添加"策略 → 标记为可复用）
你：把失败案例标注原因（"低估了人群偏好差异"）
你：5 分钟内完成本周复盘
```

---

## 三、用户故事

### 故事 1：自动巡店推送

**As a** 老板  
**I want** 每天早上打开系统就能看到"今天值得关注的 3-5 件事"  
**So that** 我不需要从一堆 dashboard 中自己找问题，直接处理异动

**验收标准**：
- [ ] 系统每天 08:30 前完成数据抓取
- [ ] 工作台首页推送 3-5 条卡片，按重要程度排序
- [ ] 每条卡片包含：SKU 名 + 异动类型 + 关键指标变化 + 一键跳转
- [ ] 卡片支持 3 种状态：🟢 正向（动作生效）/ 🔴 负向（指标恶化）/ 🟡 待办（AI 建议未处理）
- [ ] 数据抓取失败 → 通过 NotificationChannel 推送（默认前端通知；企微留端口） + 卡片显示"⚠ 抓取失败，待人工介入"
- [ ] 当日无异动时，显示"今日无异动"+ 显示常规健康指标

**优先级**：P0（核心）

---

### 故事 2：单 SKU 一站式视图

**As a** 老板  
**I want** 在一个页面看到一个 SKU 的所有相关信息（数据/动作/AI 诊断）  
**So that** 我不用在多个模块之间来回切换、复制粘贴信息

**验收标准**：
- [ ] SKU 详情页路径：`/sku/[id]`
- [ ] 顶部展示：SKU 名 / 抖店链接 / 当前状态标签 / 最近 7 天 GMV
- [ ] 三个 Tab：「概览」「动作」「AI 诊断」
- [ ] 「概览」Tab：14 天 GMV/UV/CTR/CVR 趋势图（叠加动作变更竖线）
- [ ] 「动作」Tab：时间轴展示所有 change_event，每个可展开查看截图 / 描述 / 验证结果
- [ ] 「AI 诊断」Tab：列出与本 SKU 相关的 decision_log 条目，每条可"采纳/拒绝/延后"

**优先级**：P0（核心）

---

### 故事 3：极简动作登记

**As a** 老板  
**I want** 用最少的步骤登记我刚刚做的变更  
**So that** 这件事不会成为我的负担，我愿意每天坚持登记

**验收标准**：
- [ ] 入口：SKU 详情页右上角「+ 登记动作」按钮 + 工作台首页快捷入口
- [ ] 表单字段：
  - SKU（默认当前 SKU，可下拉切换）
  - 资产类型（下拉：主图 / 详情页 / 标题 / 价格 / 视频素材 / 人群包 / 其他）
  - 变更描述（单行文本，必填，限 100 字）
  - 截图（拖拽上传，可选但推荐）
  - 优化意图（下拉：提升点击 / 提升转化 / 提升曝光 / 降低跳失 / 其他）
  - 期望影响指标（多选：CTR / CVR / GMV / UV / 加购率 / 客单价）
- [ ] 单次登记 ≤ 60 秒（性能要求 + 字段精简）
- [ ] 提交后立即可见在「动作」Tab 时间轴
- [ ] 7 天后系统自动跑验证（无需用户操作）

**优先级**：P0（核心）

---

### 故事 4：动作前后对比卡

**As a** 老板  
**I want** 在每个动作执行 7 天后看到清晰的"做了 vs 没做"效果对比  
**So that** 我知道哪些手段真正有效，哪些是浪费时间

**验收标准**：
- [ ] 触发：动作执行后第 7 天 00:00 自动跑验证
- [ ] 对比窗口：执行前 7 天 vs 执行后 7 天（同 SKU）
- [ ] 对比指标：CTR / CVR / GMV / UV（4 个核心指标）
- [ ] 对比卡内容：
  - 4 个指标各自的"前 vs 后"绝对值 + 相对变化 %
  - 自动判定：🟢 正向（≥3 个指标改善 ≥10%）/ 🔴 负向（≥3 个指标恶化 ≥10%）/ 🟡 无显著（其他）
  - 一句话总结（GPT 生成）："改主图后 CTR +23%、CVR -5%，整体偏正向，建议保留"
- [ ] 对比卡持久化到 `verification_mvp` 表
- [ ] 在 SKU 详情页「动作」Tab 内联显示

**优先级**：P0（核心）

---

### 故事 5：AI 诊断输出落库（决策日志）

**As a** 老板  
**I want** 所有 AI 给的建议都自动存档，不会用完即丢  
**So that** 我可以追踪 AI 的命中率，让系统越用越准

**验收标准**：
- [ ] 所有 AI 输出强制写入 `decision_log_mvp` 表
- [ ] 数据来源（source_module）至少覆盖：
  - `roundtable`（圆桌讨论）
  - `scout_anomaly`（异动检测自动诊断）
  - `manual_diagnosis`（你手动触发的"启动深度诊断"）
- [ ] 每条决策包含：标题 / 摘要 / 完整内容 / 关联 SKU / 状态（pending/adopted/rejected/executing/verified）
- [ ] 「采纳」操作：自动创建 change_event（资产类型 / 描述从决策内容提取）
- [ ] 「拒绝」操作：要求填一句话原因
- [ ] 「延后」操作：设提醒日期
- [ ] 7 天后系统自动验证：如果决策已采纳并产生 change_event，关联到对应的 verification 结果

**优先级**：P0（核心）

---

### 故事 6：失败通知与自愈

**As a** 老板  
**I want** 系统出问题时立即知道，不要默默挂掉  
**So that** 我不会在某天发现"过去 3 天根本没抓数据"

**验收标准**：
- [ ] scout-agent 任意 step 失败 → 重试 3 次（指数退避）
- [ ] 重试后仍失败 → 通过 **NotificationChannel** 推送（默认前端站内通知 + 浏览器原生通知；企微 webhook 留 `.env` 端口可后续补齐）。消息含错误类型 + runbook 名 + 时间
- [ ] 三平台登录态过期 → 特殊处理：前端显示"扫码续期"按钮 + 推送通知（标识哪个平台 expired）
- [ ] 连续 3 天某 step 失败 → 升级通知（"可能 UI 改版，请人工介入"）
- [ ] 失败的 runbook 在前端 `/scout/runs` 页面可见，可手动重试

**优先级**：P0（核心）

---

### 故事 7：周末复盘视图（极简）

**As a** 老板  
**I want** 周末花 5 分钟看完本周所有决策的命中情况  
**So that** 我知道哪类手段最有效，下周更聪明地选择

**验收标准**：
- [ ] 入口：工作台 → 「本周复盘」按钮（周日晚上自动突出）
- [ ] 页面内容：
  - 本周决策汇总卡（已执行 X / 已验证 Y / 待执行 Z）
  - AI 命中率（正向 / 待验证 / 无显著 / 负向 比例）
  - 已验证动作列表（按效果排序，可展开看前后对比卡）
  - "本周亮点"和"本周教训"分组
- [ ] 支持归档操作：把成功动作标记为"可复用策略"

**优先级**：P1（次要，2 周内交付）

---

### 故事 8：抖店登录态续期

**As a** 老板  
**I want** 抖店 cookie 过期时能快速重登，不影响系统运行  
**So that** 系统能持续可靠地跑下去

**验收标准**：
- [ ] 登录态检测：每次 runbook 启动前检查 cookie 有效性
- [ ] 过期检测：自动尝试访问 `compass.jinritemai.com/shop/home`，若被 302 到登录页 → 标记为过期
- [ ] 通知：推送企微 + 系统页面顶部红条提示
- [ ] 续期入口：`/scout/sessions/douyin/relogin` → 在前端弹出 Playwright 浏览器窗口让你扫码 → 扫码后自动保存 storage_state
- [ ] 续期完成后 → 自动重跑当天失败的 runbook

**优先级**：P0（核心）

---

## 四、功能需求

### 4.1 巡店自动化（scout-agent）

#### 4.1.1 模块定位

**新建独立服务**：`services/scout-agent`，端口 `:8009`

**为什么独立**：
- 电商后台登录态管理比 news-aggregator 的 harvester 复杂
- 巡店是定时强约束任务，与按需触发的 harvester 调度模式不同
- 共享底层 Playwright 工具类（抽到 `services/_shared/playwright_utils/`）

#### 4.1.2 三平台抓取范围（v1.4 终版，8 份 runbook）

> **v1.4（2026-05-02）调整**：3 平台调研后从原 4 份 → 改为 **8 份 runbook**，每份 runbook 跨多平台聚合数据。

##### Runbook 总览

| Runbook | 主题 | 主要数据源 | 频率 | 工时估算 |
|---|---|---|---|---|
| **A** | 全店日报 | 罗盘首页+退款+体验分 + 抖店后台 6 待办数 | 每天 22:00 | 3 天 |
| **B** | SKU 详情 | 罗盘 product-detail 7 Tab + 抖店后台 SKU 主数据/库存/商品诊断 + 云图 SPU 5A | 每天 | 5 天 |
| **C** | 客服与原声 | 罗盘客服分析+用户原声 + 抖店后台评价管理 4 Tab | 每天 | 3 天 |
| **D** | 搜索与流量与营销 | 罗盘流量来源/搜索引流词 + 抖店后台营销活动 + 云图搜索 SOV | 每天 | 3 天 |
| **E** | 人群与机会 | 罗盘用户偏好 + 抖店后台用户中心 + 云图 5A 资产/5A 流转/GMV TO 5A | 每天 | 4 天 |
| **F** | 物流与履约 | 抖店后台物流诊断 3 Tab + 罗盘物流分析 | 每天 | 1 天 |
| **G** | 品牌心智 | 云图品牌心智 3 指标（品牌+商品级）+ 行业心智发现 | 每天 | 2 天 |
| **H** | 品牌资产+触点效能 | 云图触点效能 + 商品 4 Tab + AI 总结 | 每天 | 3 天 |

##### 详细抓取页（按平台分组）

**罗盘（compass.jinritemai.com）—— 12 个页面**：

| 页面 | URL slug | 主要字段 | runbook |
|---|---|---|---|
| 首页 | home | 用户支付金额 / UV / 客单 / 退款率 / 体验分 | A |
| 经营分时 | business-part | 24 小时分时 GMV / UV | A |
| 全店成交 | sell-analysis | 流量来源占比（直播/短视频/商品卡/搜索/达人/付费） | D |
| 退款分析 | refund-analysis | 退款率 / 退款金额 / 待办退款 | A |
| 商家体验分 | ecology-experience-score | 4 大子维体验分 | A |
| 商品列表 | commodity-product-list | 全 SKU GMV / UV / UV 价值 | B |
| 商品详情 | product-detail | 5 SKU 各 7 Tab（源/流量/流量人群/内容/商品卡/售后/人群分析） | B |
| 客服分析 | service-customer-analysis | 会话量 / 响应时长 / 咨询意图 TOP | C |
| 用户原声 | service-user-sound | 差评率 / 差评原因标签云 | C |
| 搜索引流词 | search-drainage-terms | 词级 UV/加购/成交 | D |
| 用户偏好 | biz-center-business-center-crowd-user-buy | 机会总结（本店没卖但用户爱买） | E |
| 物流分析 | logistics-diagnosis-index | 揽收/干线/末端时效（3 个粗指标） | F |

**抖店后台（fxg.jinritemai.com）—— 8 个页面**：

| 页面 | URL slug | 主要字段 | runbook |
|---|---|---|---|
| 店铺首页 | mshop-homepage-index | **6 待办数实时**（待发货/待售后/待评论/待审核/异常/申诉） | A |
| 商品列表 | g-list | **SKU 主数据**（41 SKU 含 ID/状态/上架时间/总库存） | B |
| 库存管理 | g-stock-manage-list | 库存预警 + **库存变更记录**（双轨动作日志兜底） | B |
| 商品诊断 | growth-common-growth-shelf | 优质/优秀/待优化/衰退单品分类 | B |
| 评价管理 | maftersale-comment | **4 Tab**（评价概览/回复/分析/实拍/邀请） | C |
| 物流诊断 | logistics-project-diagnosis-index | **3 Tab**（揽收时长 / 超时单分布 / 物流商异常率） | F |
| 用户中心 | mvip-consumer | 用户总人次 / 新老客金额 / 会员金额 | E |
| 营销活动 | 活动广场 + 营销工具 + 优惠券 + 单品直降 | 在跑活动数 / 优惠券核销 / 大促报名状态 | D |

**云图（yuntu.oceanengine.com）—— 9 个页面**：

| 页面 | URL slug | 主要字段 | runbook |
|---|---|---|---|
| 首页 | home-overview | 5A 总资产 / 月活会员金额 / 5A 心电图（Dwell/Connection/Increase） | E |
| 5A 关系资产 | assets-crowd-distribution | **6 张大卡**（O/A1-A5）+ 行业对比 X% + 趋势 | E |
| 5A 关系流转 | assets-crowd-flow | **6 场景**（拉新/蓄水/种草/直播转化/种草转化/复购）+ 流转沙基图 | E |
| GMV TO 5A 概览 | assets-gta-overview | 5A 成交占比 / O 机会成交占比 / A3 占 5A 比例 | H |
| GMV TO 5A 路径 | assets-gta-deal | 5A 成交路径转化率（按 A 阶段） | H |
| 品牌心智 | image-mind-monitor | 联想量 / 行业份额 / 美誉度 / 偏爱度（品牌级 + 5 SKU 商品级） | G |
| 机会心智发现 | image-mind-discover | 行业心智增量榜 / 行业心智趋势榜 | G（每周）|
| 商品 4 Tab | product-productOverview-* | 概览分析 / 货品结构 / 带货矩阵 / 流量来源 | H |
| 搜索 | search-overview | 品牌曝光 / 品牌搜索人数 / 搜索 SOV / 搜索成交 | D |
| 触点效能 | evaluation-* | **投放资源分布**（通投/UGC/品牌广告/达人营销，部分替代千川） | H |

#### 4.1.3 Runbook 设计

每份报表 = 一份 YAML runbook，存放在 `services/scout-agent/runbooks/douyin/`：

```yaml
# 示例：services/scout-agent/runbooks/douyin/单品概览.yaml
name: 抖店日报-单品概览
schedule: "0 30 8 * * *"   # 每天 08:30
platform: douyin
shop_id: "{{SHOP_ID}}"

session:
  storage_state: ./sessions/douyin_compass.json
  recheck_url: https://compass.jinritemai.com/shop/home
  on_expired: notify_wecom

steps:
  - id: navigate
    action: goto
    url: https://compass.jinritemai.com/shop/product/single-overview

  - id: filter_yesterday
    action: click_then_select
    selector: "#date-picker"
    value: yesterday

  - id: filter_skus
    action: multi_select
    selector: ".product-filter"
    values: "{{MVP_SKU_IDS}}"

  - id: export_csv
    action: click_and_download
    selector: 'button:has-text("导出")'
    save_to: ./downloads/抖店_单品_{date}.csv
    timeout: 60000

  - id: parse_csv
    action: parse_csv
    file: ./downloads/抖店_单品_{date}.csv
    schema: douyin_single_product_metrics
    write_to: daily_metric_mvp

  - id: detect_anomalies
    action: invoke_anomaly_engine
    sku_filter: "{{MVP_SKU_IDS}}"
    write_to: anomaly_mvp
```

#### 4.1.4 异动检测算法（MVP 简化版，v1.4 扩充）

> **三大判断口径**：环比（vs 7 日均值）+ 行业对比（罗盘行业百分位 + 云图对比品牌均值）+ 5A 流转健康度

| 类别 | 条件 | 判定为异动 |
|---|---|---|
| **GMV** | 单日用户支付金额跌幅 > 25%（vs 7 日均值）| 🔴 紧急 |
| **GMV** | 单日用户支付金额涨幅 > 50%（vs 7 日均值）| 🟢 正向 |
| **CTR / CVR** | 连续 3 天下滑 | 🔴 趋势恶化 |
| **流量** | 当日点击数为 0 / UV 跌幅 > 50% | 🔴 异常（可能下架/限流） |
| **评价** | 评价中出现 ≥3 条差评（评分 ≤2）/ 实拍占比断崖下跌 | 🟡 客户问题 |
| **物流** | 当日超时单 > 3 单 / 揽收时长 > 行业均值 1.5 倍 | 🟡 物流风险 |
| **体验分** | 总分 < 4.0 / 任一子维下降超过 5 分 | 🔴 体验降级 |
| **店铺待办** | 待发货 > 5 / 待售后 > 3 / 异常订单 > 0 / 申诉中 > 0 | 🟡 运营提醒 |
| **5A 资产** | 6 卡任一**超过同行 X%** 连续 3 天下行 | 🔴 品牌资产风险 |
| **6 场景流转** | 任一场景超同行 X% 持续低于 30%（远低于行业）| 🔴 场景动作不足 |
| **品牌心智** | 联想量 / 美誉度 / 偏爱度任一连续 3 天下行 | 🟡 心智衰退 |
| **触点效能** | 单一触点占比 > 80%（结构失衡）| 🟡 投放结构告警 |
| **行业排名** | 商品行业排名连续下降 > 50 名 | 🟡 类目竞争位置下滑 |

#### 4.1.5 调度与监控

- 调度：APScheduler（与 video-analysis 服务一致）
- 监控页面：`/scout/runs` 列表 + 单 run 详情页（含 step 日志 + 截图归档）
- 失败重试：每 step 重试 3 次，指数退避 2/4/8 秒

---

### 4.2 SKU 详情页（极简版）

#### 4.2.1 路径与布局

```
/sku/[id]
├── 顶部信息卡（SKU 名 / 抖店链接 / 状态 / 最近 7 天 GMV / 主推等级）
└── Tab 区
    ├── [概览]   ← 默认
    ├── [动作]
    └── [AI 诊断]
```

#### 4.2.2 Tab 详细规格

**「概览」Tab**：
- 14 天趋势图（GMV / UV / CTR / CVR 4 条线，可单独勾选）
- 趋势图叠加动作变更竖线（鼠标悬停显示动作描述）
- 关键指标卡（昨日值 / 7 日均值 / 14 日均值 / 环比）
- 异动事件列表（如有）

**「动作」Tab**：
- 时间轴：从最新到最旧的 change_event
- 每个事件展示：时间 / 资产类型图标 / 描述 / 截图缩略图 / 验证状态徽章
- 点击展开：完整描述 / 大图 / 前后对比卡（如已验证）
- 右上角「+ 登记动作」按钮

**「AI 诊断」Tab**：
- 顶部：「启动深度诊断」按钮
- 列表：与本 SKU 相关的 decision_log（按时间倒序）
- 每条决策卡：标题 / 摘要 / 状态徽章 / 操作按钮（采纳/拒绝/延后）
- 点击展开：完整内容 + 来源（圆桌/异动/手动）

#### 4.2.3 性能要求

- 页面首次加载 ≤ 1.5 秒
- 趋势图渲染 ≤ 0.5 秒
- 切换 Tab 无明显卡顿

---

### 4.3 决策日志（极简版）

#### 4.3.1 数据写入路径

| 来源 | 触发时机 | 写入字段 |
|---|---|---|
| 圆桌讨论 | 每次圆桌会议结束 → 自动调用 `decision_log.create()` | source_module=roundtable, full_content=summary |
| 异动检测 | 检测到异动 + 自动跑诊断 → 写入 | source_module=scout_anomaly, type=anomaly |
| 手动深度诊断 | SKU 详情页点击「启动深度诊断」→ 写入 | source_module=manual_diagnosis |

#### 4.3.2 状态机

```
pending（默认） ──采纳──► executing ──执行done──► verified
              ──拒绝──► rejected
              ──延后──► postponed（设提醒日期）
```

#### 4.3.3 列表页（极简）

- 路径：`/decisions`
- 仅展示列表（无筛选 / 无批量操作 / 无搜索）
- 每行：状态徽章 / 标题 / 来源 / 关联 SKU / 创建时间 / 操作按钮

> ⚠️ 完整的决策中心（筛选/批量/状态机完整流转）留给路径 B。

---

### 4.4 动作登记 + 前后对比卡

#### 4.4.1 登记表单详细字段

| 字段 | 类型 | 必填 | 默认值 | 限制 |
|---|---|---|---|---|
| sku_id | dropdown | ✓ | 当前 SKU | **全店 41 SKU 列表**（系统自动同步，重点池 SKU 顶部置顶 + 标 ⭐）|
| asset_type | dropdown | ✓ | - | **12 大类**（v1.4 终版：product/asset/price/ad/content/audience/talent/service/campaign/shop_ops/user_reach/brand_strategy）|
| change_description | textarea | ✓ | - | ≤100 字 |
| screenshot | file upload | × | - | jpg/png，≤5MB |
| optimization_intent | dropdown | ✓ | - | 提升点击/提升转化/提升曝光/降低跳失/其他 |
| expected_kpis | multi-select | ✓ | - | CTR/CVR/GMV/UV/加购率/客单价 |
| executed_at | datetime | ✓ | now() | 不能是未来 |

#### 4.4.2 前后对比卡逻辑

```python
# 7 天后自动触发（celery beat / APScheduler）
def verify_change_event(event_id):
    event = get_event(event_id)
    sku_id = event.sku_id
    executed_at = event.executed_at

    pre_window = (executed_at - 7d, executed_at)
    post_window = (executed_at, executed_at + 7d)

    pre_metrics = aggregate_metrics(sku_id, pre_window)
    post_metrics = aggregate_metrics(sku_id, post_window)

    deltas = {
        kpi: {
            "pre": pre_metrics[kpi],
            "post": post_metrics[kpi],
            "delta_abs": post_metrics[kpi] - pre_metrics[kpi],
            "delta_pct": (post_metrics[kpi] - pre_metrics[kpi]) / pre_metrics[kpi] * 100,
        }
        for kpi in ["ctr", "cvr", "gmv", "uv"]
    }

    # 自动判定
    improved = sum(1 for d in deltas.values() if d["delta_pct"] >= 10)
    declined = sum(1 for d in deltas.values() if d["delta_pct"] <= -10)
    if improved >= 3:
        verdict = "positive"
    elif declined >= 3:
        verdict = "negative"
    else:
        verdict = "neutral"

    # GPT 一句话总结
    summary = await llm_summarize(deltas, event.change_description)

    save_verification(event_id, deltas, verdict, summary)
```

---

### 4.5 工作台首页

#### 4.5.1 布局

```
┌─ 今日巡店状态 (已完成 / 进行中 / 失败) ─────────────────┐
│ ✓ 单品概览 - 08:32 完成                              │
│ ✓ 流量来源 - 08:35 完成                              │
│ ✓ 评价管理 - 08:38 完成                              │
│ ⚠ 商品权重分 - 失败 [重试]                           │
└──────────────────────────────────────────────────────┘

┌─ 今天值得关注 (3) ─────────────────────────────────────┐
│ 🔴 SKU-A001 GMV 连跌 4 天 [跳转 SKU 详情]              │
│ 🟡 SKU-A003 待您回复：4/24 圆桌建议未处理 [查看]        │
│ 🟢 SKU-A005 主图改版生效：CVR +50% [查看对比]          │
└──────────────────────────────────────────────────────┘

┌─ 本周决策状态 ──────────────────────────────────────────┐
│ 已执行 5 / 已验证 3 / 待执行 2                          │
│ AI 命中率 60%（3 正向 / 0 负向 / 0 待验证）             │
│ [查看详细周报]                                         │
└────────────────────────────────────────────────────────┘
```

#### 4.5.2 异动卡片优先级排序

```
1. 紧急异动（GMV 大跌 / 0 点击）
2. 待您处理的 AI 建议（pending 超过 24h）
3. 验证完成的成功动作
4. 趋势性异动（连续 N 天）
```

---

## 五、非功能需求

### 5.1 性能

| 指标 | 要求 |
|---|---|
| 巡店任务总耗时 | ≤ 30 分钟（**8 份 runbook 跨三平台**，含视觉分析 + 重点池 ~9 SKU 深度抓取） |
| 工作台首页加载 | ≤ 1 秒 |
| SKU 详情页加载 | ≤ 1.5 秒（重点池 SKU 命中本地数据；非重点池 SKU 首次打开按需触发抓取，可加 loading）|
| 动作登记表单提交 | ≤ 1 秒 |
| 数据库查询（单 SKU 14 天数据） | ≤ 200ms |

### 5.2 稳定性

| 指标 | 要求 |
|---|---|
| 连续 7 天无人工干预（除登录态续期） | 必达 |
| 单 runbook 任务成功率 | ≥ 95% |
| 三平台 cookie 续期周期 | 7 天检测，≤2 小时内通知用户（罗盘+抖店后台共用 / 云图独立，分别检查） |

### 5.3 安全

| 项 | 要求 |
|---|---|
| 抖店登录态文件 (storage_state.json) | 本机加密存储 |
| 数据库连接 | 仅本机 / 内网，不暴露公网 |
| Gemini API key | 环境变量，不入仓库 |
| 截图与 CSV 文件 | 本机 `downloads/` 目录，不上传云端 |

### 5.4 可观测性

| 项 | 要求 |
|---|---|
| 每次 runbook 执行 | 完整日志可查（前端 `/scout/runs/[id]`） |
| 失败通知 | **NotificationChannel**（默认前端站内通知；企微 webhook 留 `.env` 端口可后续启用），包含错误类型 / 时间 / runbook 名 |
| 数据完整性 | 每天凌晨 02:00 跑校验：**全店 SKU × 8 份 runbook 关键字段** + **重点池 ~9 SKU × 深度字段（product-detail 7 Tab + SPU 5A）** 是否齐全 |

### 5.5 兼容性

- 浏览器：Chrome 120+（Playwright 内嵌）
- 操作系统：Windows 10/11
- 屏幕：≥1440×900

---

## 六、数据模型（极简版）

> ⚠️ 临时简化结构，**严格作为路径 B 数据模型的子集**。路径 A 跑完后，通过 SQL 迁移直接进入路径 B 的正式表，零数据丢失。

### 6.1 临时 Schema：`mvp_*`

```sql
-- 6.1.1 SKU 主数据（5 条记录）
CREATE TABLE mvp_sku (
    id              VARCHAR PRIMARY KEY,        -- "SKU-A001"
    name            VARCHAR NOT NULL,           -- "零添加生抽 500ml"
    category        VARCHAR,                    -- "调味品/酱油"
    -- 路径 B 升级时映射到 omni_core.sku.spu_id
    douyin_product_id VARCHAR NOT NULL UNIQUE,  -- 抖店商品 ID
    douyin_url      TEXT,                       -- 抖店链接
    status          VARCHAR DEFAULT 'active',   -- active / paused / archived
    metadata        JSONB,                      -- 预留扩展字段
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 6.1.2 每日指标快照
CREATE TABLE mvp_daily_metric (
    id              SERIAL PRIMARY KEY,
    sku_id          VARCHAR NOT NULL REFERENCES mvp_sku(id),
    date            DATE NOT NULL,
    metric_name     VARCHAR NOT NULL,           -- "gmv" / "uv" / "ctr" / "cvr" 等
    value           NUMERIC,
    source_runbook  VARCHAR,                    -- "douyin/单品概览"
    source_run_id   VARCHAR,                    -- 关联到 mvp_runbook_run
    raw             JSONB,                      -- 平台特有字段
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(sku_id, date, metric_name)
);
CREATE INDEX idx_mvp_metric_sku_date ON mvp_daily_metric(sku_id, date);

-- 6.1.3 动作日志
CREATE TABLE mvp_change_event (
    id              SERIAL PRIMARY KEY,
    sku_id          VARCHAR NOT NULL REFERENCES mvp_sku(id),
    asset_type      VARCHAR NOT NULL,           -- main_image / detail_page / title / price / video / audience_pack / other
    change_description VARCHAR NOT NULL,
    screenshot_path TEXT,
    optimization_intent VARCHAR,                -- click / cvr / impression / bounce / other
    expected_kpis   JSONB,                      -- ["ctr", "cvr"]
    executed_at     TIMESTAMPTZ NOT NULL,
    actor           VARCHAR DEFAULT 'owner',    -- owner / ai_agent / team_member
    source_decision_log_id INT REFERENCES mvp_decision_log(id),
    verification_status VARCHAR DEFAULT 'pending',  -- pending / running / completed
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_mvp_event_sku_time ON mvp_change_event(sku_id, executed_at);

-- 6.1.4 验证结果
CREATE TABLE mvp_verification (
    id              SERIAL PRIMARY KEY,
    change_event_id INT NOT NULL UNIQUE REFERENCES mvp_change_event(id),
    pre_window_start TIMESTAMPTZ NOT NULL,
    pre_window_end  TIMESTAMPTZ NOT NULL,
    post_window_start TIMESTAMPTZ NOT NULL,
    post_window_end TIMESTAMPTZ NOT NULL,
    kpi_deltas      JSONB NOT NULL,             -- {"ctr": {pre, post, delta_abs, delta_pct}, ...}
    verdict         VARCHAR,                    -- positive / negative / neutral
    summary         TEXT,                       -- GPT 生成的一句话总结
    verified_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 6.1.5 AI 决策日志
CREATE TABLE mvp_decision_log (
    id              SERIAL PRIMARY KEY,
    source_module   VARCHAR NOT NULL,           -- roundtable / scout_anomaly / manual_diagnosis
    source_run_id   VARCHAR,                    -- 圆桌 session id / scout run id
    sku_id          VARCHAR REFERENCES mvp_sku(id),
    type            VARCHAR,                    -- diagnosis / suggestion / anomaly
    title           VARCHAR NOT NULL,
    summary         TEXT,
    full_content    TEXT,
    status          VARCHAR DEFAULT 'pending',  -- pending / adopted / rejected / postponed / executing / verified
    adopted_at      TIMESTAMPTZ,
    rejected_reason TEXT,
    postponed_until DATE,
    linked_change_event_id INT REFERENCES mvp_change_event(id),
    verified_at     TIMESTAMPTZ,
    verification_result JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 6.1.6 异动事件
CREATE TABLE mvp_anomaly (
    id              SERIAL PRIMARY KEY,
    sku_id          VARCHAR NOT NULL REFERENCES mvp_sku(id),
    detected_at     TIMESTAMPTZ DEFAULT NOW(),
    severity        VARCHAR,                    -- urgent / warning / positive
    metric_name     VARCHAR,
    description     TEXT,
    handled         BOOLEAN DEFAULT FALSE,
    related_decision_log_id INT REFERENCES mvp_decision_log(id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 6.1.7 巡店执行记录
CREATE TABLE mvp_runbook_run (
    id              VARCHAR PRIMARY KEY,        -- UUID
    runbook_name    VARCHAR NOT NULL,           -- "douyin/单品概览"
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    status          VARCHAR,                    -- success / failed / partial
    error           TEXT,
    log_path        TEXT,
    metadata        JSONB                       -- 包含每个 step 的状态
);

-- 6.1.8 抖店登录态
CREATE TABLE mvp_session (
    platform        VARCHAR PRIMARY KEY,        -- "douyin"
    storage_path    TEXT NOT NULL,              -- ./sessions/douyin_compass.json
    last_login_at   TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    health          VARCHAR DEFAULT 'unknown',  -- ok / expired / error
    notes           TEXT
);
```

### 6.2 路径 B 迁移路径

| 路径 A 表 | 路径 B 表 | 迁移逻辑 |
|---|---|---|
| `mvp_sku` | `omni_core.sku` (SPU) + `omni_core.sku_platform_link` | 拆成 SPU 主数据 + 抖店实例 |
| `mvp_daily_metric` | `omni_data.daily_metric` | 加 `platform_instance_id` 字段，关联到 sku_platform_link |
| `mvp_change_event` | `omni_decision.change_event` | 加 `platform_instance_id` |
| `mvp_verification` | `omni_decision.verification` | 直接迁移 |
| `mvp_decision_log` | `omni_decision.decision_log` | 加 `applies_to_platforms` |
| `mvp_anomaly` | `omni_data.anomaly` | 加 `platform` |
| `mvp_runbook_run` | `omni_data.scout_run` | 直接迁移 |
| `mvp_session` | `omni_data.platform_session` | 直接迁移，加 platform 主键 |

迁移 SQL 在路径 B 施工文档中详述。

---

## 七、API 设计（高层）

详细 API 列表在「02-施工-抖店MVP工程实施文档」。这里仅列模块边界：

| 模块 | 端口 | 主要端点 |
|---|---|---|
| **scout-agent**（新建） | :8009 | `/api/v1/scout/runbooks` / `/runs` / `/sessions` / `/anomalies` |
| **knowledge-engine** | :8002 | 复用现有 RAG 端点用于诊断 |
| **ad-review-service** | :8008 | 复用现有 review_engine 用于素材诊断 |
| **frontend BFF** | :3000 | `/api/omni/scout/*` / `/api/omni/sku/*` / `/api/omni/decisions/*` / `/api/omni/changes/*` |

---

## 八、验收标准（高层）

> 详细验收 case 见「03-验收-抖店MVP验收文档」

### 8.1 功能验收（10 条核心，全部必达）

- [ ] **V01** scout-agent **8 份 runbook**（A-H 跨三平台）全部通过测试，可在真实环境跑通
- [ ] **V02** 连续 7 天每天 08:30 自动跑完，成功率 ≥95%
- [ ] **V03** **全店 SKU 主数据**（自动同步） + **重点池 ~9 SKU 深度字段**每天齐全
- [ ] **V04** 异动检测引擎能正确识别 **13 类异动**（GMV 跌幅 / 5A 资产下行 / 6 场景流转低于行业 / 心智 3 指标恶化 / 触点失衡 等）
- [ ] **V05** 工作台首页 6 区块能正确展示（5A 心电图 / 6 待办 / 巡店状态 / 异动卡 / 6 场景策略卡 / 决策待办）
- [ ] **V06** SKU 详情页 3 个 Tab 全部可用，数据准确（含 SPU 5A 心电图 + 商品级心智）
- [ ] **V07** 动作登记表单提交后立即可见（**12 大类 + 双轨标记**），截图正常上传
- [ ] **V08** 7 天后自动跑前后对比卡，结果准确（人工对比验证至少 3 条）
- [ ] **V09** AI 决策全部落入 decision_log，可在 `/decisions` 列表查看
- [ ] **V10** **三平台 cookie** 过期场景测试通过：罗盘/抖店后台/云图任一过期后扫码续期可恢复

### 8.2 数据准确性验收

- [ ] 每日抓取数据与抖店罗盘后台手动查看的数据 **误差 < 1%**
- [ ] 前后对比卡的指标计算结果与手动用 SQL 计算一致

### 8.3 用户体验验收（你来打分）

- [ ] 早晨 5 分钟内完成巡店浏览
- [ ] 单 SKU 诊断页面信息一目了然，无需查阅其他页面
- [ ] 动作登记 ≤ 60 秒
- [ ] 周末复盘 ≤ 5 分钟

---

## 九、依赖与风险

### 9.1 外部依赖

| 依赖 | 风险等级 | 应对 |
|---|---|---|
| 抖店罗盘 UI 稳定性 | 🔴 高 | runbook 内置健康检查，连续 3 天失败自动告警 |
| 抖店后台 UI 稳定性 | 🔴 高 | 同上，且 SKU 主数据/库存变更记录是 MVP 关键路径 |
| 巨量云图 UI 稳定性 | 🔴 高 | 5A 资产/6 场景流转/品牌心智是 MVP 差异化能力，丢失后异动检测会少一半口径 |
| 三平台登录态续期 | 🔴 高 | 罗盘+抖店后台共用 cookie；云图独立登录；扫码续期流程 + 通知机制 |
| Gemini API 可用性 | 🟡 中 | 视觉分析失败降级为"截图存档"，不阻塞主流程 |
| 企微 webhook（v1.5 改为可选）| 🟢 低 | **MVP 默认不依赖企微**——通过 NotificationChannel 抽象，默认前端站内通知；webhook 留 `.env` 端口（`WECOM_WEBHOOK_URL` 可空），后续配齐时无需改代码即可生效 |
| 三平台反爬 | 🔴 高 | 随机延迟 1-3s / 真实 user-agent / 真实浏览器 profile / 不用 headless |

### 9.2 内部依赖

| 依赖 | 风险等级 | 应对 |
|---|---|---|
| 老板每日登记动作的依从性 | 🔴 高 | 表单极简（≤60 秒）+ 工作台快捷入口 + 周报中显示"未登记动作可能存在" + **双轨抓取兜底** |
| 老板每周做复盘的依从性 | 🟡 中 | 周日晚上推送提醒 |
| **重点池规则的代表性**（v1.5）| 🟢 低 | 系统**自动**按 GMV TOP 5 + 衰退 TOP 2 + 新品 TOP 2 选出，每周日重排，**无需老板配置**。规则透明，前端可见，可手动锁定/解锁单个 SKU |

### 9.3 技术风险

| 风险 | 应对 |
|---|---|
| Playwright 在 Windows 长时间运行的内存泄漏 | 每次 runbook 启动新 browser context，结束后销毁 |
| 截图归档磁盘占用增长 | 90 天后自动归档到压缩包 |
| 数据库表设计偏差导致迁移困难 | 严格按"路径 B 子集"原则设计，所有字段路径 B 都有对应位置 |

---

## 十、里程碑（**32 个工作日 / 约 4.5 周**，v1.4 终版）

| 阶段 | 天数 | 交付物 |
|---|---|---|
| **Phase 1：scout-agent 框架** | Day 1-3 | 服务骨架 + 三平台 cookie 登录态持久化 + 反爬测试（罗盘+抖店后台共用 cookie；云图独立登录） |
| **Phase 2：数据底座** | Day 4-6 | 全部 mvp_* 表创建（v1.4 含 mvp_5a_asset_daily / mvp_5a_flow_daily / mvp_stock_change_log / mvp_industry_benchmark）+ 异动检测引擎（13 类规则） |
| **Phase 3：罗盘 runbook** | Day 7-12 | runbook A/B/C/D 罗盘部分（首页 / 经营分时 / 全店成交 / 退款 / 体验分 / 商品列表 / product-detail / 客服分析 / 用户原声 / 搜索引流词 / 用户偏好 / 物流分析）= **12 个页面** |
| **Phase 4：抖店后台 runbook** | Day 13-19 | 抖店后台 8 页面（6 待办数 / SKU 主数据 / 库存变更记录 / 商品诊断 / 评价管理 4 Tab / 物流诊断 3 Tab / 用户中心 / 营销活动）+ **双轨动作日志兜底** |
| **Phase 5：云图 runbook** | Day 20-27 | 云图 9 页面（首页 / 5A 资产 / 5A 流转 / GMV TO 5A 概览+路径 / 品牌心智 / 商品 4 Tab / 搜索 / 触点效能）+ runbook G/H 完成 |
| **Phase 6：跨平台合并 + 8 份 runbook 整合** | Day 28-30 | 8 份 runbook（A-H）的跨平台数据 join + benchmark 字段融合 + 调度（APScheduler）+ 失败通知 |
| **Phase 7：前端核心页** | Day 31-32 (前) | 工作台首页（5A 心电图 + 6 待办数 + 异动告警 + 6 场景策略卡）+ SKU 详情页（3 Tab，含 SPU 5A 卡）+ 动作登记表单（12 大类 + 双轨提示） |
| **Phase 8：联调 + 试用 + buffer** | Day 32 (后) | 端到端测试 + 老板试用 + 修 bug |

---

## 十一、Out-of-Scope 明确清单

以下功能**明确不在路径 A 范围**，留给路径 B：

1. ❌ 天猫 / 京东数据接入
2. ❌ 完整 SKU 详情页（4 个额外 Tab：资产 / 内容 / 客服 / 数据高级视图）
3. ❌ 资产版本树（asset / asset_version 完整管理）
4. ❌ content-studio 与 SKU 的双向流转
5. ❌ 决策日志中心（筛选 / 批量 / 状态机完整流转）
6. ❌ 周度 dashboard 多图表可视化
7. ❌ 客服会话深度分析与情感曲线
8. ❌ 多 SKU 关联诊断（"酱油涨那老抽呢"）
9. ❌ 跨平台对比视图
10. ❌ 多人协作 / 权限管理
11. ❌ 移动端
12. ❌ 数据导出（Excel / PDF 周报生成）
13. ❌ 任务队列 / 后台 worker 抽象（用 APScheduler 简单调度即可）

---

## 附录

### A. 术语表

| 术语 | 含义 |
|---|---|
| 巡店 | 系统自动从抖店罗盘抓取数据的过程 |
| Runbook | YAML 描述的"一份报表抓取任务"配置 |
| Scout-agent | 巡店服务（services/scout-agent） |
| Change Event | 动作事件，记录"你做了什么变更" |
| Decision Log | 决策日志，记录所有 AI 输出与命中情况 |
| Verification | 验证，动作执行 7 天后自动跑前后对比 |
| Anomaly | 异动，自动检测的指标异常事件 |
| Verdict | 验证结论，positive / negative / neutral |
| 重点池 SKU（v1.5）| 系统按规则自动选出的 ~9 个深度抓取 SKU |
| 工作台 | 系统首页，每日打开第一眼看到的页面 |
| NotificationChannel（v1.5）| 通知抽象层，默认前端站内通知；企微/邮件/SMS 等多通道留端口可后补 |

### B. 重点池规则（v1.5，系统自动维护，无需老板配置）

> **v1.5 升级**：原"5 个 MVP SKU 占位符（待你填）"已废弃。系统现在**全自动**——首次跑 g-list runbook 自动同步全店 41 SKU 到 mvp_sku 表；之后系统按下面规则自动选出"重点池"做深度抓取（罗盘 product-detail 7 Tab + 云图 SPU 5A）。**老板不再需要手动选 / 填商品 ID**。

| 重点池槽位 | 数量 | 选择规则 | 重排频率 |
|---|---|---|---|
| 主推（GMV 高位）| 5 | 最近 30 天用户支付金额（gmv_paid）TOP 5 | 每周日 23:00 重排 |
| 衰退（需要诊断）| 2 | 连续 3 天 gmv_paid 下行 + 30 天 GMV 同比下滑 TOP 2 | 每周日 23:00 重排 |
| 新品（需要观察）| 2 | created_on_platform_at ≤ 30 天的 SKU 中流量最大的 TOP 2 | 每天 02:00 重排（新品上架快） |
| **总计** | **~9** | — | — |

**手动覆盖**：前端 SKU 详情页有"锁定为重点池"按钮，老板可手动锁定 / 解锁单个 SKU（最多锁定 5 个），规则之外的锁定 SKU 会**额外**进入重点池。

**非重点池 SKU**：
- 全店 41 SKU 都有**主数据 + 当日核心日报指标**（来自 g-list + commodity-product-list 一份导出）
- 老板点开任一非重点池 SKU 详情页时，**按需触发 product-detail 7 Tab + SPU 5A 抓取**（首次打开 30 秒 loading，之后命中本地缓存）

### C. 抖店罗盘报表字段映射表（详细）

| 罗盘字段 | 数据库字段 | 类型 | 说明 |
|---|---|---|---|
| 商品 ID | mvp_daily_metric.sku_id（通过映射） | VARCHAR | 抖店商品 ID 通过 mvp_sku.douyin_product_id 反查 |
| GMV | metric_name='gmv', value | NUMERIC | 商品成交金额 |
| UV | metric_name='uv', value | NUMERIC | 商品访客数 |
| 点击率 | metric_name='ctr', value | NUMERIC(0-1) | 商品点击率 |
| 转化率 | metric_name='cvr', value | NUMERIC(0-1) | 商品支付转化率 |
| 客单价 | metric_name='aov', value | NUMERIC | 客单价 |
| 加购率 | metric_name='add_to_cart_rate', value | NUMERIC(0-1) | 加购转化率 |
| ... | ... | ... | ... |

> 完整字段映射在「02-施工」文档第 6 章。

### D. 文档关联

| 关联文档 | 作用 |
|---|---|
| `02-施工-抖店MVP工程实施文档.md` | 工程实施细节，研发可直接拆 ticket |
| `03-验收-抖店MVP验收文档.md` | 详细测试 case + 数据校对方法 |
| `04-使用指南-抖店MVP使用指南.md` | 你日常使用的操作手册 |
| `../路径B-中台底座/01-PRD-中台底座产品需求文档.md` | 路径 B 总体设计，路径 A 是其前置验证 |

---

## 文档变更记录

| 版本 | 日期 | 修改内容 | 修改人 |
|---|---|---|---|
| v1.0 | 2026-04-30 | 初稿 | Claude (基于使用逻辑 v2 优化架构) |
| v1.4 | 2026-05-02 | 完成 3 平台调研后大改：8 份 runbook / 32 天工期 / 12 类 asset_type / 双轨动作日志 / 5 张新表 / 13 类异动规则 | Claude |
| v1.5 | 2026-05-02 | **去除 5 SKU 强制 + 企微强依赖**：SKU 改为全店自动同步 + 规则化重点池（每周自动重排）；通知改为 NotificationChannel 抽象（企微留端口） | Claude |

---

**【v1.5 已完成审阅，无待办】**

老板不再需要：
- ❌ 手动选 5 个 MVP SKU
- ❌ 手动填抖店商品 ID
- ❌ 手动配置企微 webhook
- ❌ 手动决定"重点池"

老板还需要做的（一次性）：
- 三平台扫码登录（罗盘+抖店后台共用 / 云图独立，约 5 分钟）
- 后续可选：配置企微 webhook（写到 .env 即可生效）
5. 5 个 MVP SKU 你想现在定，还是后面定？

**审阅结果反馈后，我开始批量写其余 7 份文档。**
