import { NextRequest, NextResponse } from 'next/server'
import { Pool } from 'pg'
import { randomUUID } from 'node:crypto'

export const runtime = 'nodejs'

const pool = new Pool({
  host: process.env.PGHOST || 'localhost',
  port: parseInt(process.env.PGPORT || '5432'),
  user: process.env.PGUSER || 'omni_user',
  password: process.env.PGPASSWORD || 'omni_pass',
  database: process.env.PGDATABASE || 'omni_vibe_db',
})

export async function GET(req: NextRequest) {
  // /chat 默认只列非 sandbox session,playground 自己不读列表所以这里 default false 即可
  // 显式 ?sandbox=true 可拉 playground session(没用到,留个口)
  const url = new URL(req.url)
  const wantSandbox = url.searchParams.get('sandbox') === 'true'
  const r = await pool.query(
    `SELECT id, claude_session_id, title, sku_id, last_message_preview, message_count, status, created_at, updated_at
       FROM mcp.agent_sessions
      WHERE status != 'deleted'
        AND COALESCE(sandbox, false) = $1
      ORDER BY updated_at DESC
      LIMIT 100`,
    [wantSandbox],
  )
  return NextResponse.json({ success: true, data: r.rows })
}

export async function POST(req: NextRequest) {
  try {
    const body = (await req.json().catch(() => ({}))) as {
      title?: string
      sku_id?: string
      sandbox?: boolean
    }
    const claudeSessionId = randomUUID()
    const r = await pool.query(
      `INSERT INTO mcp.agent_sessions (claude_session_id, title, sku_id, sandbox)
       VALUES ($1, $2, $3, $4) RETURNING *`,
      [claudeSessionId, body.title || '新对话', body.sku_id || null, body.sandbox === true],
    )
    return NextResponse.json({ success: true, data: r.rows[0] })
  } catch (err) {
    const msg = (err as Error).message
    console.error('[POST /api/agent-chat/sessions] failed:', msg)
    return NextResponse.json(
      { success: false, error: msg },
      { status: 500 },
    )
  }
}
