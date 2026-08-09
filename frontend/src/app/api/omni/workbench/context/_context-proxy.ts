import { serviceBase } from '../../_shared'
import { hostBridgeAuthorization, hostBridgeBase } from '../../host-bridge/_host-auth'
import { requireRuntimeActor, runtimeTraceAuthorization, runtimeTraceError } from '../../runtime-traces/_runtime-auth'

interface ContextProxyPayload {
  context?: unknown
  expected_snapshot_id?: string | null
  expected_revision?: number | null
  session_id?: string | null
}

interface ContextResult {
  snapshot?: { snapshot_id?: string; revision?: number }
  reused?: boolean
}

async function hostAlreadyRebound(sessionId: string, snapshotId: string, revision: number): Promise<boolean> {
  const response = await fetch(
    `${hostBridgeBase()}/api/v1/host-bridge/sessions/${encodeURIComponent(sessionId)}`,
    {
      headers: { Authorization: hostBridgeAuthorization() },
      cache: 'no-store',
      signal: AbortSignal.timeout(3_000),
    },
  )
  if (!response.ok) return false
  const session = await response.json() as { context_snapshot_id?: string; context_revision?: number }
  return session.context_snapshot_id === snapshotId && session.context_revision === revision
}

export async function proxyWorkbenchContext(request: Request, rebind: boolean): Promise<Response> {
  try {
    await requireRuntimeActor(request, true)
    const payload = await request.json() as ContextProxyPayload
    const upstreamPayload = {
      context: payload.context,
      expected_snapshot_id: payload.expected_snapshot_id ?? null,
      expected_revision: payload.expected_revision ?? null,
    }
    const upstream = await fetch(
      `${serviceBase().knowledge}/api/v1/workbench-contexts${rebind ? '/rebind' : ''}`,
      {
        method: 'POST',
        headers: {
          Authorization: runtimeTraceAuthorization(),
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(upstreamPayload),
        cache: 'no-store',
        signal: AbortSignal.timeout(5_000),
      },
    )
    const raw = await upstream.text()
    if (!upstream.ok) {
      return new Response(raw, {
        status: upstream.status,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    const result = JSON.parse(raw) as ContextResult

    if (rebind && payload.session_id) {
      const expectedSnapshotId = payload.expected_snapshot_id
      const expectedRevision = payload.expected_revision
      const nextSnapshotId = result.snapshot?.snapshot_id
      const nextRevision = result.snapshot?.revision
      if (
        !expectedSnapshotId
        || !expectedRevision
        || !nextSnapshotId
        || !nextRevision
      ) {
        return Response.json(
          { detail: { code: 'context_rebind_projection_invalid' } },
          { status: 502 },
        )
      }
      const alreadyCurrent = expectedSnapshotId === nextSnapshotId && expectedRevision === nextRevision
      if (alreadyCurrent) {
        return new Response(raw, {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      const host = await fetch(
        `${hostBridgeBase()}/api/v1/host-bridge/sessions/${encodeURIComponent(payload.session_id)}/context`,
        {
          method: 'POST',
          headers: {
            Authorization: hostBridgeAuthorization(),
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            expected_snapshot_id: expectedSnapshotId,
            expected_revision: expectedRevision,
            next_snapshot_id: nextSnapshotId,
            next_revision: nextRevision,
          }),
          cache: 'no-store',
          signal: AbortSignal.timeout(5_000),
        },
      )
      if (!host.ok && !(host.status === 409 && await hostAlreadyRebound(
        payload.session_id,
        nextSnapshotId,
        nextRevision,
      ))) {
        return Response.json(
          {
            detail: { code: 'context_host_rebind_failed' },
            snapshot: result.snapshot,
          },
          { status: 502 },
        )
      }
    }

    return new Response(raw, {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  } catch (error) {
    return runtimeTraceError(error)
  }
}
