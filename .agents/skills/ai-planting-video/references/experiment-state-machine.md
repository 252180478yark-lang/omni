# 种草实验、Generation Set 与投后迭代

## 何时读取

- `ARM_BOUND`：每采纳一条就绑定同实验同轮；一臂是草稿，两臂起才构成 A/B。
- `REFERENCE_REVIEW` / `PRE_VIDEO_GATE_REVIEW`：保证角色、产品图、preflight 和 set 都绑定 arm。
- `VIDEO_SEGMENTS_REVIEW` / `GENERATION_SET_READY` / `ADOPTED`：技术重做、整组 gate 与原子采纳。
- `METRICS_PENDING` / `WINNER / NEXT_ROUND`：严格回传、A3 winner 与下一变量。

缺少本文件时不得创建实验、采纳 generation set、回传或锁 winner。

## 第一轮

两条首轮候选必须进入一个 `intent='planting'`、`track='ai_video'` 实验的同一个 round，首扫 `pain_scene_bridge`。除 variable value 外，SKU、portrait、selling point、角色、模型和全部 baseline 固定。

只有一个 arm 时状态是“实验草稿/待补对照臂”，不能显示 A/B winner。

创建实验前检查 production evaluation policy 六阈值：`play_3s_floor`、`completion_floor`、`a3_floor`、`cpm_ceiling`、`min_impressions`、`min_a3_eligible_users`。允许用户用 `evaluation_policy_overrides` 设置；null 可落库，但下一变量自动化必须返回 `diagnostic_policy_missing`。

## Arm 绑定

采纳脚本和 attach arm 是同一用户批准边界。角色定妆、视频 asset、generation set、投后指标都必须继承同一个 experiment/round/arm，不能把正式资产重新挂到另一 arm。

## Generation Set

Preflight 固化 expected segment manifest、reference manifest、pre-video group gate 和 profile version。付费生成必须带同一 `generation_set_id` 并在每次 provider 调用前重新验证当前脚本、事实、profile、embedding identity、refs 与 set。

技术重做只能替换同一 set 同一 scene 的 selected candidate，不能改内容变量。整组只有每个 expected scene 各有一个 post-gate-passing selected asset 时才 ready。

用户采纳 ready set 时，所有 selected assets 在一个事务中原子 adopted；重复采纳幂等。缺段、混 set、哈希漂移、旧 judge、失败 gate 都阻止采纳。投后指标只接收 adopted set 中当前 selected 且字节未变化的资产。

## 严格指标

正式种草回传使用 0–1 rate、CNY 和原始计数：

- A3：`new_a3 / a3_eligible_users`
- CPM：`spend / impressions × 1000`
- 三秒率：`play_3s / impressions`
- 完播：`play_complete / completion_denominator`，并保存 `completion_denominator_type`

若只有同尺度 rate 与对应 denominator，可存 `effective_numerator=rate×denominator` 并标 provenance；不能平均素材百分比。无分母、零分母、非 CNY、NaN/Inf、口径混用或覆盖不全标 suspect，不进入可信 winner。

## Winner

种草仅按 pooled `a3_ratio` 排序。CPM、三秒率、完播率用于诊断；投前预测分永不改变排名。至少两臂、每臂当前整组资产合格、A3/曝光/诊断覆盖完整且曝光倍率小于 policy 上限，才允许 confident lock。

`n_videos >= 5` 是工程门槛而非显著性。`force=True` 只能旁路 n<5 或曝光不均并留审计，不能旁路单臂、缺分母、旧 gate、wrong leader 或正式资产不合格。

## 确定性下一动作

1. 窗口未完、A3/诊断覆盖不全或曝光不均 → `rerun_current_variable`。
2. 三秒率低于阈值 → 候选 `opening_hook_3s`, `presentation_motif`。
3. 完播率低于阈值 → 候选 `story_pace`, `justification_density`。
4. A3 低于阈值 → 候选 `pain_scene_bridge`, `justification_module`。
5. CPM 高于上限 → `inspect_delivery_or_audience`。
6. 其余按 planting profile 的 `global_iteration_order` 排除已测与已锁变量，取第一个。

状态页和 `experiment_next_version_seed` 必须调用同一 helper；不要维护第二套变量顺序，也不要让 LLM解释因果。
