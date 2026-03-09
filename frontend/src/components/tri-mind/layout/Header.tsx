import { Settings, Download, RotateCcw } from 'lucide-react'
import { useUIStore } from '@/stores/tri-mind/uiStore'
import { useChatStore } from '@/stores/tri-mind/chatStore'
import { useConfigStore } from '@/stores/tri-mind/configStore'
import { cn, formatTokenCount } from '@/lib/utils'
import { estimateCost, formatCost } from '@/lib/tri-mind/cost'
import { useMemo } from 'react'

export function Header() {
  const { setSettingsOpen } = useUIStore()
  const { providers } = useConfigStore()
  const { 
    session, 
    currentRound, 
    totalRounds, 
    isGenerating, 
    tokenUsage,
    enabledModels,
    verdictUsage,
    nodes,
    resetSession 
  } = useChatStore()

  // 构建 instanceId -> modelId 映射
  const modelMap = useMemo(() => {
    const map = new Map<string, string>()
    providers.forEach(p => {
      p.models.forEach(m => {
        map.set(m.id, m.modelId)
      })
    })
    return map
  }, [providers])

  // 计算总Token用量和费用
  const { totalTokens, totalCost } = useMemo(() => {
    let input = 0
    let output = 0
    let cost = 0

    // 1. 各模型回答的用量和费用
    tokenUsage.forEach((usage, instanceId) => {
      input += usage.inputTokens
      output += usage.outputTokens
      
      const modelId = modelMap.get(instanceId)
      if (modelId) {
        cost += estimateCost(modelId, usage.inputTokens, usage.outputTokens)
      }
    })

    // 2. 裁决的用量和费用
    if (verdictUsage) {
      input += verdictUsage.inputTokens
      output += verdictUsage.outputTokens

      // 尝试找到裁决使用的模型
      let judgeModelId = ''
      
      // 方式A: 从 verdict 节点找 (历史记录)
      const verdictNode = Array.from(nodes.values()).find(n => n.role === 'verdict')
      if (verdictNode?.modelId) {
        judgeModelId = modelMap.get(verdictNode.modelId) || ''
      }
      
      // 方式B: 实时生成中，猜测 contextWindow 最大的模型 (仅作备选，通常 verdictNode 应该已存在或即将存在)
      if (!judgeModelId && enabledModels.length > 0) {
        const judge = enabledModels.reduce((prev, curr) => 
          curr.contextWindow > prev.contextWindow ? curr : prev
        )
        judgeModelId = judge.modelId
      }

      if (judgeModelId) {
        cost += estimateCost(judgeModelId, verdictUsage.inputTokens, verdictUsage.outputTokens)
      }
    }

    return {
      totalTokens: { input, output },
      totalCost: cost
    }
  }, [tokenUsage, verdictUsage, modelMap, nodes, enabledModels])

  const handleExport = () => {
    const event = new CustomEvent('app:export-debate')
    window.dispatchEvent(event)
  }

  return (
    <header className="h-14 border-b border-gray-200/50 glass flex items-center justify-between px-4">
      {/* 左侧：会话信息 */}
      <div className="flex items-center gap-4">
        <h2 className="text-sm font-medium text-gray-900">
          {session?.title || '新会话'}
        </h2>
        
        {/* 辩论状态 */}
        {isGenerating && (
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse mr-1" />
            <span className="text-xs text-gray-500">
              第 {currentRound}/{totalRounds} 轮
            </span>
          </div>
        )}
        
        {/* 模型数量 */}
        {enabledModels.length > 0 && (
          <span className="text-xs text-gray-500">
            {enabledModels.length} 个模型
          </span>
        )}
      </div>

      {/* 右侧：工具按钮 */}
      <div className="flex items-center gap-2">
        {/* Token用量和费用 */}
        {(totalTokens.input > 0 || totalTokens.output > 0) && (
          <div className="flex items-center gap-3 mr-2">
            <div className="text-xs text-gray-500">
              <span className="text-green-500">{formatTokenCount(totalTokens.input)}</span>
              {' / '}
              <span className="text-blue-500">{formatTokenCount(totalTokens.output)}</span>
              {' tokens'}
            </div>
            {totalCost > 0 && (
              <div className="text-xs font-medium text-amber-500 bg-amber-500/10 px-2 py-0.5 rounded">
                ≈ {formatCost(totalCost)}
              </div>
            )}
          </div>
        )}

        {/* 重置按钮 */}
        <button
          onClick={resetSession}
          className={cn(
            'p-2 rounded-lg',
            'hover:bg-gray-100 text-gray-500 hover:text-gray-900',
            'transition-colors'
          )}
          title="重置会话"
        >
          <RotateCcw className="w-5 h-5" />
        </button>

        {/* 导出按钮 */}
        <button
          onClick={handleExport}
          className={cn(
            'p-2 rounded-lg',
            'hover:bg-gray-100 text-gray-500 hover:text-gray-900',
            'transition-colors'
          )}
          title="导出辩论 (Ctrl+Shift+E)"
        >
          <Download className="w-5 h-5" />
        </button>

        {/* 设置按钮 */}
        <button
          onClick={() => setSettingsOpen(true)}
          className={cn(
            'p-2 rounded-lg',
            'hover:bg-gray-100 text-gray-500 hover:text-gray-900',
            'transition-colors'
          )}
          title="设置 (Ctrl+,)"
        >
          <Settings className="w-5 h-5" />
        </button>
      </div>
    </header>
  )
}
