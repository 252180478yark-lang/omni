import { NextRequest, NextResponse } from 'next/server'
import { Pool } from 'pg'
import path from 'node:path'
import os from 'node:os'
import { encodeProjectDir, readSessionHistory } from '@/lib/agent-chat/history-reader'

export const runtime = 'nodejs'

const pool = new Pool({
  host: process.env.PGHOST || 'localhost',
  port: parseInt(process.env.PGPORT || '5432'),
  user: process.env.PGUSER || 'omni_user',
  password: process.env.PGPASSWORD || 'omni_pass',
  database: process.env.PGDATABASE || 'omni_vibe_db',
})

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params
  const r = await pool.query<{ claude_session_id: string }>(
    `SELECT claude_session_id FROM mcp.agent_sessions WHERE id = $1`,
    [id],
  )
  if (r.rowCount === 0) return NextResponse.json({ success: false, error: 'not_found' }, { status: 404 })
  const claudeId = r.rows[0].claude_session_id
  const projectDir = process.env.OMNI_PROJECT_DIR || process.cwd()
  const jsonl = path.join(os.homedir(), '.claude', 'projects', encodeProjectDir(projectDir), `${claudeId}.jsonl`)
  const history = await readSessionHistory(jsonl)
  return NextResponse.json({ success: true, data: history })
}
