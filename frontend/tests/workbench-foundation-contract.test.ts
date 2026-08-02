import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  WORKBENCH_ARTIFACT_KINDS,
  WORKBENCH_ARTIFACT_STATUSES,
  WORKBENCH_CONTEXT_AVAILABILITIES,
  WORKBENCH_CONTRACT_FIELDS,
  WORKBENCH_CONTRACT_NAMES,
  WORKBENCH_CONTRACT_VERSION,
  WORKBENCH_EVENT_STATUSES,
  WORKBENCH_EXTENSION_SLOTS,
  WORKBENCH_HOST_PROVIDERS,
  WORKBENCH_HOST_STATES,
  WORKBENCH_IA_MODES,
  WORKBENCH_IA_PHASES,
  WORKBENCH_OPERATION_STATES,
  WORKBENCH_PRESENTATION_LEVELS,
  WORKBENCH_PROVIDER_STATUSES,
  WORKBENCH_REBIND_STATES,
  WORKBENCH_REQUESTED_PROVIDERS,
  WORKBENCH_RESOLVED_PROVIDERS,
  WORKBENCH_RISK_LEVELS,
  WORKBENCH_RUNNER_MODES,
  type FrontendAgentBinding,
  type RunOperationProjection,
  type WorkbenchContextSnapshot,
  type WorkbenchContractName,
} from '@/lib/workbench/contracts'

interface JsonSchemaNode {
  readonly $ref?: string
  readonly description?: string
  readonly type?: string | readonly string[]
  readonly const?: unknown
  readonly enum?: readonly unknown[]
  readonly pattern?: string
  readonly minimum?: number
  readonly properties?: Readonly<Record<string, JsonSchemaNode>>
  readonly required?: readonly string[]
  readonly additionalProperties?: boolean
  readonly items?: JsonSchemaNode
  readonly anyOf?: readonly JsonSchemaNode[]
  readonly oneOf?: readonly JsonSchemaNode[]
}

interface WorkbenchFoundationSchema extends JsonSchemaNode {
  readonly $defs: Readonly<Record<string, JsonSchemaNode>>
}

const schemaCandidates = [
  resolve(process.cwd(), 'config/schemas/workbench-foundation.v1.schema.json'),
  resolve(process.cwd(), '../config/schemas/workbench-foundation.v1.schema.json'),
]
const schemaPath = schemaCandidates.find(existsSync)
const contractSourceCandidates = [
  resolve(process.cwd(), 'frontend/src/lib/workbench/contracts.ts'),
  resolve(process.cwd(), 'src/lib/workbench/contracts.ts'),
]
const contractSourcePath = contractSourceCandidates.find(existsSync)

if (!schemaPath) {
  throw new Error(`workbench foundation schema not found from ${process.cwd()}`)
}
if (!contractSourcePath) {
  throw new Error(`workbench TypeScript contract not found from ${process.cwd()}`)
}

const schema = JSON.parse(readFileSync(schemaPath, 'utf8')) as WorkbenchFoundationSchema
const contractSource = readFileSync(contractSourcePath, 'utf8')

function contractDefinition(name: WorkbenchContractName): JsonSchemaNode {
  const definition = schema.$defs[name]
  if (!definition) throw new Error(`missing schema definition: ${name}`)
  return definition
}

function resolveNode(node: JsonSchemaNode): JsonSchemaNode {
  if (!node.$ref) return node
  const prefix = '#/$defs/'
  if (!node.$ref.startsWith(prefix)) throw new Error(`unsupported schema ref: ${node.$ref}`)
  const target = schema.$defs[node.$ref.slice(prefix.length)]
  if (!target) throw new Error(`missing schema ref target: ${node.$ref}`)
  return target
}

function contractProperty(name: WorkbenchContractName, field: string): JsonSchemaNode {
  const property = contractDefinition(name).properties?.[field]
  if (!property) throw new Error(`missing schema property: ${name}.${field}`)
  return resolveNode(property)
}

function enumValues(node: JsonSchemaNode): readonly unknown[] {
  const resolved = resolveNode(node)
  if (resolved.enum) return resolved.enum
  if (resolved.const !== undefined) return [resolved.const]

  const variants = resolved.anyOf || resolved.oneOf
  if (variants) {
    return variants.flatMap((variant) => {
      const item = resolveNode(variant)
      if (item.type === 'null') return [null]
      return enumValues(item)
    })
  }

  throw new Error('schema node does not define a fixed enum')
}

function expectEnum(
  contract: WorkbenchContractName,
  field: string,
  expected: readonly unknown[],
  options: { items?: boolean } = {},
) {
  const property = contractProperty(contract, field)
  const target = options.items ? property.items : property
  if (!target) throw new Error(`missing schema items: ${contract}.${field}`)
  expect(enumValues(target)).toEqual(expected)
}

describe('workbench foundation TypeScript mirror', () => {
  it('keeps all ten wire contracts and required snake_case fields in schema parity', () => {
    expect(WORKBENCH_CONTRACT_VERSION).toBe(1)
    expect(Object.keys(WORKBENCH_CONTRACT_FIELDS)).toEqual([...WORKBENCH_CONTRACT_NAMES])

    for (const name of WORKBENCH_CONTRACT_NAMES) {
      const definition = contractDefinition(name)
      const manifest = WORKBENCH_CONTRACT_FIELDS[name]
      const fields = [...manifest.required]

      expect(definition.type).toBe('object')
      expect(definition.additionalProperties).toBe(false)
      expect([...(definition.required || [])].sort()).toEqual([...fields].sort())
      expect(Object.keys(definition.properties || {}).sort()).toEqual([...fields].sort())
      expect(manifest.optional).toEqual([])
      expect(fields.every((field) => /^[a-z][a-z0-9_]*$/.test(field))).toBe(true)
      expect(enumValues(contractProperty(name, 'schema_version'))).toEqual([
        WORKBENCH_CONTRACT_VERSION,
      ])
    }
  })

  it('keeps every fixed enum and extension slot in canonical schema parity', () => {
    expectEnum('WorkbenchContextSnapshot', 'availability', WORKBENCH_CONTEXT_AVAILABILITIES)
    expectEnum('FrontendAgentBinding', 'presentation_level', WORKBENCH_PRESENTATION_LEVELS)
    expectEnum('FrontendAgentBinding', 'rebind_state', WORKBENCH_REBIND_STATES)
    expectEnum('ResolvedAgentProvider', 'requested_provider', WORKBENCH_REQUESTED_PROVIDERS)
    expectEnum('ResolvedAgentProvider', 'resolved_provider', WORKBENCH_RESOLVED_PROVIDERS)
    expectEnum('ResolvedAgentProvider', 'runner_mode', WORKBENCH_RUNNER_MODES)
    expectEnum('ResolvedAgentProvider', 'status', WORKBENCH_PROVIDER_STATUSES)
    expectEnum('HostCapabilityManifest', 'state', WORKBENCH_HOST_STATES)
    expectEnum('HostCapabilityManifest', 'providers', WORKBENCH_HOST_PROVIDERS, { items: true })
    expectEnum('AgentArtifactProjection', 'kind', WORKBENCH_ARTIFACT_KINDS)
    expectEnum('AgentArtifactProjection', 'status', WORKBENCH_ARTIFACT_STATUSES)
    expectEnum('RunOperationProjection', 'risk_level', WORKBENCH_RISK_LEVELS)
    expectEnum('RunOperationProjection', 'state', WORKBENCH_OPERATION_STATES)
    expectEnum('RunEventProjection', 'status', WORKBENCH_EVENT_STATUSES)
    expectEnum('WorkbenchIAProjection', 'mode', WORKBENCH_IA_MODES)
    expectEnum('WorkbenchIAProjection', 'phase', WORKBENCH_IA_PHASES)
    expectEnum('WorkbenchExtensionSlot', 'slot', WORKBENCH_EXTENSION_SLOTS)

    expect(WORKBENCH_EXTENSION_SLOTS).toEqual([
      'assistant',
      'blueprint',
      'run-center',
      'approval',
      'artifact-drawer',
    ])
  })

  it('exposes only opaque project identity across the public contract', () => {
    expect(WORKBENCH_CONTRACT_FIELDS.OpaqueProjectIdentity.required).toEqual([
      'schema_version',
      'project_handle',
      'project_hash',
      'display_name',
    ])
    expect(JSON.stringify(schema)).not.toContain('project_dir')

    const displayName = contractProperty('OpaqueProjectIdentity', 'display_name')
    expect(displayName.pattern).toBeTruthy()
    const safeDisplayName = new RegExp(displayName.pattern || '')

    expect(safeDisplayName.test('Omni Workspace')).toBe(true)
    expect(safeDisplayName.test('C:\\Users\\owner\\omni')).toBe(false)
    expect(safeDisplayName.test('/srv/private/omni')).toBe(false)
    expect(safeDisplayName.test('folder/repository')).toBe(false)
    expect(safeDisplayName.test('name\nsecret')).toBe(false)
  })

  it('keeps canonical routes and aliases path-only without query or fragment state', () => {
    const canonicalRoute = contractProperty('WorkbenchIAProjection', 'canonical_route')
    const aliasRoute = contractProperty('WorkbenchIAProjection', 'aliases').items
    expect(canonicalRoute.pattern).toBeTruthy()
    expect(aliasRoute?.pattern).toBeTruthy()

    for (const node of [canonicalRoute, aliasRoute!]) {
      const routePattern = new RegExp(node.pattern || '')
      expect(routePattern.test('/workspace/development')).toBe(true)
      expect(routePattern.test('/workspace/development?mode=dev')).toBe(false)
      expect(routePattern.test('/workspace/development#blueprint')).toBe(false)
      expect(routePattern.test('https://example.test/workspace')).toBe(false)
      expect(routePattern.test('/workspace\\private')).toBe(false)
    }
  })

  it('separates immutable business context from the current frontend surface', () => {
    const contextFields = WORKBENCH_CONTRACT_FIELDS.WorkbenchContextSnapshot.required
    const bindingFields = WORKBENCH_CONTRACT_FIELDS.FrontendAgentBinding.required

    expect(contextFields).toContain('origin_surface_ref')
    expect(contextFields).not.toContain('surface_ref')
    expect(bindingFields).toContain('surface_ref')
    expect(bindingFields).not.toContain('origin_surface_ref')
    for (const businessField of [
      'workspace_ref',
      'shop_ref',
      'sku_ref',
      'project_ref',
      'environment_ref',
      'task_ref',
      'evidence_refs',
      'permission_scope_hash',
    ]) {
      expect(bindingFields).not.toContain(businessField)
    }

    const originalContext: WorkbenchContextSnapshot = Object.freeze({
      schema_version: 1,
      snapshot_id: 'ctx-snapshot-1',
      context_ref: 'context-family-1',
      revision: 1,
      workspace_ref: 'workspace-1',
      shop_ref: 'shop-1',
      sku_ref: 'sku-a',
      project_ref: null,
      environment_ref: 'production',
      task_ref: 'task-1',
      evidence_refs: ['evidence-1'],
      origin_surface_ref: 'sku-detail',
      permission_scope_hash: 'sha256:permission-scope',
      availability: 'available',
      rebind_reason: null,
      created_at: '2026-08-02T00:00:00Z',
    })
    const originalBinding: FrontendAgentBinding = {
      schema_version: 1,
      session_id: 'session-1',
      operation_id: 'operation-1',
      context_snapshot_id: originalContext.snapshot_id,
      context_revision: originalContext.revision,
      surface_ref: 'sku-detail',
      event_cursor: 42,
      presentation_level: 'summary',
      rebind_state: 'bound',
    }
    const surfaceChanged: FrontendAgentBinding = {
      ...originalBinding,
      surface_ref: 'run-center',
      presentation_level: 'development',
    }

    expect(surfaceChanged).toMatchObject({
      session_id: originalBinding.session_id,
      operation_id: originalBinding.operation_id,
      context_snapshot_id: originalBinding.context_snapshot_id,
      context_revision: originalBinding.context_revision,
      event_cursor: originalBinding.event_cursor,
    })

    const reboundContext: WorkbenchContextSnapshot = {
      ...originalContext,
      snapshot_id: 'ctx-snapshot-2',
      revision: originalContext.revision + 1,
      sku_ref: 'sku-b',
      rebind_reason: 'business_object_changed',
      created_at: '2026-08-02T00:01:00Z',
    }

    expect(reboundContext.snapshot_id).not.toBe(originalContext.snapshot_id)
    expect(reboundContext.revision).toBe(2)
    expect(originalContext.sku_ref).toBe('sku-a')
  })

  it('separates the accepted session anchor, Host current-head CAS, and frozen operation target', () => {
    const binding = contractDefinition('FrontendAgentBinding')
    const operation = contractDefinition('RunOperationProjection')
    const bindingContext = binding.properties?.context_snapshot_id
    const bindingRevision = binding.properties?.context_revision
    const selectedOperation = binding.properties?.operation_id
    const operationContext = operation.properties?.context_snapshot_id
    const operationRevision = operation.properties?.context_revision

    expect(schema.description).toContain('accepted agent-session security anchor')
    expect(schema.description).toContain('Host-owned current head')
    expect(schema.description).toContain('immutable snapshot/revision target pair')
    expect(binding.description).toContain('Host-owned current context head')
    expect(bindingContext?.description).toContain('only the Host single writer')
    expect(bindingContext?.description).toContain('successful compare-and-swap')
    expect(bindingRevision?.description).toContain('expected snapshot and revision')
    expect(selectedOperation?.description).toContain('may differ from the Host current head')
    expect(operation.description).toContain('immutable target pair selected')
    expect(operationContext?.description).toContain('mcp.runtime_executions.context_snapshot_id')
    expect(operationContext?.description).toContain('never retargeted')
    expect(operation.required).toContain('context_revision')
    expect(operationRevision?.type).toEqual(['integer', 'null'])
    expect(operationRevision?.minimum).toBe(1)
    expect(operationRevision?.description).toContain('Legacy operations emit explicit null')
    expect(operationRevision?.description).toContain('new W5 operation')

    expect(contractSource).toContain('Projection of the Host-owned current context head')
    expect(contractSource).toContain('accepted agent-session security anchor')
    expect(contractSource).toContain('Host current head, replaced only by the Host single writer')
    expect(contractSource).toContain('Immutable operation target backed by mcp.runtime_executions.context_snapshot_id')
    expect(contractSource).toContain('Frozen revision: null only for legacy operations')

    const legacyOperation: RunOperationProjection = {
      schema_version: 1,
      operation_id: 'operation:legacy',
      session_id: null,
      context_snapshot_id: null,
      context_revision: null,
      attempt: 1,
      risk_level: 'R0',
      state: 'unknown',
      idempotency_key_hash: null,
      trace_id: null,
      checkpoint: null,
      updated_at: '2026-08-02T00:00:00Z',
    }
    const restartedW5Operation: RunOperationProjection = {
      ...legacyOperation,
      operation_id: 'operation:w5-revision-two',
      session_id: 'session:w5',
      context_snapshot_id: 'context:w5-revision-two',
      context_revision: 2,
      state: 'running',
    }

    expect(legacyOperation.context_revision).toBeNull()
    expect([
      restartedW5Operation.context_snapshot_id,
      restartedW5Operation.context_revision,
    ]).toEqual(['context:w5-revision-two', 2])
  })
})
