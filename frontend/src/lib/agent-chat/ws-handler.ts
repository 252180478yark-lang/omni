import type { WebSocket } from 'ws'
import Redis from 'ioredis'
import { getSessionManager } from './session-manager'
import { writeTempMcpConfig } from './mcp-config'
import { readSessionHistory, encodeProjectDir } from './history-reader'
import path from 'node:path'
import os from 'node:os'
import { Pool } from 'pg'
import {
  approvalServiceHeaders,
  ServiceFetchError,
  verifyApprovalActor,
} from '../../app/api/omni/_shared'
import type {
  WsClientMessage,
  WsServerMessage,
  ClaudeStreamChunk,
  ChatMessage,
  ChatAttachment,
} from './types'

// Lazy init: server.ts 用 @next/env loadEnvConfig 加载 .env.local, 但 ESM import
// hoisting 会让模块顶层 new Pool() 在 env 加载前执行 → 拿到默认 'omni_pass' 错密码.
// 改成第一次 query 时才建实例, 此时 env 已就位.
let _pool: Pool | null = null
function getPool(): Pool {
  if (!_pool) {
    _pool = new Pool({
      host: process.env.PGHOST || 'localhost',
      port: parseInt(process.env.PGPORT || '5432'),
      user: process.env.PGUSER || 'omni_user',
      password: process.env.PGPASSWORD || 'omni_pass',
      database: process.env.PGDATABASE || 'omni_vibe_db',
    })
  }
  return _pool
}

// W5-B 切片 3.2: Redis 订阅 mcp.human_gates.new，只广播给已验证审批身份的 ws
const REDIS_URL = process.env.REDIS_URL || 'redis://:changeme_redis@localhost:6379/1'
let _redisSubscriber: Redis | null = null
const _approvalConnections = new Set<WebSocket>()

function _initRedisSubscriber(): void {
  if (_redisSubscriber) return
  try {
    _redisSubscriber = new Redis(REDIS_URL, { lazyConnect: false })
    _redisSubscriber.subscribe('mcp.human_gates.new').catch((e) => {
      // eslint-disable-next-line no-console
      console.warn('[ws] redis subscribe failed:', e)
    })
    _redisSubscriber.on('message', (channel, payload) => {
      if (channel !== 'mcp.human_gates.new') return
      let data: { short_id: string; tool_name: string; summary: string }
      try {
        data = JSON.parse(payload)
      } catch {
        return
      }
      Array.from(_approvalConnections).forEach((ws) => {
        try {
          ws.send(JSON.stringify({
            kind: 'human_gate_new',
            session_id: '',
            gate: data,
          }))
        } catch {
          /* swallow */
        }
      })
    })
    _redisSubscriber.on('error', (e) => {
      // eslint-disable-next-line no-console
      console.warn('[ws] redis error:', e.message)
    })
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('[ws] redis subscriber init failed:', e)
    _redisSubscriber = null
  }
}

function send(ws: WebSocket, msg: WsServerMessage): void {
  try {
    ws.send(JSON.stringify(msg))
  } catch (e) {
    // eslint-disable-next-line no-console
    console.error('[ws] send failed:', e)
  }
}

function chunkToMessages(chunk: ClaudeStreamChunk): ChatMessage[] {
  const out: ChatMessage[] = []
  const sessionId = chunk.session_id || ''
  const createdAt = new Date().toISOString()
  if (chunk.type === 'assistant' && chunk.message) {
    for (const block of chunk.message.content) {
      if (block.type === 'text') {
        out.push({
          id: `${chunk.message.id}-text-${out.length}`,
          session_id: sessionId,
          role: 'assistant',
          text: block.text,
          created_at: createdAt,
        })
      } else if (block.type === 'tool_use') {
        out.push({
          id: `${block.id}-call`,
          session_id: sessionId,
          role: 'tool_call',
          tool_name: block.name,
          tool_args: block.input,
          tool_use_id: block.id,
          tool_status: 'pending',
          created_at: createdAt,
        })
      }
    }
  } else if (chunk.type === 'user' && chunk.message) {
    for (const block of chunk.message.content) {
      if (block.type === 'tool_result') {
        out.push({
          id: `${block.tool_use_id}-result`,
          session_id: sessionId,
          role: 'tool_result',
          tool_use_id: block.tool_use_id,
          raw_result: block.content,
          attachments: extractAttachmentsFromResult(block.content),
          created_at: createdAt,
        })
      }
    }
  }
  return out
}

function extractAttachmentsFromResult(content: unknown): ChatAttachment[] {
  if (typeof content !== 'string') return []
  let parsed: unknown
  try {
    parsed = JSON.parse(content)
  } catch {
    return []
  }
  if (typeof parsed !== 'object' || parsed === null) return []
  const obj = parsed as Record<string, unknown>
  const out: ChatAttachment[] = []
  const handleUrls = (val: unknown, type: 'image' | 'video'): void => {
    if (typeof val === 'string') out.push({ type, url: val })
    else if (Array.isArray(val)) {
      for (const v of val) {
        if (typeof v === 'string') out.push({ type, url: v })
        else if (typeof v === 'object' && v !== null && 'url' in v) {
          const u = (v as { url: unknown }).url
          if (typeof u === 'string') out.push({ type, url: u })
        }
      }
    }
  }
  if ('image_url' in obj) handleUrls(obj.image_url, 'image')
  if ('image_urls' in obj) handleUrls(obj.image_urls, 'image')
  if ('video_url' in obj) handleUrls(obj.video_url, 'video')
  if ('video_urls' in obj) handleUrls(obj.video_urls, 'video')
  if ('markdown' in obj && typeof obj.markdown === 'string') {
    out.push({ type: 'markdown', markdown: obj.markdown })
  }
  if ('script_md' in obj && typeof obj.script_md === 'string') {
    out.push({ type: 'markdown', markdown: obj.script_md })
  }
  return out
}

export function attachWsHandler(ws: WebSocket, approvalAuthorization: string | null = null): void {
  _initRedisSubscriber()
  let closed = false
  if (approvalAuthorization) {
    void verifyApprovalActor(approvalAuthorization)
      .then(() => {
        if (!closed && ws.readyState === 1) _approvalConnections.add(ws)
      })
      .catch(() => {
        // Chat compatibility remains available, but this connection is never
        // admitted to the approval notification/decision channel.
      })
  }
  ws.on('close', () => {
    closed = true
    _approvalConnections.delete(ws)
  })

  ws.on('message', async (raw) => {
    let msg: WsClientMessage
    try {
      msg = JSON.parse(raw.toString())
    } catch {
      return send(ws, { kind: 'error', error: 'bad_json' })
    }
    try {
      await handleClientMessage(ws, msg, approvalAuthorization)
    } catch (err) {
      const code = err instanceof ServiceFetchError ? err.code : 'handler_failed'
      send(ws, { kind: 'error', error: code })
    }
  })
}

async function handleClientMessage(
  ws: WebSocket,
  msg: WsClientMessage,
  approvalAuthorization: string | null,
): Promise<void> {
  const mgr = getSessionManager()

  if (msg.kind === 'open_session') {
    const r = await getPool().query<{
      id: string
      claude_session_id: string
      title: string
      sku_id: string | null
      status: string
      created_at: Date
      updated_at: Date
      message_count: number
      last_message_preview: string | null
    }>(
      `SELECT id, claude_session_id, title, sku_id, status, created_at, updated_at, message_count, last_message_preview
         FROM mcp.agent_sessions WHERE id = $1`,
      [msg.session_id],
    )
    if (r.rowCount === 0) return send(ws, { kind: 'error', error: 'session_not_found' })
    const row = r.rows[0]
    const mcpConfigPath = await writeTempMcpConfig(msg.session_id)
    const sess = mgr.open(msg.session_id, { mcpConfigPath })
    // 只在真正跑过对话(message_count>0)时 resume claude session;
    // 否则 row.claude_session_id 是 sessions POST 时塞的 placeholder fake UUID,
    // 传给 claude --resume 会报 "No conversation found" 直接退出
    if (row.message_count > 0 && row.claude_session_id) {
      sess.claudeSessionId = row.claude_session_id
    }
    const projectDir = process.env.OMNI_PROJECT_DIR || process.cwd()
    const sessionsDir = path.join(os.homedir(), '.claude', 'projects', encodeProjectDir(projectDir))
    const jsonlPath = path.join(sessionsDir, `${row.claude_session_id}.jsonl`)
    const history = await readSessionHistory(jsonlPath)
    send(ws, {
      kind: 'session_opened',
      session: {
        id: row.id,
        claude_session_id: row.claude_session_id,
        title: row.title,
        sku_id: row.sku_id,
        last_message_preview: row.last_message_preview,
        message_count: row.message_count,
        status: row.status as 'active' | 'archived' | 'deleted',
        created_at: row.created_at.toISOString(),
        updated_at: row.updated_at.toISOString(),
      },
      history,
    })
    return
  }

  if (msg.kind === 'send_prompt') {
    if (!mgr.has(msg.session_id)) return send(ws, { kind: 'error', error: 'session_not_open' })
    const cfg = msg.config
    const runner = mgr.spawn(msg.session_id, msg.prompt, {
      allowedTools: cfg?.allowed_tools && cfg.allowed_tools.length > 0 ? cfg.allowed_tools : undefined,
      maxTurns: cfg?.max_turns,
      model: cfg?.model,
      appendSystemPrompt: cfg?.append_system_prompt,
    })
    // 阶段0 块2（tool_use_id 焊归因链）：累积这一轮的 (tool_use_id, tool_name)，
    // 在 task_done（所有 tool 已执行完、KE 的 tool_calls 行已落库）后批量 POST 回填，
    // 避免 tool_use 出现时 KE 行还没落的时序坑。
    const turnToolUses: Array<{ tool_use_id: string; tool_name: string }> = []
    let claudeSessionId = ''
    runner.on('chunk', (chunk: ClaudeStreamChunk) => {
      // 累积本轮 tool_use + 捕获 Claude 侧 session id
      if (chunk.type === 'assistant' && chunk.message) {
        for (const block of chunk.message.content) {
          if (block.type === 'tool_use' && block.id && block.name) {
            turnToolUses.push({ tool_use_id: block.id, tool_name: block.name })
          }
        }
      }
      if (chunk.session_id) claudeSessionId = chunk.session_id
      const msgs = chunkToMessages(chunk)
      for (const m of msgs) {
        send(ws, { kind: 'chunk', session_id: msg.session_id, message: m })
      }
      if (chunk.type === 'result') {
        const usage = chunk.message?.usage
        const durationMs = chunk.duration_ms || 0
        const costUsd = chunk.total_cost_usd || 0
        send(ws, {
          kind: 'task_done',
          session_id: msg.session_id,
          duration_ms: durationMs,
          total_cost_usd: costUsd,
          tokens: { input: usage?.input_tokens || 0, output: usage?.output_tokens || 0 },
        })
        updateSessionStats(msg.session_id, chunk).catch(() => undefined)
        // W6 multi-device: 任务完成自动推企业微信 (老板出差时也能收到通知)
        // fire-and-forget, 没配 WECOM_WEBHOOKS 时 KE 返 skipped 不影响业务
        if (durationMs >= 10000) {
          // 只推 >=10s 的"长任务", 避免每秒级查询任务都推一条骚扰
          const keUrl = process.env.KNOWLEDGE_ENGINE_URL || 'http://knowledge-engine:8002'
          fetch(`${keUrl}/api/v1/notify/task-done`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              session_id: msg.session_id,
              duration_ms: durationMs,
              total_cost_usd: costUsd,
            }),
          }).catch((err) => {
            console.warn('[notify task_done] failed:', err?.message || err)
          })
        }
        // 阶段0 L0-2：把这次会话成本归集进月度总账（fire-and-forget，记账不阻断业务）。
        // host dev 跑前端时走 localhost；KNOWLEDGE_ENGINE_URL/OMNI_KE_URL 可覆盖。
        const keBase =
          process.env.KNOWLEDGE_ENGINE_URL || process.env.OMNI_KE_URL || 'http://localhost:8002'
        if (costUsd > 0) {
          fetch(`${keBase}/api/v1/mcp/spend/record`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              total_cost_usd: costUsd,
              session_id: msg.session_id,
              claude_session_id: claudeSessionId || undefined,
              client: 'web',
            }),
          }).catch((err) => console.warn('[spend record] failed:', err?.message || err))
        }
        // 阶段0 块2：批量回填本轮 tool_use_id 焊归因链（fire-and-forget）。
        if (turnToolUses.length > 0) {
          fetch(`${keBase}/api/v1/mcp/tool-uses/link`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              items: turnToolUses.map((t) => ({ ...t, claude_session_id: claudeSessionId || undefined })),
              within_minutes: 15,
            }),
          }).catch((err) => console.warn('[tool-uses link] failed:', err?.message || err))
        }
      }
    })
    runner.on('stderr', (data: string) => {
      // eslint-disable-next-line no-console
      console.error(`[claude-stderr ${msg.session_id}]`, data)
    })
    runner.on('error', (err: Error) => {
      console.error(`[runner ${msg.session_id}]`, err.name)
      send(ws, { kind: 'error', session_id: msg.session_id, error: 'runner_error' })
    })
    return
  }

  if (msg.kind === 'cancel') {
    const sess = mgr.get(msg.session_id)
    if (sess?.runner) sess.runner.cancel()
    return
  }

  if (msg.kind === 'close_session') {
    mgr.close(msg.session_id, 'manual')
    return
  }

  if (msg.kind === 'human_gate_decide') {
    const actor = await verifyApprovalActor(approvalAuthorization)
    const base = process.env.OMNI_KE_URL || 'http://localhost:8002'
    const url = `${base}/api/v1/mcp/human-gates/${msg.short_id}/${msg.decision}`
    const body = JSON.stringify({ note: msg.note || '' })
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...approvalServiceHeaders('POST', url, actor, body),
      },
      body,
    })
    if (!resp.ok) {
      return send(ws, { kind: 'error', error: 'gate_decide_failed', detail: `status_${resp.status}` })
    }
    return
  }
}

async function updateSessionStats(sessionId: string, chunk: ClaudeStreamChunk): Promise<void> {
  const usage = chunk.message?.usage
  await getPool().query(
    `UPDATE mcp.agent_sessions
        SET tokens_input_total = tokens_input_total + $1,
            tokens_output_total = tokens_output_total + $2,
            message_count = message_count + COALESCE($3, 0),
            updated_at = NOW()
      WHERE id = $4`,
    [usage?.input_tokens || 0, usage?.output_tokens || 0, chunk.num_turns || 0, sessionId],
  )
}
