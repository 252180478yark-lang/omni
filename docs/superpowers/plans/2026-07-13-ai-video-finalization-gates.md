# AI Video Finalization and Render Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make soft-ad and planting rendering fail closed on product/model mismatches, persist actual generation metadata, assemble ordered segments into a verified final MP4, and run prescreen on the whole final video rather than on individual segments.

**Architecture:** Product references and logical video-model profiles are validated before any paid generation. Existing generate_character_sheets and generate_video_segments remain the MCP entry points; generate_video_segments gains finalize/finalize_only modes backed by a deterministic FFmpeg service, avoiding a second rendering state machine or an extra MCP tool. pipeline.assets.generation_meta distinguishes segment and final assets.

**Tech Stack:** Python 3.12, Pillow, FFmpeg/ffprobe, asyncpg/PostgreSQL, AI Provider Hub, pytest, existing asset storage and MCP tools.

---

## Dependencies and execution preflight

- Complete the framework foundation and experiment policy plans first.
- Migration 070 belongs only to this plan.
- Preserve all user-owned dirty-tree work. Shared files such as media.py, pipeline_lineage.py, mcp_exec.py, experiment_lab.py, page.tsx, and provider code must be staged by reviewed hunk.

### Task 1: Validate and bind product reference images before content generation

**Files:**

- Create: E:\agent\omni\services\knowledge-engine\app\services\product_reference.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_product_reference.py
- Modify: E:\agent\omni\services\knowledge-engine\app\main.py
- Modify: E:\agent\omni\frontend\src\app\api\omni\sku-pipeline\upload-product-ref\route.ts
- Modify: E:\agent\omni\services\knowledge-engine\tests\test_video_segments_product_gate.py

- [ ] **Step 1: Write failing validation tests**

Test:

- unreadable bytes and wrong MIME return product_ref_invalid;
- width or height below 512 returns product_ref_invalid;
- a border dominated by dark/saturated pixels returns product_ref_invalid;
- a valid white/neutral-border PNG returns SHA-256, dimensions, background score, and normalized reference;
- missing sku_id or confirmed_by_user=False returns product_ref_sku_mismatch;
- the same experiment round cannot mix different product hashes;
- video_soft_ad and video_planting reject allow_no_product=True.

Use generated in-memory fixtures, not user product files, for unit tests.

- [ ] **Step 2: Implement deterministic image inspection**

~~~python
@dataclass(frozen=True)
class ProductReferenceResult:
    ok: bool
    error: str | None
    sku_id: str | None
    sha256: str | None
    width: int | None
    height: int | None
    background_score: float | None
    normalized_ref: str | None
    confirmed_by_user: bool
    verified_at: str
~~~

Expose validate_product_reference(ref, sku_id, confirmed_by_user, min_side=512, min_clean_border_ratio=0.85) returning ProductReferenceResult. Resolve local static URLs, HTTP URLs, data URIs, and bytes through one bounded reader. Pillow must verify and decode the image. Sample a 5% border band; count a pixel clean when it is bright neutral or near-white. This is a background usability check, not automatic product identity recognition. Identity is established only by the user’s explicit SKU binding.

- [ ] **Step 3: Extend the upload endpoint**

The multipart endpoint must require:

- file
- sku_id
- confirmed_by_user=true

Return:

~~~json
{
  "ok": true,
  "product_ref": {
    "sku_id": "SKU-367991-0002",
    "sha256": "hex",
    "width": 800,
    "height": 800,
    "background_score": 0.94,
    "normalized_ref": "/api/v1/knowledge/static/product_refs/file.png",
    "confirmed_by_user": true,
    "verified_at": "ISO-8601"
  }
}
~~~

The frontend proxy must forward form data unchanged.

- [ ] **Step 4: Enforce the gate at both content and rendering entry points**

The framework plan’s content contract builder stores the complete product_ref result. generate_creative_pack(full_video) and generate_video_segments must call the same validator and compare sku_id/hash to the contract.

- [ ] **Step 5: Run tests and commit**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_product_reference.py tests/test_video_segments_product_gate.py"
git add services/knowledge-engine/app/services/product_reference.py services/knowledge-engine/tests/test_product_reference.py
git add -p services/knowledge-engine/app/main.py services/knowledge-engine/tests/test_video_segments_product_gate.py frontend/src/app/api/omni/sku-pipeline/upload-product-ref/route.ts
git diff --cached --check
git commit -m "feat: validate and bind product reference images"
~~~

### Task 2: Add a logical video-model registry and preserve actual provider metadata

**Files:**

- Create: E:\agent\omni\services\knowledge-engine\config\video_models.yaml
- Create: E:\agent\omni\services\knowledge-engine\app\services\video_model_registry.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_video_model_registry.py
- Modify: E:\agent\omni\services\ai-provider-hub\app\schemas\ai.py
- Modify: E:\agent\omni\services\ai-provider-hub\app\services\video_service.py
- Modify: E:\agent\omni\services\ai-provider-hub\app\providers\seedance_provider.py
- Modify: E:\agent\omni\services\ai-provider-hub\app\providers\veo_provider.py
- Create: E:\agent\omni\services\ai-provider-hub\tests\test_video_metadata_contract.py
- Modify: E:\agent\omni\services\knowledge-engine\app\services\ai_hub_client.py

- [ ] **Step 1: Write registry tests**

Test:

~~~python
def test_seedance_profile_is_concrete():
    p = get_video_model_profile("seedance")
    assert p.provider == "seedance"
    assert p.model == "doubao-seedance-2-0-260128"
    assert p.max_segment_seconds == 15
    assert p.supports_product_reference is True


def test_veo_duration_is_capability_driven():
    p = get_video_model_profile("veo")
    assert p.allowed_durations == [4, 6, 8]
    assert p.reference_images_with_first_frame is False


def test_unconfigured_jimeng_fails_closed():
    result = resolve_video_model("jimeng")
    assert result["ok"] is False
    assert result["error"] == "target_model_mismatch"
~~~

- [ ] **Step 2: Create explicit profiles**

video_models.yaml must contain:

~~~yaml
version: video-model-registry-v1
models:
  seedance:
    provider: seedance
    model: doubao-seedance-2-0-260128
    profile_version: seedance-v1
    allowed_durations: [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
    max_segment_seconds: 15
    supports_product_reference: true
    supports_face_reference: true
    reference_images_with_first_frame: true
    generated_audio: unreliable
    supports_direct_full_video: false
    enabled: true
  veo:
    provider: veo
    model: veo-3.1-generate-preview
    profile_version: veo-v1
    allowed_durations: [4, 6, 8]
    max_segment_seconds: 8
    supports_product_reference: true
    supports_face_reference: true
    reference_images_with_first_frame: false
    generated_audio: supported
    supports_direct_full_video: false
    enabled: true
  jimeng:
    provider: null
    model: null
    profile_version: jimeng-v1
    allowed_durations: [3, 4, 5, 6]
    max_segment_seconds: 6
    supports_product_reference: false
    supports_face_reference: false
    reference_images_with_first_frame: false
    generated_audio: unsupported
    supports_direct_full_video: false
    enabled: false
~~~

The registry is the source of actual segment duration and reference capability. Markdown prompt profiles remain writing guidance only.

- [ ] **Step 3: Extend Hub responses**

Add model and generation_meta to VideoStatusResponse:

~~~python
class VideoStatusResponse(BaseModel):
    task_id: str
    status: str
    video_url: str | None = None
    duration: int | None = None
    provider: str | None = None
    model: str | None = None
    generation_meta: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
~~~

Store and return:

- requested_provider/model
- actual_provider/model
- requested_reference_count
- accepted_reference_count
- reference_roles_used
- generate_audio requested

Provider adapters must report what they actually sent upstream. They must not claim a product reference was used after dropping it.

- [ ] **Step 4: Update the KE client**

Preserve initial submit metadata and final status metadata. A final response missing actual model or accepted product refs is an error for formal soft-ad/planting rendering.

- [ ] **Step 5: Run tests and commit**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_video_model_registry.py tests/test_ai_hub_client_contract.py"
docker exec omni-ai-provider-hub bash -lc "cd /app && python -m pytest -q tests/test_video_metadata_contract.py"
git add services/knowledge-engine/config/video_models.yaml services/knowledge-engine/app/services/video_model_registry.py services/knowledge-engine/tests/test_video_model_registry.py services/ai-provider-hub/tests/test_video_metadata_contract.py
git add -p services/ai-provider-hub/app/schemas/ai.py services/ai-provider-hub/app/services/video_service.py services/ai-provider-hub/app/providers/seedance_provider.py services/ai-provider-hub/app/providers/veo_provider.py services/knowledge-engine/app/services/ai_hub_client.py
git diff --cached --check
git commit -m "feat: enforce actual AI video model contract"
~~~

### Task 3: Make character sheets deterministic and fail closed

**Files:**

- Create: E:\agent\omni\services\knowledge-engine\tests\test_character_sheets_gate.py
- Modify: E:\agent\omni\services\knowledge-engine\app\services\character_anchor.py
- Modify: E:\agent\omni\services\knowledge-engine\app\mcp\tools\media.py

- [ ] **Step 1: Write failing tests**

Test:

- all required character sheets failing returns ok=False and character_sheet_failed;
- a partially missing required cast member blocks formal rendering;
- the same content-contract hash yields identical character prompts and ordering;
- two arms whose swept variable does not own role_semantics receive the same cast semantics and prompt hash;
- no random.choice or unseeded random variation changes an arm.

- [ ] **Step 2: Remove uncontrolled randomness**

Generate a stable choice seed from contract hash plus role ID. Prefer deterministic first-ranked options. If diversity is explicitly tested, it must be the swept variable rather than hidden randomness.

- [ ] **Step 3: Fail closed in generate_character_sheets**

Return:

~~~json
{
  "ok": false,
  "error": "character_sheet_failed",
  "failed_roles": ["role_id"],
  "successful_assets": [],
  "next_step_hint": "修复定妆失败后从本步骤重试"
}
~~~

Do not return a “continue” hint when any required role is missing.

- [ ] **Step 4: Run tests and commit**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_character_sheets_gate.py"
git add services/knowledge-engine/tests/test_character_sheets_gate.py
git add -p services/knowledge-engine/app/services/character_anchor.py services/knowledge-engine/app/mcp/tools/media.py
git diff --cached --check
git commit -m "fix: fail closed on character sheet generation"
~~~

### Task 4: Enforce contract, refs, model, and arm lineage in segment generation

**Files:**

- Modify: E:\agent\omni\services\knowledge-engine\app\mcp\tools\media.py
- Modify: E:\agent\omni\services\knowledge-engine\app\routers\mcp_exec.py
- Modify: E:\agent\omni\services\knowledge-engine\app\services\pipeline_lineage.py
- Modify: E:\agent\omni\services\knowledge-engine\tests\test_video_segments_product_gate.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_video_segment_generation_meta.py

- [ ] **Step 1: Add failing generation tests**

Test:

- route_manifest script returns route_manifest_not_renderable before any provider call;
- non-adopted render candidate does not render;
- contract target model and request target model mismatch returns target_model_mismatch;
- product hash mismatch returns product_ref_sku_mismatch;
- i2v/provider capability logic dropping refs returns product_refs_dropped before provider billing;
- actual response with accepted_reference_count=0 fails;
- segment duration follows the registry;
- every saved segment carries experiment_arm_id and requested/actual provider/model.

- [ ] **Step 2: Extend the REST request**

GenerateVideoSegmentsRequest must include all already-supported tool fields plus:

~~~python
experiment_arm_id: str | None = None
allow_no_product: bool = False
target_model: str | None = None
generate_audio: bool = True
finalize: bool = False
finalize_only: bool = False
audio_track: str | None = None
~~~

Forward them unchanged.
Keep model_override only for legacy/non-formal calls. A formal render resolves target_model from the script contract; an explicitly supplied target_model must match it, and model_override cannot bypass that match.

- [ ] **Step 3: Put formal gates in strict order**

Before generation:

1. load script and content contract;
2. reject route_manifest;
3. require adopted render_candidate;
4. validate one-variable diff and triangle match;
5. validate product reference/SKU/hash;
6. resolve requested target model;
7. ensure provider capabilities can carry all required refs;
8. only then call the Hub.

The vector match remains a ranking side signal and cannot return pre_video_vector_low.
Formal soft-ad/planting calls request generate_audio=True. If the selected provider cannot generate audio, audio_track becomes a required input before final readiness.

- [ ] **Step 4: Save segment generation metadata**

Each segment asset receives:

~~~json
{
  "asset_role": "segment",
  "script_id": "uuid",
  "experiment_arm_id": "uuid",
  "segment_index": 1,
  "requested_provider": "seedance",
  "requested_model": "doubao-seedance-2-0-260128",
  "actual_provider": "seedance",
  "actual_model": "doubao-seedance-2-0-260128",
  "product_ref_sha256": "hex",
  "requested_reference_count": 3,
  "accepted_reference_count": 3,
  "reference_roles_used": ["product", "character"],
  "model_profile_version": "seedance-v1"
}
~~~

Do not create a usable segment asset when the actual response violates the contract.

- [ ] **Step 5: Run tests and commit**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_video_segments_product_gate.py tests/test_video_segment_generation_meta.py tests/test_character_sheets_gate.py"
git add services/knowledge-engine/tests/test_video_segment_generation_meta.py
git add -p services/knowledge-engine/app/mcp/tools/media.py services/knowledge-engine/app/routers/mcp_exec.py services/knowledge-engine/app/services/pipeline_lineage.py services/knowledge-engine/tests/test_video_segments_product_gate.py
git diff --cached --check
git commit -m "feat: fail closed during AI video segment generation"
~~~

### Task 5: Add migration 070 and deterministic final-video assembly

**Files:**

- Create: E:\agent\omni\migrations\070_ai_video_generation_meta.sql
- Create: E:\agent\omni\services\knowledge-engine\app\services\video_assembly.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_video_assembly.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_pipeline_asset_generation_meta.py
- Modify: E:\agent\omni\services\knowledge-engine\app\services\pipeline_lineage.py
- Modify: E:\agent\omni\services\knowledge-engine\app\mcp\tools\media.py
- Modify: E:\agent\omni\services\knowledge-engine\Dockerfile

- [ ] **Step 1: Write failing assembly tests**

Generate tiny synthetic MP4 fixtures with FFmpeg. Test:

- ordered segments assemble to one 1080×1920 or configured 9:16 H.264 MP4;
- frame rate is normalized;
- source audio is preserved and normalized to AAC;
- missing segment, duplicate index, unordered index, wrong script, or wrong arm returns assembly_failed;
- no source audio and no supplied audio_track returns final_media_invalid with detail=audio_missing, creates only a review draft, and cannot become READY_FOR_TEST;
- final ffprobe lacking video stream, audio stream, valid duration, or 9:16 dimensions returns final_media_invalid;
- retry with the same assembly key reuses the prior valid final asset.

- [ ] **Step 2: Create migration 070**

~~~sql
ALTER TABLE pipeline.assets
    ADD COLUMN IF NOT EXISTS generation_meta JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_assets_generation_role
    ON pipeline.assets ((generation_meta ->> 'asset_role'))
    WHERE generation_meta ? 'asset_role';

CREATE UNIQUE INDEX IF NOT EXISTS uq_assets_final_assembly_key
    ON pipeline.assets ((generation_meta ->> 'assembly_key'))
    WHERE generation_meta ->> 'asset_role' = 'final';
~~~

Rebuild pipeline.v_asset_full_lineage from its latest definition without dropping any existing column. Append generation_meta plus script.parent_script_id, parent script artifact_role/manifest_key/framework version, and the render candidate’s content_contract. In pipeline_get_asset_lineage, parse final generation_meta.segment_asset_ids, fetch those segment asset rows in order, and return them under segments. A single final-asset lineage call must therefore expose route manifest → render candidate → segment assets → final asset → metrics.

- [ ] **Step 3: Install FFmpeg**

In the KE Dockerfile, install ffmpeg and clean package lists in the same package-install layer. The image must expose both ffmpeg and ffprobe.

- [ ] **Step 4: Implement strict assembly**

~~~python
@dataclass(frozen=True)
class AssemblyRequest:
    script_id: str
    experiment_arm_id: str
    segment_paths: tuple[str, ...]
    segment_asset_ids: tuple[str, ...]
    aspect_ratio: str = "9:16"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    audio_track: str | None = None
~~~

Expose async assemble_final_video(request: AssemblyRequest) returning the persisted final-asset result or the first structured blocker. Rules:

- resolve all paths with asset_storage.get_disk_path_for_public_url;
- refuse missing/duplicate/out-of-order segments;
- normalize each segment to H.264 yuv420p at the requested size/fps;
- concatenate in scene order;
- preserve usable source audio or mux the supplied audio_track;
- do not invent subtitles, transitions, logos, prices, or marketing elements;
- if no meaningful audio source exists, return final_media_invalid with detail=audio_missing and keep any assembled file as non-ready diagnostic output;
- run ffprobe and validate dimensions, ratio, duration tolerance, video codec, audio codec, and streams;
- run FFmpeg astats/volumedetect so a structurally present but effectively silent track cannot satisfy READY_FOR_TEST.

- [ ] **Step 5: Extend generate_video_segments with finalize modes**

Behavior:

- finalize=False: generate and save segments only, backward compatible.
- finalize=True: generate segments, then assemble and create the final asset.
- finalize_only=True: do not call a provider; load existing valid segment assets for script/arm and retry assembly.

If a future enabled model profile declares supports_direct_full_video=true and returns the complete requested duration in one response, normalize that response into a distinct final asset with assembly_mode=direct, then run the same probe/audio/prescreen gates. Do not treat the provider’s raw segment row as the final asset.

This remains one MCP tool. No doctor tool-count change is required.
Preserve @tool_with_audit and the existing trace contract. The returned trace must include requested/actual model, product/character reference hashes, segment asset IDs, assembly key, probe summary, and cost metadata; do not hide the deterministic finalization behind an unaudited helper call.

- [ ] **Step 6: Save a final asset**

Use asset_type=video, scene_no=NULL, and:

~~~json
{
  "asset_role": "final",
  "assembly_key": "sha256",
  "segment_asset_ids": ["uuid-1", "uuid-2"],
  "probe": {
    "duration_seconds": 30.08,
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "video_codec": "h264",
    "audio_codec": "aac"
  },
  "audio_source": "model_or_supplied",
  "ready_for_prescreen": true
}
~~~

Persist the same script_id, audience pack lineage, experiment_id, and experiment_arm_id as the segments.
Extend test_pipeline_asset_generation_meta.py to call pipeline_get_asset_lineage(final_asset_id) and assert the parent manifest contract, ordered segment metadata, final generation metadata, experiment arm, and ad_metrics are all present.

- [ ] **Step 7: Run tests and commit**

~~~powershell
python scripts/apply_migrations.py --only 070
docker compose build knowledge-engine
docker compose up -d --force-recreate knowledge-engine
docker exec omni-knowledge-engine ffmpeg -version
docker exec omni-knowledge-engine ffprobe -version
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_video_assembly.py tests/test_pipeline_asset_generation_meta.py tests/test_video_segment_generation_meta.py"
git add migrations/070_ai_video_generation_meta.sql services/knowledge-engine/app/services/video_assembly.py services/knowledge-engine/tests/test_video_assembly.py services/knowledge-engine/tests/test_pipeline_asset_generation_meta.py
git add -p services/knowledge-engine/app/services/pipeline_lineage.py services/knowledge-engine/app/mcp/tools/media.py services/knowledge-engine/Dockerfile
git diff --cached --check
git commit -m "feat: assemble verified final AI videos"
~~~

### Task 6: Prescreen only complete final assets

**Files:**

- Create: E:\agent\omni\services\knowledge-engine\tests\test_experiment_prescreen_final.py
- Modify: E:\agent\omni\services\knowledge-engine\app\services\experiment_lab.py
- Modify: E:\agent\omni\services\knowledge-engine\app\mcp\tools\experiment.py

- [ ] **Step 1: Write failing prescreen tests**

Test:

- rounds with segments but no final asset return final_media_invalid;
- only generation_meta.asset_role=final is sent to the multimodal judge;
- a final with ready_for_prescreen=false is rejected;
- one final per arm is required;
- judge failure returns prescreen_failed and never marks READY_FOR_TEST;
- passing whole-video prescreen writes visual_prescreen only to the final asset.

- [ ] **Step 2: Change the asset query**

Filter:

~~~sql
a.asset_type = 'video'
AND a.scene_no IS NULL
AND a.generation_meta ->> 'asset_role' = 'final'
AND a.generation_meta ->> 'ready_for_prescreen' = 'true'
~~~

- [ ] **Step 3: Return readiness derived from artifacts**

READY_FOR_TEST requires:

- adopted render-candidate script;
- experiment arm;
- valid final MP4;
- whole-video prescreen pass.

No new database status enum is added.

- [ ] **Step 4: Run tests and commit**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_experiment_prescreen_final.py"
git add services/knowledge-engine/tests/test_experiment_prescreen_final.py
git add -p services/knowledge-engine/app/services/experiment_lab.py services/knowledge-engine/app/mcp/tools/experiment.py
git diff --cached --check
git commit -m "fix: prescreen complete final videos only"
~~~

### Task 7: Rendering acceptance and regression

**Files:**

- Test: all files touched in this plan

- [ ] **Step 1: Run focused KE tests**

~~~powershell
python scripts/apply_migrations.py --only 070
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_product_reference.py tests/test_video_model_registry.py tests/test_video_segments_product_gate.py tests/test_character_sheets_gate.py tests/test_video_segment_generation_meta.py tests/test_video_assembly.py tests/test_experiment_prescreen_final.py tests/test_pipeline_asset_generation_meta.py"
~~~

Expected: all pass.

- [ ] **Step 2: Run Hub metadata tests**

~~~powershell
docker exec omni-ai-provider-hub bash -lc "cd /app && python -m pytest -q tests/test_video_metadata_contract.py"
~~~

Expected: requested and actual provider/model/ref metadata survive submit and status polling.

- [ ] **Step 3: Run doctor**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
~~~

Expected: the existing tool set remains registered and healthy; no new MCP tool was added.

- [ ] **Step 4: Run a mocked end-to-end render**

With a mocked provider response, create two segments with audio, call generate_video_segments(finalize=True), and assert one final asset exists with scene_no NULL, role final, correct arm lineage, probe metadata, and prescreen eligibility.

- [ ] **Step 5: Commit any reviewed verification fixes**

Stage only reviewed hunks, run git diff --cached --check, and commit:

~~~text
test: verify final AI video render pipeline
~~~
