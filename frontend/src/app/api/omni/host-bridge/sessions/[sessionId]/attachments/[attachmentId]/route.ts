import { hostBridgeAuthorization, hostBridgeBase, hostBridgeError, requireHostActor } from '../../../../_host-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: Request, context: { params: Promise<{ sessionId: string; attachmentId: string }> }) {
  try {
    await requireHostActor(request)
    const { sessionId, attachmentId } = await context.params
    const response = await fetch(`${hostBridgeBase()}/api/v1/host-bridge/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}`, {
      headers: { Authorization: hostBridgeAuthorization() }, cache: 'no-store', signal: AbortSignal.timeout(30_000),
    })
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { 'Content-Type': response.headers.get('Content-Type') || 'application/octet-stream', 'Content-Disposition': response.headers.get('Content-Disposition') || 'attachment' } })
  } catch (error) { return hostBridgeError(error) }
}
