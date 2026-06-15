---
name: sku-pipeline
description: SKU 出片全链路（新链·挂血缘）。老板说"SKU-X 全链路"、"给 X 出片"、"跑通 X"、"X 完整流程"等，触发新链编排：成本利润（query_costs+compute_margin）→ step2 卖点矩阵 generate_selling_points_matrix → step3 人群匹配 generate_audience_match（拆 N 人群卡片，老板勾选 pipeline_adopt）→ 分流【内容 brief 3.5 generate_audience_portrait → 3.6 generate_director_brief ‖ 投放圈包 step4 generate_audience_pack/generate_keyword_pack】→ step5 generate_creative_pack（video_*）→ step6.5 generate_character_sheets → step6 generate_storyboard_images → step7 generate_video_segments，全挂 pipeline 血缘 draft→adopted，每步停等老板反馈。⚠️烧 token 的**完整出片编排**，仅当老板**明确要成片/全链路**时触发；只要脚本/文案/直播话术走 script-writer；只要画像/编导 brief 单步走对应 tool；只圈包走 crowd-sop/generate_audience_pack——别把单步需求误当全链路白烧出图出视频。
---

# sku-pipeline：SKU 出片全链路 SOP（新链 · 挂血缘）

> omni-vibe 项目内 skill。**编排型 skill**——把"一个 SKU → 卖点矩阵 → 人群 →
> （画像+编导 brief / 圈包）→ 视频脚本 → 分镜图 → 视频段"串成完整链路。
>
> **每条产物全挂 `pipeline` 血缘**（denorm sku_id + 多版本 + draft→adopted 两态），
> 投后 `record_ad_metrics` 回传 ROI/GMV，`pipeline_get_asset_lineage` 一句 SQL
> 反查"哪个人群 × 哪版卖点 × 哪版脚本真带货"。
>
> **每步停下等老板反馈**，绝不一气呵成（step 6/6.5 出图、step 7 出视频都烧钱）。
> 跟 CLAUDE.md "sku-pipeline" 各节是同一套——本 skill 是编排 SOP 总览。

## 触发场景

| 老板话术 | 含义 |
|---|---|
| "SKU-X 全链路" / "X 全链路" | 跑完整新链 |
| "给 X 出片" / "出 X 片" | 同上 |
| "跑通 X" / "X 跑通" / "X 完整流程" | 同上 |
| "X 走一遍" | 先确认全链路还是局部重跑 |

老板话术含**具体步骤词** → **不触发本 skill**，直接走对应单步：
- "录 X 成本 / 算出厂价" → cost-luru
- "找 X 卖点" → selling-point-finder（口头要）或 `generate_selling_points_matrix`（要进链路）
- "写 X 脚本 / 直播话术" → script-writer
- "给这个人群出画像 / 出编导 brief" → 直接 `generate_audience_portrait` / `generate_director_brief`
- "圈一个 X 的包" → crowd-sop / `generate_audience_pack`
- "第 N 段重做 / 分镜图重出" → 对应 step 局部重跑（见老板响应词表）

## 链路全图（先给老板看这张，确认要走哪条支线）

```
step 1   query_costs + compute_margin        成本利润审完才开跑
step 2   generate_selling_points_matrix   → pipeline.matrix_runs (draft)
step 3   generate_audience_match          → audience_runs + 拆 N 行 audience_records
            ↓ 老板勾选人群（pipeline_adopt set_selected=True）
         ┌──── 分流（同一个 audience_record，两支线互不阻塞）────┐
内容 brief 支线                                    投放圈包支线
step 3.5 generate_audience_portrait               step 4  generate_audience_pack
step 3.6 generate_director_brief                          generate_keyword_pack
   ↓ 出口①真人编导拿去拍                                  ↓ 云图后台勾选 → 推千川
   ↓ 出口②第 5 部分整段提示词直喂 Seedance 2.0
         └──────────────（AI 正式出片走下面主干）──────────────┘
step 5   generate_creative_pack(kind='video_*')  → pipeline.scripts（v11+ 含分镜+角色表）
step 6.5 generate_character_sheets               → 角色定妆白底像（锁脸，先于 6 跑）
step 6   generate_storyboard_images              → 分镜图（自动用 6.5 的像当 face_refs）
step 7   generate_video_segments                 → 视频段（分镜图当 first_frame）★最烧钱
（投后）  record_ad_metrics 回传 → pipeline_get_asset_lineage 反查全链路
```

**衔接铁律**：3.6 的 director_brief（kind='director_brief'）**不能直接进 step 6/7**
（step 7 有 `kind.startswith('video_')` 硬闸）。它是"真人拍 + 整段提示词手动出片"的
通路；要挂血缘的正式 AI 出片必须走 step 5 出 video_* 脚本。

**新形态（2026-06-12 起 step 5 默认）**：video_* 脚本出「### 提示词块 X（A-Bs）」
一大段连续叙事（≤15s/块，`target_model` 档案定写法）→ **跳过 step 6**（新形态脚本
进 step 6 返 `whole_prompt_script_no_storyboard`，这不是 bug）→ step 7 块全文 r2v
直出（自动挂全部 6.5 定妆照 + product_refs 白底图多参考）。即新形态主干 =
**5 → 6.5 → 7**；旧形态脚本（节点 N 分镜）仍走 5 → 6.5 → 6 → 7 原路。

## 标准 SOP

### Step 1: 锁定 SKU + 成本利润（同旧链，没变）

```python
get_sku(sku_id="SKU-X")
query_costs(sku_id="SKU-X", view="public")
compute_margin(sku_id="SKU-X", channel="douyin", sale_price=<mvp_sku.price_min>)
```

**前置检查**：
- `platform_status` 异常（off_sale / out_of_stock / banned）→ 警告老板"确实要出片？"
- 双口径成本（拆分式 + 出厂价合计并存）→ 提示先用 cost-luru 路径 B 清理
- 无 cost_items → 默认兜底（运费 5 + 包材 3），明说"只是兜底，建议先录"
- `channel_fee_rate` 不传，让 fallback 自动查 channel_fees（抖音 2%）

> "002 现状：套装 500ml*2+200ml*2 / 卖价 ¥76 / 成本 ¥62 / 净利 ¥12.48 (16.4%)。
> 利润 OK 进 step 2 出卖点矩阵？"

### Step 2: 卖点矩阵

```python
generate_selling_points_matrix(
    sku_id="SKU-X",
    user_initial_points="<老板口头给的卖点，可空>",
    user_reviews="<真实评论摘录，可空>",
    extra_context="<老板临时要求，可空>",
)
```

跑完自动落 `pipeline.matrix_runs`（draft）。把 5 部分矩阵 + `matrix_run_id` 给老板审：

> "卖点矩阵 v1 出来了（matrix_run_id=xxx）。三层卖点地图 + USP 排他检验 + 五心智。
> 满意我把这版采纳（adopted），然后进 step 3 跑人群？"

老板"采纳" → `pipeline_adopt(table="matrix_runs", run_id=<matrix_run_id>)`；
老板"重来" → 同 tool 重跑（新版本落库，version 自增不覆盖）。

### Step 3: 人群匹配（拆 N 人群卡片）

```python
generate_audience_match(
    sku_id="SKU-X",
    matrix_md="<step 2 的矩阵 markdown>",
    matrix_run_id="<step 2 返的 id>",   # 必传，串血缘
)
```

整段报告落 `audience_runs`，同时 regex 拆每个人群入 `audience_records`（≥15 个）。
**给老板报人群清单（编号+名字+一句话）让老板挑**：

> "拆出 17 个人群。1.1 都市轻养生族 / 1.2 赛博食客 / …
> 选哪个（几个）往下走？选完告诉我走哪条支线：出内容 brief（3.5→3.6）还是圈投放包（4）？"

老板"选第 3 个" →
`pipeline_adopt(table="audience_records", run_id=<record_id>, set_selected=True)`

### ★ 分流点：step 3 之后两条支线（可只走一条，也可同人群双开）

| 老板意图 | 走 |
|---|---|
| "出画像 / 编导 brief / 拍内容" | 内容支线 3.5 → 3.6 |
| "圈包 / 投放 / 推千川" | 投放支线 step 4 |
| "直接出片"（不要编导 brief） | 跳到 step 5（用选中的 audience_record_id）|

### Step 3.5: 人群生活状态画像（内容支线）

```python
generate_audience_portrait(
    audience_record_id="<step 3 选中的 record id>",
    extra_context="<可空，如'重点写她周末的状态'>",
    # kb_recall_override="<老板手贴 chunks 时才用>",
)
```

四路定向 KB 召回 → 5 部分画像（人群速写/生活状态/卖点重构/情绪触点/信息缺口），
每句标 `[KB:文档名]` / 🧠推演 / ⚠️推测。落 `pipeline.audience_portraits`（draft）。

**必看 `validation_warnings`**：配额超标（⚠️>5 处 / KB 占比 <50%）= KB 料薄 →
提示老板"补 X 圈层 KB 重跑"，**不硬编**。老板满意 →
`pipeline_adopt(table="audience_portraits", run_id=<portrait_id>)`，进 3.6。

### Step 3.6: 编导备忘录

```python
generate_director_brief(
    portrait_id="<3.5 返的 portrait_id>",
    idea_seed="<老板'想拍 X 那种事'时传，可空=LLM 从场景库自选>",
    include_ai_mapping=True,      # 老板"不要 AI 那段"→ False 省 token
    ai_prompt_count=None,         # None=按 target_model 档案自动定块数；老板指定块数才传
    target_model="seedance",      # 默认 Seedance 2.0 中文整段；可选 veo/jimeng/generic
    num_variants=1,               # 老板"多来几版创意"→ 2-3
)
```

V7.2 风格备忘录（一件事/起伏≠反转/卖点种情绪高点/算法信号三向量/12 项自检），
落 `pipeline.scripts`（kind='director_brief'）。**给老板说清两个出口**：

> "brief 出来了。两个用法：① 直接发给编导照拍；② 第 5 部分那一大段中文提示词
> + 产品白底图，复制进 Seedance 2.0 直接出片（无血缘临时通路）。
> 要挂血缘的正式 AI 出片，说一声我走 step 5 出视频脚本。"

### Step 4: 圈包 + 关键词扩展（投放支线）

```python
generate_audience_pack(audience_record_id="<选中的 record>")
# 按需追加：
generate_keyword_pack(seed_keywords="<种子词>", target_count=500,
                      audience_record_id=..., audience_pack_id=...)
```

圈包 SOP 落 `pipeline.audience_packs`；关键词包落 `keyword_packs`（导入云图数据
工厂关键词夹，**不是**直接进千川计划）。投放支线到此交老板去后台执行；
后续投前诊断走 `diagnose_audience_pack`（audience-pack-diagnosis skill）。

### Step 5: 视频脚本（正式出片的唯一入口）

```python
generate_creative_pack(
    kind="video_planting",        # 或 video_soft_ad / video_harvest，按漏斗位置选
    audience_record_id="<选中的 record>",   # 弹性挂：pack_id 更全 / 只有 sku_id 也行
    extra_context="<可空>",
)
```

落 `pipeline.scripts`（v11+ 格式：scenes 分镜 + character_sheets 角色表——
**step 6/6.5/7 全靠这两个字段**）。老板审脚本 + 分镜表，满意 →
`pipeline_adopt(table="scripts", run_id=<script_id>)`，进 6.5。

### Step 6.5: 角色定妆白底像（先于 step 6 跑——锁脸）

```python
generate_character_sheets(
    script_id="<step 5 的 script_id>",
    role_ids=None,        # 重跑某个角色才传，如 ["mother"]
    aspect_ratio="1:1",
)
```

每个角色出白底正面像，落 `pipeline.assets`（asset_type='character_sheet'）。
报 `no_character_sheets` = v10 老格式脚本 → 先重跑 step 5 出 v11+。
逐张给老板审脸，"第 N 个角色重来" → 只传那个 role_id 重跑。

### Step 6: 分镜图

```python
generate_storyboard_images(
    script_id="<同一个 script_id>",
    scene_nums=None,              # 局部重跑才传，如 [2, 5]
    aspect_ratio="9:16",
    # product_refs=[...]          # 产品参考图；scene.product_appearance=False 的段自动不传
    # deidentify_faces=True       # step 7 撞 content_sensitive 时的预防项
)
```

自动按 `scene.characters_in_scene` 找同 script 的 character_sheet 当 face_refs 锁脸
（老板另传的 face_refs 合并不重复）。落 `pipeline.assets`。逐张给老板审：

> "N 张分镜图齐了。第几张要重做说'第 N 张重来'，都 OK 进 step 7 出视频（最烧钱一步）。"

### Step 7: 视频段（★最烧钱 step，进之前再确认一次）

```python
generate_video_segments(
    script_id="<同一个 script_id>",
    scene_nums=None,              # 局部重跑才传
    duration_s=8,                 # seedance 接受 4-15
    aspect_ratio="9:16",
    # dry_run=True                # 先零费用看拼出的 prompt，再真跑
    # skip_first_frame_scene_nums=[N]  # content_sensitive 报错的真人脸段降级 t2v
    # force_t2v=True              # 全段纯文生视频（不依赖分镜图）
    # character_anchor="40岁主妇，齐肩黑发，米色围裙…"  # 跨镜一致性锚
)
```

前置：step 6 的 image asset 必须齐（缺会返 `missing_storyboard_images` + 缺哪几段）。
并发跑，**告诉老板预期等待 + 大致花费**。视频落 `pipeline.assets`
（asset_type='video'），返 url 给老板下载交剪辑。

### Step 8（可选）: 入档 + 投后回传

```python
save_decision(title="SKU-X 出片完成", summary="<视频 url + 人群 + 卖点 + 利润率>",
              sku_id="SKU-X", tags=["video", "douyin"])
```

投放跑了数据后：`record_ad_metrics(...)` 写回素材血缘 →
`pipeline_list_asset_performance()` 看"哪套内容真带货"。至少问一句"要不要入档"。

## 新旧两条链（兜底约定）

| 链 | tool | 血缘 | 何时用 |
|---|---|---|---|
| **新链（默认）** | step 5→6.5→6→7 | 全挂 pipeline.assets | 正式出片，要投后回溯 |
| 旧链（兜底） | generate_image / generate_video | 无 | 老板临时要张图、一次性试拍、3.6 整段提示词手动出片 |

## 老板响应词（中途打断）

| 老板说 | 怎么办 |
|---|---|
| "OK / 继续 / 进下一步" | 按 next_step_hint 进下一步 |
| "采纳 / 就这版" | `pipeline_adopt` 对应表 + run_id |
| "选第 N 个（人群）" | `pipeline_adopt(table="audience_records", run_id=..., set_selected=True)` |
| "重来 / 改" | 同 tool 重跑（新版本落库不覆盖），按新要求改 extra_context |
| "第 N 张 / 第 N 段重做" | step 6/7 传 `scene_nums=[N]`；step 6.5 传 `role_ids=[...]` |
| "出画像 / 深挖这个人群" | 跳 3.5 |
| "给编导下个 brief" / "想拍 X 那种" | 跳 3.6（缺画像先 3.5；想拍的事进 idea_seed）|
| "不要 AI 那段" | 3.6 传 `include_ai_mapping=False` |
| "再来一版创意" | 3.6 重跑或 `num_variants=2-3` |
| "圈包 / 推千川" | 走 step 4 投放支线 |
| "跳过 X / 不要这步" | 跳过，按链路下一步走（step 6.5 可跳但 step 6 没锁脸）|
| "停 / 算了" | abort，已落库产物保留（draft 状态躺血缘里，随时续跑）|
| "成本不对" | 回 step 1 用 cost-luru 重录 |

## 错误处理

| 错误 | 含义 | 怎么办 |
|---|---|---|
| `query_costs` 返空 | 没录成本 | cost-luru 录入（链路可先用兜底继续）|
| step 3.5 `audience_record 未找到` | 链路断 | 先跑 step 3 或 `pipeline_list_audience_records` 找现有 record |
| step 3.5 `validation_warnings` 配额超标 | KB 料薄 | 提示补圈层 KB 重跑，不硬编 |
| step 3.6 `portrait 未找到` | 缺 3.5 | 先跑 3.5 |
| step 6.5 `no_character_sheets` | v10 老格式脚本 | 重跑 step 5 出 v11+ |
| step 6 `no_scenes` | 脚本无分镜结构 | 重跑 step 5；director_brief 不能当 step 6 输入 |
| step 7 `non_video_kind` | 喂错脚本（如 director_brief）| 只有 kind=video_* 能进 step 7 |
| step 7 `missing_storyboard_images` | step 6 没跑全 | 先补跑缺的 scene_nums |
| step 7 `content_sensitive` | Seedance 真人脸审查 | `skip_first_frame_scene_nums=[N]` 降级 t2v 重跑那段；或 step 6 加 `deidentify_faces=True` 重出首帧 |

## 反例（**禁止**）

- **一气呵成跑完全链不停** —— 每步停等老板反馈（step 7 最烧钱，进之前必再确认）
- **把 director_brief 喂 step 6/7** —— kind 闸挡死；正式 AI 出片必走 step 5 出 video_* 脚本
- **正式出片走旧链 generate_image/generate_video** —— 无血缘不可投后回溯；旧链只做临时兜底
- **不落血缘瞎跑**（step 3 不传 matrix_run_id、step 5 不挂 record）—— 投后反查就断了
- **重跑默认全量** —— 局部重跑用 scene_nums / role_ids，只跑老板指的那段
- **3.5 配额超标硬编** —— KB 没料就说没料，提示补 KB
- **用 AI 化套话** —— 禁"赋能/打通/闭环/抢占心智/极致/匠心"

## 已知约束

- 新链每步产物 = draft 落库，老板采纳才 adopted；下游只跟 adopted 走（多版本不覆盖）
- 全链 LLM/出片 tool 不走 Human Gate；`record_cost` 走 Gate（CLI 批）
- step 7 并发跑（asyncio.gather），总时间 ≈ 单段；`dry_run=True` 可零费用调试 prompt
- 3.6 的 `target_model` 档案在 `config/prompts/video_model_profiles/<model>.md`（热加载，实测后直接改档案）
- prompt 全外置 `config/prompts/`，改完即生效（mtime 自检，KE 无需 restart）
- 前端 /sku-pipeline 各 step tab 与本 skill 同源；产物输出区挂 OutputFeedback 点评组件（反馈飞轮）

## 跟 CLAUDE.md / 其他 skill 的关系

- 是 CLAUDE.md "sku-pipeline step N" 各节的编排 SOP 总览（单 tool 细节以 CLAUDE.md 各节为准）
- step 1 缺成本调 cost-luru；投放支线包诊断接 audience-pack-diagnosis；投后复盘接 product-analysis
- 只要脚本不要片 → script-writer（别误触本 skill 白烧出图出视频）
