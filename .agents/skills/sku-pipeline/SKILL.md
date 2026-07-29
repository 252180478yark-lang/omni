---
name: sku-pipeline
description: Use when老板要跑 SKU 前链路、卖点矩阵、人群匹配、采纳人群、圈包 SOP，或要查看/续跑到 audience_pack_id 为止的 pipeline 血缘；不要用于脚本、软广、硬广、分镜、出片或 A/B 内容迭代。
---

# sku-pipeline：SKU 圈包前链路 SOP

`sku-pipeline` 现在只保留到圈包为止：

```text
SKU -> 卖点矩阵 -> 人群匹配 -> 已采纳人群 -> 圈包 SOP / audience_pack_id
```

它是**前链路工作台**，不是内容生成入口。脚本、软广、种草、硬广、故事板、成片、A/B 单变量迭代都交给互斥的下游内容 skill，并把这里产出的 `audience_pack_id` / `audience_record_id` 当上游锚点。交接时先问清内容目标，不默认替用户选软广或种草。

## 触发

| 老板话术 | 动作 |
|---|---|
| "SKU-X 跑前链路" / "SKU-X 到圈包" | 跑 step 2 -> step 3 -> step 4 |
| "给 X 做卖点矩阵和人群包" | 跑到 `audience_pack_id` 停 |
| "看 X 已采纳人群 / 圈包 SOP" | 查历史 `audience_records` / `audience_packs` |
| "X 全链路先别出片" | 只跑到圈包 |

## 不触发

- "软种草 / 深度种草 / A3 / 用产品解决画像痛点" -> `ai-planting-video`
- "软广 / O-A1 人群 AI 短视频 / 前三秒与完播优化" -> `ai-soft-ad-video`（Claude 兼容入口名 `soft-ad-ai-video`）
- "硬广 / 收割 / A4 转化视频" -> 后续硬广 skill 或 `video_harvest` 内容链
- "写脚本 / 分镜 / 生成视频 / 配音 / A/B 测试" -> 内容生成与实验链，不在本 skill 里继续
- "诊断这个包 / 提纯这个包" -> `audience-pack-diagnosis`

## 标准步骤

### Step 0: 锁定 SKU

```python
get_sku(sku_id="SKU-X")
```

只确认 SKU 基础信息、品类、规格、已有 owner_selling_points。成本利润不再作为本链路强制步骤；需要算账时单独走 `cost-luru` / `product-analysis`。

### Step 2: 卖点矩阵

```python
generate_selling_points_matrix(
    sku_id="SKU-X",
    user_initial_points="<老板补充卖点，可空>",
    user_reviews="<真实评论摘录，可空>",
    extra_context="<临时要求，可空>",
)
```

输出后落 `pipeline.matrix_runs`。让老板审卖点矩阵，满意后：

```python
pipeline_adopt(table="matrix_runs", run_id="<matrix_run_id>")
```

### Step 3: 人群匹配

```python
generate_audience_match(
    sku_id="SKU-X",
    matrix_md="<step 2 的矩阵 markdown>",
    matrix_run_id="<matrix_run_id>",
)
```

输出 `audience_run` 并拆出多条 `audience_records`。给老板看人群清单，只让老板选择要进入圈包的人群。老板选中后：

```python
pipeline_adopt(
    table="audience_records",
    run_id="<audience_record_id>",
    set_selected=True,
)
```

### Step 4: 圈包 SOP

```python
generate_audience_pack(
    audience_record_id="<已采纳/已选中的 audience_record_id>",
    extra_context="<临时圈包要求，可空>",
)
```

输出并落库：

- `audience_pack_id`
- 圈包 SOP markdown
- 关联的 `sku_id` / `matrix_run_id` / `audience_run_id` / `audience_record_id`

老板确认这版圈包可用后：

```python
pipeline_adopt(table="audience_packs", run_id="<audience_pack_id>")
```

到这里本 skill 结束。不要继续生成脚本、分镜、图片或视频。

## 交接给下游

交接时只报这几项：

- `sku_id`
- `matrix_run_id`
- `audience_record_id`
- `audience_pack_id`
- 圈包 SOP 摘要
- 人群内容制作桥接卡：若后续要做内容，必须优先交接“产品 / 场景 / 谁说 / 说什么 / 怎么说 / 在哪说 / 情绪 / 痛点”八个槽位；不要只交接人群名和 5 条匹配理由。
- 如已有关键词包，再附 `keyword_pack_id`，但关键词扩展不是本应用端主流程

下游种草 AI 视频由 `ai-planting-video` 读取 `audience_pack_id`，围绕画像痛点—产品动作—结果解除建立 A3 链路；下游 O/A1 软广由 `ai-soft-ad-video` 读取同一交接血缘，围绕前三秒与完播建立生活流内容。两者不共用 intent 或 winner 指标。

## 继续/重跑规则

| 老板说 | 做法 |
|---|---|
| "继续" | 只有当前步骤明确有下一步时才推进；到 `audience_pack_id` 后停止并问下游内容类型 |
| "重来 / 改" | 重跑当前 step，新版本落库，不覆盖旧版本 |
| "换一个人群" | 回 step 3 选择另一条 `audience_record`，再跑 step 4 |
| "这个包太大/太小" | 不在本链路硬改，转 `audience-pack-sizing` 或导出画像后 `audience-pack-diagnosis` |

## 常见错误

- 把 `sku-pipeline` 当出片入口：禁止。它只到 `audience_pack_id`。
- 在本应用端继续做脚本或视频：禁止。种草走 `ai-planting-video`，软广走 `ai-soft-ad-video`。
- 跳过老板采纳直接下游：不要。下游只吃 adopted 或老板明确指定的 draft。
- 圈包后又“再全包一次”：不要。已有 adopted `audience_pack_id` 时直接复用。
