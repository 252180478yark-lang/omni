import { useCallback } from 'react'
import { useChatStore } from '../stores/chatStore'
import { useConfigStore } from '../stores/configStore'
import { FileAttachment } from '../lib/types'

/**
 * 辩论流程控制 Hook
 * 
 * 封装辩论相关的业务逻辑：
 * - 发送消息并启动辩论
 * - 停止生成
 * - 获取辩论状态
 * - 管理文件附件
 * - Token 用量统计
 * 
 * 将 chatStore 和 configStore 的操作抽象为简洁的接口。
 */
export function useDebate() {
  const chatStore = useChatStore()
  const configStore = useConfigStore()

  /**
   * 获取当前启用的模型列表
   */
  const getEnabledModels = useCallback(() => {
    return configStore.getEnabledModels()
  }, [configStore])

  /**
   * 检查是否可以发送消息
   */
  const canSend = useCallback(() => {
    const hasInput = chatStore.inputValue.trim().length > 0
    const hasModels = configStore.getEnabledModels().length > 0
    const notGenerating = !chatStore.isGenerating
    return hasInput && hasModels && notGenerating
  }, [chatStore.inputValue, chatStore.isGenerating, configStore])

  /**
   * 发送消息并启动辩论
   * 
   * @param content 消息内容，不传则使用 inputValue
   * @param _files 附件文件（预留，当前通过 DebateParams 传递）
   * @param _intervention 上帝视角干预（预留，P1 功能）
   */
  const startDebate = useCallback(async (
    content?: string,
    _files?: FileAttachment[],
    _intervention?: string
  ) => {
    // 如果提供了 content 则先设置 inputValue
    if (content !== undefined) {
      chatStore.setInputValue(content)
    }
    
    // sendMessage 会自动从 inputValue 读取内容
    await chatStore.sendMessage(content)
  }, [chatStore])

  /**
   * 停止当前辩论
   */
  const stopDebate = useCallback(() => {
    chatStore.stopGeneration()
  }, [chatStore])

  /**
   * 重置当前会话
   */
  const resetDebate = useCallback(() => {
    chatStore.resetSession()
  }, [chatStore])

  /**
   * 创建新会话
   */
  const newSession = useCallback(async () => {
    await chatStore.createNewSession()
  }, [chatStore])

  /**
   * 设置辩论轮数
   */
  const setRounds = useCallback((rounds: number) => {
    chatStore.setRounds(rounds)
  }, [chatStore])

  /**
   * 获取所有模型的 Token 总用量
   */
  const getTotalTokenUsage = useCallback(() => {
    let totalInput = 0
    let totalOutput = 0
    
    chatStore.tokenUsage.forEach((usage) => {
      totalInput += usage.inputTokens
      totalOutput += usage.outputTokens
    })

    // 加上裁决的 Token 用量
    if (chatStore.verdictUsage) {
      totalInput += chatStore.verdictUsage.inputTokens
      totalOutput += chatStore.verdictUsage.outputTokens
    }

    return { totalInput, totalOutput, total: totalInput + totalOutput }
  }, [chatStore.tokenUsage, chatStore.verdictUsage])

  /**
   * 获取辩论进度描述
   */
  const getProgressText = useCallback(() => {
    if (!chatStore.isGenerating) return null
    
    if (chatStore.isVerdictGenerating) {
      return '正在生成裁决...'
    }
    
    return `第 ${chatStore.currentRound}/${chatStore.totalRounds} 轮辩论中...`
  }, [chatStore.isGenerating, chatStore.isVerdictGenerating, chatStore.currentRound, chatStore.totalRounds])

  /**
   * 检查辩论是否已完成（有裁决内容）
   */
  const isDebateComplete = useCallback(() => {
    return chatStore.verdictContent.length > 0 && !chatStore.isGenerating
  }, [chatStore.verdictContent, chatStore.isGenerating])

  return {
    // 状态
    isGenerating: chatStore.isGenerating,
    isVerdictGenerating: chatStore.isVerdictGenerating,
    currentRound: chatStore.currentRound,
    totalRounds: chatStore.totalRounds,
    inputValue: chatStore.inputValue,
    setInputValue: chatStore.setInputValue,
    verdictContent: chatStore.verdictContent,
    error: chatStore.error,
    enabledModels: chatStore.enabledModels,

    // 操作
    startDebate,
    stopDebate,
    resetDebate,
    newSession,
    setRounds,
    canSend,
    getEnabledModels,

    // 统计
    getTotalTokenUsage,
    getProgressText,
    isDebateComplete,
  }
}
