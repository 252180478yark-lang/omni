---
name: ai-soft-ad-video
description: Use when the user asks to generate an omni/Hetiankuan SKU O/A1 AI soft-ad video or optimize a soft-ad for the first three seconds and completion rate from selected audience lineage, exported Yuntu audience profile, selling point matrix, keyword pack, and product references. This skill must reuse existing pipeline lineage and must not handle deep planting/A3, regenerate audience packs, or default to human director briefs.
---

# AI Soft Ad Video

Generate lineage-grounded O/A1 soft-ad AI short videos for omni SKU pipeline. The goal is not a hard sell; it is to connect product, scene, selling point, and audience so Douyin can recognize the intended interest crowd while viewers feel they are watching a believable slice of life.

## Routing

Use this skill when the user says things like:

- "给 SKU002 跑一条软广 / O-A1 人群内容"
- "用这个人群包和关键词出一条 AI 短视频"
- "Seedance 2.0 软广脚本 / 纯 AI 短视频"
- "先跑软广，后面再做硬广 skill"

Do not use generic copywriting, social-content, or script-writer. Do not use `generate_director_brief` unless the user explicitly asks for a human shooting brief. `sku-pipeline` stops at `audience_pack_id`; this skill starts from that handoff and then uses `generate_creative_pack(kind='video_soft_ad')` for formal pure-AI video with lineage.

“软种草/深度种草/解决画像痛点/A3”不要触发本 skill，走 `ai-planting-video`。本 skill 的固定契约是 `video_soft_ad / intent=soft_ad / completion_rate`；它不提炼种草痛点桥，也不按 A3 判 winner。

## State machine

Use these state names exactly and never replace a review state with a tool name:

```text
LINEAGE_REVIEW
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

The first stop is always `LINEAGE_REVIEW`. A tool such as `generate_creative_pack` is an action inside the state machine, not a state or a user-approval boundary.

## Required Inputs

Before generating, locate and reuse existing lineage:

- SKU id and product data from `mvp_sku`.
- Adopted selling point matrix from step 2.
- Selected audience record from step 3.
- Latest audience portrait from step 3.5.
- Adopted audience pack from step 4; this `audience_pack_id` is the formal handoff from `sku-pipeline`.
- Adopted keyword pack if available.
- Actual exported Yuntu audience-pack profile CSV or structured summary when available.
- Product white-background reference image before video segment generation.

Never regenerate the audience pack or keyword pack just because content generation starts. The pack and keyword work exists to feed this step.

## Workflow

1. **Lineage audit**
   - List/get adopted `audience_pack`, adopted `keyword_pack`, and latest `audience_portrait`.
   - If the portrait has KB-coverage warnings, treat portrait details as cold-start hypotheses, not facts.
   - If no portrait exists, run `generate_audience_portrait(audience_record_id=...)` before video generation.
   - Present the unique proposed lineage at `LINEAGE_REVIEW` and stop for explicit user confirmation before script generation.

2. **Dual-profile calibration**
   - Use two audience sources: planned portrait = who the strategy intended to reach; exported Yuntu profile = who the platform actually selected.
   - When a Yuntu CSV/profile is provided, summarize it into 8-12 executable content signals before script writing: age/gender, city tier, family stage, spending posture, content interests, touchpoints, scene, purchase behavior.
   - Shared signals become primary visual/text anchors.
   - When planned and actual profiles conflict, visual casting, scene, opening hook, and native-feed behavior follow the actual Yuntu profile; selling-point logic and mind state stay grounded in the planned portrait and selling-point matrix.
   - If the profiles conflict heavily, choose `actual_pack_priority`, `planned_portrait_priority`, or `split_version`; do not blend them into a vague generic crowd.
   - Do not pass the full CSV into `extra_context`; pass a compact "high share / high TGI -> executable content signal" summary.

3. **Soft-ad resonance method**
   - Watchability comes before vector matching. First answer why the selected crowd would not swipe away; a script with high vector similarity but weak human interest is not launchable.
   - Require `human_watch_gate_score >= 80`, `first_1s_hook_action_present=true`, `first_5s_expectation_gap_present=true`, non-empty `viewer_reason_to_continue`, `emotion_peak_count >= 1`, and `douyin_native_feel_score >= 75` before video spend.
   - Use the working weight model: human watchability 40%, visual vector 25%, text vector 15%, product action 10%, sound emotion 10%. Sound/music amplifies emotion; it cannot rescue a boring or fake story.
   - Use a fixed soft-ad skeleton before writing scenes: `life truth -> tiny friction -> familiar action -> quiet payoff -> light product memory`.
   - The emotional target is not "make the product look good"; it is "make the selected crowd feel this is my life, then let the product become the thing that made the moment smoother".
   - For O/A1 interest crowds, the first 5 seconds must contain a recognizable identity/scene signal, not a product explanation.
   - The first 3 seconds are a stop-swipe micro-story, not atmosphere setup. They must contain identity or setting recognition, a tiny conflict/suspense/contrast, and visible action change.
   - Require `first_3s_stop_reason`, `first_3s_shot_count`, `first_3s_static_scene_seconds`, `first_8s_product_action_bridge`, and `golden_3s_gate_score` before video spend.
   - Golden 3s minimums: stop reason is one of `identity_hook`, `setting_hook`, `tiny_conflict`, `suspense_gap`, `contrast_result`; `first_3s_shot_count >= 3`; `first_3s_static_scene_seconds <= 0.8`; `first_3s_mentions_product=false`; `first_8s_product_action_bridge=true`; `golden_3s_gate_score >= 70`.
   - Product interest should come from one concrete action: pick up, pour, place on table, compare bottle size, receive a family reaction, or solve a small kitchen inconvenience.
   - Avoid abstract life slogans unless they are earned by a visible action. Lines like "男人的成熟..." are risky if the scene has not first shown a real pressure or real relationship.
   - For selected/seeded audiences, write from their daily life vocabulary: work fatigue, family meal rhythm, parents visiting, child waiting to eat, practical buying logic, not generic "quality life" language.
   - Use public-market soft-ad frameworks only as a structure check, not as hard-sell copy:
     `TikTok-first native content -> identity/setting hook -> short body movement -> open close`; native ad fit means the video must match Douyin feed behavior, not just mention the right interests.
   - Before vector matching, require a human-watch gate and a structure gate with six nodes: `life truth`, `tiny friction`, `familiar action`, `product action bridge`, `quiet payoff`, `open ending motive`.
   - If the human-watch gate or structure gate is below threshold, revise the story premise before adjusting visual/text/music vectors. A high vector score cannot rescue a story that does not feel like the audience's life.

4. **Content matching contract**
   - Define one product-to-person bridge: audience person, life scene, unique selling point, explicit benefit, implicit emotional benefit, and product role in the scene.
   - Keep one core event. Soft ad should feel like "a normal moment where the product happens to be useful", not a sales page.
   - Include the keyword pack as text/interest vocabulary, not as forced subtitles.
   - Choose the soft-ad methodology before writing: usually `M2 Slice of Life` for ordinary O/A1 daily-life soft ads; use `M3 CER` only when the crowd needs an emotional rise; use other modules only when the scene, SKU, and budget justify them. Methodology is the story skeleton, not a fixed shot template.

5. **Vector preset before script**
   - `generate_creative_pack(video_*)` now builds a pre-generation vector preset before the LLM writes the script.
   - The preset scores four lanes against audience/scene/selling-point/product anchors: `visual`, `text`, `sound`, and `product_action`.
   - The prompt receives the preset as "投前向量预设库"; the script's 第 2.5 部分 must inherit the preset baseline/candidates rather than inventing a new map after writing.
   - Require at least 7 of the core signals to appear across the 9-grid storyboard.
   - Product role must be "daily prop / action trigger / table object / light brand signature", not "sales speaker".

6. **Generate soft-ad script**
   - Call `generate_creative_pack` with:
     - `kind='video_soft_ad'`
     - `audience_pack_id=<adopted_pack_id>` when available
     - `intent='soft_ad'`
     - `target_model='seedance'`
     - `num_variants=1` for first proof, `2-3` only when explicitly making A/B candidates
     - `extra_context=<content matching contract>`
   - The output must include methodology choice, vector preset, character sheets, scene nodes, 9-grid storyboard, 70-point preflight self-check, Seedance prompt blocks, `metrics_json`, and `算法信号三向量`.
   - The result trace and `pipeline.scripts.notes` should carry the vector preset score/baseline/allowed sweeps for A/B handoff.

7. **Review gate before video**
   - Must be O/A1 soft ad: no price, no discount, no hard CTA, no "buy now".
   - Brand/product name appears at most once; product appears naturally as a prop.
   - One scene, one main person, one main selling point.
   - If an actual Yuntu profile was provided, the script must include dual-profile calibration fields: `actual_pack_profile_status=provided`, `actual_pack_profile_used=true`, at least 8 actual-pack signals, alignment score, and conflict resolution.
   - The human-watch gate must pass before vector prediction: watchability >=80, 1s hook action present, 5s expectation gap present, one clear reason to continue, at least one emotion peak, Douyin-native feel >=75.
   - The golden 3s gate must pass before any video generation. If the opening is only a slow table/room setup, rewrite it.
   - 第 2.4 structure gate must score at least 70 and include all six nodes: life truth, tiny friction, familiar action, product action bridge, quiet payoff, open ending motive.
   - Product visual details must be based on the product reference image. If not verified, write "以产品白底图为准" rather than inventing bottle material, label, color, or cap details.
   - The first subtitle must fit the prompt constraint. If the prompt says <=12 Chinese chars, revise before video.
   - Pure AI output sections should say "AI role sheet / no human shooting needed"; avoid leftover human-shooting wording.
   - The 9-grid storyboard must be coherent before video. If characters, room layout, product position, or plot continuity breaks in the storyboard, revise before generating character sheets or video.
   - The preflight self-check must score at least 70 overall, with watchability >=80, visual >=72, text >=68, and sound >=55. This is a heuristic gate; embedding prediction still runs afterward.
   - If the generated script's real embedding score is below 70, revise the preset/script before video generation. Do not treat the LLM self-check as a substitute for vector similarity.
   - Run the self-built triangle audit before video spend:
     `triangle_match.audit_script_triangle(script_id=..., portrait_id=..., product_ref_desc=...)`.
     It must report `product_audience`, `product_content`, and `audience_content`; the gate is pass only when overall >=70 and both content edges are >=70.

8. **Produce video**
   - Product refs are mandatory for `generate_video_segments`; do not bypass with `allow_no_product=True` for a formal product soft ad.
   - For character consistency, generate character sheets first when the script has recurring people.
   - For Seedance 2.0, use prompt blocks of no more than 15 seconds for API segment generation. Keep the same face anchors, clothing, room layout, product reference, and lighting across blocks.
   - Prompt block 1 must translate the 0-3s micro-story beat by beat, then place the product action bridge in 3-8s. Do not let the product first appear after 8s in a formal soft ad.
   - Bind adopted scripts to same-round experiment arms before paid video generation. Character sheets and video assets inherit the arm.
   - Call `generate_video_segments(..., preflight_only=True)` first. Review the compiled prompts, exact reference manifest, pre-video vector gate, freshness fingerprint, `generation_set_id`, and estimated provider calls; stop for explicit user approval.
   - The paid call must reuse that `generation_set_id`. Each provider submission revalidates the current script, arm, facts, profile, embedding identity, references, and set.
   - Only post-video-gate-passing assets may be selected. A complete ready generation set is adopted atomically after explicit user approval; missing or failed segments remain draft.
   - If a generated frame shows wrong Chinese, gibberish, competitor condiment bottles, third-party logos, or other identifiable condiment brands, reject the video and regenerate from prompt; do not try to hide it with captions.
   - Report script-level vector score and actual-video post-gate score separately. If the video score falls below the target, keep it draft and name the missing/drift signals.

9. **A/B binding**
   - After the user adopts a script, create or reuse an experiment with `intent='soft_ad'`, `track='ai_video'`, and `portrait_id=<latest_portrait_id>`.
   - Attach each adopted script as an arm with exactly one `swept_variable`.
   - Embed both content and audience, run prediction, then run visual prescreen before paid testing:
     - `embed_content_and_audience(script_id=..., portrait_id=...)`
     - `predict_audience_match(experiment_id=...)`
     - `experiment_prescreen_round(experiment_id=..., round_no=...)` after video assets exist
   - Winner is decided only by post-launch north-star metrics, not by vector score.

## Single-Variable Ladder

Use this order unless the user gives a better reason:

1. `actual_profile_mapping` - same SKU/selling point, change only how actual Yuntu-profile signals become casting, scene, props, and opening hook.
2. `human_watch_gate` - same product/selling point/audience, change only the reason to continue, 1s action, 5s expectation gap, and emotion peak.
3. `soft_ad_structure` - same product/selling point/audience, change only life truth + tiny friction + quiet payoff.
4. `scene` - same product and selling point, different life scene.
5. `opening_hook_3s` - same scene, different first 3 seconds. Move this to the next round immediately when the current video is slow, lacks a golden 3s hook, or introduces product too late.
6. `visual_vector` - same story, different composition, color, prop density, or camera language.
7. `selling_point_set` - same crowd and scene, different explicit/implicit selling point emphasis.
8. `story_pace` or `edit_pace` - only after the content idea is clearly right.
9. AI technical variables: `prompt_structure`, `realism_anchor`, `character_ref`, `negative_words`, `motion_style`.
10. `bgm` - usually later; visual and text signal matter more for early soft-ad matching.

Do not mix content variables and AI technical variables in one round. Do not change intent inside an experiment.

## Similarity Improvement

Use vector match as a cold-start filter:

- Pre-generation preset score chooses the baseline elements and allowed single-variable sweeps.
- Dual-profile calibration comes before vector scoring; if the actual Yuntu audience differs from the planned portrait, score content against the actual delivery profile for visual/text/native-feed signals.
- Post-generation content embedding checks whether the actual script still matches the intended audience.
- Post-merge actual-video embedding checks whether the generated/edited final video still carries the same audience signals. This catches cases where realism edits remove the very signals that made the script score high.
- Triangle audit checks the full bridge: product-to-audience strategic fit, product-to-content product role, and audience-to-content delivery signal.
- High vector score but low watchability means false precision; revise the human-watch gate before touching vector vocabulary.
- Low visual score: adjust scene props, room, character behavior, camera distance, product placement, and visual vocabulary.
- Low text score: adjust subtitles, hook wording, dialogue, keyword vocabulary, and daily-life phrases.
- Low music score: adjust rhythm and mood only after visual/text are acceptable.
- High vector score but poor completion rate means false positive; trust the north star and test the next variable.

## State-Machine Notes

The A/B state machine already supports `soft_ad` and `ai_video`. Soft ad north star is `completion_rate`; auxiliary metric is `new_followers`. AI-video experiments add technical variables on top of the normal creative variable pool.

The experiment must have `portrait_id` for vector prediction. If a generated script lacks `portrait_id`, explicitly create the experiment with `portrait_id` first, then attach the script. The preferred system behavior is for `generate_creative_pack` to save the latest portrait id into `pipeline.scripts`.

For detailed handoff and test commands, see `references/state-machine.md`.
