import { NextRequest, NextResponse } from 'next/server'
import fs from 'node:fs/promises'
import path from 'node:path'
import { randomUUID } from 'node:crypto'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const UPLOAD_BASE = process.env.OMNI_UPLOAD_BASE || path.join(process.cwd(), '..', 'data', 'uploads')

export async function POST(req: NextRequest) {
  const url = new URL(req.url)
  const sessionId = url.searchParams.get('session_id')
  if (!sessionId) return NextResponse.json({ success: false, error: 'missing_session_id' }, { status: 400 })
  const form = await req.formData()
  const file = form.get('file') as File | null
  if (!file) return NextResponse.json({ success: false, error: 'no_file' }, { status: 400 })

  const ext = path.extname(file.name) || '.bin'
  const uuid = randomUUID()
  const dir = path.join(UPLOAD_BASE, sessionId)
  await fs.mkdir(dir, { recursive: true })
  const target = path.join(dir, `${uuid}${ext}`)
  const buffer = Buffer.from(await file.arrayBuffer())
  await fs.writeFile(target, buffer)

  const urlPath = `/api/v1/knowledge/static/uploads/${sessionId}/${uuid}${ext}`
  return NextResponse.json({
    success: true,
    data: {
      url: urlPath,
      filename: file.name,
      size: file.size,
      mime: file.type,
    },
  })
}
