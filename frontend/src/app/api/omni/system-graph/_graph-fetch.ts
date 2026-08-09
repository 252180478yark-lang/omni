import { serviceBase } from '../_shared'

export const DEFAULT_SYSTEM_GRAPH_TIMEOUT_MS = 60_000
const MIN_SYSTEM_GRAPH_TIMEOUT_MS = 1_000
const MAX_SYSTEM_GRAPH_TIMEOUT_MS = 120_000

export function systemGraphTimeoutMs(value = process.env.OMNI_SYSTEM_GRAPH_TIMEOUT_MS): number {
  if (!value) return DEFAULT_SYSTEM_GRAPH_TIMEOUT_MS
  const parsed = Number(value)
  if (!Number.isInteger(parsed) || parsed < MIN_SYSTEM_GRAPH_TIMEOUT_MS || parsed > MAX_SYSTEM_GRAPH_TIMEOUT_MS) {
    return DEFAULT_SYSTEM_GRAPH_TIMEOUT_MS
  }
  return parsed
}

export function fetchSystemGraphSnapshot(): Promise<Response> {
  return fetch(`${serviceBase().knowledge}/api/v1/system-graph/snapshot`, {
    cache: 'no-store',
    signal: AbortSignal.timeout(systemGraphTimeoutMs()),
  })
}
