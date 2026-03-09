import { NextRequest } from 'next/server'
import { storage } from '@/server/tri-mind/storage'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params
    const session = storage.getSession(id)
    if (!session) {
      return Response.json({ success: false, error: 'Session not found' }, { status: 404 })
    }
    const nodes = storage.getNodesBySession(id)
    return Response.json({ success: true, data: { session, nodes } })
  } catch (error) {
    console.error('Load session error:', error)
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params
    storage.deleteSession(id)
    return Response.json({ success: true })
  } catch (error) {
    console.error('Delete session error:', error)
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
