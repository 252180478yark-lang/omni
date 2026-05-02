import type { PreparedRag } from './roundtable-controller'

/**
 * Process-local TTL+LRU cache for roundtable RAG prepared contexts.
 *
 * Why: a roundtable session does N rounds × M personas. The retrieval query
 * (= topic) is identical every round, so re-running parse_query/embedding/
 * hybrid/rerank/CRAG/compress per round is pure waste. Caching by the
 * frontend-generated `roundtableId` keeps the prepared context across all
 * rounds of one session, while persona generation still runs fresh each round.
 *
 * Lifetime: in-memory only (Next.js node runtime). Cleared on server restart,
 * which is fine — at worst the next round refills it.
 */

interface Entry {
  value: PreparedRag
  expires: number
}

const MAX_ENTRIES = 50
const TTL_MS = 30 * 60 * 1000 // 30 min

const store = new Map<string, Entry>()

export function getPrepared(id: string): PreparedRag | null {
  if (!id) return null
  const e = store.get(id)
  if (!e) return null
  if (Date.now() > e.expires) {
    store.delete(id)
    return null
  }
  // LRU touch: re-insert to move to end of iteration order
  store.delete(id)
  store.set(id, e)
  return e.value
}

export function setPrepared(id: string, value: PreparedRag): void {
  if (!id) return
  if (store.has(id)) store.delete(id)
  store.set(id, { value, expires: Date.now() + TTL_MS })
  while (store.size > MAX_ENTRIES) {
    const oldest = store.keys().next().value
    if (!oldest) break
    store.delete(oldest)
  }
}

export function deletePrepared(id: string): void {
  if (!id) return
  store.delete(id)
}
