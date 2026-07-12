# Content Experiment and Metrics Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make planting experiments use A3 conversion as the winner metric, make soft-ad completion use a three-second guardrail, normalize postback data, enforce comparable windows and delivery, atomically advance the baseline, and recommend the next single variable from observed funnel loss.

**Architecture:** Keep pipeline.experiments, experiment_rounds, experiment_arms, and assets.ad_metrics as the only state machine. A pure evaluation service aggregates raw counts when available, applies a versioned policy, and returns evidence plus gates. experiment_status and experiment_lock_winner call the same evaluator. Baseline updates run in one database transaction and use the framework registry from the foundation plan.

**Tech Stack:** Python 3.12, asyncpg/PostgreSQL, JSONB, pytest, existing experiment MCP tools and REST routes.

---

## Dependencies and execution preflight

- Complete 2026-07-13-ai-planting-framework-foundation.md first.
- Migration 068 belongs to the foundation plan. This plan owns migration 069 only.
- Preserve the current dirty worktree. Use a reviewed worktree/patch strategy and hunk-level staging; never reset or stash user changes.

### Task 1: Repair experiment_arm_id forwarding before changing evaluation logic

**Files:**

- Modify: E:\agent\omni\services\knowledge-engine\app\routers\mcp_exec.py
- Modify: E:\agent\omni\services\knowledge-engine\tests\test_pipeline_asset_metrics_api.py

- [ ] **Step 1: Add a failing REST forwarding test**

~~~python
def test_record_ad_metrics_rest_forwards_experiment_arm_id(client, monkeypatch):
    captured = {}

    async def fake_record_ad_metrics(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        "app.mcp.tools.pipeline.record_ad_metrics",
        fake_record_ad_metrics,
    )
    response = client.post(
        "/api/v1/mcp/exec/record_ad_metrics",
        json={
            "experiment_arm_id": "arm-1",
            "metrics": {"impressions": 1000, "spend": 80},
        },
    )
    assert response.status_code == 200
    assert captured["experiment_arm_id"] == "arm-1"
~~~

- [ ] **Step 2: Run the test and confirm RED**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_pipeline_asset_metrics_api.py"
~~~

Expected: experiment_arm_id is rejected or absent.

- [ ] **Step 3: Add and forward the field**

~~~python
class RecordAdMetricsRequest(BaseModel):
    metrics: dict
    asset_id: str | None = None
    external_video_id: str | None = None
    external_creative_id: str | None = None
    experiment_arm_id: str | None = None
    mark_published: bool = True
~~~

Forward experiment_arm_id=payload.experiment_arm_id to the existing MCP tool.

- [ ] **Step 4: Run tests and commit**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_pipeline_asset_metrics_api.py"
git add -p services/knowledge-engine/app/routers/mcp_exec.py services/knowledge-engine/tests/test_pipeline_asset_metrics_api.py
git diff --cached --check
git commit -m "fix: forward experiment arm metric postbacks"
~~~

### Task 2: Normalize the complete postback contract and compute canonical ROI

**Files:**

- Modify: E:\agent\omni\services\knowledge-engine\app\services\ad_metrics_validation.py
- Modify: E:\agent\omni\services\knowledge-engine\app\services\pipeline_lineage.py
- Modify: E:\agent\omni\services\knowledge-engine\app\mcp\tools\pipeline.py
- Modify: E:\agent\omni\services\knowledge-engine\tests\test_diagnose_and_validation.py
- Modify: E:\agent\omni\services\knowledge-engine\tests\test_experiment_attach_and_batch.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_ad_metrics_normalization.py

- [ ] **Step 1: Add failing metric-contract tests**

Cover:

~~~python
def test_planting_raw_counts_compute_a3_ratio():
    normalized = normalize_ad_metrics({
        "new_a3": 25,
        "a3_eligible_users": 500,
        "spend": 100,
        "gmv": 240,
        "platform_reported_roi": 2.35,
        "data_start": "2026-07-01",
        "data_end": "2026-07-07",
        "attribution_window": "7d_click",
        "as_of": "2026-07-08T09:00:00+08:00",
        "source": "platform_export",
    })
    assert normalized["a3_ratio"] == 0.05
    assert normalized["roi"] == 2.4
    assert normalized["platform_reported_roi"] == 2.35


def test_soft_ad_raw_counts_compute_watch_rates():
    normalized = normalize_ad_metrics({
        "plays": 1000,
        "play_3s": 720,
        "play_complete": 210,
        "average_watch_time_seconds": 8.6,
    })
    assert normalized["play_3s_rate"] == 0.72
    assert normalized["completion_rate"] == 0.21
~~~

Also test division-by-zero, unavailable A3 denominator, ISO date validation, attribution-window preservation, same-window partial updates, later data_end snapshots, explicit window replacement, and rejection from aggregation when _validation.suspect marks the relevant metric. A changed data_start or attribution_window must never silently merge with old facts.
Derived rates are always stored as 0–1. For direct platform rates, a value with a percent sign or explicit metric_units entry is normalized deterministically. An unmarked direct rate whose unit is ambiguous is retained for display but marked ambiguous_rate_unit and excluded from formal winner aggregation.

- [ ] **Step 2: Extend the whitelist**

Add:

- a3_eligible_users: count
- average_watch_time_seconds: count/decimal with minimum 0
- platform_reported_roi: computed-side-evidence, not canonical ROI
- data_start, data_end, attribution_window, as_of, source: metadata
- metric_units: metadata, mapping a direct rate key to ratio_0_1 or percent_0_100

Keep hand-filled roi/roas suspect. Change validate_ad_metrics to accept a private trusted_computed_keys set supplied only by the normalization layer. The normalization layer may put roi in that set only when valid spend and a canonical GMV numerator produced it; use gmv_paid when present, otherwise gmv, and record roi_numerator_key. External callers cannot mark their own value trusted. platform_reported_roi is valid side evidence only when source=platform_export and never overwrites canonical roi.

- [ ] **Step 3: Normalize inside the existing row lock**

Within record_ad_metrics, separate external input from trusted derived values, merge prior and incoming values, derive rates/ROI from the merged raw facts, then validate the resulting complete document with trusted_computed_keys returned by the normalizer. This allows an early postback with impressions/spend and a later postback with A3 counts to produce one consistent record without allowing a caller-supplied ROI to masquerade as computed.

Add replace_window: bool=False to the MCP/REST/batch service contract. With the default, a different data_start or attribution_window records _validation.window_conflict and the evaluator blocks formal comparison under attribution_window_open details. With replace_window=True, clear prior metric/window facts inside the same row lock before writing the complete replacement snapshot. Extending data_end within the same start/attribution window is allowed and incoming snapshot counts replace prior counts rather than being summed.

Use decimal-safe division and store rates as 0–1, matching the existing rate contract:

~~~python
def _safe_ratio(numerator: Any, denominator: Any) -> float | None:
    n = _decimal_or_none(numerator)
    d = _decimal_or_none(denominator)
    if n is None or d is None or d <= 0:
        return None
    return float(n / d)
~~~

- [ ] **Step 4: Extend CSV aliases**

Add default aliases for:

- 新增A3人数 → new_a3
- A3转化人数 → new_a3
- A3可转化人数 → a3_eligible_users
- A3分母 → a3_eligible_users
- A3转化率 → a3_ratio
- 3秒播放人数 → play_3s
- 3秒观看率 → play_3s_rate
- 完播人数 → play_complete
- 平均观看时长 → average_watch_time_seconds
- 平台ROI → platform_reported_roi
- 数据开始日期 → data_start
- 数据结束日期 → data_end
- 归因窗口 → attribution_window
- 数据截至时间 → as_of
- 数据来源 → source

Add batch identity aliases separate from ad_metrics: 最终资产ID/asset_id → asset_id, 素材ID → external_video_id, 创意ID → external_creative_id. For track=ai_video, every imported row must carry asset_id for a persisted generation_meta.asset_role=final asset that already belongs to the matched arm. Verify this before writing and never auto-create a placeholder asset for an AI-video row. Human-brief rows may retain the existing arm/external-ID fallback.

- [ ] **Step 5: Run tests and commit**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_ad_metrics_normalization.py tests/test_diagnose_and_validation.py tests/test_experiment_attach_and_batch.py tests/test_pipeline_asset_metrics_api.py"
git add -p services/knowledge-engine/app/services/ad_metrics_validation.py services/knowledge-engine/app/services/pipeline_lineage.py services/knowledge-engine/app/mcp/tools/pipeline.py services/knowledge-engine/tests/test_diagnose_and_validation.py services/knowledge-engine/tests/test_experiment_attach_and_batch.py
git add services/knowledge-engine/tests/test_ad_metrics_normalization.py
git diff --cached --check
git commit -m "feat: normalize A3 and watch metric postbacks"
~~~

### Task 3: Add migration 069 for pack identity and evaluation snapshots

**Files:**

- Create: E:\agent\omni\migrations\069_content_experiment_policy.sql
- Create: E:\agent\omni\services\knowledge-engine\tests\test_experiment_policy_persistence.py
- Modify: E:\agent\omni\services\knowledge-engine\app\services\experiment_lab.py
- Modify: E:\agent\omni\services\knowledge-engine\app\mcp\tools\experiment.py

- [ ] **Step 1: Write failing create/get tests**

Assert a planting experiment persists audience_pack_id, north_star_metric=a3_ratio, and its evaluation_policy. Assert a soft-ad experiment persists completion_rate and requires a configured three-second floor before it can be formally locked. Assert register_round, attach_arm, and experiment_adopt_script reject a script whose content_contract audience_pack_id differs from the experiment, even when SKU/intent/track match.

- [ ] **Step 2: Create the additive migration**

~~~sql
ALTER TABLE pipeline.experiments
    ADD COLUMN IF NOT EXISTS audience_pack_id UUID
        REFERENCES pipeline.audience_packs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS evaluation_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS convergence_meta JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE pipeline.experiment_rounds
    ADD COLUMN IF NOT EXISTS evaluation_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_experiments_audience_pack
    ON pipeline.experiments (audience_pack_id)
    WHERE audience_pack_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_experiments_content_identity
    ON pipeline.experiments (
        sku_id,
        audience_pack_id,
        intent,
        track,
        north_star_metric,
        status
    );
~~~

- [ ] **Step 3: Change intent defaults**

~~~python
INTENT_NORTH_STAR = {
    "planting": ("a3_ratio", "higher_better", ["new_a3", "a3_cost", "completion_rate", "ctr", "roi"]),
    "harvest": ("cvr", "higher_better", ["roi", "gmv"]),
    "soft_ad": ("completion_rate", "higher_better", ["play_3s_rate", "average_watch_time_seconds", "plays"]),
    "hard_ad": ("cvr", "higher_better", ["roi", "gmv"]),
}
~~~

Add content_framework_route, narrative_framework, proof_framework, presentation_motif, pain_selling_point_bridge, value_proposition_route, scene_need_route, product_action, and the existing atomic variables to the sweep pool. The canonical selling-point key is selling_point and the canonical sound key is sound_vector. Preserve backward keys only through an explicit normalization table: selling_point_set → selling_point and bgm → sound_vector; normalize before ownership lookup and never maintain duplicate decision logic. Composite route keys are labeled composite in status/baseline/changelog. Intent remains experiment-level and cannot be swept. target_model and the AI-extra technical variables remain available only for track=ai_video. Their diffs may change only the paths declared in the shared ownership registry; they cannot change content semantics, product identity, role semantics, duration, or aspect ratio, and their winners are labeled production-technology results rather than content-framework results.

- [ ] **Step 4: Define the policy shape without inventing business thresholds**

~~~python
DEFAULT_EVALUATION_POLICY = {
    "version": "content-eval-v1",
    "min_arms": 2,
    "min_assets_per_arm": 1,
    "replication_reference": 5,
    "min_impressions_per_arm": None,
    "min_spend_per_arm": None,
    "min_denominator_per_arm": None,
    "require_one_volume_minimum": True,
    "max_exposure_ratio": None,
    "max_spend_ratio": None,
    "require_balance_limits": True,
    "require_same_data_window": True,
    "require_closed_attribution_window": True,
    "soft_ad_min_play_3s_rate": None,
    "diagnostic_thresholds": {},
    "convergence": {
        "north_star_target": None,
        "max_rounds": None,
        "max_no_improvement_rounds": None,
    },
}
~~~

Tests pass explicit numeric minima and may use 3.0 as a fixture value to exercise the mechanism. Production defaults retain n≥5 only as a replication/stability annotation, not the sole hard gate. Formal lock requires at least one configured volume minimum and explicit exposure/spend balance limits; if they are absent, return upstream_content_incomplete with detail=policy_incomplete. No ungrounded minimum impression, spend, denominator, balance ratio, diagnostic cutoff, or three-second rate is fabricated. A soft-ad policy with no play_3s floor may show ranking but returns the same ordered top-level blocker with detail=soft_ad_guardrail_missing.

- [ ] **Step 5: Extend experiment_create and REST/MCP schemas**

Add audience_pack_id and evaluation_policy parameters. Resolve and persist the adopted pack directly; do not infer it later from an arbitrary script. In one transaction, take a PostgreSQL advisory lock over SKU × pack × intent × track × north star, reuse an existing running experiment with that identity, or create exactly one new row.

Extend experiment_adopt_script with an optional explicit experiment_id. When it is omitted, auto-discovery must match SKU, intent, track, and audience_pack_id from the script content contract. register_round, attach_arm, and adopt-script paths must compare the script’s pack ID to the experiment’s pack ID and return upstream_content_incomplete with detail=audience_pack_mismatch on any mismatch. A missing pack ID is not a wildcard.

- [ ] **Step 6: Rebuild the current 066 view in migration 069**

Copy the final column order from migrations/066_match_vectors.sql, preserve production_mode, impressions_sum, and predicted_match_score, then add:

- spend_sum
- north_star_numerator_sum
- north_star_denominator_sum
- aggregation_basis
- data_start_min/data_start_max
- data_end_min/data_end_max

Use pooled counts when present:

- planting: sum(new_a3) / sum(a3_eligible_users)
- soft_ad completion: sum(play_complete) / sum(plays)
- soft_ad guardrail: sum(play_3s) / sum(plays)
- fallback: average of valid asset-level rates

Exclude values marked suspect under ad_metrics._validation. The evaluator, not the SQL view, remains the lock authority.

- [ ] **Step 7: Run tests and commit**

~~~powershell
python scripts/apply_migrations.py --only 069
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_experiment_policy_persistence.py tests/test_experiment_attach_and_batch.py"
git add migrations/069_content_experiment_policy.sql
git add -p services/knowledge-engine/app/services/experiment_lab.py services/knowledge-engine/app/mcp/tools/experiment.py
git add services/knowledge-engine/tests/test_experiment_policy_persistence.py
git diff --cached --check
git commit -m "feat: persist content experiment evaluation policy"
~~~

### Task 4: Build a single deterministic evaluator for status and lock

**Files:**

- Create: E:\agent\omni\services\knowledge-engine\app\services\experiment_evaluation.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_experiment_evaluation.py
- Modify: E:\agent\omni\services\knowledge-engine\app\services\experiment_lab.py

- [ ] **Step 1: Write table-driven evaluation tests**

Test all gates and outcomes:

~~~python
@pytest.mark.parametrize(
    ("case", "expected_gate"),
    [
        ("one_valid_arm", "insufficient_sample"),
        ("open_window", "attribution_window_open"),
        ("different_windows", "attribution_window_open"),
        ("low_sample", "insufficient_sample"),
        ("exposure_ratio_over_3", "exposure_imbalance"),
        ("spend_ratio_over_3", "exposure_imbalance"),
        ("soft_ad_below_3s_floor", "insufficient_sample"),
    ],
)
def test_hard_gates(case, expected_gate, fixtures):
    result = evaluate_round(fixtures[case])
    assert result["can_lock"] is False
    assert result["blocking_gate"] == expected_gate
~~~

Also test:

- planting ranks by pooled A3 ratio, never ROI;
- soft_ad excludes an arm below the configured three-second floor and ranks remaining arms by pooled completion rate;
- rate-only fallback is labeled asset_rate_average;
- n≥5 is described as an engineering threshold, not statistical significance;
- a high vector score never changes the winner order;
- force can bypass the low-sample gate but cannot bypass open/mismatched windows, exposure imbalance, spend imbalance, or the soft-ad guardrail.
- force cannot bypass upstream_content_incomplete(policy_incomplete) or insufficient_sample caused by missing rate-unit provenance.

- [ ] **Step 2: Implement a pure evaluator**

Expose aggregate_arm_metrics(assets, intent) and evaluate_round(experiment, round_row, arms, assets_by_arm, now) as pure functions. aggregate_arm_metrics must prefer pooled raw counts, fall back only to unit-qualified direct rates, and include aggregation_basis. evaluate_round applies policy completeness, arm count, closed/equal windows, configured volume minima, exposure/spend ratios, intent guardrails, and ranking in that order. Use the shared top-level blocker vocabulary; put distinctions such as window_mismatch, spend_balance, or play_3s_guardrail_failed in gate_details rather than creating competing error codes.

Return:

- arm ranking and aggregation basis;
- can_lock;
- blocking_gate and all gate details;
- observations containing only measured facts;
- hypotheses clearly marked as hypotheses;
- leading_arm when the winner cannot yet be locked;
- policy version and the complete evaluation snapshot.

- [ ] **Step 3: Make experiment_status use the evaluator**

Remove duplicate winner eligibility logic from experiment_status. Persist no state during status. Include the next-step recommendation but label it as an operational suggestion, not causality.

- [ ] **Step 4: Make lock_winner call the same evaluator**

If the selected arm is not the evaluator’s eligible leader, reject unless an existing explicit business override applies. force=True only bypasses insufficient_sample and records the override; it does not bypass data-integrity or delivery-balance gates.

- [ ] **Step 5: Run tests and commit**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_experiment_evaluation.py tests/test_experiment_attach_and_batch.py"
git add services/knowledge-engine/app/services/experiment_evaluation.py services/knowledge-engine/tests/test_experiment_evaluation.py
git add -p services/knowledge-engine/app/services/experiment_lab.py
git diff --cached --check
git commit -m "feat: enforce comparable content experiment evaluation"
~~~

### Task 5: Merge framework winners atomically into the baseline

**Files:**

- Create: E:\agent\omni\services\knowledge-engine\app\services\experiment_baseline.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_experiment_baseline_merge.py
- Modify: E:\agent\omni\services\knowledge-engine\app\services\experiment_lab.py

- [ ] **Step 1: Write atomic-merge tests**

Test:

- content_framework_route winner copies route ID, N/P/V, framework version, and all ownership-derived fields from the winning script contract;
- route ID is recomputed and cannot be independently supplied;
- narrative_framework changes only narrative plus its allowlisted derived fields;
- proof_framework changes only proof plus proof execution;
- presentation_motif changes only motif plus presentation-owned fields;
- role_semantics, scene.semantic, text_vector.semantic, and product_action.core_use remain fixed for every framework-level winner;
- target_model winner on ai_video updates only the arm-scoped requested model/profile fields and is recorded as a production-model result;
- an incompatible resulting N/P/V combination rejects the lock and leaves experiment, round, and arms unchanged;
- two concurrent lock attempts serialize under row locks;
- a failed experiment never overwrites the prior baseline.

- [ ] **Step 2: Implement deterministic merge**

~~~python
DERIVED_BASELINE_FIELDS = {
    "content_framework_route",
    "framework_library_version",
    "narrative_framework",
    "proof_framework",
    "presentation_motif",
    "story_structure",
    "timeline_order",
    "transition_text",
    "scene.execution_instances",
    "proof_method",
    "proof_segment_structure",
    "product_action.proof_execution",
    "production_cast_form",
    "visual_vector",
    "text_vector.presentation",
    "sound_vector",
    "camera_signal",
    "story_pace",
    "edit_pace",
}
~~~

Expose merge_winner_into_baseline(current, swept_variable, winning_contract). For content_framework_route, copy all DERIVED_BASELINE_FIELDS from the winning contract in one new dictionary and recompute the route ID. For an atomic N/P/V test, remove the selected framework’s owned paths from a deep copy, copy those paths from the winning contract, validate the new combination, then recompute content_framework_route. Return a new dictionary; never mutate current in place.

- [ ] **Step 3: Move lock_winner into one transaction**

Within one asyncpg transaction:

1. SELECT experiment FOR UPDATE.
2. SELECT round FOR UPDATE.
3. Re-run the evaluator using current assets.
4. Load the winning script content_contract.
5. Compute and validate the new baseline.
6. Mark one arm winner, lock the round, persist baseline_snapshot and evaluation_snapshot, update the experiment baseline.

Any failure rolls back all six writes.

- [ ] **Step 4: Exclude derived bookkeeping from prompt-rule distillation**

experiment_distill may summarize the human-readable winning setting, but must not create separate rules for route ID, framework version, ownership-derived fields, or data-window fields. Rules remain disabled until explicitly enabled.

- [ ] **Step 5: Run tests and commit**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_experiment_baseline_merge.py tests/test_experiment_evaluation.py tests/test_experiment_attach_and_batch.py"
git add services/knowledge-engine/app/services/experiment_baseline.py services/knowledge-engine/tests/test_experiment_baseline_merge.py
git add -p services/knowledge-engine/app/services/experiment_lab.py
git diff --cached --check
git commit -m "feat: atomically advance content experiment baselines"
~~~

### Task 6: Recommend the next single variable from observed funnel loss

**Files:**

- Create: E:\agent\omni\services\knowledge-engine\app\services\next_variable_policy.py
- Create: E:\agent\omni\services\knowledge-engine\tests\test_next_variable_policy.py
- Modify: E:\agent\omni\services\knowledge-engine\app\services\experiment_lab.py

- [ ] **Step 1: Write deterministic recommendation tests**

~~~python
@pytest.mark.parametrize(
    ("signals", "expected_candidates"),
    [
        ({"play_3s": "low"}, {"opening_hook_3s", "presentation_motif"}),
        ({"play_3s": "ok", "completion": "low"}, {"narrative_framework", "story_pace", "edit_pace"}),
        ({"completion": "ok", "a3": "low"}, {"proof_framework", "pain_selling_point_bridge", "product_action"}),
        ({"a3": "high", "roi": "low"}, {"spawn_harvest_experiment"}),
        ({"delivery_balance": "failed"}, {"rerun_same_variable"}),
    ],
)
def test_next_variable_mapping(signals, expected_candidates):
    result = recommend_next_variable(signals=signals, history=history_fixture())
    assert result["action"] in expected_candidates
~~~

Test that already failed values are not silently repeated, locked baseline values are excluded, incompatible framework atomic tests are skipped, and delivery imbalance keeps the same round/variable.

- [ ] **Step 2: Implement policy**

The policy returns one action, evidence paths, excluded variables with reasons, and a next-round seed. Signal classification must use explicit diagnostic_thresholds from evaluation_policy or a comparison explicitly defined against the locked baseline. If the required classification threshold is missing, return upstream_content_incomplete with detail=insufficient_diagnostic_policy and ask for an operator choice instead of guessing “low” or “ok.” It may choose from the deterministic candidate set based on the strongest observed loss, but it must never claim the chosen variable caused the loss.

- [ ] **Step 3: Wire experiment_next_version_seed**

Replace mechanical pool order with the policy result. Preserve override_variable only when it is legal and compatible. Include the prior baseline, failed values, window snapshot, and exact one-variable sweep contract.

- [ ] **Step 4: Run tests and commit**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_next_variable_policy.py tests/test_experiment_evaluation.py tests/test_experiment_baseline_merge.py"
git add services/knowledge-engine/app/services/next_variable_policy.py services/knowledge-engine/tests/test_next_variable_policy.py
git add -p services/knowledge-engine/app/services/experiment_lab.py
git diff --cached --check
git commit -m "feat: recommend next content test variable"
~~~

### Task 7: Implement explicit experiment convergence

**Files:**

- Create: E:\agent\omni\services\knowledge-engine\tests\test_experiment_convergence.py
- Modify: E:\agent\omni\services\knowledge-engine\app\services\experiment_lab.py
- Modify: E:\agent\omni\services\knowledge-engine\app\mcp\tools\experiment.py
- Modify: E:\agent\omni\services\knowledge-engine\app\mcp\doctor.py

- [ ] **Step 1: Write failing convergence tests**

Test:

- experiment_status returns a non-mutating stop_recommendation when a configured north-star target, max rounds, no-improvement limit, or variable-pool exhaustion condition is met;
- no threshold is invented when convergence policy fields are null;
- experiment_converge accepts only target_reached, variable_pool_exhausted, data_insufficient, bottleneck_transferred, or user_stopped;
- the tool locks the experiment row and writes status=converged plus reason, actor, timestamp, policy/evidence snapshot, and current open-round ID into convergence_meta;
- open rounds remain historically visible but cannot accept new arms once the parent experiment is converged;
- next_version_seed and register_round reject a converged experiment;
- experiment_distill no longer changes running → converged as a side effect.

- [ ] **Step 2: Run convergence tests and confirm RED**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_experiment_convergence.py"
~~~

Expected: collection or assertions fail because experiment_converge and convergence_meta behavior do not exist.

- [ ] **Step 3: Implement the deterministic service and MCP tool**

Add experiment_converge(experiment_id, reason, note=None, evidence=None). It changes state only after an explicit tool call. Evaluator recommendations are advisory and never mutate the experiment automatically.

- [ ] **Step 4: Register and verify the new tool**

Add experiment_converge to the authoritative doctor wanted set and tool registration path.

- [ ] **Step 5: Run tests and commit**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_experiment_convergence.py tests/test_experiment_evaluation.py tests/test_next_variable_policy.py"
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
git add services/knowledge-engine/tests/test_experiment_convergence.py
git add -p services/knowledge-engine/app/services/experiment_lab.py services/knowledge-engine/app/mcp/tools/experiment.py services/knowledge-engine/app/mcp/doctor.py
git diff --cached --check
git commit -m "feat: add explicit content experiment convergence"
~~~

### Task 8: End-to-end multi-round verification

**Files:**

- Test: all files touched in this plan

- [ ] **Step 1: Add one multi-round acceptance test**

Create a planting experiment with audience_pack_id, register two content_framework_route arms, post comparable A3 data, lock the winner, ask for the next seed, register a second round sweeping opening_hook_3s, and assert:

- Round 1 baseline atomically contains N/P/V and route ID.
- Round 2 changes only opening_hook_3s.
- failed Round 2 data does not replace Round 1 baseline.
- changelog distinguishes “composite route leader” from “atomic variable leader.”

- [ ] **Step 2: Run the experiment suite**

~~~powershell
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m pytest -q tests/test_pipeline_asset_metrics_api.py tests/test_ad_metrics_normalization.py tests/test_diagnose_and_validation.py tests/test_experiment_attach_and_batch.py tests/test_experiment_policy_persistence.py tests/test_experiment_evaluation.py tests/test_experiment_baseline_merge.py tests/test_next_variable_policy.py tests/test_experiment_convergence.py"
~~~

Expected: all pass.

- [ ] **Step 3: Run doctor and inspect the view**

~~~powershell
python scripts/apply_migrations.py --only 069
docker exec omni-knowledge-engine bash -lc "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
docker exec omni-postgres psql -U omni_user -d omni_vibe_db -c "SELECT * FROM pipeline.v_experiment_round_results LIMIT 1"
~~~

Expected: doctor remains green; the view exposes pooled metric basis, exposure/spend, windows, and predicted_match_score.

- [ ] **Step 4: Commit acceptance coverage**

Stage only the acceptance test and any reviewed fixes, run git diff --cached --check, and commit:

~~~text
test: verify multi-round content experiment loop
~~~
