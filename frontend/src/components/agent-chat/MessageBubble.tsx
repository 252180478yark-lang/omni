'use client'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { User2, Brain } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  role: 'user' | 'assistant'
  text: string
}

export function MessageBubble({ role, text }: Props) {
  const isUser = role === 'user'
  return (
    <div className={cn('flex gap-3 max-w-3xl', isUser ? 'flex-row-reverse self-end' : 'self-start')}>
      <div
        className={cn(
          'w-8 h-8 rounded-full flex items-center justify-center shrink-0',
          isUser ? 'bg-violet-100 text-violet-700' : 'bg-gradient-to-br from-violet-600 to-purple-500 text-white',
        )}
      >
        {isUser ? <User2 className="w-4 h-4" /> : <Brain className="w-4 h-4" />}
      </div>
      <div
        className={cn(
          'rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
          isUser
            ? 'bg-violet-600 text-white rounded-tr-sm prose-invert'
            : 'bg-white border border-gray-200 text-gray-900 rounded-tl-sm',
        )}
      >
        <div className="prose prose-sm max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        </div>
      </div>
    </div>
  )
}
