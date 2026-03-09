import { create } from 'zustand'
import { v4 as uuidv4 } from 'uuid'
import { ChatNode, TokenUsage, Session, ModelConfig, FileAttachment } from '../lib/types'
import { ipc } from '../lib/ipc'
import { useConfigStore } from './configStore'

/** 查看阶段: 'live' = 实时, number = 某一轮, 'verdict' = 裁决 */
export type ViewingStage = 'live' | number | 'verdict'

interface ChatState {
  // 当前会话
  sessionId: string | null
  session: Session | null
  
  // 对话节点
  nodes: Map<string, ChatNode>
  
  // 生成状态
  isGenerating: boolean
  currentRound: number
  totalRounds: number
  
  // 流式内容缓冲（当前正在流式的内容）
  streamBuffers: Map<string, string>
  
  // 轮次快照：每轮完成后保存的内容快照
  roundSnapshots: Map<number, Map<string, string>>
  
  // 已完成的轮次列表
  completedRounds: number[]
  
  // 当前查看的阶段
  viewingStage: ViewingStage
  
  // Token用量
  tokenUsage: Map<string, TokenUsage>
  
  // 模型状态
  modelStatuses: Map<string, 'idle' | 'generating' | 'completed' | 'error'>
  
  // 模型错误信息
  modelErrors: Map<string, string>
  
  // 裁决内容
  verdictContent: string
  verdictUsage: TokenUsage | null
  isVerdictGenerating: boolean
  
  // 全局错误
  error: string | null
  
  // Actions
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
  
  // 轮次快照
  saveRoundSnapshot: (round: number) => void
  setViewingStage: (stage: ViewingStage) => void
  
  // 裁决相关
  appendVerdictChunk: (content: string) => void
  finalizeVerdict: (usage?: TokenUsage) => void
  setVerdictContent: (content: string) => void
  
  // 输入框状态
  inputValue: string
  setInputValue: (value: string) => void
  
  // 加载会话历史
  loadSessionHistory: (sessionId: string) => Promise<void>
  
  // 启用的模型
  enabledModels: ModelConfig[]
  setEnabledModels: (models: ModelConfig[]) => void
  
  // 辅助：获取当前查看阶段的内容
  getDisplayContent: (modelId: string) => string
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessionId: null,
  session: null,
  nodes: new Map(),
  isGenerating: false,
  currentRound: 0,
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

  setSession: (session) => {
    set({ session, sessionId: session?.id ?? null })
  },

  sendMessage: async (content?: string, files?: FileAttachment[]) => {
    const state = get()
    const messageContent = content ?? state.inputValue.trim()
    
    if (!messageContent || state.isGenerating) return
    
    const configState = useConfigStore.getState()
    const currentModels = configState.getEnabledModels()
    
    if (currentModels.length === 0) {
      set({ error: '请先在设置中启用至少一个模型 (Ctrl+, 打开设置)' })
      return
    }
    
    set({ enabledModels: currentModels })

    // 如果没有会话，自动创建一个
    let currentSessionId = state.sessionId
    if (!currentSessionId) {
      try {
        const result = await ipc.newSession?.()
        if (result?.success && result.data) {
          currentSessionId = result.data.id
          set({ session: result.data, sessionId: currentSessionId })
        }
      } catch (e) {
        console.warn('自动创建会话失败:', e)
      }
    }
    const sessionId = currentSessionId || 'temp'

    // 创建用户消息节点
    const userNode: ChatNode = {
      id: uuidv4(),
      sessionId,
      parentId: null,
      role: 'user',
      content: messageContent,
      createdAt: Date.now(),
    }

    // 初始化模型状态和缓冲区
    const newStatuses = new Map<string, 'idle' | 'generating' | 'completed' | 'error'>()
    const newBuffers = new Map<string, string>()
    
    currentModels.forEach(model => {
      newStatuses.set(model.id, 'generating')
      newBuffers.set(model.id, '')
    })

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
    })

    try {
      const apiKeys: Record<string, string> = {}
      configState.providers.forEach(p => {
        if (p.apiKey) {
          apiKeys[p.provider] = p.apiKey
        }
      })
      
      await ipc.startDebate?.({
        sessionId: sessionId,
        query: messageContent,
        models: currentModels,
        rounds: state.totalRounds,
        files: files && files.length > 0 ? files : undefined,
        apiKeys,
        reportDetailLevel: configState.reportDetailLevel,
      })
    } catch (error) {
      console.error('发送消息失败:', error)
      set({ isGenerating: false })
    }
  },

  stopGeneration: () => {
    const state = get()
    if (!state.isGenerating) return
    
    ipc.stopGeneration?.(state.sessionId || 'temp')
    
    const newStatuses = new Map(state.modelStatuses)
    newStatuses.forEach((status, modelId) => {
      if (status === 'generating') {
        newStatuses.set(modelId, 'completed')
      }
    })
    
    set({ isGenerating: false, modelStatuses: newStatuses })
  },

  appendStreamChunk: (modelId, chunk) => {
    // 裁决内容特殊处理
    if (modelId === '__verdict__') {
      set(s => ({
        verdictContent: s.verdictContent + chunk,
        isGenerating: true,
        isVerdictGenerating: true,
      }))
      return
    }
    set(s => {
      const newBuffers = new Map(s.streamBuffers)
      const current = newBuffers.get(modelId) || ''
      newBuffers.set(modelId, current + chunk)
      return {
        streamBuffers: newBuffers,
        isGenerating: true,
      }
    })
  },

  finalizeStream: (modelId, usage) => {
    set(state => {
      const newStatuses = new Map(state.modelStatuses)
      newStatuses.set(modelId, 'completed')
      
      const newUsage = new Map(state.tokenUsage)
      if (usage) {
        newUsage.set(modelId, usage)
      }
      
      return {
        modelStatuses: newStatuses,
        tokenUsage: newUsage,
        // 不在这里设置 isGenerating=false，由 debate-event 控制轮次切换
      }
    })
  },

  // 保存当前轮次的快照
  saveRoundSnapshot: (round: number) => {
    const state = get()
    
    // 防止重复保存同一轮次
    if (state.completedRounds.includes(round)) {
      return
    }

    const snapshot = new Map(state.streamBuffers)
    const newSnapshots = new Map(state.roundSnapshots)
    newSnapshots.set(round, snapshot)
    
    const newCompleted = [...state.completedRounds, round]
    
    // 清空 streamBuffers 准备下一轮
    const clearedBuffers = new Map<string, string>()
    state.enabledModels.forEach(m => clearedBuffers.set(m.id, ''))
    
    // 重置模型状态为 generating（下一轮）
    const newStatuses = new Map<string, 'idle' | 'generating' | 'completed' | 'error'>()
    state.enabledModels.forEach(m => newStatuses.set(m.id, 'generating'))

    set({
      roundSnapshots: newSnapshots,
      completedRounds: newCompleted,
      streamBuffers: clearedBuffers,
      modelStatuses: newStatuses,
      currentRound: round + 1,
    })
  },

  setViewingStage: (stage) => {
    set({ viewingStage: stage })
  },

  resetSession: () => {
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
      inputValue: '',
      verdictContent: '',
      verdictUsage: null,
      isVerdictGenerating: false,
      error: null,
    })
  },

  createNewSession: async () => {
    try {
      // 不停止旧辩论，让它在后台继续跑（数据会持久化到DB）
      // 只清除前端状态
      get().resetSession()
      const result = await ipc.newSession?.()
      if (result?.success && result.data) {
        set({ session: result.data, sessionId: result.data.id })
      }
    } catch (error) {
      console.error('创建会话失败:', error)
    }
  },

  setRounds: (rounds) => {
    set({ totalRounds: Math.max(1, Math.min(5, rounds)) })
  },

  setInputValue: (value) => {
    set({ inputValue: value })
  },

  setEnabledModels: (models) => {
    set({ enabledModels: models })
  },

  setModelError: (modelId, error) => {
    set(state => {
      const newErrors = new Map(state.modelErrors)
      newErrors.set(modelId, error)
      
      const newStatuses = new Map(state.modelStatuses)
      newStatuses.set(modelId, 'error')
      
      return { modelErrors: newErrors, modelStatuses: newStatuses }
    })
  },

  setError: (error) => {
    set({ error, isGenerating: false })
  },

  appendVerdictChunk: (content) => {
    set(state => ({
      verdictContent: state.verdictContent + content,
      isGenerating: true,
      isVerdictGenerating: true,
    }))
  },

  finalizeVerdict: (usage) => {
    set({
      verdictUsage: usage || null,
      isVerdictGenerating: false,
      isGenerating: false,
    })
  },

  setVerdictContent: (content) => {
    set({ verdictContent: content })
  },

  loadSessionHistory: async (sessionId) => {
    try {
      const result = await ipc.loadSession?.(sessionId)
      if (result?.success && result.data) {
        const { session, nodes } = result.data
        const nodeMap = new Map<string, ChatNode>()
        let lastVerdictContent = ''
        let lastVerdictUsage: TokenUsage | null = null
        
        // 按轮次分组助手回答，重建轮次快照
        const roundSnapshotsMap = new Map<number, Map<string, string>>()
        const tokenUsageMap = new Map<string, TokenUsage>()
        const completedRoundSet = new Set<number>()
        let maxRound = 0
        
        nodes.forEach((node: ChatNode) => {
          if (node.role === 'verdict') {
            // 裁决内容
            lastVerdictContent = node.content
            if (node.tokenInput || node.tokenOutput) {
              lastVerdictUsage = {
                inputTokens: node.tokenInput || 0,
                outputTokens: node.tokenOutput || 0,
              }
            }
          } else if (node.role === 'assistant' && node.round && node.modelId) {
            // 助手回答 → 按轮次分组为快照
            const round = node.round
            if (!roundSnapshotsMap.has(round)) {
              roundSnapshotsMap.set(round, new Map())
            }
            roundSnapshotsMap.get(round)!.set(node.modelId, node.content)
            completedRoundSet.add(round)
            if (round > maxRound) maxRound = round
            
            // Token 用量
            if (node.modelId && (node.tokenInput || node.tokenOutput)) {
              tokenUsageMap.set(node.modelId, {
                inputTokens: node.tokenInput || 0,
                outputTokens: node.tokenOutput || 0,
              })
            }
          } else {
            // 用户消息等
            nodeMap.set(node.id, node)
          }
        })

        const completedRounds = Array.from(completedRoundSet).sort((a, b) => a - b)
        
        // 默认显示：有裁决就显示裁决，否则显示最后一轮
        const defaultStage: ViewingStage = lastVerdictContent 
          ? 'verdict' 
          : (completedRounds.length > 0 ? completedRounds[completedRounds.length - 1] : 'live')
        
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
      }
    } catch (error) {
      console.error('加载会话历史失败:', error)
    }
  },

  // 辅助方法：根据当前查看阶段返回对应内容
  getDisplayContent: (modelId: string) => {
    const state = get()
    
    switch (state.viewingStage) {
      case 'live':
        return state.streamBuffers.get(modelId) || ''
      case 'verdict':
        return '' // 裁决阶段不显示模型列内容
      default:
        // 数字 = 某一轮
        const roundSnapshot = state.roundSnapshots.get(state.viewingStage as number)
        return roundSnapshot?.get(modelId) || ''
    }
  },
}))
