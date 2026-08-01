import { readFileSync } from 'node:fs'
import { requireApprovalActor, requireSameOrigin, ServiceFetchError } from '../_shared'

export async function requireHostActor(request: Request, mutation = false): Promise<void> {
  if (mutation) requireSameOrigin(request)
  await requireApprovalActor(request)
}

export function hostBridgeBase(): string {
  return (process.env.OMNI_HOST_BRIDGE_URL || 'http://127.0.0.1:7777').replace(/\/$/, '')
}

export function hostBridgeAuthorization(): string {
  const path = process.env.OMNI_HOST_TOKEN_FILE?.trim()
  if (!path) throw new Error('host_auth_unconfigured')
  let token = ''
  try { token = readFileSync(path, 'utf8').trim() } catch { throw new Error('host_auth_unavailable') }
  if (token.length < 24) throw new Error('host_auth_invalid')
  return `Bearer ${token}`
}

export function hostBridgeError(error: unknown): Response {
  if (error instanceof ServiceFetchError) {
    return Response.json({ success: false, error: { code: error.code, source: error.source, status: error.status } }, { status: error.status })
  }
  const code = error instanceof Error ? error.message : 'host_bridge_upstream_unavailable'
  return Response.json({ success: false, error: { code, source: 'frontend:host-bridge', status: 503 } }, { status: 503 })
}
