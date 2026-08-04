/**
 * TypeScript mirror of config/schemas/workbench-foundation.v1.schema.json.
 *
 * These are wire contracts: field names intentionally remain snake_case and
 * nullable fields remain present on the payload instead of becoming optional.
 */

export const WORKBENCH_CONTRACT_VERSION = 1 as const

export const WORKBENCH_CONTEXT_AVAILABILITIES = ['available', 'unavailable'] as const
export const WORKBENCH_PRESENTATION_LEVELS = ['summary', 'development'] as const
export const WORKBENCH_REBIND_STATES = ['bound', 'stale', 'rebind_required'] as const
export const WORKBENCH_REQUESTED_PROVIDERS = ['auto', 'codex', 'claude'] as const
export const WORKBENCH_RESOLVED_PROVIDERS = ['codex', 'claude', null] as const
export const WORKBENCH_RUNNER_MODES = ['host', 'local', null] as const
export const WORKBENCH_PROVIDER_STATUSES = [
  'pending',
  'resolved',
  'active',
  'paused',
  'failed',
  'unavailable',
] as const
export const WORKBENCH_HOST_STATES = [
  'healthy',
  'degraded',
  'stale',
  'unavailable',
  'unknown',
] as const
export const WORKBENCH_HOST_PROVIDERS = ['codex', 'claude'] as const
export const WORKBENCH_ARTIFACT_KINDS = [
  'input_attachment',
  'candidate_file',
  'output_asset',
  'formal_asset',
] as const
export const WORKBENCH_ARTIFACT_STATUSES = [
  'available',
  'stale',
  'unavailable',
  'rejected',
] as const
export const WORKBENCH_RISK_LEVELS = ['R0', 'R1', 'R2', 'R3'] as const
export const WORKBENCH_OPERATION_STATES = [
  'pending',
  'running',
  'paused',
  'awaiting_approval',
  'succeeded',
  'failed',
  'partial_failed',
  'cancelled',
  'unknown',
] as const
export const WORKBENCH_EVENT_STATUSES = [
  'running',
  'completed',
  'failed',
  'cancelled',
  'partial',
  'unknown',
] as const
export const WORKBENCH_IA_MODES = ['work', 'development', 'both'] as const
export const WORKBENCH_IA_PHASES = ['active', 'visible', 'hidden', 'retirement_candidate'] as const
export const WORKBENCH_EXTENSION_SLOTS = [
  'assistant',
  'blueprint',
  'run-center',
  'approval',
  'artifact-drawer',
] as const

export type WorkbenchContextAvailability = (typeof WORKBENCH_CONTEXT_AVAILABILITIES)[number]
export type WorkbenchPresentationLevel = (typeof WORKBENCH_PRESENTATION_LEVELS)[number]
export type WorkbenchRebindState = (typeof WORKBENCH_REBIND_STATES)[number]
export type WorkbenchRequestedProvider = (typeof WORKBENCH_REQUESTED_PROVIDERS)[number]
export type WorkbenchResolvedProvider = (typeof WORKBENCH_RESOLVED_PROVIDERS)[number]
export type WorkbenchRunnerMode = (typeof WORKBENCH_RUNNER_MODES)[number]
export type WorkbenchProviderStatus = (typeof WORKBENCH_PROVIDER_STATUSES)[number]
export type WorkbenchHostState = (typeof WORKBENCH_HOST_STATES)[number]
export type WorkbenchHostProvider = (typeof WORKBENCH_HOST_PROVIDERS)[number]
export type WorkbenchArtifactKind = (typeof WORKBENCH_ARTIFACT_KINDS)[number]
export type WorkbenchArtifactStatus = (typeof WORKBENCH_ARTIFACT_STATUSES)[number]
export type WorkbenchRiskLevel = (typeof WORKBENCH_RISK_LEVELS)[number]
export type WorkbenchOperationState = (typeof WORKBENCH_OPERATION_STATES)[number]
export type WorkbenchEventStatus = (typeof WORKBENCH_EVENT_STATUSES)[number]
export type WorkbenchIAMode = (typeof WORKBENCH_IA_MODES)[number]
export type WorkbenchIAPhase = (typeof WORKBENCH_IA_PHASES)[number]
export type WorkbenchExtensionSlotName = (typeof WORKBENCH_EXTENSION_SLOTS)[number]

export interface WorkbenchContextSnapshot {
  readonly schema_version: typeof WORKBENCH_CONTRACT_VERSION
  readonly snapshot_id: string
  readonly context_ref: string
  readonly revision: number
  readonly workspace_ref: string
  readonly shop_ref: string | null
  readonly sku_ref: string | null
  readonly project_ref: string | null
  readonly environment_ref: string | null
  readonly task_ref: string | null
  readonly evidence_refs: readonly string[]
  readonly origin_surface_ref: string
  readonly permission_scope_hash: string
  readonly availability: WorkbenchContextAvailability
  readonly rebind_reason: string | null
  readonly created_at: string
}

/**
 * Projection of the Host-owned current context head for one logical session.
 * Only the Host single writer advances this head by compare-and-swap; the
 * accepted agent-session security anchor and existing operation targets stay frozen.
 */
export interface FrontendAgentBinding {
  readonly schema_version: typeof WORKBENCH_CONTRACT_VERSION
  readonly session_id: string
  /** Its frozen RunOperationProjection target may differ after a later current-head rebind. */
  readonly operation_id: string | null
  /** Host current head, replaced only by the Host single writer after a successful CAS. */
  readonly context_snapshot_id: string
  /** Monotonic CAS token paired with context_snapshot_id and advanced to the canonical next revision. */
  readonly context_revision: number
  readonly surface_ref: string
  readonly event_cursor: number | null
  readonly presentation_level: WorkbenchPresentationLevel
  readonly rebind_state: WorkbenchRebindState
}

export interface ResolvedAgentProvider {
  readonly schema_version: typeof WORKBENCH_CONTRACT_VERSION
  readonly requested_provider: WorkbenchRequestedProvider
  readonly resolved_provider: WorkbenchResolvedProvider
  readonly runner_mode: WorkbenchRunnerMode
  readonly fallback_reason_code: string | null
  readonly status: WorkbenchProviderStatus
  readonly accepted_at: string | null
  readonly capabilities: readonly string[]
}

export interface OpaqueProjectIdentity {
  readonly schema_version: typeof WORKBENCH_CONTRACT_VERSION
  readonly project_handle: string
  readonly project_hash: string
  readonly display_name: string
}

export interface HostCapabilityManifest {
  readonly schema_version: typeof WORKBENCH_CONTRACT_VERSION
  readonly protocol_version: string
  readonly state: WorkbenchHostState
  readonly build_commit: string | null
  readonly capabilities: readonly string[]
  readonly providers: readonly WorkbenchHostProvider[]
  readonly project: OpaqueProjectIdentity | null
  readonly reason_codes: readonly string[]
}

export interface AgentArtifactProjection {
  readonly schema_version: typeof WORKBENCH_CONTRACT_VERSION
  readonly cursor: number
  readonly artifact_ref: string
  readonly session_id: string
  readonly operation_id: string | null
  readonly context_snapshot_id: string
  readonly kind: WorkbenchArtifactKind
  readonly display_name: string
  readonly sha256: string
  readonly size_bytes: number
  readonly status: WorkbenchArtifactStatus
  readonly safe_diff_summary: string | null
  readonly local_handle: string | null
  readonly source_ref: string
}

/** Complete frozen operation binding: legacy is explicitly null, W5 is a non-null pair. */
export type RunOperationContextBinding =
  | {
      readonly context_snapshot_id: null
      readonly context_revision: null
    }
  | {
      readonly context_snapshot_id: string
      readonly context_revision: number
    }

/** Existing runtime operation whose frozen snapshot/revision pair never follows a later rebind. */
export type RunOperationProjection = Readonly<{
  readonly schema_version: typeof WORKBENCH_CONTRACT_VERSION
  readonly operation_id: string
  readonly session_id: string | null
  readonly attempt: number
  readonly risk_level: WorkbenchRiskLevel
  readonly state: WorkbenchOperationState
  readonly idempotency_key_hash: string | null
  readonly trace_id: string | null
  readonly checkpoint: string | null
  readonly updated_at: string
}> & RunOperationContextBinding

export interface RunEventProjection {
  readonly schema_version: typeof WORKBENCH_CONTRACT_VERSION
  readonly event_id: string
  readonly operation_id: string
  readonly attempt: number
  readonly cursor: number
  readonly type: string
  readonly raw_type: string | null
  readonly status: WorkbenchEventStatus
  readonly safe_summary: string
  readonly checkpoint: string | null
  readonly observed_at: string
}

export interface WorkbenchIAProjection {
  readonly schema_version: typeof WORKBENCH_CONTRACT_VERSION
  readonly feature_id: string
  readonly owner: string
  readonly renderer: string
  readonly canonical_route: string
  readonly aliases: readonly string[]
  readonly mode: WorkbenchIAMode
  readonly primary_group: string
  readonly contextual_groups: readonly string[]
  readonly phase: WorkbenchIAPhase
  readonly feature_flag: string | null
}

export interface WorkbenchExtensionSlot {
  readonly schema_version: typeof WORKBENCH_CONTRACT_VERSION
  readonly slot: WorkbenchExtensionSlotName
  readonly feature_id: string
  readonly order: number
}

export const WORKBENCH_CONTRACT_NAMES = [
  'WorkbenchContextSnapshot',
  'FrontendAgentBinding',
  'ResolvedAgentProvider',
  'OpaqueProjectIdentity',
  'HostCapabilityManifest',
  'AgentArtifactProjection',
  'RunOperationProjection',
  'RunEventProjection',
  'WorkbenchIAProjection',
  'WorkbenchExtensionSlot',
] as const

export type WorkbenchContractName = (typeof WORKBENCH_CONTRACT_NAMES)[number]

const WORKBENCH_CONTRACT_REQUIRED_FIELDS = {
  WorkbenchContextSnapshot: [
    'schema_version',
    'snapshot_id',
    'context_ref',
    'revision',
    'workspace_ref',
    'shop_ref',
    'sku_ref',
    'project_ref',
    'environment_ref',
    'task_ref',
    'evidence_refs',
    'origin_surface_ref',
    'permission_scope_hash',
    'availability',
    'rebind_reason',
    'created_at',
  ],
  FrontendAgentBinding: [
    'schema_version',
    'session_id',
    'operation_id',
    'context_snapshot_id',
    'context_revision',
    'surface_ref',
    'event_cursor',
    'presentation_level',
    'rebind_state',
  ],
  ResolvedAgentProvider: [
    'schema_version',
    'requested_provider',
    'resolved_provider',
    'runner_mode',
    'fallback_reason_code',
    'status',
    'accepted_at',
    'capabilities',
  ],
  OpaqueProjectIdentity: [
    'schema_version',
    'project_handle',
    'project_hash',
    'display_name',
  ],
  HostCapabilityManifest: [
    'schema_version',
    'protocol_version',
    'state',
    'build_commit',
    'capabilities',
    'providers',
    'project',
    'reason_codes',
  ],
  AgentArtifactProjection: [
    'schema_version',
    'cursor',
    'artifact_ref',
    'session_id',
    'operation_id',
    'context_snapshot_id',
    'kind',
    'display_name',
    'sha256',
    'size_bytes',
    'status',
    'safe_diff_summary',
    'local_handle',
    'source_ref',
  ],
  RunOperationProjection: [
    'schema_version',
    'operation_id',
    'session_id',
    'context_snapshot_id',
    'context_revision',
    'attempt',
    'risk_level',
    'state',
    'idempotency_key_hash',
    'trace_id',
    'checkpoint',
    'updated_at',
  ],
  RunEventProjection: [
    'schema_version',
    'event_id',
    'operation_id',
    'attempt',
    'cursor',
    'type',
    'raw_type',
    'status',
    'safe_summary',
    'checkpoint',
    'observed_at',
  ],
  WorkbenchIAProjection: [
    'schema_version',
    'feature_id',
    'owner',
    'renderer',
    'canonical_route',
    'aliases',
    'mode',
    'primary_group',
    'contextual_groups',
    'phase',
    'feature_flag',
  ],
  WorkbenchExtensionSlot: [
    'schema_version',
    'slot',
    'feature_id',
    'order',
  ],
} as const satisfies Record<WorkbenchContractName, readonly string[]>

export type WorkbenchContractFieldManifest = {
  readonly [Name in WorkbenchContractName]: {
    readonly required: (typeof WORKBENCH_CONTRACT_REQUIRED_FIELDS)[Name]
    readonly optional: readonly []
  }
}

/** Runtime required/optional field manifest used by cross-language parity tests. */
export const WORKBENCH_CONTRACT_FIELDS = Object.fromEntries(
  WORKBENCH_CONTRACT_NAMES.map((name) => [
    name,
    { required: WORKBENCH_CONTRACT_REQUIRED_FIELDS[name], optional: [] as const },
  ]),
) as WorkbenchContractFieldManifest
