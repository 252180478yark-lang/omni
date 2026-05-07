---
name: cost-luru
description: 录入或重录 SKU 成本。老板说"录 sku-X 物流费 5 块"/"加成本 包装 0.8"/"录运费"走单笔录入 5 步 SOP；说"算 sku-X 出厂价"/"重录 X 成本"/"X 用工厂出厂价"走桥接 SOP（list_product_prices 找候选 → disable 旧拆分 → record 新出厂价合计）。
---

# cost-luru：录成本/重录成本 SOP

> omni-vibe 项目内 skill。两条路径并存：
> - **路径 A 单笔录入**：老板说"录 sku-X 物流费 5 块"等具体单条 → 5 步 SOP
> - **路径 B 工厂出厂价桥接**（W4-B 切片 12 加）：老板说"算 sku-X 出厂价"等
>   要从工厂单品组合算 → 6 步桥接 SOP
>
> **每步停下等老板反馈**，不一气呵成。

## 触发场景

### 路径 A：单笔录入

| 话术 | 解析 | tool 调用 |
|---|---|---|
| "录 sku-A 物流费 5 块" | sku_id=SKU-A, category=logistics, item_name=物流费, unit_cost=5 | record_cost(...) |
| "sku-B 加成本 包装 0.8" | sku_id=SKU-B, category=product, item_name=包装, unit_cost=0.8 | record_cost(...) |
| "顺丰华东 8 块每单" | sku_id=None（共享）, category=logistics, item_name=顺丰华东, unit_cost=8, unit=单 | record_cost(...) |
| "C 厂商品报价 12 块/箱 24 瓶" | sku_id=None, category=partner_quote, vendor=C 厂, unit=箱, quantity_per_unit=24, unit_cost=12 | record_cost(...) |
| "改 sku-A 物流费 6 块"（已存在） | 先 query_costs 找旧条 → disable_cost_item 停旧 → record_cost 录新 | 3 tool 链 |

### 路径 B：工厂出厂价桥接（套装/组合 SKU）

| 话术 | 含义 | 走 |
|---|---|---|
| "算 sku-X 出厂价" / "X 用工厂出厂价" | 按工厂单品组合算成本 | 桥接 6 步 |
| "重录 X 成本"（含组合品） | 旧拆分式废弃用出厂价 | 桥接 6 步 |
| "X 是套装 / 多瓶组合" | 显示型套装 SKU | 桥接 6 步 |

## 标准 5 步 SOP

### Step 1: 解析话术 → 推参数

按上面"触发场景"表把老板说的拆成 record_cost 入参。**关键约束**：

- `category` 必须是 `product` / `logistics` / `partner_quote` 之一（不是其他词）
- `unit_cost` 必须是字符串（"0.50" 而不是 0.5），避免 float 误差
- `quantity_per_unit` 默认 "1"，老板说"一箱 24 瓶"才填 "24"
- `unit` 默认 "件"，常见还有 "次"/"箱"/"单"
- `sku_id` 可空（共享成本如顺丰运费 → 全 SKU 用）
- `valid_from` 默认今天，老板说"从昨天开始算"才显式填
- **`visibility` 默认 `public`（员工出厂价）**；老板话术里若提到"真实成本/我自己看的/老板版"→ `real`；物流/平台扣点等共用 → `shared`（W4-B 切片 7 后）

**话术 → visibility 映射**（默认 public，明确触发改值）：

| 老板话术 | visibility |
|---|---|
| 没明说（默认）/ "员工版" / "出厂价" / "对外" | `public`（默认） |
| "真实成本" / "我自己看" / "老板版" / "实际进货价" | `real` |
| "物流费" / "运费" / "平台扣点" / "共用" / "通用" | `shared` |

**解析完先复述给老板看**，让老板确认参数（含 visibility）：

> "我打算录：SKU-A，物流类，「物流费」¥5/件，visibility=shared（共用），从今天起。对吗？"

### Step 2: 调 record_cost

老板确认后调：

```python
record_cost(
    sku_id="SKU-A",          # 或 None
    category="logistics",    # product | logistics | partner_quote
    item_name="物流费",
    unit_cost="5",
    currency="CNY",          # 默认
    unit="件",               # 默认
    quantity_per_unit="1",   # 默认
    vendor=None,             # 老板说了供应商才填
    valid_from=None,         # None 默认今天
    valid_to=None,
    notes=None,
    visibility="public",     # public（默认）| real（老板独占）| shared（共用）
)
```

**记住**：record_cost 走 Human Gate（require_approval=True），返回会带 `pending_approval_id`。

### Step 3: 提示老板批 Gate

返回结果给老板看，**告诉他怎么批**：

> "已写入 pending（id 前 8 位：abcd1234），你批一下：
> ```
> docker exec omni-knowledge-engine python -m app.mcp.cli_approve list
> docker exec omni-knowledge-engine python -m app.mcp.cli_approve approve abcd1234 --note "OK"
> ```
> 或者去前端 `/agent-log` 看（如果已开 /inbox 页）。批完跟我说『批好了』。"

如果老板说 `驳/不要/算了` → 用 cli_approve reject 让他驳。

### Step 4: 老板批好后，调 query_costs 验证

```python
query_costs(sku_id="SKU-A", category="logistics")  # 或 sku_id=None 看共享
```

把结果给老板看，**确认刚录的那条在不在**：

> "查到 SKU-A 物流类下 3 条，最新一条「物流费 ¥5/件 从今天起」就是刚录的，✅"

### Step 5: 提示下一步

询问老板要不要继续录别的，或进 sku 全链路（CLAUDE.md 5 步走）。

- 如果老板说"还要录 X"→ 回 Step 1 解析
- 如果老板说"算利润"→ 调 compute_margin
- 如果老板说"OK"→ skill 完成

## 路径 B：工厂出厂价桥接 6 步 SOP

> 适用：**套装/组合 SKU**（mvp_sku.specifications 含"X瓶 + Y瓶"或"500ml*2 +
> 200ml*2"），需要从 accounting.product_price_list 查工厂单品出厂价合计，
> 替代旧的"主料/人工/包装拆分式"成本（避免双算）。
>
> 真实跑通参考：W4-B 切片 12 给 SKU-367991-0002 重录的全过程（详见 §三十一）。

### Step B1: 拿 SKU 信息推套装组合

```python
get_sku(sku_id="SKU-X")
```

看 `name` / `specifications` / `owner_notes` 推断它由哪些工厂单品组成。
**复述给老板确认**：

> "看 SKU-002 名「和田宽有机本酿造特级酱油」+ specifications「500ml*2 +
> 200ml*2」→ 应该是「有机本酿造日式酱油」系列套装：2 瓶 500ml + 2 瓶 200ml。
> 对吗？还是别的工厂单品组成？"

老板确认后进 B2；老板说"是 X 系列别的款"→ 改 query 重 B2。

### Step B2: list_product_prices 查候选

```python
list_product_prices(query="<推断的工厂单品名>", vendor="和田宽产品", limit=20)
```

vendor 一般是「和田宽产品」或「辣嘴宽心系列产品」（W4-B 切片 8 import 的两 sheet）。
**关键约束**：
- query 用工厂单品名关键词（如"本酿造日式酱油"），不要塞 SKU 名（太长稀释）
- 命中后**给老板看候选**，让他圈对应的 500ml/200ml/1L 等规格

> "查到 5 个候选：
> A 宽牌本酿造原汁酱油 特级 500ml*12 ¥8.0/瓶
> B 有机本酿造日式酱油 特级 500ml*12 ¥17.5/瓶
> C 有机本酿造日式酱油 特级 200ml*12 ¥9.5/瓶
>
> 002 套装含 200ml → 排除 A（A 系列没 200ml 规格）；用 B+C 对吗？"

### Step B3: 算套装合计 + 复述

```
500ml × 2 × ¥17.5 = ¥35.00
200ml × 2 × ¥9.50 = ¥19.00
出厂价合计 = ¥54.00
```

把组合关系明示给老板，**等老板确认才进 B4**。

### Step B4: query_costs 列出现有 002 专属拆分式 cost_items

```python
query_costs(sku_id="SKU-X", view="public")
```

筛出 `sku_id="SKU-X"`（不是 sku_id=None 的 shared 共享行，那些不动）+
category="product" 的旧拆分式行。给老板看 cost_item_id 列表 + 合计金额：

> "002 专属 6 行拆分式：主料 ¥4.20 + 人工 ¥0.30 + 标签 ¥0.05 + 瓶身 ¥0.45×24 +
> 瓶盖 ¥0.08×24 + 包装箱 ¥1.80×24。
> 跟出厂价 ¥54 双算冲突，要 disable 这 6 行才能换出厂价口径。OK？"

### Step B5: 一次性发起 N+1 个 Gate

老板拍板后，**一气呵成**调：
- N 次 `disable_cost_item(<旧 id>, reason="改用工厂出厂价口径")`
- 1 次 `record_cost(sku_id="SKU-X", category="product", visibility="public",
  item_name="出厂价合计", unit_cost="<合计>", unit="套", quantity_per_unit="1",
  notes="<组合关系>")`

老板用 `/inbox` 前端页**一次显示多个**批准（W4-B 切片 2 双向通路实测真路径通），
或 cli_approve 逐个批。

### Step B6: 验证 + 算新利润

```python
query_costs(sku_id="SKU-X")          # 确认旧的 disable + 新的 record 都生效
compute_margin(sku_id="SKU-X", channel="douyin",
               sale_price="<mvp_sku.price_min 或老板确认的卖价>")
```

把 cost_total / channel_fee / net_profit / margin_pct 给老板看，对照旧
拆分式的虚高利润率（通常 80%+）vs 出厂价的真实利润率（通常 15-30%）。

### 路径 B 实战参考（002 例）

```
卖价 ¥76 / 抖音扣点 2%
出厂价 ¥54 + 默认运费 ¥5 + 默认包材 ¥3 = cost_total ¥62
net_profit = 76 - 62 - 1.52 = ¥12.48
margin_pct = 16.4%
```

## 错误处理

| 错误 | hint | 怎么办 |
|---|---|---|
| `invalid_category` | category 不是 3 选 1 | 跟老板确认是 product/logistics/partner_quote 哪个 |
| `invalid_visibility` | visibility 不是 3 选 1 | 跟老板确认是 public/real/shared 哪个（默认 public） |
| `invalid_decimal` | unit_cost 含非数字 / 负数 | 让老板重说价格 |
| `cost_item_not_found_or_already_inactive` | disable 时找不到 | query_costs 看看 id 对不对 |
| Gate 超时（默认 1h） | 老板 1 小时没批 | 提醒老板在 cli_approve list 里看 / 重调 record_cost |
| 路径 B 中 list_product_prices 返空 | KB 没该工厂单品 | 提示老板"是不是 vendor 写错了"或"工厂单品名没在字典里" |
| 路径 B 中 SKU 没 specifications 字段 | 抖店爬取没填 | 让老板手填或 SQL 补，不要瞎猜套装组合 |

## 反例（**禁止**）

- 不复述参数直接调 record_cost — 老板可能听错或想改
- 用 float 而不是 str 传 unit_cost
- 一气呵成跑完 5 步不停 — 必须每步停下等老板反馈
- 调用前没先 query_costs 看是否已存在同名条目 — 容易录重复（同一个 SKU 同名不同 category 是允许的，但同 SKU 同名同 category 应先 disable 旧的）
- 用模糊话术回老板（"已成功录入数据" → 否；"录好了 SKU-A 物流费 5 块/件" → 是）

## 已知约束

- record_cost / disable_cost_item 都走 Human Gate（W3a 锁定，本 skill 不绕过）
- 一次 record_cost 只录一条，老板说"批量录 3 条" → skill 拆 3 次走 5 步
- import_costs.py 是 CSV 批量入口，超过 10 条建议老板用脚本而不是 skill：
  ```
  docker exec omni-knowledge-engine python /app/scripts/import_costs.py /app/scripts/cost_template.csv
  ```

## 跟 CLAUDE.md 的关系

CLAUDE.md "老板响应词约定" line 40 写过：
> 录成本 / 加成本 / 录入物流费 → 调 `record_cost(...)`，老板用 `python -m app.mcp.cli_approve approve <id>` 批

本 skill 是这条约定的展开 SOP（更详细 + 5 步走 + 错误处理）。两边话术冲突时以 CLAUDE.md 为准。
