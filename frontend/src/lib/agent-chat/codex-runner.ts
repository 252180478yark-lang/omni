import { spawn } from 'node:child_process'
import { EventEmitter } from 'node:events'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import type { Readable } from 'node:stream'
import type { ClaudeRunner, SpawnOptions } from './claude-runner'
import type { ClaudeStreamChunk } from './types'

const OMNI_SYSTEM_ROOT = process.env.OMNI_SYSTEM_ROOT || 'E:\\agent\\omni-system'
const DEFAULT_CODEX_HOME = `${OMNI_SYSTEM_ROOT}\\brain\\codex`
const DEFAULT_CODEX_CACHE = `${OMNI_SYSTEM_ROOT}\\brain\\cache`

type CodexEvent = {
  type?: string
  thread_id?: string
  usage?: { input_tokens?: number; output_tokens?: number }
  item?: {
    id?: string
    type?: string
    text?: string
    command?: string
    aggregated_output?: string
    exit_code?: number | null
    server?: string
    tool?: string
    arguments?: Record<string, unknown>
    result?: { content?: Array<{ type?: string; text?: string }> } | null
    error?: string | null
  }
}

type CodexSpawnArgOptions = Pick<
  SpawnOptions,
  'prompt' | 'appendSystemPrompt' | 'resumeSessionId' | 'cwd' | 'model' | 'effort'
>

export function buildCodexPrompt(opts: Pick<SpawnOptions, 'prompt' | 'appendSystemPrompt'>): string {
  return [opts.appendSystemPrompt, opts.prompt]
    .filter((part): part is string => !!part && part.trim().length > 0)
    .join('\n\n')
}

export function buildCodexSpawnArgs(opts: CodexSpawnArgOptions): string[] {
  const args = opts.resumeSessionId
    ? ['exec', 'resume', opts.resumeSessionId]
    : ['exec']

  args.push('--json')

  if (!opts.resumeSessionId && opts.cwd) {
    args.push('-C', opts.cwd)
  }

  if (!opts.resumeSessionId) {
    args.push('--sandbox', 'danger-full-access')
  }

  args.push('--skip-git-repo-check')

  if (opts.model) {
    args.push('--model', opts.model)
  }

  if (opts.effort) {
    args.push('--config', `model_reasoning_effort="${opts.effort}"`)
  }

  args.push(buildCodexPrompt(opts))
  return args
}

export function resolveCodexCwd(
  explicitCwd?: string,
  configuredProjectDir = process.env.OMNI_PROJECT_DIR,
  currentCwd = process.cwd(),
  omniSystemRoot = OMNI_SYSTEM_ROOT,
): string {
  const requireProjectRoot = (candidate: string, source: string): string => {
    const projectRoot = resolve(candidate)
    if (!existsSync(projectRoot) || !existsSync(resolve(projectRoot, 'AGENTS.md'))) {
      throw new Error(
        `[codex-runner] ${source} must be an existing project directory with AGENTS.md: ${candidate}`,
      )
    }
    return projectRoot
  }

  if (explicitCwd?.trim()) return requireProjectRoot(explicitCwd, 'explicit cwd')
  if (configuredProjectDir?.trim()) {
    return requireProjectRoot(configuredProjectDir, 'OMNI_PROJECT_DIR')
  }

  const conventionalProjectDir = resolve(omniSystemRoot, '..', 'omni')
  if (existsSync(resolve(conventionalProjectDir, 'AGENTS.md'))) {
    return conventionalProjectDir
  }
  return requireProjectRoot(currentCwd, 'process cwd fallback')
}

export function codexEventToClaudeChunks(event: CodexEvent, activeThreadId = ''): ClaudeStreamChunk[] {
  const threadId = event.thread_id || activeThreadId
  if (event.type === 'thread.started' && event.thread_id) {
    return [{ type: 'system', session_id: event.thread_id }]
  }

  const item = event.item
  if ((event.type === 'item.started' || event.type === 'item.completed') && item) {
    if (item.type === 'agent_message' && item.text && event.type === 'item.completed') {
      return [{
        type: 'assistant',
        session_id: threadId,
        message: {
          id: item.id || `codex-message-${Date.now()}`,
          type: 'message',
          role: 'assistant',
          content: [{ type: 'text', text: item.text }],
        },
      }]
    }

    if (item.type === 'command_execution' && event.type === 'item.started') {
      const toolUseId = item.id || `codex-command-${Date.now()}`
      return [{
        type: 'assistant',
        session_id: threadId,
        message: {
          id: toolUseId,
          type: 'message',
          role: 'assistant',
          content: [{
            type: 'tool_use',
            id: toolUseId,
            name: 'codex_shell',
            input: { command: item.command || '' },
          }],
        },
      }]
    }

    if (item.type === 'command_execution' && event.type === 'item.completed') {
      const toolUseId = item.id || `codex-command-${Date.now()}`
      return [{
        type: 'user',
        session_id: threadId,
        message: {
          id: `${toolUseId}-result-message`,
          type: 'message',
          role: 'user',
          content: [{
            type: 'tool_result',
            tool_use_id: toolUseId,
            content: item.aggregated_output || '',
            is_error: typeof item.exit_code === 'number' && item.exit_code !== 0,
          }],
        },
      }]
    }

    if (item.type === 'mcp_tool_call' && event.type === 'item.started') {
      const toolUseId = item.id || `codex-mcp-${Date.now()}`
      return [{
        type: 'assistant',
        session_id: threadId,
        message: {
          id: toolUseId,
          type: 'message',
          role: 'assistant',
          content: [{
            type: 'tool_use',
            id: toolUseId,
            name: `mcp__${item.server || 'mcp'}__${item.tool || 'tool'}`,
            input: item.arguments || {},
          }],
        },
      }]
    }

    if (item.type === 'mcp_tool_call' && event.type === 'item.completed') {
      const toolUseId = item.id || `codex-mcp-${Date.now()}`
      const resultText = item.result?.content
        ?.map((part) => part.text || '')
        .filter(Boolean)
        .join('\n') || item.error || ''
      return [{
        type: 'user',
        session_id: threadId,
        message: {
          id: `${toolUseId}-result-message`,
          type: 'message',
          role: 'user',
          content: [{
            type: 'tool_result',
            tool_use_id: toolUseId,
            content: resultText,
            is_error: !!item.error,
          }],
        },
      }]
    }
  }

  if (event.type === 'turn.completed') {
    return [{
      type: 'result',
      session_id: threadId,
      duration_ms: 0,
      total_cost_usd: 0,
      message: {
        id: `${threadId || 'codex'}-result`,
        type: 'message',
        role: 'assistant',
        content: [],
        usage: {
          input_tokens: event.usage?.input_tokens || 0,
          output_tokens: event.usage?.output_tokens || 0,
        },
      },
    }]
  }

  return []
}

async function* parseCodexEvents(stream: Readable): AsyncGenerator<CodexEvent> {
  let buffer = ''
  for await (const data of stream) {
    buffer += typeof data === 'string' ? data : (data as Buffer).toString('utf8')
    let nlIdx: number
    while ((nlIdx = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, nlIdx).trim()
      buffer = buffer.slice(nlIdx + 1)
      if (!line) continue
      try {
        yield JSON.parse(line) as CodexEvent
      } catch {
        // eslint-disable-next-line no-console
        console.error('[codex-runner] bad json line:', line.slice(0, 200))
      }
    }
  }
  if (buffer.trim()) {
    try {
      yield JSON.parse(buffer.trim()) as CodexEvent
    } catch {
      /* swallow */
    }
  }
}

export function resolveCodexCommand(
  isWindows: boolean,
  configuredPath = process.env.CODEX_CLI_PATH,
  omniSystemRoot = OMNI_SYSTEM_ROOT,
  localAppData = process.env.LOCALAPPDATA,
): string {
  const configured = configuredPath?.trim()
  const configuredNeedsShell = isWindows && /\.(?:cmd|bat)$/i.test(configured || '')
  if (
    configured
    && !configuredNeedsShell
    && (!/[\\/]/.test(configured) || existsSync(configured))
  ) {
    return configured
  }

  if (!isWindows) return 'codex'

  const candidates = [
    resolve(omniSystemRoot, 'runtimes', 'npm-global', 'codex.exe'),
    resolve(omniSystemRoot, '..', '.codex', 'app', 'resources', 'codex.exe'),
    localAppData
      ? resolve(localAppData, 'Programs', 'OpenAI', 'Codex', 'bin', 'codex.exe')
      : '',
  ]
  return candidates.find((candidate) => candidate && existsSync(candidate)) || 'codex.exe'
}

export const CODEX_SPAWN_WITH_SHELL = false

export function startCodexRunner(opts: SpawnOptions): ClaudeRunner {
  const isWindows = process.platform === 'win32'
  const codexCmd = resolveCodexCommand(isWindows)
  const configuredCodexCmd = process.env.CODEX_CLI_PATH?.trim()
  if (configuredCodexCmd && codexCmd !== configuredCodexCmd) {
    // eslint-disable-next-line no-console
    console.warn(
      `[codex-runner] CODEX_CLI_PATH does not exist; falling back to ${codexCmd}`,
    )
  }
  const cwd = resolveCodexCwd(opts.cwd)
  const args = buildCodexSpawnArgs({ ...opts, cwd })
  const emitter = new EventEmitter() as ClaudeRunner
  const env: NodeJS.ProcessEnv = { ...process.env }
  env.OMNI_SYSTEM_ROOT = env.OMNI_SYSTEM_ROOT || OMNI_SYSTEM_ROOT
  env.CODEX_HOME = env.CODEX_HOME || DEFAULT_CODEX_HOME
  env.XDG_CACHE_HOME = env.XDG_CACHE_HOME || DEFAULT_CODEX_CACHE
  env.NPM_CONFIG_PREFIX = env.NPM_CONFIG_PREFIX || `${OMNI_SYSTEM_ROOT}\\runtimes\\npm-global`

  const proc = spawn(codexCmd, args, {
    cwd,
    env,
    stdio: ['pipe', 'pipe', 'pipe'],
    shell: CODEX_SPAWN_WITH_SHELL,
  })

  ;(emitter as unknown as { proc: typeof proc }).proc = proc

  ;(async () => {
    let activeThreadId = opts.resumeSessionId || ''
    try {
      for await (const event of parseCodexEvents(proc.stdout)) {
        if (event.type === 'thread.started' && event.thread_id) {
          activeThreadId = event.thread_id
        }
        for (const chunk of codexEventToClaudeChunks(event, activeThreadId)) {
          emitter.emit('chunk', chunk)
        }
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
