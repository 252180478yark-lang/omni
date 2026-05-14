import type { WebSocket } from 'ws'
import { getSessionManager } from './session-manager'
import { writeTempMcpConfig } from './mcp-config'
import { readSessionHistory, encodeProjectDir } from './history-reader'
import path from 'node:path'
import os from 'node:os'
import { Pool } from 'pg'
import type {
  WsClientMessage,
  WsServerMessage,
  ClaudeStreamChunk,
  ChatMessage,
  ChatAttachment,
} from './types'

const pool = new Pool({
  host: process.env.PGHOST || 'localhost',
  port: parseInt(process.env.PGPORT || '5432'),
  user: process.env.PGUSER || 'omni_user',
  password: process.env.PGPASSWORD || 'omni_pass',
  database: process.env.PGDATABASE || 'omni_vibe_db',
})

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

export function attachWsHandler(ws: WebSocket): void {
  ws.on('message', async (raw) => {
    let msg: WsClientMessage
    try {
      msg = JSON.parse(raw.toString())
    } catch {
      return send(ws, { kind: 'error', error: 'bad_json' })
    }
    try {
      await handleClientMessage(ws, msg)
    } catch (err) {
      const e = err as Error
      send(ws, { kind: 'error', error: 'handler_failed', detail: e.message })
    }
  })
}

async function handleClientMessage(ws: WebSocket, msg: WsClientMessage): Promise<void> {
  const mgr = getSessionManager()

  if (msg.kind === 'open_session') {
    const r = await pool.query<{
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
    sess.claudeSessionId = row.claude_session_id
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
    const runner = mgr.spawn(msg.session_id, msg.prompt)
    runner.on('chunk', (chunk: ClaudeStreamChunk) => {
      const msgs = chunkToMessages(chunk)
      for (const m of msgs) {
        send(ws, { kind: 'chunk', session_id: msg.session_id, message: m })
      }
      if (chunk.type === 'result') {
        const usage = chunk.message?.usage
        send(ws, {
          kind: 'task_done',
          session_id: msg.session_id,
          duration_ms: chunk.duration_ms || 0,
          total_cost_usd: chunk.total_cost_usd || 0,
          tokens: { input: usage?.input_tokens || 0, output: usage?.output_tokens || 0 },
        })
        updateSessionStats(msg.session_id, chunk).catch(() => undefined)
      }
    })
    runner.on('stderr', (data: string) => {
      // eslint-disable-next-line no-console
      console.error(`[claude-stderr ${msg.session_id}]`, data)
    })
    runner.on('error', (err: Error) => {
      send(ws, { kind: 'error', session_id: msg.session_id, error: 'runner_error', detail: err.message })
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
    const base = process.env.OMNI_KE_URL || 'http://localhost:8002'
    const resp = await fetch(`${base}/api/v1/mcp/human-gates/${msg.short_id}/${msg.decision}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: msg.note || '' }),
    })
    if (!resp.ok) {
      const text = await resp.text()
      return send(ws, { kind: 'error', error: 'gate_decide_failed', detail: text })
    }
    return
  }
}

async function updateSessionStats(sessionId: string, chunk: ClaudeStreamChunk): Promise<void> {
  const usage = chunk.message?.usage
  await pool.query(
    `UPDATE mcp.agent_sessions
        SET tokens_input_total = tokens_input_total + $1,
            tokens_output_total = tokens_output_total + $2,
            message_count = message_count + COALESCE($3, 0),
            updated_at = NOW()
      WHERE id = $4`,
    [usage?.input_tokens || 0, usage?.output_tokens || 0, chunk.num_turns || 0, sessionId],
  )
}
