import { serviceBase } from '../../../../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ jobId: string; filename: string }> },
) {
  const { jobId, filename } = await params
  const base = serviceBase()
  const upstream = await fetch(
    `${base.knowledge}/api/v1/knowledge/harvester/images/${jobId}/${filename}`,
    { cache: 'no-store' },
  )

  if (!upstream.ok) {
    return new Response('Image not found', { status: upstream.status })
  }

  const contentType = upstream.headers.get('content-type') || 'image/png'
  const body = await upstream.arrayBuffer()

  return new Response(body, {
    headers: {
      'Content-Type': contentType,
      'Cache-Control': 'public, max-age=86400',
    },
  })
}
