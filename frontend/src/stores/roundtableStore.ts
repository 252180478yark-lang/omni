'use client'

import { create } from 'zustand'
import { v4 as uuidv4 } from 'uuid'
import type { SourceRef } from './chatStore'

export type ModeratorType = 'default' | 'boss'

export interface RoundtableSpeech {
  id: string
  personaId: string
  personaName: string
  personaIcon: string
  round: number
  content: string
  sources?: SourceRef[]
  loading: boolean
  error?: string
  timestamp: number
}

export interface RoundtableIntervention {
  id: string
  content: string
  targetPersonaId: string | null
  afterRound: number
  timestamp: number
}

export interface RoundtableSummary {
  content: string
  moderatorType: ModeratorType
  loading: boolean
  timestamp: number
}

export interface RoundtableSession {
  id: string
  topic: string
  participantIds: string[]
  moderatorType: ModeratorType
  totalRounds: number
  currentRound: number
  kbIds: string[]
  model: string | null
  provider: string | null

  speeches: RoundtableSpeech[]
  interventions: RoundtableIntervention[]
  summary: RoundtableSummary | null

  status: 'configuring' | 'discussing' | 'intervening' | 'summarizing' | 'completed' | 'aborted'
  createdAt: number
}

interface RoundtableState {
  session: RoundtableSession | null
  abortController: AbortController | null

  createSession: (config: {
    topic: string
    participantIds: string[]
    moderatorType: ModeratorType
    totalRounds: number
    kbIds: string[]
    model?: string
    provider?: string
  }) => void
  setAbort: (c: AbortController | null) => void
  abort: () => void
  reset: () => void

  addSpeechPlaceholder: (p: Omit<RoundtableSpeech, 'id' | 'content' | 'loading' | 'timestamp'> & { id?: string }) => string
  appendSpeechToken: (speechId: string, token: string) => void
  finishSpeech: (speechId: string, sources?: SourceRef[]) => void
  failSpeech: (speechId: string, error: string) => void

  addIntervention: (content: string, targetPersonaId: string | null, afterRound: number) => void

  startSummary: () => void
  appendSummaryToken: (token: string) => void
  finishSummary: () => void

  setStatus: (status: RoundtableSession['status']) => void
  bumpCurrentRound: () => void
}

export const useRoundtableStore = create<RoundtableState>((set, get) => ({
  session: null,
  abortController: null,

  createSession: (config) => {
    const id = `rt-${Date.now()}-${uuidv4().slice(0, 8)}`
    set({
      session: {
        id,
        topic: config.topic,
        participantIds: [...config.participantIds],
        moderatorType: config.moderatorType,
        totalRounds: config.totalRounds,
        currentRound: 0,
        kbIds: [...config.kbIds],
        model: config.model ?? null,
        provider: config.provider ?? null,
        speeches: [],
        interventions: [],
        summary: null,
        status: 'discussing',
        createdAt: Date.now(),
      },
    })
  },

  setAbort: (c) => set({ abortController: c }),

  abort: () => {
    get().abortController?.abort()
    set((s) => {
      if (!s.session) return { abortController: null }
      const speeches = s.session.speeches.map((sp) =>
        sp.loading
          ? {
              ...sp,
              loading: false,
              error: sp.error ?? '已中断',
              content: sp.content.trim() ? sp.content : '（讨论已中止）',
            }
          : sp,
      )
      return {
        abortController: null,
        session: { ...s.session, status: 'aborted', speeches },
      }
    })
  },

  reset: () => set({ session: null, abortController: null }),

  addSpeechPlaceholder: (p) => {
    const id = p.id ?? `sp-${Date.now()}-${uuidv4().slice(0, 6)}`
    const speech: RoundtableSpeech = {
      id,
      personaId: p.personaId,
      personaName: p.personaName,
      personaIcon: p.personaIcon,
      round: p.round,
      content: '',
      loading: true,
      timestamp: Date.now(),
    }
    set((s) => {
      if (!s.session) return s
      return {
        session: {
          ...s.session,
          speeches: [...s.session.speeches, speech],
        },
      }
    })
    return id
  },

  appendSpeechToken: (speechId, token) =>
    set((s) => {
      if (!s.session) return s
      return {
        session: {
          ...s.session,
          speeches: s.session.speeches.map((sp) =>
            sp.id === speechId ? { ...sp, content: sp.content + token } : sp,
          ),
        },
      }
    }),

  finishSpeech: (speechId, sources) =>
    set((s) => {
      if (!s.session) return s
      return {
        session: {
          ...s.session,
          speeches: s.session.speeches.map((sp) =>
            sp.id === speechId ? { ...sp, loading: false, sources } : sp,
          ),
        },
      }
    }),

  failSpeech: (speechId, error) =>
    set((s) => {
      if (!s.session) return s
      return {
        session: {
          ...s.session,
          speeches: s.session.speeches.map((sp) =>
            sp.id === speechId
              ? { ...sp, loading: false, error, content: sp.content || `⚠ ${error}` }
              : sp,
          ),
        },
      }
    }),

  addIntervention: (content, targetPersonaId, afterRound) => {
    const iv: RoundtableIntervention = {
      id: `iv-${Date.now()}`,
      content,
      targetPersonaId,
      afterRound,
      timestamp: Date.now(),
    }
    set((s) => {
      if (!s.session) return s
      return {
        session: {
          ...s.session,
          interventions: [...s.session.interventions, iv],
          // 保持 'intervening' 状态，让插话面板继续显示，用户可追加多条插话后再手动进入下一轮
        },
      }
    })
  },

  startSummary: () =>
    set((s) => {
      if (!s.session) return s
      return {
        session: {
          ...s.session,
          status: 'summarizing',
          summary: {
            content: '',
            moderatorType: s.session.moderatorType,
            loading: true,
            timestamp: Date.now(),
          },
        },
      }
    }),

  appendSummaryToken: (token) =>
    set((s) => {
      if (!s.session?.summary) return s
      return {
        session: {
          ...s.session,
          summary: {
            ...s.session.summary,
            content: s.session.summary.content + token,
          },
        },
      }
    }),

  finishSummary: () =>
    set((s) => {
      if (!s.session?.summary) return s
      return {
        session: {
          ...s.session,
          status: 'completed',
          summary: { ...s.session.summary, loading: false },
        },
      }
    }),

  setStatus: (status) =>
    set((s) => {
      if (!s.session) return s
      return { session: { ...s.session, status } }
    }),

  bumpCurrentRound: () =>
    set((s) => {
      if (!s.session) return s
      return {
        session: {
          ...s.session,
          currentRound: s.session.currentRound + 1,
        },
      }
    }),
}))
