---
name: selling-point-finder
description: 找一个 SKU 的卖点。老板说"找 SKU-X 的卖点"、"X 这款酱油有啥好讲的"、"挖一下 X 的产品力"等，触发标准 4 步走 SOP，从 SKU 基础信息 → 模板素材 → 三类卖点（功能 / 情绪 / 场景）。
---

# selling-point-finder：SKU 卖点挖掘 SOP

> omni-vibe 项目内 skill。老板说"找 X 卖点/挖 X 产品力/X 有啥好讲的"时，按 4 步走，**每步停下等反馈**。

## 触发场景（话术 → 参数）

| 老板话术 | sku_id 解析 | 备注 |
|---|---|---|
| "找 SKU-375753-0001 的卖点" | 直接给的 | 走标准流程 |
| "和田宽特级辣酱油有啥好讲的" | 名字模糊 | 先 list_skus(query=...) 找 ID，再确认 |
| "挖一下寿喜烧的产品力" | 名字模糊 | 同上 |
| "我这款米醋的卖点" | 没指定具体 SKU | 先反问"是哪个具体的——5 度白米醋还是黑醋？" |

## 标准 4 步 SOP

### Step 1: 锁定 SKU + 拿基础信息（含 owner 字段优先）

如果老板话术里 SKU ID 不明确：

```python
list_skus(status="active", query="<老板说的关键词>")
```

把候选列表给老板，确认 ID。然后：

```python
get_sku(sku_id="SKU-X")
```

返回字段优先级（W4-B 切片 12 后字段全抓全）：
- `owner_selling_points`（**老板手填的卖点 JSON 数组**）—— 最权威，先看这个
- `owner_notes`（老板手填的产品参数）
- `specifications`（套装规格：500ml*2 + 200ml*2 等）
- `name`（抖店标题，SEO 堆词长串）
- `price_min/price_max` / `platform_status`

**关键**：如果 `owner_selling_points` 已填，**优先复用**老板已有判断，不要重新挖：

> "002 已经有 9 条 owner_selling_points：「180天发酵酿造 / 日式工艺 / 高盐稀态发酵 /
> 有机 / 零添加 / 玻璃瓶 / 不含白砂糖 / 33年源头工厂 / 老北京和田宽酱油」。
> 是基于这些挖深，还是要全新角度？"

如果老板说"挖深"→ 拿 owner_selling_points 作种子进 Step 2 找模板支撑；
如果老板说"全新"→ 跳过 owner_selling_points 走通用挖法。

**status 检查**：如果 `platform_status` 是 `off_sale` / `out_of_stock`，先告诉老板：

> "这款 platform_status=off_sale 已下架，确实要找卖点？是要复活推还是分析历史？"

### Step 2: 拿模板素材（卖点框架/竞品对比）

```python
query_template_chunks(query="<品类> 卖点", top_k=8)
```

`query` 用品类词（如"辣酱油"/"寿喜烧"/"米醋"），不要直接塞 SKU 名（SKU 名太长会稀释）。

返回 chunks 看 **哪些是直接可用的"卖点框架"**（如"功能-情绪-场景"三段式 / "对比-痛点-解决"等）；如果空命中，提示老板：

> "KB 里没找到 <品类> 的卖点模板。要不要我用通用框架（功能/情绪/场景）继续？还是你先补一篇模板进 template KB？"

如果命中合理的 chunks，**告诉老板你打算用哪几条**：

> "拿到 3 条相关模板：A 是功能-情绪-场景三段式 / B 是 5 度酸度的科普角度 / C 是日式调味场景延伸。我打算综合 A+C 出三类卖点，可以吗？"

老板 OK 进 Step 3；老板说"换 X" 就重调 query_template_chunks 用新关键词。

### Step 3: 拿历史/方法论 KB（可选但推荐）

```python
search_kb(query="<品类> 卖点 OR 差异化", kb_roles=["authoritative", "methodology"], top_k=5)
```

补充权威/方法论维度（如品牌定位、品类格局、过往打过的角度）。**返回如有**，挑 2-3 条跟 Step 2 模板素材合并。

> "另外 KB authoritative 区有 1 条「和田宽 vs 千禾品牌站位差异」可借——要不要纳入卖点角度？"

老板 OK 进 Step 4；老板说不要就跳过这部分。

### Step 4: 出三类卖点（功能 / 情绪 / 场景）

把 Step 1-3 拿到的素材综合，输出**三类**卖点，每类 2-3 条：

```
功能型卖点（产品本身能干啥）：
  - 5 度自然酿造，无添加（SKU.detail）
  - 500ml 大瓶 + 200ml 小瓶组合，新老用户都覆盖（pack_spec）

情绪型卖点（让用户感觉啥）：
  - "和田宽" 老牌信任感（authoritative KB）
  - 给娃辅食用更安心（template chunk B）

场景型卖点（什么时候买它）：
  - 凉拌饺子蘸料（template chunk C 日式调味场景）
  - 送朋友体面又实用（500+200 组合礼盒感）
```

**重要约束**：
- 每条卖点必须**带来源**（SKU 字段 / template chunk ID / authoritative kb 名）
- 不允许编造（feedback memory 强制：写作风格反幻觉）
- 三类总数 6-9 条，不要一类堆 5 条

把结果给老板看，问"哪几条要进脚本/上素材"。

## 错误处理

| 错误 | hint | 怎么办 |
|---|---|---|
| `list_skus` 返空 | 老板关键词太模糊 | 让老板补品类或品牌词 |
| `query_template_chunks` 返空 | template KB 没相关素材 | 提示老板"先补一篇模板"或用通用三段式继续 |
| `search_kb` 全是不相关命中 | query 没切中 | 换关键词重调（如品类改品牌名） |
| 老板说"卖点太空了" | 输出泛化 | 回 Step 2 重挖模板，加 SKU 具体字段（pack_spec / detail）落地 |

## 反例（**禁止**）

- 不调任何 tool 直接凭 SKU 名编卖点 — 没素材就是空中楼阁
- 卖点不带来源 — 老板没法验真假
- 一类卖点写 5 条 — 失焦，挑最强的 2-3 条
- 用 AI 化套话（"赋能/打通/闭环/抢占心智"）— feedback memory 强制说人话
- 一气呵成跑完 4 步不停 — 必须每步停老板反馈

## 已知约束

- 不直接调 generate_brief（那是 script-writer skill 的事；本 skill 只到"卖点列表"为止）
- query_template_chunks 没显式 kb_id 时默认查所有 kb_role='template' 的 KB
- search_kb 用 kb_roles 自动解析 KB ID（不需要手填）

## 跟 CLAUDE.md / 其他 skill 的关系

- 本 skill 是 **script-writer** skill 的前置（先找卖点 → 再写脚本）；老板说"给 X 写个脚本"时，script-writer skill 会先内调本 skill 的 Step 1-4
- 跟 **product-analysis** skill 互补：product-analysis 看健康度（成本/利润/数据），本 skill 看卖点（内容角度）。老板"全面分析 X" → 两个一起跑
- CLAUDE.md "老板响应词约定"通用，"重来/改/不行" → 同 step 重调；"第 N 条不要" → 改输出，不重跑 tool
