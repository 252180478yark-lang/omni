# Soft Ad State Machine Handoff

## Existing Fit

The experiment state machine already fits soft-ad AI video:

- `intent='soft_ad'` uses `completion_rate` as the north-star metric.
- `track='ai_video'` routes distillation to `pipeline.creative_pack`.
- AI-video experiments can sweep normal content variables plus AI technical variables.
- `record_ad_metrics` and `record_ad_metrics_batch` attach post-launch metrics to assets or experiment arms.
- `embed_content_and_audience` plus `predict_audience_match` gives a pre-launch audience-match ranking.
- `experiment_prescreen_round` filters obvious AI failures before paid testing.

## Required Test Flow

1. Generate candidate scripts with `generate_creative_pack(kind='video_soft_ad', intent='soft_ad', target_model='seedance')`.
2. Check the script-level gates before any video generation:
   - dual-profile calibration exists before human-watch gate when an exported Yuntu audience profile is provided
   - `actual_pack_profile_status` is `provided` or `not_provided`
   - if provided: `actual_pack_profile_used=true`
   - if provided: `actual_pack_core_signal_count >= 8`
   - if provided: `planned_actual_profile_alignment_score >= 60`, otherwise choose `split_version` or rewrite
   - if provided: `actual_profile_conflict_resolution` is one of `actual_pack_priority`, `planned_portrait_priority`, `split_version`
   - human-watch gate exists before vector preset and before golden 3s
   - `human_watch_gate_score >= 80`
   - `first_1s_hook_action_present=true`
   - `first_5s_expectation_gap_present=true`
   - `viewer_reason_to_continue` is non-empty and names the selected crowd's reason to keep watching
   - `emotion_peak_count >= 1`
   - `douyin_native_feel_score >= 75`
   - 第 2.4 structure gate exists before vector preset
   - `structure_fit_score >= 70`
   - `structure_life_truth_present`, `structure_tiny_friction_present`, `structure_familiar_action_present`, `structure_product_bridge_present`, `structure_quiet_payoff_present`, and `structure_open_ending_motive_present` are all true
   - pre-generation vector preset exists in the result trace and `pipeline.scripts.notes`
   - preset baseline has four lanes: `visual`, `text`, `sound`, `product_action`
   - preset `allowed_sweeps` lists the single-variable candidates for the first experiment rounds
   - golden 3s gate exists before storyboard/video generation
   - `first_3s_stop_reason` is one of `identity_hook`, `setting_hook`, `tiny_conflict`, `suspense_gap`, `contrast_result`
   - `first_3s_shot_count >= 3`
   - `first_3s_static_scene_seconds <= 0.8`
   - `first_3s_mentions_product=false`
   - `first_8s_product_action_bridge=true`
   - `golden_3s_gate_score >= 70`
   - methodology chosen and justified
   - script 第 2.5 部分 inherits the preset rather than inventing a new one
   - 9-grid storyboard present
   - preflight self-check >=70 overall, watchability >=80, visual >=72, text >=68, sound >=55
   - no unsupported product appearance details
3. User adopts at least two scripts or two values for one variable.
4. Create experiment:

```python
experiment_create(
    sku_id="SKU-367991-0002",
    intent="soft_ad",
    portrait_id="<latest_portrait_id>",
    track="ai_video",
)
```

5. Attach arms:

```python
experiment_attach_arm(
    experiment_id="<experiment_id>",
    script_id="<script_id>",
    swept_variable="scene",
    variable_value="下班饺子小餐桌",
    adopt_script=True,
)
```

6. Embed and rank:

```python
embed_content_and_audience(script_id="<script_id>", portrait_id="<portrait_id>")
predict_audience_match(experiment_id="<experiment_id>")
triangle_match.audit_script_triangle(
    script_id="<script_id>",
    portrait_id="<portrait_id>",
    product_ref_desc="product white-background image: bottle shape, label, cap, packaging details",
)
```

7. If the real post-generation embedding score is below 70, revise the preset/script before video generation. Formal soft-ad profiles fail closed below 70; user approval cannot bypass this technical gate.
8. If the triangle audit is below 70 overall, or either `product_content` / `audience_content` is below 70, revise the script before video generation.
9. Generate arm-bound character sheets and register the current-SKU product reference. Formal soft-ad segments always keep the exact product-reference manifest; prompt wording controls when it becomes visible.
10. Call `generate_video_segments(..., experiment_arm_id=..., preflight_only=True)` and stop. The result must include a passing `pre_video` group gate, exact reference manifest, current hashes, `generation_set_id`, and estimated provider calls with no video task ID.
11. After explicit approval, call the same tool with that `generation_set_id`. Every provider boundary reloads and revalidates current state; each actual video runs the `post_video` vector gate before selection.
12. A generation set becomes ready only when all expected scenes have one passing selected asset. Adopt its selected assets atomically after explicit approval; do not mix segments across sets.
13. Run visual prescreen before paid launch. A vector score ranks/filters candidates but never declares the completion-rate winner.
14. After launch, record metrics:

```python
record_ad_metrics(
    asset_id="<video_asset_id>",
    experiment_arm_id="<arm_id>",
    metrics={
        "impressions": 1000,
        "completion_rate": 0.32,
        "new_followers": 12
    },
)
```

15. Check status, lock the `completion_rate` winner only when sample is sufficient, then generate the next-version seed.

## Recommended Variables

- Round 1: `actual_profile_mapping` - same SKU/selling point, change only how actual Yuntu-profile signals become casting, scene, props, and opening hook.
- Round 2: `human_watch_gate` - same audience/product/selling point, change only the reason to continue, 1s action, 5s expectation gap, and emotion peak.
- Round 3: `soft_ad_structure` - same audience/product/selling point, change only the life truth + tiny friction skeleton.
- Round 4: `opening_hook_3s` - same scene and product action, change only the first 3 seconds. Use this immediately if the last video was slow or product entered too late.
- Round 5: `scene`
- Round 6: `visual_vector`
- Round 7: `selling_point_set`
- Round 8: `story_pace`
- Round 9+: AI technical variables such as `prompt_structure`, `realism_anchor`, `character_ref`, `negative_words`, `motion_style`

## Guardrails

- One round, one variable.
- Same SKU, same intent, same portrait, same north star.
- If an actual Yuntu profile exists, do not optimize creative variables until actual-profile mapping is explicit; otherwise A/B tests are testing the wrong delivery crowd.
- Do not optimize vectors until the human-watch gate passes; precise but boring content should be rewritten, not keyword-stuffed.
- Do not mix `soft_ad_structure` with visual/text/music vector changes in the same round. First prove the story skeleton, then tune signal vectors.
- Keep exposure volume comparable. If one arm has much more exposure, treat the result as contaminated.
- Vector score ranks candidates; it never declares the winner.
- Generation-set adoption and publishing are explicit user boundaries; no individual segment can bypass the complete-set gate.
- Script vector score is not the same as final-video vector score. Any manual edit, segment split, missing audio, removed subtitle, or removed character interaction requires a new actual-final vector check.
- `n>=5` is an engineering threshold, not statistical significance.
- Distilled rules describe the winning setting, not a causal explanation.
