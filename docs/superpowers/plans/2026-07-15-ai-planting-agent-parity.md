# AI Planting Video Agent Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Agent-conversation planting-video chain from adopted SKU/audience lineage through pain-solution extraction, two single-variable scripts, arm-bound character/video segments, double vector gates, atomic generation-set adoption, and A3-based iteration while preserving the distinct soft-ad method and metrics.

**Architecture:** Keep one shared video orchestration kernel and select behavior through versioned `planting` and `soft_ad` intent profiles. Planting adds a Gemini 3.1 Pro pain-solution bridge and hard content contract; both formal profiles share prompt compilation, reference manifests, generation sets, vector freshness, asset failure semantics, and experiment infrastructure. New-version assets fail closed; rows without the new contract remain explicit legacy data and retain their old read/write behavior.

**Tech Stack:** Python 3.11, FastMCP, FastAPI/Pydantic, asyncpg/PostgreSQL JSONB, Gemini via `AIHubClient`, pgvector/NumPy cosine scoring, YAML prompt/model profiles, pytest/pytest-asyncio, Markdown-based Codex skills.

---

## Source of truth and delivery boundary

- Approved design: `docs/superpowers/specs/2026-07-15-ai-planting-agent-parity-design.md`.
- This plan ships the Agent conversation path through downloadable video segments, experiment arms, metric feedback, and deterministic next-variable advice.
- It does not add a frontend, automatic stitching, voice-over, subtitles, or a final MP4.
- Paid Seedance calls are excluded from automated verification. The last task stops after a zero-cost preflight and presents the estimated call count for a separately approved real test.

## Dirty-worktree execution guard

The relevant implementation already contains valuable uncommitted work, especially `media.py`, `pipeline_lineage.py`, `experiment_lab.py`, prompt profiles, and the untracked `triangle_match.py` / `vector_presets.py` files. A separate worktree made from `HEAD` would omit that state, so execute in the current workspace with these rules:

1. Before each task, run `git status --short` and `git diff -- <every modified tracked file in that task>`.
2. Treat every pre-existing line as user-owned; patch narrow functions instead of replacing whole files.
3. Treat untracked files named by this plan as existing user work; inspect and extend them, never recreate them from memory.
4. The commit blocks below define file scope, not permission to absorb older hunks. Use plain `git add` only for new/clean files; for a file already modified at task start, use `git add -p <path>` and select only that task's hunks. If an overlapping hunk cannot be isolated safely, leave that file unstaged and resolve the overlap before committing.
5. Verify both `git diff --cached --name-only` and `git diff --cached` before every commit. If a task exposes unrelated staged content, unstage only that path with `git restore --staged -- <path>` and restage the intended hunks; never discard working-tree content.

## File responsibility map

### New shared services

- `services/knowledge-engine/app/services/video_intent_profiles.py` — load and validate versioned planting/soft-ad behavior.
- `services/knowledge-engine/app/services/pain_solution_bridge.py` — normalize upstream facts, parse Gemini JSON, and enforce evidence eligibility.
- `services/knowledge-engine/app/services/video_content_gate.py` — build machine-readable script contracts and apply intent-specific hard gates.
- `services/knowledge-engine/app/services/video_prompt_compiler.py` — compile per-segment final prompts and enforce duration-scaled detail budgets without truncation.
- `services/knowledge-engine/app/services/media_reference_manifest.py` — resolve SKU-owned product/character references and compare expected versus provider-sent hashes.
- `services/knowledge-engine/app/services/video_generation_sets.py` — persist expected segments, selected rerenders, group gates, and atomic adoption.
- `services/knowledge-engine/app/services/video_vector_gates.py` — score final prompts and actual video, bind results to hashes/versions, and detect stale gates.
- `services/knowledge-engine/app/services/ad_metrics_normalization.py` — canonicalize rate/currency inputs and derive raw-count metrics with provenance.

### New configuration, prompts, schema, and Agent entry

- `services/knowledge-engine/config/video_intent_profiles.yaml` — profile versions, methods, metric policy, prompt budgets, and ordered iteration variables.
- `services/knowledge-engine/config/prompts/planting_pain_solution_bridge.system.md`
- `services/knowledge-engine/config/prompts/planting_pain_solution_bridge.user.md`
- `migrations/068_ai_planting_agent_parity.sql`
- `.agents/skills/ai-planting-video/` — the single canonical planting-video Agent skill and progressive-disclosure references.

### Narrowly modified integration points

- `services/knowledge-engine/app/mcp/tools/planting.py` and `app/mcp/server.py` — audited bridge and product-reference registration tools.
- `services/knowledge-engine/app/mcp/tools/media.py` — creative-pack contract, arm-bound character sheets, formal preflight, provider execution, and truthful failure results.
- `services/knowledge-engine/app/services/pipeline_lineage.py` — new JSONB fields, product refs, generation-set asset linkage, and metric admission.
- `services/knowledge-engine/app/services/experiment_lab.py` — planting A3 policy, strict same-round arm checks, pooled evaluation, lock rules, and next variable.
- `services/knowledge-engine/app/services/ad_metrics_validation.py` — new raw fields and canonical validation metadata.
- `services/knowledge-engine/app/mcp/tools/pipeline.py` and `app/routers/mcp_exec.py` — request/response contracts and service-side enforcement.
- `services/knowledge-engine/config/prompts/creative_pack.video_planting.system.md` — structured bridge/contract fields while retaining `M1/M2 × M3–M9`.
- `services/knowledge-engine/config/prompts/video_model_profiles/seedance.md` — document API-segment capacity semantics without overwriting the existing whole-video director-brief section.
- `AGENTS.md`, `CLAUDE.md`, `.agents/skills/ai-soft-ad-video/`, `.claude/skills/soft-ad-ai-video/`, and `.claude/skills/sku-pipeline/SKILL.md` — unambiguous routing and compatibility.

---

### Task 1: Add versioned video intent profiles

**Files:**
- Create: `services/knowledge-engine/config/video_intent_profiles.yaml`
- Create: `services/knowledge-engine/app/services/video_intent_profiles.py`
- Create: `services/knowledge-engine/tests/test_video_intent_profiles.py`

- [ ] **Step 1: Write failing profile tests**

```python
from app.services.video_intent_profiles import get_video_intent_profile


def test_planting_and_soft_ad_do_not_share_method_or_north_star():
    planting = get_video_intent_profile("planting")
    soft_ad = get_video_intent_profile("soft_ad")
    assert planting.kind == "video_planting"
    assert planting.bridge_extractor == "generate_planting_pain_solution_bridge"
    assert planting.north_star == "a3_ratio"
    assert planting.method == "M1/M2_x_M3-M9"
    assert planting.prompt_profile == "creative_pack.video_planting"
    assert planting.metric_policy == "planting_a3_v1"
    assert soft_ad.kind == "video_soft_ad"
    assert soft_ad.bridge_extractor is None
    assert soft_ad.north_star == "completion_rate"
    assert soft_ad.method == "soft_ad_life_flow"
    assert soft_ad.prompt_profile == "creative_pack.video_soft_ad"


def test_seedance_prompt_budget_and_policy_are_versioned():
    profile = get_video_intent_profile("planting")
    assert profile.prompt_budget.segment_max_seconds == 15
    assert profile.prompt_budget.min_chars_per_second == 50
    assert profile.prompt_budget.recommended_chars_per_second == (60, 87)
    assert profile.prompt_budget.max_chars_per_second == 107
    assert profile.evaluation_policy["max_exposure_ratio"] == 3.0
    assert profile.evaluation_policy["rate_scale"] == "0-1"
    assert profile.evaluation_policy["currency"] == "CNY"
    assert profile.evaluation_policy["play_3s_floor"] is None
```

- [ ] **Step 2: Run the tests and confirm the missing module failure**

Run from `services/knowledge-engine`:

```powershell
python -m pytest tests/test_video_intent_profiles.py -q
```

Expected: collection fails with `ModuleNotFoundError: app.services.video_intent_profiles`.

- [ ] **Step 3: Add the profile configuration**

```yaml
version: "2026-07-15.v1"
profiles:
  planting:
    kind: video_planting
    intent: planting
    method: M1/M2_x_M3-M9
    bridge_extractor: generate_planting_pain_solution_bridge
    content_gate: planting_v1
    prompt_profile: creative_pack.video_planting
    metric_policy: planting_a3_v1
    north_star: a3_ratio
    diagnostic_metrics: [cpm, play_3s_rate, completion_rate]
    vector_threshold_100: 70
    key_vector_dimensions:
      - audience_scene
      - pain_conflict
      - product_action
      - result_relief
      - justification_evidence
    prompt_budget:
      segment_max_seconds: 15
      min_chars_per_second: 50
      recommended_chars_per_second: [60, 87]
      max_chars_per_second: 107
    evaluation_policy:
      play_3s_floor: null
      completion_floor: null
      a3_floor: null
      cpm_ceiling: null
      min_impressions: null
      min_a3_eligible_users: null
      max_exposure_ratio: 3.0
      rate_scale: "0-1"
      currency: CNY
    iteration_candidates:
      play_3s_rate: [opening_hook_3s, presentation_motif]
      completion_rate: [story_pace, justification_density]
      a3_ratio: [pain_scene_bridge, justification_module]
    global_iteration_order:
      - pain_scene_bridge
      - idea_seed
      - opening_hook_3s
      - selling_point_set
      - scene
      - emotion
      - story_pace
      - justification_density
      - justification_module
      - presentation_motif
      - edit_pace
      - visual_vector
      - bgm
      - target_model
  soft_ad:
    kind: video_soft_ad
    intent: soft_ad
    method: soft_ad_life_flow
    bridge_extractor: null
    content_gate: soft_ad_v1
    prompt_profile: creative_pack.video_soft_ad
    metric_policy: soft_ad_completion_v1
    north_star: completion_rate
    diagnostic_metrics: [play_3s_rate, completion_rate]
    vector_threshold_100: 70
    key_vector_dimensions: [audience_scene, product_action, watchability]
    prompt_budget:
      segment_max_seconds: 15
      min_chars_per_second: 50
      recommended_chars_per_second: [60, 87]
      max_chars_per_second: 107
    evaluation_policy:
      play_3s_floor: null
      completion_floor: null
      a3_floor: null
      cpm_ceiling: null
      min_impressions: null
      min_a3_eligible_users: null
      max_exposure_ratio: 3.0
      rate_scale: "0-1"
      currency: CNY
    iteration_candidates:
      play_3s_rate: [opening_hook_3s, presentation_motif]
      completion_rate: [story_pace, edit_pace]
    global_iteration_order:
      - idea_seed
      - opening_hook_3s
      - selling_point_set
      - scene
      - emotion
      - story_pace
      - edit_pace
      - presentation_motif
      - visual_vector
      - bgm
      - target_model
```

The null production thresholds are intentional: the approved design supplied formulas and ordering but no business target values. Missing thresholds must later produce `diagnostic_policy_missing`, not invented defaults.

- [ ] **Step 4: Implement a typed, cached loader that returns defensive copies**

```python
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_PROFILE_PATH = Path(__file__).resolve().parents[2] / "config" / "video_intent_profiles.yaml"


@dataclass(frozen=True)
class PromptBudgetProfile:
    segment_max_seconds: int
    min_chars_per_second: int
    recommended_chars_per_second: tuple[int, int]
    max_chars_per_second: int


@dataclass(frozen=True)
class VideoIntentProfile:
    version: str
    intent: str
    kind: str
    method: str
    bridge_extractor: str | None
    content_gate: str
    prompt_profile: str
    metric_policy: str
    north_star: str
    diagnostic_metrics: tuple[str, ...]
    vector_threshold_100: float
    key_vector_dimensions: tuple[str, ...]
    prompt_budget: PromptBudgetProfile
    evaluation_policy: dict[str, Any]
    iteration_candidates: dict[str, tuple[str, ...]]
    global_iteration_order: tuple[str, ...]


@lru_cache(maxsize=1)
def _load_profiles() -> dict[str, Any]:
    raw = yaml.safe_load(_PROFILE_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw.get("version") or not isinstance(raw.get("profiles"), dict):
        raise ValueError("video_intent_profiles_invalid")
    return raw


def get_video_intent_profile(intent: str) -> VideoIntentProfile:
    raw = _load_profiles()
    item = deepcopy(raw["profiles"].get(intent))
    if not isinstance(item, dict):
        raise ValueError(f"video_intent_profile_not_found:{intent}")
    budget = item["prompt_budget"]
    rec = tuple(int(v) for v in budget["recommended_chars_per_second"])
    if len(rec) != 2 or rec[0] > rec[1]:
        raise ValueError(f"video_intent_profile_budget_invalid:{intent}")
    return VideoIntentProfile(
        version=str(raw["version"]), intent=str(item["intent"]), kind=str(item["kind"]),
        method=str(item["method"]), bridge_extractor=item.get("bridge_extractor"),
        content_gate=str(item["content_gate"]), prompt_profile=str(item["prompt_profile"]),
        metric_policy=str(item["metric_policy"]), north_star=str(item["north_star"]),
        diagnostic_metrics=tuple(item["diagnostic_metrics"]),
        vector_threshold_100=float(item["vector_threshold_100"]),
        key_vector_dimensions=tuple(item["key_vector_dimensions"]),
        prompt_budget=PromptBudgetProfile(
            segment_max_seconds=int(budget["segment_max_seconds"]),
            min_chars_per_second=int(budget["min_chars_per_second"]),
            recommended_chars_per_second=(rec[0], rec[1]),
            max_chars_per_second=int(budget["max_chars_per_second"]),
        ),
        evaluation_policy=deepcopy(item["evaluation_policy"]),
        iteration_candidates={k: tuple(v) for k, v in item["iteration_candidates"].items()},
        global_iteration_order=tuple(item["global_iteration_order"]),
    )
```

- [ ] **Step 5: Run tests**

```powershell
python -m pytest tests/test_video_intent_profiles.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit only the profile unit**

```powershell
git add services/knowledge-engine/config/video_intent_profiles.yaml services/knowledge-engine/app/services/video_intent_profiles.py services/knowledge-engine/tests/test_video_intent_profiles.py
git diff --cached --name-only
git commit -m "feat(video): add versioned planting and soft-ad profiles"
```

---

### Task 2: Build the structured planting pain-solution bridge tool

**Files:**
- Create: `services/knowledge-engine/app/services/pain_solution_bridge.py`
- Create: `services/knowledge-engine/app/mcp/tools/planting.py`
- Create: `services/knowledge-engine/config/prompts/planting_pain_solution_bridge.system.md`
- Create: `services/knowledge-engine/config/prompts/planting_pain_solution_bridge.user.md`
- Create: `services/knowledge-engine/tests/test_pain_solution_bridge.py`
- Modify: `services/knowledge-engine/config/tool_models.yaml`
- Modify: `services/knowledge-engine/app/mcp/server.py`
- Modify: `services/knowledge-engine/app/mcp/doctor.py`

- [ ] **Step 1: Write failing evidence and mocked-model tests**

```python
import pytest

from app.services.pain_solution_bridge import (
    canonical_upstream_fact_hash,
    validate_pain_solution_bridge,
)


VALID = {
    "audience_segment": "工作日晚归、要快速做一家人晚饭的双职工父母",
    "portrait_evidence": [{"source": "portrait", "field": "生活状态", "value": "下班后做饭时间紧"}],
    "pack_calibration_evidence": [{"field": "城市层级", "value": "新一线"}],
    "trigger_scene": "周三19:10，母亲刚进家门，孩子在餐桌边催饭",
    "pain_point": "调味步骤多，做一道菜要反复找瓶子和试味",
    "pain_consequence": "晚饭更晚，家人都在等",
    "product_action": "把当前 SKU 倒入锅中完成调味",
    "visible_result": "一次调味后菜色和入口反馈稳定，直接装盘",
    "product_evidence": [{"source": "matrix", "field": "1.1", "value": "已采纳的真实卖点"}],
    "belief_shift": "它能解决我赶晚饭时的具体调味麻烦",
    "relevance_module": "M1",
    "justification_module": "M4",
}


def test_pack_evidence_cannot_substitute_portrait_pain_evidence():
    bridge = {**VALID, "portrait_evidence": []}
    result = validate_pain_solution_bridge(bridge)
    assert result["ok"] is False
    assert result["error"] == "pain_solution_bridge_invalid"
    assert "portrait_evidence" in result["missing_or_invalid"]


def test_product_action_requires_sku_or_matrix_evidence():
    result = validate_pain_solution_bridge({**VALID, "product_evidence": []})
    assert result["ok"] is False
    assert "product_evidence" in result["missing_or_invalid"]


def test_upstream_fact_hash_is_key_order_independent():
    a = canonical_upstream_fact_hash({"portrait": {"b": 2, "a": 1}, "sku": {"id": "S"}})
    b = canonical_upstream_fact_hash({"sku": {"id": "S"}, "portrait": {"a": 1, "b": 2}})
    assert a == b
```

Add an async tool test that monkeypatches `AIHubClient.chat`, returns a JSON array containing `VALID`, and asserts the request uses `gemini-3.1-pro-preview`, temperature `0.2`, and returns both the bridge and a trace. Add a second test where the model raises and assert `ok=false` with no Flash retry.

- [ ] **Step 2: Run the tests and confirm failure**

```powershell
python -m pytest tests/test_pain_solution_bridge.py -q
```

Expected: collection fails because the bridge module and tool do not exist.

- [ ] **Step 3: Implement canonical hashing and deterministic validation**

```python
import hashlib
import json
from typing import Any

_REQUIRED_TEXT = (
    "audience_segment", "trigger_scene", "pain_point", "pain_consequence",
    "product_action", "visible_result", "belief_shift",
)
_VALID_RELEVANCE = {"M1", "M2"}
_VALID_JUSTIFICATION = {f"M{i}" for i in range(3, 10)}


def canonical_upstream_fact_hash(facts: dict[str, Any]) -> str:
    payload = json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_pain_solution_bridge(bridge: dict[str, Any]) -> dict[str, Any]:
    bad = [key for key in _REQUIRED_TEXT if not str(bridge.get(key) or "").strip()]
    portrait = bridge.get("portrait_evidence") or []
    product = bridge.get("product_evidence") or []
    if not any(e.get("source") in {"portrait", "record"} and e.get("field") and e.get("value") for e in portrait):
        bad.append("portrait_evidence")
    if not any(e.get("source") in {"sku", "matrix"} and e.get("field") and e.get("value") for e in product):
        bad.append("product_evidence")
    if bridge.get("relevance_module") not in _VALID_RELEVANCE:
        bad.append("relevance_module")
    if bridge.get("justification_module") not in _VALID_JUSTIFICATION:
        bad.append("justification_module")
    return ({"ok": False, "error": "pain_solution_bridge_invalid", "missing_or_invalid": sorted(set(bad))}
            if bad else {"ok": True, "bridge": bridge})
```

The extractor must normalize the upstream bundle into four separate sections: SKU facts, adopted matrix evidence, portrait/record evidence, and pack calibration. It must never merge pack calibration into the eligible portrait evidence array.

- [ ] **Step 4: Add external prompts and the fixed model entry**

The system prompt must require JSON only, the exact approved bridge keys, source-qualified evidence, one `M1`/`M2` module, and one `M3`–`M9` module. It must explicitly say that pack evidence can only calibrate casting, language, and visual texture.

```yaml
generate_planting_pain_solution_bridge:
  provider: gemini
  model: gemini-3.1-pro-preview
  temperature: 0.2
  max_tokens: 4000
```

The user prompt must render the four upstream sections and ask for exactly two candidate bridge objects so both first-round scripts share facts while varying only `pain_scene_bridge` expression. After validating each object, compare them and allow differences only in `trigger_scene`, `pain_point`, and `pain_consequence`; `audience_segment`, both evidence arrays, `product_action`, `visible_result`, `belief_shift`, and both method modules must be byte-for-byte equal after canonical normalization. Otherwise return `pain_solution_bridge_invalid` with `cross_candidate_drift`.

- [ ] **Step 5: Add the audited MCP tool with fail-closed model behavior**

```python
@tool_with_audit(mcp, require_approval=False)
async def generate_planting_pain_solution_bridge(
    sku_id: str,
    audience_record_id: str,
    portrait_id: str,
    audience_pack_id: str | None = None,
) -> dict:
    upstream = await load_planting_bridge_context(
        sku_id=sku_id, audience_record_id=audience_record_id,
        portrait_id=portrait_id, audience_pack_id=audience_pack_id,
    )
    if not upstream["ok"]:
        return upstream
    cfg = get_model_for_tool("generate_planting_pain_solution_bridge")
    if cfg.get("model") != "gemini-3.1-pro-preview":
        return {"ok": False, "error": "pain_solution_bridge_model_misconfigured"}
    try:
        response = await AIHubClient(timeout=360.0).chat(
            messages=render_bridge_messages(upstream["facts"]),
            provider=cfg.get("provider", "gemini"), model=cfg["model"],
            temperature=float(cfg["temperature"]), max_tokens=int(cfg["max_tokens"]),
            enforce_human_voice=False,
        )
    except Exception as exc:
        return {"ok": False, "error": "pain_solution_bridge_generation_failed", "detail": str(exc)}
    return parse_and_validate_bridge_response(response, upstream["facts"], cfg)
```

`load_planting_bridge_context` must return `upstream_lineage_incomplete` if the SKU, adopted matrix, audience record, or portrait needed to support the bridge is missing. `parse_and_validate_bridge_response` must include `upstream_fact_hash`, model/provider/temperature, and the rendered prompt in `trace`.

- [ ] **Step 6: Register the module and doctor contract**

Import `app.mcp.tools.planting` in `app/mcp/server.py`, add `generate_planting_pain_solution_bridge` to `_wanted_tools()`, and update only the doctor assertion that derives the live count from that set. Do not hand-edit a second numeric count in test code.

- [ ] **Step 7: Run the focused tests and doctor registration test**

```powershell
python -m pytest tests/test_pain_solution_bridge.py tests/test_tool_models_api.py tests/test_mcp_agent_meta.py -q
```

Expected: all pass; the mocked call shows one Pro request and no fallback call.

- [ ] **Step 8: Commit the bridge unit**

```powershell
git add services/knowledge-engine/app/services/pain_solution_bridge.py services/knowledge-engine/app/mcp/tools/planting.py services/knowledge-engine/config/prompts/planting_pain_solution_bridge.system.md services/knowledge-engine/config/prompts/planting_pain_solution_bridge.user.md services/knowledge-engine/config/tool_models.yaml services/knowledge-engine/app/mcp/server.py services/knowledge-engine/app/mcp/doctor.py services/knowledge-engine/tests/test_pain_solution_bridge.py
git diff --cached --name-only
git commit -m "feat(planting): add evidence-grounded pain solution bridge"
```

---

### Task 3: Add the additive schema and preserve the final experiment view contract

**Files:**
- Create: `migrations/068_ai_planting_agent_parity.sql`
- Create: `services/knowledge-engine/tests/test_planting_schema.py`

- [ ] **Step 1: Write a failing database schema test**

```python
import pytest

from app.database import get_pool


@pytest.mark.asyncio
async def test_planting_schema_has_contract_policy_and_generation_sets():
    pool = get_pool()
    script_col = await pool.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='pipeline' "
        "AND table_name='scripts' AND column_name='content_contract'"
    )
    policy_col = await pool.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='pipeline' "
        "AND table_name='experiments' AND column_name='evaluation_policy'"
    )
    set_table = await pool.fetchval("SELECT to_regclass('pipeline.video_generation_sets')::text")
    asset_col = await pool.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='pipeline' "
        "AND table_name='assets' AND column_name='generation_set_id'"
    )
    assert (script_col, policy_col, set_table, asset_col) == (1, 1, "pipeline.video_generation_sets", 1)
```

Also assert `v_experiment_round_results` still exposes `production_mode`, `impressions_sum`, and `predicted_match_score`, followed by the new pooled metric columns. This protects migrations 054, 064, 065, and 066 from view-column drift.

- [ ] **Step 2: Run the schema test and confirm failure**

```powershell
python -m pytest tests/test_planting_schema.py -q
```

Expected: the new columns/table assertions fail.

- [ ] **Step 3: Write migration 068 as an additive migration**

```sql
ALTER TABLE pipeline.scripts
    ADD COLUMN IF NOT EXISTS content_contract JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE pipeline.experiments
    ADD COLUMN IF NOT EXISTS evaluation_policy JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS pipeline.video_generation_sets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sku_id VARCHAR(64) NOT NULL,
    script_id UUID NOT NULL REFERENCES pipeline.scripts(id) ON DELETE CASCADE,
    experiment_id UUID NOT NULL REFERENCES pipeline.experiments(id) ON DELETE CASCADE,
    experiment_arm_id UUID NOT NULL REFERENCES pipeline.experiment_arms(id) ON DELETE CASCADE,
    expected_segment_manifest JSONB NOT NULL DEFAULT '[]'::jsonb,
    selected_assets JSONB NOT NULL DEFAULT '[]'::jsonb,
    reference_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    pre_video_group_gate JSONB NOT NULL DEFAULT '{}'::jsonb,
    post_video_group_gate JSONB NOT NULL DEFAULT '{}'::jsonb,
    profile_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT video_generation_sets_status_check
        CHECK (status IN ('draft', 'ready', 'adopted', 'discarded'))
);

ALTER TABLE pipeline.assets
    ADD COLUMN IF NOT EXISTS generation_set_id UUID
        REFERENCES pipeline.video_generation_sets(id) ON DELETE SET NULL;

ALTER TABLE pipeline.assets DROP CONSTRAINT IF EXISTS assets_type_check;
ALTER TABLE pipeline.assets ADD CONSTRAINT assets_type_check
    CHECK (asset_type IN ('image', 'image_first', 'image_last', 'video', 'character_sheet', 'product_reference'));

CREATE INDEX IF NOT EXISTS idx_video_generation_sets_arm
    ON pipeline.video_generation_sets (experiment_arm_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assets_generation_set
    ON pipeline.assets (generation_set_id, scene_no) WHERE generation_set_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_product_reference_file
    ON pipeline.assets (file_url) WHERE asset_type = 'product_reference' AND status <> 'discarded';
```

Recreate `pipeline.v_experiment_round_results` from the exact final shape in migration 066, preserving the existing column order through `predicted_match_score`. Append these columns after it:

```sql
a3_numerator_sum, a3_denominator_sum, a3_ratio_pooled,
spend_sum, cpm_pooled,
play_3s_sum, play_3s_rate_pooled,
completion_numerator_sum, completion_denominator_sum,
completion_denominator_type, completion_rate_pooled,
metric_coverage_complete
```

The view's asset eligibility predicate must be exactly equivalent to:

```sql
a.status IN ('published', 'adopted')
AND COALESCE((a.ad_metrics #>> '{_validation,suspect}')::boolean, false) = false
AND (
    a.generation_set_id IS NULL
    OR EXISTS (
        SELECT 1
        FROM pipeline.video_generation_sets gs
        WHERE gs.id = a.generation_set_id
          AND gs.status = 'adopted'
          AND COALESCE((gs.post_video_group_gate ->> 'pass')::boolean, false) = true
          AND a.id::text IN (SELECT jsonb_array_elements_text(gs.selected_assets))
    )
)
```

Use safe numeric regex casts for every JSONB value. Compute pooled values with `NULLIF(sum(denominator), 0)`, never `avg(rate)`. Retain legacy `north_star_avg` for non-planting compatibility; for `intent='planting'`, set it to the pooled A3 value so existing readers rank the correct north star.

- [ ] **Step 4: Apply migration 068 to the development database**

From the repository root:

```powershell
Get-Content migrations/068_ai_planting_agent_parity.sql -Raw | docker exec -i omni-postgres psql -v ON_ERROR_STOP=1 -U omni_user -d omni_vibe_db
```

Expected: `ALTER TABLE`, `CREATE TABLE`, `CREATE INDEX`, and `CREATE VIEW` complete without error.

- [ ] **Step 5: Run schema and dependent-view tests**

```powershell
python -m pytest tests/test_planting_schema.py tests/test_match_vectors.py -q
```

Expected: schema and view compatibility tests pass with no SQL/view-shape error.

- [ ] **Step 6: Commit the schema unit**

```powershell
git add migrations/068_ai_planting_agent_parity.sql services/knowledge-engine/tests/test_planting_schema.py
git diff --cached --name-only
git commit -m "feat(pipeline): add planting contracts and generation sets"
```

---

### Task 4: Enforce the planting script content contract and hard gate

**Files:**
- Create: `services/knowledge-engine/app/services/video_content_gate.py`
- Create: `services/knowledge-engine/tests/test_planting_content_gate.py`
- Modify: `services/knowledge-engine/app/mcp/tools/media.py`
- Modify: `services/knowledge-engine/app/services/pipeline_lineage.py`
- Modify: `services/knowledge-engine/app/services/triangle_match.py`
- Modify: `services/knowledge-engine/app/services/vector_presets.py`
- Modify: `services/knowledge-engine/config/prompts/creative_pack.video_planting.system.md`
- Modify: `services/knowledge-engine/tests/test_triangle_match.py`
- Modify: `services/knowledge-engine/tests/test_vector_presets.py`
- Modify: `services/knowledge-engine/tests/test_creative_pack_batch.py`

- [ ] **Step 1: Snapshot the existing overlapping changes**

```powershell
git diff -- services/knowledge-engine/app/mcp/tools/media.py services/knowledge-engine/app/services/pipeline_lineage.py services/knowledge-engine/config/prompts/creative_pack.video_planting.system.md
git status --short services/knowledge-engine/app/services/triangle_match.py services/knowledge-engine/app/services/vector_presets.py
```

Expected: the command shows pre-existing work. Keep that diff open while applying narrow patches.

- [ ] **Step 2: Write failing gate tests**

```python
import pytest

from app.services.video_content_gate import evaluate_planting_content_gate


PASSING = {
    "portrait_scene_alignment_score": 80,
    "pain_specificity_score": 80,
    "product_solution_fit_score": 80,
    "product_action_visible": True,
    "solution_result_visible": True,
    "justification_grounded": True,
    "belief_shift_present": True,
    "hard_cta_present": False,
    "price_promotion_present": False,
    "fabricated_qualification_present": False,
    "fake_testimonial_present": False,
}
TRIANGLE = {"overall_score_100": 70, "edges_100": {"audience_content": 70, "product_content": 70}}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("portrait_scene_alignment_score", 79),
        ("pain_specificity_score", 79),
        ("product_solution_fit_score", 79),
        ("product_action_visible", False),
        ("solution_result_visible", False),
        ("justification_grounded", False),
        ("belief_shift_present", False),
        ("hard_cta_present", True),
        ("price_promotion_present", True),
        ("fabricated_qualification_present", True),
        ("fake_testimonial_present", True),
    ],
)
def test_each_planting_gate_dimension_blocks_downstream_media(field, value):
    gate = evaluate_planting_content_gate({**PASSING, field: value}, TRIANGLE)
    assert gate["pass"] is False
    assert field in gate["failed_checks"]


def test_triangle_key_edges_and_total_are_hard_gates():
    gate = evaluate_planting_content_gate(PASSING, {
        "overall_score_100": 70,
        "edges_100": {"audience_content": 69, "product_content": 70},
    })
    assert gate["pass"] is False
    assert "audience_content" in gate["failed_checks"]
```

Add an async media test that feeds a valid bridge into `generate_creative_pack(kind='video_planting', intent='planting')`, mocks the LLM metrics, and asserts a failed gate still saves a draft script but returns `ok=false`, `error='planting_content_gate_failed'`, and no `generate_character_sheets` next step.

- [ ] **Step 3: Run focused tests and confirm failure**

```powershell
python -m pytest tests/test_planting_content_gate.py tests/test_triangle_match.py tests/test_vector_presets.py -q
```

Expected: the new service import or hard-gate assertions fail.

- [ ] **Step 4: Implement the content-contract service**

```python
def evaluate_planting_content_gate(metrics: dict, triangle: dict) -> dict:
    failed: list[str] = []
    for field in (
        "portrait_scene_alignment_score", "pain_specificity_score", "product_solution_fit_score",
    ):
        if float(metrics.get(field, -1)) < 80:
            failed.append(field)
    for field in (
        "product_action_visible", "solution_result_visible",
        "justification_grounded", "belief_shift_present",
    ):
        if metrics.get(field) is not True:
            failed.append(field)
    for field in (
        "hard_cta_present", "price_promotion_present",
        "fabricated_qualification_present", "fake_testimonial_present",
    ):
        if metrics.get(field) is not False:
            failed.append(field)
    if float(triangle.get("overall_score_100", -1)) < 70:
        failed.append("script_vector_overall")
    for edge in ("audience_content", "product_content"):
        if float((triangle.get("edges_100") or {}).get(edge, -1)) < 70:
            failed.append(edge)
    return {"pass": not failed, "failed_checks": failed, "gate_version": "planting_v1"}


def build_content_contract(*, profile, bridge, metrics, triangle, prompt_blocks) -> dict:
    return {
        "version": "2026-07-15.v1",
        "intent": profile.intent,
        "kind": profile.kind,
        "profile_version": profile.version,
        "pain_solution_bridge": bridge,
        "method": {
            "relevance_module": bridge["relevance_module"],
            "justification_module": bridge["justification_module"],
        },
        "content_gate": evaluate_planting_content_gate(metrics, triangle),
        "script_vector_gate": triangle,
        "prompt_blocks": prompt_blocks,
    }
```

Add `build_soft_ad_content_contract(profile, metrics, triangle, prompt_blocks)` in the same service. It writes the same contract/profile/hash envelope but stores the existing soft-ad watchability/three-second/content gate and has no pain bridge. This gives newly generated formal soft-ad scripts the shared media/generation-set kernel without applying planting's 80-point pain fields. Add `test_soft_ad_keeps_completion_rate_and_skips_planting_gate` to prove the separation.

Add `assert_script_ready_for_media(script, experiment_arm_id)` to enforce: contract version present, script status `adopted`, content gate pass, arm exists, arm script matches, and arm/experiment SKU/intent/track match. Return the approved error codes instead of raising generic exceptions.

- [ ] **Step 5: Extend the planting prompt and creative-pack signature**

Add `pain_solution_bridge: dict | None = None` to both `_creative_pack_one` and public `generate_creative_pack`. For formal planting (`kind='video_planting'`, `intent='planting'`) reject a missing or invalid bridge with `pain_solution_bridge_invalid`. For formal soft-ad, build its own new-version contract without a bridge. Keep legacy `intent='generic'` readable and mark it `legacy_warning`; do not silently synthesize the bridge.

Require the planting prompt's `metrics_json` to emit all 11 structured content-gate fields tested above and keep the existing `M1/M2 × M3–M9` method. Inject the selected structured bridge as a compact JSON section; do not paste the entire audience CSV or methodology prose into the video prompt blocks.

Generate the two first-round candidates with two Agent calls, not `num_variants` temperature drift:

```python
experiment_context={
    "baseline": fixed_baseline,
    "sweep": {"variable": "pain_scene_bridge", "value": bridge_value},
}
```

- [ ] **Step 6: Generalize existing vector helpers instead of duplicating them**

Modify `triangle_match.triangle_gate` to accept thresholds from the intent profile and expose both 0–1 and 0–100 fields. Remove soft-ad-only wording from return keys. Keep `audit_script_triangle` as the script-level gate; do not use it later as the final-prompt or actual-video gate.

Modify `vector_presets.build_creative_vector_preset` to accept the intent profile and current lineage anchors. Remove hard-coded soy-sauce, SKU002, or “舒适休闲” defaults; if lineage lacks a fact, return an explicit missing anchor instead of a cross-SKU fallback.

- [ ] **Step 7: Persist and retrieve `content_contract`**

Add a required keyword argument to new-version saves:

```python
async def save_creative_pack(
    *,
    sku_id: str,
    kind: str,
    script_md: str,
    audience_record_id: str | None = None,
    audience_pack_id: str | None = None,
    audience_run_id: str | None = None,
    matrix_run_id: str | None = None,
    hooks: list | None = None,
    scenes: list | None = None,
    character_sheets: list | None = None,
    extra_context: str | None = None,
    model_provider: str | None = None,
    model: str | None = None,
    final_prompt: str | None = None,
    cost_estimate: str | None = None,
    portrait_id: str | None = None,
    intent: str | None = None,
    parent_script_id: str | None = None,
    notes: str | None = None,
    content_contract: dict | None = None,
) -> str | None:
    contract = content_contract or {}
```

Add `content_contract` to the existing `INSERT INTO pipeline.scripts` column list and pass `json.dumps(contract)` through an explicit `$N::jsonb` value before `RETURNING id`.

Include `content_contract` in `get_creative_pack`, `list_creative_packs`, and `pipeline_get_script` results. A failed formal planting gate is saved with `status='draft'`; downstream media admission reads the structured field, not `script_md` or warning text.

- [ ] **Step 8: Run content and compatibility tests**

```powershell
python -m pytest tests/test_planting_content_gate.py tests/test_triangle_match.py tests/test_vector_presets.py tests/test_audience_content_bridge.py tests/test_creative_pack_batch.py tests/test_mcp_media.py -q
```

Expected: all pass; formal planting fails closed and soft-ad/generic legacy paths retain their profile-specific behavior.

- [ ] **Step 9: Commit the contract unit**

```powershell
git add services/knowledge-engine/app/services/video_content_gate.py services/knowledge-engine/tests/test_planting_content_gate.py services/knowledge-engine/app/mcp/tools/media.py services/knowledge-engine/app/services/pipeline_lineage.py services/knowledge-engine/app/services/triangle_match.py services/knowledge-engine/app/services/vector_presets.py services/knowledge-engine/config/prompts/creative_pack.video_planting.system.md services/knowledge-engine/tests/test_triangle_match.py services/knowledge-engine/tests/test_vector_presets.py services/knowledge-engine/tests/test_creative_pack_batch.py
git diff --cached --name-only
git commit -m "feat(planting): enforce script content contract"
```

---

### Task 5: Snapshot planting experiment policy and enforce same-round arm lineage

**Files:**
- Create: `services/knowledge-engine/tests/test_planting_experiment_policy.py`
- Modify: `services/knowledge-engine/app/services/experiment_lab.py`
- Modify: `services/knowledge-engine/app/mcp/tools/experiment.py`
- Modify: `services/knowledge-engine/tests/test_experiment_attach_and_batch.py`

- [ ] **Step 1: Write failing policy and arm-contract tests**

```python
import pytest

from app.services import experiment_lab as lab


@pytest.mark.asyncio
async def test_planting_experiment_snapshots_a3_policy(planting_portrait_fixture):
    result = await lab.create_experiment(
        sku_id=planting_portrait_fixture.sku_id,
        intent="planting",
        portrait_id=planting_portrait_fixture.portrait_id,
        track="ai_video",
    )
    assert result["ok"] is True
    assert result["experiment"]["north_star_metric"] == "a3_ratio"
    policy = result["experiment"]["evaluation_policy"]
    assert policy["profile_version"] == "2026-07-15.v1"
    assert policy["max_exposure_ratio"] == 3.0
    assert policy["currency"] == "CNY"


@pytest.mark.asyncio
async def test_explicit_business_thresholds_are_validated_and_snapshotted(planting_portrait_fixture):
    result = await lab.create_experiment(
        sku_id=planting_portrait_fixture.sku_id,
        intent="planting",
        portrait_id=planting_portrait_fixture.portrait_id,
        track="ai_video",
        evaluation_policy_overrides={
            "play_3s_floor": 0.35,
            "completion_floor": 0.18,
            "a3_floor": 0.02,
            "cpm_ceiling": 80.0,
            "min_impressions": 1000,
            "min_a3_eligible_users": 200,
        },
    )
    assert result["ok"] is True
    assert result["experiment"]["evaluation_policy"]["a3_floor"] == 0.02


@pytest.mark.asyncio
async def test_second_planting_candidate_requires_explicit_experiment_and_round(two_planting_scripts):
    first = await lab.adopt_script_as_arm(
        script_id=two_planting_scripts[0],
        variable_value="先呈现晚归催饭，再给解决动作",
        swept_variable="pain_scene_bridge",
    )
    assert first["ok"] is True
    second = await lab.adopt_script_as_arm(
        script_id=two_planting_scripts[1],
        variable_value="先呈现反复试味，再给解决动作",
    )
    assert second["ok"] is False
    assert second["error"] == "planting_second_arm_requires_explicit_round"
    accepted = await lab.adopt_script_as_arm(
        script_id=two_planting_scripts[1],
        variable_value="先呈现反复试味，再给解决动作",
        swept_variable="pain_scene_bridge",
        experiment_id=first["experiment_id"],
        round_no=first["arm"]["round_no"],
    )
    assert accepted["ok"] is True
    assert accepted["arm"]["round_no"] == first["arm"]["round_no"]
```

Add parameterized mismatches for SKU, script intent, `ai_video` track, round, and `swept_variable`. Add a soft-ad regression proving its existing same-experiment implicit append remains accepted and its north star remains `completion_rate`.

- [ ] **Step 2: Run tests and observe old completion-rate/loose-arm behavior**

```powershell
python -m pytest tests/test_planting_experiment_policy.py tests/test_experiment_attach_and_batch.py -q
```

Expected: planting still reports `completion_rate`; the implicit second arm is accepted.

- [ ] **Step 3: Change only planting's north star and extend its variable vocabulary**

```python
INTENT_NORTH_STAR = {
    "planting": ("a3_ratio", "higher_better", ["cpm", "completion_rate", "play_3s_rate"]),
    "harvest": ("cvr", "higher_better", ["roi", "gmv"]),
    "soft_ad": ("completion_rate", "higher_better", ["play_3s_rate"]),
    "hard_ad": ("cvr", "higher_better", ["roi", "gmv"]),
}
```

Add `pain_scene_bridge`, `presentation_motif`, `justification_density`, and `justification_module` labels to the valid variable set. Keep the global soft-ad ordering intact; planting's recommendation order comes from its intent profile in Task 10.

- [ ] **Step 4: Snapshot the versioned evaluation policy on experiment creation**

```python
profile = get_video_intent_profile(intent)
evaluation_policy = {
    **profile.evaluation_policy,
    "profile_version": profile.version,
    "intent": intent,
    "north_star": profile.north_star,
    "diagnostic_metrics": list(profile.diagnostic_metrics),
}
```

Add `evaluation_policy_overrides: dict | None = None` to the service and MCP `experiment_create` signatures. Permit only the six business threshold keys shown in the test; validate rates as 0–1, money/count thresholds as non-negative, and keep `max_exposure_ratio=3`, `rate_scale='0-1'`, currency `CNY`, and profile version immutable. This lets the Agent snapshot user-approved business thresholds without inventing them. Omitting overrides remains valid and later produces `diagnostic_policy_missing` for automatic next-variable advice.

Insert that object into `pipeline.experiments.evaluation_policy`, and return it from create/get/list/status. A custom `north_star_metric` may still be accepted where the existing API allows it, but a formal planting Agent call must use `a3_ratio`; the skill never overrides it.

- [ ] **Step 5: Make formal planting arm checks hard errors**

In `attach_arm`, load the script and experiment together and require:

```python
if formal_planting:
    if script_intent != "planting" or experiment_intent != "planting":
        return {"ok": False, "error": "experiment_arm_missing_or_mismatch", "field": "intent"}
    if script_track != "ai_video" or experiment_track != "ai_video":
        return {"ok": False, "error": "experiment_arm_missing_or_mismatch", "field": "track"}
    if existing_round and existing_round["swept_variable"] != swept_variable:
        return {"ok": False, "error": "experiment_arm_missing_or_mismatch", "field": "swept_variable"}
```

In `adopt_script_as_arm`, when a formal planting open round already has one arm, reject the second candidate unless the call explicitly supplies both `experiment_id` and `round_no`. Validate those values before changing script status. Return the first call's experiment ID and round number in stable top-level fields.

- [ ] **Step 6: Update existing test expectations without weakening soft-ad**

Change only the planting assertions in `test_experiment_attach_and_batch.py` from `completion_rate` to `a3_ratio`. Add explicit raw A3 data wherever the test expects a planting ranking. Leave soft-ad fixtures on completion rate.

- [ ] **Step 7: Run experiment tests**

```powershell
python -m pytest tests/test_planting_experiment_policy.py tests/test_experiment_attach_and_batch.py -q
```

Expected: all pass; one accepted candidate is reported as a single-arm draft, not an A/B comparison.

- [ ] **Step 8: Commit the experiment policy unit**

```powershell
git add services/knowledge-engine/app/services/experiment_lab.py services/knowledge-engine/app/mcp/tools/experiment.py services/knowledge-engine/tests/test_planting_experiment_policy.py services/knowledge-engine/tests/test_experiment_attach_and_batch.py
git diff --cached --name-only
git commit -m "feat(experiments): make planting A3-first and arm-strict"
```

---

### Task 6: Compile high-detail final video prompts within a duration-scaled capacity window

**Files:**
- Create: `services/knowledge-engine/app/services/video_prompt_compiler.py`
- Create: `services/knowledge-engine/tests/test_video_prompt_compiler.py`
- Modify: `services/knowledge-engine/config/prompts/video_model_profiles/seedance.md`
- Modify: `services/knowledge-engine/tests/test_whole_prompt_scenes.py`

- [ ] **Step 1: Write failing budget, timestamp, and no-truncation tests**

```python
from app.services.video_prompt_compiler import (
    compile_final_prompt_segment,
    prompt_budget_for_duration,
)
from app.services.video_intent_profiles import get_video_intent_profile


def test_prompt_budget_scales_with_segment_duration():
    profile = get_video_intent_profile("planting")
    budget = prompt_budget_for_duration(15, profile.prompt_budget)
    assert budget.min_chars == 750
    assert budget.recommended_chars == (900, 1305)
    assert budget.max_chars == 1605


def test_over_budget_prompt_compresses_duplicates_without_tail_truncation():
    source = {
        "identity_product_anchor": "人物、服装、产品包装、厨房、暖光、9:16、手持近景。" * 12,
        "reference_instruction": "角色参考图保持同一张脸，产品参考图保持同一包装。",
        "product_solution_action": "产品完成调味，让赶晚饭时不再反复找瓶子试味。",
        "timeline": "0-3秒人物回家；3-8秒产品完成调味；8-15秒家人立即开饭并给出可见反馈。",
        "scene_detail": "灶台蒸汽、门口还放着通勤包。",
        "sound_detail": "钥匙落桌声、锅中轻响、孩子一句可以开饭了吗。",
        "decorative_detail": "细腻电影感、自然生活质感。",
        "negative": "禁止换脸、包装变形、手部畸形、乱码、动作跳变。",
        "required_anchors": ["产品完成调味", "家人立即开饭"],
    }
    result = compile_final_prompt_segment(source, duration_seconds=15, intent="planting")
    assert result["ok"] is True
    assert result["char_count"] <= 1605
    assert result["final_prompt"].endswith("禁止换脸、包装变形、手部畸形、乱码、动作跳变。")
    assert "产品完成调味" in result["final_prompt"]
    assert "家人立即开饭" in result["final_prompt"]


def test_prompt_over_hard_max_never_tail_truncates():
    result = compile_final_prompt_segment(
        {"identity_product_anchor": "互不重复细节" * 900, "reference_instruction": "保持参考图一致", "product_solution_action": "连续动作解除痛点", "timeline": "0-15秒连续动作", "scene_detail": "独特场景", "sound_detail": "独特声音", "decorative_detail": "独特修饰", "negative": "禁止变形", "required_anchors": ["连续动作"]},
        duration_seconds=15,
        intent="planting",
    )
    assert result["ok"] is False
    assert result["error"] == "prompt_capacity_exceeded"
```

Add tests for: duration over 15 seconds, prompt below `50 × seconds`, non-contiguous timestamps, missing character/product/action/result anchors, and Unicode code-point counting with Chinese text and whitespace included.

- [ ] **Step 2: Run tests and confirm the missing compiler**

```powershell
python -m pytest tests/test_video_prompt_compiler.py -q
```

Expected: collection fails with a missing compiler module.

- [ ] **Step 3: Implement budget and deterministic duplicate compression**

```python
from dataclasses import dataclass
from math import ceil
import re

from app.services.video_intent_profiles import get_video_intent_profile


@dataclass(frozen=True)
class PromptBudget:
    min_chars: int
    recommended_chars: tuple[int, int]
    max_chars: int


def prompt_budget_for_duration(duration_seconds: int, profile) -> PromptBudget:
    if duration_seconds <= 0 or duration_seconds > profile.segment_max_seconds:
        raise ValueError("video_segment_duration_invalid")
    return PromptBudget(
        min_chars=ceil(duration_seconds * profile.min_chars_per_second),
        recommended_chars=(
            ceil(duration_seconds * profile.recommended_chars_per_second[0]),
            ceil(duration_seconds * profile.recommended_chars_per_second[1]),
        ),
        max_chars=ceil(duration_seconds * profile.max_chars_per_second),
    )


def _dedupe_repeated_clauses(text: str) -> str:
    clauses = re.split(r"(?<=[。；！？])", text)
    seen: set[str] = set()
    kept: list[str] = []
    for clause in clauses:
        key = re.sub(r"\s+", "", clause)
        if key and key not in seen:
            seen.add(key)
            kept.append(clause)
    return "".join(kept)
```

`compile_final_prompt_segment` must concatenate exactly three layers in order: (1) identity/product/reference anchors, (2) product-solution action plus the continuous timestamped timeline and scene/sound details, and (3) negative constraints. Preserve content in this priority order: identity/product/reference consistency, product-solution action, timeline/key shots, scene detail, sound detail, decorative detail. Duplicate compression walks from the lowest-priority lane upward and removes only a normalized clause already present in a higher-priority lane; it never removes a unique clause. Count `len(final_prompt)` after compression, including timestamps, reference instructions, whitespace, and negative constraints but excluding outer API JSON/system metadata. Never slice the string. Return `prompt_detail_insufficient` below the hard minimum and `prompt_capacity_exceeded` above the hard maximum.

- [ ] **Step 4: Validate timestamps and executable anchors**

Parse all `A-B秒` ranges, require the first start to be `0`, require each next start to equal the previous end, and require the last end to equal the segment duration. Check every item in `required_anchors` against the final string. Return structured `failed_checks` so the Agent can revise the current stage without regenerating unrelated assets.

- [ ] **Step 5: Update Seedance documentation without changing director-brief semantics**

Add an “API 分段模式（creative_pack → generate_video_segments）” subsection documenting the 15-second cap and 50 / 60–87 / 107 character-per-second profile. Keep the existing whole-video director-brief guidance in its own section; do not replace it with the API-segment rules.

Change `test_whole_prompt_scenes.py:test_step7_dry_run_whole_mode` so a 22-second formal segment returns `video_segment_duration_invalid` rather than being silently clamped to 15 seconds. Keep any explicitly legacy test under a `legacy` fixture.

- [ ] **Step 6: Run compiler and whole-prompt tests**

```powershell
python -m pytest tests/test_video_prompt_compiler.py tests/test_whole_prompt_scenes.py -q
```

Expected: all pass; no test permits blind tail truncation or formal duration clamping.

- [ ] **Step 7: Commit the compiler unit**

```powershell
git add services/knowledge-engine/app/services/video_prompt_compiler.py services/knowledge-engine/tests/test_video_prompt_compiler.py services/knowledge-engine/config/prompts/video_model_profiles/seedance.md services/knowledge-engine/tests/test_whole_prompt_scenes.py
git diff --cached --name-only
git commit -m "feat(video): compile detailed prompts within model capacity"
```

---

### Task 7: Bind character sheets and SKU-owned product references to the experiment arm

**Files:**
- Create: `services/knowledge-engine/app/services/media_reference_manifest.py`
- Create: `services/knowledge-engine/tests/test_media_reference_manifest.py`
- Modify: `services/knowledge-engine/app/mcp/tools/planting.py`
- Modify: `services/knowledge-engine/app/mcp/tools/media.py`
- Modify: `services/knowledge-engine/app/mcp/doctor.py`
- Modify: `services/knowledge-engine/app/services/ai_hub_client.py`
- Modify: `services/knowledge-engine/app/services/pipeline_lineage.py`
- Modify: `services/knowledge-engine/app/routers/mcp_exec.py`
- Modify: `services/knowledge-engine/tests/test_ai_hub_client_contract.py`
- Modify: `services/knowledge-engine/tests/test_mcp_media.py`
- Modify: `services/knowledge-engine/tests/test_video_segments_product_gate.py`

- [ ] **Step 1: Write failing reference ownership/hash tests**

```python
from pathlib import Path

from app.services.media_reference_manifest import (
    assert_sent_references_match,
    build_reference_manifest,
    sha256_reference,
)


def test_reference_hash_uses_file_bytes(tmp_path: Path):
    ref = tmp_path / "product.png"
    ref.write_bytes(b"same-image-bytes")
    first = sha256_reference(ref)
    ref.write_bytes(b"changed-image-bytes")
    assert sha256_reference(ref) != first


def test_sent_reference_hashes_must_equal_expected_hashes():
    expected = {"face_refs": [{"id": "face-1", "sha256": "a"}], "product_refs": [{"id": "prod-1", "sha256": "b"}]}
    sent = {"face_refs": [{"id": "face-1", "sha256": "a"}], "product_refs": []}
    result = assert_sent_references_match(expected, sent)
    assert result["ok"] is False
    assert result["error"] == "reference_manifest_mismatch"
```

Add async tests proving a product reference registered to `SKU-A` is rejected for a `SKU-B` script, a missing file returns `product_ref_invalid_or_mismatch`, and an arm-mismatched character sheet is never included.

- [ ] **Step 2: Run tests and confirm failure**

```powershell
python -m pytest tests/test_media_reference_manifest.py tests/test_video_segments_product_gate.py -q
```

Expected: the new service is missing and the existing `allow_no_product=True` formal-planting test still passes incorrectly.

- [ ] **Step 3: Implement file resolution, byte hashing, and canonical manifests**

```python
def build_reference_manifest(*, sku_id: str, arm_id: str, face_assets: list[dict], product_assets: list[dict], provider: str, model: str) -> dict:
    def item(asset: dict, role: str) -> dict:
        if asset["sku_id"] != sku_id:
            raise ReferenceManifestError("product_ref_invalid_or_mismatch")
        path = resolve_asset_file(asset["file_url"])
        if not path.is_file():
            raise ReferenceManifestError("product_ref_invalid_or_mismatch")
        return {"id": str(asset["id"]), "role": role, "file_url": asset["file_url"], "sha256": sha256_reference(path)}
    return {
        "sku_id": sku_id,
        "experiment_arm_id": arm_id,
        "provider": provider,
        "model": model,
        "face_refs": [item(asset, "face") for asset in face_assets],
        "product_refs": [item(asset, "product") for asset in product_assets],
    }
```

Preserve list order and compare `(id, sha256)` pairs exactly. A URL or static path is resolved to the actual local file before hashing; a formal path cannot use a hash of the URL string.

Expose one preparation seam in `ai_hub_client.py` so “sent” means the exact bytes serialized into the hub request, not the pre-localization URL:

```python
def decode_data_url_bytes(value: str) -> bytes:
    if not value.startswith("data:") or ";base64," not in value:
        raise ValueError("reference_payload_not_localized")
    return base64.b64decode(value.split(",", 1)[1], validate=True)


def prepare_video_reference_images(face_refs: list[dict], product_refs: list[dict]) -> tuple[list[dict], dict]:
    prepared: list[dict] = []
    sent_manifest = {"face_refs": [], "product_refs": []}
    for role, refs in (("face", face_refs), ("product", product_refs)):
        for ref in refs:
            localized = _localize_url(ref["file_url"])
            payload_bytes = decode_data_url_bytes(localized)
            digest = hashlib.sha256(payload_bytes).hexdigest()
            prepared.append({"url": localized, "type": role, "weight": 1.0})
            sent_manifest[f"{role}_refs"].append({"id": ref["id"], "sha256": digest})
    return prepared, sent_manifest
```

Add an optional `prepared_reference_images` keyword to `AIHubClient.generate_video_v2`; when supplied, place that exact list in `body["reference_images"]` and do not localize the original refs a second time. Tests must inspect the mocked HTTP JSON body and confirm its decoded bytes match `sent_manifest`.

- [ ] **Step 4: Add an audited product-reference registration tool**

```python
@tool_with_audit(mcp, require_approval=False)
async def register_product_reference_asset(sku_id: str, file_ref: str) -> dict:
    path = resolve_asset_file(file_ref)
    if not path.is_file():
        return {"ok": False, "error": "product_ref_invalid_or_mismatch"}
    existing = await pipeline_lineage.get_product_reference_by_file(file_ref)
    if existing and existing["sku_id"] != sku_id:
        return {"ok": False, "error": "product_ref_invalid_or_mismatch", "existing_sku_id": existing["sku_id"]}
    asset = existing or await pipeline_lineage.save_product_reference_asset(
        sku_id=sku_id, file_url=file_ref, sha256=sha256_reference(path),
    )
    return {"ok": True, "asset": asset}
```

Store it as `asset_type='product_reference'`, `status='adopted'`, no script/arm/generation-set ownership. The video reference manifest records each use by arm without copying the underlying asset. Add the tool to doctor; total tool count now increases by one more.

- [ ] **Step 5: Make character-sheet generation arm-aware and truthful**

Change the signature to:

```python
async def generate_character_sheets(
    script_id: str,
    role_ids: list[str] | None = None,
    aspect_ratio: str = "1:1",
    experiment_arm_id: str | None = None,
) -> dict:
```

For a new-version contract, call `assert_script_ready_for_media` before any image request and require `experiment_arm_id`. Save every character asset with that arm. Return:

```python
{
    "ok": success_count > 0,
    "partial": success_count > 0 and error_count > 0,
    "successful_items": successful_items,
    "failed_items": failed_items,
    "retryable_role_ids": retryable_role_ids,
}
```

If every role fails, return `ok=false`, `error='character_sheet_generation_failed'`. Update the REST request model and forwarding call.

- [ ] **Step 6: Make product references mandatory for formal planting and soft-ad**

Add `product_ref_asset_ids: list[str] | None` to `generate_video_segments` and the REST request model. New-version planting/soft-ad must use registered IDs and cannot set `allow_no_product=True`; return `missing_product_refs` before compilation. Keep raw `product_refs` and `allow_no_product` only for explicit legacy/non-product flows.

Update `test_video_segments_product_gate.py` so the formal planting override is rejected and a registered current-SKU asset is accepted.

- [ ] **Step 7: Run reference and character tests**

```powershell
python -m pytest tests/test_media_reference_manifest.py tests/test_video_segments_product_gate.py tests/test_mcp_media.py -q
```

Expected: all pass, including all-character-failure `ok=false` and SKU mismatch rejection.

- [ ] **Step 8: Commit the reference unit**

```powershell
git add services/knowledge-engine/app/services/media_reference_manifest.py services/knowledge-engine/tests/test_media_reference_manifest.py services/knowledge-engine/app/mcp/tools/planting.py services/knowledge-engine/app/mcp/tools/media.py services/knowledge-engine/app/mcp/doctor.py services/knowledge-engine/app/services/ai_hub_client.py services/knowledge-engine/app/services/pipeline_lineage.py services/knowledge-engine/app/routers/mcp_exec.py services/knowledge-engine/tests/test_ai_hub_client_contract.py services/knowledge-engine/tests/test_mcp_media.py services/knowledge-engine/tests/test_video_segments_product_gate.py
git diff --cached --name-only
git commit -m "feat(video): bind arm and SKU reference manifests"
```

---

### Task 8: Implement video generation-set state and atomic adoption

**Files:**
- Create: `services/knowledge-engine/app/services/video_generation_sets.py`
- Create: `services/knowledge-engine/tests/test_video_generation_sets.py`
- Modify: `services/knowledge-engine/app/services/pipeline_lineage.py`
- Modify: `services/knowledge-engine/app/mcp/tools/pipeline.py`

- [ ] **Step 1: Write failing state-machine tests**

```python
import pytest

from app.services import video_generation_sets as sets


@pytest.mark.asyncio
async def test_generation_set_missing_segment_never_becomes_ready(generation_set_fixture):
    await sets.select_segment_asset(generation_set_fixture.id, scene_no=1, asset_id=generation_set_fixture.scene1_asset)
    result = await sets.evaluate_group_gate(generation_set_fixture.id)
    assert result["pass"] is False
    assert result["error"] == "generation_set_incomplete"
    assert result["missing_scene_nums"] == [2]


@pytest.mark.asyncio
async def test_technical_rerender_replaces_selection_without_changing_arm(generation_set_fixture):
    first = await sets.select_segment_asset(generation_set_fixture.id, 1, generation_set_fixture.scene1_asset)
    second = await sets.select_segment_asset(generation_set_fixture.id, 1, generation_set_fixture.scene1_rerender)
    assert first["experiment_arm_id"] == second["experiment_arm_id"]
    assert second["selected_assets"] == [generation_set_fixture.scene1_rerender]


@pytest.mark.asyncio
async def test_single_asset_adoption_cannot_bypass_generation_set(generation_set_fixture):
    result = await sets.assert_single_asset_adoption_allowed(generation_set_fixture.scene1_asset)
    assert result == {"ok": False, "error": "generation_set_asset_requires_atomic_adoption"}
```

Add cases for duplicate active selections, post-gate failure, prompt-hash mismatch, and atomic rollback if one selected asset update fails.

- [ ] **Step 2: Run tests and confirm failure**

```powershell
python -m pytest tests/test_video_generation_sets.py -q
```

Expected: collection fails because the generation-set service is missing.

- [ ] **Step 3: Implement draft creation and immutable expected manifests**

```python
async def create_generation_set(*, sku_id, script_id, experiment_id, experiment_arm_id,
                                expected_segment_manifest, reference_manifest,
                                pre_video_group_gate, profile_version) -> dict:
    if not pre_video_group_gate.get("pass"):
        return {"ok": False, "error": "pre_video_vector_gate_failed"}
    row = await get_pool().fetchrow(
        "INSERT INTO pipeline.video_generation_sets "
        "(sku_id,script_id,experiment_id,experiment_arm_id,expected_segment_manifest,reference_manifest,pre_video_group_gate,profile_version) "
        "VALUES ($1,$2::uuid,$3::uuid,$4::uuid,$5::jsonb,$6::jsonb,$7::jsonb,$8) RETURNING *",
        sku_id, script_id, experiment_id, experiment_arm_id,
        json.dumps(expected_segment_manifest), json.dumps(reference_manifest),
        json.dumps(pre_video_group_gate), profile_version,
    )
    return {"ok": True, "generation_set": dict(row)}
```

On reuse, require the exact ordered expected manifest, pre-gate hashes, profile version, script, and arm. A semantic prompt/hash change returns `vector_gate_stale` and instructs the Agent to create a new script/arm; it is not a technical rerender.

- [ ] **Step 4: Implement candidate recording, selection, and group evaluation**

`record_segment_candidate` must require an asset with matching `generation_set_id`, scene number, script, arm, expected prompt hash, and current post-video gate. `select_segment_asset` replaces only the selected asset for that scene and preserves old rerenders for audit.

`evaluate_group_gate` must require exactly one selected asset for every expected scene and require every selected asset's current post gate to pass. Store the result in `post_video_group_gate`; set status to `ready` only when it passes, otherwise keep `draft`.

- [ ] **Step 5: Implement atomic group adoption and metric admission**

```python
async def adopt_video_generation_set(generation_set_id: str) -> dict:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            group = await conn.fetchrow("SELECT * FROM pipeline.video_generation_sets WHERE id=$1::uuid FOR UPDATE", generation_set_id)
            gate = await evaluate_group_gate(generation_set_id, conn=conn)
            if not gate["pass"]:
                return {"ok": False, "error": gate["error"]}
            selected = gate["selected_asset_ids"]
            await conn.execute("UPDATE pipeline.assets SET status='adopted',updated_at=NOW() WHERE id=ANY($1::uuid[])", selected)
            await conn.execute("UPDATE pipeline.video_generation_sets SET status='adopted',updated_at=NOW() WHERE id=$1::uuid", generation_set_id)
    return {"ok": True, "generation_set_id": generation_set_id, "selected_asset_ids": selected}
```

`assert_generation_set_allows_metrics` must require `status='adopted'`, current group-gate freshness, and membership in `selected_assets`.

- [ ] **Step 6: Route generic pipeline adoption safely**

Extend `pipeline_adopt` to accept `table='video_generation_sets'` and call the atomic service. If `table='assets'` refers to an asset with a non-null generation set, return `generation_set_asset_requires_atomic_adoption`. Keep legacy single-asset adoption unchanged.

- [ ] **Step 7: Run generation-set tests**

```powershell
python -m pytest tests/test_video_generation_sets.py tests/test_portrait_lineage.py -q
```

Expected: all pass; failed/missing segments never become ready or adopted.

- [ ] **Step 8: Commit the generation-set unit**

```powershell
git add services/knowledge-engine/app/services/video_generation_sets.py services/knowledge-engine/tests/test_video_generation_sets.py services/knowledge-engine/app/services/pipeline_lineage.py services/knowledge-engine/app/mcp/tools/pipeline.py
git diff --cached --name-only
git commit -m "feat(video): adopt complete generation sets atomically"
```

---

### Task 9: Enforce fresh pre-video and post-video vector gates in the media provider path

**Files:**
- Create: `services/knowledge-engine/app/services/video_vector_gates.py`
- Create: `services/knowledge-engine/tests/test_video_vector_gates.py`
- Create: `services/knowledge-engine/tests/test_video_media_failure_semantics.py`
- Modify: `services/knowledge-engine/app/mcp/tools/media.py`
- Modify: `services/knowledge-engine/app/services/pipeline_lineage.py`
- Modify: `services/knowledge-engine/app/services/match_vectors.py`
- Modify: `services/knowledge-engine/app/routers/mcp_exec.py`
- Modify: `services/knowledge-engine/tests/test_match_vectors.py`
- Modify: `services/knowledge-engine/tests/test_mcp_media.py`
- Modify: `services/knowledge-engine/tests/test_whole_prompt_scenes.py`

- [ ] **Step 1: Write failing hash-freshness and weighted-score tests**

```python
from app.services.video_vector_gates import (
    aggregate_duration_weighted_scores,
    build_pre_gate_fingerprint,
    validate_post_gate_freshness,
    validate_pre_gate_freshness,
)


def test_pre_gate_stales_when_prompt_or_fact_or_profile_or_embedding_changes():
    stored = build_pre_gate_fingerprint(
        final_prompt_hashes=["p1", "p2"], upstream_fact_hash="facts-v1",
        intent_profile_version="profile-v1", embedding_model="gemini-embedding",
        embedding_version="emb-v1",
    )
    assert validate_pre_gate_freshness(stored, stored)["ok"] is True
    for field, replacement in (
        ("final_prompt_hashes", ["p1", "changed"]),
        ("upstream_fact_hash", "facts-v2"),
        ("intent_profile_version", "profile-v2"),
        ("embedding_version", "emb-v2"),
    ):
        current = {**stored, field: replacement}
        assert validate_pre_gate_freshness(stored, current)["error"] == "vector_gate_stale"


def test_post_gate_stales_when_video_hash_or_judge_version_changes():
    stored = {"video_file_hash": "v1", "final_prompt_hash": "p1", "upstream_fact_hash": "f1", "intent_profile_version": "i1", "judge_model": "gemini", "judge_version": "j1"}
    assert validate_post_gate_freshness(stored, stored)["ok"] is True
    assert validate_post_gate_freshness(stored, {**stored, "video_file_hash": "v2"})["error"] == "vector_gate_stale"
    assert validate_post_gate_freshness(stored, {**stored, "judge_version": "j2"})["error"] == "vector_gate_stale"


def test_duration_weighted_score_is_not_plain_average():
    result = aggregate_duration_weighted_scores([
        {"duration_seconds": 5, "overall_score_100": 100},
        {"duration_seconds": 15, "overall_score_100": 60},
    ])
    assert result == 70.0
```

Add a pre-gate test in which one applicable dimension is `69` while the average is over `70`; the group must fail. Add a test requiring at least one segment to carry both product action and pain relief.

- [ ] **Step 2: Write failing media orchestration tests before provider changes**

Use a fake provider client with a call counter and assert:

```python
async def test_force_t2v_cannot_drop_required_refs(formal_video_fixture, fake_provider):
    result = await generate_video_segments(
        script_id=formal_video_fixture.script_id,
        experiment_arm_id=formal_video_fixture.arm_id,
        product_ref_asset_ids=[formal_video_fixture.product_ref_id],
        force_t2v=True,
    )
    assert result["ok"] is False
    assert result["error"] == "reference_manifest_mismatch"
    assert fake_provider.calls == 0


async def test_all_video_segment_failures_return_ok_false(formal_video_fixture, failing_provider):
    result = await run_formal_video_generation(formal_video_fixture, failing_provider)
    assert result["ok"] is False
    assert result["error"] == "video_segment_generation_failed"
    assert result["successful_items"] == []
    assert len(result["failed_items"]) == formal_video_fixture.segment_count
```

Add cases for pre-gate failure (zero provider calls), post-gate failure (asset stays draft and is not a usable success), partial success, missing segment, and a semantic prompt change attempting to reuse a generation set.

- [ ] **Step 3: Run focused tests and confirm old behavior fails them**

```powershell
python -m pytest tests/test_video_vector_gates.py tests/test_video_media_failure_semantics.py -q
```

Expected: missing service failures plus current media behavior that clears refs or reports top-level success.

- [ ] **Step 4: Implement canonical fingerprints and freshness checks**

```python
def build_pre_gate_fingerprint(*, final_prompt_hashes, upstream_fact_hash,
                               intent_profile_version, embedding_model,
                               embedding_version) -> dict:
    return {
        "final_prompt_hashes": list(final_prompt_hashes),
        "upstream_fact_hash": upstream_fact_hash,
        "intent_profile_version": intent_profile_version,
        "embedding_model": embedding_model,
        "embedding_version": embedding_version,
    }


def validate_pre_gate_freshness(stored: dict, current: dict) -> dict:
    keys = (
        "final_prompt_hashes", "upstream_fact_hash", "intent_profile_version",
        "embedding_model", "embedding_version",
    )
    changed = [key for key in keys if stored.get(key) != current.get(key)]
    return ({"ok": False, "error": "vector_gate_stale", "changed": changed}
            if changed else {"ok": True})
```

Implement the analogous post-gate check for `generation_set_id`, video file hash, corresponding final-prompt hash, upstream fact hash, profile version, judge model, and judge version.

- [ ] **Step 5: Score final prompts by declared dimensions**

`score_pre_video_prompt_set` receives compiled prompts and the structured contract facts. Embed the prompt text and each applicable fact lane using the existing embedding infrastructure, return 0–100 per-dimension and per-segment scores, and duration-weight the group score. Fail if any applicable key dimension is below the profile threshold, the group is below it, a segment is missing, or no segment carries both product action and pain relief.

Write the arm result as:

```python
await conn.execute(
    "UPDATE pipeline.experiment_arms SET predicted_match_score=$2,predicted_match_meta=$3::jsonb WHERE id=$1::uuid",
    arm_id,
    pre_gate["overall_score_100"] / 100.0,
    json.dumps({**pre_gate, **fingerprint}),
)
```

`predicted_match_score` remains a preflight proxy and never enters winner ranking.

- [ ] **Step 6: Score actual video and bind its bytes to the result**

Use the existing Gemini video reader to extract visible/audible signals from the actual saved file, then score the same applicable fact dimensions. Store the result under `assets.visual_prescreen.post_video_vector_gate`; include the post fingerprint and missing/drift signals. A score below 70 keeps the asset `draft`, makes it ineligible for selection, and returns `post_video_vector_gate_failed` for that segment.

- [ ] **Step 7: Reorder `generate_video_segments` into a fail-closed formal pipeline**

Add `generation_set_id: str | None = None` to the MCP and REST signatures. For a new-version planting/soft-ad script, execute this exact order:

1. `assert_script_ready_for_media` checks adopted script and matching arm.
2. Resolve registered product refs plus arm-bound character sheets.
3. Compile all final prompts and validate duration/detail/timestamps.
4. Build expected reference manifest and pre-gate fingerprints.
5. Score the final prompts; reject below threshold or stale scores.
6. With `preflight_only=True`, create/update the draft generation set, return final prompts, scores, hashes, references, and `estimated_provider_calls`, then stop with zero video calls.
7. A formal paid call must supply that `generation_set_id`; reload and revalidate every hash and reference immediately before provider submission.
8. Build the actual sent manifest from the final provider arguments. If the model/mode would clear a required ref, return `reference_manifest_mismatch`; never call the provider.
9. Save each returned video with script, arm, generation set, expected prompt hash, and reference manifest.
10. Run actual-video post scoring, select only passing assets, then evaluate the group gate.

Delete the hard-coded SKU002/soy-sauce repair suffix. A failed pre-gate returns evidence for revising the script or prompt; it must not prepend unrelated product facts and resubmit automatically.

Select the top-level blocker with one shared ordered tuple, never dictionary/async completion order:

```python
PRIMARY_ERROR_ORDER = (
    "upstream_lineage_incomplete", "pain_solution_bridge_invalid",
    "planting_content_gate_failed", "script_not_adopted",
    "experiment_arm_missing_or_mismatch", "character_sheet_generation_failed",
    "missing_product_refs", "product_ref_invalid_or_mismatch",
    "reference_manifest_mismatch", "prompt_detail_insufficient",
    "prompt_capacity_exceeded", "pre_video_vector_gate_failed",
    "vector_gate_stale", "video_segment_generation_failed",
    "post_video_vector_gate_failed", "generation_set_incomplete",
    "insufficient_a3_denominator", "metric_coverage_incomplete",
    "exposure_imbalance", "diagnostic_policy_missing",
)
```

Add a unit case with multiple failed segments that proves the earliest configured error wins while all item-level errors remain in `failed_items`.

- [ ] **Step 8: Make top-level results reflect usable assets**

Return:

```python
{
    "ok": bool(successful_items),
    "partial": bool(successful_items) and bool(failed_items),
    "error": None if successful_items else primary_error,
    "successful_items": successful_items,
    "failed_items": failed_items,
    "retryable_scene_nums": retryable_scene_nums,
    "generation_set_id": generation_set_id,
    "group_gate": group_gate,
}
```

Only post-gate-passing items count as successful. The generation set can be `ready` only if every expected segment has one valid selected asset. `post_vector_check=False` is ignored with a strict-profile error; it remains available only for legacy calls.

- [ ] **Step 9: Persist generation-set and prescreen fields through lineage helpers**

Extend `save_storyboard_asset` with `generation_set_id` and structured `visual_prescreen`. Include the generation set, arm, contract, and manifests in `pipeline_get_asset_lineage`. Preserve current callers by making the new arguments keyword-only with `None` defaults, while formal calls always provide them.

- [ ] **Step 10: Run vector/media and legacy compatibility tests**

```powershell
python -m pytest tests/test_video_vector_gates.py tests/test_video_media_failure_semantics.py tests/test_match_vectors.py tests/test_whole_prompt_scenes.py tests/test_video_segments_product_gate.py tests/test_mcp_media.py -q
```

Expected: all pass; `predict_match` calibration still reads a normalized 0–1 arm score, and no failing formal gate reaches the video provider.

- [ ] **Step 11: Commit the double-vector media unit**

```powershell
git add services/knowledge-engine/app/services/video_vector_gates.py services/knowledge-engine/tests/test_video_vector_gates.py services/knowledge-engine/tests/test_video_media_failure_semantics.py services/knowledge-engine/app/mcp/tools/media.py services/knowledge-engine/app/services/pipeline_lineage.py services/knowledge-engine/app/services/match_vectors.py services/knowledge-engine/app/routers/mcp_exec.py services/knowledge-engine/tests/test_match_vectors.py services/knowledge-engine/tests/test_mcp_media.py services/knowledge-engine/tests/test_whole_prompt_scenes.py
git diff --cached --name-only
git commit -m "feat(video): gate final prompts and actual segments by vector freshness"
```

---

### Task 10: Normalize planting metrics, pool raw counts, and make iteration policy deterministic

**Files:**
- Create: `services/knowledge-engine/app/services/ad_metrics_normalization.py`
- Create: `services/knowledge-engine/tests/test_ad_metrics_normalization.py`
- Create: `services/knowledge-engine/tests/test_planting_experiment_metrics.py`
- Create: `services/knowledge-engine/tests/test_pipeline_asset_metrics_api.py`
- Modify: `services/knowledge-engine/app/services/ad_metrics_validation.py`
- Modify: `services/knowledge-engine/app/services/pipeline_lineage.py`
- Modify: `services/knowledge-engine/app/services/experiment_lab.py`
- Modify: `services/knowledge-engine/app/mcp/tools/pipeline.py`
- Modify: `services/knowledge-engine/app/routers/mcp_exec.py`
- Modify: `services/knowledge-engine/tests/test_diagnose_and_validation.py`
- Modify: `services/knowledge-engine/tests/test_experiment_attach_and_batch.py`
- Modify: `services/knowledge-engine/tests/test_match_vectors.py`

- [ ] **Step 1: Write failing canonical metric tests**

```python
from app.services.ad_metrics_normalization import normalize_ad_metrics


def test_percent_string_normalizes_to_zero_one():
    result = normalize_ad_metrics({"a3_ratio": "5%", "currency": "CNY"}, strict=True)
    assert result["metrics"]["a3_ratio"] == 0.05


def test_raw_values_override_hand_entered_rates():
    result = normalize_ad_metrics({
        "new_a3": 20, "a3_eligible_users": 1000, "a3_ratio": 0.9,
        "spend": 240, "impressions": 12000, "cpm": 999,
        "play_3s": 6000, "play_3s_rate": 0.1,
        "currency": "CNY",
    }, strict=True)
    metrics = result["metrics"]
    assert metrics["a3_ratio"] == 0.02
    assert metrics["cpm"] == 20.0
    assert metrics["play_3s_rate"] == 0.5
    assert result["provenance"]["a3_ratio"] == "derived_from_raw_counts"


def test_zero_denominator_and_non_cny_are_suspect():
    result = normalize_ad_metrics({"new_a3": 1, "a3_eligible_users": 0, "spend": 1, "impressions": 10, "currency": "USD"}, strict=True)
    assert result["poolable"] is False
    assert set(result["errors"]) >= {"zero_denominator", "currency_must_be_cny"}


def test_rate_with_matching_denominator_derives_poolable_numerator():
    result = normalize_ad_metrics({
        "a3_ratio": 0.04, "a3_eligible_users": 250,
        "currency": "CNY",
    }, strict=True)
    assert result["effective_numerators"]["new_a3"] == 10.0
    assert result["provenance"]["a3_ratio"] == "derived_from_rate_and_denominator"
```

Add tests for numeric rates above 1 in strict mode, negative counts, platform completion rate without raw denominator (stored but not poolable), complete raw completion inputs overriding the platform value, and mixed completion denominator types.

- [ ] **Step 2: Write failing pooled-arm and winner tests**

```python
@pytest.mark.asyncio
async def test_planting_arm_uses_pooled_a3_ratio_not_average_rate(planting_round):
    await planting_round.record("A", new_a3=1, a3_eligible_users=10, impressions=100, spend=10, play_3s=50)
    await planting_round.record("A", new_a3=9, a3_eligible_users=90, impressions=900, spend=90, play_3s=450)
    status = await experiment_status(planting_round.experiment_id)
    arm = next(item for item in status["arms"] if item["arm_label"] == "A")
    assert arm["a3_ratio"] == 0.10
    assert arm["a3_ratio"] != 0.50


@pytest.mark.asyncio
async def test_missing_a3_denominator_or_exposure_imbalance_blocks_confident_lock(planting_round):
    await planting_round.record("A", new_a3=5, a3_eligible_users=100, impressions=1000)
    await planting_round.record("B", new_a3=7, a3_eligible_users=100, impressions=3000)
    status = await experiment_status(planting_round.experiment_id)
    assert status["can_lock"] is False
    assert status["blocker"] == "exposure_imbalance"
```

Add cases for single arm, discarded/unselected generation-set assets, any eligible asset missing `a3_eligible_users`, missing impressions, diagnostic coverage below 100%, and predicted vector score not affecting A3 ranking.

- [ ] **Step 3: Run metric tests and confirm failure**

```powershell
python -m pytest tests/test_ad_metrics_normalization.py tests/test_planting_experiment_metrics.py tests/test_pipeline_asset_metrics_api.py -q
```

Expected: missing normalization service and old average-rate winner behavior.

- [ ] **Step 4: Implement strict normalization with raw-value provenance**

```python
def normalize_rate(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.strip().endswith("%"):
        return float(value.strip()[:-1]) / 100.0
    rate = float(value)
    return rate if 0.0 <= rate <= 1.0 else None


def _ratio(numerator, denominator):
    if numerator is None or denominator is None:
        return None
    if float(denominator) <= 0:
        raise ValueError("zero_denominator")
    return float(numerator) / float(denominator)
```

`normalize_ad_metrics` must:

- require explicit `currency='CNY'` for strict generation-set assets;
- retain the platform `completion_rate` unless all of `play_complete`, `completion_denominator`, and `completion_denominator_type` are present;
- recalculate A3, CPM, three-second rate, and complete raw completion values;
- when a raw numerator is absent but a normalized rate and its matching denominator are present, store `effective_numerator = rate × denominator` and mark `derived_from_rate_and_denominator=true` so arm aggregation can weight it;
- store `_validation`, `_provenance`, and per-metric `poolable` metadata;
- mark invalid data suspect without silently converting numeric `5` into `0.05`.

Legacy assets with `generation_set_id IS NULL` continue through the existing tolerant validator and retain their historical 0–100 interpretation; do not rewrite old JSONB values.

- [ ] **Step 5: Extend the whitelist and metric API fields**

Add `a3_eligible_users`, `completion_denominator`, and `completion_denominator_type`; keep `new_a3`, `spend`, `impressions`, `play_3s`, `play_complete`, and `currency`. Update MCP docs and the REST `RecordAdMetricsRequest` to forward `experiment_arm_id`, which the current REST model omits.

In batch CSV mapping, recognize A3 eligible users, new A3, spend, impressions, three-second plays, completed plays, completion denominator/type, and currency. Dry runs must report missing denominator/currency coverage before writes.

- [ ] **Step 6: Enforce generation-set metric admission in one transaction**

In `pipeline_lineage.record_ad_metrics`, lock the asset row, verify script/arm/experiment lineage, call `assert_generation_set_allows_metrics`, normalize the merged metrics, and only then publish/update the selected asset. Do not allow a caller to reattach a generation-set asset to a different arm. Keep the current legacy path for null generation sets.

- [ ] **Step 7: Evaluate planting rounds from pooled columns**

For planting, `experiment_status` must sum raw numerators first and otherwise use the stored effective numerator from a same-scale rate plus denominator. It must never average material-level percentages. Return:

```python
{
    "a3_ratio": pooled_a3,
    "cpm": pooled_cpm,
    "play_3s_rate": pooled_3s,
    "completion_rate": pooled_completion,
    "metric_coverage": coverage,
    "a3_complete": a3_complete,
    "impressions": impressions_sum,
}
```

Require at least two arms for comparison. Winner ordering uses only pooled A3. Keep the existing `n_videos >= 5` engineering gate and label it as non-significance. An exposure ratio `>= evaluation_policy.max_exposure_ratio` sets `can_lock=false` and `blocker='exposure_imbalance'`. Missing impressions blocks CPM and exposure conclusions.

Soft-ad remains on completion rate and must not enter the planting A3 evaluator.

- [ ] **Step 8: Make locking safe and next-variable selection deterministic**

`lock_winner` must recompute eligibility server-side and reject: single arm, incomplete A3 denominator, unselected/stale generation assets, and a selected arm that is not the current A3 leader. `force=True` may preserve the existing manual override for the `n<5` engineering gate and exposure imbalance with an audit flag; it may not bypass missing denominators, stale gates, single-arm state, or wrong leader.

Implement one shared helper for status and `next_version_seed`:

```python
def choose_planting_next_action(metrics, policy, tested, locked, current_variable):
    required = ("play_3s_floor", "completion_floor", "a3_floor", "cpm_ceiling", "min_impressions", "min_a3_eligible_users")
    if any(policy.get(key) is None for key in required):
        return {"ok": False, "error": "diagnostic_policy_missing", "missing": [key for key in required if policy.get(key) is None]}
    if metrics["window_incomplete"] or not metrics["a3_complete"] or metrics["coverage"] < 1 or metrics["exposure_imbalanced"]:
        return {"action": "rerun_current_variable", "variable": current_variable}
    if metrics["play_3s_rate"] < policy["play_3s_floor"]:
        candidates = ("opening_hook_3s", "presentation_motif")
    elif metrics["completion_rate"] < policy["completion_floor"]:
        candidates = ("story_pace", "justification_density")
    elif metrics["a3_ratio"] < policy["a3_floor"]:
        candidates = ("pain_scene_bridge", "justification_module")
    elif metrics["cpm"] > policy["cpm_ceiling"]:
        return {"action": "inspect_delivery_or_audience", "variable": None}
    else:
        candidates = get_video_intent_profile("planting").global_iteration_order
    legal = [item for item in candidates if item not in tested and item not in locked]
    return ({"action": "sweep", "variable": legal[0]} if legal else {"action": "content_variables_converged", "variable": None})
```

Use `VideoIntentProfile.global_iteration_order` everywhere the global pool is needed; do not reconstruct a second ordering inside `experiment_lab.py`.

- [ ] **Step 9: Run metrics, experiment, API, and vector compatibility tests**

```powershell
python -m pytest tests/test_ad_metrics_normalization.py tests/test_planting_experiment_metrics.py tests/test_pipeline_asset_metrics_api.py tests/test_diagnose_and_validation.py tests/test_experiment_attach_and_batch.py tests/test_match_vectors.py -q
```

Expected: all pass; raw counts pool correctly, soft-ad still ranks completion, and prediction stays a non-winner side signal.

- [ ] **Step 10: Commit the metric and iteration unit**

```powershell
git add services/knowledge-engine/app/services/ad_metrics_normalization.py services/knowledge-engine/tests/test_ad_metrics_normalization.py services/knowledge-engine/tests/test_planting_experiment_metrics.py services/knowledge-engine/tests/test_pipeline_asset_metrics_api.py services/knowledge-engine/app/services/ad_metrics_validation.py services/knowledge-engine/app/services/pipeline_lineage.py services/knowledge-engine/app/services/experiment_lab.py services/knowledge-engine/app/mcp/tools/pipeline.py services/knowledge-engine/app/routers/mcp_exec.py services/knowledge-engine/tests/test_diagnose_and_validation.py services/knowledge-engine/tests/test_experiment_attach_and_batch.py services/knowledge-engine/tests/test_match_vectors.py
git diff --cached --name-only
git commit -m "feat(metrics): pool planting A3 and drive deterministic iteration"
```

---

### Task 11: Create the canonical planting Agent skill and disambiguate soft-ad routing

**Files:**
- Create: `.agents/skills/ai-planting-video/SKILL.md`
- Create: `.agents/skills/ai-planting-video/agents/openai.yaml`
- Create: `.agents/skills/ai-planting-video/references/planting-method-library.md`
- Create: `.agents/skills/ai-planting-video/references/content-contract-schema.md`
- Create: `.agents/skills/ai-planting-video/references/experiment-state-machine.md`
- Create: `.agents/skills/ai-planting-video/evals/evals.json`
- Create: `tests/test_ai_planting_video_skill.py`
- Create: `tests/test_ai_soft_ad_video_skill.py`
- Create: `tests/test_ai_video_skill_routing.py`
- Modify: `.agents/skills/ai-soft-ad-video/SKILL.md`
- Modify: `.agents/skills/ai-soft-ad-video/agents/openai.yaml`
- Modify: `.agents/skills/ai-soft-ad-video/references/state-machine.md`
- Modify: `.claude/skills/soft-ad-ai-video/SKILL.md`
- Modify: `.claude/skills/soft-ad-ai-video/agents/openai.yaml`
- Modify: `.claude/skills/sku-pipeline/SKILL.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Write failing static skill and routing tests**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_planting_skill_declares_exact_profile_and_boundary():
    text = (ROOT / ".agents/skills/ai-planting-video/SKILL.md").read_text(encoding="utf-8")
    for required in ("video_planting", "intent=planting", "a3_ratio", "gemini-3.1-pro-preview", "M1", "M2", "M3–M9"):
        assert required in text
    assert "最终 MP4 已完成" not in text
    assert "generate_video` 兜底" not in text


def test_planting_skill_stops_before_each_paid_or_adoption_boundary():
    text = (ROOT / ".agents/skills/ai-planting-video/SKILL.md").read_text(encoding="utf-8")
    for stop in ("BRIDGE_REVIEW", "SCRIPT_REVIEW", "ARM_BOUND", "REFERENCE_REVIEW", "PRE_VIDEO_GATE_REVIEW", "VIDEO_SEGMENTS_REVIEW"):
        assert stop in text


def test_soft_ad_excludes_a3_deep_planting_and_keeps_completion_winner():
    text = (ROOT / ".agents/skills/ai-soft-ad-video/SKILL.md").read_text(encoding="utf-8")
    assert "completion_rate" in text
    assert "深度种草" in text and "不要触发" in text
```

The routing test must parse `AGENTS.md` and `CLAUDE.md` and assert:

- planting/A3/pain-solution phrases route to `ai-planting-video`;
- soft-ad/O-A1/three-second/completion phrases route to `ai-soft-ad-video`;
- script-only routes to `script-writer`;
- human brief routes to the director-brief skill;
- `sku-pipeline` stops at `audience_pack_id` and does not claim formal video generation.

- [ ] **Step 2: Run tests and confirm missing/ambiguous routing**

```powershell
python -m pytest -q tests/test_ai_planting_video_skill.py tests/test_ai_soft_ad_video_skill.py tests/test_ai_video_skill_routing.py
```

Expected: the planting skill is missing and current soft-ad routing still claims “软种草”.

- [ ] **Step 3: Create the canonical skill metadata and workflow**

Use this frontmatter:

```yaml
---
name: ai-planting-video
description: Use when老板要沿已有 SKU、人群画像或人群包血缘生成纯 AI 种草、深度种草或 A3 短视频，重点是用产品解决画像里的具体痛点、看完建立相信，或续跑种草视频实验；不用于 O/A1 软广播放优化、A4 收割、只写脚本、从零圈包、真人编导或竞品反推。
---
```

The body must drive this persisted state sequence, deriving state from database products rather than a private state file:

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

At every stage report current lineage, the first blocker, hard-gate results, experiment/arm IDs, successful/failed assets, and exactly one next action. Before creating a planting experiment, show whether all six production thresholds are configured; accept explicit user values through `evaluation_policy_overrides`, or create with nulls while stating that next-variable automation will later stop at `diagnostic_policy_missing`. Never pass a paid boundary, adopt a script/set, publish, record metrics, or lock a winner without the user's explicit continuation at that stage.

- [ ] **Step 4: Write progressive-disclosure references**

- `planting-method-library.md`: the A1/A2→A3 chain, evidence eligibility, `M1/M2 × M3–M9`, selection constraints, and prohibitions on hard CTA/fake evidence.
- `content-contract-schema.md`: the exact bridge JSON, 11 structured content-gate fields plus script-vector thresholds, 50 / 60–87 / 107 prompt budget, five vector dimensions, 0–100 versus 0–1 boundary, hashes/versions, and reference manifest.
- `experiment-state-machine.md`: first two candidates in one experiment/round, single-arm draft wording, arm-bound character/video generation, generation-set rerenders and atomic adoption, A3 winner, diagnostic metrics, and the deterministic next-variable policy.

Each reference must say exactly which states require reading it. `SKILL.md` must say a missing required reference blocks the current stage rather than falling back to soft-ad memory.

- [ ] **Step 5: Add the skill interface and realistic eval prompts**

```yaml
interface:
  display_name: "AI 种草短视频"
  short_description: "沿 SKU 与人群画像血缘生成以 A3 为目标的痛点解决型 AI 视频段。"
  default_prompt: "Use $ai-planting-video to continue the lineage-grounded planting-video chain for this SKU."
```

Create `evals/evals.json` with at least these cases and expected routes:

```json
{
  "skill_name": "ai-planting-video",
  "evals": [
    {"id": 1, "prompt": "给这个 SKU 做两条按 A3 优化、解决画像具体痛点的种草短视频", "expected_output": "select ai-planting-video; stop at lineage review", "files": []},
    {"id": 2, "prompt": "做一条 O/A1 软广，重点看前三秒和完播", "expected_output": "select ai-soft-ad-video", "files": []},
    {"id": 3, "prompt": "只给这个 SKU 写一版种草脚本，不出片", "expected_output": "select script-writer", "files": []},
    {"id": 4, "prompt": "给真人编导下一个种草拍摄 brief", "expected_output": "select short-video-director-brief", "files": []},
    {"id": 5, "prompt": "跑 SKU 前链路到圈包就停", "expected_output": "select sku-pipeline and stop at audience_pack_id", "files": []}
  ]
}
```

- [ ] **Step 6: Narrow soft-ad and Claude compatibility skills**

Remove “软种草/深度种草/A3” from the canonical soft-ad trigger and define soft-ad as `video_soft_ad / soft_ad / completion_rate`. Keep its shared asset/gate state machine, but not planting's pain bridge or A3 winner.

Reduce `.claude/skills/soft-ad-ai-video/SKILL.md` to a compatibility shim under 40 non-empty lines pointing to the canonical soft-ad contract. Set its interface metadata to `allow_implicit_invocation: false`. Do not create a second `.claude/skills/ai-planting-video` implementation.

Update both `AGENTS.md` and `CLAUDE.md` so “软种草” alone follows planting, while explicit O/A1 or three-second/completion optimization follows soft-ad. Keep script-only, human brief, harvest, reverse-video, and front-chain routes mutually exclusive. Update the documented MCP count from 113 to 115 for the bridge and product-reference tools.

- [ ] **Step 7: Validate skill structure on Windows UTF-8**

```powershell
python -X utf8 E:\agent\omni-system\brain\codex\skills\.system\skill-creator\scripts\quick_validate.py .agents\skills\ai-planting-video
python -X utf8 E:\agent\omni-system\brain\codex\skills\.system\skill-creator\scripts\quick_validate.py .agents\skills\ai-soft-ad-video
python -m pytest -q tests/test_ai_planting_video_skill.py tests/test_ai_soft_ad_video_skill.py tests/test_ai_video_skill_routing.py
```

Expected: both validators report valid skills and all routing tests pass. `-X utf8` is required to avoid Windows GBK decode failures.

- [ ] **Step 8: Run fresh-agent route probes without business calls**

For each eval prompt, run:

```powershell
codex exec --ephemeral -s read-only -a never -C E:\agent\omni --json "只做技能路由判定，不调用业务工具、不改文件。用户原话：给这个 SKU 做两条按 A3 优化、解决画像具体痛点的种草短视频。输出 selected_skill、kind、intent、north_star、first_stop。"
```

Repeat with the four remaining eval prompts. Expected selections match `evals/evals.json`; the planting response reports `video_planting`, `planting`, `a3_ratio`, and `LINEAGE_REVIEW`.

- [ ] **Step 9: Commit the Agent routing unit**

```powershell
git add .agents/skills/ai-planting-video .agents/skills/ai-soft-ad-video .claude/skills/soft-ad-ai-video .claude/skills/sku-pipeline/SKILL.md tests/test_ai_planting_video_skill.py tests/test_ai_soft_ad_video_skill.py tests/test_ai_video_skill_routing.py AGENTS.md CLAUDE.md
git diff --cached --name-only
git commit -m "feat(agent): add distinct A3 planting video workflow"
```

---

### Task 12: Verify the zero-cost Agent chain, soft-ad regression, and operational handoff

**Files:**
- Create: `services/knowledge-engine/tests/test_ai_planting_agent_flow.py`
- Modify: `docs/build-log.md`

- [ ] **Step 1: Write the end-to-end mocked integration test**

Build one fixed fixture containing an adopted matrix, audience record, portrait, current-SKU product reference, two valid pain bridges, two scripts, one experiment with two same-round arms, character sheets, and two expected video segments per arm. Mock Gemini bridge/script/video-description results and the media provider bytes; use real database services and state transitions.

```python
@pytest.mark.asyncio
async def test_agent_planting_chain_reaches_adopted_generation_set_and_a3_status(agent_flow_fixture):
    bridges = await agent_flow_fixture.extract_bridges()
    scripts = await agent_flow_fixture.generate_two_scripts(bridges)
    assert all(item["content_contract"]["content_gate"]["pass"] for item in scripts)
    arms = await agent_flow_fixture.adopt_same_round(scripts, swept_variable="pain_scene_bridge")
    assert len({arm["experiment_id"] for arm in arms}) == 1
    assert len({arm["round_no"] for arm in arms}) == 1
    await agent_flow_fixture.generate_character_sheets(arms)
    preflight = await agent_flow_fixture.preflight_video(arms[0])
    assert preflight["estimated_provider_calls"] == 2
    generated = await agent_flow_fixture.generate_mocked_segments(preflight["generation_set_id"])
    assert generated["group_gate"]["pass"] is True
    adopted = await agent_flow_fixture.adopt_generation_set(generated["generation_set_id"])
    assert adopted["ok"] is True
    status = await agent_flow_fixture.record_and_status_a3(arms)
    assert status["north_star_metric"] == "a3_ratio"
```

Add a negative path for each main error-priority stage and a soft-ad fixture proving `completion_rate` remains its north star and the planting bridge is not required.

- [ ] **Step 2: Run the complete targeted suite**

From `services/knowledge-engine`:

```powershell
python -m pytest -q tests/test_video_intent_profiles.py tests/test_pain_solution_bridge.py tests/test_planting_schema.py tests/test_planting_content_gate.py tests/test_planting_experiment_policy.py tests/test_video_prompt_compiler.py tests/test_media_reference_manifest.py tests/test_video_generation_sets.py tests/test_video_vector_gates.py tests/test_video_media_failure_semantics.py tests/test_ad_metrics_normalization.py tests/test_planting_experiment_metrics.py tests/test_pipeline_asset_metrics_api.py tests/test_ai_planting_agent_flow.py
```

Expected: all pass with no network or paid provider call.

- [ ] **Step 3: Run the high-risk compatibility suites**

```powershell
python -m pytest -q tests/test_triangle_match.py tests/test_vector_presets.py tests/test_audience_content_bridge.py tests/test_whole_prompt_scenes.py tests/test_video_segments_product_gate.py tests/test_experiment_attach_and_batch.py tests/test_match_vectors.py tests/test_diagnose_and_validation.py tests/test_mcp_media.py tests/test_creative_pack_batch.py tests/test_portrait_lineage.py
```

Expected: all pass; soft-ad still uses its own method and completion winner, while historical null-generation-set assets retain legacy behavior.

- [ ] **Step 4: Run the full Knowledge Engine test suite**

```powershell
python -m pytest -q
```

Expected: zero failures. If unrelated pre-existing failures appear, record the exact test names and prove the targeted/new suites still pass; do not alter unrelated code to hide them.

- [ ] **Step 5: Run MCP doctor and confirm the authoritative tool count**

```powershell
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
```

Expected: `all 115 ok`, including `generate_planting_pain_solution_bridge` and `register_product_reference_asset`.

- [ ] **Step 6: Run a real-lineage, zero-cost Agent preflight**

Use one real adopted SKU/audience lineage and call `generate_video_segments(script_id=real_script_id, experiment_arm_id=real_arm_id, product_ref_asset_ids=real_product_ref_ids, preflight_only=True)`. Verify the returned report contains:

```text
sku_id / matrix_run_id / audience_record_id / portrait_id / audience_pack_id
script_id / experiment_id / round_no / experiment_arm_id
content gate fields
script vector score
ordered final prompts with character counts
expected and sent-reference preview hashes
pre-video per-dimension and group score
generation_set_id
estimated_provider_calls
```

Expected: no Seedance job/task ID exists and provider call count is zero.

- [ ] **Step 7: Record the implementation and verification result**

Append a dated section to `docs/build-log.md` listing the new tools, migration 068, profile version, targeted/full test counts, doctor result, and the fact that paid Seedance ladder testing is still pending separate approval. Do not claim a final MP4, UI, or real A3 outcome.

- [ ] **Step 8: Commit the integration verification unit**

```powershell
git add services/knowledge-engine/tests/test_ai_planting_agent_flow.py docs/build-log.md
git diff --cached --name-only
git commit -m "test(planting): verify Agent chain and soft-ad compatibility"
```

- [ ] **Step 9: Hand off the separately approved real test**

Report the real SKU/arm/generation-set preflight result and the exact `estimated_provider_calls`. Ask for explicit approval before the first paid video request. After approval, use the same script, model, duration, role, and product references for a prompt-detail ladder; record API acceptance and effective adherence separately, then update only `video_intent_profiles.yaml` / the Seedance profile and regression tests with the observed safe window.

---

## Completion checklist

- The Agent can resume from adopted SKU/audience lineage without regenerating the front chain.
- The planting bridge is structured, Pro-model-only, source-qualified, and pack calibration cannot replace portrait pain evidence.
- Two first-round scripts vary only `pain_scene_bridge`; only explicit user adoption attaches them to the same experiment/round.
- Character sheets and video assets carry the arm; product references are current-SKU assets and expected/sent hashes match.
- Final prompt pre-score and actual-video post-score both use a 70/100 hard threshold with freshness hashes.
- A generation set cannot become ready with missing/failed segments, and its selected assets adopt atomically.
- A3, CPM, three-second rate, and completion use raw-count pooling; planting winner is A3 only.
- Missing denominators, metric coverage, impressions, exposure balance, or production thresholds block confident conclusions at the specified stage.
- Soft-ad remains `video_soft_ad / soft_ad / completion_rate` with its own method.
- All automated tests and MCP doctor pass; paid real-video testing remains an explicit next approval, not an implied completion claim.
