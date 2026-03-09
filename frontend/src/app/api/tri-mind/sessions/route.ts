import { storage } from '@/server/tri-mind/storage'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET() {
  try {
    const sessions = storage.listSessions()
    return Response.json({ success: true, data: sessions })
  } catch (error) {
    console.error('List sessions error:', error)
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}

export async function POST() {
  try {
    const session = storage.newSession()
    return Response.json({ success: true, data: session })
  } catch (error) {
    console.error('Create session error:', error)
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
