# 人群专属抖音电商主图与详情页视觉包设计

日期：2026-07-10

状态：四部分设计已由老板逐段确认，待书面设计复核

方案：B——统一商详视觉包（Codex Skill + MCP 编排与审计）

## 1. 摘要

在现有「SKU → 卖点矩阵 → 人群匹配 → 人群画像 → 圈包 SOP → 内容」链路后，新增一条正式的商品视觉承接链：

```text
已采纳 SKU / 卖点 / 人群 / 画像 / 圈包 / 可选软广脚本
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

实际 AI 出图由 Codex Skill 调用订阅内置图像能力，不经额外付费的 OpenAI API。MCP 负责读取真实数据、生成结构化方案、向量计算、合成、质检、拼接、版本与血缘落库。

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
返回 5 + 10 个 unit、每个 slot 的 2 个文字候选、向量初筛、事实引用
  ↓
老板审核策划
  ↓
Skill 每个 slot 选择 1 个方案出图
  ↓
确定性合成真实产品和准确中文
  ↓
finalize_ecommerce_visual_pack
  ↓
硬 QA + 三边向量审计 + 套组覆盖/去重 + 拼长图
  ↓
若失败：只返回 rerender_units
  ↓
Skill 定向重做，每 unit 最多 2 次额外尝试
  ↓
全部通过后等待老板采纳
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
    product_reference_ids: list[str] | None = None,
    product_reference_inputs: list[dict] | None = None,
    platform: str = "douyin",
    main_count: int = 5,
    detail_count: int = 10,
    extra_context: str | None = None,
) -> dict:
    ...
```

约束：

- `main_count` 第一版只允许 5。
- `detail_count` 允许 8–12，本次样板固定 10。
- `portrait_id` 必须显式传入，禁止“自动拿最新”造成画像版本漂移。
- `audience_pack_id`、`portrait_id` 必须指向同一个 audience record / matrix / SKU。
- `source_script_id` 可选；若传入，必须属于同一 SKU 和人群血缘，且 kind 为 `video_soft_ad` 或 `video_planting`。
- 已采纳 upstream 优先；使用 draft 必须显式确认并在 trace 留痕。
- `product_reference_inputs` 允许 Skill 首次把本地图片连同 role、packaging_version 和 checksum 交给 prepare 登记；已有登记则直接传 ID。

主要返回：

```json
{
  "ok": true,
  "visual_pack_id": "...",
  "units": [
    {
      "unit_id": "...",
      "surface": "main_image",
      "slot_no": 1,
      "required_axes": ["pain", "scene", "product_role"],
      "plan": {},
      "candidates": [],
      "audience_plan_audit": {}
    }
  ],
  "fact_snapshot": {},
  "trace": {},
  "next_step_hint": {
    "action": "review_plan_before_render"
  }
}
```

### 8.2 `finalize_ecommerce_visual_pack`

建议签名：

```python
async def finalize_ecommerce_visual_pack(
    *,
    visual_pack_id: str,
    rendered_assets: list[dict],
    stitch_detail: bool = True,
    max_attempts_per_unit: int = 3,
) -> dict:
    ...
```

`rendered_assets` 每项至少包含：

```json
{
  "unit_id": "...",
  "file_path": "...",
  "generation_channel": "codex_builtin",
  "used_product_reference_ids": ["..."],
  "prompt_snapshot": "..."
}
```

主要返回：

```json
{
  "ok": true,
  "visual_pack_id": "...",
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
  "next_step_hint": {
    "action": "rerender_failed_units_or_review_final"
  }
}
```

### 8.3 历史检索

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
- `channel`，默认 `douyin_ecommerce`
- `status`：`draft | adopted | archived`
- `plan_approved_at`
- `version`
- `parent_visual_pack_id`
- `set_qa_status`：`pending | passed | failed | needs_human_review`
- `set_qa_summary JSONB`，仅保存最新摘要，完整历史在 audit runs
- `notes`
- `created_at / updated_at`

不把全部上游 ID 重复抄入 pack。创建时通过 portrait、audience pack 和可选 source script 动态解析 record、matrix 与 SKU，并强校验一致；血缘视图负责展开。

### 9.2 `pipeline.ecommerce_visual_units`

一行代表一个不可变的计划单元：

- `id`
- `visual_pack_id`
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
- `status`
- timestamps

一个 unit 可对应多个 asset attempt；unit 不存 `render_url` 或单一 `asset_id`。

### 9.3 `pipeline.product_reference_images`

把产品图从“临时上传文件”升级为可复用权威参考：

- `id`
- `sku_id`
- `packaging_version`
- `role`：`primary | front | back | label | detail | scale`
- `ordinal`
- `file_url`
- `checksum_sha256`
- `mime_type`
- `width / height`
- `status`：`active | archived`
- `supersedes_id`
- timestamps

关联表：

- `ecommerce_visual_pack_product_refs(pack_id, product_ref_id, ordinal, required)`
- `asset_product_refs(asset_id, product_ref_id, ordinal, usage_role)`

这样 SKU 换包装后，历史视觉包仍能证明当时使用了哪版参考图。

### 9.4 `pipeline.assets` 扩展

新增最小字段：

- `ecommerce_visual_unit_id`，unit 渲染时填写
- `ecommerce_visual_pack_id`，只给详情长图等 pack 级产物填写
- `attempt_no`
- `generation_channel`：`codex_builtin | manual | upload`
- `ecommerce_role`：`unit_render | detail_composite`
- `ecommerce_qa_status`

不重复存 `slot_no` 和 `surface`；它们从 unit 得出。每个 unit 最多一个 adopted asset。

### 9.5 `pipeline.visual_audit_runs`

复核记录必须 append-only：

- `id`
- `visual_pack_id`
- `unit_id`，pack 级审计可空
- `asset_id`，plan 阶段可空
- `stage`：`plan | render | set`
- `judge_model`
- `judge_prompt_version`
- `source_checksum`
- `blind_observation JSONB`
- `hard_gate JSONB`
- `vector_scores JSONB`
- `coverage_result JSONB`
- `dedupe_result JSONB`
- `status`
- `created_at`

不得只覆盖 `assets.qa_result`，否则重做后无法追溯前一次为什么失败。

### 9.6 向量存储

新增 `pipeline.ecommerce_visual_vectors`，只用于 unit/asset 粒度缓存和可复现：

- `unit_id`
- `asset_id`，plan 阶段为空，render 阶段必填
- `stage`：`plan | render`
- `axis`：`pain | scene | emotion | demand_bridge | product_role | overall`
- `source_text`
- `source_checksum`
- `embedding vector(1536)`
- `model`
- timestamps

MVP 数据量很小，不需要新建 HNSW 索引。计算仍复用现有 `embed_texts`、`vector_presets` 和 `triangle_match`，不是另建一套 embedding 服务。

### 9.7 关键约束

- `UNIQUE(visual_pack_id, surface, slot_no)`
- 主图 slot 只能为 1–5
- 详情 slot 只能为 1–12；采纳事务再检查总数不少于 8
- `UNIQUE(ecommerce_visual_unit_id, attempt_no)`
- `UNIQUE(ecommerce_visual_unit_id) WHERE asset.status='adopted'`
- 产品参考图按 SKU、包装版本、role、checksum 去重
- pack 采纳前必须恰好 5 个主图 unit、8–12 个详情 unit，且每个 unit 有一个 QA passed 的 adopted asset

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

以下任一失败，都直接失败，不看向量分：

1. 指定包装版本的瓶型、灰白瓶盖、标签、Logo、颜色或 250ml 规格错误。
2. OCR 与计划文案不一致，出现乱码、额外品牌、错误规格或未计划文字。
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

### 14.2 当前包装参考

老板确认本次实际发货版本为灰白瓶盖包装。用户提供的正面产品参考图：

- 尺寸：407×732
- SHA-256：`355f03442fde418b391e5a2902bfe9dd7228a1519d12f1739e0287696c572aec`
- 角色：`primary/front`
- 状态：待实施时复制到稳定 workspace 路径并登记为 active reference

该图足以做外观锚点，但横向分辨率较低。若最终首图标签清晰度硬 QA 不通过，必须要求更高分辨率产品图，不能靠生成模型补写标签。

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

## 15. 生成与合成策略

### 15.1 两种渲染模式

1. **锁品合成模式**：首图、产品信息页、证据页使用真实产品图和确定性版式。
2. **参考引导场景模式**：人物手持、锅边使用等生活场景由图像模型参考产品图生成，成图后接受严格包装审计。

第一版优先使用锁品合成；只有真实动作无法通过平面合成表达时才使用参考引导生成。

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
- `generation_channel=codex_builtin`
- 文件尺寸、格式和 checksum
- 采纳状态

## 17. 错误处理

标准错误码：

| 错误 | 处理 |
|---|---|
| `lineage_mismatch` | 停止，返回冲突的 SKU/record/matrix ID |
| `portrait_not_explicit` | 要求传明确 portrait_id，不自动拿最新 |
| `product_reference_missing` | 停止，要求上传或登记当前包装图 |
| `product_reference_too_weak` | 可继续策划，但出图前警告；最终清晰度失败则阻断 |
| `product_fact_conflict` | 停止，列出冲突事实并等待老板确认 |
| `unsupported_claim` | 删除该文案并返回缺失 fact ref |
| `main_count_invalid` | 必须改为 5 |
| `detail_count_invalid` | 必须调整到 8–12 |
| `render_file_invalid` | 只重做对应 unit |
| `product_fidelity_failed` | 只重做对应 unit，附具体包装差异 |
| `ocr_failed` | 使用确定性文字层重新合成，不先重跑背景 |
| `required_axis_missing` | 定向修改 prompt 后重做对应 unit |
| `set_duplicate_failed` | 替换重复度最高且覆盖贡献最低的 unit |
| `stitch_failed` | 保留合格分屏，单独重跑拼接 |
| `max_attempts_exceeded` | 标 `needs_human_review`，禁止自动采纳 |

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

## 19. 测试与验收

### 19.1 单元与集成测试

1. 恰好 5 张主图，详情页 8–12 张。
2. 明确 portrait 选择，不得因“最新版本”漂移。
3. portrait、audience pack、source script、SKU 血缘一致性。
4. product main/detail 结构 parser 契约。
5. 每个 unit 多 asset attempt、最多一个 adopted asset。
6. 详情分屏顺序、750×1000 尺寸和 750×N 长图拼接。
7. pack/list/get 可完整找回。
8. 资产可反查完整血缘。
9. subscription-first 路径不得调用 ai-provider-hub 的付费图像 API。

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

### 19.4 端到端验收

以本寿喜烧样板跑通：

1. 生成 5 个 main units 和 10 个 detail units。
2. 老板审核策划后才出图。
3. 每个 unit 完成 blind observation、hard QA 和三边向量审计。
4. 只重做失败单元，不影响已合格单元。
5. 产出 5 张主图、10 张详情分屏、1 张长图、manifest 和 audit report。
6. 任一最终 asset 能反查到目标人群画像和 SKU。
7. doctor、相关服务测试和静态 schema 检查通过。

## 20. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 产品参考图分辨率偏低 | 先作为外观锚；最终标签清晰度不合格时要求高分辨率，不让模型补字 |
| 内置图像能力不暴露具体 model slug | 只记录 `codex_builtin`；不虚报模型名 |
| 图像模型改动包装 | 首图优先真实图合成；动作图走参考引导并硬审计 |
| 视觉 judge 受计划暗示 | 成图描述严格盲审，不向 judge 暴露画像和 prompt |
| 向量看似精确但无业务意义 | 展示原始相似度、最弱轴和相对排名，不包装成购买概率 |
| 同一套图视觉不一致 | 固定人物、场景、光线、色板和产品参考，套组级复核 |
| 详情长图过大 | 分屏永远保留；长图单独压缩和复核，拼接失败不影响分屏 |
| 平台规则变化 | 发布前以抖店后台商品诊断和最新规则为准 |
| 订阅额度或内置工具临时不可用 | 明确报错并暂停；不得静默切到付费 API |

## 21. 计费与模型边界

本设计选择订阅优先的原因：ChatGPT/Codex 订阅和 OpenAI API 是分开的计费体系。若 MCP 后台直接调用 `gpt-image-2` API，会产生 API 账单；Codex App 内置图像生成则属于 Codex 交互工作流。

参考：

- [ChatGPT 订阅是否包含 API 使用](https://help.openai.com/en/articles/8156019-is-api-usage-included-in-chatgpt-subscriptions-even-if-i-have-a-paid-chatgpt-account)
- [Introducing the Codex app](https://openai.com/index/introducing-the-codex-app/)
- [Codex pricing](https://chatgpt.com/codex/pricing/)
- [GPT Image 2 API model](https://developers.openai.com/api/docs/models/gpt-image-2)

## 22. 实施切片建议

1. **切片 A：数据契约与策划**：migration、pack/unit/reference/audit 模型、`prepare`、结构校验、list/get。
2. **切片 B：Skill 与订阅出图**：新建 `audience-ecommerce-visuals` Skill、逐 unit 调用内置 imagegen、文件归档。
3. **切片 C：确定性合成与硬 QA**：产品层、文字层、OCR、尺寸、安全区、长图拼接、失败单元重做。
4. **切片 D：三边向量审计**：盲描述、现有向量引擎泛化、黄金集、相对排序、审计报告。
5. **切片 E：可选投后实验**：visual pack 实验臂、商品级指标回灌和校准；不阻塞首版交付。

详细文件级施工步骤在本设计经老板书面复核后，用 `writing-plans` 另行产出。
