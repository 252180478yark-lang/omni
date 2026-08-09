import { afterEach, describe, expect, it } from 'vitest'

import { buildWorkbenchActionCard } from '@/lib/workbench-runtime'
import type { SystemGraphSnapshot } from '@/lib/system-command-center/runtime-model'
import { useWorkbenchStore } from '@/stores/workbenchStore'

afterEach(() => useWorkbenchStore.getState().reset())

describe('unified AI workbench v1.3 runtime contract', () => {
  it('never proposes a write when evidence is unavailable or insufficient', () => {
    const unavailable = buildWorkbenchActionCard(null, 'what next')
    const empty = buildWorkbenchActionCard({ snapshot_id: 'snapshot:empty', content: { nodes: [], edges: [] } }, 'what next')

    expect(unavailable).toMatchObject({ evidenceState: 'unavailable', approvalRequired: false, riskLevel: 'R0' })
    expect(empty).toMatchObject({ evidenceState: 'insufficient', approvalRequired: false, riskLevel: 'R0' })
    expect([...unavailable.toolPlan, ...empty.toolPlan]).not.toContain('operation.create')
  })

  it('separates observations, inference, action, evidence and expected impact', () => {
    const snapshot: SystemGraphSnapshot = {
      snapshot_id: 'snapshot:observed', generated_at_utc: '2026-08-09T00:00:00Z',
      content: {
        nodes: [{
          id: 'service:host-bridge', kind: 'service', key: 'host-bridge', label: 'Host Bridge',
          state: { existence: 'observed', health: 'healthy', lifecycle: 'active', evidence: 'code' },
          sources: ['collector:runtime'],
        }],
        edges: [],
      },
    }
    const card = buildWorkbenchActionCard(snapshot, 'can this run?')

    expect(card.observations).toHaveLength(1)
    expect(card.inference).toContain('业务因果仍需真实经营数据验证')
    expect(card.action).toBeTruthy()
    expect(card.evidenceRefs[0]).toMatchObject({ id: 'service:host-bridge', source: 'collector:runtime' })
    expect(card.expectedImpact).toContain('不触发外部写入')
  })

  it('freezes an operation target while the current UI context advances by CAS', () => {
    expect(useWorkbenchStore.getState().rebindContext({ snapshotId: 'context:sku-a', revision: 1, label: 'SKU-A' })).toBe(true)
    const frozen = useWorkbenchStore.getState().freezeOperationContext('operation:one')
    expect(useWorkbenchStore.getState().rebindContext({
      snapshotId: 'context:sku-b', revision: 2, label: 'SKU-B',
      expectedSnapshotId: 'context:sku-a', expectedRevision: 1,
    })).toBe(true)

    expect(frozen).toEqual({ contextSnapshotId: 'context:sku-a', contextRevision: 1 })
    expect(useWorkbenchStore.getState().frozenOperationContexts['operation:one']).toEqual(frozen)
    expect(useWorkbenchStore.getState().contextSnapshotId).toBe('context:sku-b')
    expect(useWorkbenchStore.getState().contextChanged).toBe(true)
  })
})
