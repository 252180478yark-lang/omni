---
name: crowd-sop
description: Use when the user asks to create a new audience pack, 圈包 SOP, 圈人策略, 受众怎么定, or sku-pipeline step 4 audience-pack output for 和田宽/SKU/巨量云图/千川 context. Do not use for diagnosing or purifying an existing exported audience pack.
---

# crowd-sop: 巨量云图圈包 SOP

## Scope

Use this skill for creating a new audience pack strategy from product, selling points, scenes, matched audience, and Yuntu capabilities.

Do not use it for:
- 诊断/提纯/适不适合投/太大了帮我切 an existing exported pack. Use `audience-pack-diagnosis`.
- 投放预算、出价、ROI/GMV 预测、计划类型分配.
- 视频脚本 or content creation. Those consume the final audience pack later.

If this is sku-pipeline step 4 and there is an `audience_record_id`, call or route to `generate_audience_pack`. Do not hand-write a parallel SOP from memory. The long prompt of record is `services/knowledge-engine/config/prompts/audience_pack.system.md`.

## Core Principle

**源图优先, 场景继承, 后台可执行.**

Yuntu audience packing is not:

```text
商品品类 -> 硬判人群能不能买
```

It is:

```text
卖点矩阵 X.Y [卖点]
-> 场景 2.X [使用/内容/消费场景]
-> 人群真实需求/内容信号
-> 云图真实标签/关键词/行为入口
-> 自定义人群包/标签工厂标签
-> 推送千川
```

不能因为 SKU 是酱油就否定人群。抖音是兴趣电商, 品类不是否决条件, 也不是通行证。必须判断这个卖点在这个场景里能不能触发该人群的真实需求或内容兴趣。

## Source Graph First

Before writing the SOP, consult the latest Yuntu source graph and deterministic taxonomy if available:

- Live crawl summary: `data/yuntu_live_crawl_20260703/yuntu_source_graph_live_summary.md`
- Custom audience live JSON: `data/yuntu_live_crawl_20260703/custom_audience/custom_audience_live.json`
- Data factory live JSON: `data/yuntu_live_crawl_20260703/data_factory/data_factory_live.json`
- Deterministic tool when available: `query_yuntu_taxonomy`

Known live backend facts from 2026-07-03:

| Area | Confirmed Structure |
|---|---|
| 自定义人群 | 6 个一级区 / 11 个二级分组 / 61 个可点入口 |
| 一级区 | 我的人群, 触点场景圈人, 用户属性, 兴趣偏好, 行业品类兴趣, 标签工厂 |
| 内容偏好 | 抖音视频观看分类 captured 25 一级 / 147 二级 |
| 数据工厂 | 当前主入口是 标签工厂 / 数据融合 |
| 标签工厂 | 内容标签 / 人群标签 / 达人标签 |
| 人群标签 | 内容人群标签 / 搜索人群标签 / 商品人群标签 |
| 关键词夹 | 不是左侧独立一级菜单, 是标签工厂表单里的导入抽屉 |
| 关键词池 | 表单显示 关键词池 0/500, 可从关键词夹导入或使用词联想工具 |
| 数据融合 | 人群上传 / 转化事件 / 数据上传 |

Full traversal does not mean full selection. Use the source graph to know what is possible, then select only labels that inherit the selling-point scene chain.

## Required Workflow

### 1. Read Inputs

Collect or infer:

- SKU/product facts
- adopted selling-point matrix
- adopted audience match or audience profile
- scene bridge and match reasons
- KB/persona evidence
- `include_ecommerce_data`
- whether this is a broad reach master pack or a precision test pack

If the user is only brainstorming with no SKU/matrix/audience context, ask one concise question. If the pipeline already has adopted upstream artifacts, do not stop at every step.

### 2. Build The 场景链路继承表

Every SOP must include a scene-chain table before the audience units:

| Link | Required Content |
|---|---|
| L1/L2/L3 | Chain id |
| 卖点 | matrix section id + selling point |
| 场景 | matrix scene id + scene name |
| 人群需求 | why this audience is triggered |
| 可圈信号 | content preference, search terms, behavior, attribute, touchpoint, or data factory tag |
| 圈人单元 | A/B/C unit using this chain |

If a unit cannot point to L1/L2/L3, delete or rewrite it.

### 3. Choose The Correct Yuntu Route

Pick 1 to 3 route families, not everything.

| Need | Route |
|---|---|
| 固定年龄/地域/消费群体/内容偏好/IP/行业特色 | 自定义人群 -> 新建人群 -> direct labels |
| 任意关键词, 近 30 天搜过 X, 看过/互动过 X 内容 | 数据工厂 -> 标签工厂 -> 新建搜索人群标签 or 内容人群标签 -> 回自定义人群引用 |
| 商品标题/品类/购买/加购/浏览/成交行为 | Only when `include_ecommerce_data=True`, use 商品人群标签 |
| 老客/店铺/直播/小店/达人/5A | 触点场景圈人 or 我的人群 |
| Need scalable content/search signal | generate_keyword_pack -> 关键词夹/关键词包 -> 标签工厂标签 |

Data policy:

- `include_ecommerce_data=False`: 禁用商品人群标签, 电商品类成交偏好, 电商品牌成交偏好. Use content/search audience tags, Douyin content preferences, attributes, region, and non-commerce interest signals. Keyword route uses `keyword_strategy="audience_content"`.
- `include_ecommerce_data=True`: 商品人群标签 and commerce behaviors can be used. Keyword route may use `keyword_strategy="ecommerce_intent"`.

### 4. Translate Abstract Strategy To Real Clicks

Every selected item needs a real menu path and option name.

| Abstract Target | Backend Landing |
|---|---|
| 31-40 岁 | 用户属性 -> 基础属性 -> 预测年龄 -> 31-35 + 36-40 |
| 下沉/三线及以下 | 用户属性 -> 地域属性 -> 地域分布 -> 按城市级别 -> 三线/四线/五线, then city list 全选 and 确定 |
| 短剧/剧情内容 | 兴趣偏好 -> 内容偏好 -> 抖音视频观看分类 -> 演绎 -> 剧情短剧 |
| 本地民生/务实生活/日常 | 兴趣偏好 -> 内容偏好 -> 抖音视频观看分类 -> 生活 -> 民生 / 生活用品 / 日常活动 |
| 家常饭/下厨内容 | 兴趣偏好 -> 内容偏好 -> 抖音视频观看分类 -> 美食 -> 美食展示 / 日常美食展示 / 制作美食 |
| 任意搜索词 | 数据工厂 -> 标签工厂 -> 新建搜索人群标签 -> 关键词规则 -> 从关键词夹导入 |
| 内容兴趣词 | 数据工厂 -> 标签工厂 -> 新建内容人群标签 -> 内容标题/视频语音/视频字幕 -> 关键词规则 |

IP preference only has fixed buckets like 明星, 电影, 电视剧, 综艺, 动漫. Do not put short-drama interests under IP unless the audience explicitly targets a real IP/drama title.

### 5. Build Audience Units

Create as many units as needed, but no forced count.

Each unit must contain:

- Unit name, such as A: 下班放松内容兴趣人群
- Which Lx scene chain it inherits
- What kind of person it captures
- Exact backend path
- Exact selected labels/options
- Whether it is direct custom audience or data factory first
- One-line reason
- Backend executable check:

```text
抽象目标 X -> 后台真实路径 Y -> 真实可选项 Z -> if missing, use W or switch to data factory
```

### 6. Combine Units Only When Needed

Use combinations intentionally:

- `A ∩ B`: precision, when two signals must both hold
- `A ∪ B`: reach, when several scene clusters are valid
- `A - B`: exclude pollution, old buyers, irrelevant groups, or over-narrow content noise
- lookalike: only after the base pack is valid and too small for scale

Do not use lookalike to compensate for a bad or overly narrow keyword pack. If the base pack is too small, first broaden seeds, content preferences, or union scene clusters.

## Keyword Expansion Rules

Keyword expansion is default for search/content audience tags, especially broad reach packs.

Use:

```text
generate_keyword_pack(
  target_count=500,
  recall_mode="reach",
  keyword_strategy="audience_content" or "ecommerce_intent"
)
```

Seed source must inherit L1/L2/L3:

- KB original audience words
- matrix selling point + scene words
- approved content preference terms

Filtering logic:

```text
max(candidate, 任一种子词或已启用的人群内容偏好)
```

Meaning: a candidate can stay if it is close to any seed or enabled audience content preference. It does not need to be close to all seeds, because clusters like 辅食调味, 凉拌菜, 炒肉丝, 下班放松, 民生生活 may be different semantic clusters.

For `keyword_strategy="audience_content"`, keywords describe people and content they like, not just product terms. They can include lifestyle, local life, family, short drama, emotion, food watching, relaxation, and search curiosity signals if they inherit the scene chain.

For `keyword_strategy="ecommerce_intent"`, keywords can include product category, adjacent categories, competitor/alternative nouns, usage, and purchase intent.

Destination is always:

```text
云图 -> 数据工厂 -> 标签工厂 -> 人群标签 -> 关键词规则/关键词夹 -> 生成标签 -> 回自定义人群引用 -> 推千川
```

It is not 千川计划里的关键词定向.

## Output Contract

Write in plain operator language. The boss should be able to click along.

Required sections:

1. 第 0 部分: 人群画像扩展 + 场景链路继承表
2. 第 1 部分: 圈包概览 + 最准圈人方式判断
3. 第 2 部分: 圈人方案, with N audience units
4. 第 3 部分: 组合运算, only if useful
5. 第 4 部分: 关键词扩展, including seeds, target count, strategy, and data factory destination

Every concrete label must be grounded in one of:

- live source graph
- deterministic Yuntu taxonomy
- KB authoritative/methodology chunk
- explicit backend-search fallback instruction

## Adoption Handoff

After the boss adopts and approves the SOP, do not stop at markdown.

Next default step:

```text
adopted audience pack -> yuntu-audience-automation dry-run -> Yuntu browser execution -> read/screenshot 预估人数 -> 导出画像 -> 圈包准度验收 -> audience-pack-sizing if volume or precision misses target
```

Rules:

- Only hand off packs with `pack_status=adopted`.
- Use `yuntu-audience-automation` for dry-run, keyword package creation, audience unit creation, combination, and final push gates.
- Use `audience-pack-sizing` when Yuntu preview volume misses the target. Adjust labels, time windows, frequency, and formulas before using lookalike.
- The browser executor must capture the real Yuntu preview count, screenshot, and exported audience profile before any completion claim.
- Completion standard is **人数合适 + 包类型明确 + 画像准度通过 + 内容继承方向明确**. 人数合适 alone is not done.

## Post-Execution Acceptance

After Yuntu execution and exported profile are available, run a short 后验画像验收:

1. **量级**: judge whether the real Yuntu count is inside the launch range.
2. **包类型标注**: label the final pack as `reach_master` 放量主包 / 内容探索包, `precision_core` 精准核心包, `content_test` 内容测试包, or `harvest_intent` 收割意图包.
3. **底盘贡献 vs 意图层贡献**: state whether the final profile is mainly carried by the A base population, or whether B/C search, content, or product-intent layers truly contributed.
4. **画像准度**: check whether the exported profile still inherits `卖点 -> 场景 -> 人群 -> 内容信号`. If it only inherits broad lifestyle interests, mark it as reach/content exploration, not precision.
5. **泛兴趣污染**: explicitly inspect broad interests such as 汽车、游戏、二次元、影视、时尚. If they dominate without scene-chain justification, call them pollution signals and propose one cleanup step.
6. **内容继承方向**: say how downstream `creative_pack` should inherit the final profile. Content must be written for the real exported audience, not only the original audience name.

If a pack has acceptable volume but weak scene/product intent, do not call it failed or too large by default. Classify it as a valid `reach_master` / 内容探索包 and create a separate `precision_core` pack when precise harvesting is needed.

## Prohibited

- Do not reject a valid audience only because the SKU is soy sauce/酱油/调味品.
- Do not invent backend labels like "佛系青年" or "精致猪猪女孩".
- Do not write "近 30 天搜过 X" directly inside custom audience. That requires data factory first.
- Do not put 短剧 under IP 偏好 unless it is a real named IP.
- Do not force all dimensions or all source graph labels into the pack.
- Do not write budget, bid, ROI, GMV, or campaign plan allocation.
- Do not let keywords become pure SKU terms when the pack is non-commerce audience content.

## Final Self Check

Before presenting the SOP:

- Did it start from source graph / taxonomy rather than memory?
- Does every unit cite L1/L2/L3?
- Are all abstract labels translated into backend paths?
- Is data factory used for arbitrary keyword/search/content behavior?
- Is `include_ecommerce_data` respected?
- If keywords are used, is target 500 and destination data factory, not 千川 keyword targeting?
- Can a junior operator follow menu -> click -> select -> name -> save -> push?
- Does the handoff require 后验画像验收 with 包类型标注 before calling the pack complete?
