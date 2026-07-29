---
name: ai-planting-video
description: Use when老板要沿已有 SKU、人群画像或人群包血缘生成纯 AI 种草、软种草、深度种草或 A3 短视频，重点是用产品解决画像里的具体痛点、看完建立相信，或续跑种草视频实验；不用于 O/A1 软广播放优化、A4 收割、只写脚本、从零圈包、真人编导或竞品反推。
---

# AI 种草短视频

沿 omni 已落库血缘生成 `video_planting`、`intent=planting`、北极星为 `a3_ratio` 的纯 AI 视频段。种草要让画像中的人看到“我的具体麻烦，被这个产品用一个可信动作解决了”；它不是把软广换一个标题，也不是直接卖货。

## 持久化状态机

状态只由数据库产物推导，不写私有状态文件：

```text
LINEAGE_REVIEW
→ BRIDGE_REVIEW
→ SCRIPT_REVIEW
→ ARM_BOUND
→ REFERENCE_REVIEW
→ PRE_VIDEO_GATE_REVIEW
→ VIDEO_SEGMENTS_REVIEW
→ GENERATION_SET_READY
→ ADOPTED
→ METRICS_PENDING
→ WINNER / NEXT_ROUND
```

每到一个状态，输出当前 SKU/matrix/audience/portrait/pack/bridge/script/experiment/round/arm/generation-set 血缘、第一阻断项、硬闸结果、成功与失败资产，以及恰好一个下一动作。没有产物就报告缺口，不猜状态。

用户必须在每个付费、采纳、发布、回传或锁 winner 边界明确说“显式继续/采纳/投放/回传/锁定”。“继续”只推进当前报告里的唯一下一动作；不能跨过两个状态。

## 路由边界

- 触发：种草、软种草、深度种草、A3、痛点—产品动作—解除、用产品解决画像痛点、续跑种草实验。
- O/A1、前三秒停滑、完播优化、`video_soft_ad / soft_ad / completion_rate` → `ai-soft-ad-video`；深度种草不要触发软广 skill。
- 只写脚本且不出片 → `script-writer`。
- 真人编导、真人拍摄 brief → `short-video-director-brief`。
- A4 收割、强 CTA → `video_harvest` 内容链。
- 从 SKU 跑到圈包 → `sku-pipeline`，在 `audience_pack_id` 停。
- 竞品“怎么拍”反推 → `video-reverse`；“打什么人” → `reverse_audience_analysis`。

## 渐进读取

在进入相应状态前读取下列文件。所需 reference 缺失或读不完整时，阻断当前状态；不要凭 soft-ad 记忆补写种草方法。

| Reference | 必读状态 | 用途 |
|---|---|---|
| `references/planting-method-library.md` | lineage/bridge/script 阶段 | 选择 M1/M2 与 M3–M9，约束证据和痛点解决桥 |
| `references/content-contract-schema.md` | script/reference/pre-video/video 阶段 | 校验内容契约、提示词容量、五维向量、哈希和参考图 |
| `references/experiment-state-machine.md` | arm/generation-set/metrics/winner 阶段 | 单变量实验、整组采纳、A3 汇总和下一轮 |

## 工作流

### 1. 复用前链路

读取已有 `sku_id`、adopted matrix、selected/adopted audience record、latest/adopted portrait、adopted audience pack；关键词包和云图实际包画像只能校准表达，不能替代 portrait 中有证据的痛点。

如果只给 SKU，先列出可继续的历史产物。不要重跑卖点、人群、圈包来“凑完整”。到 `LINEAGE_REVIEW` 停，等用户选择唯一血缘。

### 2. 提炼痛点—解决桥

调用 `generate_planting_pain_solution_bridge`，模型固定 `gemini-3.1-pro-preview`。桥必须来自当前 portrait 的生活状态/痛点与当前 SKU 可验证事实；云图标签只做校准。

返回候选桥、证据资格、`upstream_fact_hash` 与第一阻断项，到 `BRIDGE_REVIEW` 停。用户明确采用某条桥后才能生成脚本。

### 3. 生成两条同轮候选脚本

调用 `generate_creative_pack`：

```text
kind='video_planting'
intent='planting'
target_model='seedance'
pain_solution_bridge=<adopted bridge>
```

首轮两条候选只改变 `pain_scene_bridge` 的取值；SKU、人群、卖点、角色、目标模型和其余基线相同。每条都要通过 planting 内容闸与脚本三角向量闸。到 `SCRIPT_REVIEW` 停；不能自行采纳。

### 4. 先挂臂，再烧视频

用户每采纳一条候选，就在同一批准动作中把该脚本挂入 `SKU × portrait × intent=planting × track=ai_video` 实验、同一 round、同一 `swept_variable='pain_scene_bridge'`。第一条可进入单臂“实验草稿/待补对照臂”；第二条采纳后补入同轮，才可称 A/B。不能因尚无第二臂而阻断已采纳脚本继续走定妆和技术验证，但单臂不能比较或锁 winner。

建实验前展示六个生产阈值是否齐全：`play_3s_floor`、`completion_floor`、`a3_floor`、`cpm_ceiling`、`min_impressions`、`min_a3_eligible_users`。用户可通过 `evaluation_policy_overrides` 明确设置；也可暂存 null，但必须说明自动下一变量会停在 `diagnostic_policy_missing`。

到 `ARM_BOUND` 停，报告 experiment/round/arm IDs。

### 5. 定妆与产品参考图

为每个 arm 分别生成角色定妆；同一 arm 的视频只能用该 arm 的角色资产。产品白底图先用 `register_product_reference_asset` 登记为当前 SKU 的 adopted `product_reference`。正式种草不能用 `allow_no_product=True`。

输出 expected reference manifest 的资产 ID、角色、SKU、文件哈希，到 `REFERENCE_REVIEW` 停。不要在这里调用视频 provider。

### 6. 零视频调用预检

调用 `generate_video_segments(..., preflight_only=True)`。编译每段最终提示词，校验 50 / 60–87 / 107 字符每秒容量、精确参考图 manifest、五维适用声明、投前向量 ≥70、事实/profile/embedding 哈希新鲜度，并创建或复用 draft `generation_set_id`。

到 `PRE_VIDEO_GATE_REVIEW` 停，报告最终提示词、字符数、逐维/整组分、哈希、参考图和 `estimated_provider_calls`。此步不得产生视频 task ID。

### 7. 付费生成与成片后向量闸

只有用户对本次 `generation_set_id`、预计调用数和提示词显式继续后，才用同一 set 调 `generate_video_segments`。每次 provider 提交前必须重验 script/arm/facts/profile/refs/set；返回视频先以实际字节做 post-video 五维向量闸，再允许成为该 scene 的候选。

到 `VIDEO_SEGMENTS_REVIEW` 停。列全成功、失败、可重试 scene；失败段只在同一 generation set 内技术重做，不改内容变量。整组缺段或任一已选段不过闸时不能称 ready。

### 8. 整组采纳

只有 group gate 通过才进入 `GENERATION_SET_READY`。用户明确采纳后，整组 selected assets 原子变为 adopted；不能逐段偷采纳，也不能混入另一 set 的段。到 `ADOPTED` 停。

### 9. 投放回传与迭代

投放后按 arm 回传原始计数和口径：`new_a3`、`a3_eligible_users`、`spend`、`impressions`、`play_3s`、`play_complete`、`completion_denominator`、`completion_denominator_type`、`currency='CNY'`。缺分母、币种、曝光、覆盖或整组准入时停止，不补数。

种草 winner 只按 pooled `a3_ratio` 排；CPM、三秒率、完播率是诊断指标，投前向量分只排序，不参与 winner。系统阈值 `n>=5` 不是统计显著。用户明确锁定前不能调用 winner lock。

用同一确定性策略给一个下一动作：窗口/覆盖不全则重跑当前变量；三秒差扫钩子，完播差扫节奏/论证密度，A3 差扫痛点桥/论证模块，CPM 超限则检查投放或人群；否则按 profile 的全局变量顺序推进。

## 汇报模板

每次只给一张状态卡：

```text
state: <当前状态>
lineage: <关键 IDs>
first_blocker: <无则 none>
hard_gates: <通过/失败及证据>
assets: <成功/失败/selected>
metrics: <A3/CPM/三秒/完播及覆盖，尚无则 pending>
next_action: <恰好一个动作，注明是否需用户明确批准>
```
