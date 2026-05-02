# 路径 A · 验收：抖店 MVP 验收文档

> 配套 PRD：`01-PRD-抖店MVP产品需求文档.md`
> 配套施工：`02-施工-抖店MVP工程实施文档.md`
>
> 本文档列出 MVP 验收时要逐项核对的测试 case + 数据校对方法 + 边界 case + 性能稳定性指标。

---

## 文档信息

| 项 | 值 |
|---|---|
| 版本 | v1.0 |
| 阶段 | Path A 验收期（Day 13-14） |
| 编写日期 | 2026-04-30 |
| 验收人 | 老板（你） + 研发 |

---

## 一、验收原则

### 1.1 通过标准

**MVP 必达**（不通过则视为路径 A 未完成）：
- 所有 P0 用户故事的验收 checkbox 全部打勾
- 数据准确性 ≥ 99%
- 连续 7 天稳定性测试通过
- 老板试用 3 天后给出"确实在帮我"的主观评价

### 1.2 不通过怎么办

- **不达标项 ≤ 2 项**：标记为 known-issue，路径 A 验收通过，进入路径 B 时一并修
- **不达标项 ≥ 3 项**：路径 A 不通过，延期 3-5 天集中修复

---

## 二、功能验收 Case

### 2.1 V01：scout-agent 8 份 runbook 跑通（v1.4 终版）

**前置**（v1.5 极简化）：三平台账号已配置（罗盘+抖店后台共用 douyin cookie；云图独立登录）+ storage_state 已保存 + sku_bootstrapper 已跑过一次（自动从 g-list 同步全店 41 SKU）+ focus_pool_builder 已跑过一次（自动选出 ~9 个重点池 SKU）+ 品牌设置为 WADAKAN/和田宽（食品饮料）。**不再需要 5 个 MVP SKU 商品 ID，不再依赖企微 webhook**。

#### Case V01-1：单品概览 runbook

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 在 `/scout` 页面点击「立即执行」单品概览 | 显示 running 状态 |
| 2 | 等待执行完成（约 1-3 分钟） | 状态变 success |
| 3 | 检查 `mvp_runbook_run` 表 | 1 条记录，status=success |
| 4 | 检查 `mvp_daily_metric` 表 | **全店 41 SKU × ≥6 个核心 metric = ≥246 条记录**（昨天日期，允许 ≤ 5 条偶发漏抓） |
| 5 | 抽 2 个 SKU 跟抖店罗盘后台对比 | gmv_paid / UV / CTR 三项数值差异 < 1% |

**通过条件**：步骤 5 数值差异 < 1%。

#### Case V01-2：流量来源 runbook

类似 V01-1，重点验证：来源分类（视频内容 / 搜索 / 推荐）+ 各渠道 UV 占比能正确入库。

#### Case V01-3：评价管理 runbook

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 触发 reviews runbook | 跑通 |
| 2 | 检查抓取到的评价文本 | 与抖店后台一致（至少抓全昨日新增评价） |
| 3 | 检查差评摘要（LLM 生成） | 在 `mvp_anomaly` 中，type=negative_reviews，描述合理 |

#### Case V01-4：商品权重分（视觉读图）

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 触发 product_weight runbook | 跑通 |
| 2 | 检查截图归档 | `./snapshots/{date}_weight_*.png` 存在 |
| 3 | 检查 LLM 提取的 weight_score | 与人工读图差异 ≤ 5% |
| 4 | 抽 2 个 SKU 对比 | 排名一致，分数偏差小 |

#### Case V01-5：抖店后台 SKU 主数据同步（v1.4）

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 触发 g-list runbook | 跑通 |
| 2 | 检查 `mvp_sku` 表 | **全店 41 行**（不是 5 行）；每行的 `platform_status` / `total_stock` / `available_stock` / `created_on_platform_at` / `growth_class` / `in_focus_pool` 字段全部有值 |
| 3 | 抽 2 个 SKU 对照抖店后台 g-list | 库存数据一致（差异 = 0） |
| 4 | 检查重点池规则 | `SELECT id, focus_reason FROM mvp_sku WHERE in_focus_pool=TRUE` 返回 ~9 行：5 个 'top_gmv' + 2 个 'declining' + 2 个 'new'（如老板锁定了 SKU，再加 ≤5）|

#### Case V01-6：抖店后台库存变更记录（v1.4，双轨轨 B）

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 在抖店后台手动改 SKU-A001 的库存 +50 | 操作完成 |
| 2 | 等下一次 stock-change runbook 跑（每 30 分钟）| 跑通 |
| 3 | 查 `mvp_stock_change_log` 表 | 1 条记录，change_type='manual_set'，delta=50，source='shop_admin_log' |
| 4 | 同时查 `mvp_change_event` 表 | 1 条记录，asset_type='product'，source='shop_admin_log'，自动关联到 mvp_stock_change_log |

#### Case V01-7：抖店后台物流诊断 3 Tab（v1.4）

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 触发 logistics-project-diagnosis-index runbook | 跑通（3 Tab 全部抓取）|
| 2 | 查 `mvp_daily_metric` 表 | logistics_pickup_avg_hours / logistics_overdue_orders / logistics_pickup_rate / logistics_trunk_rate / logistics_lastmile_rate 5 项当日有值 |
| 3 | 抽 1 项对照抖店后台 | 数据一致 |

#### Case V01-8：抖店后台评价管理 4 Tab（v1.4）

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 触发 maftersale-comment runbook | 跑通 |
| 2 | 查 `mvp_daily_metric` 表 | review_real_pic_ratio / review_video_ratio / review_quality_ratio / review_invite_count 4 项当日有值 |
| 3 | 抽 1 项对照抖店后台评价管理 | 数据一致 |

#### Case V01-9：云图 5A 资产 + 6 场景流转（v1.4 关键）

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 触发 yuntu-5a-asset + yuntu-5a-flow runbook | 跑通 |
| 2 | 查 `mvp_5a_asset_daily` 表（品牌级 brand_id='WADAKAN_HETIANKUAN', sku_id IS NULL） | 6 项 5A 字段（o_count/a1_aware/a2_appeal/a3_ask/a4_act/a5_advocate）全部有值 + 行业对比百分位有值 |
| 3 | 查 `mvp_5a_flow_daily` 表 | 6 个 scene（acquire/reservoir/seed/live_convert/seed_convert/repurchase）全部有 1 条记录 + outperform_pct 有值 |
| 4 | 抽 1 项对照云图 5A 关系资产 | 数据一致（差异 < 1%）|

#### Case V01-10：云图品牌心智 3 指标（v1.4）

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 触发 yuntu-image-mind runbook | 跑通（品牌级 + **重点池 ~9 SKU** 商品级共 ~10 份）|
| 2 | 查 `mvp_brand_mind_daily` 表 | ~10 行（1 品牌级 + 重点池 SKU 商品级）；每行 brand_assoc_count / industry_share / industry_rank / reputation / preference 全部有值 |
| 3 | 抽 1 项对照云图品牌心智 | 数据一致 |

#### Case V01-11：云图 GMV TO 5A 归因 + 触点效能（v1.4）

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 触发 yuntu-gta runbook + yuntu-touchpoint runbook | 跑通 |
| 2 | 查 `mvp_daily_metric` 表 | gta_5a_buyer_ratio / gta_o_buyer_ratio / gta_a3_in_5a_ratio / touchpoint_traffic_share_* 系列字段当日有值 |
| 3 | 抽 1 项对照云图 GMV TO 5A 概览 | 数据一致 |

---

### 2.2 V02：连续 7 天稳定性（v1.4 三平台 8 份 runbook）

**测试期**：MVP 上线后第 1-7 天每日 08:30 自动跑 8 份 runbook（A 全店日报 / B SKU 详情 / C 客服与原声 / D 搜索与流量与营销 / E 人群与机会 / F 物流与履约 / G 品牌心智 / H 品牌资产+触点效能）。

| 指标 | 阈值 |
|---|---|
| 单 runbook 任务成功率 | ≥ 95%（即 7 天 × 8 份 = 56 次执行至多 3 次失败） |
| 任意 runbook 连续失败次数 | ≤ 2 次（连续 3 次失败必须告警） |
| 失败时是否 100% 触发通知（任一启用通道：站内/浏览器/企微/邮件）| 100% |
| 三平台登录态过期是否被正确识别 | 是（罗盘+抖店后台共用 cookie / 云图独立各自检查） |
| 6 待办数实时抓取（每 30 分钟）| 24×7 = 168 次至多 5 次失败 |

**测试方法**：
1. Day 1 早上验证全部 8 份 runbook（A-H）跑通
2. 之后 7 天每天早上 9:00 上 `/scout/runs` 检查
3. 第 7 天统计：累计执行次数 / 失败次数 / 失败原因

---

### 2.3 V03：全店 SKU 数据完整 + 重点池深度数据完整（v1.5）

**Case V03-1：覆盖度（v1.5：全店 SKU 主数据 + 核心日报 + 重点池深度）**

```sql
-- A. 全店 41 SKU 每天的核心日报 metric（主线）
WITH expected_full AS (
  SELECT s.id AS sku_id, d::date AS date, m.metric_name
  FROM mvp_sku s   -- 全店 41 SKU
  CROSS JOIN generate_series(CURRENT_DATE - 7, CURRENT_DATE - 1, '1 day') d
  CROSS JOIN (VALUES
    ('gmv_paid'), ('uv'), ('ctr'), ('cvr'), ('aov'), ('refund_rate'),
    ('sku_total_stock'), ('sku_growth_class')
  ) m(metric_name)
),
actual AS (
  SELECT sku_id, date, metric_name FROM mvp_daily_metric
  WHERE date BETWEEN CURRENT_DATE - 7 AND CURRENT_DATE - 1
)
SELECT e.sku_id, e.date, e.metric_name AS missing
FROM expected_full e
LEFT JOIN actual a USING (sku_id, date, metric_name)
WHERE a.metric_name IS NULL
ORDER BY e.date, e.sku_id;
-- 通过：返回行数 ≤ 41 × 7 × 8 × 0.01 ≈ 23 条（< 1%）

-- B. 重点池 ~9 SKU 的深度 metric（5A / 心智）
WITH expected_focus AS (
  SELECT s.id AS sku_id, d::date AS date, m.metric_name
  FROM mvp_sku s
  WHERE s.in_focus_pool = TRUE   -- 仅重点池
  CROSS JOIN generate_series(CURRENT_DATE - 7, CURRENT_DATE - 1, '1 day') d
  CROSS JOIN (VALUES
    ('asset_a3_ask'), ('asset_a4_act'), ('mind_brand_assoc')
  ) m(metric_name)
),
actual AS (
  SELECT sku_id, date, metric_name FROM mvp_daily_metric
  WHERE date BETWEEN CURRENT_DATE - 7 AND CURRENT_DATE - 1
)
SELECT e.sku_id, e.date, e.metric_name AS missing
FROM expected_focus e
LEFT JOIN actual a USING (sku_id, date, metric_name)
WHERE a.metric_name IS NULL;
-- 通过：返回行数 ≤ 5 条（重点池 SKU 偶发漏抓）
```

**通过条件**：A 部分缺失 < 1%；B 部分缺失 ≤ 5 条。

**Case V03-2：5A 资产 + 流转完整性（v1.4）**

```sql
-- 品牌级 5A 资产 7 天每天有 1 行
SELECT date, COUNT(*) AS rows
FROM mvp_5a_asset_daily
WHERE brand_id = 'WADAKAN_HETIANKUAN'
  AND sku_id IS NULL
  AND date BETWEEN CURRENT_DATE - 7 AND CURRENT_DATE - 1
GROUP BY date
ORDER BY date;
-- 通过：7 天每天 1 行

-- 6 场景流转 7 天每天 6 行
SELECT date, COUNT(*) AS rows
FROM mvp_5a_flow_daily
WHERE brand_id = 'WADAKAN_HETIANKUAN'
  AND sku_id IS NULL
  AND date BETWEEN CURRENT_DATE - 7 AND CURRENT_DATE - 1
GROUP BY date
ORDER BY date;
-- 通过：7 天每天 6 行（acquire/reservoir/seed/live_convert/seed_convert/repurchase 各一行）

-- 商品级 SPU 5A：重点池 ~9 SKU × 7 天 ≈ 63 行（仅重点池跑深度抓取）
SELECT COUNT(*) FROM mvp_5a_asset_daily
WHERE sku_id IS NOT NULL AND date BETWEEN CURRENT_DATE - 7 AND CURRENT_DATE - 1;
-- 通过：≥ 50 行（允许 ≤ 13 条偶发漏抓）

-- 品牌心智 7 天每天 ≈ 10 行（1 品牌 + 重点池 ~9 SKU）
SELECT date, COUNT(*) AS rows
FROM mvp_brand_mind_daily
WHERE date BETWEEN CURRENT_DATE - 7 AND CURRENT_DATE - 1
GROUP BY date
ORDER BY date;
-- 通过：每天 ≥ 8 行
```

**Case V03-3（v1.5 新增）：重点池规则正确性**

```sql
-- 重点池应该恰好是这些规则的并集
WITH top_gmv AS (
  SELECT id FROM mvp_sku
  WHERE id IN (
    SELECT sku_id FROM mvp_daily_metric
    WHERE metric_name='gmv_paid' AND date >= CURRENT_DATE - 30
    GROUP BY sku_id ORDER BY SUM(value) DESC LIMIT 5
  )
),
declining AS (
  SELECT id FROM mvp_sku WHERE focus_reason='declining' LIMIT 2
),
new_skus AS (
  SELECT id FROM mvp_sku
  WHERE created_on_platform_at >= CURRENT_DATE - 30
  ORDER BY created_on_platform_at DESC LIMIT 2
)
SELECT id, focus_reason FROM mvp_sku
WHERE in_focus_pool = TRUE
ORDER BY focus_reason;
-- 通过：返回 ~9 行（5 'top_gmv' + 2 'declining' + 2 'new'）+ 任何 'locked' 的

---

### 2.4 V04：异动检测正确性

#### Case V04-1：人为造异动

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 在 `mvp_daily_metric` 手动插入：SKU-A001 今天 gmv = 1000，过去 7 天平均 gmv = 5000（跌 80%） | - |
| 2 | 调用 `POST /api/v1/scout/anomalies/detect/SKU-A001` | 返回 anomalies 列表，包含 rule_id=`gmv_drop_25` |
| 3 | 检查 `mvp_anomaly` 表 | 1 条新记录，severity=urgent |
| 4 | 检查 `mvp_decision_log` 表 | 1 条新 pending 决策（来源 scout_anomaly） |
| 5 | 工作台首页 | 该 SKU 的异动卡片出现在 `今天值得关注` |

#### Case V04-2：13 条规则全部覆盖（v1.4）

逐一构造数据触发：
- 罗盘相关 6 条：`gmv_drop_25` / `gmv_surge_50` / `ctr_3day_decline` / `kpi_3day_improve` / `zero_traffic` / `negative_reviews`
- 抖店后台相关 3 条（v1.3）：`logistics_overdue_alert` / `experience_score_drop` / `todo_overflow`
- 云图相关 4 条（v1.4）：`5a_asset_3day_decline` / `flow_scene_under_industry_30pct` / `mind_3indicator_3day_decline` / `touchpoint_imbalance_80pct`

每条规则至少 1 次正向触发 + 1 次反向不触发（边界值）。

---

### 2.5 V05：工作台首页（v1.4 含 5A 心电图 + 6 待办 + 6 场景策略卡）

| Case | 操作 | 预期 |
|---|---|---|
| V05-1 | 打开 `/workspace` | 显示 6 个区块：**5A 心电图卡** / **6 待办数实时卡** / 今日巡店状态 / 今天值得关注 / **6 场景化策略卡** / 本周决策状态 |
| V05-2 | 8 份 runbook 全部 success | 巡店状态显示 8 个 ✓ |
| V05-3 | 1 个 runbook 失败 | 巡店状态显示 1 个 ⚠ + 重试按钮 |
| V05-4 | 异动卡片排序 | urgent > warning > positive；同级按时间倒序 |
| V05-5 | 点异动卡片 | 跳到 `/sku/{id}` |
| V05-6 | 当日无异动 | 显示"今日无异动"+ 健康指标摘要 |
| V05-7 ⭐ | 5A 心电图卡 | 显示 6 张大卡（O/A1-A5 各一张），每张含数值 + 行业百分位 + 7 日趋势小图 |
| V05-8 ⭐ | 6 待办数卡 | 显示 6 个数字（待发货/待售后/待评论/待审核/异常/申诉），点击跳到抖店后台对应页 |
| V05-9 ⭐ | 6 场景化策略卡 | 显示 6 张场景卡（拉新/蓄水/种草/直播转化/种草转化/复购），每张含"超过同行 X%" + 1 句行动建议 |

---

### 2.6 V06：SKU 详情页 3 Tab

#### 概览 Tab

| Case | 预期 |
|---|---|
| V06-1 | 14 天趋势图正确显示 4 条线 |
| V06-2 | 鼠标悬停曲线某点显示该日期的具体数值 |
| V06-3 | 该 SKU 所有 change_event 在图上显示为竖线 |
| V06-4 | 鼠标悬停竖线显示动作描述 |
| V06-5 | 关键指标卡：4 metric × 4 时间窗口正确 |
| V06-6 | 异动事件列表（如该 SKU 有未处理异动） |

#### 动作 Tab

| Case | 预期 |
|---|---|
| V06-7 | 时间轴按 executed_at 倒序 |
| V06-8 | 截图缩略图正确显示，点击放大 |
| V06-9 | 已验证的动作显示 verdict 徽章 + 前后对比卡可展开 |
| V06-10 | 「+ 登记动作」按钮可用 |
| V06-11 ⭐（v1.4）| 双轨标记：来自 `user_manual`（用户登记）显示 👤 / `shop_admin_log`（抖店后台）显示 🏪 / `yuntu_log`（云图）显示 ☁️ |

#### 概览 Tab v1.4 增补

| Case | 预期 |
|---|---|
| V06-Z1 ⭐ | SKU 详情页顶部显示**SPU 5A 心电图卡**（来自 mvp_5a_asset_daily where sku_id={id}）|
| V06-Z2 ⭐ | 显示该 SKU 的**商品级品牌心智 3 指标**（联想量 / 美誉度 / 偏爱度）|
| V06-Z3 ⭐ | 显示**抖店后台 SKU 主数据**（platform_status / total_stock / available_stock / growth_class） |

#### AI 诊断 Tab

| Case | 预期 |
|---|---|
| V06-11 | 列出本 SKU 关联的所有 decision_log |
| V06-12 | 状态徽章正确显示（pending/adopted/rejected/...） |
| V06-13 | 「采纳」按钮 → 自动建一条 change_event（pending） |
| V06-14 | 「拒绝」按钮 → 弹窗填原因 → 状态变 rejected |
| V06-15 | 「启动深度诊断」→ 触发圆桌讨论 + 结果落库 |

---

### 2.7 V07：动作登记表单

| Case | 操作 | 预期 |
|---|---|---|
| V07-1 | 进入 SKU 详情页点「+ 登记动作」 | 表单弹出，SKU 默认当前 SKU |
| V07-2 | 必填字段未填提交 | 表单校验提示 |
| V07-3 | 提交 | < 1 秒响应 |
| V07-4 | 提交后 | 立即可见在「动作」Tab 时间轴，标记 source=user_manual 👤 |
| V07-5 | 截图上传 jpg/png ≤ 5MB | 上传成功，缩略图显示 |
| V07-6 | 截图上传 > 5MB | 表单提示"超出大小限制" |
| V07-7 | 截图上传 .exe | 表单提示"不支持的文件类型" |
| V07-8 | 单次完整登记耗时（含截图上传） | ≤ 60 秒 |
| V07-9 ⭐（v1.4）| 表单顶部"系统已自动抓到 X 条抖店后台动作"提示 | 当系统在轨 B 已抓到该 SKU 当日动作时显示，引导用户补充原因 |
| V07-10 ⭐（v1.4）| asset_type 下拉 | 显示 12 大类（product/asset/price/ad/content/audience/talent/service/campaign/shop_ops/user_reach/brand_strategy） |

---

### 2.8 V08：前后对比卡

#### Case V08-1：基本流程

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 在 SKU-A001 登记动作（executed_at = 7 天前） | change_event 创建，verification_status=pending |
| 2 | 等到第 7 天 02:00 cron 触发 | verification 自动跑 |
| 3 | 检查 `mvp_verification` 表 | 1 条记录，含 4 KPI deltas |
| 4 | 检查 SKU 详情页动作 Tab | 该动作显示 verdict 徽章 + 对比卡可展开 |
| 5 | 检查 `mvp_change_event.verification_status` | 变 completed |

#### Case V08-2：数据校对

随机抽 3 条已 verified 的对比卡，手动用 SQL 计算前后窗口的 KPI 平均：

```sql
SELECT AVG(value)
FROM mvp_daily_metric
WHERE sku_id = 'SKU-A001'
  AND metric_name = 'ctr'
  AND date BETWEEN '2026-04-15' AND '2026-04-22';
```

**通过条件**：与 verification.kpi_deltas 中 pre/post 值一致（误差 < 0.1%）。

#### Case V08-3：verdict 判定

| 输入 | 预期 verdict |
|---|---|
| 4 KPI 全 +20% | positive |
| 4 KPI 全 -20% | negative |
| 4 KPI 全在 ±5% 内 | neutral |
| 2 涨 2 跌（±15%） | neutral |

#### Case V08-4：窗口冲突

构造场景：SKU-A001 在 4/22 改主图，4/24 又改详情页。验证 4/22 的对比卡：

| 预期 | 验证 |
|---|---|
| verdict = `inconclusive` 或 verification 跳过 | 7 天内有其他动作，无法干净归因 |

---

### 2.9 V09：决策日志

| Case | 操作 | 预期 |
|---|---|---|
| V09-1 | 圆桌讨论结束点「💾 存入决策日志」 | 弹窗，可填标题/SKU/类型 |
| V09-2 | 提交 | localStorage + mvp_decision_log 双写（路径 A 后端可选） |
| V09-3 | 进入 `/decisions` | 列表显示该决策 |
| V09-4 | 状态筛选 | 切换 tab 数量正确 |
| V09-5 | 异动检测自动写入 | source_module=scout_anomaly，自动 pending |
| V09-6 | 点采纳 | 状态变 adopted + linked_change_event 创建（如有） |
| V09-7 | 点拒绝填原因 | 状态变 rejected，原因可见 |

---

### 2.10 V10：三平台登录态续期（v1.4）

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 手动删除 `sessions/douyin_compass.json` | 模拟罗盘登录态丢失 |
| 2 | 触发任意罗盘 runbook | 失败，error=`session_expired_compass` |
| 3 | 收到通知（默认前端站内 + 浏览器原生；如配置了企微也会发企微）| 包含"扫码续期-抖店罗盘"提示 |
| 4 | 进入 `/scout` 看到红色提示条 | 是（标识哪个平台 expired）|
| 5 | 点「扫码续期-罗盘」 | 弹出 Playwright 浏览器窗口（headed） |
| 6 | 扫码登录抖店罗盘 | session 保存 |
| 7 | `mvp_session.health` for douyin_compass | 变 ok |
| 8 | 点「重跑当天失败任务」 | 自动重跑 |
| 9 | 数据完整入库 | ✓ |
| 10 | 重复 1-9 步对 douyin_shop_admin（抖店后台 cookie）| ✓ |
| 11 | 重复 1-9 步对 yuntu（云图，独立登录系统）| ✓ |

---

### 2.11 V11–V23：v1.3 / v1.4 增补验收项

| ID | 验收项 | 数据源 |
|---|---|---|
| V11 | SKU 详情页 7 Tab 与抖店罗盘 product-detail 一一对应（源/流量/流量人群/内容/商品卡/售后/人群分析）| 罗盘 product-detail |
| V12 | 每个核心指标都附带行业均值与百分位 | 罗盘所有页 + 云图所有页 |
| V13 | 差评关键词云能识别 TOP 5 原因（包装/口味/物流/假冒/其他）| 罗盘用户原声 |
| V14 | SKU 主数据来自抖店后台 g-list（41 SKU）；status / 总库存 / 商品诊断分类正确 | 抖店后台 g-list + g-stock-manage-list + growth-common-growth-shelf |
| V15 | 抖店后台库存变更记录已镜像到 mvp_stock_change_log，与用户登记的商品类动作可对账 | 抖店后台库存变更记录 |
| V16 | 首页 6 待办数实时抓取，每天 22:00 推送当日异动 | 抖店后台 mshop-homepage-index |
| V17 | 物流诊断 3 Tab 数据完整（揽收时长 / 超时单分布 / 物流商异常）| 抖店后台 logistics-project-diagnosis-index |
| V18 | 评价管理 4 Tab 数据完整，实拍占比 / 优质占比 / 邀请评价数有值 | 抖店后台 maftersale-comment |
| **V19** ⭐ | 5A 资产 6 卡 + 6 场景流转每天有值，含行业对比百分位 | 云图 assets-crowd-distribution + assets-crowd-flow |
| **V20** ⭐ | 品牌心智 3 指标（联想量 / 美誉度 / 偏爱度）每天有值，品牌级 + **重点池 ~9 SKU 商品级**各 1 份 | 云图 image-mind-monitor |
| **V21** ⭐ | GMV TO 5A 归因路径每天有值（5A 成交占比 / O 机会成交占比 / A3 占 5A 比例）| 云图 assets-gta-overview |
| **V22** ⭐ | 触点效能投放资源分布完整（通投/UGC/品牌广告/达人营销）| 云图 evaluation-* |
| **V23** ⭐ | SPU 5A 资产针对**重点池 ~9 SKU**各跑一份；非重点池 SKU 在用户点开详情页时按需触发抓取 | 云图 assets-commodity-* |
| **V24** ⭐（v1.5）| 重点池规则正确：每周日 23:00 自动重排（GMV TOP 5 + 衰退 TOP 2 + 新品 TOP 2 + 老板锁定 ≤5）| focus_pool_builder.py |
| **V25** ⭐（v1.5）| NotificationChannel 抽象正确工作：未配 WECOM_WEBHOOK_URL 时 inapp + browser_push 仍能发出通知；配置后 wecom 通道自动启用，无需重启 | notification/dispatcher.py |
| **V26** ⭐（v1.5）| sku_bootstrapper 正确：首次启动从 g-list 同步全 41 SKU；老板**完全不需要手动填占位 SKU**| sku_bootstrapper.py |

---

## 三、数据准确性验收

### 3.1 误差容忍度

| 数据来源 | 误差容忍 |
|---|---|
| CSV 导出（gmv/uv/ctr/cvr 等核心字段） | < 1% |
| 视觉读图（weight_score 等） | < 5% |
| LLM 摘要（差评摘要、视觉提取） | 主观评估，准确率 ≥ 80% |

### 3.2 抽样校对

每周从 `mvp_daily_metric` 随机抽 10 条记录，登录抖店后台手动核对。

```sql
-- 抽样 SQL
SELECT sku_id, date, metric_name, value
FROM mvp_daily_metric
WHERE date BETWEEN CURRENT_DATE - 7 AND CURRENT_DATE - 1
ORDER BY RANDOM()
LIMIT 10;
```

### 3.3 校对记录表

每周一抽查后填一份：

| 抽查日期 | SKU | metric | 系统值 | 罗盘值 | 偏差 | 是否通过 |
|---|---|---|---|---|---|---|
| 2026-05-07 | （g-list 真实 SKU ID） | gmv_paid | 5234.50 | 5234.50 | 0% | ✓ |
| ... | ... | ... | ... | ... | ... | ... |

连续 4 周 100% 通过 → 路径 A 数据准确性正式签收。

---

## 四、性能验收

| 指标 | 阈值 | 测量方法 |
|---|---|---|
| 巡店任务总耗时 | ≤ 9 分钟 | `mvp_runbook_run.ended_at - started_at` 平均 |
| 工作台首页加载 | ≤ 1 秒 | Chrome DevTools Network 面板 |
| SKU 详情页加载 | ≤ 1.5 秒 | 同上 |
| 动作登记表单提交 | ≤ 1 秒 | 同上（不含截图上传） |
| 单 SKU 14 天数据查询 | ≤ 200ms | API 响应时间 |
| 异动检测引擎 | ≤ 90 秒（**全店 41 SKU + 13 类规则**全跑完） | 日志时间戳 |
| 验证 cron（10+ pending events） | ≤ 90 秒 | 日志时间戳 |
| 重点池重排（focus_pool_builder） | ≤ 30 秒 | 日志时间戳 |

---

## 五、稳定性验收

### 5.1 7 天连续运行

**起止**：MVP 上线日 ~ +7 天

**统计指标**：

```sql
-- 每天 8 runbook × 7 天 = 56 次执行（v1.4 终版）
SELECT
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE status = 'success') AS success,
  COUNT(*) FILTER (WHERE status = 'failed') AS failed,
  ROUND(COUNT(*) FILTER (WHERE status = 'success')::numeric / COUNT(*) * 100, 2) AS rate
FROM mvp_runbook_run
WHERE started_at >= CURRENT_DATE - 7;
```

**通过**：rate ≥ 95%。

### 5.2 故障恢复

| 故障 | 期望恢复行为 |
|---|---|
| 三平台登录态过期（罗盘/抖店后台/云图任一）| ≤ 2 小时内通知 + 提供续期入口（按平台分别） |
| 罗盘 UI 改版 | 连续 3 天失败自动告警 + LLM 视觉 fallback 启动 |
| 网络中断 | runbook 重试 3 次（2/4/8s 退避） |
| 数据库不可达 | scout-agent 健康检查失败，NotificationChannel 通知（任一可用通道）|
| LLM 视觉服务不可达 | 跳过视觉步骤但 CSV 步骤继续 |

---

## 六、安全验收

| 项 | 验证方法 | 通过条件 |
|---|---|---|
| storage_state 加密保存 | 检查 `sessions/` 目录权限 + 文件加密状态 | 加密；权限 600 |
| 数据库不暴露公网 | netstat 检查端口 | 仅 127.0.0.1:5432 监听 |
| Gemini key 未入仓 | git log + .gitignore | API key 仅在 .env，不在代码 |
| 截图 / CSV 文件 | 检查 `downloads/` `snapshots/` | 仅本机存储，无上传外网 |

---

## 七、UX 验收（老板主观打分）

完成 7 天试用后填表：

| 维度 | 1-5 分 | 备注 |
|---|---|---|
| 早晨 5 分钟巡店：能完成吗？ | _ | |
| 单 SKU 信息一目了然吗？ | _ | |
| 动作登记不超过 60 秒吗？ | _ | |
| 前后对比卡的结论可信吗？ | _ | |
| AI 建议有没有命中你认为对的方向？ | _ | |
| 周末复盘 ≤ 5 分钟可以做完吗？ | _ | |
| 整体使用体验给几分？ | _ | |

**通过条件**：平均 ≥ 4.0 分。

---

## 八、边界 Case 清单

| ID | 场景 | 期望 |
|---|---|---|
| B01 | 任一 SKU 当日抖店报表为空（节假日） | runbook 不报错，写入 0 / null，不触发异动 |
| B11 | 全店突然新增 SKU | sku_bootstrapper 当日增量同步，新 SKU 出现在 mvp_sku 且 30 天内自动进入新品池 |
| B12 | 老板锁定的 SKU 数量超过 5 | 前端校验阻止；锁定上限 5 |
| B13 | g-list 全店 SKU 数从 41 变成 50+ | 系统不报错，全部同步；重点池仍按规则选 |
| B02 | 时区切换 | 所有 datetime 统一 UTC，前端按本地时区展示 |
| B03 | 单日同 SKU 同 metric 重复入库 | UPSERT，不报错 |
| B04 | 7 天前后对比窗口跨月 | 正确取数 |
| B05 | 截图文件名含中文 | 正确保存 + 可访问 |
| B06 | 决策日志全文 ≥ 50KB | 不截断，可正常存取 |
| B07 | 同时间多个 runbook 跑 | Playwright 实例隔离，不互相干扰 |
| B08 | 浏览器 localStorage 满 | 决策日志双写后端，不丢失 |
| B09 | 老板手动改 mvp_change_event 描述 | 不影响 verification 计算 |
| B10 | 删除一个 SKU | 关联 metric/event/decision 全部 cascade |

---

## 九、上线 Checklist

```markdown
☐ 三平台账号首次扫码登录完成（罗盘+抖店后台共用 + 云图独立），storage_state 已保存
☐ sku_bootstrapper 已跑过一次，全店 41 SKU 已在 mvp_sku 表
☐ focus_pool_builder 已跑过一次，重点池 ~9 SKU 已标记 in_focus_pool=TRUE
☐ NotificationChannel 抽象正常工作（inapp 默认，wecom 端口预留可后补）
☐ Gemini API key 已配置并测试
☐ 8 份 runbook（A-H）全部跑通至少 1 次
☐ V01-V26 全部通过（v1.5 终版）
☐ 7 天稳定性测试通过（56 次执行 success_rate ≥ 95%）
☐ UX 评分 ≥ 4.0
☐ 数据准确性首周抽样 ≥ 99%
☐ 老板使用指南交付
☐ scout-agent 进 docker-compose 自启
☐ APScheduler 时区配置正确（Asia/Shanghai）
☐ 截图归档磁盘容量预留 ≥ 50GB
☐ 备份策略确定（mvp_* 表每日备份）

# 后续可补（不阻塞上线）：
☐ 企微 webhook URL（写入 .env WECOM_WEBHOOK_URL）
☐ 邮件 SMTP 配置（写入 .env SMTP_*）
```

---

## 十、不合格修复路径

| 问题 | 修复策略 |
|---|---|
| Runbook 失败率 > 5% | 加 selector 容错 + 视觉 fallback |
| 数据偏差 > 1% | 检查 CSV 字段映射 / 时区 / 累计逻辑 |
| 异动检测过于敏感 | 调阈值参数（写到 config 表，不改代码） |
| AI 建议命中率低 | 调圆桌 prompt + 增加知识库人群报告 |
| 老板用得累 | 砍功能：先保留巡店推送 + 单 SKU 视图 + 动作登记，其他延后 |

---

## 十一、文档关联

| 关联文档 | 作用 |
|---|---|
| `01-PRD-抖店MVP产品需求文档.md` | 验收标准来源（用户故事 V01-V10） |
| `02-施工-抖店MVP工程实施文档.md` | 测试环境与数据模型 |
| `04-使用指南-抖店MVP使用指南.md` | 老板试用期参考 |

---

## 文档变更记录

| 版本 | 日期 | 内容 |
|---|---|---|
| v1.0 | 2026-04-30 | 初稿 |
