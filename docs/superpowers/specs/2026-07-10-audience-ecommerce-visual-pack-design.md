# 人群专属抖音电商主图与详情页视觉包设计

日期：2026-07-10

状态：四部分设计已由老板逐段确认，并通过无上下文读者盲审；待老板最终书面复核

方案：B——统一商详视觉包（Codex Skill + MCP 编排与审计）

## 1. 摘要

在现有「SKU → 卖点矩阵 → 人群匹配 → 人群画像 → 圈包 SOP → 内容」链路后，新增一条正式的商品视觉承接链：

```text
明确选定的 SKU / 卖点 / 人群 / 画像 / 圈包 / 可选软广脚本
  → 统一主图与详情页策划
  → 人群↔方案向量初筛
  → 老板审核策划
  → Codex 订阅内置图像能力生成场景
  → 真实产品图与准确中文确定性合成
  → 成图后三边向量审计 + 产品/OCR/事实硬质检
  → 只重做失败单元
  → 5 张主图 + 详情分屏 + 详情长图正式落库
```

最终固定产物为：

- 5 张可直接上传的 1:1 主图；
- 8–12 张详情分屏，本次寿喜烧样板固定 10 张；
- 1 张按分屏顺序拼接的详情长图；
- 1 份 `manifest.json`；
- 1 份包含逐图三边向量结果与硬质检结果的 `audit-report.json`。

实际 AI 出图由 Codex Skill 调用订阅内置图像能力，不经额外付费的 OpenAI 图像 API。MCP 负责读取真实数据、生成结构化方案、向量计算、合成、质检、拼接、版本与血缘落库。这里的无额外付费承诺只无条件覆盖“图像生成”；embedding 或可选的 MCP 视觉模型调用必须遵守第 21 节的计费策略，未知计费状态时 fail-closed。

## 2. 背景与现有缺口

现有 `generate_creative_pack` 已支持：

- `product_main_image`：输出 5–9 张主图设计 brief；
- `product_detail_page`：输出 8–12 段详情页设计 brief。

但它们目前仍是文案/设计稿节点，不是正式商品视觉出图链。现有缺口包括：

1. 商品主图与详情页只生成 brief，没有最终图片。
2. 旧 `generate_image` 不挂 pipeline 血缘，不适合正式资产。
3. `generate_storyboard_images` 面向视频分镜，默认资产语义、画幅和下一步均偏视频。
4. 主图没有“恰好 5 张”的后端硬校验。
5. 详情页标题契约和现有 scene parser 不一致，可能解析为空。
6. 没有详情分屏拼接成长图的能力。
7. 没有静态商品图专用的包装、标签、OCR、事实、安全区、重复度和整套叙事质检。
8. 现有向量粒度是画像级和脚本级，不能复核单张主图或单个详情分屏。
9. 现有向量能力只覆盖生成前或视频链；缺少“生成后的实际图片是否仍贴人群”的强制复核。
10. 产品参考图上传后未形成 SKU × 包装版本的权威登记。

本设计不另建第二套 SKU pipeline，也不复制现有卖点、人群和实验系统。它只补齐“商品视觉套组”这一缺口。

## 3. 目标

### 3.1 业务目标

1. 主图和详情页必须由同一版人群画像与同一套商品事实驱动。
2. 每张图都明确承接痛点、场景、情绪、卖点或信任任务，不能只做泛化商品展示。
3. 五张主图组成一个完整内容套组，而不是五张独立海报。
4. 详情页从痛点进入，经解决方式、使用、证据、规格和情绪结果完成承接。
5. 生成后必须复核人群、方案和实际成图的向量相近程度。
6. 包装、标签、规格和事实错误必须硬拦截，不得被高向量分抵消。
7. 所有图片可从资产反查到 SKU、卖点矩阵、人群、画像、圈包和来源内容。

### 3.2 工程目标

1. 精确输出 5 张 1:1 主图和 8–12 张详情分屏。
2. 每个视觉单元允许多次生成尝试，但只能有一个被采纳的资产。
3. 任何失败都返回明确错误、失败单元和下一步，不静默缺图。
4. 所有生成节点继续遵守 audit、trace、prompt 外置、反馈出口和多版本不覆盖。
5. 复用现有 embedding、`vector_presets`、`triangle_match` 和 pipeline 资产体系，不造第三套评分引擎。

## 4. 非目标

第一版不做：

1. 不在 MCP 后台无人值守调用付费图像 API。
2. 不承诺把内置图像能力锁成某个可见 API model slug；只记录 `generation_channel=codex_builtin`。
3. 不在图片中固化价格、折扣、赠品、销量或库存。
4. 不自动发布到抖店。
5. 不先做新的前端页面；首版以 Codex Skill 为唯一主入口。
6. 不声称向量分等于购买概率、CTR 或 CVR。
7. 不把某一张非首图或某一个详情分屏的变化直接归因为独立转化贡献。
8. 不用 AI 重画产品商标、中文标签、配料表或营养成分表。
9. 不把“订阅出图”描述成整条链所有模型调用都绝对零成本；向量和视觉审计单独披露 provider 与费用边界。

## 5. 核心决策

| 决策 | 结论 |
|---|---|
| 用户主入口 | Codex Skill `audience-ecommerce-visuals` |
| 正式策划入口 | MCP `prepare_ecommerce_visual_pack` |
| 成图复核与落库 | MCP `finalize_ecommerce_visual_pack` |
| 实际 AI 出图 | Codex 订阅内置图像能力 |
| 模型计费路径 | 订阅优先，不调用额外付费图像 API |
| 产品呈现 | 真实产品图锁定；场景生成与确定性合成结合 |
| 中文文字 | 确定性排版，不交给图像模型生成 |
| 向量复核 | 人群↔方案、方案↔成图、人群↔成图三边分开看 |
| 事实校验 | 确定性硬门槛，与向量分分层 |
| 版本单位 | 整套 visual pack 版本化；单图重做记 asset attempt |
| A/B 单位 | 整套 pack 为实验臂，每轮只变一个 slot/unit |
| 审批状态 | plan approval 与 final adoption 分成两个显式事务 |
| 计费策略 | `subscription_first` 默认 fail-closed；不静默切换到计费 provider |

## 6. 总体架构

### 6.1 职责边界

#### Codex Skill：`audience-ecommerce-visuals`

负责：

1. 识别用户话术和当前 SKU-pipeline 上下文。
2. 自动解析已选择的 SKU、人群、画像、圈包和可选来源软广脚本。
3. 调 `prepare_ecommerce_visual_pack`。
4. 把结构化策划展示给老板，停下等待确认。
5. 按 unit 逐张调用 Codex 内置图像能力。
6. 把最终文件复制到工作区指定目录。
7. 调 `finalize_ecommerce_visual_pack`。
8. 读取 `rerender_units`，仅重做失败单元。
9. 返回最终文件、血缘和审计摘要。

#### MCP 服务

负责：

1. 读取 pipeline 与 SKU 真实数据。
2. 校验上游血缘、状态和商品事实。
3. 输出统一的主图/详情页结构化策划。
4. 生成和保存向量源文本、相似度、相对排名及版本信息。
5. 登记产品参考图和实际渲染使用的参考图。
6. 执行确定性排版、尺寸规范化和详情长图拼接。
7. 执行静态视觉盲审、OCR、事实与产品一致性校验。
8. 保存 asset attempt、append-only audit run 和最终采纳结果。

### 6.2 两个人工闸门

1. **策划闸门**：`prepare` 完成后，老板先审 5 张主图和 10 张详情分屏的承接逻辑。
2. **成图闸门**：全部成图通过复核后，老板再决定是否采纳整套视觉包。

不得一口气从策划跑到最终采纳。

### 6.3 与现有商品视觉 kind 的兼容

不复制两套 prompt 和校验器。新增共享内部服务 `build_ecommerce_visual_plan`：

- `prepare_ecommerce_visual_pack` 以 `surfaces=['main_image','detail_section']` 调用，形成完整正式 visual pack。
- 现有 `generate_creative_pack(kind='product_main_image'|'product_detail_page')` 保留原入口和历史返回结构，但改为调用同一个 planner 的 surface-only 兼容模式。
- 兼容模式仍只产生 legacy brief，不自动成为正式 visual pack；其 next-step 改为引导进入 `audience-ecommerce-visuals`。
- 历史 product brief 继续可 list/get；若要作为本次策划参考，通过 `legacy_plan_script_ids` 显式导入，不能混入 `source_script_id`。
- `source_script_id` 只表示可选的种草/软广内容来源，不承担商品视觉 plan 版本语义。

### 6.4 持久审批状态机

```text
prepare
  → pack.status=draft, plan_status=pending
  → 持久化候选，不创建最终 unit
approve_plan
  → 锁定每个 slot 的 candidate
  → 冻结 fact snapshot + packaging reference set
  → 事务内物化不可变 units
  → plan_status=approved
render / incremental finalize
  → assets.status=draft
  → ecommerce_qa_status=pending|passed|failed|needs_human_review
  → 合格资产只标 selected，不提前 adopted
finalize_set
  → render_status=ready_for_review
adopt_pack（老板最终确认后）
  → 事务内校验整套
  → pack、units、selected assets 同时 adopted
```

任何 plan 变更都新建 pack version；不得原地修改已批准 unit。最终人工闸门之前，单图即使 QA passed 也保持 `status='draft'`，避免把“机器选中”混同为“老板采纳”。

## 7. 用户流程

```text
老板：“给这个人群做 5 张主图和详情页”
  ↓
Skill 解析明确的 portrait_id / audience_pack_id / sku_id
  ↓
登记或选定当前包装版本产品参考图
  ↓
prepare_ecommerce_visual_pack
  ↓
返回并持久化 5 + 10 个 slot 的候选、向量初筛、事实冲突和参考图集合
  ↓
老板审核策划
  ↓
approve_ecommerce_visual_plan 锁定每个 slot 的候选、draft 上游例外和事实 resolution
  ↓
事务内物化不可变 units；未 approved 不允许出图
  ↓
Skill 每个 unit 调订阅内置图像能力生成背景/场景
  ↓
通过 artifact storage 登记图片字节，不传裸 Windows file_path
  ↓
finalize_ecommerce_visual_pack 增量摄取、确定性合成真实产品和准确中文
  ↓
image-only 盲描述 + 产品参考对照 + 硬 QA + 三边向量审计
  ↓
若失败：只返回 rerender_units，服务端原子分配下一 attempt
  ↓
Skill 定向重做；每 unit 总尝试上限固定为 3
  ↓
finalize_set：套组覆盖/去重 + 拼长图，进入 ready_for_review
  ↓
老板最终确认后 adopt_ecommerce_visual_pack 原子采纳整套
```

## 8. MCP 工具设计

### 8.1 `prepare_ecommerce_visual_pack`

建议签名：

```python
async def prepare_ecommerce_visual_pack(
    *,
    audience_pack_id: str,
    portrait_id: str,
    source_script_id: str | None = None,
    legacy_plan_script_ids: list[str] | None = None,
    product_reference_ids: list[str] | None = None,
    product_reference_inputs: list[dict] | None = None,
    plan_candidate_inputs: list[dict] | None = None,
    planning_mode: str = "codex_payload",
    platform: str = "douyin",
    main_count: int = 5,
    detail_count: int = 10,
    billing_policy: str = "subscription_first",
    embedding_policy: str = "local_or_explicit",
    extra_context: str | None = None,
) -> dict:
    ...
```

约束：

- `main_count` 第一版只允许 5。
- `detail_count` 允许 8–12，本次样板固定 10。
- 第一版每个 surface × slot 必须持久化 2 个通过 plan schema/fact QA 的文字候选；不足 2 个时 prepare 不进入可审核状态。
- `portrait_id` 必须显式传入，禁止“自动拿最新”造成画像版本漂移。
- `audience_pack_id`、`portrait_id` 必须指向同一个 audience record / matrix / SKU。
- `source_script_id` 可选；若传入，必须属于同一 SKU 和人群血缘，且 kind 为 `video_soft_ad` 或 `video_planting`。
- `legacy_plan_script_ids` 仅允许同血缘的 `product_main_image` / `product_detail_page`，作为策划参考，不改变 source content 血缘。
- 已采纳 upstream 优先；prepare 只报告 draft，不在此处自行放行。draft 例外只能在 `approve_ecommerce_visual_plan` 中逐 ID 确认并留痕。
- `product_reference_inputs` 使用 `{data_url|source_url, role, packaging_version}`；服务端读取实际字节后重算 checksum、尺寸和 MIME，不能信任客户端自报值。已有登记则直接传 ID。
- 同一 visual pack 的所有产品参考图必须属于同一 SKU 和同一 `packaging_version`。
- `planning_mode='codex_payload'` 是 subscription-first 默认：Skill 用当前 Codex 订阅生成结构化候选，MCP 只校验、向量化和持久化；候选 payload 必须通过 schema、事实和血缘校验。
- `planning_mode='configured_provider'` 才允许 MCP 自己调用已配置 LLM 生成候选，并必须显式 opt-in、返回 provider 与费用 trace。
- `billing_policy='subscription_first'` 时不得静默调用计费 provider；没有本地或明确标为 included/zero-cost 的 embedding provider 时返回 `metered_embedding_approval_required`。

主要返回：

```json
{
  "processing_ok": true,
  "visual_pack_id": "...",
  "slot_candidates": [
    {
      "surface": "main_image",
      "slot_no": 1,
      "required_axes": ["pain", "scene", "product_role"],
      "candidates": [
        {"candidate_id": "...", "plan": {}, "audience_plan_audit": {}}
      ]
    }
  ],
  "fact_snapshot_draft": {},
  "fact_conflicts": [],
  "upstream_status_warnings": [],
  "trace": {},
  "next_step_hint": {
    "action": "review_plan_before_render"
  }
}
```

### 8.2 `approve_ecommerce_visual_plan`

该工具是第一个人工闸门的持久化事务：

```python
async def approve_ecommerce_visual_plan(
    *,
    visual_pack_id: str,
    candidate_selections: list[dict],
    allow_draft_upstream_ids: list[str] | None = None,
    fact_resolutions: list[dict] | None = None,
    expected_version: int,
    approval_note: str | None = None,
) -> dict:
    ...
```

要求：

- 每个必需 surface × slot 恰好选择一个持久化 candidate。
- 使用乐观锁 `expected_version`，防止审核期间候选被并发替换。
- `allow_draft_upstream_ids` 必须逐 ID 写入，不能用一个宽泛布尔值绕过。
- `fact_resolutions` 保存冲突字段、最终值、来源类型、原始冲突、确认人、确认时间和 note。
- 事务内冻结 `fact_snapshot`、`fact_snapshot_checksum`、`packaging_version`、`reference_set_checksum` 和平台规则核验快照。
- 事务内从选中 candidates 物化 units，之后 unit 计划字段不可原地修改。
- 失败时不产生半套 units。

### 8.3 Artifact 传输与存储契约

Codex 内置 imagegen 的文件位于宿主机，KE 在容器内，禁止把任意 Windows `file_path` 直接传给 MCP。

首版统一走现有 asset storage 能力：

1. Skill 把单张生成结果作为 data URL，或先上传得到可访问的 `source_url`。
2. 服务端通过 `asset_storage` 读取字节、校验 MIME/尺寸/checksum，并保存到 canonical storage。
3. canonical storage 使用容器路径 `/app/data/outputs/ecommerce_visuals/...`；实施时必须增加受控 bind mount `./data/outputs:/app/data/outputs`，或配置等价对象存储。
4. 后续工具只传 `artifact_id`，不再传宿主机绝对路径。
5. 所有写入带 `idempotency_key`；服务端原子分配 `attempt_no`，网络重试不得重复落资产。
6. 允许的输入只有已登记 artifact、data URL 或 allowlist URL；拒绝路径穿越和任意本地路径。
7. artifact 以服务端 checksum 内容寻址，登记后不可原地替换；finalize 重新核对 checksum，避免上传后文件被换掉。
8. 单次 data URL 大小、MIME 和像素上限放配置；超过上限必须先走上传接口取得 artifact ID。

统一登记入口命名为 `register_ecommerce_source_artifact`（MCP tool，并由 REST `/api/v1/mcp/ecommerce-visual/artifacts` 复用同一 service）：

```python
async def register_ecommerce_source_artifact(
    *,
    visual_pack_id: str,
    unit_id: str | None,
    artifact_role: str,
    data_url: str | None = None,
    source_url: str | None = None,
    idempotency_key: str,
) -> dict:
    ...
```

`data_url` 与 `source_url` 二选一。工具返回 `artifact_id`、服务端 checksum、尺寸、MIME 和 canonical storage URL；产品参考图首次登记也复用这一存储 service，再写 `product_reference_images` 业务记录。

### 8.4 `finalize_ecommerce_visual_pack`

建议签名：

```python
async def finalize_ecommerce_visual_pack(
    *,
    visual_pack_id: str,
    rendered_assets: list[dict] | None = None,
    finalize_set: bool = False,
    stitch_detail: bool = True,
) -> dict:
    ...
```

`rendered_assets` 每项至少包含：

```json
{
  "unit_id": "...",
  "artifact_id": "...",
  "idempotency_key": "...",
  "render_mode": "background_only",
  "layer_role": "background",
  "generation_channel": "codex_builtin",
  "used_product_reference_ids": ["..."],
  "prompt_snapshot": "...",
  "blind_observation": {
    "mode": "codex_isolated",
    "observation": {},
    "input_manifest": {"artifact_id": "...", "plan_exposed": false}
  },
  "product_fidelity_observation": {
    "mode": "codex_isolated_reference_only",
    "observation": {},
    "input_manifest": {
      "artifact_id": "...",
      "product_reference_ids": ["..."],
      "plan_exposed": false,
      "portrait_exposed": false
    }
  }
}
```

处理语义：

- `rendered_assets` 可只提交本轮新增/失败 unit，合格单元无需重传。
- pack 必须已 `plan_status='approved'`，否则返回 `plan_not_approved`。
- 每 unit 总尝试上限由服务端固定为 3，调用方不能扩大。
- `background_only` 由 MCP 按 unit 的 layout/copy/product refs 合成最终图片；`scene_with_product_placeholder` 还必须提供遮挡/替换信息，否则进入人工复核。
- 确定性文字层、真实产品层、尺寸规范化均发生在 MCP；Skill 交回的是生成背景/场景 artifact，不称为最终成图。
- `finalize_set=False` 时执行增量 ingest、合成与 unit 审计；`True` 时在所有 unit 已合格后执行套组覆盖、去重、长图和 ready-for-review 状态转换。
- image-only 盲描述与产品参考对照是两个独立 payload 和隔离步骤：前者只看成图，后者只看成图和冻结参考图；两者都不接触画像或 plan。
- `uncertain` 不自动通过或失败，统一进入 `needs_human_review`。
- 若 `blind_observation.mode='codex_isolated'`，Skill 必须用无对话继承的独立 Codex 任务，只提供图片和观察 schema；audit 保存输入 manifest。若改用 MCP vision provider，必须显式 opt-in 并在 trace 披露计费。

主要返回：

```json
{
  "processing_ok": true,
  "visual_pack_id": "...",
  "pack_qa_status": "failed",
  "ready_for_human_review": false,
  "passed_units": [],
  "rerender_units": [
    {
      "unit_id": "...",
      "failure_type": "product_fidelity_failed",
      "observed": {},
      "targeted_prompt_patch": "..."
    }
  ],
  "set_audit": {},
  "detail_long_image": "...",
  "manifest_path": "...",
  "audit_report_path": "...",
  "trace": {},
  "next_step_hint": {
    "action": "rerender_failed_units_or_review_final"
  }
}
```

`processing_ok` 只表示本次请求执行完成，不表示整套通过；业务结论必须读取 `pack_qa_status` 与 `ready_for_human_review`。

### 8.5 `adopt_ecommerce_visual_pack`

第二个人工闸门使用专用事务，不复用宽松的通用 `pipeline_adopt`：

```python
async def adopt_ecommerce_visual_pack(
    *,
    visual_pack_id: str,
    expected_version: int,
    approval_note: str | None = None,
) -> dict:
    ...
```

采纳前必须在同一事务中确认：

- plan 已批准；
- 恰好 5 个主图 unit、8–12 个详情 unit；
- 每个 unit 恰好一个 `selected=true AND ecommerce_qa_status='passed'` 的 draft asset；
- pack 级覆盖、去重、叙事和长图检查 passed；
- 没有 `needs_human_review`；
- fact snapshot、reference set 与所有 asset audit checksum 一致。

通过后原子地把 pack、units 和 selected assets 改为 adopted；失败时一个都不改。

### 8.6 历史检索

新增：

- `pipeline_list_ecommerce_visual_packs(sku_id?, portrait_id?, status?)`
- `pipeline_get_ecommerce_visual_pack(visual_pack_id, include_units=True, include_audits=True)`

产物不得只能依赖当前对话找回。

## 9. 数据模型

### 9.1 `pipeline.ecommerce_visual_packs`

整套商品视觉的业务版本，建议字段：

- `id`
- `sku_id`
- `portrait_id`
- `audience_pack_id`
- `source_script_id`，可空
- `legacy_plan_script_ids JSONB`，可空，只作兼容参考
- `channel`，默认 `douyin_ecommerce`
- `status`：`draft | adopted | archived`
- `plan_status`：`pending | approved | rejected`
- `render_status`：`pending | in_progress | qa_failed | ready_for_review`
- `plan_approved_at`
- `plan_approved_by`
- `adopted_at / adopted_by`
- `version`
- `parent_visual_pack_id`
- `upstream_snapshot JSONB` 与 checksum
- `fact_snapshot JSONB` 与 `fact_snapshot_checksum`
- `fact_resolutions JSONB`
- `packaging_version`
- `reference_set_checksum`
- `platform_rule_snapshot JSONB` 与 `platform_rule_checked_at`
- `set_qa_status`：`pending | passed | failed | needs_human_review`
- `set_qa_summary JSONB`，仅保存最新摘要，完整历史在 audit runs
- `notes`
- `created_at / updated_at`

不把全部上游 ID 重复抄入 pack。创建时通过 portrait、audience pack 和可选 source script 动态解析 record、matrix 与 SKU，并强校验一致；血缘视图负责展开。用于复现的关键原文、版本与 checksum 冻结在 snapshot 中，上游后来更新不会改变本次审计依据。

### 9.2 `pipeline.ecommerce_visual_unit_candidates`

prepare 阶段持久化候选，避免“对话里看过两个，数据库里只剩一个”：

- `id`
- `visual_pack_id`
- `surface`
- `slot_no`
- `candidate_no`
- `required_axes JSONB`
- `plan_payload JSONB`
- `prompt`
- `plan_checksum`
- `audience_plan_audit_id`
- `status`：`proposed | selected | rejected`
- timestamps

审批事务要求每个必需 slot 恰好一个 selected candidate，并把它物化为 unit。候选审批后不可修改；重新出策划必须新建 pack version。

### 9.3 `pipeline.ecommerce_visual_units`

一行代表一个不可变的计划单元：

- `id`
- `visual_pack_id`
- `selected_candidate_id`
- `surface`：`main_image | detail_section`
- `slot_no`
- `role`
- `required_axes JSONB`
- `pain_text`
- `scene_text`
- `emotion_before`
- `emotion_after`
- `demand_bridge_text`
- `product_role_text`
- `selling_point_refs JSONB`
- `fact_refs JSONB`
- `copy_spec JSONB`
- `expected_visual JSONB`
- `prompt`
- `layout_spec JSONB`
- `plan_qa_status`
- `plan_qa_result JSONB`
- `approved_plan_checksum`
- `status`：`draft | adopted | archived`
- timestamps

一个 unit 可对应多个 asset attempt；unit 不存 `render_url` 或单一 `asset_id`。

### 9.4 `pipeline.product_reference_images`

把产品图从“临时上传文件”升级为可复用权威参考：

- `id`
- `sku_id`
- `packaging_version`
- `role`：`primary | front | back | label | detail | scale`
- `ordinal`
- `source_artifact_id`
- `file_url`
- `checksum_sha256`
- `mime_type`
- `width / height`
- `status`：`active | archived`
- `supersedes_id`
- `created_by`
- timestamps

关联表：

- `ecommerce_visual_pack_product_refs(pack_id, product_ref_id, ordinal, required)`
- `asset_product_refs(asset_id, product_ref_id, ordinal, usage_role)`

这样 SKU 换包装后，历史视觉包仍能证明当时使用了哪版参考图。

`role` 是单值；同一张文件需要同时承担 `primary` 与 `front` 时，关联表记录两个 `usage_role`，不把数据库 enum 写成 `primary/front`。服务端以真实图片字节重算 checksum；`supersedes_id` 必须属于同一 SKU。

### 9.5 `pipeline.ecommerce_source_artifacts`

宿主机生成结果进入 MCP 后的不可变源文件登记；它不是最终可投放 asset：

- `id`
- `visual_pack_id`
- `unit_id`，产品公共参考或 pack 级源可空
- `artifact_role`：`product_reference | generated_background | generated_scene | occlusion_mask | manual_layer`
- `storage_provider`
- `storage_key / file_url`
- `checksum_sha256`
- `mime_type`
- `width / height / size_bytes`
- `idempotency_key`
- `status`：`active | archived`
- `created_by`
- timestamps

同一个 `idempotency_key + checksum` 重试返回同一 artifact；同 key 不同 checksum 直接报冲突。source artifact 登记后内容不可原地替换。`finalize.rendered_assets[].artifact_id` 和产品参考图的 `source_artifact_id` 均指向此表。

### 9.6 `pipeline.assets` 扩展

新增最小字段：

- `ecommerce_visual_unit_id`，unit 渲染时填写
- `ecommerce_visual_pack_id`，只给详情长图等 pack 级产物填写
- `attempt_no`
- `generation_channel`：`codex_builtin | manual | upload`
- `ecommerce_role`：`unit_render | detail_composite`
- `ecommerce_qa_status`：`pending | passed | failed | needs_human_review`
- `ecommerce_selected BOOLEAN NOT NULL DEFAULT FALSE`
- `source_artifact_id`
- `composition_manifest JSONB`
- `idempotency_key`

不重复存 `slot_no` 和 `surface`；它们从 unit 得出。机器审计通过时只把一个 draft asset 标成 `ecommerce_selected=true`；老板最终采纳事务才把 selected asset 改成 adopted。

### 9.7 `pipeline.visual_audit_runs`

复核记录必须 append-only：

- `id`
- `visual_pack_id`
- `candidate_id`，plan 阶段必填
- `unit_id`，pack 级审计可空
- `asset_id`，plan 阶段可空
- `stage`：`plan | render | set`
- `judge_model`
- `judge_prompt_version`
- `billing_policy`
- `provider_call_ids JSONB`
- `source_checksum`
- `observation_input_manifest JSONB`
- `blind_observation JSONB`
- `product_fidelity_observation JSONB`
- `hard_gate JSONB`
- `vector_scores JSONB`
- `vector_ids JSONB`
- `coverage_result JSONB`
- `dedupe_result JSONB`
- `status`：`passed | failed | uncertain`
- `actor_id`
- `created_at`

不得只覆盖 `assets.qa_result`，否则重做后无法追溯前一次为什么失败。

### 9.8 向量存储

新增 `pipeline.ecommerce_visual_vectors`，保存三端逐轴源向量，保证三条边可重算：

- `visual_pack_id`
- `candidate_id`，prepare 阶段 audience/plan 向量必填
- `unit_id`，render 阶段必填
- `asset_id`，仅 `source_role='render'` 时必填
- `portrait_id`，仅 `source_role='audience'` 时必填
- `source_role`：`audience | plan | render`
- `axis`：`pain | scene | emotion | demand_bridge | product_role`
- `source_text`
- `source_checksum`
- `embedding vector`
- `dimensions`
- `model`
- `provider`
- `task_type`
- timestamps

MVP 数据量很小，不需要新建 HNSW 索引。prepare 为每个 candidate 保存一组 audience anchor 与 plan 向量；approve 后 unit 通过 `selected_candidate_id` 复用它们；render 再保存 asset observation 向量。每条 edge 的 audit run 保存实际使用的 audience / plan / render vector ID。同一条 edge 只允许比较相同 provider、model、dimensions 与 task type 的向量。这里复用现有 `embed_texts`、余弦和审计框架，并把 `triangle_match` 泛化成 artifact-edge engine；不能原样复用其自动找最新画像和 0.65/0.70 绝对阈值。

### 9.9 关键约束

- `UNIQUE(visual_pack_id, surface, slot_no, candidate_no)` on candidates
- candidate_no 第一版只能为 1–2，且每个必需 slot 恰好两个 proposed candidates 才能进入 plan review
- audience/plan vectors：`UNIQUE(candidate_id, source_role, axis)`
- render vectors：`UNIQUE(asset_id, source_role, axis)`
- `UNIQUE(visual_pack_id, surface, slot_no)`
- 主图 slot 只能为 1–5
- 详情 slot 只能为 1–12；采纳事务再检查总数不少于 8
- `UNIQUE(ecommerce_visual_unit_id, attempt_no)`
- partial unique index：每个 unit 最多一个 `ecommerce_selected=true` 的 asset
- partial unique index：每个 unit 最多一个 `status='adopted'` 的 asset
- 产品参考图按 SKU、包装版本、role、checksum 去重
- unit asset 与 pack 级 composite asset 必须满足 XOR：前者 unit_id 非空，后者 pack_id 非空
- pack 采纳前必须恰好 5 个主图 unit、8–12 个详情 unit，且每个 unit 有一个 QA passed、selected 的 draft asset
- 张数、全 unit QA passed、pack/unit/asset 同步采纳属于跨行规则，必须由专用事务执行，不能伪装成普通 CHECK

FK 与不可变约束：

- pack 到 portrait、audience pack、source script 使用 `ON DELETE RESTRICT`；历史血缘不得因上游清理而断。
- candidate/unit 随未采纳 pack 清理可 cascade；pack adopted 后只允许 archived，不允许物理删除。
- asset 到 unit/pack 使用 `ON DELETE RESTRICT`。
- 产品参考图一旦被 pack 或 asset 引用，只能 archived，不能物理删除。
- `source_role IN ('audience','plan')` 时 candidate_id 必填且 asset_id 为空；`source_role='render'` 时 unit_id 与 asset_id 必填。candidate、unit、asset 必须归属同一 visual pack。
- plan audit run 必须绑定 candidate_id；render audit run 必须绑定 unit_id + asset_id；set audit 只绑定 visual_pack_id。
- plan approved 后，数据库触发器或 service-level immutable guard 拒绝修改 candidate selection、unit plan、fact snapshot、packaging version 和 reference set；修改只能创建新 pack version。
- 所有 mutation 带 actor、expected_version 和审计记录。

## 10. 生成前后向量复核

### 10.1 不做一个黑箱总分

用户需要的是“人群和方案的向量相近程度”，但余弦相似度不是购买概率。因此输出三条边，各自展示原始相似度、弱项和相对排名：

1. **人群 ↔ 方案**：策划是否真正承接画像。
2. **方案 ↔ 成图**：实际图片是否兑现策划。
3. **人群 ↔ 成图**：最终成品是否仍然像为该人群定制。

每条边按 unit 的 required axes 计算，不要求每张图把所有轴都塞满。

### 10.2 轴定义

| 轴 | 含义 | 是否可由向量证明 |
|---|---|---|
| pain | 画面/方案是否承接目标痛点 | 仅语义接近度 |
| scene | 是否出现画像中的真实场景 | 仅语义接近度 |
| emotion | 是否表达目标情绪起伏 | 仅可见情绪信号，不代表购买意愿 |
| demand_bridge | 人群需求与所用卖点是否搭桥 | 语义旁证 |
| product_role | 产品是否以计划中的角色/动作出现 | 语义旁证 |
| fact/evidence | 卖点是否真实、有证据 | **不能用向量证明，走确定性硬 QA** |
| package fidelity | 包装是否正确 | **不能用向量证明，走视觉硬 QA** |

### 10.3 盲审防虚高

成图后的视觉描述器只看图片，不看到 portrait、plan 或 prompt，输出：

- `observed`
- `not_observed`
- `uncertain`

以及人物、场景、动作、情绪、产品、食物和可见文字的结构化观察。之后才把观察描述与画像和方案做 embedding。这样避免 judge 直接复述计划，造成虚假的高相似度闭环。

盲描述与产品保真对照必须分两次调用：

1. image-only descriptor 的输入 manifest 只能包含成图 artifact、观察 schema 和版本，不含画像、计划、prompt 或产品参考图。
2. product-fidelity judge 只能看到成图与冻结的产品参考集，不含画像和计划。

第二次独立盲审必须使用新的隔离任务/调用 ID；两次结论冲突时不得自动裁决为通过，而是转 `needs_human_review`。

### 10.4 报告结构

每个 unit 输出：

```text
hard_gate
audience_plan: raw axis similarities
plan_render: raw axis similarities
audience_render: raw axis similarities
audience_min
audience_median
bridge_min
missing_required_axes
relative_rank
observations
```

字段定义：

- `audience_min`：该 unit 必需的 pain / scene / emotion 轴中最低的原始余弦；无该轴则不参与。
- `audience_median`：上述必需人群轴的中位数，不用加权和掩盖弱项。
- `bridge_min`：该 unit 必需的 demand_bridge / product_role 中较弱的一轴。
- `relative_rank`：plan 阶段只在“同 visual pack、同 surface、同 slot 的候选”内排序；render 阶段只在“同 unit 的 asset attempts”内排序。不同模型或不同向量空间不得互排。

最终对老板的表述是：

> 这套方案与目标人群在本批候选中属于较近 / 中等 / 较远；最贴人群的是哪些槽位，最弱的是哪些槽位，依据是哪些实际可见元素。

不输出“匹配度 87% = 购买概率 87%”之类结论。

### 10.5 初版不用绝对余弦阈值判生死

在没有黄金集和投后校准前：

- 向量只用于同槽候选相对排序、指出弱项和辅助重做。
- required axis 被盲审判为 `not_observed` 可以触发重做。
- 原始余弦低但没有具体可见偏差时，先做第二次独立盲审。
- 正确配对必须在黄金集中排在打乱配对之前；后续积累足够样本后再映射“近/中/远”分位。

## 11. 成图硬质检

硬质检分成两个层次，不能把模型判断伪装成确定性规则。

### 11.1 确定性 gate

- 文件可读、MIME、checksum、分辨率、色彩空间和长宽比。
- 主图/详情张数和 slot 唯一性。
- overlay 文字层的精确 copy、字号、安全边距、禁用词和 fact ref。
- 详情页配料、营养、使用方法和商品信息模块是否存在。
- 拼接顺序、最终尺寸和文件完整性。

OCR 按区域处理：

- `overlay_text_regions`：必须与计划文案逐字一致。
- `forbidden_text_regions`：不得出现额外营销字、第三方品牌或水印。
- `product_native_text_mask`：不按“未计划文字”误报；改由产品保真对照检查是否与冻结参考图一致。

### 11.2 Model-assisted blocking gate

- 包装版本、瓶型、瓶盖、Logo、标签布局、颜色和 250ml 规格对照。
- 人物、场景、产品动作和 required axes 的可见性。
- 明显重复构图、场景或产品贴片感。

模型判断为 `uncertain` 时不得自动通过或失败，进入人工复核。对于包装关键字段，至少结合冻结参考图对照、OCR/局部图像检查和一次隔离视觉判断。

以下任一明确失败，都直接失败，不看向量分：

1. 指定包装版本的瓶型、灰白瓶盖、标签、Logo、颜色或 250ml 规格错误。
2. overlay OCR 与计划文案不一致，出现乱码、额外品牌、错误规格或禁区文字。
3. 可见卖点、价格、促销、认证或功效不能映射到有效 fact ref。
4. 主图或必需产品槽位没有清晰产品，或产品只是无意义贴片。
5. 画幅、分辨率、安全区、文件完整性不合格。
6. 主图不是恰好 5 张，或详情页不在 8–12 张。
7. 详情事实段缺配料、营养、使用方法或必要产品信息。
8. 详情叙事顺序断裂。
9. 主图出现明显重复构图、重复场景或同一卖点无意义重复。

重复判断至少组合：

- 计划/盲审描述文本相似度；
- OCR 文案重复；
- 感知哈希或图像 embedding；
- 主体位置、场景和色调等视觉观察。

## 12. 重生成策略

1. 硬 QA 失败：只重生成对应 unit。
2. 必需轴 `not_observed`：定向补充该轴后重生成。
3. 向量低但没有可见偏差：先第二次盲审，避免 judge 噪声。
4. 只有“实际观察与计划不一致”，且 `plan↔render` 与 `audience↔render` 同时处于本批弱档，才因软匹配问题重生成。
5. 整套覆盖或去重失败：替换最重复、覆盖贡献最低的 unit，不重跑整套。
6. 每个 unit 总尝试次数上限为 3；超过后标 `needs_human_review`，整套不能自动采纳。

## 13. 抖音电商输出约束

本设计按当前官方资料采用保守口径：

- 单商品至少准备 5 张 1:1 主图；
- 图片至少 600×600；本设计统一输出 1024×1024；
- 第一张完整正面实物，主体清晰、居中，占画面约 70%；
- 主图不做大字报、拼图、水印或额外营销文字；痛点主要通过人物、动作和场景表达；
- 食品详情页展示配料、营养信息和食用方法；
- 具体发布时仍以抖店后台当时的商品诊断提示为准。

官方参考：

- [搜索双列样式中小商家运营指南](https://school.jinritemai.com/doudian/wap/article/aJb9jw4wsCcd?from=shop_zxdt&from_school=1&should_full_screen=1&should_hide_bottom_nav=1)
- [商品基础分规范](https://school.jinritemai.com/doudian/wap/article/aHfEp3nje8fR)
- [商品主图发布规范意见征集](https://school.jinritemai.com/doudian/wap/article/aHdt9Rv1GNS9)

## 14. 寿喜烧首套样板

### 14.1 血缘锚点

以下是设计时核对到的当前候选，实施时必须动态查询并验证状态，禁止硬编码：

- SKU：`SKU-378619-0006`
- 商品：和田宽寿喜烧 250ml 日式风味锅汁底料
- 卖点矩阵：`a8f70529-8c74-4530-9903-08d0bd1f7a49`
- 人群记录：`8eec33df-a543-4b65-baea-3ca69125cf20`
- 人群画像：`e98693ae-29c8-4b6f-8b18-c12671735838`
- 已采纳圈包：`19592026-4ee8-467c-abff-b45c7513bad5`
- 来源种草脚本：`3d424dc5-a08e-4c29-84f9-c761e1065e77`
- 目标人群：「饭局主理人·合家欢聚」

当前状态并非全绿：audience record 与 audience pack 已采纳；matrix、portrait 和 source script 目前仍为 draft。首套运行前必须二选一：先按现有 pipeline 流程采纳它们，或在 `approve_ecommerce_visual_plan` 中逐 ID 写入 draft 例外及确认理由。prepare 不得自行忽略这些状态。

### 14.2 当前包装参考

老板确认本次实际发货版本为灰白瓶盖包装。用户提供的正面产品参考图：

- 尺寸：407×732
- SHA-256：`355f03442fde418b391e5a2902bfe9dd7228a1519d12f1739e0287696c572aec`
- 产品图 role：`primary`；在 pack 关联表中同时登记 `usage_role='front'`
- 状态：待实施时复制到稳定 workspace 路径并登记为 active reference

该图足以做外观锚点，但横向分辨率较低。若最终首图标签清晰度硬 QA 不通过，必须要求更高分辨率产品图，不能靠生成模型补写标签。

当前图片仍位于临时目录，且尚未形成稳定 reference set；因此本样板暂时不能宣称“现在即可全绿跑通”。首套 E2E 前至少要完成：

1. 把正面图复制/上传到 canonical asset storage 并登记 checksum。
2. 登记同一包装版本的背面、标签/配料和营养信息参考图。
3. 如 407×732 正面图不能满足首图标签清晰度，先补高分辨率正面图。
4. 冻结整套 reference set checksum，禁止混用金盖或其他包装版本。

### 14.3 已确认商品事实

- 规格：250ml
- 保质期：18 个月，由老板本次明确确认
- 使用：按已核实资料展示 7–9 倍稀释关系
- 配料/风味锚：酿造酱油、味淋、昆布等现有资料事实
- 多用途：寿喜烧、关东煮、乌冬、盖饭
- 包装原生表述：只允许“0 添加山梨酸钾、0 添加苯甲酸钠”
- 执行标准：GB31644
- 不写价格、折扣、赠品、销量
- 不扩大成“无添加”“零添加全部添加剂”
- 不写有机、低盐、儿童专用、销量或复购等无依据描述
- “汤底越煮越淡”只作为用户痛点；没有证据时不得宣称产品“永不变淡”“无需补味”或“越煮越浓”

仓库历史资料仍保留“详情 18 个月、瓶身 12 个月”的原始冲突。本次对话确认的 18 个月在 `approve_ecommerce_visual_plan.fact_resolutions` 落库前，只是设计输入，不是已完成的数据修复；不得让 prepare 静默覆盖历史原文。

审批时允许把老板确认为 `owner_confirmed` 来源，但最终参考集中的当前发货背标若仍清晰显示 12 个月，产品保真/事实一致性 gate 必须阻断 18 个月上图，要求补当前 18 个月包装或厂家凭证；不能用文字层覆盖真实瓶身矛盾。

### 14.4 五张主图

| Slot | 痛点 | 单画面表达 | 产品角色 | 必需轴 |
|---|---|---|---|---|
| 1 | 一桌难合众口 | 产品完整正面居中，背景是一桌不同饮食偏好的家人 | 主体约 70%，列表识别 | pain / scene / product_role |
| 2 | 聚餐备菜太累 | 主理人面对食材和锅具，生活化忙乱 | 锅边的简化入口 | pain / scene / emotion / product_role |
| 3 | 调味总拿不准 | 主理人在量杯、清水与锅之间犹豫 | 与 7–9 倍稀释使用关系搭桥 | pain / scene / demand_bridge / product_role |
| 4 | 汤底越煮越淡 | 聚餐中段补汤、续锅、重新调味的真实动作 | 参与续锅，不宣称无需补味 | pain / scene / product_role |
| 5 | 忙完没空入席 | 家人留座，主理人终于走向餐桌 | 桌边自然常备，情绪转松 | pain / scene / emotion / product_role |

五张均为 1024×1024、sRGB、无额外营销字、无水印、无拼图。

### 14.5 十张详情分屏

1. 人群钩子：每次聚餐，最先累的是主理人。
2. 众口难调：一家人想吃的都不一样。
3. 操持疲惫：备料、配汁、守锅，忙完才入席。
4. 产品承接：把产品定位为一锅基础味的解决入口，不承诺人人口味一致。
5. 使用方法：按 7–9 倍稀释事实展示步骤。
6. 风味来源：酿造酱油、味淋、昆布等已核实信息。
7. 多场景使用：寿喜烧、关东煮、乌冬、盖饭。
8. 情绪结果：主理人也能坐下来一起吃。
9. 信任信息：准确展示两项“0 添加”限定表述。
10. 商品信息：250ml、18 个月、GB31644、配料、营养和使用信息。

详情分屏统一输出 750×1000，同时拼接为 750×10000 长图。

详情页确定性文字层以 750px 画布上的最小正文字号 24px、左右安全边距至少 32px 为初始验收值，具体阈值放配置并用实际手机预览校准。第 10 屏若无法在该可读性约束下容纳事实信息，禁止缩成小字硬塞；prepare 必须把信息重新分配到第 9–10 屏，仍放不下则提出 11–12 屏修订并重新走策划审批。

## 15. 生成与合成策略

### 15.1 两种渲染模式

1. **锁品合成模式**：首图、产品信息页、证据页使用真实产品图和确定性版式。
2. **场景占位替换模式**：人物手持、锅边使用等场景允许模型生成产品占位，但最终必须用冻结的真实产品层、遮挡 mask 和 placement 数据替换；输出 `composition_manifest` 证明最终产品层来源。

第一版优先生成“不含产品的背景/场景”，再合成真实产品。只有真实动作无法通过平面合成表达时才使用场景占位替换。若手部遮挡、透视或反光导致无法可靠替换，就进入人工复核；不得把模型生成的瓶身宣称为“没有重画标签”。

### 15.2 人物一致性

- 主理人身份来自画像，不凭空硬编码职业或性别。
- 画像无强性别信号时，以手部、侧脸、背影和家庭关系表达为主。
- 同套图固定年龄段、服装、家居环境、光线与色彩锚点。
- 不使用豪华样板间、影棚广告光或与目标人群生活状态冲突的场景。

### 15.3 文字与事实

- 主图不加额外营销文字。
- 详情页中文全部由本地确定性排版系统渲染。
- 产品包装原生文字来自真实产品图，不让图像模型重写。
- `fact_refs` 缺失的卖点不得进入 copy。

### 15.4 Codex 出图执行约定

- 每个不同 unit 单独调用一次内置 `image_gen`；不得用一个 prompt 的 `n` 代替 15 个不同资产。
- 每完成一个 unit 就登记 artifact 和恢复点，额度耗尽或任务中断后从未完成 unit 续跑。
- 首轮只生成每 unit 一个候选；复核失败才定向重做，避免无意义消耗订阅额度。
- 内置工具不可用时明确暂停；未经老板确认不得切到 CLI/API fallback。
- 最终选中资产必须复制/登记到 workspace canonical storage，不能只留在 `$CODEX_HOME/generated_images`。

## 16. 输出目录与清单

```text
data/outputs/ecommerce_visuals/<sku_id>/<visual_pack_id>/
├── main/
│   ├── 01.jpg
│   ├── 02.jpg
│   ├── 03.jpg
│   ├── 04.jpg
│   └── 05.jpg
├── detail/
│   ├── screens/
│   │   ├── 01.jpg
│   │   └── ...
│   └── detail-long.jpg
├── manifest.json
└── audit-report.json
```

`manifest.json` 至少记录：

- visual pack / unit / asset ID
- 输入画像、圈包和来源脚本版本
- 使用的产品参考图 ID 与 checksum
- 每张图最终 prompt
- 每个资产自己的 `generation_channel`，不得把整包写死
- composition/layout template version
- blind judge / product fidelity judge 的 prompt version 与 provider call ID
- 平台规则核验时间、来源 URL 和快照 checksum
- 文件尺寸、格式和 checksum
- 采纳状态

## 17. 错误处理

标准错误码：

| 错误 | 处理 |
|---|---|
| `lineage_mismatch` | 停止，返回冲突的 SKU/record/matrix ID |
| `portrait_not_explicit` | 要求传明确 portrait_id，不自动拿最新 |
| `candidate_selection_incomplete` | 返回缺失/重复 slot，不物化任何 unit |
| `version_conflict` | 重新读取 pack，防止用过期候选审批或采纳 |
| `draft_upstream_not_approved` | 要求逐 ID 采纳或写入 draft 例外 |
| `product_reference_missing` | 停止，要求上传或登记当前包装图 |
| `product_reference_too_weak` | 可继续策划，但出图前警告；最终清晰度失败则阻断 |
| `product_fact_conflict` | prepare 列出冲突；在 resolution 落库前禁止 approve_plan |
| `fact_resolution_missing` | 要求在 approve_plan 中持久化冲突解决记录 |
| `plan_not_approved` | 禁止摄取成图，先完成策划审批事务 |
| `artifact_source_invalid` | 拒绝裸本地路径、路径穿越或 checksum 不一致 |
| `metered_embedding_approval_required` | subscription_first 下停止，不静默调用计费 embedding |
| `metered_vision_approval_required` | subscription_first 下停止，不静默调用计费 vision judge |
| `isolated_observer_unavailable` | 无法完成无上下文盲描述时暂停，不能用主会话自评冒充盲审 |
| `unsupported_claim` | 删除该文案并返回缺失 fact ref |
| `main_count_invalid` | 必须改为 5 |
| `detail_count_invalid` | 必须调整到 8–12 |
| `render_artifact_invalid` | 只重做对应 unit |
| `product_fidelity_failed` | 只重做对应 unit，附具体包装差异 |
| `ocr_failed` | 使用确定性文字层重新合成，不先重跑背景 |
| `composition_requires_human` | 手持遮挡/透视无法可靠替换真实产品层，进入人工复核 |
| `required_axis_missing` | 定向修改 prompt 后重做对应 unit |
| `set_duplicate_failed` | 替换重复度最高且覆盖贡献最低的 unit |
| `stitch_failed` | 保留合格分屏，单独重跑拼接 |
| `max_attempts_exceeded` | 标 `needs_human_review`，禁止自动采纳 |
| `audit_uncertain` | 进入人工复核，不自动通过或失败 |

## 18. A/B 与投后闭环边界

商品图实验以整套 visual pack 为臂：

1. 每轮只替换一个 slot/unit，其他商品图、标题、价格、活动、库存、评价、流量来源和时间窗尽量固定。
2. 首图实验北极星使用商品曝光→点击 CTR，例如 `show_click_rate`，或由商品曝光 UV / 点击 UV 计算。
3. 详情页整套使用点击→成交 `click_pay_rate` / CVR；GMV、订单量作辅助。
4. 抖音当前指标库没有可靠的详情停留指标，因此第一版不承诺详情停留。
5. 非首图与详情分屏通常没有逐图归因数据，不能声称某一单图独立带来转化。
6. 现有视频实验的 `n≥5` 工程门槛不直接复用；商品图需要按 impressions、clicks、orders 和曝光均衡判断数据是否足够。
7. 平台不能同期随机分流时，只能称为交替时间窗准实验，不能写成严格因果 A/B。
8. winner 永远由投后北极星决定；三边向量只做冷启动排序和校准旁证。

本节属于切片 E 的扩展设计，现有视频实验状态机不能直接复用。实施时至少要新增：

- `track='ecommerce_visual'`；
- experiment arm 指向 `visual_pack_id`，而非只指向 `script_id`；
- 商品配置版本 × 上线时间窗级 observation 表，避免把一套商品指标复制到 15 个 asset 后重复计数；
- `show_click_rate` / `click_pay_rate` 与当前 `ctr` / `cvr` 白名单的显式 metric alias；
- impressions、clicks、orders、曝光均衡和混杂项记录。

首版可验证的 winner 只有两类：slot 1 封面 CTR，或整套详情 visual pack 的 CVR 准实验。slot 2–5 在平台无逐图数据时只做内容完整性和向量复核，不建立独立 winner 机制。

## 19. 测试与验收

### 19.1 单元与集成测试

1. 恰好 5 张主图，详情页 8–12 张。
2. 明确 portrait 选择，不得因“最新版本”漂移。
3. portrait、audience pack、source script、SKU 血缘一致性。
4. 候选持久化、每 slot 单选审批、乐观锁和不可变 unit 物化。
5. draft 上游必须逐 ID 确认；fact conflict 必须有持久化 resolution。
6. product main/detail compatibility planner 与新正式 plan 使用同一结构契约。
7. 每个 unit 多 asset attempt、最多一个 selected draft 和一个 adopted asset。
8. `idempotency_key` 重试不重复落资产，attempt_no 由服务端原子分配且最多 3。
9. host→container artifact storage、MIME/checksum、allowlist URL 和路径穿越拒绝。
10. 详情分屏顺序、750×1000 尺寸和 750×N 长图拼接。
11. pack/list/get 可完整找回，资产可通过 unit→pack 反查完整血缘。
12. image-only blind descriptor 的 input manifest 不包含画像、plan 或 prompt。
13. subscription-first 路径不得调用 ai-provider-hub 的付费图像生成 API；未知计费 embedding/vision provider 必须 fail-closed。
14. adoption 事务失败时 pack、units、assets 均不发生部分状态变化。

### 19.2 负样本黄金集

至少覆盖：

- 金色瓶盖替换灰白瓶盖；
- 瓶型改变；
- 标签、Logo 或“250ml”错误；
- 把两项防腐剂限定扩大成“零添加”；
- 把保质期写成 12 个月；
- 编造价格、赠品、销量、有机、低盐、儿童专用或认证；
- 中文乱码；
- 主图拼贴、文字遮挡、低分辨率；
- 五图重复；
- 详情页漏配料、营养或食用方法。

验收表述限定为“约定负样本零漏放”，不扩展成真实世界永久 100% 准确。

### 19.3 向量黄金集

1. 正确 audience–plan–render 配对必须排在打乱配对之前。
2. 同槽两个候选中，包含目标痛点、场景和情绪信号的候选应排序更高。
3. 不允许高向量分绕过产品、OCR 或事实硬失败。
4. 在没有校准前，不用固定 65/70 余弦阈值判业务有效。
5. 所有 rendered asset 必须存在完整三边审计；缺任一边即不可采纳。
6. 每条 edge 保存实际使用的 audience / plan / render vector ID，三端向量可按 checksum 重算。
7. `relative_rank` 只比较同 slot candidates 或同 unit attempts，不跨模型/向量空间。

### 19.4 端到端验收

以本寿喜烧样板跑通：

0. 前置条件：稳定前/背/标签参考集已登记；18 个月 resolution 已落库；draft matrix/portrait/source script 已采纳或逐 ID 放行。
1. prepare 持久化 5×2 个 main candidates 和 10×2 个 detail candidates。
2. 老板审核后，approve_plan 才物化 5 个 main units 和 10 个 detail units。
3. 每个 unit 完成 image-only blind observation、产品参考对照、hard QA 和三边向量审计。
4. 只重做失败单元，不影响已合格单元。
5. finalize_set 产出 5 张主图、10 张详情分屏、1 张长图、manifest 和 audit report。
6. 老板最终确认后，adopt 事务一次性采纳整套；任一最终 asset 能反查到目标人群画像和 SKU。
7. doctor、相关服务测试、provider denylist 审计和静态 schema 检查通过。

## 20. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 产品参考图分辨率偏低 | 先作为外观锚；最终标签清晰度不合格时要求高分辨率，不让模型补字 |
| 内置图像能力不暴露具体 model slug | 只记录 `codex_builtin`；不虚报模型名 |
| 图像模型改动包装 | 首图优先真实图合成；动作图使用占位替换和真实产品层，无法可靠替换则人工复核 |
| 视觉 judge 受计划暗示 | image-only descriptor 使用隔离任务和输入 manifest，不向其暴露画像、plan 或 prompt |
| 向量看似精确但无业务意义 | 展示原始相似度、最弱轴和相对排名，不包装成购买概率 |
| 同一套图视觉不一致 | 固定人物、场景、光线、色板和产品参考，套组级复核 |
| 详情长图过大 | 分屏永远保留；长图单独压缩和复核，拼接失败不影响分屏 |
| 平台规则变化 | 发布前以抖店后台商品诊断和最新规则为准 |
| 订阅额度或内置工具临时不可用 | 明确报错并保存恢复点；不得静默切到付费 API |
| 向量 provider 可能计费 | subscription_first 默认本地/已标 included provider；否则先报 `metered_embedding_approval_required` |

## 21. 计费与模型边界

本设计选择订阅优先的原因：ChatGPT/Codex 订阅和 OpenAI API 是分开的计费体系。若 MCP 后台直接调用 `gpt-image-2` API，会产生 API 账单；Codex App 内置图像生成则属于 Codex 交互工作流。

计费策略分层如下：

| 能力 | subscription-first 默认路径 | 计费边界 |
|---|---|---|
| 创意策划 | 当前 Codex 生成 `plan_candidate_inputs`，MCP 做确定性校验 | 使用 Codex 订阅 |
| 图片生成 | Codex 内置 imagegen | 不调用 OpenAI 图像 API |
| image-only 盲描述 | 无对话继承的隔离 Codex 任务 | 使用 Codex 订阅 |
| OCR / 合成 / 拼接 | 本地确定性程序 | 无模型 API |
| 向量 embedding | 本地 adapter 或明确标记 included/zero-cost 的 provider | 未满足时停止并请求选择，不静默计费 |
| MCP LLM/vision provider | 仅 `configured_provider` 显式 opt-in | 可能产生 API/provider 费用，trace 必须披露 |

因此“订阅优先”不是靠客户端自报 `generation_channel` 证明。验收必须同时检查 provider-call audit：该 visual pack 在 subscription-first 模式下不得出现付费图像生成调用；embedding/vision 若走 provider，必须存在用户 opt-in、provider 名和费用估算。不同 embedding provider/model 的分数不得直接比较。

参考：

- [ChatGPT 订阅是否包含 API 使用](https://help.openai.com/en/articles/8156019-is-api-usage-included-in-chatgpt-subscriptions-even-if-i-have-a-paid-chatgpt-account)
- [Introducing the Codex app](https://openai.com/index/introducing-the-codex-app/)
- [Codex pricing](https://chatgpt.com/codex/pricing/)
- [GPT Image 2 API model](https://developers.openai.com/api/docs/models/gpt-image-2)

## 22. 读者盲审结果

使用无本轮对话上下文的独立技术读者，仅依据本文档和仓库现状进行两轮检查。首轮发现审批状态机、候选持久化、宿主机↔容器 artifact bridge、三端向量存储、事实/包装冻结和 adopted 语义等契约缺口；本文已修正。第二轮复审结论为：无 P0 设计阻塞，可以进入 `writing-plans`。

实施计划第一阶段仍需核实 canonical storage 挂载与现有 `asset_storage` 的最终文件级接入点，但不再需要产品方向选择。

## 23. 实施切片建议

1. **切片 A：数据契约与策划**：migration、candidate/pack/unit/reference/audit/vector 模型、共享 planner、`prepare`、`approve_plan`、结构校验、list/get。
2. **切片 B：Skill 与订阅出图**：新建 `audience-ecommerce-visuals` Skill、Codex plan payload、逐 unit 调用内置 imagegen、隔离盲描述、artifact storage 与恢复点。
3. **切片 C：确定性合成与硬 QA**：真实产品层、遮挡/placement、文字层、区域化 OCR、尺寸、安全区、长图拼接、增量 finalize、失败单元重做与 `adopt_pack` 事务。
4. **切片 D：三边向量审计**：artifact-edge engine、本地/显式 provider adapter、三端逐轴向量、黄金集、相对排序、审计报告。
5. **切片 E：可选投后实验**：visual pack 实验臂、商品级指标回灌和校准；不阻塞首版交付。

详细文件级施工步骤在本设计经老板书面复核后，用 `writing-plans` 另行产出。
