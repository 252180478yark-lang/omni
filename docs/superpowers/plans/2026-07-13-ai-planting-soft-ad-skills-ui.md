# AI Planting and Soft-Ad Skills plus SKU Pipeline UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a canonical ai-planting-video Skill, align the existing ai-soft-ad-video Skill to the shared contract and experiment loop, remove the duplicate Claude implementation, and expose route review, readiness, final MP4, and iteration evidence in the existing SKU Pipeline UI.

**Architecture:** Skills route and orchestrate but store no state. Both Skills call the same pipeline/experiment/rendering backend while keeping distinct content frameworks and north stars. The UI remains inside the existing SKU Pipeline page and extracts focused components from the current large page.tsx. All stages are derived from persisted artifacts.

**Tech Stack:** Codex Skill packages, Markdown progressive-disclosure references, Python static Skill tests, Next.js 14, React 18, TypeScript, Vitest/Testing Library, existing FastAPI proxies.

---

## Dependencies and execution preflight

- Complete the framework, experiment, and rendering plans first.
- Use the skill-creator Skill while implementing the new Skill package.
- The current canonical ai-soft-ad-video and compatibility soft-ad-ai-video directories are untracked user work. Inspect and preserve useful content; do not replace them wholesale.
- page.tsx currently contains uncommitted work that hides downstream tabs while leaving old code in place. Do not revert the file. Re-enable only the approved AI creative/A-B/formal render/lineage entries through reviewed hunks.
- Resolve every repository write path from the active isolated worktree using git rev-parse --show-toplevel. Absolute E:\agent\omni paths in the Files lists identify source locations only; commands must never use them as write targets from another worktree.

### Task 1: Write static routing and package-boundary tests

**Files:**

- Create: E:\agent\omni\tests\test_ai_planting_video_skill.py
- Create: E:\agent\omni\tests\test_ai_soft_ad_video_skill.py

- [ ] **Step 1: Define the expected canonical packages**

~~~python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLANTING = ROOT / ".agents/skills/ai-planting-video"
SOFT_AD = ROOT / ".agents/skills/ai-soft-ad-video"
SHIM = ROOT / ".claude/skills/soft-ad-ai-video/SKILL.md"


def test_canonical_skill_files_exist():
    assert (PLANTING / "SKILL.md").is_file()
    assert (PLANTING / "references/planting-framework-library.md").is_file()
    assert (PLANTING / "references/experiment-state-machine.md").is_file()
    assert (PLANTING / "references/content-contract-schema.md").is_file()
    assert (PLANTING / "agents/openai.yaml").is_file()
    assert (SOFT_AD / "SKILL.md").is_file()
~~~

Place the PLANTING assertions in test_ai_planting_video_skill.py and the SOFT_AD/SHIM assertions in test_ai_soft_ad_video_skill.py; the shared path snippet above is duplicated deliberately so each test file can run independently.

- [ ] **Step 2: Add trigger-boundary assertions**

Positive planting examples:

- 给 SKU-002 生成种草短视频
- 按 A3 目标给这个人群做深度种草
- 采纳 B 方案并正式出片
- 继续这条种草实验的下一版

Positive soft-ad examples:

- 给 SKU-002 做一条前三秒痛点开场的软广
- 这条主要看三秒率和完播率
- 用场景、情绪和故事测两版 O/A1 素材

Negative boundaries:

- “只写一个脚本” routes to script-writer, not either full-video Skill.
- “做收割/成交 A4” does not route to planting or soft-ad.
- “从零圈一个人群包” routes to crowd-sop.
- “反推竞品视频怎么拍” routes to video-reverse.

The two static tests should parse frontmatter descriptions and assert planting text contains A3/种草 while soft-ad contains 软广/三秒/完播, with no duplicate generic description that causes both to claim the same request.

- [ ] **Step 3: Assert progressive disclosure and shim behavior**

Test that:

- planting SKILL.md links all three references but does not duplicate their full bodies;
- the Skill says which phase reads which reference;
- missing references are blocking;
- the Claude shim is fewer than 40 nonblank lines;
- the shim does not duplicate the framework/state-machine content;
- the shim frontmatter does not advertise automatic “软广” triggering.

- [ ] **Step 4: Run tests and confirm RED**

~~~powershell
python -m pytest -q tests/test_ai_planting_video_skill.py tests/test_ai_soft_ad_video_skill.py
~~~

Expected: ai-planting-video does not exist and the current shim is still a full implementation.

- [ ] **Step 5: Capture a fresh-agent behavioral baseline**

In an isolated test stack with a mocked video provider, run two fresh subagents. Give one only “给测试 SKU 生成两条按 A3 优化的种草短视频。” Give the other only “给测试 SKU 做两版前三秒痛点不同、看三秒率和完播率的软广。” Do not mention the future Skill changes or expected workflows. Save both raw routing/tool traces outside the Skill directories as evaluation evidence.

Expected planting baseline failure: no ai-planting-video trigger and no complete route-manifest → final-MP4 → experiment-arm workflow. Expected soft-ad baseline failure: the existing Skill cannot produce shared-contract render candidates with a strict one-variable diff, final asset, and comparable experiment postback loop. These are the behavioral RED observations for Task 8’s forward tests.

### Task 2: Scaffold and write the canonical ai-planting-video Skill

**Files:**

- Create via scaffold: E:\agent\omni\.agents\skills\ai-planting-video\SKILL.md
- Create: E:\agent\omni\.agents\skills\ai-planting-video\references\planting-framework-library.md
- Create: E:\agent\omni\.agents\skills\ai-planting-video\references\experiment-state-machine.md
- Create: E:\agent\omni\.agents\skills\ai-planting-video\references\content-contract-schema.md
- Create: E:\agent\omni\.agents\skills\ai-planting-video\agents\openai.yaml

- [ ] **Step 1: Read the UI metadata contract**

Read completely:

~~~text
E:\agent\omni-system\brain\codex\skills\.system\skill-creator\references\openai_yaml.md
~~~

Use only the supported display_name, short_description, and default_prompt fields.

- [ ] **Step 2: Scaffold with the official script and deterministic metadata**

~~~powershell
$root = (git rev-parse --show-toplevel).Trim()
python E:\agent\omni-system\brain\codex\skills\.system\skill-creator\scripts\init_skill.py ai-planting-video --path "$root\.agents\skills" --resources references --interface 'display_name=AI 种草视频' --interface 'short_description=从已有 SKU 人群链路生成并迭代 A3 种草成片' --interface 'default_prompt=使用 $ai-planting-video 从已采用的 SKU 人群包链路生成可投放的种草短视频。'
~~~

Do not manually create the package before running init_skill.py.

- [ ] **Step 3: Write precise frontmatter**

Use this description:

~~~yaml
---
name: ai-planting-video
description: Use when老板要从已有 SKU/人群包链路生成纯 AI 种草短视频、以 A3 转化率为北极星做 4→2 框架预筛、正式 MP4 出片和投后单变量迭代；不用于软广播放优化、A4 收割、只写脚本、圈包或竞品反推。
---
~~~

- [ ] **Step 4: Keep SKILL.md as an orchestrator**

It must:

1. resolve SKU alias and adopted lineage;
2. build/validate content contract and product ref;
3. read planting-framework-library.md only for route creation/review;
4. call generate_creative_pack with kind=video_planting and workflow_mode=full_video;
5. persist/reuse route manifest and show 4→2 candidates;
6. require user confirmation before deriving/adopting at least two render candidates;
7. read experiment-state-machine.md only when attaching arms, evaluating data, or creating the next round;
8. call character sheets, segment generation with finalize=True, and whole-video prescreen;
9. return final asset and exact postback template;
10. read content-contract-schema.md only when building or diagnosing the contract.

The Skill must stop on the first ordered blocker and resume from the current artifact. It must never create its own status file or database.
Keep SKILL.md below 500 lines. Do not add README, installation guide, changelog, or quick-reference files.

- [ ] **Step 5: Write the framework reference**

planting-framework-library.md must contain:

- N1–N8, P1–P6, V1–V6 names and meanings;
- the exact compatibility matrix from framework-v1;
- P5 pure-AI prohibition and P6 evidence gate;
- 30/45-second functional skeleton;
- 4→2 route logic and stable sort;
- Round 1 content_framework_route rule;
- external evidence is a cold-start prior only; A3 postback is the only local winner truth;
- variable ownership and examples of legal/illegal framework tests.

Do not place implementation code or database state in this reference.
If the reference exceeds 100 lines, add a compact table of contents at the top.

- [ ] **Step 6: Write the experiment-state reference**

Include:

- experiment identity = SKU × actual audience pack × intent × track × north star;
- stages derived from artifacts: READY, ROUTE_REVIEW, SCRIPT_REVIEW, RENDERING, ASSEMBLING, PRESCREEN_REVIEW, READY_FOR_TEST, METRICS_PENDING, NEXT_ROUND_READY;
- new experiment Round 1 composite route sweep;
- later one-variable rounds;
- A3 winner policy and ROI side evidence;
- comparable windows, exposure/spend balance, minimum policy, and “current leader ≠ proven better” warning;
- winner baseline merge and failed-arm retention;
- next-variable mapping from three-second/completion/A3 loss;
- stop conditions and explicit user confirmation before new paid rendering;
- experiment_converge is called only after the user accepts a stop recommendation or explicitly says to stop; distillation alone never marks convergence.

- [ ] **Step 7: Write the content-contract reference**

Include all permanent facts, audience material, baseline fields, product/model requirements, artifact_role/render_eligible meanings, dependency allowlists, earliest-blocker order, and postback fields. State that unknown remains unknown and that route manifests cannot render or attach to arms.

- [ ] **Step 8: Regenerate agents/openai.yaml if the finished Skill changed its interface**

Use the official generator with explicit values:

~~~powershell
$root = (git rev-parse --show-toplevel).Trim()
python E:\agent\omni-system\brain\codex\skills\.system\skill-creator\scripts\generate_openai_yaml.py "$root\.agents\skills\ai-planting-video" --interface 'display_name=AI 种草视频' --interface 'short_description=从已有 SKU 人群链路生成并迭代 A3 种草成片' --interface 'default_prompt=使用 $ai-planting-video 从已采用的 SKU 人群包链路生成可投放的种草短视频。'
~~~

Ensure the default prompt invokes the Skill naturally and does not claim capabilities outside the workflow.

- [ ] **Step 9: Validate and commit**

~~~powershell
$root = (git rev-parse --show-toplevel).Trim()
python E:\agent\omni-system\brain\codex\skills\.system\skill-creator\scripts\quick_validate.py "$root\.agents\skills\ai-planting-video"
python -m pytest -q tests/test_ai_planting_video_skill.py
git add .agents/skills/ai-planting-video tests/test_ai_planting_video_skill.py
git diff --cached --check
git commit -m "feat: add canonical AI planting video skill"
~~~

### Task 3: Align canonical soft-ad Skill and replace the compatibility implementation with a shim

**Files:**

- Modify: E:\agent\omni\.agents\skills\ai-soft-ad-video\SKILL.md
- Modify: E:\agent\omni\.agents\skills\ai-soft-ad-video\references\state-machine.md
- Create: E:\agent\omni\.agents\skills\ai-soft-ad-video\references\soft-ad-framework-library.md
- Create: E:\agent\omni\.agents\skills\ai-soft-ad-video\references\content-contract-schema.md
- Modify: E:\agent\omni\.agents\skills\ai-soft-ad-video\agents\openai.yaml
- Modify: E:\agent\omni\.claude\skills\soft-ad-ai-video\SKILL.md
- Modify: E:\agent\omni\.claude\skills\soft-ad-ai-video\agents\openai.yaml
- Modify: E:\agent\omni\tests\test_ai_soft_ad_video_skill.py

- [ ] **Step 1: Tighten the soft-ad trigger**

Use a description centered on O/A1, soft insertion, first-three-second retention, completion rate, and playback-quality A/B. Explicitly exclude A3 deep planting, harvest, script-only requests, and audience-pack creation.

- [ ] **Step 2: Preserve soft-ad’s own content library**

soft-ad-framework-library.md must define its variables without copying planting N/P/V:

- opening_hook_3s: visible pain, emotion action, scene conflict, result curiosity, authentic question;
- pain_point;
- emotion;
- scene.semantic and execution instances;
- story_structure;
- selling_point;
- product_entry;
- visual_vector;
- text presentation;
- sound_vector/BGM;
- story_pace and edit_pace.

The first three seconds jointly specify pain, emotion, scene, and visual vector. A round still sweeps only one registered variable; any necessary linked change must be in the allowlist. Primary metric is completion_rate with configured play_3s_rate guardrail. Raw plays are scale diagnostics, not winner truth.

- [ ] **Step 3: Reuse the shared renderer and experiment tail**

Update state-machine.md so soft-ad:

- requires a product reference even if the first three seconds contain no product;
- creates adopted render candidates and experiment arms;
- calls generate_character_sheets and generate_video_segments(finalize=True);
- requires final whole-video prescreen;
- waits for playback postbacks;
- locks a winner only through the shared evaluator;
- produces the next one-variable round.

It must not adopt planting’s A3 metric or N/P/V registry.

- [ ] **Step 4: Replace the Claude directory with a compatibility forwarder**

Keep the file under 40 nonblank lines. It should say this package exists only for explicit legacy invocation, then instruct the runtime to load the repository-root .agents/skills/ai-soft-ad-video/SKILL.md and follow it. Remove duplicated business rules and automatic soft-ad trigger wording.

- [ ] **Step 5: Regenerate canonical soft-ad UI metadata**

After reading the same openai_yaml.md contract, run:

~~~powershell
$root = (git rev-parse --show-toplevel).Trim()
python E:\agent\omni-system\brain\codex\skills\.system\skill-creator\scripts\generate_openai_yaml.py "$root\.agents\skills\ai-soft-ad-video" --interface 'display_name=AI 软广视频' --interface 'short_description=生成并按三秒率和完播率迭代 O/A1 软广成片' --interface 'default_prompt=使用 $ai-soft-ad-video 从已有 SKU 人群链路生成并迭代软广短视频。'
~~~

The compatibility package metadata must identify itself as a legacy forwarder and set:

~~~yaml
policy:
  allow_implicit_invocation: false
~~~

It must not advertise a second automatic trigger. Quote all openai.yaml string values.

- [ ] **Step 6: Validate both packages and commit**

~~~powershell
$root = (git rev-parse --show-toplevel).Trim()
python E:\agent\omni-system\brain\codex\skills\.system\skill-creator\scripts\quick_validate.py "$root\.agents\skills\ai-soft-ad-video"
python E:\agent\omni-system\brain\codex\skills\.system\skill-creator\scripts\quick_validate.py "$root\.agents\skills\ai-planting-video"
python -m pytest -q tests/test_ai_planting_video_skill.py tests/test_ai_soft_ad_video_skill.py
git add .agents/skills/ai-soft-ad-video/SKILL.md .agents/skills/ai-soft-ad-video/references/state-machine.md .agents/skills/ai-soft-ad-video/references/soft-ad-framework-library.md .agents/skills/ai-soft-ad-video/references/content-contract-schema.md .agents/skills/ai-soft-ad-video/agents/openai.yaml .claude/skills/soft-ad-ai-video/SKILL.md .claude/skills/soft-ad-ai-video/agents/openai.yaml
git add -p tests/test_ai_soft_ad_video_skill.py
git diff --cached --check
git commit -m "refactor: align soft-ad skill with shared video loop"
~~~

### Task 4: Extend the shared content contract to formal soft-ad candidates

**Files:**

- Create: E:\agent\omni\services\knowledge-engine\config\soft_ad_frameworks\framework-v1.json
- Create: E:\agent\omni\services\knowledge-engine\app\services\soft_ad_framework_registry.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_soft_ad_content_contract.py
- Modify: E:\agent\omni\services\knowledge-engine\app\mcp\tools\media.py
- Modify: E:\agent\omni\services\knowledge-engine\app\routers\mcp_exec.py
- Modify: E:\agent\omni\services\knowledge-engine\config\prompts\creative_pack.video_soft_ad.system.md
- Modify: E:\agent\omni\services\knowledge-engine\config\prompts\creative_pack.user.md

- [ ] **Step 1: Write failing formal soft-ad tests**

Test:

- kind=video_soft_ad and workflow_mode=full_video builds the same permanent-fact/audience/product/model contract used by planting;
- the workflow never splits O and A1 into separate experiments;
- a new experiment defaults to one declared sweep, normally opening_hook_3s, and produces 2–3 render candidates;
- every pair differs only in the swept variable and its allowlisted presentation paths;
- changing pain point, scene semantics, story, selling point, or product hash while sweeping the hook returns multi_variable_drift;
- soft-ad permits a later product entry but still requires a validated product reference;
- output contains the first-three-second pain/emotion/scene/visual plan, full story, selling-point bridge, product entry/actions, text/visual/sound vectors, and variable-difference card;
- price, discount, hard CTA, and planting A3 proof structure remain forbidden;
- candidate scripts persist artifact_role=render_candidate, render_eligible=true, intent=soft_ad, framework version, and target video model.

- [ ] **Step 2: Run the formal soft-ad tests and confirm RED**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_soft_ad_content_contract.py"
~~~

Expected: collection or assertions fail because the registry and full-video soft-ad contract path do not exist.

- [ ] **Step 3: Create soft-ad-framework-v1**

The registry must be distinct from planting N/P/V and include:

~~~json
{
  "version": "soft-ad-framework-v1",
  "intent": "soft_ad",
  "audience_stages": ["O", "A1"],
  "default_sweep": "opening_hook_3s",
  "variables": {
    "opening_hook_3s": [
      "visible_pain",
      "emotion_action",
      "scene_conflict",
      "result_curiosity",
      "authentic_question"
    ],
    "pain_point": [],
    "emotion": [],
    "scene": [],
    "story_structure": [],
    "selling_point": [],
    "product_entry": [],
    "visual_vector": [],
    "text_vector": [],
    "sound_vector": [],
    "story_pace": [],
    "edit_pace": []
  }
}
~~~

Empty arrays mean values come from the SKU/audience content contract and experiment history, not a universal canned list. Define dependency ownership explicitly. opening_hook_3s may own the opening shot/text presentation needed to express the hook, but not the pain, semantic scene, selling point, product hash, intent, duration, or target model.

- [ ] **Step 4: Implement the formal workflow**

Extend generate_creative_pack so:

- workflow_mode=script remains backward compatible;
- workflow_mode=full_video with video_planting keeps the manifest flow;
- workflow_mode=full_video with video_soft_ad builds formal candidates directly from one swept variable and experiment_context;
- product_refs, target model, actual audience pack, and content contract are required;
- every generated candidate passes validate_single_variable_diff before persistence;
- content vector remains side evidence only.

Do not create a soft-ad route manifest or copy planting framework IDs.

- [ ] **Step 5: Align the prompt and validator**

The prompt must produce one complete 25–30 second soft-ad per candidate with:

- 0–3 second hook card combining the selected hook, inherited pain, emotion action, scene, and opening visual vector;
- scene/story continuation;
- natural selling-point and pain bridge;
- light product entry and real use action;
- no price or strong purchase CTA;
- complete variable-difference card and metrics JSON matching the validator.

- [ ] **Step 6: Forward REST fields and run tests**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_soft_ad_content_contract.py tests/test_content_contract.py tests/test_mcp_prompts.py tests/test_creative_pack_batch.py"
~~~

Expected: formal soft-ad candidates pass and existing script-mode callers remain unchanged.

- [ ] **Step 7: Commit**

~~~powershell
git add services/knowledge-engine/config/soft_ad_frameworks/framework-v1.json services/knowledge-engine/app/services/soft_ad_framework_registry.py services/knowledge-engine/tests/test_soft_ad_content_contract.py
git add -p services/knowledge-engine/app/mcp/tools/media.py services/knowledge-engine/app/routers/mcp_exec.py services/knowledge-engine/config/prompts/creative_pack.video_soft_ad.system.md services/knowledge-engine/config/prompts/creative_pack.user.md
git diff --cached --check
git commit -m "feat: add formal soft-ad experiment candidates"
~~~

### Task 5: Add typed UI models and backend proxy coverage

**Files:**

- Create: E:\agent\omni\frontend\src\app\sku-pipeline\ai-video-types.ts
- Create: E:\agent\omni\frontend\src\app\api\omni\sku-pipeline\video-assemble\route.ts
- Modify: E:\agent\omni\frontend\src\app\api\omni\sku-pipeline\creative-pack\route.ts
- Modify: E:\agent\omni\frontend\src\app\api\omni\sku-pipeline\video-generate\route.ts
- Create: E:\agent\omni\frontend\tests\sku-pipeline\ai-video-api.test.ts

- [ ] **Step 1: Write failing proxy tests**

Assert creative-pack forwards workflow_mode, product_refs, route_manifest_id, selected_route_ids, route_shortlist_target, and reroute_revision. Assert video-generate forwards experiment_arm_id, target model, product/character refs, finalize, finalize_only, and audio_track. Assert video-assemble calls the same backend video endpoint with finalize_only=true.

- [ ] **Step 2: Define UI types**

~~~typescript
export type AiVideoStage =
  | 'READY'
  | 'ROUTE_REVIEW'
  | 'SCRIPT_REVIEW'
  | 'RENDERING'
  | 'ASSEMBLING'
  | 'PRESCREEN_REVIEW'
  | 'READY_FOR_TEST'
  | 'METRICS_PENDING'
  | 'NEXT_ROUND_READY'

export interface RouteCandidate {
  route_id: string
  narrative_framework: string
  proof_framework: string
  presentation_motif: string
  route_fit_total: number
  triangle_score: number
  vector_score: number
  hard_gate: { ok: boolean; error?: string }
  excluded_reasons: string[]
  default_selected: boolean
}

export interface FinalVideoAsset {
  asset_id: string
  file_url: string
  experiment_arm_id: string
  generation_meta: {
    asset_role: 'final'
    segment_asset_ids: string[]
    probe: Record<string, number | string>
    ready_for_prescreen: boolean
  }
  visual_prescreen?: Record<string, unknown>
}
~~~

- [ ] **Step 3: Implement proxies and run tests**

~~~powershell
npm --prefix frontend run test:unit -- tests/sku-pipeline/ai-video-api.test.ts
~~~

Expected: pass.

- [ ] **Step 4: Commit**

~~~powershell
git add frontend/src/app/sku-pipeline/ai-video-types.ts frontend/src/app/api/omni/sku-pipeline/video-assemble/route.ts frontend/tests/sku-pipeline/ai-video-api.test.ts
git add -p frontend/src/app/api/omni/sku-pipeline/creative-pack/route.ts frontend/src/app/api/omni/sku-pipeline/video-generate/route.ts
git diff --cached --check
git commit -m "feat: add AI video workflow API contracts"
~~~

### Task 6: Build readiness, route review, and final-video components

**Files:**

- Create: E:\agent\omni\frontend\src\app\sku-pipeline\AiVideoReadinessPanel.tsx
- Create: E:\agent\omni\frontend\src\app\sku-pipeline\RouteManifestPanel.tsx
- Create: E:\agent\omni\frontend\src\app\sku-pipeline\FinalVideoAssetCard.tsx
- Create: E:\agent\omni\frontend\tests\sku-pipeline\AiVideoReadinessPanel.test.tsx
- Create: E:\agent\omni\frontend\tests\sku-pipeline\RouteManifestPanel.test.tsx
- Create: E:\agent\omni\frontend\tests\sku-pipeline\FinalVideoAssetCard.test.tsx

- [ ] **Step 1: Write component tests first**

Readiness tests:

- show lineage/portrait/pack/product/model facts;
- show only the earliest blocker as the primary action;
- product mismatch and route-manifest non-renderability disable render;
- show “向量只用于投前排序，A3/投后北极星才判 winner.”

Route tests:

- show up to four cards and default Top 2 checked;
- show N/P/V, compatibility, evidence eligibility, route/triangle/vector scores, and exclusions;
- require at least two eligible selections;
- show route_pool_limited when only 2–3 survive;
- show OutputFeedback.

Final asset tests:

- segment assets stay in a collapsible diagnostic section;
- only asset_role=final appears as “最终成片”;
- render the absolute media URL, probe result, arm code, prescreen gate, and postback fields;
- no audio/invalid probe cannot show READY_FOR_TEST;
- show OutputFeedback.

- [ ] **Step 2: Implement focused components**

Do not add another page. Components receive typed props and callbacks; they do not call the database directly.

- [ ] **Step 3: Run component tests and commit**

~~~powershell
npm --prefix frontend run test:unit -- tests/sku-pipeline/AiVideoReadinessPanel.test.tsx tests/sku-pipeline/RouteManifestPanel.test.tsx tests/sku-pipeline/FinalVideoAssetCard.test.tsx
git add frontend/src/app/sku-pipeline/AiVideoReadinessPanel.tsx frontend/src/app/sku-pipeline/RouteManifestPanel.tsx frontend/src/app/sku-pipeline/FinalVideoAssetCard.tsx frontend/tests/sku-pipeline
git diff --cached --check
git commit -m "feat: add AI video review and final asset components"
~~~

### Task 7: Integrate components into the existing SKU Pipeline page

**Files:**

- Modify: E:\agent\omni\frontend\src\app\sku-pipeline\page.tsx
- Modify: E:\agent\omni\frontend\src\app\sku-pipeline\LineageTree.tsx
- Create: E:\agent\omni\frontend\tests\sku-pipeline\sku-pipeline-ai-video-flow.test.tsx

- [ ] **Step 1: Add an integration test around visible tabs and actions**

Assert:

- 创意素材, A/B实验, 正式出片, and 血缘 are visible when their prerequisites exist;
- 真人编导 brief remains hidden from the pure-AI main path;
- no existing user edit is globally reverted;
- upload sends sku_id and confirmed_by_user;
- both i2v and t2v paths send product refs;
- route review → selected candidates → script review → render → final asset works through mocked APIs;
- metrics panel shows A3 for planting and completion + 3s guardrail for soft-ad;
- winner/new-round controls use existing experiment APIs.

- [ ] **Step 2: Integrate by narrow hunks**

Insert:

- contract/readiness panel in the creative output area;
- route manifest cards before full script candidates;
- single-variable difference card next to experiment round controls;
- product/model validation state before character/render buttons;
- final MP4 card as the primary render result;
- segment cards as diagnostics;
- baseline/changelog and next-variable work order in the existing A/B board.

All new output areas retain OutputFeedback.

- [ ] **Step 3: Update LineageTree**

Add generation_meta to the asset type. Label:

- asset_role=final → 最终成片
- asset_role=segment → 视频段 N
- character_sheet → 定妆照

Do not display a final asset as “视频 #?”.

- [ ] **Step 4: Run tests, typecheck, and build**

~~~powershell
npm --prefix frontend run test:unit -- tests/sku-pipeline
npm --prefix frontend exec tsc -- --noEmit
npm --prefix frontend run build
~~~

Expected: all pass.

- [ ] **Step 5: Commit only reviewed UI hunks**

~~~powershell
git add -p frontend/src/app/sku-pipeline/page.tsx frontend/src/app/sku-pipeline/LineageTree.tsx
git add frontend/tests/sku-pipeline/sku-pipeline-ai-video-flow.test.tsx
git diff --cached --check
git commit -m "feat: expose AI video experiment loop in SKU pipeline"
~~~

### Task 8: Full Skill and UI acceptance

**Files:**

- Test: all files touched in this plan

- [ ] **Step 1: Validate Skill packages**

~~~powershell
$root = (git rev-parse --show-toplevel).Trim()
python E:\agent\omni-system\brain\codex\skills\.system\skill-creator\scripts\quick_validate.py "$root\.agents\skills\ai-soft-ad-video"
python E:\agent\omni-system\brain\codex\skills\.system\skill-creator\scripts\quick_validate.py "$root\.agents\skills\ai-planting-video"
python -m pytest -q tests/test_ai_planting_video_skill.py tests/test_ai_soft_ad_video_skill.py
~~~

- [ ] **Step 2: Run frontend verification**

~~~powershell
npm --prefix frontend run test:unit -- tests/sku-pipeline
npm --prefix frontend exec tsc -- --noEmit
npm --prefix frontend run build
~~~

- [ ] **Step 3: Run backend smoke tests needed by the UI**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_planting_route_manifest.py tests/test_soft_ad_content_contract.py tests/test_experiment_evaluation.py tests/test_video_assembly.py tests/test_experiment_prescreen_final.py"
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
~~~

- [ ] **Step 4: Manually verify trigger boundaries**

Invoke one planting phrase, one soft-ad phrase, one script-only phrase, one harvest phrase, and one crowd-SOP phrase. Record the selected Skill/tool and ensure no pair double-triggers.

- [ ] **Step 5: Forward-test both Skills in an isolated test stack**

Use fresh subagents with only the Skill path and one natural request. Do not give them the expected route, diagnosis, or intended answer. Point the stack at a test database and mocked video provider so no production records, paid generation, or real ads are touched.

Run at least:

- “Use $ai-planting-video at the active worktree’s .agents/skills/ai-planting-video to handle: 给测试 SKU 生成两条按 A3 优化的种草短视频。”
- “Use $ai-soft-ad-video at the active worktree’s .agents/skills/ai-soft-ad-video to handle: 给测试 SKU 做两版前三秒痛点不同、看三秒率和完播率的软广。”
- “Use $ai-planting-video at the active worktree’s .agents/skills/ai-planting-video to handle: 只给这个 SKU 写一个脚本。”

Expected: the first two follow their own workflows; the third declines full-video routing in favor of script-writer. Review raw traces and outputs, revise the Skill if a result depends on leaked context, then rerun quick_validate.py and the static tests.

- [ ] **Step 6: Commit any acceptance-only fixes**

Use hunk-level staging and commit:

~~~text
fix: finish AI video skill and UI acceptance
~~~
