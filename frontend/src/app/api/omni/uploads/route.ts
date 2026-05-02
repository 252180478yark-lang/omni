import { NextRequest, NextResponse } from 'next/server'
import { writeFile, mkdir } from 'fs/promises'
import { join } from 'path'
import { randomUUID } from 'crypto'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const UPLOAD_DIR = join(process.cwd(), 'public', 'uploads', 'changes')

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData()
    const file = formData.get('file') as File | null
    if (!file) {
      return NextResponse.json({ error: 'No file provided' }, { status: 400 })
    }

    const allowed = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
    if (!allowed.includes(file.type)) {
      return NextResponse.json({ error: 'Only JPEG/PNG/WebP/GIF allowed' }, { status: 400 })
    }

    if (file.size > 5 * 1024 * 1024) {
      return NextResponse.json({ error: 'File exceeds 5 MB limit' }, { status: 400 })
    }

    await mkdir(UPLOAD_DIR, { recursive: true })

    const ext = file.name.split('.').pop() || 'png'
    const filename = `${new Date().toISOString().slice(0, 10)}-${randomUUID().slice(0, 8)}.${ext}`
    const dest = join(UPLOAD_DIR, filename)

    const bytes = await file.arrayBuffer()
    await writeFile(dest, Buffer.from(bytes))

    return NextResponse.json({ path: `/uploads/changes/${filename}` }, { status: 201 })
  } catch (err) {
    console.error('[uploads] error:', err)
    return NextResponse.json({ error: 'Upload failed' }, { status: 500 })
  }
}
