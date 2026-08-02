// @vitest-environment happy-dom

import { afterEach, describe, expect, it } from 'vitest'

import { isWorkbenchFlagEnabled, workbenchFlags } from '@/lib/workbench-flags'
import {
  WORKBENCH_MODE_STORAGE_KEY,
  WORKBENCH_PREFERENCE_ERROR,
  useWorkbenchStore,
} from '@/stores/workbenchStore'

class MemoryStorage {
  private readonly values = new Map<string, string>()

  getItem(key: string) {
    return this.values.get(key) ?? null
  }

  setItem(key: string, value: string) {
    this.values.set(key, value)
  }
}

afterEach(() => {
  useWorkbenchStore.getState().reset()
  window.localStorage.clear()
})

describe('workbench mode and continuity state', () => {
  it('hydrates a valid personal preference and uses the route fallback otherwise', () => {
    const storage = new MemoryStorage()
    storage.setItem(WORKBENCH_MODE_STORAGE_KEY, 'development')

    useWorkbenchStore.getState().hydrateMode('work', storage)
    expect(useWorkbenchStore.getState().mode).toBe('development')

    useWorkbenchStore.getState().reset()
    useWorkbenchStore.getState().hydrateMode('development', new MemoryStorage())
    expect(useWorkbenchStore.getState().mode).toBe('development')
  })

  it('changes only presentation mode and preserves context, operation and session identity', () => {
    const storage = new MemoryStorage()
    useWorkbenchStore.getState().bindContinuity({
      contextRevision: 'context:sku-001:rev-7',
      contextLabel: 'SKU-001',
      contextStatus: 'available',
      resolvedProvider: 'codex',
      providerStatus: 'available',
      systemHealth: 'healthy',
      systemFreshness: 'fresh',
      operationId: 'operation:001',
      agentSessionId: 'session:001',
    })

    useWorkbenchStore.getState().setMode('development', storage)
    useWorkbenchStore.getState().setMode('work', storage)

    expect(useWorkbenchStore.getState()).toMatchObject({
      mode: 'work',
      contextRevision: 'context:sku-001:rev-7',
      contextLabel: 'SKU-001',
      contextStatus: 'available',
      resolvedProvider: 'codex',
      providerStatus: 'available',
      systemHealth: 'healthy',
      systemFreshness: 'fresh',
      operationId: 'operation:001',
      agentSessionId: 'session:001',
    })
    expect(storage.getItem(WORKBENCH_MODE_STORAGE_KEY)).toBe('work')
  })

  it('keeps the current-session mode and reports a recoverable persistence failure', () => {
    const failingStorage = {
      setItem() {
        throw new Error('quota exceeded')
      },
    }

    useWorkbenchStore.getState().setMode('development', failingStorage)

    expect(useWorkbenchStore.getState().mode).toBe('development')
    expect(useWorkbenchStore.getState().preferenceError).toBe(WORKBENCH_PREFERENCE_ERROR)
  })
})

describe('unified shell rollback flag', () => {
  it('is enabled by default and accepts explicit false-like rollback values', () => {
    expect(workbenchFlags({}).unifiedShell).toBe(true)
    for (const value of ['false', '0', 'off', 'NO']) {
      expect(isWorkbenchFlagEnabled('unified_shell', { unified_shell: value })).toBe(false)
    }
    expect(isWorkbenchFlagEnabled('unified_shell', { unified_shell: 'true' })).toBe(true)
  })
})
