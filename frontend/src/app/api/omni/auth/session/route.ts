import { NextResponse } from 'next/server'

import {
  requireApprovalActor,
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

export async function GET(request: Request) {
  try {
    const actor = await requireApprovalActor(request)
    return NextResponse.json({ success: true, actor })
  } catch (error: unknown) {
    const safe = safeError(error)
    return NextResponse.json({ success: false, error: safe.code }, { status: safe.status })
  }
}

export async function POST(request: Request) {
  try {
    requireSameOrigin(request)
    const actor = await requireApprovalActor(request)
    return NextResponse.json({ success: true, actor, trust_mode: 'trusted-local' })
  } catch (error: unknown) {
    const safe = safeError(error)
    return NextResponse.json({ success: false, error: safe.code }, { status: safe.status })
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
  return NextResponse.json({ success: true, trust_mode: 'trusted-local' })
}
