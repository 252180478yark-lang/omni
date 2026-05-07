---
name: sku-pipeline
description: SKU 出片全链路。老板说"SKU-X 全链路"、"给 X 出片"、"跑通 X"、"X 完整流程"等，触发 5 步标准编排：query_costs → compute_margin → script-writer 子流程出 brief → generate_image 3 张分镜 → generate_video 3 段，每步停下等老板反馈。
---

# sku-pipeline：SKU 出片全链路 SOP

> omni-vibe 项目内 skill。**编排型 skill**——把 cost-luru / product-analysis /
> script-writer 等单点 skill 串成完整的"从一个 SKU 到 3 段视频"链路。
>
> **每步停下等老板反馈**，绝不一气呵成（最后 step 5 generate_video 烧钱 ≈ 30 元）。
> 跟 CLAUDE.md "sku 出片标准链路" 章节是同一套——本 skill 是详细 SOP 展开。

## 触发场景

| 老板话术 | 含义 |
|---|---|
| "SKU-X 全链路" / "X 全链路" | 跑完整 5 步 |
| "给 X 出片" / "出 X 片" | 同上 |
| "跑通 X" / "X 跑通" | 同上 |
| "X 完整流程" / "X 一条龙" | 同上 |
| "X 走一遍" | 老板可能要重跑某步，先确认是全链路还是局部 |

老板话术含**具体步骤词**（如"录 X 成本"/"找 X 卖点"/"写 X 脚本"/"分析 X"）→
**不触发本 skill**，触发对应单点 skill。

## 标准 5 步 SOP

### Step 1: 锁定 SKU + 算成本

```python
get_sku(sku_id="SKU-X")
query_costs(sku_id="SKU-X", view="public")
```

**前置检查**：
- `platform_status` 异常（off_sale / out_of_stock / banned）→ 警告老板
  "已下架/已售罄/已封禁，确实要出片？"
- `cost_items` 有"拆分式"+"出厂价合计"双口径 → 提示用 cost-luru skill
  路径 B 清理后再来
- 没 cost_items 行（只 shared 兜底）→ 用默认成本兜底（运费 5 + 包材 3），
  告诉老板"成本只是兜底，建议先 cost-luru 录 SKU 专属成本"

把 cost_items 列表 + 套装组合（specifications）+ 真实卖价（price_min）
**一次给老板看**：

> "002 现状：
> - 套装：500ml*2 + 200ml*2
> - 卖价：¥76（抖店真实）
> - 成本：出厂价 ¥54 + 默认运费 ¥5 + 默认包材 ¥3 = ¥62
> - 状态：on_sale，growth_class=excellent，重点池
> 进 step 2 算利润？"

### Step 2: compute_margin 算利润 + 老板审

```python
compute_margin(sku_id="SKU-X", channel="douyin",
               sale_price=SKU.price_min)  # 用 mvp_sku.price_min，不让老板手报
```

`channel_fee_rate=None` 让 W4-B 切片 9 fallback 自动查 channel_fees（抖音 2%）。

**输出 breakdown 给老板**：

> "GMV ¥76 - cost ¥62 - 抖音 2%扣点 ¥1.52 = **净利 ¥12.48 (16.4%)**。
> 利润率 OK 进 step 3 出 brief；不 OK 我们重看成本结构。"

老板"OK"进 step 3；老板"重来"→ 回 cost-luru 调成本。

### Step 3: gather_brief_context + generate_brief 出脚本

**触发 script-writer skill 模式**（本 skill Step 3 跟 script-writer skill 全 SOP 重合）。

```python
gather_brief_context(sku_id="SKU-X", channel="douyin")
generate_brief(
    sku_id="SKU-X",
    channel="douyin",
    kb_context=<3a 返的>,        # 必传，防 W3a 漏看裸跑
    extra_context="""
    脚本类型：30s 视频（默认）
    必须用的卖点：<老板从 owner_selling_points 圈的 2-3 条>
    脚本框架：<query_template_chunks 拿到的模板>
    """,
)
```

返 brief.result + sources 给老板审：

> "脚本草稿出来了。三段：开头痛点 X / 中段试吃 Y / 结尾 CTA Z。
> 引用 KB sources：authoritative kb1, template chunk_X, owner_notes。
> 进 step 4 出分镜图？"

老板"重来" → 改 extra_context 重调 generate_brief；
老板"OK" → 进 step 4。

### Step 4: generate_image 出 3 张分镜图

```python
generate_image(
    prompts=[
        "<分镜 1 prompt>",     # 从 brief 三段拆出
        "<分镜 2 prompt>",
        "<分镜 3 prompt>",
    ],
    face_refs=[...],            # 老板侧上传的人脸参考
    product_refs=[...],         # 产品参考图（从 SKU 详情页拉或老板上传）
)
```

返 3 张分镜图的 url 给老板**逐张审**：

> "3 张分镜图：
> [图1 url] - 开头痛点（对比框）
> [图2 url] - 中段试吃（特写）
> [图3 url] - 结尾 CTA（产品+价格牌）
> 看一下，第 N 张要重做就说『第 N 张重来』。"

**局部重跑**：老板说"第 2 张重做" → 只 generate_image(prompts=[新 prompt 2])，
不重跑全 3 张。

### Step 5: generate_video 出 3 段视频（**烧钱 step**）

**最贵的步骤**——确认老板真要进。

```python
generate_video(
    segments=[
        {"prompt": "...", "first_frame": <分镜 1 url>, "last_frame": <分镜 2 url>},
        {"prompt": "...", "first_frame": <分镜 2 url>, "last_frame": <分镜 3 url>},
        {"prompt": "...", "first_frame": <分镜 3 url>, "last_frame": None},
    ],
    face_refs=[...],
    product_refs=[...],
)
```

3 段并发跑（asyncio.gather），typically 30-60s 每段；并发后总时间 ≈ 单段。
**告诉老板预期等待时间 + 大致花费**（每段 ~10 元，3 段 ~30 元）。

返视频 url 给老板下载。

### Step 6（可选）: save_decision 入档

老板满意完工 → 把这次决策入 mcp.decisions 表：

```python
save_decision(
    title="SKU-X 出片完成",
    summary="<3 段视频 url + brief 关键卖点 + 利润率>",
    sku_id="SKU-X",
    tags=["video", "douyin", "<其他>"],
)
```

不满意完工就别 save_decision；也可以让老板拍要不要存。

## 老板响应词（中途打断）

| 老板说 | 怎么办 |
|---|---|
| "OK / 继续 / 进下一步" | 按 next_step_hint 进下一步 |
| "重来 / 改" | 用同 tool 重调，按老板新要求改 extra_context / prompts |
| "第 N 张重做" / "第 N 段重做" | step 4/5 局部重跑（不重跑全 3 张/3 段）|
| "跳过 video" | step 5 跳过，直接 step 6 入档 |
| "停 / 算了 / 不做了" | 当前步骤 abort，已生成的素材保留（图/视频 url 还在） |
| "卖点错了" | 回 step 3 重圈卖点，brief 重出 |
| "成本不对" | 回 step 1 用 cost-luru 重录 |

## 错误处理

| 错误 | hint | 怎么办 |
|---|---|---|
| `query_costs` 返空 | cost_items 没该 SKU | 提示用 cost-luru skill 录成本（路径 A 单笔或 B 桥接） |
| `compute_margin` `wrong_passphrase` | 老板要看 real 但口令错 | 提示口令在 .env COST_REAL_VIEW_PASSPHRASE |
| `generate_brief` 无 kb_context | 漏传防裸跑 | step 3 必先 gather_brief_context |
| `generate_image` 失败 | OpenAI / Seedance 限流或参数错 | 看 trace 改 prompt 重调；不要一直重试 |
| `generate_video` 超时 | 单段 >5min | 看 trace 哪段超时，单独重跑那段 |
| `platform_status` 异常 | SKU 不在卖 | step 1 警告老板，老板说要继续才走 |

## 反例（**禁止**）

- **一气呵成跑完 5 步不停** —— 必须每步等老板反馈（特别是 video step 烧钱）
- **不前置检查 platform_status** —— 给已下架 SKU 出片浪费钱
- **generate_brief 不传 kb_context** —— W3a feedback memory 强约束防裸跑
- **generate_video 默认重跑全 3 段** —— 局部重跑只跑老板指的那段
- **不 save_decision 也不告诉老板**—— 至少问一句"要不要入档"
- **用 AI 化套话** —— 写脚本/分镜 prompt 时禁"赋能/打通/闭环/抢占心智"

## 已知约束

- 全链路依赖单点 skill：cost-luru / script-writer / product-analysis 等
  升级后自动受益（不用重写本 skill）
- generate_brief / generate_image / generate_video 都不走 Human Gate（W2 锁定 LLM 类 F）
- save_decision 不走 Gate（W4-B 切片 5 锁定 F 类）
- 整套跑下来 step 5 烧钱 ~30 元，重跑全部更贵——**让老板审每步省钱**

## 跟 CLAUDE.md / 其他 skill 的关系

- **是 CLAUDE.md "sku 出片标准链路"章节的详细 SOP 展开**（CLAUDE.md 行 77-90 是简版）
- step 1 调 cost-luru skill 输出（如果缺成本）
- step 3 等价于 script-writer skill 全 SOP（kb_context 注入 + 卖点圈选 + 模板）
- step 5 后续可触发 product-analysis 复盘（数据出来后看效果）

## 真实参考

W4-B 切片 12 已用 cost-luru 路径 B 给 SKU-367991-0002 重录出厂价（cost ¥62 / 利润率 16.4%），
Step 1+2 已通；本 skill 等老板拍 step 3+ 真跑通后回填经验。
