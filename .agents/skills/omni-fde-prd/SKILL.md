---
name: omni-fde-prd
description: 把需要结合 omni 当前真实系统能力的模糊业务需求转成研发可开工、可验收的 PRD。老板说“这个需求怎么接进 omni”“先盘现有能力再出方案”“结合我的系统做 PRD”“别重复造轮子，给研发开工方案”“把需求拆到页面、接口、数据、状态和验收”，或虽未说 PRD 但要求把新功能落到现有代码、MCP、数据表、前端、自动化或业务工作流时触发。必须先只读核查仓库与运行契约，区分现状事实、用户确认、设计决策、假设和待确认，再写复用与缺口、范围、流程、数据/API/UI 影响、权限、异常、灰度回滚、验收和实施切片。不用于通用 PRD 写作、单纯产品策略或优先级、已有文档润色、只解释系统、直接编码或修 bug，也不接管已有 omni 业务 skill 能直接完成的业务动作。
---

# omni FDE 需求落地官

把老板的业务愿望接到 omni 的真实代码、数据和工作流上。先还原要解决的现场问题，再证明系统已经有什么，最后给出“复用、修改、拟新增、不做”的研发合同；不要把用户的一句话扩写成一篇看似完整但无法开工的文档。

## 路由边界

- 只有“业务需求 + 结合 omni 现状 + 需要落地设计”同时成立时使用本 skill。
- 直接执行找卖点、写脚本、算成本、SKU 体检、圈包、包诊断、出片等已有业务动作时，路由到对应业务 skill。
- 用户明确要直接实现或修 bug、且没要求先出 PRD 时，进入工程实施流程；不要强制加一轮 PRD。
- 只做通用产品战略、优先级或路线图时，用产品管理能力；只共同撰写或润色已有文档时，用文档共创能力。
- 创建或修改 skill 本身时，用 `skill-creator`；本 skill 负责设计将要进入 omni 的产品/系统能力。

## 必读资源

开始工作前完整读取：

1. `references/system-discovery.md`：事实源、检索顺序和证据规则。
2. `references/prd-contract.md`：固定章节、验收格式和 Definition of Ready。

最终成稿从 `assets/implementation-prd-template.md` 复制并按需求裁剪；不适用的章节写“不适用 + 原因”，不要直接删除。准备标记 `READY` 前，运行：

```powershell
python -X utf8 scripts/validate_prd.py <prd-path> --strict
```

用户明确只要聊天正文、不允许创建文件时，把完整 Markdown 经 stdin 传入。在 Windows PowerShell 5.1 中，普通文本管道会损坏中文，必须先转 UTF-8 Base64：

```powershell
$taskPrdBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($taskPrdText))
$taskPrdBase64 | python -X utf8 scripts/validate_prd.py - --stdin-base64 --strict
```

能保证 raw stdin 为 UTF-8 的环境可直接省略 Base64 和 `--stdin-base64`。

资源缺失、读不完整或验证脚本失败时，不得声称 PRD 已可开工。

## 工作状态

只使用三种状态：

- `DISCOVERY`：使用者、问题或目标仍不清楚，只能交付需求发现稿。
- `DRAFT`：方案已成形，但仍有影响 P0 开工的决策或证据缺口。
- `READY`：通过 Definition of Ready，研发可以按实施切片开工。

不要用“基本可用”“差不多 Ready”弱化闸门。状态必须写在 PRD 顶部和最终汇报中。

## 标准工作流

### 1. 形成需求复述卡

从用户原话和会话上下文提取：

- 谁在什么场景使用
- 当前问题、失败成本与现有绕行方式
- 想得到的业务结果与可观察完成信号
- 已给出的约束、时间要求、正反例和非目标

不要先发长问卷。只有当缺失信息会导致不同产品、权限边界、不可逆数据行为或明显不同成本时，才集中问最多三个阻塞问题，并给推荐默认项及各选项影响。可逆、局部、低风险的细节直接作为显式假设继续。

### 2. 只读核查当前系统

按 `references/system-discovery.md` 检索相关业务 skill、MCP tool、路由/service、schema/migration、前端、prompt、测试和运行契约。优先用 `rg` 定位，按需求相关性读取，不做全库漫游。

跨多个服务时可并行安排“现状/数据契约”“交互/异常”“验收/风险”检查，但主 agent 必须亲自核对进入 PRD 的关键证据。PRD 任务只授权只读调查和文档产出；不得顺手修改产品代码、数据库或外部系统。

关键结论使用以下标签：

- `[现状事实]`：由当前代码、schema、测试或安全的运行时查询证明。
- `[用户确认]`：老板明确给出的目标、规则或取舍。
- `[设计决策]`：本 PRD 提出的 V1 方案，不是现有能力。
- `[假设]`：可逆的默认项，必须附验证与回退方法。
- `[待确认]`：会阻塞 P0 或触发高风险副作用的决策。

不存在的 endpoint、table、tool、字段、页面和指标必须写成“拟新增”，禁止用将来方案描述当前系统。

### 3. 建立能力差距表

逐项回答：

| 分类 | 要回答的问题 |
|---|---|
| 复用 | 哪个现有 skill/tool/service/table/component 已满足，证据在哪里？ |
| 修改 | 哪个现有契约需要扩展，怎样保持兼容？ |
| 拟新增 | 现状确实没有什么，最小新增落点是什么？ |
| 不做 | 哪些需求退出 V1，为什么？ |
| 冲突 | 用户设想与现有业务铁律、权限、状态或数据口径哪里冲突？ |

沿真实链路检查入口 → UI/对话 → API/IPC/MCP → service → DB/外部系统 → 审计/反馈/指标。优先复用已有状态机、血缘和反馈飞轮，不另造平行入口。

### 4. 选择最小可闭环方案

默认给一个推荐 V1。只有确有架构、权限、成本或体验差异时才给 2–3 个方案；明确推荐项、放弃项和原因。以下情况必须停下请老板拍板：

- 改变核心业务口径、状态语义、血缘或历史兼容行为。
- 涉及不可逆 migration、删除/大回填、权限提升、真实成本或秘密凭证。
- 涉及发布、推送、采纳、广告平台创建等真实外部副作用。
- 新增付费依赖，或可能明显影响成本上限。
- 权威事实源冲突，且会改变 P0 设计。

暂停时先交付已核事实、冲突原因、推荐选项和最小拍板问题，不能只把问题抛回给老板。

### 5. 生成实施级 PRD

使用模板和 `references/prd-contract.md`。每项 P0 功能必须有 `FR-*`，每条验收必须有 `AC-*` 并能追到对应 FR。至少覆盖正常、空数据、无权限、依赖超时/失败、重复提交与部分失败；若某分支不适用，说明理由。

实施切片优先按可独立验收的纵向闭环拆分，而不是只按“前端/后端/数据库”横向分工。每个切片写清依赖、目标模块或文件、交付物、测试和完成条件；没有证据时不要编工期、效果数字或接口字段。

涉及 omni 时逐项检查：

- 新 MCP tool 是否加入 doctor 权威清单并经 `@tool_with_audit` 留痕。
- LLM tool 是否 prompt 外置、返回 trace、接规则注入、声明 grounding 与 fallback/hard gate。
- 新前端产物区是否有 `OutputFeedback`，执行后是否用人话汇报结果。
- 状态型产物是否保留版本、父子关系、血缘，以及需要时的 `draft → adopted` 人工闸门。
- 写操作、发布、推送、采纳、真实成本和外部系统动作是否有明确 Human Gate、幂等与审计。
- 审批/签名/能力链接是否把“通知”与“授权”分开，做到短期、最小范围、单用途、服务端复核状态，并处理 hash 存储、过期、撤销、重放和日志/Referer 泄漏。
- 现在审批、未来由 cron/worker 执行的延迟副作用，是否冻结授权范围与 payload，记录执行时间/渠道，支持过期与撤销，并在执行时防重留痕。
- 数字分析是否区分 observation/hypothesis，样本不足是否按 R-15 标待验证。
- 实时、日报和历史落库数据是否走正确的数据层级。
- migration、兼容、灰度、回滚、日志、指标和失败补偿是否可验证。

### 6. 验证与交付

先运行普通校验；只有要标 `READY` 时再运行 `--strict`。若用户禁止落文件，使用 stdin 模式，不能仅因“没有路径”把完整 PRD 自动降级。validator 只证明结构、ID 和基础覆盖完整，不证明源码证据、业务判断或拟新增 contract 真实正确；主 agent 仍须逐条复核关键证据。若校验失败，修正文档或降级为 `DRAFT`，不得删掉真实阻塞项来骗过校验。

文件型 PRD 的唯一归档根目录是 `docs/prds/`。每份 PRD 必须遵守以下发布合同：

- 为需求分配稳定的 `<prd-id>`，推荐 `YYYY-MM-DD-<slug>-prd`；版本使用 PRD 顶部的 `v1.0`、`v1.1` 等值。
- Markdown 与 PDF 必须由同一份最终 Markdown 生成，并以同 basename 成对保存：`docs/prds/<prd-id>/<prd-id>-<version>.md` 和 `.pdf`。
- 完全相同的一对文件可幂等重发；同一版本不可覆盖，Markdown 或 PDF 任一内容变化都必须提升版本号并发布新的一对文件。
- 先验证 Markdown；`READY` 使用 `--strict`。再用当次可用的 PDF 生成能力从这份最终 Markdown 渲染并目检，确认可打开、无空白页、表格和分页可读。
- 最后从当前仓库根运行 `.agents/skills/omni-fde-prd/scripts/publish_prd.py`，自动更新 `docs/prds/catalog.json` 与 `docs/prds/README.md`，不得手工编辑目录文件：

```powershell
python -X utf8 .agents/skills/omni-fde-prd/scripts/publish_prd.py publish `
  --markdown <final-prd.md> --pdf <final-prd.pdf> `
  --prd-id <prd-id> --title "<PRD标题>" --version <version> --status <status> `
  --root docs/prds
python -X utf8 .agents/skills/omni-fde-prd/scripts/publish_prd.py check --root docs/prds
```

`docs/plans/` 与 `output/pdf/` 是历史兼容位置：不移动、不删除、不再写入新 PRD。用户明确禁止创建文件时，可仅交付经 stdin 验证的 Markdown，此时必须说明没有生成 PDF，也不登记目录。

最终只汇报：

1. PRD 状态和一句话落地结论。
2. 主要复用项、拟改项和拟新增项。
3. 阻塞开工的决策或证据缺口；没有就写“无”。
4. 索引路径、Markdown/PDF 成对路径与验证结果。
5. 恰好一个下一动作；未经用户明确要求，不进入实现。

## 禁止

- 禁止把历史文档、旧 PRD 或 `docs/build-log.md` 当作当前实现证明。
- 禁止把用户设想、模型推断、竞品能力或未来接口写成 `[现状事实]`。
- 禁止读取或输出 `.env`、口令、cookie、token 等秘密。
- 禁止为显得完整而编交付天数、目标阈值、业务数字、平台能力或负责人。
- 禁止只给页面原型而漏掉状态、数据、权限、失败、审计、上线与回滚。
- 禁止在 PRD 任务里顺手实施代码；实现必须由老板另行授权。
