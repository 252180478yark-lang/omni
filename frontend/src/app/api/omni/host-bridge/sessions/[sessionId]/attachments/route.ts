import { hostBridgeAuthorization, hostBridgeBase, hostBridgeError, requireHostActor } from '../../../_host-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: Request, context: { params: Promise<{ sessionId: string }> }) {
  try {
    await requireHostActor(request, true)
    const { sessionId } = await context.params
    const response = await fetch(`${hostBridgeBase()}/api/v1/host-bridge/sessions/${encodeURIComponent(sessionId)}/attachments`, {
      method: 'POST', body: await request.formData(), headers: { Authorization: hostBridgeAuthorization() },
      cache: 'no-store', signal: AbortSignal.timeout(30_000),
    })
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { 'Content-Type': response.headers.get('Content-Type') || 'application/json' } })
  } catch (error) { return hostBridgeError(error) }
}
