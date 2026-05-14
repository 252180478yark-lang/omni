import { NextRequest, NextResponse } from 'next/server'
import { Pool } from 'pg'

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
  const r = await pool.query(`SELECT * FROM mcp.agent_sessions WHERE id = $1`, [id])
  if (r.rowCount === 0) return NextResponse.json({ success: false, error: 'not_found' }, { status: 404 })
  return NextResponse.json({ success: true, data: r.rows[0] })
}

export async function DELETE(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params
  await pool.query(`UPDATE mcp.agent_sessions SET status = 'deleted', updated_at = NOW() WHERE id = $1`, [id])
  return NextResponse.json({ success: true })
}

export async function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params
  const body = (await req.json().catch(() => ({}))) as { title?: string; sku_id?: string }
  const r = await pool.query(
    `UPDATE mcp.agent_sessions
        SET title = COALESCE($2, title),
            sku_id = COALESCE($3, sku_id),
            updated_at = NOW()
      WHERE id = $1
      RETURNING *`,
    [id, body.title || null, body.sku_id || null],
  )
  if (r.rowCount === 0) return NextResponse.json({ success: false, error: 'not_found' }, { status: 404 })
  return NextResponse.json({ success: true, data: r.rows[0] })
}
