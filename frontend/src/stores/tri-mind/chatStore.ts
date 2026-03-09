'use client'

import { create } from 'zustand'
import { v4 as uuidv4 } from 'uuid'
import type { ChatNode, TokenUsage, Session, ModelConfig, FileAttachment } from '@/lib/tri-mind/types'
import { triMindApi } from '@/lib/tri-mind/api'
import { useConfigStore } from './configStore'

export type ViewingStage = 'live' | number | 'verdict'

interface ChatState {
  sessionId: string | null
  session: Session | null
  nodes: Map<string, ChatNode>
  isGenerating: boolean
  currentRound: number
  totalRounds: number
  streamBuffers: Map<string, string>
  roundSnapshots: Map<number, Map<string, string>>
  completedRounds: number[]
  viewingStage: ViewingStage
  tokenUsage: Map<string, TokenUsage>
  modelStatuses: Map<string, 'idle' | 'generating' | 'completed' | 'error'>
  modelErrors: Map<string, string>
  verdictContent: string
  verdictUsage: TokenUsage | null
  isVerdictGenerating: boolean
  error: string | null
  inputValue: string
  enabledModels: ModelConfig[]
  abortControllerRef: AbortController | null

  setSession: (session: Session | null) => void
  sendMessage: (content?: string, files?: FileAttachment[]) => Promise<void>
  stopGeneration: () => void
  appendStreamChunk: (modelId: string, chunk: string) => void
  finalizeStream: (modelId: string, usage?: TokenUsage) => void
  resetSession: () => void
  createNewSession: () => Promise<void>
  setRounds: (rounds: number) => void
  setModelError: (modelId: string, error: string) => void
  setError: (error: string | null) => void
  saveRoundSnapshot: (round: number) => void
  setViewingStage: (stage: ViewingStage) => void
  appendVerdictChunk: (content: string) => void
  finalizeVerdict: (usage?: TokenUsage) => void
  setVerdictContent: (content: string) => void
  setInputValue: (value: string) => void
  loadSessionHistory: (sessionId: string) => Promise<void>
  setEnabledModels: (models: ModelConfig[]) => void
  getDisplayContent: (modelId: string) => string
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessionId: null,
  session: null,
  nodes: new Map(),
  isGenerating: false,
  currentRound: 1,
  totalRounds: 2,
  streamBuffers: new Map(),
  roundSnapshots: new Map(),
  completedRounds: [],
  viewingStage: 'live',
  tokenUsage: new Map(),
  modelStatuses: new Map(),
  modelErrors: new Map(),
  verdictContent: '',
  verdictUsage: null,
  isVerdictGenerating: false,
  error: null,
  inputValue: '',
  enabledModels: [],
  abortControllerRef: null,

  setSession: (session) => set({ session, sessionId: session?.id ?? null }),

  sendMessage: async (content?, files?) => {
    const state = get()
    const messageContent = content ?? state.inputValue.trim()
    if (!messageContent || state.isGenerating) return

    const configState = useConfigStore.getState()
    const currentModels = configState.getEnabledModels()
    if (currentModels.length === 0) {
      set({ error: '请先在设置中启用至少一个模型 (Ctrl+, 打开设置)' })
      return
    }

    let currentSessionId = state.sessionId
    if (!currentSessionId) {
      const result = await triMindApi.newSession()
      if (result?.success && result.data) {
        currentSessionId = result.data.id
        set({ session: result.data, sessionId: currentSessionId })
      }
    }
    const sessionId = currentSessionId || 'temp'

    const userNode: ChatNode = {
      id: uuidv4(),
      sessionId,
      parentId: null,
      role: 'user',
      content: messageContent,
      createdAt: Date.now(),
    }

    const newStatuses = new Map<string, 'idle' | 'generating' | 'completed' | 'error'>()
    const newBuffers = new Map<string, string>()
    currentModels.forEach((m) => {
      newStatuses.set(m.id, 'generating')
      newBuffers.set(m.id, '')
    })

    const abortController = new AbortController()
    set({
      isGenerating: true,
      currentRound: 1,
      inputValue: '',
      modelStatuses: newStatuses,
      streamBuffers: newBuffers,
      roundSnapshots: new Map(),
      completedRounds: [],
      viewingStage: 'live',
      verdictContent: '',
      verdictUsage: null,
      isVerdictGenerating: false,
      error: null,
      nodes: new Map(state.nodes).set(userNode.id, userNode),
      enabledModels: currentModels,
      abortControllerRef: abortController,
    })

    const apiKeys: Record<string, string> = {}
    configState.providers.forEach((p) => {
      if (p.apiKey) apiKeys[p.provider] = p.apiKey
    })

    try {
      await triMindApi.startDebate(
        {
          sessionId,
          query: messageContent,
          models: currentModels,
          rounds: state.totalRounds,
          files: files && files.length > 0 ? files : undefined,
          apiKeys,
          reportDetailLevel: configState.reportDetailLevel,
        },
        (chunk) => {
          const store = useChatStore.getState()
          if (chunk.modelId === '__verdict__') {
            if (!chunk.done) {
              store.appendVerdictChunk(chunk.content)
            } else {
              store.finalizeVerdict(chunk.usage)
            }
          } else if (chunk.modelId === '__error__') {
            store.setError(chunk.error || '未知错误')
          } else {
            if (!chunk.done) {
              store.appendStreamChunk(chunk.modelId, chunk.content)
            } else {
              if (chunk.error) store.setModelError(chunk.modelId, chunk.error)
              else store.finalizeStream(chunk.modelId, chunk.usage)
            }
          }
        },
        (event) => {
          const store = useChatStore.getState()
          if (event.type === 'round-complete' && event.round) {
            store.saveRoundSnapshot(event.round)
          } else if (event.type === 'debate-complete') {
            if (!store.isVerdictGenerating && !store.verdictContent) {
              set({ isGenerating: false })
            }
          } else if (event.type === 'error') {
            store.setError(event.error || '未知错误')
          }
        },
        abortController.signal
      )
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      console.error('发送消息失败:', err)
      set({ isGenerating: false })
    } finally {
      set({ abortControllerRef: null })
    }
  },

  stopGeneration: () => {
    const state = get()
    if (!state.isGenerating) return
    state.abortControllerRef?.abort()
    const newStatuses = new Map(state.modelStatuses)
    newStatuses.forEach((_, modelId) => newStatuses.set(modelId, 'completed'))
    set({ isGenerating: false, modelStatuses: newStatuses })
  },

  appendStreamChunk: (modelId, chunk) => {
    set((s) => {
      const newBuffers = new Map(s.streamBuffers)
      newBuffers.set(modelId, (newBuffers.get(modelId) || '') + chunk)
      return { streamBuffers: newBuffers, isGenerating: true }
    })
  },

  finalizeStream: (modelId, usage) => {
    set((s) => {
      const newStatuses = new Map(s.modelStatuses)
      newStatuses.set(modelId, 'completed')
      const newUsage = new Map(s.tokenUsage)
      if (usage) newUsage.set(modelId, usage)
      return { modelStatuses: newStatuses, tokenUsage: newUsage }
    })
  },

  saveRoundSnapshot: (round) => {
    const state = get()
    if (state.completedRounds.includes(round)) return
    const snapshot = new Map(state.streamBuffers)
    const newSnapshots = new Map(state.roundSnapshots)
    newSnapshots.set(round, snapshot)
    const clearedBuffers = new Map<string, string>()
    state.enabledModels.forEach((m) => clearedBuffers.set(m.id, ''))
    const newStatuses = new Map<string, 'idle' | 'generating' | 'completed' | 'error'>()
    state.enabledModels.forEach((m) => newStatuses.set(m.id, 'generating'))
    set({
      roundSnapshots: newSnapshots,
      completedRounds: [...state.completedRounds, round].sort((a, b) => a - b),
      streamBuffers: clearedBuffers,
      modelStatuses: newStatuses,
      currentRound: round + 1,
    })
  },

  setViewingStage: (stage) => set({ viewingStage: stage }),
  setModelError: (modelId, error) => {
    set((s) => {
      const newErrors = new Map(s.modelErrors)
      newErrors.set(modelId, error)
      const newStatuses = new Map(s.modelStatuses)
      newStatuses.set(modelId, 'error')
      return { modelErrors: newErrors, modelStatuses: newStatuses }
    })
  },
  setError: (error) => set({ error, isGenerating: false }),
  appendVerdictChunk: (content) =>
    set((s) => ({
      verdictContent: s.verdictContent + content,
      isGenerating: true,
      isVerdictGenerating: true,
    })),
  finalizeVerdict: (usage) =>
    set({ verdictUsage: usage || null, isVerdictGenerating: false, isGenerating: false }),
  setVerdictContent: (content) => set({ verdictContent: content }),
  setInputValue: (value) => set({ inputValue: value }),
  setRounds: (rounds) => set({ totalRounds: Math.max(1, Math.min(5, rounds)) }),
  setEnabledModels: (models) => set({ enabledModels: models }),

  resetSession: () =>
    set({
      sessionId: null,
      session: null,
      nodes: new Map(),
      streamBuffers: new Map(),
      roundSnapshots: new Map(),
      completedRounds: [],
      viewingStage: 'live',
      tokenUsage: new Map(),
      modelStatuses: new Map(),
      modelErrors: new Map(),
      currentRound: 0,
      isGenerating: false,
      verdictContent: '',
      verdictUsage: null,
      isVerdictGenerating: false,
      error: null,
    }),

  createNewSession: async () => {
    get().resetSession()
    const result = await triMindApi.newSession()
    if (result?.success && result.data) {
      set({ session: result.data, sessionId: result.data.id })
    }
  },

  loadSessionHistory: async (sessionId) => {
    const result = await triMindApi.loadSession(sessionId)
    if (!result?.success || !result.data) return
    const { session, nodes } = result.data
    const nodeMap = new Map<string, ChatNode>()
    let lastVerdictContent = ''
    let lastVerdictUsage: TokenUsage | null = null
    const roundSnapshotsMap = new Map<number, Map<string, string>>()
    const tokenUsageMap = new Map<string, TokenUsage>()
    const completedRoundSet = new Set<number>()
    let maxRound = 0

    nodes.forEach((node) => {
      if (node.role === 'verdict') {
        lastVerdictContent = node.content
        if (node.tokenInput || node.tokenOutput) {
          lastVerdictUsage = {
            inputTokens: node.tokenInput || 0,
            outputTokens: node.tokenOutput || 0,
          }
        }
      } else if (node.role === 'assistant' && node.round && node.modelId) {
        const round = node.round
        if (!roundSnapshotsMap.has(round)) roundSnapshotsMap.set(round, new Map())
        roundSnapshotsMap.get(round)!.set(node.modelId, node.content)
        completedRoundSet.add(round)
        if (round > maxRound) maxRound = round
        if (node.tokenInput || node.tokenOutput) {
          tokenUsageMap.set(node.modelId, {
            inputTokens: node.tokenInput || 0,
            outputTokens: node.tokenOutput || 0,
          })
        }
      } else {
        nodeMap.set(node.id, node)
      }
    })

    const completedRounds = Array.from(completedRoundSet).sort((a, b) => a - b)
    const defaultStage: ViewingStage = lastVerdictContent
      ? 'verdict'
      : completedRounds.length > 0
        ? completedRounds[completedRounds.length - 1]
        : 'live'

    set({
      session,
      sessionId: session.id,
      nodes: nodeMap,
      verdictContent: lastVerdictContent,
      verdictUsage: lastVerdictUsage,
      roundSnapshots: roundSnapshotsMap,
      completedRounds,
      tokenUsage: tokenUsageMap,
      viewingStage: defaultStage,
      currentRound: maxRound,
      totalRounds: Math.max(2, maxRound),
      isGenerating: false,
    })
  },

  getDisplayContent: (modelId) => {
    const s = get()
    if (s.viewingStage === 'live') return s.streamBuffers.get(modelId) || ''
    if (s.viewingStage === 'verdict') return ''
    const snap = s.roundSnapshots.get(s.viewingStage as number)
    return snap?.get(modelId) || ''
  },
}))
