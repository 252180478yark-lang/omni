import { NextRequest } from 'next/server'
import { debateController } from '@/server/tri-mind'
import type { DebateParams, StreamChunk, DebateEvent } from '@/server/tri-mind/types'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: NextRequest) {
  try {
    const params: DebateParams = await request.json()
    const abortSignal = request.signal

    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      async start(controller) {
        const streamWriter = {
          onChunk: (chunk: StreamChunk) => {
            controller.enqueue(encoder.encode(JSON.stringify(chunk) + '\n'))
          },
          onEvent: (event: DebateEvent) => {
            controller.enqueue(encoder.encode(JSON.stringify({ kind: 'event', ...event }) + '\n'))
          },
        }

        abortSignal?.addEventListener('abort', () => {
          debateController.stopGeneration(params.sessionId)
        })

        try {
          await debateController.runDebate(params, streamWriter)
        } catch (err) {
          controller.enqueue(
            encoder.encode(
              JSON.stringify({
                sessionId: params.sessionId,
                modelId: '__error__',
                content: '',
                done: true,
                error: String(err),
              }) + '\n'
            )
          )
        } finally {
          controller.close()
        }
      },
    })

    return new Response(stream, {
      headers: {
        'Content-Type': 'application/x-ndjson',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      },
    })
  } catch (error) {
    console.error('Debate API error:', error)
    return Response.json({ error: String(error) }, { status: 500 })
  }
}
