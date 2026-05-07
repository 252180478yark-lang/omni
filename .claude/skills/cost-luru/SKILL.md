---
name: cost-luru
description: 录入成本（物流/包装/原料/供应商报价）。老板说"录 sku-X 物流费 5 块"、"加成本 包装 0.8"、"录运费"等，触发标准录成本 5 步走 SOP，调用 record_cost 走 Human Gate，批后调 query_costs 验证。
---

# cost-luru：录成本标准 SOP

> 这是 omni-vibe 项目内 skill。当老板提到"录成本/加成本/录入物流费/录运费/sku-X 加 X 块"等话术时，按本 SOP 走 5 步，**不要一气呵成跑完，每步停下来等老板反馈**。

## 触发场景（5 类话术）

| 话术 | 解析 | tool 调用 |
|---|---|---|
| "录 sku-A 物流费 5 块" | sku_id=SKU-A, category=logistics, item_name=物流费, unit_cost=5 | record_cost(...) |
| "sku-B 加成本 包装 0.8" | sku_id=SKU-B, category=product, item_name=包装, unit_cost=0.8 | record_cost(...) |
| "顺丰华东 8 块每单" | sku_id=None（共享）, category=logistics, item_name=顺丰华东, unit_cost=8, unit=单 | record_cost(...) |
| "C 厂商品报价 12 块/箱 24 瓶" | sku_id=None, category=partner_quote, vendor=C 厂, unit=箱, quantity_per_unit=24, unit_cost=12 | record_cost(...) |
| "改 sku-A 物流费 6 块"（已存在） | 先 query_costs 找旧条 → disable_cost_item 停旧 → record_cost 录新 | 3 tool 链 |

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

## 错误处理

| 错误 | hint | 怎么办 |
|---|---|---|
| `invalid_category` | category 不是 3 选 1 | 跟老板确认是 product/logistics/partner_quote 哪个 |
| `invalid_visibility` | visibility 不是 3 选 1 | 跟老板确认是 public/real/shared 哪个（默认 public） |
| `invalid_decimal` | unit_cost 含非数字 / 负数 | 让老板重说价格 |
| `cost_item_not_found_or_already_inactive` | disable 时找不到 | query_costs 看看 id 对不对 |
| Gate 超时（默认 1h） | 老板 1 小时没批 | 提醒老板在 cli_approve list 里看 / 重调 record_cost |

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
