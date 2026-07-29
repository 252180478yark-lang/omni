import { NextResponse } from 'next/server'

import {
  APPROVAL_SESSION_COOKIE,
  requireApprovalActor,
  requireSameOrigin,
  ServiceFetchError,
  serviceBase,
  verifyApprovalActor,
} from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const COOKIE_MAX_AGE_SECONDS = 30 * 60

function safeError(error: unknown, fallback = 'authentication_failed') {
  return {
    code: error instanceof ServiceFetchError ? error.code : fallback,
    status: error instanceof ServiceFetchError ? error.status : 502,
  }
}

function clearSession(response: NextResponse): NextResponse {
  response.cookies.set(APPROVAL_SESSION_COOKIE, '', {
    httpOnly: true,
    sameSite: 'strict',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: 0,
  })
  return response
}

export async function GET(request: Request) {
  try {
    const actor = await requireApprovalActor(request)
    return NextResponse.json({ success: true, actor })
  } catch (error: unknown) {
    const safe = safeError(error)
    return clearSession(
      NextResponse.json(
        { success: false, error: safe.code },
        { status: safe.status },
      ),
    )
  }
}

export async function POST(request: Request) {
  try {
    requireSameOrigin(request)
    const body = await request.json() as Record<string, unknown>
    const email = typeof body.email === 'string' ? body.email.trim() : ''
    const password = typeof body.password === 'string' ? body.password : ''
    if (!email || email.length > 320 || !password || password.length > 1024) {
      return NextResponse.json(
        { success: false, error: 'invalid_credentials_shape' },
        { status: 400 },
      )
    }

    let loginResponse: Response
    try {
      loginResponse = await fetch(`${serviceBase().identity}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        cache: 'no-store',
        signal: AbortSignal.timeout(5000),
      })
    } catch {
      throw new ServiceFetchError('identity login unavailable', {
        status: 503,
        source: 'identity-service:login',
        code: 'identity_login_unavailable',
      })
    }
    const loginBody = await loginResponse.json().catch(() => null) as {
      data?: { access_token?: unknown }
    } | null
    const accessToken = loginBody?.data?.access_token
    if (!loginResponse.ok || typeof accessToken !== 'string' || !accessToken) {
      throw new ServiceFetchError('invalid credentials', {
        status: 401,
        source: 'identity-service:login',
        code: 'invalid_credentials',
      })
    }

    // Verify both account existence and admin/owner role before issuing the
    // browser session.  The raw token is never returned to client JavaScript.
    const actor = await verifyApprovalActor(`Bearer ${accessToken}`)
    const response = NextResponse.json({ success: true, actor })
    response.cookies.set(APPROVAL_SESSION_COOKIE, accessToken, {
      httpOnly: true,
      sameSite: 'strict',
      secure: process.env.NODE_ENV === 'production',
      path: '/',
      maxAge: COOKIE_MAX_AGE_SECONDS,
    })
    return response
  } catch (error: unknown) {
    const safe = safeError(error)
    return clearSession(
      NextResponse.json(
        { success: false, error: safe.code },
        { status: safe.status },
      ),
    )
  }
}

export async function DELETE(request: Request) {
  try {
    requireSameOrigin(request)
  } catch (error: unknown) {
    const safe = safeError(error)
    return NextResponse.json(
      { success: false, error: safe.code },
      { status: safe.status },
    )
  }
  return clearSession(NextResponse.json({ success: true }))
}
