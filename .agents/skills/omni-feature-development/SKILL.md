---
name: omni-feature-development
description: Enforce contract-first, full-chain development for Omni features. Use whenever creating or modifying an Omni page or frontend flow, REST/API route, MCP tool, service, database table or migration, external data source, state model, or workflow; also use for fixes or refactors that can change connections between those layers.
---

# Omni Feature Development

Develop every cross-layer feature through an explicit impact contract, evidence-backed verification, and a graph diff. Prevent a locally working file from being mistaken for a connected feature.

## Required state machine and delivery truth

Advance exactly one state at a time:

`DISCOVERED -> IMPACT_LOCKED -> IMPLEMENTING -> VERIFYING -> GRAPH_DIFF_READY -> CI attestation COMPLETE`

Do not skip or move backward. Keep the current state when rework is needed. New
schema v3 repository contracts stop at `GRAPH_DIFF_READY`; they cannot self-write
`delivered_commit` or transition to `COMPLETE`. Only commit-mode validation in CI
may create the external attestation that makes delivery complete. Historical v1/v2
contracts retain their existing `COMPLETE` semantics.

## Workflow

### 1. Discover the existing chain

- Read repository instructions and inspect the actual code, registries, OpenAPI, migrations, tests, and runtime catalogs relevant to the request.
- Trace both directions: `page -> API/BFF -> MCP or service -> database/data source` and every downstream consumer.
- Treat runtime evidence as stronger than prose. Mark an unavailable collector as `unknown`, never as `missing`.
- Record concrete node, edge, and evidence identifiers in the impact contract.

Initialize the contracts:

```powershell
python -X utf8 .agents/skills/omni-feature-development/scripts/dev_contract.py init `
  --change-dir docs/dev-changes/<change-id> `
  --change-id <change-id> `
  --title "<short title>"
```

Read [contract-spec.md](references/contract-spec.md) while filling either contract. Use [impact-template.yaml](references/impact-template.yaml) and [completion-template.yaml](references/completion-template.yaml) as field examples.

Newly initialized contracts use schema v3. Before `IMPACT_LOCKED`, fill at least one
`feature_refs[]` item (`feature_id` plus a stable `feature_ref`) and
`before_snapshot.ref`, `delivery.base_commit` with the full immutable 40-character
Git SHA, and structured `risk` fields. The feature reference is an opaque, non-empty baseline identifier
until S3 provides a graph snapshot parser; do not invent a second feature registry.
Historical v1/v2 contracts remain valid and must not be rewritten merely to add v3 fields.

### 2. Lock impact before product edits

- Declare every reused, modified, added, or removed node and its expected upstream/downstream edges.
- Declare affected files or globs, compatibility and migration behavior, out-of-scope items, risks, rollback, and deterministic verification commands.
- Classify risk as R0 documentation/tests, R1 reversible single-layer, R2 cross-layer or contract/governance/database boundary, or R3 external/paid/security/irreversible. The validator may raise the minimum from the real diff.
- R3 must declare `approval.required: true` and a machine-readable `gate_ref`.
  Commit sealing remains fail-closed until the CI-side external gate verifier exists;
  a value typed into YAML is not approval evidence.
- Include tests for every changed contract boundary. Include a migration and rollback strategy for persistent data changes.
- Validate, then transition to `IMPACT_LOCKED` before editing product code:

```powershell
python -X utf8 .agents/skills/omni-feature-development/scripts/dev_contract.py transition `
  --impact docs/dev-changes/<change-id>/impact.yaml `
  --completion docs/dev-changes/<change-id>/completion.yaml `
  --to IMPACT_LOCKED --actor codex
```

If scope changes later, update and revalidate the contract before touching the new scope. Record the change in `contract_delta`; do not silently expand.

### 3. Implement the locked scope

- Transition once to `IMPLEMENTING`.
- Reuse existing boundaries and registries before adding parallel paths.
- Keep request/response, status, identity, migration, and source contracts aligned across layers.
- Add audit, feedback, trace, and approval behavior required by the owning subsystem.
- Preserve unrelated user changes. Do not repair unrelated findings under this contract.

### 4. Verify behavior and contracts

- Populate `completion.yaml.actual_changes` from the real diff, not from the plan.
- Transition to `VERIFYING`; run the narrow tests first, then relevant integration, doctor, schema, and frontend checks.
- Record command, exit code, result, and evidence for every required verification ID.
- Test success, empty data, invalid input, permission failure, timeout/source unavailable, retries or duplicate submission, and partial failure when applicable.
- Use `scripts/check_feature_contracts.py --mode worktree` for advisory discovery.
  For a schema-v3 staged candidate, use `--mode index --base <impact.delivery.base_commit>`
  so already-committed implementation below `HEAD` stays inside the candidate scope.
  These modes derive paths from Git; do not hand-curate a changed-file list for delivery claims.

### 5. Prove the graph diff

- Re-scan the affected chain after implementation.
- Record added, modified, and removed nodes and edges in `completion.yaml.graph_diff`.
- Fail on missing required edges, unowned orphan nodes, or required checks that did not pass.
- Permit `unknown` only with an explicit reason, owner, expiry, and acceptance. Never convert collector failure into removal.
- Transition to `GRAPH_DIFF_READY` only after the completion contract validates.
- Set `completion.delivery.status: ready_for_ci`. Do not add a delivered commit to either YAML file.

### 6. Seal delivery in CI or report the blocker

- Keep the v3 repository contract at `GRAPH_DIFF_READY` and retain rollback instructions.
- Run strict candidate validation:

```powershell
python -X utf8 .agents/skills/omni-feature-development/scripts/dev_contract.py validate `
  --impact docs/dev-changes/<change-id>/impact.yaml `
  --completion docs/dev-changes/<change-id>/completion.yaml `
  --expect-state GRAPH_DIFF_READY --strict
```

- CI evaluates one immutable commit and writes the seal outside the Git tree:

```powershell
python -X utf8 scripts/check_feature_contracts.py --mode commit `
  --base <merge-base> --head <evaluation-sha> `
  --attestation-out <runner-temp>/delivery-attestation.json
```

  `worktree`, `index`, and legacy `--changed-files-file` modes can never emit this seal.

- Report changed chain, verification results, graph diff, remaining accepted unknowns, and contract paths.
- If validation or CI sealing fails, report the exact blocked state and failed evidence. Do not describe the feature as delivered or complete.

## Non-negotiable gates

- Do not modify product code before `IMPACT_LOCKED`.
- Do not add a page without its real data path, or a backend node without a declared consumer or owner.
- Do not add an API/MCP contract without registration, implementation, tests, and caller alignment.
- Do not add a database dependency without migration, compatibility, and rollback evidence.
- Do not hard-delete factual graph nodes through the graph UI; use supported business archive semantics or presentation-only hiding.
- Do not accept self-authored prose as verification evidence when a deterministic check is available.
- Every protected path in new v3 work must have exactly one v3 contract owner; zero or multiple v3 owners block delivery. Historical v1/v2 union coverage remains readable only for compatibility.

Hooks may enforce local transitions, but CI and the deterministic validator are authoritative.
