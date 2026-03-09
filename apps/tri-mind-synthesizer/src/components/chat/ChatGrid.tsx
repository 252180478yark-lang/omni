import { useEffect } from 'react'
import { ChatColumn } from './ChatColumn'
import { VerdictCard } from './VerdictCard'
import { useChatStore, ViewingStage } from '../../stores/chatStore'
import { useConfigStore } from '../../stores/configStore'
import { cn } from '../../lib/utils'
import { Bot, AlertCircle, Radio, Gavel } from 'lucide-react'

export function ChatGrid() {
  const { 
    enabledModels, 
    setEnabledModels, 
    streamBuffers, 
    modelStatuses,
    error,
    setError,
    verdictContent,
    isVerdictGenerating,
    isGenerating,
    completedRounds,
    viewingStage,
    setViewingStage,
    roundSnapshots,
    currentRound,
    totalRounds,
  } = useChatStore()
  const { providers, getEnabledModels } = useConfigStore()

  // 当配置变化时更新启用的模型
  useEffect(() => {
    const models = getEnabledModels()
    setEnabledModels(models)
  }, [providers, getEnabledModels, setEnabledModels])

  // 根据模型数量决定网格列数
  const getGridCols = () => {
    const count = enabledModels.length
    if (count <= 1) return 'grid-cols-1'
    if (count === 2) return 'grid-cols-2'
    if (count === 3) return 'grid-cols-3'
    return 'grid-cols-4'
  }

  // 获取模型在当前查看阶段的内容
  const getModelContent = (modelId: string): string => {
    if (viewingStage === 'live') {
      return streamBuffers.get(modelId) || ''
    }
    if (viewingStage === 'verdict') {
      return '' // 裁决视图不显示模型列
    }
    // 查看某一轮
    const snapshot = roundSnapshots.get(viewingStage as number)
    return snapshot?.get(modelId) || ''
  }

  // 获取模型在当前查看阶段的状态
  const getModelStatus = (modelId: string): 'idle' | 'generating' | 'completed' | 'error' => {
    if (viewingStage === 'live') {
      return modelStatuses.get(modelId) || 'idle'
    }
    // 查看历史轮次，状态固定为 completed
    return 'completed'
  }

  // 是否应显示裁决
  const showVerdict = viewingStage === 'verdict' || 
    (viewingStage === 'live' && (verdictContent || isVerdictGenerating))

  // 是否应显示模型列
  const showColumns = viewingStage !== 'verdict'

  // 是否有可切换的阶段（辩论已开始）
  const hasStages = completedRounds.length > 0 || isGenerating || verdictContent

  // 空状态
  if (enabledModels.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-gray-500">
        <Bot className="w-16 h-16 mb-4 opacity-50" />
        <h3 className="text-lg font-medium mb-2">欢迎使用 Tri-Mind Synthesizer</h3>
        <p className="text-sm text-center max-w-md">
          请先在设置中配置并启用至少一个 AI 模型，
          <br />
          然后开始您的多模型辩论之旅。
        </p>
        <p className="text-xs mt-4">
          按 <kbd className="px-1.5 py-0.5 bg-gray-200 rounded text-gray-900">Ctrl+,</kbd> 打开设置
        </p>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* 错误提示 */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-2 bg-destructive/10 text-destructive border-b border-destructive/20 shrink-0">
          <AlertCircle className="w-4 h-4" />
          <span className="text-sm">{error}</span>
          <button 
            onClick={() => setError(null)}
            className="ml-auto text-xs underline hover:no-underline"
          >
            关闭
          </button>
        </div>
      )}

      {/* 轮次切换标签栏 */}
      {hasStages && (
        <StageTabs
          completedRounds={completedRounds}
          currentRound={currentRound}
          totalRounds={totalRounds}
          viewingStage={viewingStage}
          onStageChange={setViewingStage}
          isGenerating={isGenerating}
          hasVerdict={!!verdictContent || isVerdictGenerating}
        />
      )}
      
      {/* 聊天网格 */}
      {showColumns && (
        <div className={cn('flex-1 grid gap-0.5 bg-gray-200/30 min-h-0 overflow-hidden', getGridCols())}>
          {enabledModels.map((model) => (
            <ChatColumn
              key={model.id}
              model={model}
              content={getModelContent(model.id)}
              status={getModelStatus(model.id)}
            />
          ))}
        </div>
      )}
      
      {/* 裁决卡片 */}
      {showVerdict && (
        <div className={cn(
          'overflow-y-auto chat-scroll',
          showColumns ? 'shrink-0 max-h-[45%] border-t border-gray-200/50' : 'flex-1'
        )}>
          <VerdictCard />
        </div>
      )}
    </div>
  )
}

// ==================== 轮次切换标签组件 ====================

interface StageTabsProps {
  completedRounds: number[]
  currentRound: number
  totalRounds: number
  viewingStage: ViewingStage
  onStageChange: (stage: ViewingStage) => void
  isGenerating: boolean
  hasVerdict: boolean
}

function StageTabs({
  completedRounds,
  currentRound,
  totalRounds,
  viewingStage,
  onStageChange,
  isGenerating,
  hasVerdict,
}: StageTabsProps) {
  return (
    <div className="flex items-center gap-1 px-3 py-2 border-b border-gray-200/50 bg-gray-100/80 shrink-0 overflow-x-auto rounded-t-xl">
      {/* 实时标签 */}
      <button
        onClick={() => onStageChange('live')}
        className={cn(
          'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap',
          viewingStage === 'live'
            ? 'bg-white shadow-sm text-gray-900'
            : 'hover:bg-gray-200/60 text-gray-600'
        )}
      >
        {isGenerating && <Radio className="w-3 h-3 animate-pulse" />}
        {isGenerating ? `第 ${currentRound}/${totalRounds} 轮进行中` : '实时'}
      </button>

      {/* 已完成轮次的标签 */}
      {completedRounds.map((round) => (
        <button
          key={round}
          onClick={() => onStageChange(round)}
          className={cn(
            'px-3 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap',
            viewingStage === round
              ? 'bg-gradient-to-r from-blue-600 to-purple-500 text-white'
              : 'hover:bg-gray-200/60 text-gray-600'
          )}
        >
          第 {round} 轮
        </button>
      ))}

      {/* 裁决标签 */}
      {hasVerdict && (
        <button
          onClick={() => onStageChange('verdict')}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap',
            viewingStage === 'verdict'
              ? 'bg-amber-500 text-white'
              : 'hover:bg-gray-200/60 text-gray-600'
          )}
        >
          <Gavel className="w-3 h-3" />
          最终裁决
        </button>
      )}
    </div>
  )
}
