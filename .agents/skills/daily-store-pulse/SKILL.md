---
name: daily-store-pulse
description: 看店铺今天/昨天/最近的整体脉搏。老板说"看一下今天店铺咋样"、"今日大盘"、"店铺数据日报"、"最近两天店铺变化"等，触发标准 4 步走 SOP，串 fetch_compass_store_daily + fetch_yuntu_brand_mind + search_kb 异动模板出日报。仅**全店当日/近几日**脉搏日报：单 SKU 体检走 product-analysis、跨月/趋势经营分析走 generate_business_analysis、要此刻实时真值走 platform-data。
---

# daily-store-pulse：店铺脉搏日报 SOP

> omni-vibe 项目内 skill。老板说"看一下店铺/今日大盘/最近店铺咋样"时，按 4 步走，**每步停下等反馈**。

## 触发场景（话术 → date_range）

| 老板话术 | date_range 解析 |
|---|---|
| "看今天店铺咋样" | last_1d（今日实时） |
| "昨天店铺数据" | yesterday |
| "最近三天" | last_3d |
| "近一周/这周" | last_7d |
| "店铺日报" | last_1d（默认） |
| "对比上周" | last_7d + 加 vs_prev_7d 标志 |

## 标准 4 步 SOP

### Step 1: 拿罗盘大盘数据（必查）

```python
fetch_compass_store_daily(date_range="last_1d")  # 或 yesterday / last_3d / last_7d
```

返回包含：
- visit_uv（访客）
- pay_buyer_count（支付买家数）
- gmv_paid（**用户支付金额** —— feedback memory 强制命名，不要写 GMV/成交金额/实收）
- conversion_rate（转化率）
- refund_rate（退货率）

把核心数字给老板看（**不要堆全部字段**，挑这 5 个）：

> "今日（截止 14:00）：UV 1245，支付买家 38 人，用户支付金额 ¥3120，转化 3.05%，退货 4%。继续看品牌心智 + 异动判断？"

如果罗盘失败（cookie 过期 / 网络）→ **明说**："罗盘 store_daily 拉失败：<错误>。要刷 cookie 还是先用云图数据继续？"

### Step 2: 拿云图品牌心智（可选但推荐）

```python
fetch_yuntu_brand_mind(date_range="last_1d")  # 同 Step 1 的 date_range
```

返回品牌**搜索热度 / 关键词 TOP / 兴趣人群**。把 Top 3 给老板：

> "今日云图品牌心智：搜索热度 +12% 环比，TOP 关键词「和田宽 辣酱油」「和田宽 5度米醋」，兴趣人群「调味品爱好者」环比涨 8%。继续 Step 3？"

云图失败 → 明说，不阻塞。

### Step 3: 异动判断（关键步！）

把 Step 1+2 数字跟"昨日/上周同期"对比，找**异动**（变化 ≥10% 或绝对值显著）：

```python
search_kb(
    query="店铺数据 异动 OR 转化下降 OR 流量增长",
    kb_roles=["methodology"],
    top_k=5,
)
```

KB methodology 区里**老板/卡兹罗的"异动判断 SOP"**——比如"转化下降 10%+ 该看哪 3 个原因"。如有，**摘判断框架**给老板：

> "今日异动 2 处：
> 1. 转化 3.05% vs 上周 4.2%（**降 27%**，触发异动）
> 2. UV 1245 vs 上周 1100（**涨 13%**，正常波动）
>
> KB methodology 有「转化下降 SOP」3 个排查项：
>   a. 详情页素材老旧
>   b. 价格变动 / 优惠活动结束
>   c. 流量来源结构变了（达人下播）
>
> 我用这 3 项排查转化降，UV 涨忽略。可以吗？"

老板 OK → Step 4 出报告；如果老板说"UV 涨也排查" → 重调 KB 用涨幅 query。

### Step 4: 出脉搏日报

```
## <店铺名> 脉搏日报（<日期>）

### 1. 大盘数据（today）
- UV：1245（vs 上周同期 +13% ✓）
- 支付买家：38 人（vs 上周 -8%，正常）
- 用户支付金额（gmv_paid）：¥3120（vs 上周 -12% ⚠）
- 转化率：3.05%（vs 上周 4.2%，**-27% ⚠**）
- 退货率：4%（正常区间）

### 2. 品牌心智（云图）
- 搜索热度：+12%
- TOP 关键词：和田宽 辣酱油 / 和田宽 5度米醋
- 兴趣人群：调味品爱好者 +8%

### 3. 异动 + 排查
**异动**：转化 -27%
**排查 3 项**（KB methodology「转化下降 SOP」）：
  a. 详情页素材：<最近改过没？需要看>
  b. 价格变动：<查 sku 价格表>
  c. 流量来源：<查罗盘流量来源结构>

### 4. 待老板拍板
- 排查项 a/b/c 哪个先看？
- 要不要把"转化下降"事件 save_decision 存档（防过两天又忘）？
```

**关键约束**：
- 异动判断必须**有数字依据**（环比%或绝对值），不要"感觉跌了 / 大概涨了"
- 用 **gmv_paid** 命名，不要 GMV/成交金额（feedback memory 强制）
- 排查项**带方法论 KB 来源**
- 不要**自动**继续做排查 — 等老板拍哪个先看
- 退货率 5% 以内是正常，不要每次都报警

## 错误处理

| 错误 | hint | 怎么办 |
|---|---|---|
| `fetch_compass_store_daily` 401 | cookie 过期 | 提示老板"罗盘 cookie 过期，刷一下" |
| `fetch_yuntu_brand_mind` 拉空 | 云图未授权或 SKU 没数据 | Step 2 跳过，只用罗盘数据 |
| `search_kb` methodology 返空 | 没异动 SOP 模板 | 退化用通用 3 项排查（素材/价格/流量），但**告诉老板** |
| 没异动 | 数字波动 <10% | Step 3 直接出"今日平稳"，不强报异动 |

## 反例（**禁止**）

- 把"GMV"或"成交金额"作为字段名 — 强制 gmv_paid（feedback memory）
- 异动靠感觉判断，不带数字 — 必须 ≥10% 或绝对值显著
- 一气呵成跑完 4 步不停 — 必须每步反馈
- 退货 4% 报警 — 5% 以内正常区间
- 用 AI 化套话（"全方位赋能/数据闭环/精细化运营"）— 说人话
- Step 4 自动开始排查 a/b/c — 等老板拍

## 已知约束

- 本 skill **纯读**，不写入任何数据
- 罗盘 cookie 持久性差（约 12 小时）；老板早起刷一次能撑半天
- 云图数据有 24h 延迟（"今日"实际是昨日数据）
- "对比上周"需要历史数据已被 fetch；首次跑没历史就退化只出"今日"

## 跟 CLAUDE.md / 其他 skill 的关系

- 是 W4 加分项 schedule_observation 的最佳"被定时调用"对象（老板可以 cron 每天 9:00 触发本 skill 自动跑 → save_decision 存日报 → send_wecom_message 推企微）
- 触发"转化下降"异动 → 老板可能转去调 product-analysis（看具体哪款 SKU）或 crowd-sop（看人群是不是变了）
- CLAUDE.md "老板响应词约定"通用："重来" → 同 step 重调；"换 date_range" → 改参数重跑
