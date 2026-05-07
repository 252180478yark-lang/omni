---
name: script-writer
description: 给一个 SKU 写脚本（视频脚本 / 图文脚本 / 直播话术）。老板说"给 SKU-X 写个脚本"、"X 写个直播话术"、"出 X 的图文文案"等，触发标准 5 步走 SOP，串 SKU + 模板 + KB + generate_brief 出脚本。
---

# script-writer：SKU 脚本生成 SOP

> omni-vibe 项目内 skill。老板说"给 X 写脚本/X 直播话术/X 文案"时，按 5 步走，**每步停下等反馈**。

## 触发场景（话术 → 渠道/形态）

| 老板话术 | channel 解析 | 形态推断 |
|---|---|---|
| "给 SKU-X 写个脚本" | 默认 douyin | 视频 30s（默认） |
| "X 写个直播话术" | douyin（直播） | 直播口播 |
| "X 出图文文案" | xiaohongshu / douyin 图文 | 图文 |
| "给 X 写个 60s 脚本" | douyin | 视频 60s |
| "X 京东详情页文案" | jd | 详情页长文 |

不确定时**先反问**："你要的是视频脚本还是直播话术？多长时间/多少字？"

## 标准 5 步 SOP

### Step 1: 锁定 SKU + 拿基础信息（用 mvp_sku 真实字段）

老板话术里 SKU ID 不明确就先 list_skus(query=...) 找；明确就直接：

```python
get_sku(sku_id="SKU-X")
```

抓的字段（W4-B 切片 12 后全抓全）：
- `name`（抖店标题，SEO 堆词长串——脚本里**别全用**，挑关键词即可）
- `specifications`（**真实规格**：500ml*2 + 200ml*2 等，脚本提到规格用这个）
- `price_min/price_max`（**真实卖价**，脚本 CTA 价格用这个）
- `platform_status`（如果 `off_sale` / `out_of_stock` 警告老板）
- `owner_selling_points`（老板手填的卖点 → Step 2 直接用）
- `owner_notes`（老板手填的产品参数）

**status 检查**：

```
if platform_status in ('off_sale', 'out_of_stock', 'paused'):
    告诉老板"这款已下架/已售罄/暂停，写脚本前确认是要复活吗？"
```

`unknown` 状态也提醒老板（爬虫没匹配到任何状态文字，可能 UI 又改了）。

### Step 2: 找卖点（owner 字段优先 + selling-point-finder 子流程）

**优先看 mvp_sku.owner_selling_points**（老板手填的卖点 JSON 数组）：

```
if SKU.owner_selling_points and len > 0:
    直接列出来，让老板圈 2-3 条进脚本
else:
    跑 selling-point-finder 子流程：
        search_kb(query="<品类> 卖点", kb_roles=["template"], top_k=5)
        query_template_chunks(query="<品类> 脚本 OR 文案", top_k=5)
```

如果老板**之前用过 selling-point-finder skill** 出过这个 SKU 的卖点，**直接复用**（让老板说"用上次那几条卖点"），不再重跑。

**输出 3 类卖点**（功能/情绪/场景）给老板，让他**圈 2-3 条** 进脚本。

> "002 owner_selling_points 已有 9 条：180天发酵酿造 / 日式工艺 / 高盐稀态发酵 /
> 有机 / 零添加 / 玻璃瓶 / 不含白砂糖 / 33年源头工厂 / 老北京和田宽酱油。
> 你圈哪 2-3 条进脚本？"

老板圈完进 Step 3。

### Step 3: 拿模板/受众 KB（脚本框架）

```python
query_template_chunks(query="<品类> <脚本类型>", top_k=8)
```

`<脚本类型>` 用形态词（"视频"/"直播"/"图文"/"详情页"），不要塞品类全名。

**老板话术里有受众词**（如"宝妈"/"年轻人"/"商务人士"）也调：

```python
search_kb(query="<受众> 沟通", kb_roles=["template", "authoritative"], top_k=5)
```

返回的 chunks 里挑 1-2 个最像本次脚本框架的，**告诉老板你打算用哪个**：

> "拿到 5 条脚本模板：A 痛点-解决-行动三段式（30s 视频）/ B 对比-试吃-推荐（直播话术）/ C 场景代入式（图文）。这次是 30s 视频脚本，我用 A，可以吗？"

老板 OK 进 Step 4。

### Step 4: 调 generate_brief 出脚本

把 Step 1-3 拿到的全部素材**合成 kb_context** 传给 generate_brief：

```python
generate_brief(
    sku_id="SKU-X",
    channel="douyin",  # 或 tmall / jd / xiaohongshu
    kb_context=<合并 Step 2 卖点 + Step 3 模板素材>,
    extra_context="""
    脚本类型：30s 视频
    受众：<老板说的>
    必须用的卖点：A、C、F（老板圈的）
    脚本框架：模板 A 痛点-解决-行动三段式
    """,
)
```

**关键约束**：
- 必须传 `kb_context` 不要让 LLM 裸跑（feedback memory 强制：W3a 漏看导致浅层裸跑被叫停）
- `extra_context` 把"形态/受众/卖点圈选/框架"都明示进去
- 默认走 prompts/generate_brief.{system,user}.md（说人话+反幻觉+去 AI 化已注入）

返回 result.brief + result.sources 给老板审：

> "脚本草稿出来了。三段：开头痛点 X / 中段试吃 Y / 结尾 CTA Z。引用了 3 条素材（kb1/kb2/template_chunk_X）。看一下，要改的地方说一声。"

### Step 5: 老板反馈 → 回炉或定稿

| 老板说 | 怎么做 |
|---|---|
| "OK / 通过" | 完，提示要不要去 generate_image 出分镜 |
| "重来" | 同 generate_brief 调，把老板新要求加 extra_context |
| "第 N 段重写" | 用 extra_context 指明"第 N 段改成 X"重调（generate_brief 没法局部重跑，整篇重出但其他段保持） |
| "卖点错了" | 回 Step 2 重圈卖点，再调 generate_brief |
| "框架不合适" | 回 Step 3 换模板 chunk，再调 generate_brief |

## 错误处理

| 错误 | hint | 怎么办 |
|---|---|---|
| `query_template_chunks` 返空 | template KB 没该品类脚本素材 | 提示老板"先补一份模板"或退化用通用三段式 |
| `search_kb` 受众无命中 | KB 没该受众沟通材料 | 跳过受众部分，只用品类模板 |
| `generate_brief` 输出空/超短 | LLM 上下文不足 | 检查 kb_context 是不是空 / SKU.detail 是不是空 |
| 老板说"太 AI 化了" | LLM 没读 prompt 反 AI 化指令 | 在 extra_context 重申"避免赋能/打通/闭环；说人话"，重调一次 |

## 反例（**禁止**）

- 不调 query_template_chunks 直接调 generate_brief — KB 上下文空，LLM 裸跑出空泛脚本（W3a 已踩过坑）
- 不让老板圈卖点直接出脚本 — 选错重点，浪费一次调用
- 一气呵成跑 5 步不停 — 必须每步等老板反馈
- 用 AI 化套话（"赋能/打通/闭环/抢占心智"）— feedback memory 强制说人话
- 出脚本时硬编 SKU 不存在的字段（如 SKU.detail 没说"5 度"，不要瞎写）

## 已知约束

- generate_brief 不走 Human Gate（W2 锁定 LLM tool 全 F 类）
- generate_brief 必返 trace 字段；老板要看 final_prompt 才能调 prompt 重跑
- prompts/generate_brief.{system,user}.md 改了 KE 容器无需 restart（mtime 自检）
- 本 skill 出来的是脚本**文本**；分镜图/视频是后续 generate_image / generate_video 的事

## 跟 CLAUDE.md / 其他 skill 的关系

- 是 CLAUDE.md "sku 出片标准链路"的 step 3（**brief 出片三步走**）的精细化版本
- 前置：**selling-point-finder** skill（找卖点）；如果老板没用过，本 skill Step 2 内置一遍
- 后续：**generate_image** / **generate_video** tool（不是 skill，直接调）
- 跟 **product-analysis** 不冲突：那个看健康度，本 skill 看脚本内容
