import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { User, Bot } from 'lucide-react'
import { cn } from '../../lib/utils'
import { CodeBlock } from './CodeBlock'

interface MessageBubbleProps {
  role: 'user' | 'assistant' | 'system' | 'verdict'
  content: string
  modelName?: string
  isStreaming?: boolean
}

export function MessageBubble({ role, content, modelName, isStreaming }: MessageBubbleProps) {
  const isUser = role === 'user'

  return (
    <div className={cn('flex gap-3', isUser ? 'flex-row-reverse' : 'flex-row')}>
      {/* 头像 */}
      <div
        className={cn(
          'w-8 h-8 rounded-full flex items-center justify-center shrink-0',
          isUser ? 'bg-gradient-to-tr from-blue-600 to-purple-500 shadow-md' : 'bg-gray-100'
        )}
      >
        {isUser ? (
          <User className="w-4 h-4 text-white" />
        ) : (
          <Bot className="w-4 h-4 text-gray-600" />
        )}
      </div>

      {/* 消息内容 */}
      <div
        className={cn(
          'flex-1 max-w-[85%] rounded-xl px-4 py-3 shadow-sm',
          isUser ? 'bg-gradient-to-r from-blue-600 to-purple-500 text-white' : 'bg-white border border-gray-200/50'
        )}
      >
        {/* 模型名称 */}
        {modelName && !isUser && (
          <p className="text-xs text-gray-500 mb-1">{modelName}</p>
        )}

        {/* Markdown渲染 */}
        <div className={cn('markdown-body', isStreaming && 'cursor-blink')}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              // 拦截 <pre> 标签，让 CodeBlock 自己处理外层样式
              pre({ children }) {
                return <>{children}</>
              },
              code({ className, children, node, ...props }) {
                const match = /language-(\w+)/.exec(className || '')
                const codeString = String(children).replace(/\n$/, '')
                
                // 判断是否为代码块：有语言标识 或 包含换行 或 父元素是 <pre>
                const isBlock = match || codeString.includes('\n') || 
                  (node?.position && codeString.length > 60)
                
                if (!isBlock) {
                  return (
                    <code
                      className="px-1.5 py-0.5 rounded bg-black/20 text-sm font-mono"
                      {...props}
                    >
                      {children}
                    </code>
                  )
                }

                return (
                  <CodeBlock
                    language={match?.[1] || 'text'}
                    code={codeString}
                  />
                )
              },
              // 自定义表格样式
              table({ children }) {
                return (
                  <div className="overflow-x-auto my-2">
                    <table className="min-w-full">{children}</table>
                  </div>
                )
              },
              // 自定义链接
              a({ href, children }) {
                return (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary underline hover:no-underline"
                  >
                    {children}
                  </a>
                )
              },
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  )
}
