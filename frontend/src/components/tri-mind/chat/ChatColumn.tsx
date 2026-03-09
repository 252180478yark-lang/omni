import { useRef, useEffect } from 'react'
import { Loader2, CheckCircle, AlertCircle } from 'lucide-react'
import type { ModelConfig } from '@/lib/tri-mind/types'
import { MessageBubble } from './MessageBubble'
import { useChatStore } from '@/stores/tri-mind/chatStore'

interface ChatColumnProps {
  model: ModelConfig
  content: string
  status: 'idle' | 'generating' | 'completed' | 'error'
}

export function ChatColumn({ model, content, status }: ChatColumnProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const { nodes, tokenUsage, modelErrors } = useChatStore()

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [content])

  // 获取状态图标和颜色
  const StatusIcon = () => {
    switch (status) {
      case 'generating':
        return <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
      case 'completed':
        return <CheckCircle className="w-4 h-4 text-green-500" />
      case 'error':
        return <AlertCircle className="w-4 h-4 text-red-500" />
      default:
        return <div className="w-3 h-3 rounded-full bg-gray-500/40 ring-1 ring-gray-500/20" />
    }
  }

  // 获取该模型的Token用量
  const usage = tokenUsage.get(model.id)
  
  // 获取错误信息
  const errorMsg = modelErrors.get(model.id)

  // 获取用户消息
  const userMessages = Array.from(nodes.values()).filter(n => n.role === 'user')

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden bg-white">
      {/* 头部：模型名称和状态 */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200/50 bg-gray-50/80">
        <div className="flex items-center gap-2">
          <StatusIcon />
          <span className="text-sm font-medium text-gray-900">{model.name}</span>
        </div>
        {usage && (
          <span className="text-xs text-gray-500">
            {usage.inputTokens}/{usage.outputTokens} tokens
          </span>
        )}
      </div>

      {/* 消息区域 — 独立滚动，始终显示滚动条 */}
      <div ref={scrollRef} className="flex-1 overflow-y-scroll p-4 space-y-4 chat-scroll">
        {/* 用户消息（只显示有内容的） */}
        {userMessages
          .filter(node => node.content && node.content.trim().length > 0)
          .map((node) => (
            <MessageBubble
              key={node.id}
              role="user"
              content={node.content}
            />
          ))
        }

        {/* 模型响应 */}
        {content && content.trim().length > 0 && (
          <MessageBubble
            role="assistant"
            content={content}
            modelName={model.name}
            isStreaming={status === 'generating'}
          />
        )}

        {/* 错误状态 */}
        {status === 'error' && errorMsg && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4">
            <div className="flex items-start gap-2">
              <AlertCircle className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-red-500">调用失败</p>
                <p className="text-sm text-red-400 mt-1">{errorMsg}</p>
              </div>
            </div>
          </div>
        )}

        {/* 空状态 */}
        {userMessages.filter(n => n.content?.trim()).length === 0 && !content && status !== 'error' && (
          <div className="h-full flex items-center justify-center">
            <p className="text-sm text-gray-500">
              等待输入...
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
