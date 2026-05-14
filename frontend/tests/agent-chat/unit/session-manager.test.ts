import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SessionManager } from '@/lib/agent-chat/session-manager'

describe('SessionManager', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('opens session and tracks active count', () => {
    const mgr = new SessionManager({ maxActive: 3, ttlMs: 30 * 60 * 1000 })
    mgr.open('sess-1', { mcpConfigPath: '/tmp/m1.json' })
    mgr.open('sess-2', { mcpConfigPath: '/tmp/m2.json' })
    expect(mgr.activeCount()).toBe(2)
    expect(mgr.has('sess-1')).toBe(true)
  })

  it('LRU evicts oldest when over capacity', () => {
    const mgr = new SessionManager({ maxActive: 2, ttlMs: 30 * 60 * 1000 })
    const closed: string[] = []
    mgr.on('session_closed', (id) => closed.push(id))
    mgr.open('sess-1', { mcpConfigPath: '/tmp/m1.json' })
    mgr.open('sess-2', { mcpConfigPath: '/tmp/m2.json' })
    mgr.open('sess-3', { mcpConfigPath: '/tmp/m3.json' })
    expect(mgr.activeCount()).toBe(2)
    expect(mgr.has('sess-1')).toBe(false)
    expect(closed).toContain('sess-1')
  })

  it('touching session updates lru position', () => {
    const mgr = new SessionManager({ maxActive: 2, ttlMs: 30 * 60 * 1000 })
    mgr.open('sess-1', { mcpConfigPath: '/tmp/m1.json' })
    mgr.open('sess-2', { mcpConfigPath: '/tmp/m2.json' })
    mgr.touch('sess-1')
    mgr.open('sess-3', { mcpConfigPath: '/tmp/m3.json' })
    expect(mgr.has('sess-1')).toBe(true)
    expect(mgr.has('sess-2')).toBe(false)
  })

  it('auto closes session after ttl', () => {
    const mgr = new SessionManager({ maxActive: 3, ttlMs: 1000 })
    mgr.open('sess-1', { mcpConfigPath: '/tmp/m1.json' })
    vi.advanceTimersByTime(500)
    expect(mgr.has('sess-1')).toBe(true)
    vi.advanceTimersByTime(600)
    expect(mgr.has('sess-1')).toBe(false)
  })
})
