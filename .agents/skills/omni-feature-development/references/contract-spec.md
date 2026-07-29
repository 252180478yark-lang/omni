# Development contract specification

Use two versioned YAML contracts under `docs/dev-changes/<change-id>/`:

- `impact.yaml`: locks intent, scope, boundaries, required edges, risk, rollback, and verification before product edits.
- `completion.yaml`: records the real diff, executed verification, post-change graph diff, exceptions, and final result.

## Schema compatibility

The validator accepts schema versions 1, 2, and 3. Keep completed v1/v2 contracts
at their original version; historical evidence is not rewritten merely to add
delivery fields. New contracts use v3.

| Version | `feature_refs` | `before_snapshot.ref` | Completion binding |
|---|---|---|---|
| v1 | Optional and normally absent | Optional and normally absent | Existing `graph_diff.snapshot_before` rules remain unchanged. |
| v2 | Required and non-empty from `IMPACT_LOCKED`; each item has a unique non-empty `feature_id` and non-empty `feature_ref` | Required and non-empty from `IMPACT_LOCKED` | At `GRAPH_DIFF_READY` and `COMPLETE`, `completion.graph_diff.snapshot_before` must exactly equal this reference. |
| v3 | Same identity rules as v2 | Same graph binding as v2 | `impact.delivery.base_commit` binds the candidate to an immutable Git baseline. The repository contract stops at `GRAPH_DIFF_READY`; only an external CI attestation can declare the delivered commit `COMPLETE`. |

`impact.yaml` is the identity authority. `completion.yaml` must use the same
`schema_version` but does not duplicate feature references. A v2/v3 `feature_ref` is
an opaque stable reference in S1; resolving it against `FeatureDefinition` or a
graph snapshot is deferred until S3.

## State ownership

`impact.yaml.state` is authoritative. Keep `completion.yaml.state` synchronized.

| State | Required proof |
|---|---|
| `DISCOVERED` | Contract files exist and the request is identified. |
| `IMPACT_LOCKED` | Existing-chain evidence, non-empty scope and plan, required edges, compatibility, rollback, verification plan, and lock identity are valid. |
| `IMPLEMENTING` | The locked contract is unchanged or every scope delta is explicitly accepted. |
| `VERIFYING` | Actual changes are recorded and verification is in progress. |
| `GRAPH_DIFF_READY` | Every planned change maps to an actual change; required checks pass; no missing edge or unowned orphan remains. |
| `COMPLETE` | Historical v1/v2 only. For v3 this is a computed delivery status owned by a CI attestation, never a value self-authored in repository YAML. |

Transitions are forward-only and one step at a time. Failed work stays in its current state until corrected. A v3 local transition from `GRAPH_DIFF_READY` to `COMPLETE` is rejected.

## Evaluation modes and delivery authority

- `worktree`: derives tracked plus untracked changes from Git and reads contract
  files from the worktree. It is advisory and can never emit a delivery seal.
- `index`: derives the complete staged candidate from Git's index and reads the
  staged contract blobs. It can block a bad local candidate but cannot emit a seal.
- `commit`: derives the diff from explicit immutable base/head revisions and reads
  contracts from the evaluated commit tree. Only a successful commit-mode check
  may emit an external delivery attestation.
- `--changed-files-file` exists for compatibility and tests. It is not a delivery
  authority and cannot emit an attestation.

For v3, `impact.delivery.authority` is always `ci_attestation` and
`impact.delivery.base_commit` is the full 40-character commit locked before
implementation. `completion.delivery.status` becomes `ready_for_ci` at
`GRAPH_DIFF_READY`. Do not add `delivered_commit` to either repository contract:
the external attestation records the exact evaluated commit and tree without a
self-referential Git hash.

Every protected changed path covered by new v3 work has exactly one v3 contract
owner. Zero owners is uncontracted; multiple v3 owners is ambiguous and both are
blocking. Historical v1/v2 pairs retain their previous union-coverage behavior so
archived staged candidates remain readable, but they cannot issue a v3 attestation.

## Risk levels

- `R0`: documentation, tests, copy, or other non-behavioral work.
- `R1`: one internal, reversible layer.
- `R2`: cross-layer changes or API, MCP, database, governance, CI, Hook, permission,
  source, or state-machine boundaries.
- `R3`: breaking compatibility, irreversible data work, external publication,
  paid actions, secrets, or security-sensitive effects.

The contract declares `risk.level`, `reasons`, `external_effects`, and a structured
`approval` mapping (`required` plus `gate_ref`). The gate
derives a minimum from actual changed paths and contract semantics; a lower
self-declared level is rejected. R3 requires a concrete external-effect description,
`approval.required: true`, and a non-empty gate reference. S0.5 deliberately fails
closed for R3 commit-mode sealing until an external verifier can validate that
reference; self-authored approval text is never enough to issue an attestation.

## Impact contract semantics

- `feature_refs`: v2/v3 records one or more stable feature identities. Do not reuse a
  `feature_id` within a change.
- `before_snapshot.ref`: v2 records the baseline commit or snapshot reference before
  implementation. It becomes the required `graph_diff.snapshot_before` value at the
  final graph-diff states.
- `current_chain.evidence`: cite code path, registry, OpenAPI operation, migration, schema query, test, or runtime catalog. Do not cite assumptions.
- `scope`: enumerate affected page, API, MCP, service, database, data-source, state/workflow, test, and documentation nodes. Use empty lists explicitly.
- `planned_changes`: assign a stable ID to each change. Declare action (`reuse`, `modify`, `add`, `remove`), file globs, upstream/downstream node IDs, contract compatibility, and verification IDs.
- `compatibility`: explain API, database, workflow, and data-source behavior. Use `not_applicable` only with a reason.
- `graph_acceptance.required_edges`: list edges that must exist after implementation.
- `graph_acceptance.allowed_unknowns`: reserve for evidence that cannot be collected; include reason, owner, and expiry.
- `verification_plan`: use deterministic commands and state what each command proves. Mark release-critical checks `required: true`.
- `out_of_scope`: state deliberate exclusions so nearby work is not silently absorbed.
- `rollback`: identify a safe, concrete reversal path before implementation.
- `delivery`: v3 fixes the CI authority and immutable pre-change commit.
- `risk`: v3 supplies the structured R0-R3 declaration used by deterministic gates.

Every product file changed by the work must match a `planned_changes[].paths` glob or `allowed_unplanned_paths`. Contract files themselves are exempt. Globs are segment-safe: `*` never crosses `/`; use `**` only after a literal repository path segment when recursive coverage is intentional. Bare repository-wide globs are invalid. Every planned change must reference at least one required verification.

## Completion contract semantics

- `actual_changes`: derive from the actual diff. Link each entry to `planned_change_id` and list exact, non-glob paths that match that planned change's declared globs. CI compares protected diff paths and actual paths in both directions.
- `contract_delta`: record any difference from the locked impact contract. Each delta needs reason, effect, and explicit acceptance.
- `verification_results`: reuse IDs from `verification_plan`; the command must match the locked command exactly, with status, exit code, and evidence recorded. Every required check must be `passed`.
- `graph_diff.required_edges`: reproduce every locked `from/to/relation` triple and record it as `present`, `missing`, or `unknown`, with evidence. Before/after snapshot identifiers must be non-empty.
- `graph_diff.orphan_nodes`: list unexpected unowned nodes. The list must be empty at `GRAPH_DIFF_READY`.
- `graph_diff.unknowns`: include reason, owner, expiry, and `accepted: true`; an unavailable collector belongs here, not under removals.
- `graph_diff.removed_nodes`: require explicit planned removal and evidence from successful before/after collection.
- `delivery.status`: v3 must be `ready_for_ci` at `GRAPH_DIFF_READY` and must not contain `delivered_commit`.
- `final`: for v1/v2, completion is a fact only when `status` is `complete` and strict validation succeeds. For v3, final delivery exists only in the external CI attestation.

## Stable identifiers

Use readable IDs that survive refactors:

- Page: `page:/sku-pipeline`
- API: `api:POST:/api/v1/example`
- MCP: `mcp:generate_example`
- Service: `service:module.function`
- Database: `db:schema.table`
- Data source: `source:platform.endpoint`
- Workflow state: `state:workflow.status`
- Test: `test:path::case`

An edge is directional: `from` is the caller/producer and `to` is the callee/consumer. Record an explicit `relation`, such as `calls`, `reads`, `writes`, `registers`, `migrates`, or `verifies`.

## Evidence rules

Acceptable evidence includes a file and symbol, generated catalog entry, OpenAPI operation, migration ID, database introspection result, test output, or graph snapshot ID. A filename without a relevant symbol or result is not enough for a critical edge.

Distinguish these outcomes:

- `present`: both the relationship and evidence exist.
- `missing`: evidence collection succeeded and the required relationship is absent.
- `unknown`: evidence collection could not complete. Attach owner and expiry; do not infer removal.
