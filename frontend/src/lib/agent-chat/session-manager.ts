import { EventEmitter } from 'node:events'
import { cleanupTempMcpConfig } from './mcp-config'
import { startClaudeRunner, type ClaudeRunner, type SpawnOptions } from './claude-runner'

export interface ActiveSession {
  id: string
  claudeSessionId: string | null
  mcpConfigPath: string
  runner: ClaudeRunner | null
  lastActiveAt: number
  ttlTimer: ReturnType<typeof setTimeout> | null
}

export interface ManagerOptions {
  maxActive: number
  ttlMs: number
}

/**
 * Events:
 *   'session_closed' - (sessionId: string, reason: 'lru' | 'ttl' | 'manual')
 */
export class SessionManager extends EventEmitter {
  private sessions = new Map<string, ActiveSession>()
  private _tick = 0

  constructor(private opts: ManagerOptions) {
    super()
  }

  private now(): number {
    // Use Date.now() as base but always increment tick to ensure strict ordering
    // even when fake timers freeze Date.now() (vitest vi.useFakeTimers).
    return Date.now() * 1000 + (this._tick++)
  }

  open(id: string, spawn: { mcpConfigPath: string }): ActiveSession {
    if (this.sessions.has(id)) {
      this.touch(id)
      return this.sessions.get(id)!
    }
    while (this.sessions.size >= this.opts.maxActive) {
      const oldest = this.findOldest()
      if (!oldest) break
      this.close(oldest, 'lru')
    }
    const sess: ActiveSession = {
      id,
      claudeSessionId: null,
      mcpConfigPath: spawn.mcpConfigPath,
      runner: null,
      lastActiveAt: this.now(),
      ttlTimer: null,
    }
    this.sessions.set(id, sess)
    this.resetTtl(sess)
    return sess
  }

  spawn(
    id: string,
    prompt: string,
    extra?: {
      allowedTools?: string[]
      maxTurns?: number
      model?: string
      appendSystemPrompt?: string
    },
  ): ClaudeRunner {
    const sess = this.sessions.get(id)
    if (!sess) throw new Error(`session ${id} not opened`)
    if (sess.runner && !sess.runner.proc.killed) {
      sess.runner.cancel()
    }
    const opts: SpawnOptions = {
      prompt,
      mcpConfigPath: sess.mcpConfigPath,
      resumeSessionId: sess.claudeSessionId || undefined,
      allowedTools: extra?.allowedTools,
      maxTurns: extra?.maxTurns,
      model: extra?.model,
      appendSystemPrompt: extra?.appendSystemPrompt,
    }
    const runner = startClaudeRunner(opts)
    sess.runner = runner
    sess.lastActiveAt = this.now()
    this.resetTtl(sess)
    runner.on('chunk', (chunk: { type: string; session_id?: string }) => {
      if (chunk.type === 'system' && chunk.session_id && !sess.claudeSessionId) {
        sess.claudeSessionId = chunk.session_id
      }
    })
    runner.on('exit', () => {
      sess.runner = null
    })
    return runner
  }

  touch(id: string): void {
    const sess = this.sessions.get(id)
    if (!sess) return
    sess.lastActiveAt = this.now()
    this.resetTtl(sess)
  }

  close(id: string, reason: 'lru' | 'ttl' | 'manual' = 'manual'): void {
    const sess = this.sessions.get(id)
    if (!sess) return
    if (sess.ttlTimer) clearTimeout(sess.ttlTimer)
    if (sess.runner && !sess.runner.proc.killed) sess.runner.cancel()
    cleanupTempMcpConfig(id).catch(() => undefined)
    this.sessions.delete(id)
    this.emit('session_closed', id, reason)
  }

  has(id: string): boolean {
    return this.sessions.has(id)
  }

  activeCount(): number {
    return this.sessions.size
  }

  get(id: string): ActiveSession | undefined {
    return this.sessions.get(id)
  }

  private findOldest(): string | null {
    let oldestId: string | null = null
    let oldestTime = Infinity
    for (const [id, s] of this.sessions) {
      if (s.lastActiveAt < oldestTime) {
        oldestTime = s.lastActiveAt
        oldestId = id
      }
    }
    return oldestId
  }

  private resetTtl(sess: ActiveSession): void {
    if (sess.ttlTimer) clearTimeout(sess.ttlTimer)
    sess.ttlTimer = setTimeout(() => {
      this.close(sess.id, 'ttl')
    }, this.opts.ttlMs)
  }
}

// 单例
let _instance: SessionManager | null = null
export function getSessionManager(): SessionManager {
  if (!_instance) {
    _instance = new SessionManager({
      maxActive: 3,
      ttlMs: 30 * 60 * 1000,
    })
  }
  return _instance
}
