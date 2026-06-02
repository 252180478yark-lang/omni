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

export async function GET() {
  const r = await pool.query(
    `SELECT id, claude_session_id, title, sku_id, last_message_preview, message_count, status, created_at, updated_at
       FROM mcp.agent_sessions
      WHERE status != 'deleted'
      ORDER BY updated_at DESC
      LIMIT 100`,
  )
  return NextResponse.json({ success: true, data: r.rows })
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as { title?: string; sku_id?: string }
  const claudeSessionId = randomUUID()
  const r = await pool.query(
    `INSERT INTO mcp.agent_sessions (claude_session_id, title, sku_id)
     VALUES ($1, $2, $3) RETURNING *`,
    [claudeSessionId, body.title || '新对话', body.sku_id || null],
  )
  return NextResponse.json({ success: true, data: r.rows[0] })
}
