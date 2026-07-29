# 种草内容契约与双向量闸

## 何时读取

- `SCRIPT_REVIEW`：检查 bridge、内容闸、脚本向量闸与逐段声明。
- `REFERENCE_REVIEW`：建立 SKU/arm 绑定的精确参考图 manifest。
- `PRE_VIDEO_GATE_REVIEW`：编译最终提示词并校验投前向量与新鲜度。
- `VIDEO_SEGMENTS_REVIEW`：对实际视频字节运行投后向量闸。

缺少本文件时不得生成或选择正式视频段。

## Bridge JSON

```json
{
  "audience_segment": "画像中的目标人",
  "portrait_evidence": [
    {"source": "portrait", "field": "portrait_md", "value": "画像原文中的生活状态或痛点证据"}
  ],
  "pack_calibration_evidence": [
    {"field": "pack_md", "value": "云图实际包信号；没有则为空数组"}
  ],
  "trigger_scene": "具体发生时刻",
  "pain_point": "可观察的麻烦",
  "pain_consequence": "对生活任务的后果",
  "product_action": "当前 SKU 的可见使用动作",
  "visible_result": "画面可观察的结果/解除",
  "product_evidence": [
    {"source": "sku", "field": "owner_selling_points", "value": "当前 SKU 可核验事实"}
  ],
  "belief_shift": "由证据支持的信念变化",
  "relevance_module": "M1 或 M2",
  "justification_module": "M3 至 M9 之一"
}
```

正式桥必须由 `gemini-3.1-pro-preview` 提炼并绑定 current lineage 的 `upstream_fact_hash`。

## 11 项内容硬闸

三个 0–100 分数字段都需 ≥80：

1. `portrait_scene_alignment_score`
2. `pain_specificity_score`
3. `product_solution_fit_score`

四个字段必须为 true：

4. `product_action_visible`
5. `solution_result_visible`
6. `justification_grounded`
7. `belief_shift_present`

四个字段必须为 false：

8. `hard_cta_present`
9. `price_promotion_present`
10. `fabricated_qualification_present`
11. `fake_testimonial_present`

脚本三角向量同时要求 `overall_score_100 >= 70`、`audience_content >= 70`、`product_content >= 70`。LLM 自评分不能替代真实 embedding。

## 提示词容量

Seedance API 每段 ≤15 秒。最终提示词按段校验：

- 最少 `50 字符/秒`
- 建议 `60–87 字符/秒`
- 最大 `107 字符/秒`

容量超限不能静默截断；先去跨层重复，再返回 `prompt_capacity_exceeded`。低于最少细节、时间戳不连续、人物/产品/动作/结果锚缺失则返回 `prompt_detail_insufficient`。

## 逐段五维声明

Profile 的五维是：

1. `audience_scene`
2. `pain_conflict`
3. `product_action`
4. `result_relief`
5. `justification_evidence`

每个 scene 必须显式保存 `applicable_dimensions`，只能从五维中选择、不可重复、不可空。投前和投后都只针对该段声明的 facts 评分；整组必须覆盖全部五维，且至少一段同时声明 `product_action` 与 `result_relief`。

公开闸门分使用 0–100；写入 `experiment_arms.predicted_match_score` 时才除以 100 变成 0–1。不要把两个尺度混用。

## 新鲜度指纹

投前 fingerprint 绑定：ordered final prompt hashes、upstream fact hash、intent profile version、embedding model/version。

投后 fingerprint 绑定：generation set ID、实际判读视频字节 hash、对应 final prompt hash、upstream fact hash、intent profile version、judge model/version。

任一字段变化都返回 `vector_gate_stale`。Gemini 必须判读一个内容寻址的不可变副本；判读前后哈希不一致不得选择资产。

## Reference manifest

Manifest 的每项至少包含 asset ID、role/type、SKU、arm（角色图）、文件引用及 SHA-256。产品图必须是当前 SKU 的 adopted `product_reference`；角色图必须绑定当前 script 与 arm。expected manifest 与 provider 实际发送 manifest 必须逐项一致，不能因 t2v/model 分支清空参考图。
