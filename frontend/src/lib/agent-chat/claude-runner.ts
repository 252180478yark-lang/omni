import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { EventEmitter } from 'node:events'
import type { Readable } from 'node:stream'
import type { ClaudeStreamChunk } from './types'

export interface SpawnOptions {
  prompt: string
  mcpConfigPath: string
  resumeSessionId?: string
  cwd?: string
  allowedTools?: string[]
  disallowedTools?: string[]
  maxTurns?: number
}

export function buildSpawnArgs(opts: SpawnOptions): string[] {
  const args = [
    '-p', opts.prompt,
    '--output-format', 'stream-json',
    '--verbose',
    '--mcp-config', opts.mcpConfigPath,
  ]
  if (opts.resumeSessionId) {
    args.push('--resume', opts.resumeSessionId)
  }
  if (opts.allowedTools && opts.allowedTools.length > 0) {
    args.push('--allowedTools', opts.allowedTools.join(','))
  }
  if (opts.disallowedTools && opts.disallowedTools.length > 0) {
    args.push('--disallowedTools', opts.disallowedTools.join(','))
  }
  if (opts.maxTurns && opts.maxTurns > 0) {
    args.push('--max-turns', String(opts.maxTurns))
  }
  return args
}

export async function* parseStreamChunks(stream: Readable): AsyncGenerator<ClaudeStreamChunk> {
  let buffer = ''
  for await (const data of stream) {
    buffer += typeof data === 'string' ? data : (data as Buffer).toString('utf8')
    let nlIdx: number
    while ((nlIdx = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, nlIdx).trim()
      buffer = buffer.slice(nlIdx + 1)
      if (!line) continue
      try {
        yield JSON.parse(line)
      } catch (_err) {
        // eslint-disable-next-line no-console
        console.error('[claude-runner] bad json line:', line.slice(0, 200))
      }
    }
  }
  // flush remaining buffer (no trailing newline)
  if (buffer.trim()) {
    try {
      yield JSON.parse(buffer.trim())
    } catch {
      /* swallow */
    }
  }
}

export interface ClaudeRunner extends EventEmitter {
  readonly proc: ChildProcessWithoutNullStreams
  cancel(): void
}

export function startClaudeRunner(opts: SpawnOptions): ClaudeRunner {
  const args = buildSpawnArgs(opts)
  const emitter = new EventEmitter() as ClaudeRunner

  const isWindows = process.platform === 'win32'
  const claudeCmd = isWindows ? 'claude.cmd' : 'claude'

  const proc = spawn(claudeCmd, args, {
    cwd: opts.cwd || process.cwd(),
    env: { ...process.env },
    stdio: ['pipe', 'pipe', 'pipe'],
    shell: isWindows,
  })

  ;(emitter as unknown as { proc: ChildProcessWithoutNullStreams }).proc = proc

  ;(async () => {
    try {
      for await (const chunk of parseStreamChunks(proc.stdout)) {
        emitter.emit('chunk', chunk)
      }
    } catch (err) {
      emitter.emit('error', err as Error)
    }
  })()

  proc.stderr.on('data', (d: Buffer) => emitter.emit('stderr', d.toString('utf8')))
  proc.on('exit', (code: number | null) => emitter.emit('exit', code))
  proc.on('error', (err: Error) => emitter.emit('error', err))

  emitter.cancel = () => {
    try {
      proc.kill('SIGTERM')
      setTimeout(() => {
        if (!proc.killed) proc.kill('SIGKILL')
      }, 2000)
    } catch {
      /* swallow */
    }
  }

  return emitter
}
