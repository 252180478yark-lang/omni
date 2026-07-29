---
name: selling-point-finder
description: 统一的 SKU 卖点/产品力/差异化分析入口，默认从 SKU 开始并为后续链路服务。老板说“找 SKU-X 的卖点”“X 有啥好讲的”“挖一下 X 的产品力”“做卖点矩阵”“分析这个详情页卖点”等，一律触发本 skill。内部唯一生成口径是 `generate_selling_points_matrix`；输出默认是可继续做人群匹配/圈包/脚本的“链路接续卡”，不是孤立长报告。凡调味品 SKU 卖点分析走本 skill，不走 marketing-psychology/competitive-landscape 等通用营销框架。
---

# selling-point-finder：统一卖点矩阵入口

> 目标：以后老板侧只认一个“卖点分析”入口。`selling-point-finder` 是入口，`generate_selling_points_matrix` 是唯一执行工具。<br>
> 不再维护“轻量三类卖点”和“pipeline 卖点矩阵”两套结果，避免同一个 SKU 前后口径打架。
> 老板实际用法通常是“从 SKU 开始，卖点出来就走后续”，所以默认输出要方便继续跑，不要像终稿报告一样展开。

## 触发场景

| 老板话术 | 动作 |
|---|---|
| “找 SKU-xxx 的卖点 / 卖点分析” | 锁定 SKU 后跑 `generate_selling_points_matrix` |
| “X 有啥好讲的 / 挖一下 X 产品力 / 差异化” | 先 `list_skus` 找候选，再跑矩阵 |
| “做卖点矩阵 / 跑卖点矩阵” | 仍走本 skill，内部调同一个矩阵工具 |
| “我把详情页截图给你，先做卖点分析” | 先提取截图里的确定事实，再作为 `extra_context` 喂矩阵工具 |
| “给 X 写脚本” | 这是 `script-writer`，但它找卖点时也复用本 skill 的矩阵结果 |

## 标准流程

### Step 1: 锁定 SKU 与事实字段

如果老板没给 SKU ID：

```python
list_skus(status="active")
```

用关键词在人话里筛候选，候选多时让老板确认。确定后：

```python
get_sku(sku_id="SKU-X")
```

重点读这些字段：
- `owner_selling_points`：老板手填卖点，作为 `user_initial_points`，不是最终答案。
- `owner_notes`：详情页/规格/配料/使用方法等事实，放进 `extra_context`。
- `specifications`、`name`、`price_min/price_max`、`platform_status`。
- 若老板提供详情页截图、评论、客服反馈，先只提取能看见的确定事实，不补脑。

如果 `platform_status` 是 `off_sale` / `out_of_stock` / `paused`，先提醒老板这款当前不可正常推，再问是否仍要分析历史或复活角度。

### Step 2: 组装矩阵工具参数

把已有事实整理后调用：

```python
generate_selling_points_matrix(
    sku_id="SKU-X",
    user_initial_points="<owner_selling_points 或老板口头补充，可空>",
    user_reviews="<真实评价/客服反馈摘录，可空>",
    extra_context="<详情页事实、价格、规格、老板临时要求、禁用角度>",
)
```

原则：
- `generate_selling_points_matrix` 是唯一卖点生成工具。
- 不再先手工 `query_template_chunks` / `search_kb` 拼一版三类卖点。
- 有 KB、prompt_rule、trace、落库血缘的事情交给矩阵工具做。
- 老板只要“简单卖点”时，也照样跑矩阵，然后给他输出短摘要。

### Step 3: 输出链路接续卡

矩阵工具返回后，默认只给老板看“链路接续卡”，不要把全文矩阵无脑糊满屏。输出顺序固定：

1. SKU 确认：`sku_id`、品名、价格、规格、状态。
2. 矩阵血缘：`matrix_run_id`、`version`、`status=draft/adopted`。
3. 主推卖点：从矩阵里挑 1 条最适合继续往下跑的主卖点，说明理由，并标证据等级。
4. 备用卖点：再给 2-3 条可切换角度，每条标功能/情绪/场景属性 + 证据等级。
5. `next_step_hint`：直接透出工具返回的 suggested_tool/suggested_args/human_text；若老板说“继续”，优先按这个 hint 走。
6. 后续链路建议：下一步建议接人群匹配、脚本，还是先补详情页/评论。
7. 证据缺口：哪些卖点现在不能讲，缺什么证据。
8. 痛点原料：只摘“产品侧能解决的场景痛点”（如调味比例难把握、多人锅底怕寡淡、一人食嫌麻烦），不写具体人群痛点、不写谁说/怎么说；这些留给后续人群画像和内容链路。

每条摘要必须带来源：
- `SKU 字段`
- `owner_notes / owner_selling_points`
- `详情页截图事实`
- `generate_selling_points_matrix` 矩阵段落
- KB 名称或 trace 里能追到的来源

证据等级固定三档：
- `A 可直接讲`：SKU 字段、详情页截图、配料/参数/认证、真实评价能直接支撑。
- `B 可弱讲`：产品属性 + 品类常识能支撑，但缺用户评价或详情页强证据。
- `C 暂不能讲`：缺证据、合规风险高、竞品也能讲到泛滥，只能列在证据缺口里。

只有老板明确说“展开全文 / 给我完整矩阵 / 看五心智维度”时，才展开完整的产品档案、三层卖点地图、五心智维度、结构化标签、信息补全建议。

### Step 4: 采纳与下游

如果老板说“这版可以 / 采纳 / 后面就用这个”，执行：

```python
pipeline_adopt(table="matrix_runs", run_id="<matrix_run_id>")
```

下游只复用 adopted matrix 或老板明确指定的 draft：
- 写脚本：`script-writer` 读取本次卖点矩阵，让老板圈 2-3 条进脚本。
- 跑前链路：`sku-pipeline` 从同一个 `matrix_run_id` 继续做人群匹配。
- 做软广 AI 视频：下游用 `matrix_run_id` / `audience_record_id` / `audience_pack_id` 接血缘。

## 错误处理

| 情况 | 处理 |
|---|---|
| SKU 候选多个 | 列候选，让老板确认，不猜 |
| SKU 字段太少 | 仍可跑矩阵，但输出里标“证据不足”，提示补详情页/评论/资质 |
| 详情页截图看不清 | 只用能看清的字，不推断配料、工艺、认证 |
| 矩阵输出太长 | 先给摘要 + `matrix_run_id`，老板要全文再展开 |
| 老板说“卖点太空” | 补详情页事实/用户评论后重跑 `generate_selling_points_matrix`，产生新版本 |

## 禁止

- 禁止绕过 `generate_selling_points_matrix` 自己拼一套卖点结论。
- 禁止把竞品卖点当成自家 SKU 事实，只能作为 `extra_context` 的参考/避让。
- 禁止编造无添加、有机、进口、老字号、检测认证、销量、回购率等未证实信息。
- 禁止直接调 `generate_brief`；脚本归 `script-writer`。
- 禁止一边输出旧“三类卖点”，一边又跑新“卖点矩阵”，造成两份口径。

## 与其他 skill 的关系

- `selling-point-finder`：唯一卖点分析入口，内部调 `generate_selling_points_matrix`。
- `sku-pipeline`：前链路编排入口；只有老板要“卖点矩阵 + 人群 + 圈包”时才继续 Step 3/4。
- `script-writer`：写脚本入口；找卖点时复用本 skill 的矩阵结果。
- `competitor-product-research`：拆竞品入口；竞品结论只能当参考，不替代自家 SKU 矩阵。
- `product-analysis`：看健康度、成本、利润、数据；不是卖点入口。
