import { randomUUID } from 'node:crypto'
import { EventEmitter } from 'node:events'
import { readFileSync } from 'node:fs'

import { codexEventToClaudeChunks } from './codex-runner'
import type { ClaudeRunner, SpawnOptions } from './claude-runner'
import type { BrainProvider, ClaudeStreamChunk } from './types'

interface HostBridgeEvent {
  cursor: number
  kind: string
  payload: { chunk?: Record<string, unknown> }
}

function hostToken(): string | null {
  const path = process.env.OMNI_HOST_TOKEN_FILE?.trim()
  if (!path) return null
  try {
    const value = readFileSync(path, 'utf8').trim()
    return value.length >= 24 ? value : null
  } catch {
    return null
  }
}

async function hostFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = hostToken()
  if (!token) throw new Error('host_auth_unconfigured')
  const base = (process.env.OMNI_HOST_BRIDGE_URL || 'http://127.0.0.1:7777').replace(/\/$/, '')
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...init.headers },
    signal: AbortSignal.timeout(5_000),
  })
  if (!response.ok) throw new Error(`host_bridge_status_${response.status}`)
  return response
}

export interface HostBridgeSpawnOptions extends SpawnOptions {
  sessionId: string
  provider: BrainProvider
  traceId: string
  executionId: string
  parentSpanId: string
  projectDir: string
  fallbackFactory?: () => ClaudeRunner
}

export function startHostBridgeRunner(options: HostBridgeSpawnOptions): ClaudeRunner {
  const emitter = new EventEmitter() as ClaudeRunner
  const procState = { killed: false }
  ;(emitter as unknown as { proc: typeof procState }).proc = procState
  let runId = ''
  let accepted = false
  let runSubmissionStarted = false
  let cancelled = false
  let fallback: ClaudeRunner | null = null

  const forwardFallback = (runner: ClaudeRunner) => {
    fallback = runner
    runner.on('chunk', (chunk: ClaudeStreamChunk) => emitter.emit('chunk', chunk))
    runner.on('stderr', (message: string) => emitter.emit('stderr', message))
    runner.on('error', (error: Error) => emitter.emit('error', error))
    runner.on('exit', (code: number | null) => emitter.emit('exit', code))
  }

  ;(async () => {
    try {
      await hostFetch('/api/v1/host-bridge/sessions', {
        method: 'POST',
        body: JSON.stringify({
          session_id: options.sessionId, runner_provider: options.provider,
          runner_session_id: options.resumeSessionId || null, project_dir: options.projectDir,
          model: options.model || null, effort: options.effort || null, trace_id: options.traceId,
          execution_id: options.executionId, parent_span_id: options.parentSpanId,
        }),
      })
      runSubmissionStarted = true
      const started = await hostFetch(`/api/v1/host-bridge/sessions/${encodeURIComponent(options.sessionId)}/runs`, {
        method: 'POST', body: JSON.stringify({ prompt: [options.appendSystemPrompt, options.prompt].filter(Boolean).join('\n\n'), request_id: `request:${randomUUID()}` }),
      })
      const run = await started.json() as { run_id: string }
      runId = run.run_id
      accepted = true
      let cursor = 0
      let codexThreadId = options.resumeSessionId || ''
      while (!cancelled) {
        const response = await hostFetch(`/api/v1/host-bridge/runs/${encodeURIComponent(runId)}/events?cursor=${cursor}`)
        const page = await response.json() as { status: string; next_cursor: number; events: HostBridgeEvent[] }
        cursor = page.next_cursor
        for (const event of page.events) {
          if (event.kind !== 'provider.chunk' || !event.payload.chunk) continue
          if (options.provider === 'codex') {
            const raw = event.payload.chunk as Parameters<typeof codexEventToClaudeChunks>[0]
            if (raw.type === 'thread.started' && typeof raw.thread_id === 'string') codexThreadId = raw.thread_id
            for (const chunk of codexEventToClaudeChunks(raw, codexThreadId)) emitter.emit('chunk', chunk)
          } else {
            emitter.emit('chunk', event.payload.chunk as unknown as ClaudeStreamChunk)
          }
        }
        if (['completed', 'failed', 'cancelled'].includes(page.status)) {
          emitter.emit('exit', page.status === 'completed' ? 0 : 1)
          return
        }
        await new Promise((resolve) => setTimeout(resolve, 250))
      }
    } catch (reason) {
      if (!runSubmissionStarted && !accepted && options.fallbackFactory) {
        forwardFallback(options.fallbackFactory())
        return
      }
      emitter.emit('error', reason instanceof Error ? reason : new Error('host_bridge_failed'))
    }
  })()

  emitter.cancel = () => {
    cancelled = true
    procState.killed = true
    if (fallback) return fallback.cancel()
    if (accepted && runId) void hostFetch(`/api/v1/host-bridge/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' }).catch(() => undefined)
  }
  return emitter
}
