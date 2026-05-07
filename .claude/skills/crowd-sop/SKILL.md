---
name: crowd-sop
description: 圈一个人群包/受众包的策略 SOP。老板说"圈一个 X 的人群包"、"针对 X 出个圈人策略"、"X 受众咋定"等，触发标准 4 步走 SOP，从 KB authoritative + methodology + 模板 → 出可执行圈人策略文档。
---

# crowd-sop：人群包圈选策略 SOP

> omni-vibe 项目内 skill。老板说"圈一个 X 的人群包/X 受众咋定/出个圈人策略"时，按 4 步走，**每步停下等反馈**。

## 触发场景（话术 → 受众维度）

| 老板话术 | 受众解析 | 关注点 |
|---|---|---|
| "圈一个宝妈的人群包" | demographic（人口）→ 宝妈 | 年龄/家庭结构/带娃阶段 |
| "针对年轻白领出圈人策略" | psychographic（心理）→ 年轻白领 | 收入/通勤/生活节奏 |
| "辣酱油的核心人群" | 品类反推 → 谁吃辣酱油 | 地域/口味偏好/烹饪场景 |
| "上次买过 X 的人群" | behavioral（行为）→ 复购 | 渠道后台抓老客 |
| "5 度米醋的健身人群" | 多维交叉 | demo + psycho 拼 |

不确定时**先反问**："你要的是品类反推（谁吃这个）、行为定向（买过的人）、还是场景代入（什么场合用）？"

**绑 SKU 的 crowd 圈选**（如"圈 SKU-X 的人群包"）：

先 `get_sku(sku_id)` 看 `mvp_sku.growth_class`：
- `excellent` / `good` → 重点池 SKU，圈广泛人群（拉新+复购双侧）
- `optimizing` → 当前数据弱，圈窄精准人群（test 验证）
- `declining` → 衰退期，圈老客户为主（救流失）

`owner_selling_points` 也要看——老板手填的卖点决定 psychographic 维度。

## 标准 4 步 SOP

### Step 1: 拆解老板的话术 → 三类维度

把老板话术拆成 **demographic / psychographic / behavioral** 三类，给老板看：

> "你说'圈一个宝妈的人群包'。我拆成：
> - demographic：女性 / 25-40 岁 / 已婚已育
> - psychographic：注重健康 / 育儿压力 / 选品挑剔
> - behavioral：天猫超市/抖音买过同品类，或母婴类目
>
> 这三类哪些要重点深挖、哪些跳过？"

老板圈完进 Step 2。

### Step 2: 拿权威/方法论 KB

```python
search_kb(
    query="<老板说的受众词> + <品类>",  # 如 "宝妈 调味品" / "年轻白领 健康饮食"
    kb_roles=["authoritative", "methodology"],
    top_k=8,
)
```

**重点关注**：
- authoritative 区有没有该品类的"权威人群定义"（如卡兹罗的"调味品消费人群分级"）
- methodology 区有没有"圈人方法"（如 5A 资产分级 / RFM / GMV 漏斗反推）

返回的命中**摘 2-3 条**给老板，让他确认哪几条靠谱：

> "找到 4 条相关：
> A 「调味品消费 5A 分级」（authoritative）
> B 「母婴人群 RFM 模型」（methodology）
> C 「健康饮食人群心智图」（authoritative）
> D 「场景代入式圈人 SOP」（methodology）
>
> 我打算用 A 做品类基础，B 做行为分层。要不要 C/D？"

老板拍 → 进 Step 3。

### Step 3: 拿模板素材（标签维度/平台投放语言）

```python
query_template_chunks(
    query="<受众词> 投放 OR 标签 OR 圈人",
    top_k=5,
)
```

**为啥要这步**：authoritative+methodology 给的是"理论框架"，模板给的是"平台落地语言"——比如抖店达人广场的标签词、巨量引擎的兴趣类目名。

返回 chunks 看是否有"<品类> 投放标签清单"模板。如有，**直接列给老板**：

> "拿到 1 条模板「调味品圈人 12 标签」：
> demographic: 女_25_40 / 已婚 / 一线
> behavioral: 调味品_30 天 / 母婴_最近购
> interest: 烘焙美食 / 育儿 / 家居家电
>
> 这 12 条用哪些？"

老板圈完进 Step 4。

### Step 4: 出圈人策略文档（可执行）

把 Step 1-3 拼成一份**可直接复制进抖店/巨量后台**的策略文：

```
## SKU-X 人群包策略（<受众主题>）

### 1. 受众画像（一句话）
<示例：25-40 岁注重健康的一线宝妈，月消调味品 ≥1 次，关注配料表>

### 2. 核心标签（按平台分）
**巨量引擎（抖音）**：
  - demographic：[女、25-40 岁、已婚、一线]
  - interest：[育儿、烘焙美食]
  - behavioral：[调味品_30 天有购、母婴_近 90 天]

**抖店达人广场**：
  - 达人粉丝画像：宝妈 ≥30%
  - 达人内容：测评/科普类

### 3. 优先级
P0（必投）：标签 X+Y 交叉
P1（拓展）：标签 Z 单维
P2（备用）：相似人群拓展（lookalike）

### 4. 排除
- 排除 A 类（如老年人/学生）
- 排除已转化（30 天内）

### 5. 投放预算建议
P0:P1:P2 = 6:3:1（参考方法论 KB B）
```

**关键约束**：
- 标签词必须是**抖店/巨量后台真实存在**的（如 KB 模板里的，不是 LLM 编的）
- 排除条件必写
- 优先级 ≤3 档（不要"P0/P1/P2/P3/P4" 一股脑）
- 预算建议**带依据**（指方法论 KB B 哪条）

把结果给老板审：

> "策略出来了。核心受众是 X，3 档标签 P0/P1/P2，排除 Y。看一下哪部分要改。"

## 错误处理

| 错误 | hint | 怎么办 |
|---|---|---|
| `search_kb` authoritative 返空 | KB 没该品类权威定义 | 退化用通用方法论（5A / RFM），但**告诉老板** |
| `query_template_chunks` 返空 | KB 没投放标签模板 | 退化只出"画像+逻辑"，标签留空老板自己填 |
| 老板说"标签太宽了" | P0 选了交集太弱的维度 | 回 Step 3 选更窄的标签交集 |
| 老板说"模板里那 12 标签不对" | template KB 内容陈旧 | 提示老板补一份新模板 |

## 反例（**禁止**）

- 不调 search_kb authoritative 凭通用心智胡说人群 — 没数据支撑
- 标签里编平台没有的词（如"佛系青年"、"精致猪猪女孩"）— 老板没法在巨量里勾
- 优先级写 5 档以上 — 失焦
- 不写排除条件 — 投放会浪费预算
- 一气呵成 4 步不停 — 必须每步等老板反馈
- 用 AI 化套话（"赋能精准触达 / 心智渗透 / 用户旅程闭环"）— feedback memory 强制说人话

## 已知约束

- 本 skill **不**调任何写入 tool（纯查 KB + 出文档）
- search_kb kb_roles 用 ['authoritative', 'methodology'] 双路找
- 平台标签会变；模板素材老旧时退化仍可，但要明说"标签需老板侧验证"

## 跟 CLAUDE.md / 其他 skill 的关系

- 跟 **product-analysis** 互补：那个看产品健康度（卖给现有受众卖得咋样），本 skill 决定"卖给谁"
- 跟 **selling-point-finder** 平行：那个找内容素材，本 skill 找投放对象；script-writer 把两者拼脚本
- KB authoritative 区 = 已有 5A 资产分级文档（W3b 抓数 fetch_yuntu_5a 入的 KB）；methodology 区 = 卡兹罗/老板线下沉淀的方法论
