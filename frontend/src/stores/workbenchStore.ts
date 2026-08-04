'use client'

import { create } from 'zustand'

import type { WorkbenchMode } from '@/lib/workbench-ia'

export type { WorkbenchMode } from '@/lib/workbench-ia'
export type WorkbenchBindingStatus = 'available' | 'unavailable' | 'unknown'
export type WorkbenchHealth = 'healthy' | 'degraded' | 'unavailable' | 'unknown'
export type WorkbenchFreshness = 'fresh' | 'stale' | 'unknown'

export interface WorkbenchContinuity {
  contextRevision: string | null
  contextLabel: string | null
  contextStatus: WorkbenchBindingStatus
  resolvedProvider: string | null
  providerStatus: WorkbenchBindingStatus
  systemHealth: WorkbenchHealth
  systemFreshness: WorkbenchFreshness
  operationId: string | null
  agentSessionId: string | null
}

interface ReadableModeStorage {
  getItem: (key: string) => string | null
}

interface WritableModeStorage {
  setItem: (key: string, value: string) => void
}

interface WorkbenchState extends WorkbenchContinuity {
  mode: WorkbenchMode
  preferenceHydrated: boolean
  preferenceError: string | null
  hydrateMode: (fallbackMode?: WorkbenchMode, storage?: ReadableModeStorage | null) => void
  setMode: (mode: WorkbenchMode, storage?: WritableModeStorage | null) => void
  bindContinuity: (binding: Partial<WorkbenchContinuity>) => void
  clearPreferenceError: () => void
  reset: () => void
}

export const WORKBENCH_MODE_STORAGE_KEY = 'omni.workbench.mode.v1'
export const WORKBENCH_PREFERENCE_ERROR = '模式偏好无法保存；当前会话仍可继续使用。'
export const WORKBENCH_OVERVIEW_MAX_AGE_MS = 5 * 60 * 1000
export const WORKBENCH_OVERVIEW_REFRESH_MS = 60 * 1000
const WORKBENCH_OVERVIEW_CLOCK_SKEW_MS = 60 * 1000

export const EMPTY_WORKBENCH_CONTINUITY: WorkbenchContinuity = Object.freeze({
  contextRevision: null,
  contextLabel: null,
  contextStatus: 'unavailable',
  resolvedProvider: null,
  providerStatus: 'unknown',
  systemHealth: 'unavailable',
  systemFreshness: 'unknown',
  operationId: null,
  agentSessionId: null,
})

function browserStorage(): Storage | null {
  return typeof window === 'undefined' ? null : window.localStorage
}

function isWorkbenchMode(value: string | null): value is WorkbenchMode {
  return value === 'work' || value === 'development'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export function parseWorkbenchOverviewObservation(
  value: unknown,
  now = Date.now(),
): Pick<WorkbenchContinuity, 'systemHealth' | 'systemFreshness'> | null {
  if (!isRecord(value) || value.success !== true || !isRecord(value.data)) return null
  const overviewHealth = value.data.health
  if (!isRecord(overviewHealth) || typeof overviewHealth.partial !== 'boolean') return null

  const summary = overviewHealth.summary
  if (!['healthy', 'degraded', 'unavailable', 'stale', 'unknown'].includes(String(summary))) return null
  if (typeof overviewHealth.generatedAt !== 'string') return null

  const generatedAt = Date.parse(overviewHealth.generatedAt)
  if (!Number.isFinite(generatedAt) || generatedAt - now > WORKBENCH_OVERVIEW_CLOCK_SKEW_MS) return null

  const age = Math.max(0, now - generatedAt)
  const systemFreshness: WorkbenchFreshness = summary === 'stale' || age > WORKBENCH_OVERVIEW_MAX_AGE_MS
    ? 'stale'
    : 'fresh'
  const systemHealth: WorkbenchHealth = summary === 'healthy'
    ? overviewHealth.partial ? 'degraded' : 'healthy'
    : summary === 'stale' ? 'degraded' : summary as WorkbenchHealth

  return { systemHealth, systemFreshness }
}

const initialState = () => ({
  mode: 'work' as WorkbenchMode,
  preferenceHydrated: false,
  preferenceError: null as string | null,
  ...EMPTY_WORKBENCH_CONTINUITY,
})

export const useWorkbenchStore = create<WorkbenchState>((set) => ({
  ...initialState(),

  hydrateMode: (fallbackMode = 'work', storage = browserStorage()) => {
    if (!storage) {
      set({ mode: fallbackMode, preferenceHydrated: true })
      return
    }

    try {
      const storedMode = storage.getItem(WORKBENCH_MODE_STORAGE_KEY)
      set({
        mode: isWorkbenchMode(storedMode) ? storedMode : fallbackMode,
        preferenceHydrated: true,
        preferenceError: null,
      })
    } catch {
      set({
        mode: fallbackMode,
        preferenceHydrated: true,
        preferenceError: WORKBENCH_PREFERENCE_ERROR,
      })
    }
  },

  setMode: (mode, storage = browserStorage()) => {
    // Mode is intentionally the only field changed here. Context, operation and
    // agent-session bindings remain stable across presentation-mode switches.
    set({ mode, preferenceHydrated: true })
    if (!storage) return

    try {
      storage.setItem(WORKBENCH_MODE_STORAGE_KEY, mode)
      set({ preferenceError: null })
    } catch {
      set({ preferenceError: WORKBENCH_PREFERENCE_ERROR })
    }
  },

  bindContinuity: (binding) => set(binding),
  clearPreferenceError: () => set({ preferenceError: null }),
  reset: () => set(initialState()),
}))
