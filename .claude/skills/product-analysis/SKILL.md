---
name: product-analysis
description: 分析一个 SKU 的健康度（成本/利润/数据/历史决策综合体检）。老板说"分析 SKU-X"、"看下 X 这款卖得咋样"、"X 健康度报告"、"X 还能不能继续推"等，触发标准 5 步走 SOP，串 get_sku + query_costs + compute_margin + fetch_compass_sku_detail + search_kb 出体检报告。
---

# product-analysis：SKU 健康度体检 SOP

> omni-vibe 项目内 skill。老板说"分析 X / X 卖得咋样 / X 还能推不"时，按 5 步走，**每步停下等反馈**。

## 触发场景（话术 → 视角）

| 老板话术 | 视角 | 备注 |
|---|---|---|
| "分析 SKU-X" | 综合 | 5 步走全套 |
| "X 卖得咋样" | 偏数据 | 重点 Step 3（罗盘数据） |
| "X 健康度" | 综合 | 全套 |
| "X 还能不能继续推" | 偏决策 | 重点 Step 4（历史决策）+ Step 5 给建议 |
| "X 利润够不" | 偏成本 | 重点 Step 2（成本+利润） |

## 标准 5 步 SOP

### Step 1: 锁定 SKU + 拿基础信息（mvp_sku 全字段）

老板话术里 SKU ID 不明确就先 list_skus(query=...)；明确就直接：

```python
get_sku(sku_id="SKU-X")
```

W4-B 切片 12 后字段抓全，**重点看**：
- `status` (active / archived) —— 内部状态
- `platform_status` (on_sale / off_sale / out_of_stock / paused / under_review / banned / unknown) —— 抖店真实状态
- `growth_class` (excellent / good / optimizing / declining) —— 抖店诊断分类
- `price_min/price_max` —— 真实卖价
- `total_stock` —— 真实库存
- `owner_selling_points` / `owner_notes` —— 老板手填判断
- `in_focus_pool` / `push_tier` / `focus_reason` —— 老板的重点池标记

**status 警告**：

| 字段 | 警告条件 |
|---|---|
| `status != 'active'` | "这款 status=archived，确实要分析？还是分析当前 active 版本？" |
| `platform_status == 'off_sale'` | "已下架，分析里要不要标'已下架'警示？" |
| `platform_status == 'out_of_stock'` | "已售罄，库存原因，分析时要看销量历史" |
| `platform_status == 'unknown'` | "状态未识别，可能爬虫 UI 失配，要不要重抓？" |
| `growth_class == 'declining'` | "抖店诊断为衰退，体检重点查衰退原因" |

### Step 2: 成本 + 利润（员工版口径默认 + 真实卖价）

```python
query_costs(sku_id="SKU-X", view="public")
compute_margin(sku_id="SKU-X", channel="douyin",
               sale_price=SKU.price_min)  # 用 mvp_sku.price_min 真实价，不让老板说
```

**关键约束**：
- **优先用 mvp_sku.price_min/price_max**（W4-B 切片 12 抓的真实抖店价），不再让老板手报
- 默认走 view='public' 员工口径（出厂价），**不**默认查 real（真实成本需口令）
- 老板话术里**明确说**"真实成本/我自己看的/老板版" → 提示老板传 passphrase 走 real
- compute_margin 不传 channel_fee_rate 自动从 channel_fees 表 fallback（W4-B 切片 9）；
  breakdown.fee_rate_source 字段说明 fee 来源

**双口径警告**：
- 看到 cost_items 里有"主料/人工/包装"等**拆分式**行 + "出厂价合计"行**并存** →
  双算冲突，提示老板用 cost-luru skill 路径 B 桥接清理

把 breakdown 返回的 cost_total / channel_fee / margin / margin_rate 给老板看：

> "成本 ¥X，渠道扣点 2%（来源 channel_fees），毛利 ¥Y，利润率 Z%。这是员工版口径——要看真实账给口令。"

如果 query_costs 返空（缺成本），**别瞎算**——提示老板：

> "这款 SKU 在 cost_items 里查不到记录，全 SKU 默认成本（运费 5 + 包材 3）兜底。要不先 record_cost 录一下产品本身的成本再算？"

### Step 3: 渠道数据（罗盘）

```python
fetch_compass_sku_detail(sku_id="SKU-X", date_range="last_7d")  # 或 last_30d
```

返回的 visit_uv / pay_buyer_count / conversion_rate / refund_rate 等给老板看。

如果失败（罗盘 cookie 过期 / 没数据） → **不要抱**，明说：

> "罗盘 sku_detail 拉失败：<错误信息>。可能 cookie 过期需要重登。先用 cost+利润数据继续，要补这块的话刷 cookie 后重调。"

老板说"先看其他维度"就跳过；老板说"等下，刷 cookie" → 等。

### Step 4: 历史决策（KB authoritative + decisions）

```python
search_kb(query="SKU-X 的相关名 OR 品类决策", kb_roles=["authoritative"], top_k=5)
```

KB 里**之前老板对这款 SKU 或品类的决定**（如"这款 5 度米醋打高端线"/"辣酱油不上低价"）。如有，**摘 1-2 条** 给老板看：

> "找到 1 条历史决策：「2026-04 拍板这款走高端线，不参与 9.9 包邮」。本次分析里要不要把这条作为约束？"

老板说要带就纳入 Step 5；不要就跳过。

### Step 5: 综合体检报告（5 维度打分 + 建议）

把 Step 1-4 的输出拼成结构化报告：

```
## SKU-X 健康度体检（员工版口径，<日期>）

1. **基础**：<品牌+名+规格+状态>
2. **成本利润**：成本 ¥X，毛利率 Y%（注：员工版/含/不含真实成本提示）
3. **数据**（近 7 日）：UV xxx，转化 yy%，退货 zz%（或：罗盘拉失败）
4. **历史决策**：<KB 里相关决策摘要 / 无>
5. **健康度判断**：<3 维打分：成本健康 ✓/✗ / 数据健康 ✓/✗ / 战略一致 ✓/✗>
6. **建议**（3 条，可执行）：
   - 继续推：<具体动作>
   - 调整推法：<具体动作>
   - 下架/撤资源：<具体动作>
```

**关键约束**：
- 不允许 5 个维度全打 ✓ — 体检的意义就是找问题
- 建议必须**可执行**（动词开头：调整 X / 测试 Y / 下架 Z），不要"赋能 / 加强 / 优化"这种空话
- **每条建议带依据**（来源 Step 几）
- 老板说"哪个维度不够细" → 回那个 Step 重调 tool

## 错误处理

| 错误 | hint | 怎么办 |
|---|---|---|
| `query_costs` 返空 | cost_items 没该 SKU | 提示老板录成本（cost-luru skill）或用 default 兜底 |
| `fetch_compass_sku_detail` 401/403 | cookie 过期 | 提示老板刷 cookie，或本次跳过此 step |
| `search_kb` 返空 | KB 里没该品类相关决策 | 跳过 Step 4，Step 5 只 4 维度 |
| `compute_margin` `wrong_passphrase` | 老板要看 real 但口令错 | 提示老板口令在 .env COST_REAL_VIEW_PASSPHRASE |

## 反例（**禁止**）

- 缺成本就硬算（用 default 5+3）不提醒老板 — 算出来不准还误导决策
- 罗盘失败就不报告 — 要明说哪步失败了，别藏
- 5 维度全 ✓ — 体检失败
- 建议写"加强营销/优化转化"这种空话 — 必须具体
- 用真实成本口径但没拿口令 — 默认 public，老板明确要 real 才走
- 一气呵成 5 步不停 — 必须每步停反馈

## 已知约束

- 本 skill **不调** record_cost / 任何写入 tool（纯读分析）
- 默认 channel='douyin'；老板做天猫/京东就明示 channel
- compute_margin 默认 view='public'；老板话术明示"真实成本" 走 view='real' + passphrase
- search_kb kb_roles=['authoritative'] 默认；如果想加方法论维度老板会说

## 跟 CLAUDE.md / 其他 skill 的关系

- 跟 **selling-point-finder** 互补：本 skill 看健康度（成本/数据/决策），那个看卖点（内容角度）
- 跟 **cost-luru** 是反向关系：cost-luru 录数据，本 skill 用数据
- CLAUDE.md "sku 出片标准链路"的 step 1+2 是本 skill Step 1+2 的简化版；如果老板说"sku-X 全链路"先按 CLAUDE.md 走，不必触发本 skill
