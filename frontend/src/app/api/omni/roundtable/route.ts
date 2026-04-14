import { NextRequest } from 'next/server'
import { RoundtableController } from '@/server/roundtable/roundtable-controller'
import type { Persona } from '@/lib/personas/types'
import type { InterventionPayload, RoundHistoryPayload } from '@/server/roundtable/roundtable-controller'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface RoundtableBody {
  action: 'run-round' | 'run-summary'
  topic: string
  participants: Persona[]
  moderatorType: 'default' | 'boss'
  totalRounds: number
  kbIds: string[]
  model?: string
  provider?: string
  round?: number
  roundHistory?: RoundHistoryPayload
  interventions?: InterventionPayload[]
  targetChars?: number
}

export async function POST(req: NextRequest) {
  let body: RoundtableBody
  try {
    body = (await req.json()) as RoundtableBody
  } catch {
    return Response.json({ success: false, error: 'Invalid JSON' }, { status: 400 })
  }

  const {
    action,
    topic,
    participants,
    moderatorType,
    totalRounds,
    kbIds,
    model,
    provider,
    round = 1,
    roundHistory,
    interventions = [],
    targetChars,
  } = body

  if (!topic || !participants?.length || !kbIds?.length) {
    return Response.json({ success: false, error: '缺少 topic、participants 或 kbIds' }, { status: 400 })
  }

  const encoder = new TextEncoder()
  const controller = new RoundtableController()
  controller.restoreHistory(roundHistory)

  const stream = new ReadableStream({
    async start(streamController) {
      const sendEvent = (event: unknown) => {
        streamController.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
      }

      try {
        if (action === 'run-round') {
          await controller.runRound(
            {
              topic,
              participants,
              moderatorType,
              totalRounds,
              kbIds,
              model,
              provider,
              targetChars,
            },
            round,
            interventions,
            sendEvent,
            req.signal,
          )
        } else if (action === 'run-summary') {
          await controller.runSummary(
            {
              topic,
              participants,
              moderatorType,
              totalRounds,
              kbIds,
              model,
              provider,
              targetChars,
            },
            interventions,
            sendEvent,
            req.signal,
          )
        } else {
          sendEvent({ type: 'error', error: '未知 action' })
        }

        streamController.enqueue(encoder.encode('data: [DONE]\n\n'))
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err)
        sendEvent({ type: 'error', error: msg })
      } finally {
        streamController.close()
      }
    },
  })

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    },
  })
}
