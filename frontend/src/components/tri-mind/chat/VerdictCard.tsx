import { Download, Gavel, Loader2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useChatStore } from '@/stores/tri-mind/chatStore'
import { cn, formatTokenCount } from '@/lib/utils'

/**
 * 最终裁决卡片组件
 * 
 * 展示由主裁判模型生成的综合结论
 */
export function VerdictCard() {
  const { 
    verdictContent, 
    verdictUsage, 
    isVerdictGenerating,
  } = useChatStore()

  // 如果没有裁决内容，不显示
  if (!verdictContent && !isVerdictGenerating) {
    return null
  }

  const handleExportMarkdown = () => {
    if (!verdictContent) return
    const blob = new Blob([verdictContent], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'debate-verdict.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleExportJSON = () => {
    if (!verdictContent) return
    const blob = new Blob([JSON.stringify({ verdict: verdictContent }, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'debate-verdict.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="mx-4 mb-4">
      <div className={cn(
        'rounded-2xl border-2 overflow-hidden apple-card',
        'bg-gradient-to-br from-amber-50 to-orange-50',
        'border-amber-200/50 shadow-sm'
      )}>
        {/* 头部 */}
        <div className="flex items-center justify-between px-4 py-3 bg-amber-100/50 border-b border-amber-200/50">
          <div className="flex items-center gap-2">
            <Gavel className="w-5 h-5 text-amber-600" />
            <span className="font-semibold text-gray-900">最终裁决</span>
            {isVerdictGenerating && (
              <Loader2 className="w-4 h-4 animate-spin text-amber-600" />
            )}
          </div>
          
          {/* Token 用量 */}
          {verdictUsage && (
            <span className="text-xs text-gray-500">
              {formatTokenCount(verdictUsage.inputTokens)} / {formatTokenCount(verdictUsage.outputTokens)} tokens
            </span>
          )}
        </div>

        {/* 内容 */}
        <div className={cn(
          'p-4 markdown-body',
          isVerdictGenerating && 'cursor-blink'
        )}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {verdictContent || '正在生成裁决...'}
          </ReactMarkdown>
        </div>

        {/* 底部：导出按钮 */}
        {!isVerdictGenerating && verdictContent && (
          <div className="flex items-center gap-2 px-4 py-3 border-t border-amber-200/50 bg-amber-50/50">
            <span className="text-sm text-gray-500 mr-auto">导出辩论记录:</span>
            <button
              onClick={handleExportMarkdown}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-sm',
                'bg-white hover:bg-gray-100 transition-colors',
                'border border-gray-200 shadow-sm'
              )}
            >
              <Download className="w-4 h-4" />
              Markdown
            </button>
            <button
              onClick={handleExportJSON}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-sm',
                'bg-white hover:bg-gray-100 transition-colors',
                'border border-gray-200 shadow-sm'
              )}
            >
              <Download className="w-4 h-4" />
              JSON
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
