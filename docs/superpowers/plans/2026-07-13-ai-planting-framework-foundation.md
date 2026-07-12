# AI Planting Framework Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic content contract, versioned N/P/V planting framework registry, route manifest, legacy migration, and 4→2 route-selection workflow without creating a second pipeline state machine.

**Architecture:** Existing pipeline records remain the source of truth. A Pydantic content contract normalizes inherited SKU, audience, portrait, pack, product, and experiment facts. A JSON registry and pure Python router determine eligible N/P/V routes; the LLM only instantiates already-selected routes. Route manifests and render candidates reuse pipeline.scripts with explicit artifact roles.

**Tech Stack:** Python 3.12, Pydantic 2, asyncpg/PostgreSQL JSONB, pytest, existing MCP generate_creative_pack tool, Markdown prompt templates.

---

## Execution preflight

The current E:\agent\omni worktree contains extensive user-owned uncommitted upgrades, including files this plan modifies. Do not stash, reset, checkout, or overwrite them. Before implementation:

- [ ] Run git status --short and git diff --name-only.
- [ ] Use superpowers:using-git-worktrees.
- [ ] If the clean worktree created from HEAD does not contain required uncommitted prerequisites such as triangle_match.py, vector_presets.py, or the current media.py changes, stop and ask the user to choose whether to commit those prerequisites or authorize a reviewed patch transfer.
- [ ] During implementation, stage only named files or reviewed hunks with git add -p; never stage the whole dirty tree.

This plan is the dependency root for the experiment, rendering, Skill/UI, and SKU-002 rollout plans.

### Task 1: Lock the content-contract schema and upstream field bridge

**Files:**

- Create: E:\agent\omni\services\knowledge-engine\app\services\content_contract.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_content_contract.py
- Modify: E:\agent\omni\services\knowledge-engine\tests\test_audience_content_bridge.py
- Modify: E:\agent\omni\services\knowledge-engine\app\mcp\tools\media.py

- [ ] **Step 1: Write failing schema and bridge tests**

Create tests covering:

~~~python
from copy import deepcopy

from app.services.content_contract import (
    build_content_contract,
    validate_content_contract,
    validate_single_variable_diff,
)


def contract_fixture() -> dict:
    contract = build_content_contract(
        permanent_facts={
            "sku_id": "SKU-X",
            "intent": "planting",
            "kind": "video_planting",
            "duration_seconds": 30,
            "aspect_ratio": "9:16",
            "target_video_model": "seedance",
        },
        audience_material={
            "true_need": ["安心做好一顿家常饭"],
            "pain_point": ["不知道如何判断调味品是否适合长期使用"],
            "trigger_scene": ["工作日晚饭"],
        },
    )
    contract["baseline"] = {
        "opening_hook_3s": "痛点直入",
        "selling_point": "已继承卖点 A",
    }
    return contract


def test_contract_preserves_structured_audience_fields():
    contract = build_content_contract(
        permanent_facts={
            "sku_id": "SKU-367991-0002",
            "matrix_run_id": "matrix-1",
            "audience_record_id": "record-1",
            "portrait_id": "portrait-1",
            "audience_pack_id": "pack-1",
            "intent": "planting",
            "kind": "video_planting",
            "duration_seconds": 30,
            "aspect_ratio": "9:16",
            "target_video_model": "seedance",
        },
        audience_material={
            "true_need": ["一顿家常饭也想吃得安心、顺口"],
            "pain_point": ["提鲜与配料负担之间难取舍"],
            "trigger_scene": ["工作日晚饭"],
            "hesitation": ["担心只讲概念、不好吃"],
            "blockers": ["不知道用什么事实判断"],
            "emotion_base": ["想把家常饭照顾好"],
            "positive_triggers": ["具体可见的使用结果"],
            "negative_triggers": ["夸张健康焦虑"],
            "algorithm_signals": {
                "text": ["家常饭", "配料选择"],
                "visual": ["自然厨房", "真实烹调"],
                "sound": ["锅铲声", "轻旁白"],
            },
            "selling_point_links": [{
                "pain_point": "提鲜与配料负担之间难取舍",
                "selling_point": "有机本酿造特级酱油",
                "scene": "工作日晚饭",
                "true_need": "安心且顺口",
            }],
        },
    )
    assert contract["audience_material"]["pain_point"][0] == "提鲜与配料负担之间难取舍"
    assert contract["audience_material"]["algorithm_signals"]["visual"] == ["自然厨房", "真实烹调"]
    assert validate_content_contract(contract)["ok"] is True


def test_missing_fact_is_marked_unknown_not_fabricated():
    contract = build_content_contract(
        permanent_facts={"sku_id": "SKU-X"},
        audience_material={},
    )
    assert contract["audience_material"]["true_need"] == {"status": "missing", "values": []}
    assert "true_need" in validate_content_contract(contract)["missing_fields"]


def test_single_variable_diff_rejects_unowned_semantic_change():
    baseline = contract_fixture()
    arm_b = deepcopy(baseline)
    arm_b["baseline"]["opening_hook_3s"] = "结果前置"
    arm_b["baseline"]["selling_point"] = "另一卖点"
    result = validate_single_variable_diff(
        baseline,
        arm_b,
        swept_variable="opening_hook_3s",
    )
    assert result == {
        "ok": False,
        "error": "multi_variable_drift",
        "changed_paths": ["baseline.opening_hook_3s", "baseline.selling_point"],
        "unowned_paths": ["baseline.selling_point"],
    }
~~~

Extend test_audience_content_bridge.py so the old “first 36 matching lines” bridge fails the test. Assert extraction is by headings/structured fields and retains true_need, pain_point, trigger_scene, hesitation, blockers, all three algorithm-signal tracks, and selling-point links.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_content_contract.py tests/test_audience_content_bridge.py"
~~~

Expected: collection fails because content_contract.py and the new structured bridge do not exist.

- [ ] **Step 3: Implement the Pydantic schema and deterministic diff**

Use Pydantic models for validation and return JSON-safe dictionaries with model_dump(mode="json"). Keep these four top-level sections:

~~~python
class ContentContract(BaseModel):
    schema_version: Literal["content-contract-v1"]
    permanent_facts: PermanentFacts
    audience_material: AudienceMaterial
    baseline: dict[str, Any] = Field(default_factory=dict)
    experiment: ExperimentContract | None = None
    artifact_role: Literal["route_manifest", "render_candidate", "legacy"] | None = None
    render_eligible: bool = False
~~~

Permanent facts must include lineage IDs, evidence-qualified selling points, actual audience-pack portrait source, product-reference validation, intent/kind/duration/aspect ratio, requested target video model/profile version, framework-library version, and production track. Unknown source values stay explicit missing/unknown objects.

Implement deterministic ownership:

~~~python
DEPENDENCY_ALLOWLIST = {
    "content_framework_route": {
        "baseline.content_framework_route",
        "baseline.framework_library_version",
        "baseline.narrative_framework",
        "baseline.proof_framework",
        "baseline.presentation_motif",
        "baseline.story_structure",
        "baseline.timeline_order",
        "baseline.transition_text",
        "baseline.scene.execution_instances",
        "baseline.proof_method",
        "baseline.proof_segment_structure",
        "baseline.product_action.proof_execution",
        "baseline.production_cast_form",
        "baseline.visual_vector",
        "baseline.text_vector.presentation",
        "baseline.sound_vector",
        "baseline.camera_signal",
        "baseline.story_pace",
        "baseline.edit_pace",
    },
    "narrative_framework": {
        "baseline.narrative_framework",
        "baseline.story_structure",
        "baseline.timeline_order",
        "baseline.transition_text",
        "baseline.scene.execution_instances",
        "baseline.story_pace",
    },
    "proof_framework": {
        "baseline.proof_framework",
        "baseline.proof_method",
        "baseline.proof_segment_structure",
        "baseline.product_action.proof_execution",
    },
    "presentation_motif": {
        "baseline.presentation_motif",
        "baseline.production_cast_form",
        "baseline.visual_vector",
        "baseline.text_vector.presentation",
        "baseline.sound_vector",
        "baseline.camera_signal",
        "baseline.edit_pace",
    },
    "opening_hook_3s": {
        "baseline.opening_hook_3s",
        "baseline.opening_frame",
        "baseline.opening_action_0_3s",
        "baseline.opening_pace_0_3s",
    },
    "idea_seed": {
        "baseline.idea_seed",
        "baseline.scene.execution_instances",
    },
    "pain_point": {
        "baseline.pain_point",
        "baseline.pain_point_expression",
    },
    "emotion": {
        "baseline.emotion",
        "baseline.performance_emotion",
        "baseline.emotion_wording",
        "baseline.sound_vector.music_emotion",
    },
    "scene": {
        "baseline.scene.semantic",
        "baseline.scene.execution_instances",
    },
    "story_structure": {
        "baseline.story_structure",
        "baseline.timeline_order",
        "baseline.transition_text",
        "baseline.structure_pace",
    },
    "selling_point": {
        "baseline.selling_point",
        "baseline.selling_point_evidence_refs",
    },
    "pain_selling_point_bridge": {
        "baseline.pain_selling_point_bridge",
        "baseline.bridge_expression",
    },
    "value_proposition_route": {
        "baseline.value_proposition_route",
        "baseline.pain_point",
        "baseline.pain_point_expression",
        "baseline.selling_point",
        "baseline.selling_point_evidence_refs",
        "baseline.proof_framework",
        "baseline.proof_method",
        "baseline.proof_segment_structure",
        "baseline.product_action.core_use",
        "baseline.product_action.proof_execution",
        "baseline.pain_selling_point_bridge",
        "baseline.bridge_expression",
    },
    "scene_need_route": {
        "baseline.scene_need_route",
        "baseline.scene.semantic",
        "baseline.scene.execution_instances",
        "baseline.true_need",
        "baseline.pain_point",
        "baseline.pain_point_expression",
        "baseline.pain_selling_point_bridge",
        "baseline.bridge_expression",
    },
    "proof_method": {
        "baseline.proof_method",
        "baseline.product_action.proof_execution",
    },
    "product_entry": {
        "baseline.product_entry",
        "baseline.product_entry_shot",
    },
    "product_action": {
        "baseline.product_action.core_use",
    },
    "visual_vector": {
        "baseline.visual_vector.actor_signal",
        "baseline.visual_vector.environment_signal",
        "baseline.visual_vector.camera_signal",
        "baseline.visual_vector.product_signal",
    },
    "text_vector": {
        "baseline.text_vector.presentation",
    },
    "sound_vector": {
        "baseline.sound_vector",
    },
    "story_pace": {
        "baseline.story_pace",
    },
    "edit_pace": {
        "baseline.edit_pace",
    },
    "target_model": {
        "permanent_facts.target_video_model",
        "permanent_facts.model_profile_version",
    },
    "prompt_structure": {
        "permanent_facts.ai_generation.prompt_structure",
    },
    "realism_anchor": {
        "permanent_facts.ai_generation.realism_anchor",
    },
    "character_ref": {
        "permanent_facts.character_reference_hashes",
    },
    "negative_words": {
        "permanent_facts.ai_generation.negative_words",
    },
    "motion_style": {
        "baseline.visual_vector.camera_signal",
        "baseline.camera_signal",
    },
    "production_mode": {
        "permanent_facts.production_mode",
    },
}
~~~

Permanent facts, pain point, true need, selling point, scene.semantic, role_semantics, text_vector.semantic, product_action.core_use, duration, aspect ratio, product hash, intent, and target model are never implicitly owned by a framework change. value_proposition_route and scene_need_route are the only declared composite exceptions for their listed linked baseline selections; they may select a different already-grounded need/pain/selling-point combination from audience_material and selling-point evidence, but cannot edit those source facts or invent new evidence. Their round/changelog must be labeled composite rather than atomic. target_model, prompt_structure, realism_anchor, character_ref, negative_words, and motion_style are explicit technical-sweep exceptions only on track=ai_video; production_mode is allowed only on track=mixed. Each may change only its listed paths while every other content and product-semantic path stays fixed. Registry tests must assert every selectable canonical standard, composite, and AI-extra swept variable above has a nonempty explicit entry; legacy aliases are normalized before lookup, and unknown variables fail closed rather than receiving blanket permission.

Define one shared ordered blocker contract and a first_blocker helper so later plans do not invent local precedence:

~~~python
WORKFLOW_BLOCKER_ORDER = (
    "upstream_content_incomplete",
    "portrait_confidence_low",
    "missing_product_ref",
    "product_ref_invalid",
    "product_ref_sku_mismatch",
    "framework_route_incompatible",
    "proof_evidence_missing",
    "insufficient_eligible_routes",
    "route_manifest_not_renderable",
    "target_model_mismatch",
    "multi_variable_drift",
    "triangle_match_low",
    "character_sheet_failed",
    "product_refs_dropped",
    "segment_generation_failed",
    "assembly_failed",
    "final_media_invalid",
    "prescreen_failed",
    "attribution_window_open",
    "insufficient_sample",
    "exposure_imbalance",
)
~~~

Unit-test that first_blocker always returns the earliest present code. Route-level framework/evidence exclusions remain attached to their route; they become a top-level blocker only when forced by the user or when fewer than two eligible routes remain.

- [ ] **Step 4: Replace head truncation with structured extraction**

In media.py, preserve the existing compatibility entry point but have it call a field parser. Parse explicit headings and structured JSON first; use bounded heading sections as the fallback. Do not recover missing data from unrelated leading lines.

- [ ] **Step 5: Run tests and confirm GREEN**

Run the same focused command. Expected: all tests pass.

- [ ] **Step 6: Commit only this task**

~~~powershell
git add -p services/knowledge-engine/app/mcp/tools/media.py
git add services/knowledge-engine/app/services/content_contract.py services/knowledge-engine/tests/test_content_contract.py services/knowledge-engine/tests/test_audience_content_bridge.py
git diff --cached --check
git commit -m "feat: add structured planting content contract"
~~~

### Task 2: Add schema migration 068 and persistence contracts

**Files:**

- Create: E:\agent\omni\migrations\068_ai_content_contract.sql
- Create: E:\agent\omni\services\knowledge-engine\tests\test_content_contract_persistence.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_route_manifest_persistence.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_pack_portrait_binding.py
- Modify: E:\agent\omni\services\knowledge-engine\tests\test_portrait_lineage.py
- Modify: E:\agent\omni\services\knowledge-engine\app\services\pipeline_lineage.py
- Modify: E:\agent\omni\services\knowledge-engine\app\mcp\tools\pipeline.py
- Modify: E:\agent\omni\services\knowledge-engine\app\routers\mcp_exec.py
- Modify: E:\agent\omni\services\knowledge-engine\app\mcp\doctor.py

- [ ] **Step 1: Write failing persistence tests**

Test that save_creative_pack accepts content_contract and target_video_model, persists an explicit empty scenes list, and returns persistence failure as a top-level error. Test two manifest revisions with the same manifest key and ensure an exact retry reuses the existing row rather than silently inserting a duplicate. Extend portrait-lineage coverage so save/get audience pack round-trips audience_portrait_id and execution_meta without changing pack_md or status.

- [ ] **Step 2: Create the additive migration**

Use migration number 068 only in this plan:

~~~sql
ALTER TABLE pipeline.scripts
    ADD COLUMN IF NOT EXISTS content_contract JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS target_video_model TEXT;

ALTER TABLE pipeline.audience_packs
    ADD COLUMN IF NOT EXISTS audience_portrait_id UUID
        REFERENCES pipeline.audience_portraits(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS execution_meta JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_scripts_artifact_role
    ON pipeline.scripts ((content_contract ->> 'artifact_role'))
    WHERE content_contract ? 'artifact_role';

CREATE UNIQUE INDEX IF NOT EXISTS uq_scripts_route_manifest_revision
    ON pipeline.scripts (
        sku_id,
        kind,
        (content_contract ->> 'manifest_key'),
        (content_contract ->> 'manifest_revision')
    )
    WHERE content_contract ->> 'artifact_role' = 'route_manifest'
      AND content_contract ? 'manifest_key'
      AND content_contract ? 'manifest_revision';
~~~

Add comments explaining that artifact_role is not a new state machine and route manifests remain status=draft.
The manifest service must always persist manifest_revision as a decimal string starting at "1".

- [ ] **Step 3: Extend save_creative_pack**

Add keyword-only parameters content_contract: dict | None and target_video_model: str | None. Change both truthiness fallbacks below to identity checks:

~~~python
if scenes is None:
    scenes = parsed_scenes
if character_sheets is None:
    character_sheets = parsed_character_sheets
~~~

This preserves deliberate empty arrays for a non-renderable manifest.

- [ ] **Step 4: Extend audience-pack persistence**

Add optional audience_portrait_id and execution_meta parameters to save_audience_pack, return both from list/get methods, and update only those metadata fields when binding a newly adopted portrait to an already adopted pack. Do not rewrite pack_md or create a second pack automatically.

- [ ] **Step 5: Add an audited pack-portrait binding surface**

Add pipeline_bind_pack_portrait(audience_pack_id, portrait_id, actual_portrait_source, actual_portrait_sha256). It must verify:

- pack and portrait both exist and are adopted;
- sku_id and audience_record_id match;
- the source/hash are nonempty;
- only audience_portrait_id and execution_meta.content_inheritance are updated.

Expose the same arguments through /api/v1/mcp/exec/pipeline_bind_pack_portrait and add the MCP tool to doctor. Test success, status mismatch, SKU/record mismatch, idempotent repeat, and proof that pack_md/status/version remain unchanged.

- [ ] **Step 6: Run persistence tests**

~~~powershell
python scripts/apply_migrations.py --only 068
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_content_contract_persistence.py tests/test_route_manifest_persistence.py tests/test_portrait_lineage.py tests/test_pack_portrait_binding.py"
~~~

Expected: pass against a migrated test database.

- [ ] **Step 7: Commit**

~~~powershell
git add migrations/068_ai_content_contract.sql services/knowledge-engine/tests/test_content_contract_persistence.py services/knowledge-engine/tests/test_route_manifest_persistence.py services/knowledge-engine/tests/test_pack_portrait_binding.py
git add -p services/knowledge-engine/app/services/pipeline_lineage.py services/knowledge-engine/app/mcp/tools/pipeline.py services/knowledge-engine/app/routers/mcp_exec.py services/knowledge-engine/app/mcp/doctor.py services/knowledge-engine/tests/test_portrait_lineage.py
git diff --cached --check
git commit -m "feat: persist content contracts and route manifests"
~~~

### Task 3: Build framework-v1 registry and compatibility validator

**Files:**

- Create: E:\agent\omni\services\knowledge-engine\config\planting_frameworks\framework-v1.json
- Create: E:\agent\omni\services\knowledge-engine\app\services\planting_framework_registry.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_planting_framework_registry.py

- [ ] **Step 1: Write registry tests**

Assert the exact ID sets:

~~~python
assert set(registry.narratives) == {f"N{i}" for i in range(1, 9)}
assert set(registry.proofs) == {f"P{i}" for i in range(1, 7)}
assert set(registry.presentations) == {f"V{i}" for i in range(1, 7)}
assert registry.version == "framework-v1"
assert derive_route_id("N1", "P3", "V2", "framework-v1") == "N1+P3+V2@framework-v1"
assert validate_route("N1", "P3", "V2", production_track="pure_ai")["ok"] is True
assert validate_route("N1", "P2", "V2", production_track="pure_ai")["error"] == "framework_route_incompatible"
assert registry.proofs["P5"].eligible_production_tracks == ["future_real_material"]
assert validate_route("N6", "P5", "V2", production_track="pure_ai")["error"] == "framework_route_incompatible"
assert validate_route("N7", "P6", "V3", production_track="pure_ai")["error"] == "proof_evidence_missing"
~~~

- [ ] **Step 2: Populate the registry from the approved design**

The JSON must contain these immutable cards and names:

- N1 pain_solution
- N2 routine_integration
- N3 result_reverse
- N4 micro_drama
- N5 recipe_step
- N6 comment_qa
- N7 origin_behind_scenes
- N8 multi_scene_use
- P1 demonstration
- P2 comparison
- P3 reason_why
- P4 choice_standard
- P5 real_review
- P6 authority_evidence
- V1 recipe_montage
- V2 native_direct_narration
- V3 tabletop_macro
- V4 food_asmr
- V5 skit_dialogue
- V6 multi_scene_voiceover

Encode the exact compatibility matrix:

~~~json
{
  "N1": {"proofs": ["P1", "P3", "P4"], "presentations": ["V2", "V5", "V6"]},
  "N2": {"proofs": ["P1", "P3"], "presentations": ["V4", "V6"]},
  "N3": {"proofs": ["P1", "P2"], "presentations": ["V1", "V3", "V6"]},
  "N4": {"proofs": ["P1", "P3", "P4"], "presentations": ["V5", "V6"]},
  "N5": {"proofs": ["P1", "P3", "P4"], "presentations": ["V1", "V3", "V4"]},
  "N6": {"proofs": ["P1", "P3", "P4"], "presentations": ["V2", "V3"]},
  "N7": {"proofs": ["P3", "P6"], "presentations": ["V3", "V6"]},
  "N8": {"proofs": ["P1", "P2"], "presentations": ["V1", "V4", "V6"]}
}
~~~

Each card must also carry fit_tags, required_evidence, eligible_production_tracks, source_refs, evidence_level, and dependency_ownership. P5 has eligible_production_tracks=["future_real_material"] and is ineligible for pure_ai. P6 requires a verifiable authority/qualification source.

- [ ] **Step 3: Implement load and validation APIs**

Expose only:

~~~python
load_registry(version: str = "framework-v1") -> FrameworkRegistry
derive_route_id(narrative: str, proof: str, presentation: str, version: str) -> str
validate_route(narrative: str, proof: str, presentation: str, *, production_track: str, evidence: dict | None = None) -> dict
ownership_for(variable: str, *, registry_version: str = "framework-v1") -> set[str]
~~~

Reject unknown versions and all combinations not present in the registry. Never let a caller bypass compatibility by passing an arbitrary allow flag.

- [ ] **Step 4: Run tests and commit**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_planting_framework_registry.py"
git add services/knowledge-engine/config/planting_frameworks/framework-v1.json services/knowledge-engine/app/services/planting_framework_registry.py services/knowledge-engine/tests/test_planting_framework_registry.py
git diff --cached --check
git commit -m "feat: add versioned planting framework registry"
~~~

### Task 4: Implement deterministic route enumeration and stable 4→2 ranking

**Files:**

- Create: E:\agent\omni\services\knowledge-engine\app\services\planting_framework_router.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_planting_framework_router.py

- [ ] **Step 1: Write failing router tests**

Test:

- evidence and production hard gates run before scoring;
- no route outside the compatibility matrix appears;
- pure AI excludes P5;
- missing P6 evidence excludes the route;
- enough eligible routes produce four meaningfully distinct text routes;
- two or three eligible routes are kept with route_pool_limited;
- fewer than two return insufficient_eligible_routes;
- final order is route_fit_total descending, triangle_score descending, vector_score descending, route_id ascending;
- vector score cannot rescue a route that failed a hard gate.

- [ ] **Step 2: Implement pure routing functions**

Expose three public functions: enumerate_eligible_routes(contract, registry), shortlist_routes(eligible, target=4, diversity_keys=("narrative_framework", "proof_framework", "presentation_motif")), and rank_prescreened_routes(routes, top_n=2).

The final ranking implementation is exact:

~~~python
def rank_prescreened_routes(routes: list[dict], *, top_n: int = 2) -> list[dict]:
    eligible = [route for route in routes if route["hard_gate"]["ok"]]
    return sorted(
        eligible,
        key=lambda route: (
            -route["route_fit_total"],
            -route["triangle_score"],
            -route["vector_score"],
            route["route_id"],
        ),
    )[:top_n]
~~~

enumerate_eligible_routes iterates the registry’s allowed N/P/V combinations only, calls validate_route for every combination, records rejected routes with their first hard-gate reason, and computes five named 0–2 rule components from explicit contract tags. shortlist_routes greedily selects the highest rule score that adds a new narrative, proof, or presentation value until target is reached; it then fills remaining slots by stable route ID order. It returns route_pool_limited for 2–3 survivors and insufficient_eligible_routes below 2.

The deterministic rule score is five 0–2 components: audience relevance, selling-point bridge, evidence honesty, AI production feasibility, and route diversity. Missing facts score zero and are never inferred.

- [ ] **Step 3: Run tests and commit**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_planting_framework_router.py"
git add services/knowledge-engine/app/services/planting_framework_router.py services/knowledge-engine/tests/test_planting_framework_router.py
git diff --cached --check
git commit -m "feat: add deterministic planting route router"
~~~

### Task 5: Add deterministic legacy M1–M9 migration

**Files:**

- Create: E:\agent\omni\services\knowledge-engine\app\services\legacy_planting_migration.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_legacy_planting_migration.py
- Read-only fixture: E:\agent\omni\services\knowledge-engine\config\eval\golden\generate_creative_pack\video_planting-v2-ce40eb36\golden.md

- [ ] **Step 1: Write the migration matrix tests**

Cover every mapping:

~~~python
EXPECTED = {
    "M1": ("N2", None),
    "M2": ("N1", None),
    "M3": (None, "P4"),
    "M4": (None, "P3"),
    "M5": (None, "P2"),
    "M6": (None, "P3"),
    "M7": (None, "P5"),
    "M8": (None, "P1"),
    "M9": (None, "P6"),
}
~~~

Also test M1 only becomes N8 when the old script explicitly contains multiple adjacent use scenes; M4 only becomes N7 after explicit human review; P5 is history-only for pure AI; P6 without a verifiable source is blocked; unknown V remains unknown; and two narrative frameworks cannot form a current route.
Run the same assertions against the existing video_planting-v2 golden so the migration proves compatibility with a real historical output rather than only synthetic dictionaries.

- [ ] **Step 2: Implement read-only migration output**

Return selected_combo_original, migrated_fields, migration_warnings, render_eligible, and route_id. Never update the old script row. Only complete, compatible, evidence-qualified N/P/V results receive a new route_id.

- [ ] **Step 3: Run tests and commit**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_legacy_planting_migration.py"
git add services/knowledge-engine/app/services/legacy_planting_migration.py services/knowledge-engine/tests/test_legacy_planting_migration.py
git diff --cached --check
git commit -m "feat: migrate legacy planting frameworks deterministically"
~~~

### Task 6: Persist route manifests and derive render candidates through generate_creative_pack

**Files:**

- Create: E:\agent\omni\services\knowledge-engine\app\services\planting_route_manifest.py
- Create: E:\agent\omni\services\knowledge-engine\config\prompts\planting_route_manifest.system.md
- Create: E:\agent\omni\services\knowledge-engine\config\prompts\planting_route_manifest.user.md
- Create: E:\agent\omni\services\knowledge-engine\tests\test_planting_route_manifest.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_route_manifest_gates.py
- Modify: E:\agent\omni\services\knowledge-engine\app\mcp\tools\media.py
- Modify: E:\agent\omni\services\knowledge-engine\app\routers\mcp_exec.py
- Modify: E:\agent\omni\services\knowledge-engine\app\services\experiment_lab.py
- Modify: E:\agent\omni\services\knowledge-engine\config\prompts\creative_pack.video_planting.system.md
- Modify: E:\agent\omni\services\knowledge-engine\config\prompts\creative_pack.user.md

- [ ] **Step 1: Write failing manifest workflow tests**

Test the two calls:

~~~python
manifest = await generate_creative_pack(
    kind="video_planting",
    sku_id="SKU-367991-0002",
    audience_pack_id="pack-1",
    workflow_mode="full_video",
    product_refs=[validated_product_ref()],
    route_shortlist_target=4,
)
assert manifest["stage"] == "ROUTE_REVIEW"
assert manifest["route_manifest_script_id"]
assert len(manifest["routes"]) <= 4
assert len(manifest["default_candidates"]) == 2

candidates = await generate_creative_pack(
    kind="video_planting",
    workflow_mode="full_video",
    route_manifest_id=manifest["route_manifest_script_id"],
    selected_route_ids=[r["route_id"] for r in manifest["default_candidates"]],
    product_refs=[validated_product_ref()],
)
assert candidates["stage"] == "SCRIPT_REVIEW"
assert all(s["content_contract"]["artifact_role"] == "render_candidate" for s in candidates["scripts"])
assert all(s["parent_script_id"] == manifest["route_manifest_script_id"] for s in candidates["scripts"])
~~~

Also assert:

- exact retries reuse manifest_key and outputs;
- changing router, generator, prompt, embedding, framework, or contract version produces a new child manifest and never reuses stale scores/text;
- reroute_revision creates a new child manifest with parent_script_id;
- route manifests cannot be adopted, attached as arms, or rendered;
- content vector score only changes route order and never returns pre_video_vector_low;
- a manifest persistence error fails the top-level call;
- product_ref, evidence, compatibility, and triangle gates return the earliest ordered blocker.

In this foundation plan, product_refs are prevalidated contract objects supplied by tests/callers. Byte decoding, white-background inspection, and user SKU binding are implemented by the rendering-gates plan. The manifest layer still rejects a missing or structurally invalid validation object before calling the LLM.

- [ ] **Step 2: Define an idempotent manifest key**

~~~python
manifest_key = sha256(
    canonical_json({
        "sku_id": contract["permanent_facts"]["sku_id"],
        "audience_pack_id": contract["permanent_facts"]["audience_pack_id"],
        "contract_hash": contract_hash,
        "contract_schema_version": contract["schema_version"],
        "framework_library_version": "framework-v1",
        "router_version": router_version,
        "generator_provider": generator_provider,
        "generator_model": generator_model,
        "prompt_hash": prompt_hash,
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
        "route_shortlist_target": route_shortlist_target,
        "idea_seed": idea_seed or "",
        "manifest_revision": manifest_revision,
    }).encode("utf-8")
).hexdigest()
~~~

Persist the same contract/router/generator/prompt/embedding versions, route text hashes, rule scores, hard gates, triangle scores, vector scores, default Top 2, and excluded routes in content_contract.manifest. An exact retry with identical inputs and versions reuses the row; a prompt, router, generator, embedding, framework, contract, or explicit reroute revision change creates a new child manifest instead of reusing stale output.

- [ ] **Step 3: Constrain the LLM to text instantiation**

The manifest prompt receives only routes selected by the deterministic router. Require JSON output with route_id, opening, timeline, proof execution, product actions, visual/sound notes, and source-bound claims. The prompt must explicitly forbid adding a new route, claim, price, certification, testimonial, or selling point.

- [ ] **Step 4: Extend generate_creative_pack without breaking existing callers**

Add optional parameters:

~~~python
workflow_mode: Literal["script", "full_video"] = "script"
product_refs: list[dict] | None = None
route_manifest_id: str | None = None
selected_route_ids: list[str] | None = None
route_shortlist_target: int = 4
reroute_revision: bool = False
~~~

Default script mode must preserve all six existing creative kinds. full_video is allowed only for video_planting in this plan. It means “build the formal content workflow,” not “render immediately.”

- [ ] **Step 5: Align the planting prompt and validator**

Make the emitted metrics block and media.py validator use exactly the same field names. Validate the full content contract, N/P/V route, variable-difference card, 30/45-second time skeleton, 6–9 continuous nodes, product appearance plan, four signal tracks, and hard-gate results.

- [ ] **Step 6: Add REST forwarding**

Add the same optional fields to GenerateCreativePackRequest and forward them unchanged.

- [ ] **Step 7: Block manifest adoption and arm attachment**

In register_round, attach_arm, and adopt_script_as_arm, load the script content_contract and return route_manifest_not_renderable when artifact_role=route_manifest or render_eligible is not true. Do not copy registry logic into experiment_lab.py; the experiment layer only checks the persisted artifact contract.

- [ ] **Step 8: Run tests**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_planting_route_manifest.py tests/test_route_manifest_gates.py tests/test_mcp_prompts.py tests/test_whole_prompt_scenes.py"
~~~

Expected: pass with no fake vector hard block.

- [ ] **Step 9: Commit**

~~~powershell
git add services/knowledge-engine/app/services/planting_route_manifest.py services/knowledge-engine/config/prompts/planting_route_manifest.system.md services/knowledge-engine/config/prompts/planting_route_manifest.user.md services/knowledge-engine/tests/test_planting_route_manifest.py services/knowledge-engine/tests/test_route_manifest_gates.py
git add -p services/knowledge-engine/app/mcp/tools/media.py services/knowledge-engine/app/routers/mcp_exec.py services/knowledge-engine/app/services/experiment_lab.py services/knowledge-engine/config/prompts/creative_pack.video_planting.system.md services/knowledge-engine/config/prompts/creative_pack.user.md
git diff --cached --check
git commit -m "feat: add planting route manifest workflow"
~~~

### Task 7: Run foundation regression and migration verification

**Files:**

- Test: all files touched above

- [ ] **Step 1: Apply migration in the local stack**

Run:

~~~powershell
python scripts/apply_migrations.py --only 068
~~~

Then verify:

~~~sql
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'pipeline'
  AND table_name IN ('scripts', 'audience_packs')
  AND column_name IN (
      'content_contract',
      'target_video_model',
      'audience_portrait_id',
      'execution_meta'
  )
ORDER BY column_name;
~~~

Expected: four rows.

- [ ] **Step 2: Run the complete focused suite**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_content_contract.py tests/test_audience_content_bridge.py tests/test_content_contract_persistence.py tests/test_route_manifest_persistence.py tests/test_planting_framework_registry.py tests/test_planting_framework_router.py tests/test_legacy_planting_migration.py tests/test_planting_route_manifest.py tests/test_route_manifest_gates.py"
~~~

Expected: all pass.

- [ ] **Step 3: Run existing creative regressions**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_mcp_media.py tests/test_creative_pack_batch.py tests/test_mcp_prompts.py tests/test_audience_content_bridge.py tests/test_triangle_match.py tests/test_match_vectors.py tests/test_vector_presets.py"
~~~

Expected: all pass; existing soft-ad/harvest/graphics calls remain backward compatible.

- [ ] **Step 4: Inspect the staged diff and final commit if verification required fixes**

Use git add -p for shared dirty files, run git diff --cached --check, and commit only the reviewed correction hunks with message:

~~~text
fix: stabilize planting framework foundation
~~~
