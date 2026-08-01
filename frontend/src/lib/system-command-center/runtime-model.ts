export type RuntimeStatus = 'running' | 'completed' | 'failed' | 'cancelled' | 'partial' | 'unknown'
export type RuntimeMode = 'live' | 'delayed' | 'replaying' | 'partial' | 'failed' | 'cancelled' | 'completed' | 'disconnected'

export interface RuntimeEvent {
  cursor: number
  source: string
  event_id: string
  trace_id: string
  execution_id: string
  span_id: string | null
  parent_span_id: string | null
  correlation_id: string | null
  session_id: string | null
  gate_id: string | null
  sequence: number | null
  event_type: 'started' | 'completed' | 'failed' | 'cancelled' | 'retry' | 'gap' | 'annotation'
  status: RuntimeStatus
  span_kind: string
  node_id: string | null
  read_write: 'none' | 'read' | 'write' | 'read_write'
  payload_schema: string[]
  payload_summary: Record<string, unknown>
  observed_at: string
  received_at: string
  retention_until: string
  ordering: 'known' | 'ordering_unknown'
}

export interface RuntimeEventPage {
  trace_id: string
  events: RuntimeEvent[]
  next_cursor: number | null
  replay_hash: string
  partial: boolean
  has_more: boolean
  dropped_count: number
  redacted_count: number
}

export interface RuntimeExecutionSummary {
  trace_id: string
  execution_id: string
  session_id: string | null
  gate_id: string | null
  status: RuntimeStatus
  event_count: number
  last_cursor: number
  updated_at: string
}

export interface SystemGraphNode {
  id: string
  kind: string
  key: string
  label: string
  state: { existence: 'planned' | 'observed' | 'removed' | 'unknown'; health: string; lifecycle: string; evidence: string }
  attrs?: Record<string, unknown>
  evidence?: Array<{ path: string; line: number; symbol?: string; blob: string }>
  sources?: string[]
}

export interface SystemGraphEdge {
  id: string
  relation: string
  source: string
  target: string
  state: { existence: 'planned' | 'observed' | 'removed' | 'unknown'; health: string; lifecycle: string; evidence: string }
  confidence?: number
  attrs?: Record<string, unknown>
  evidence?: Array<{ path: string; line: number; symbol?: string; blob: string }>
  sources?: string[]
}

export interface SystemGraphSnapshot {
  snapshot_id: string
  generated_at_utc?: string
  content: {
    nodes: SystemGraphNode[]
    edges: SystemGraphEdge[]
    source_results?: Array<{ collector_id: string; version: string; status: 'success' | 'partial' | 'failed' | 'unknown'; reason_code?: string; retryable?: boolean }>
    diagnostics?: Array<{ fingerprint: string; code: string; severity: 'warning' | 'unknown'; collector_id: string }>
  }
}

export interface RuntimeFinding {
  fingerprint: string
  detector_version: string
  code: string
  severity: 'blocking' | 'warning' | 'info'
  classification: 'observed_fact' | 'hypothesis'
  state: 'open' | 'stale' | 'resolved'
  layers: Array<'planned' | 'fact' | 'runtime' | 'delivery'>
  trace_id: string
  message_zh: string
  evidence: string[]
  repair_hint: string
  verification: string
  impact_path?: string[]
  possible_fix_locations?: string[]
  history?: string[]
}

export interface RuntimeFindingPage {
  trace_id: string
  findings: RuntimeFinding[]
  source_status: 'success' | 'partial' | 'unknown'
}

export interface RuntimePlanDraft {
  draft_id: string
  finding_fingerprint: string
  trace_id: string
  base_snapshot_id: string
  title: string
  status: 'active' | 'frozen' | 'stale'
  version: number
  reused: boolean
}
