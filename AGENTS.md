# Omni Codex 项目契约

> 本文件只放每次任务都必须生效的硬规则、路由和完成标准。详细 SOP 必须放到匹配的 Skill、reference、代码契约或 runbook，禁止把业务百科和动态清单重新复制回来。

## 1. 适用范围与事实优先级

- 适用于 `E:/agent/omni` 仓库内的需求分析、开发、修复、审查和业务操作。
- 事实优先级：当前运行时代码/数据库/OpenAPI/MCP Catalog > versioned manifest/schema > 匹配 Skill > 设计文档/历史记录 > 记忆或口头推断。
- 不在本文件手工维护工具数量、SKU 清单、指标数量、当前重点池、cookie 状态或 migration 流水。需要时读取运行态；MCP 工具真值以 `services/knowledge-engine/app/mcp/doctor.py` 和 live catalog 为准。
- `docs/build-log.md` 只用于追溯施工历史；精简前规则快照在 `docs/archive/agents/AGENTS.pre-slim-2026-07-28.md`，不得把它当当前指令或事实源。
- 工作树可能包含用户未提交改动。修改前检查路径级 diff，保留无关改动；不得为本任务清理、覆盖或回退用户工作。
- 默认使用中文、先说结果、执行后必须汇报“做了什么 + 关键结果/数字 + 产物位置或唯一下一步”。

## 2. Skill 路由总则

- 用户话术命中 Omni 业务 Skill 时，优先使用业务 Skill，不走通用营销、战略、财务或创作 Skill，也不裸调底层工具另起流程。
- Skill 的 `description` 是触发真源；完整步骤只在命中后加载 `SKILL.md`。根文件只保留高风险消歧。
- 同一任务可组合多个 Skill，但每个阶段只能有一个主流程，明确输入、输出和交接点，禁止两套链路同时写同一产物。

| 用户目标 | 主入口 | 关键边界 |
|---|---|---|
| 结合现有系统把模糊需求写成可开工 PRD | [omni-fde-prd](.agents/skills/omni-fde-prd/SKILL.md) | 只做发现/PRD，不自动编码 |
| 实现或修改页面、API、MCP、service、表、数据源、状态或工作流 | [omni-feature-development](.agents/skills/omni-feature-development/SKILL.md) | 先锁影响合同，后写代码 |
| 找卖点/产品力/差异化 | [selling-point-finder](.agents/skills/selling-point-finder/SKILL.md) | 唯一卖点矩阵入口 |
| 单 SKU 成本/出厂价/利润/定价 | [cost-luru](.agents/skills/cost-luru/SKILL.md) | 读真账；真实成本需口令/Gate |
| 单 SKU 健康度 | [product-analysis](.agents/skills/product-analysis/SKILL.md) | 全店日报不走这里 |
| 全店今日/近几日脉搏 | [daily-store-pulse](.agents/skills/daily-store-pulse/SKILL.md) | 长周期经营分析另走分析工具 |
| 实时平台原始数 | [platform-data](.agents/skills/platform-data/SKILL.md) | 历史序列不触发实时抓取 |
| 从零圈人/新建人群包策略 | [crowd-sop](.agents/skills/crowd-sop/SKILL.md) | 已有包诊断不走这里 |
| 已有人群包诊断/提纯 | [audience-pack-diagnosis](.agents/skills/audience-pack-diagnosis/SKILL.md) | “做一个包”属于生成侧例外 |
| 已生成包的量级调整 | [audience-pack-sizing](.agents/skills/audience-pack-sizing/SKILL.md) | 一刀一刀看云图真覆盖 |
| 采纳后在云图执行 | [yuntu-audience-automation](.agents/skills/yuntu-audience-automation/SKILL.md) | 先 dry-run，最终写入需确认 |
| SKU 前链路/血缘 | [sku-pipeline](.agents/skills/sku-pipeline/SKILL.md) | 默认只到 `audience_pack_id`，不继续脚本或出片 |
| 只写脚本/文案/直播话术 | [script-writer](.agents/skills/script-writer/SKILL.md) | 不出图视频 |
| 纯 AI 种草/软种草/A3 视频 | [ai-planting-video](.agents/skills/ai-planting-video/SKILL.md) | 复用正式血缘和产品参考图 |
| 纯 AI 软广/O/A1 视频 | [ai-soft-ad-video](.agents/skills/ai-soft-ad-video/SKILL.md) | 优化前三秒与完播，不套种草痛点桥 |
| 真人编导/拍摄团队 Brief | [short-video-director-brief](.agents/skills/short-video-director-brief/SKILL.md) | 不走纯 AI 出片链 |
| 反推视频怎么拍 | [video-reverse](.agents/skills/video-reverse/SKILL.md) | 反推“打什么人”走人群逆向工具 |
| 淘宝竞品/对标 | [competitor-product-research](.agents/skills/competitor-product-research/SKILL.md) | 必须取真实竞品素材 |

高风险消歧：

- “包”+圈/做/出/写/受众怎么定 → 生成；诊断/提纯/适不适合投/太大太小 → 诊断或 sizing。
- “实时/现在” → `platform-data`；“历史走势/单指标” → `query_metric_nl`；“综合经营” → `generate_business_analysis`；“解释某条异常” → `explain_anomaly`。
- 纯 AI 正式出片走 `ai-planting-video` / `ai-soft-ad-video`；真人制作走 `short-video-director-brief`；临时 `generate_image` / `generate_video` 产物不得冒充正式血缘产物。
- A4 收割内容走 `generate_creative_pack(kind='video_harvest')`，不得套种草或软广的 intent 与北极星。
- 反推“怎么拍”走 `video-reverse`；反推“打什么人/对比画像”走 `reverse_audience_analysis`。
- 标签体系、标签路径和可勾选项优先 `query_yuntu_taxonomy`，不得用碎片 RAG 猜标签。

## 3. 新功能开发硬闸

只要任务新增或改变页面、接口、MCP Tool、service、数据库/字段、外部数据源、状态机、权限、审计、自动化或跨层工作流，就必须触发以下流程：

0. Codex SessionStart 自动运行开发就绪检查，报告当前 `HEAD/index/worktree`、READY PRD、活跃合同与运行资源；只在工作树或暂存区的资产属于候选实现，不属于已交付事实。
1. 若需求仍需系统发现或 PRD，先用 `omni-fde-prd`；已有 `READY` PRD则直接交给 `omni-feature-development`。
2. 使用 `omni-feature-development` 建立 `change_id`，状态按 `DISCOVERED → IMPACT_LOCKED → IMPLEMENTING → VERIFYING → GRAPH_DIFF_READY → COMPLETE` 推进。
3. 在 `IMPACT_LOCKED` 前只允许只读调查和合同/计划文件，不修改产品代码、migration 或运行配置。
4. 影响合同必须覆盖：复用/修改/新增/不做，UI、BFF/API/IPC、MCP、service、表/视图、外部 source、权限/Gate、审计、指标、测试、迁移、回滚和预期图谱差异。
5. 实施中出现合同外关键文件或新依赖，先更新影响合同和理由，再继续；禁止开发完后倒填一份看似完整的合同。
6. 完成合同必须记录实际 changed files、计划与实际偏差、测试命令与退出码、OpenAPI/doctor/migration/数据源证据、图谱 diff 和未完成项。
7. 文件已创建、接口能编译或单测局部通过都不等于完成；静态必需链路仍断裂时不得宣称 `COMPLETE`。
8. 本地验证、暂存候选与交付完成分开：只有不可变提交通过 CI 并生成与该 commit/tree 绑定的 delivery attestation，系统进度才可记为已交付。

轻量例外：纯文案/文档排版、只读解释、无行为变化的机械重命名可不建完整合同；但一旦跨越 UI/API/MCP/DB/source 任一边界，立即升级到标准流程。

风险只分四级：R0 只读无需合同；R1 单层可恢复修改由 Codex 自动走轻量检查且不等人工确认；R2 跨层/公开契约/治理/加法 migration 由 Codex 自动建完整合同；R3 外部发布、付费、密钥、共享库执行 migration、硬删除或客户端物理退役才要求一次明确 Human Gate。不得用头脑风暴、TDD、审查或额外工作树等仪式阻断普通开发。

## 4. 全链路工程合同

开发或审查新功能时，按真实链路逐层核对：

```text
用户入口/页面
→ Web BFF / REST / IPC
→ MCP Tool 或内部操作契约
→ Service / domain logic
→ DB table/view 或外部数据源
→ reader/consumer
→ 测试、审计、指标与前端状态
```

- 先搜索复用已有页面、route、tool、service、表、prompt 和组件；禁止为相同语义平行造第二套接口、表或脚本链。
- 自动发现只能证明存在性；业务必需边、owner、read/write、危险动作和合法根节点必须进入 feature manifest/合同，不靠 AST 或名称猜测。
- collector 或外部源失败时状态为 `unknown/stale`，不能伪报 `missing`；只有前后快照来源都成功且对象消失，才算 removed。
- 新前端必须有 loading/empty/error/success 四态；错误不能伪装为空；分页不得静默截断；关键交互要有键盘/文本替代；生成类输出接 `OutputFeedback` 并优先精确 `tool_call_id`。
- 新 REST/MCP 必须有明确输入输出 schema、错误语义、超时/幂等策略；MCP 进入注册表和 doctor，写操作尊重 Human Gate，调用走审计。
- 新 LLM Tool 必须 prompt 外置、返回 `trace.final_prompt/params/cost_estimate`，不得把动态业务规则硬编码进 Python。
- 新表/字段必须走 migration，优先加法兼容；核对仓库 ledger、运行库和 frozen track，说明回滚/恢复策略。
- 新外部数据源必须进入 endpoint catalog，声明 expected fields、认证状态、落库映射、freshness 和消费方；cookie/authorization/token/passphrase/secret 不得进入图谱、日志或测试 fixture。
- KE Python 代码变更需按当前运行方式重启/重载后再做 live 验证；prompt 模板可按其热加载契约验证，不得把两者混为一谈。

## 5. 业务数据、安全与内容边界

- 优先读取 `mvp_sku`、成本表、渠道费率、KB、pipeline lineage 和平台真数据；禁止编造卖点、规格、价格、资质、赠品、销量或投放结果。
- 数字结论区分“观察到的”和“可能的原因”。不能从相关性写成因果；样本不足必须标待验证，投前画像/向量分不能替代投后 CTR/CVR/完播率/GMV 等真实结果。
- 成本默认 public/shared 口径；real 成本必须由老板明确要求并通过口令，错误口令不得泄露任何真实成本。
- 正式内容资产必须挂 SKU→卖点→人群→脚本→素材血缘；临时旧链只作一次性试验，不能进入正式复盘。
- 归档、删除、发布、外部平台写入、真实成本修改和其他难恢复动作必须先展示目标、影响和恢复方式，再遵循 Gate/显式确认。
- 实际图谱事实不可手工改绿或硬删；个人视图隐藏与业务归档必须分开，归档保留数据和审计。
- 用户提到“之前的反馈/很多反馈/这些反馈处理了吗”时，先查真实反馈和未处理投诉，再按已修/待办汇报，不得凭记忆回答“没有”。

## 6. 对话推进规则

- 高成本生成、正式出片、外部写入和多阶段业务 SOP 每个关键 Gate 停下来等反馈，除非用户明确要求并授权连续执行。
- “继续/OK/通过”只有在上一条明确留下 `next_step` 或正处于多步流程时才推进；没有待续动作就说明已完成并询问新目标。用户提出新问题时丢弃旧的悬空“继续”。
- “重来/改/不行”默认在当前步骤重跑并注入新要求；局部重做只影响指定部分，除非底层工具不支持局部更新并已说明。
- 任何工具调用、文件修改、数据写入或产物生成后都要用完整人话汇报，不能只回“收到/待命/好了”。

## 7. 运行真源与最小验证

- MCP 实现：`services/knowledge-engine/app/mcp/tools/`
- MCP 注册/自检：`services/knowledge-engine/app/mcp/server.py`、`services/knowledge-engine/app/mcp/doctor.py`
- Prompt：`services/knowledge-engine/config/prompts/`
- 业务 Skills：`.agents/skills/`；详细规则只改 canonical Skill/reference，不在根文件复制。
- 项目配置/Hooks：`.codex/`
- 开发合同：`docs/dev-changes/<change-id>/`
- PRD 归档：`docs/prds/<prd-id>/`；Markdown/PDF 同版本、同 basename 成对发布，并登记 `docs/prds/README.md`。`docs/plans/` 与 `output/pdf/` 仅作历史兼容，不再接收新 PRD。
- 历史与 runbook：`docs/build-log.md`、`docs/multi-device/` 及相关设计文档。

常用自检：

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
python scripts/check_agent_policy.py --require-tracked
```

测试按变更风险选择目标套件；完成前必须运行能直接证明本次声明的命令并读取退出码，不得以旧日志或子代理口头报告代替。

## 8. 指令卫生

- 本文件 UTF-8 字节数目标不超过 12 KiB，CI 硬上限 16 KiB。
- 禁止把工具全量清单、动态数字、完整业务 SOP、历史 migration 说明、当前 SKU 状态或大段调试手册写回本文件。
- 新规则先判断落点：跨任务硬规则进根文件；重复工作流进 Skill；细节进一层 reference；机器事实进代码/schema；历史进 docs；可机械判定的约束进 Hook/CI。
- 子目录 `AGENTS.md` 只在 Codex 从对应目录启动时进入指令链，不能承载跨前后端任务的唯一硬规则。
- 修改本文件、Skill 或 Hooks 后必须在新 Codex 任务中验证加载与路由；当前会话不会自动重建指令链。
