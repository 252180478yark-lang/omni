import type { SourceRef } from '@/stores/chatStore'

export type RoundtableStreamEvent =
  | {
      type: 'speech-start'
      personaId: string
      personaName: string
      personaIcon: string
      round: number
    }
  | { type: 'speech-token'; personaId: string; round: number; content: string }
  | {
      type: 'speech-done'
      personaId: string
      personaName: string
      personaIcon: string
      round: number
      content: string
      sources?: SourceRef[]
    }
  | { type: 'round-complete'; round: number }
  | { type: 'summary-start' }
  | { type: 'summary-token'; content: string }
  | { type: 'summary-continue-meta'; continueRound: number; charsSoFar: number; target: number }
  | { type: 'summary-done' }
  | { type: 'error'; personaId?: string; error: string }
