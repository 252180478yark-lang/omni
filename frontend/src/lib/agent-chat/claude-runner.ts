import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { EventEmitter } from 'node:events'
import type { Readable } from 'node:stream'
import type { BrainEffortLevel, ClaudeStreamChunk } from './types'

// ── L0-1（蓝图 §4）：stream-json 运行时形状校验 ────────────────────────────────
// CLI 上游一改 stream-json 格式 → 原来裸 JSON.parse 静默崩。这里做轻量运行时校验：
// 校验只警告不拦（fail-open，避免误判把正常流断掉），把"格式漂移"暴露到日志。
// 注：完整 L0-1（版本钉死 + 校验收敛进三端共享 runner 包）属 §8 阶段0 runner 共享包
// （T2，会动 desktop/web/orch 三端正在跑的代码），本处只做 web 端可加法的运行时校验 + 版本可见性。
const KNOWN_CHUNK_TYPES = new Set(['system', 'assistant', 'user', 'result', 'stream_event'])

export function isValidChunkShape(parsed: unknown): boolean {
  if (typeof parsed !== 'object' || parsed === null) return false
  const t = (parsed as { type?: unknown }).type
  return typeof t === 'string' && KNOWN_CHUNK_TYPES.has(t)
}

// CLI 版本可见性：进程内只跑一次 `claude --version` 记日志，便于排查"升级后格式变了"。
let _versionLogged = false
function logCliVersionOnce(claudeCmd: string, isWindows: boolean): void {
  if (_versionLogged) return
  _versionLogged = true
  try {
    const p = spawn(claudeCmd, ['--version'], { shell: isWindows, stdio: ['ignore', 'pipe', 'ignore'] })
    // 2s 超时杀掉，防 `claude --version` 挂起导致子进程泄漏
    const killer = setTimeout(() => { try { p.kill() } catch { /* */ } }, 2000)
    let out = ''
    p.stdout.on('data', (d: Buffer) => { out += d.toString('utf8') })
    p.on('close', () => {
      clearTimeout(killer)
      // eslint-disable-next-line no-console
      console.info('[claude-runner] CLI version:', out.trim() || '(unknown)')
    })
    p.on('error', () => { clearTimeout(killer) /* swallow: 版本探测失败不影响主流程 */ })
  } catch {
    /* swallow */
  }
}

export interface SpawnOptions {
  prompt: string
  mcpConfigPath: string
  resumeSessionId?: string
  cwd?: string
  allowedTools?: string[]
  disallowedTools?: string[]
  maxTurns?: number
  /** claude --model alias 或 full name(e.g. 'sonnet' / 'claude-opus-4-7'). 默认不传 */
  model?: string
  /** claude --effort: low / medium / high / xhigh / max */
  effort?: BrainEffortLevel
  /** claude --append-system-prompt 追加到默认 system prompt 后面;不替换 */
  appendSystemPrompt?: string
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
  // 烧钱护栏：显式值（playground）> OMNI_CLAUDE_MAX_TURNS env > 默认 100；设 0 = 关闭
  const envMaxTurns = parseInt(process.env.OMNI_CLAUDE_MAX_TURNS || '', 10)
  const maxTurns = opts.maxTurns ?? (Number.isFinite(envMaxTurns) ? envMaxTurns : 100)
  if (maxTurns > 0) {
    args.push('--max-turns', String(maxTurns))
  }
  if (opts.model) {
    args.push('--model', opts.model)
  }
  if (opts.effort) {
    args.push('--effort', opts.effort)
  }
  if (opts.appendSystemPrompt && opts.appendSystemPrompt.trim().length > 0) {
    args.push('--append-system-prompt', opts.appendSystemPrompt)
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
        const parsed = JSON.parse(line)
        if (!isValidChunkShape(parsed)) {
          // eslint-disable-next-line no-console
          console.warn('[claude-runner] stream-json 形状异常（仍透传，fail-open）:',
            JSON.stringify(parsed).slice(0, 200))
        }
        yield parsed as ClaudeStreamChunk
      } catch {
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
  // CLAUDE_CLI_PATH env 优先 (老板装的可能是 claude.exe 而非 claude.cmd, 也可能不在 PATH 里);
  // 没配回退到老 PATH 解析 'claude.cmd' / 'claude'
  const claudeCmd =
    process.env.CLAUDE_CLI_PATH && process.env.CLAUDE_CLI_PATH.trim().length > 0
      ? process.env.CLAUDE_CLI_PATH
      : isWindows
        ? 'claude.cmd'
        : 'claude'

  logCliVersionOnce(claudeCmd, isWindows)  // L0-1：进程内一次性记 CLI 版本，便于排查格式漂移

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
