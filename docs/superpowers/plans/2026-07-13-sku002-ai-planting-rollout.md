# SKU-002 AI Planting Video Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the complete planting workflow on SKU-002 using its adopted matrix, selected audience, real audience pack, refreshed portrait, user-confirmed product image, two Round 1 route arms, final MP4 assets, A3 postbacks, and one data-driven next round.

**Architecture:** This is an operational rollout, not a code implementation. It uses the artifacts and APIs delivered by the other four plans. Existing history remains immutable. New portrait, manifest, scripts, experiment, arms, segment/final assets, and postbacks are appended and linked through the current pipeline.

**Tech Stack:** Existing omni MCP tools, PostgreSQL read-only verification, SKU Pipeline UI, 巨量/云图 export CSV, final MP4 assets.

---

## Preconditions

Complete and deploy:

1. 2026-07-13-ai-planting-framework-foundation.md
2. 2026-07-13-content-experiment-metrics-loop.md
3. 2026-07-13-ai-video-finalization-gates.md
4. 2026-07-13-ai-planting-soft-ad-skills-ui.md

This rollout contains two mandatory human gates:

- the user confirms that the product image belongs to SKU-367991-0002;
- the user selects at least two eligible route candidates before paid rendering.

Do not auto-run those gates.

### Task 1: Freeze the known SKU-002 lineage and readiness facts

**Known lineage on 2026-07-13:**

- SKU alias: SKU-002 → SKU-367991-0002
- adopted matrix: a3e479ce-dbc4-4cf9-ab90-7dc571cd3377, version 19
- selected/adopted audience “舒适休闲”: 6cceff70-3d16-4bad-b810-13f08fbe66fd
- current portrait: f666bb9e-9e4e-48d2-816f-95c57192dda7, draft version 1
- adopted audience pack: 194bb95f-00ae-41f1-88d0-077f25a717dc, version 4
- adopted keyword pack: ffcf875a-32ea-4d24-b910-bd83ed9b8e3f, version 6
- actual pack CSV: E:\agent\omni\services\knowledge-engine\config\audience\SKU002舒适休闲主包AD画像数据.csv
- external audience ID: 482514677
- current pack size: 1,000,415
- current experiment: none
- candidate product image: E:\agent\omni\data\assets\product_refs\sku002_downloadImg.png
- candidate product image dimensions: 800×800
- candidate SHA-256: 80458451EF49595E9DA75BE234714CDD6AB2E7F42F1FB38CD9612DD18CB53D86
- legacy hand-assembled asset: 07975511-7d24-4420-80a1-565ba707d79b, about 30.08 seconds, no audio, no arm, no prescreen

- [ ] **Step 1: Re-query all IDs read-only**

Use pipeline get/list tools or:

~~~sql
SELECT id, status, version
FROM pipeline.matrix_runs
WHERE sku_id = 'SKU-367991-0002'
ORDER BY version DESC;

SELECT id, status, selected_for_pack
FROM pipeline.audience_records
WHERE id = '6cceff70-3d16-4bad-b810-13f08fbe66fd';

SELECT id, status, version
FROM pipeline.audience_portraits
WHERE sku_id = 'SKU-367991-0002'
ORDER BY version DESC;

SELECT id, status, version, audience_portrait_id, execution_meta
FROM pipeline.audience_packs
WHERE sku_id = 'SKU-367991-0002'
ORDER BY version DESC;

SELECT id, status, intent, north_star_metric, audience_pack_id
FROM pipeline.experiments
WHERE sku_id = 'SKU-367991-0002'
ORDER BY created_at DESC;
~~~

Expected: IDs above still resolve; no running planting experiment exists. If a running planting experiment appears, resume it instead of creating a duplicate.

- [ ] **Step 2: Verify the actual audience CSV**

Confirm the file is readable and record file hash/mtime in the content contract. Do not re-circle or replace the adopted audience pack.

- [ ] **Step 3: Classify old assets**

Mark asset 07975511-7d24-4420-80a1-565ba707d79b as a legacy diagnostic fixture only. It cannot satisfy READY_FOR_TEST because it has no audio, experiment arm, generation manifest, or whole-video prescreen.

- [ ] **Step 4: Produce a readiness report**

Expected blockers before continuing:

1. portrait must be refreshed and adopted;
2. product image SKU binding must be confirmed by the user;
3. no route manifest/experiment exists.

### Task 2: Refresh the portrait against the latest analysis rules

- [ ] **Step 1: Generate a new portrait version**

Call generate_audience_portrait with:

~~~json
{
  "audience_record_id": "6cceff70-3d16-4bad-b810-13f08fbe66fd",
  "extra_context": "沿用已采纳舒适休闲人群和实际云图包画像；补齐真实需求、具体痛点、触发场景、犹豫/阻断、正负情绪触点、文字/画面/声音算法信号，以及卖点—痛点—场景—需求连接。缺失事实标 unknown，不补造。"
}
~~~

Expected: a new draft portrait with parent_portrait_id=f666bb9e-9e4e-48d2-816f-95c57192dda7.

- [ ] **Step 2: Review portrait evidence**

Check:

- every claim has [KB:], 🧠, or ⚠️ provenance;
- true_need, pain_point, trigger_scene, hesitation, blockers are explicit;
- all three algorithm-signal tracks exist;
- no SKU002-only sauce facts leak into unrelated products;
- validation warnings are explained rather than hidden.

- [ ] **Step 3: Human gate — adopt the portrait**

Show the portrait to the user. Only after explicit approval call:

~~~text
pipeline_adopt(
  table='audience_portraits',
  run_id=portrait_result['portrait_id']
)
~~~

- [ ] **Step 4: Bind the adopted portrait to the existing pack snapshot**

Call:

~~~text
pipeline_bind_pack_portrait(
  audience_pack_id='194bb95f-00ae-41f1-88d0-077f25a717dc',
  portrait_id=portrait_result['portrait_id'],
  actual_portrait_source='services/knowledge-engine/config/audience/SKU002舒适休闲主包AD画像数据.csv',
  actual_portrait_sha256=actual_audience_csv_sha256
)
~~~

Expected: the tool preserves the existing pack ID and adopted status, stores the actual CSV source/hash and portrait version in execution_meta, and changes neither pack_md nor version. Do not circle a new pack.

### Task 3: Validate and confirm the product reference

- [ ] **Step 1: Run the product-reference validator**

Validate:

~~~text
E:\agent\omni\data\assets\product_refs\sku002_downloadImg.png
~~~

Expected machine facts:

- 800×800
- SHA-256 80458451EF49595E9DA75BE234714CDD6AB2E7F42F1FB38CD9612DD18CB53D86
- clean white/neutral background passes
- label and bottle are visually readable

- [ ] **Step 2: Human gate — confirm SKU binding**

Display the image and ask the user to confirm it is the product reference for SKU-367991-0002. A machine white-background score is not SKU identity proof.

- [ ] **Step 3: Persist the validated reference**

Upload/bind it with:

~~~json
{
  "sku_id": "SKU-367991-0002",
  "confirmed_by_user": true
}
~~~

Expected: content contract product_ref contains the exact hash, dimensions, background score, SKU, confirmation, and verification time.

### Task 4: Build and review the 4→2 planting route manifest

- [ ] **Step 1: Create/reuse the idempotent manifest**

Call:

~~~text
generate_creative_pack(
  kind='video_planting',
  sku_id='SKU-367991-0002',
  audience_pack_id='194bb95f-00ae-41f1-88d0-077f25a717dc',
  workflow_mode='full_video',
  product_refs=[product_ref_result['product_ref']],
  route_shortlist_target=4,
  intent='planting',
  target_model='seedance'
)
~~~

Expected stage: ROUTE_REVIEW.

- [ ] **Step 2: Verify manifest hard gates**

For every route, verify:

- route ID and framework-v1;
- N/P/V is present in the compatibility matrix;
- P5 is absent;
- P6 appears only with verifiable authority evidence;
- the same pain, need, selling point, semantic scene, duration, product action core, product hash, and audience pack are fixed;
- excluded routes retain explicit reasons;
- vector is only a tie-breaker.

Expected: target four text routes; if only 2–3 survive, show route_pool_limited; fewer than two blocks.

- [ ] **Step 3: Show default Top 2 and alternatives**

Display the deterministic order:

~~~text
route_fit_total desc
→ triangle_score desc
→ vector_score desc
→ route_id asc
~~~

State visibly: “这些是投前排序，不能判 winner；投后 A3 转化率才判 winner.”

- [ ] **Step 4: Human gate — select at least two routes**

The user must select two eligible route IDs. Do not render all four automatically.

### Task 5: Derive scripts, create Round 1, and attach adopted arms

- [ ] **Step 1: Derive formal render-candidate scripts**

Call generate_creative_pack again with route_manifest_id and the selected route IDs. Expected:

- stage SCRIPT_REVIEW;
- each script parent_script_id points to the manifest;
- artifact_role=render_candidate;
- render_eligible=true;
- swept_variable=content_framework_route;
- variable_value is the stable route ID;
- variable-difference card passes.

- [ ] **Step 2: Review scripts**

Verify each contains:

- who moves from which blocker toward A3;
- inherited need/pain/scene/emotion/selling-point evidence;
- complete 30-second timeline unless 45 seconds is evidence-required;
- 6–9 continuous nodes;
- product appearance/use plan;
- character list;
- target-model prompt blocks;
- text/visual/sound/product-action signals;
- no price, hard CTA, fake testimonial, or unsupported qualification.

- [ ] **Step 3: Configure the planting experiment policy**

Create:

~~~json
{
  "version": "content-eval-v1",
  "min_arms": 2,
  "min_assets_per_arm": 1,
  "replication_reference": 5,
  "min_impressions_per_arm": null,
  "min_spend_per_arm": null,
  "min_denominator_per_arm": null,
  "require_one_volume_minimum": true,
  "max_exposure_ratio": null,
  "max_spend_ratio": null,
  "require_balance_limits": true,
  "require_same_data_window": true,
  "require_closed_attribution_window": true,
  "diagnostic_thresholds": {}
}
~~~

Before launch, the operator must fill at least one volume minimum, preferably min_denominator_per_arm for a planting test, both acceptable exposure/spend balance ratios, and any diagnostic thresholds they want the next-variable policy to classify automatically. replication_reference=5 is a stability annotation, not a demand to burn five videos per arm. Do not invent these thresholds in code or this runbook.

- [ ] **Step 4: Create the experiment**

Call experiment_create with:

- sku_id=SKU-367991-0002
- portrait_id=portrait_result['portrait_id']
- audience_pack_id=194bb95f-00ae-41f1-88d0-077f25a717dc
- intent=planting
- track=ai_video
- north_star_metric=a3_ratio
- evaluation_policy=approved_evaluation_policy

- [ ] **Step 5: Human gate — adopt and attach scripts**

After explicit script approval, call experiment_adopt_script for each selected route with experiment_id=experiment_result['experiment']['id'], swept_variable=content_framework_route, and variable_value=route['route_id']. Ensure the tool verifies audience_pack_id=194bb95f-00ae-41f1-88d0-077f25a717dc, attaches both scripts to the same open Round 1, and returns distinct arm codes.

### Task 6: Render, assemble, and prescreen final videos

- [ ] **Step 1: Generate deterministic character sheets**

Call generate_character_sheets for every adopted arm. Any required-role failure blocks that arm; do not continue with a partial cast.

- [ ] **Step 2: Generate segments and final assets**

For each arm call:

~~~text
generate_video_segments(
  script_id=arm['script_id'],
  product_refs=[product_ref_result['product_ref']],
  face_refs=character_sheet_result['validated_refs'],
  experiment_arm_id=arm['id'],
  target_model='seedance',
  generate_audio=True,
  finalize=True
)
~~~

Expected:

- all segments report requested/actual Seedance provider/model;
- accepted product refs are nonzero;
- segment assets are linked to the arm;
- one final asset has scene_no=NULL and asset_role=final;
- ffprobe confirms 9:16 H.264 video and a real/generated/supplied AAC audio source;
- silent output is not READY_FOR_TEST.

- [ ] **Step 3: Run whole-video prescreen**

Call experiment_prescreen_round. Expected: only final assets are judged. Failed arms remain reviewable but cannot launch.

- [ ] **Step 4: Human gate — approve test launch**

Show:

- final MP4;
- arm code;
- route and single-variable difference;
- product/model/assembly checks;
- visual-prescreen result;
- planned comparable data window and delivery minima.

Only the user/operator launches.

### Task 7: Post back Round 1 data and lock only a valid winner

- [ ] **Step 1: Export one comparable material report**

Use the same:

- data_start
- data_end
- attribution_window
- as_of
- source

for both arms.

- [ ] **Step 2: Dry-run the batch mapping**

Required columns/fields:

~~~csv
臂码,最终资产ID,素材ID,创意ID,数据开始日期,数据结束日期,归因窗口,数据截至时间,数据来源,消耗,展现,播放,3秒播放人数,完播人数,点击,新增A3人数,A3可转化人数,成交金额,平台ROI
~~~

The following rows must use the untouched R1A/R1B metric values exported by the platform, plus the exact final asset IDs returned in Task 6, one per row. Set 数据来源 to platform_export and use the report’s actual as_of time. Do not insert illustrative numbers into the real import file.

Call record_ad_metrics_batch with dry_run=True. Verify each row resolves the existing asset_role=final asset and its arm, all common contract fields are present, and normalized keys/units are correct; then rerun dry_run=False. Any attempt to create a placeholder asset is a blocker.

- [ ] **Step 3: Evaluate Round 1**

Call experiment_status. Expected:

- ranks by pooled new_a3 / a3_eligible_users;
- shows aggregation basis and A3 denominator;
- ROI, CTR, completion, and 3s are side/diagnostic evidence;
- blocks winner on open/mismatched windows, insufficient sample, or exposure/spend imbalance;
- otherwise returns can_lock=true and the leading arm.

- [ ] **Step 4: Lock the winner**

Call experiment_lock_winner only when can_lock=true. Expected baseline atomically stores route ID, N/P/V, framework version, and ownership-derived fields. Keep both arms and the evaluation snapshot.

### Task 8: Generate and test Round 2

- [ ] **Step 1: Request the next-version seed**

Call experiment_next_version_seed. Confirm it uses observed data shape:

- low 3s → opening_hook_3s or presentation motif;
- acceptable 3s but low completion → narrative/story/edit pace;
- acceptable completion but low A3 → proof/bridge/product action;
- high A3 but low ROI → retain planting winner and propose a separate harvest experiment;
- delivery imbalance → rerun the same variable.

It must not claim causality.

- [ ] **Step 2: Generate 2–3 Round 2 candidates**

Fix the entire Round 1 winner baseline. Change exactly one new variable and its allowlisted dependencies. Run variable diff before adoption.

- [ ] **Step 3: Render and post back through the same gates**

Repeat final MP4, whole-video prescreen, comparable launch, postback, status, and lock. Do not overwrite the Round 1 winner if Round 2 loses.

- [ ] **Step 4: Verify changelog**

The changelog must answer:

- Round 1 changed the composite content framework route and which route led;
- Round 2 changed one atomic variable and which value led;
- what data/window supported each decision;
- what remains uncertain;
- what the next legal variable is.

If experiment_status recommends a configured stop condition, show the evidence to the user. Only after explicit approval call experiment_converge with the matching reason; otherwise keep the experiment running and continue with the next legal single variable.

### Task 9: Rollout acceptance

- [ ] **Step 1: Verify lineage**

For each final asset call pipeline_get_asset_lineage. It must resolve:

SKU → matrix → selected audience → adopted portrait → adopted pack → route manifest → render candidate → experiment/round/arm → segment assets → final asset → postback metrics.

- [ ] **Step 2: Verify readiness**

At least two Round 1 arms have:

- adopted script;
- valid product hash;
- actual target model match;
- successful character sheets;
- final MP4 with audio;
- whole-video prescreen pass;
- arm code and postback template.

- [ ] **Step 3: Verify the learning loop**

Round 1 has a lockable or explicitly still-preliminary result, and Round 2 is either completed or generated as a valid one-variable work order. Failed experiments remain in history and do not erase the best baseline.

- [ ] **Step 4: Produce the operator handoff**

Report:

- current best baseline;
- exact winning/leading metrics and window;
- sample/delivery limitations;
- all final asset links and arm codes;
- next variable;
- stop condition or next observation date.

No source-code commit is created by this operational runbook.
