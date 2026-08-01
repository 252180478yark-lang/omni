import { hostBridgeAuthorization, hostBridgeBase, hostBridgeError, requireHostActor } from '../../../_host-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: Request, context: { params: Promise<{ sessionId: string }> }) {
  try {
    await requireHostActor(request, true)
    const { sessionId } = await context.params
    const payload = await request.json()
    const response = await fetch(`${hostBridgeBase()}/api/v1/host-bridge/sessions/${encodeURIComponent(sessionId)}/visible-auth`, {
      method: 'POST', body: JSON.stringify(payload),
      headers: { Authorization: hostBridgeAuthorization(), 'Content-Type': 'application/json' },
      cache: 'no-store', signal: AbortSignal.timeout(10_000),
    })
    return new Response(await response.arrayBuffer(), {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('Content-Type') || 'application/json' },
    })
  } catch (error) { return hostBridgeError(error) }
}
