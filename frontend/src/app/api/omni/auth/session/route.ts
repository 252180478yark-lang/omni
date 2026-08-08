import {
  LOCAL_OWNER,
  requireSameOrigin,
  ServiceFetchError,
} from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

function safeError(error: unknown, fallback = 'authentication_failed') {
  return {
    code: error instanceof ServiceFetchError ? error.code : fallback,
    status: error instanceof ServiceFetchError ? error.status : 502,
  }
}

export async function GET() {
  return Response.json({ success: true, mode: 'single-user-local', actor: LOCAL_OWNER })
}

export async function POST(request: Request) {
  try {
    requireSameOrigin(request)
    return Response.json({ success: true, mode: 'single-user-local', actor: LOCAL_OWNER })
  } catch (error: unknown) {
    const safe = safeError(error)
    return Response.json({ success: false, error: safe.code }, { status: safe.status })
  }
}

export async function DELETE(request: Request) {
  try {
    requireSameOrigin(request)
  } catch (error: unknown) {
    const safe = safeError(error)
    return Response.json(
      { success: false, error: safe.code },
      { status: safe.status },
    )
  }
  return Response.json({ success: true, mode: 'single-user-local', actor: LOCAL_OWNER })
}
